"""Tests for deltadewa.marketdata.refresh."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

import pytest
import requests

from deltadewa.marketdata import CboeFredProvider, Source
from deltadewa.marketdata import refresh as refresh_module
from deltadewa.marketdata.refresh import main, refresh_all

# Reuses the CSV fixtures' shape from test_cboe_fred_provider.py — kept
# local (rather than imported) since dispatch-by-URL below needs a
# multi-row SKEW series for the percentile call, distinct from that
# module's single-row default.
_SPX_CSV = "DATE,SPX\n06/15/2026,5000.0\n"
_VIX_CSV = "DATE,OPEN,HIGH,LOW,CLOSE\n06/15/2026,16.0,16.5,15.5,16.5\n"
_SKEW_CSV = (
    "DATE,SKEW\n"
    + "\n".join(f"{(i % 12) + 1:02d}/01/2026,{120.0 + i}" for i in range(10))
    + "\n"
)
_VIXCLS_CSV = (
    "observation_date,VIXCLS\n"
    + "\n".join(f"2026-{(i % 12) + 1:02d}-01,{12.0 + i}" for i in range(10))
    + "\n"
)


def _mock_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.raise_for_status = MagicMock()
    return response


def _dispatching_session(
    *,
    fail_url_substrings: frozenset[str] = frozenset(),
) -> MagicMock:
    """Fake ``requests.Session`` serving a distinct canned CSV per series.

    A single ``return_value`` (as the provider's own test module uses)
    can't cover a whole refresh run: SPX/SKEW/VIX-family/VIXCLS each need
    their own column layout. *fail_url_substrings* names request-URL
    substrings that should raise ``ConnectionError`` instead — e.g.
    ``{"VIXCLS"}`` fails only the FRED-sourced VIX series, leaving the
    CBOE-sourced ones (term structure, SKEW, spot) to succeed, for
    partial-failure tests.
    """

    def _get(url: str, timeout: int) -> MagicMock:
        for needle in fail_url_substrings:
            if needle in url:
                raise requests.ConnectionError(f"offline: {needle}")
        if "fred.stlouisfed.org" in urlparse(url).netloc:
            return _mock_response(_VIXCLS_CSV)
        if "SPX_History.csv" in url:
            return _mock_response(_SPX_CSV)
        if "SKEW_History.csv" in url:
            return _mock_response(_SKEW_CSV)
        return _mock_response(_VIX_CSV)  # VIX9D/VIX/VIX3M/VIX6M/VIX1Y legs

    session = MagicMock(spec=requests.Session)
    session.get.side_effect = _get
    return session


class TestRefreshAll:
    """refresh_all() — independent per-series fetch, partial-failure-safe."""

    def test_all_succeed_writes_cache_the_app_reads_as_cached(
        self,
        tmp_path: Path,
    ) -> None:
        """A clean successful run leaves every series CACHED for a reader."""
        writer = CboeFredProvider(
            cache_dir=tmp_path,
            session=_dispatching_session(),
        )

        succeeded, total = refresh_all(writer, "SPX")

        assert (succeeded, total) == (6, 6)
        # A second, independent read-only-style provider sharing the same
        # cache dir must see everything as CACHED, not LIVE (this process
        # didn't fetch) and not STALE (the write just happened).
        reader = CboeFredProvider(
            cache_dir=tmp_path,
            session=MagicMock(spec=requests.Session),
        )
        assert reader.get_spot("SPX").source is Source.CACHED
        assert reader.get_vix().source is Source.CACHED
        assert reader.get_skew_index().source is Source.CACHED

    def test_total_failure_returns_zero_succeeded(self, tmp_path: Path) -> None:
        """Every series failing is reported, not raised."""
        session = MagicMock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError("offline")
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        succeeded, total = refresh_all(provider, "SPX")

        assert (succeeded, total) == (0, 6)
        assert list(tmp_path.iterdir()) == []

    def test_partial_failure_keeps_successes_and_reports_failures(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """VIXCLS down, CBOE up: vix + vix_history fail, four others don't."""
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            session=_dispatching_session(
                fail_url_substrings=frozenset({"VIXCLS"})
            ),
        )

        with caplog.at_level(logging.WARNING):
            succeeded, total = refresh_all(provider, "SPX")

        assert (succeeded, total) == (4, 6)
        assert "vix: FAILED" in caplog.text
        assert "vix_history: FAILED" in caplog.text
        # The successful series are still on disk.
        assert (tmp_path / "spot_SPX.json").exists()
        assert (tmp_path / "spot_SKEW.json").exists()

    def test_failed_series_does_not_poison_a_prior_cache_entry(
        self,
        tmp_path: Path,
    ) -> None:
        """A live-fetch failure with a prior entry serves STALE, not blank.

        ``ttl=0`` forces every call past the fresh-cache check into an
        actual (fake) network attempt, rather than a cache hit that would
        never exercise the failure path at all. ``_DiskCache.set()`` is
        only called on success, so the losing attempt must leave the prior
        entry byte-for-byte untouched instead of blanking or poisoning it.
        """
        warm = CboeFredProvider(
            cache_dir=tmp_path,
            ttl=timedelta(seconds=0),
            session=_dispatching_session(),
        )
        refresh_all(warm, "SPX")
        before = (tmp_path / "vix_fred.json").read_text()

        cold = CboeFredProvider(
            cache_dir=tmp_path,
            ttl=timedelta(seconds=0),
            session=_dispatching_session(
                fail_url_substrings=frozenset({"VIXCLS"})
            ),
        )
        refresh_all(cold, "SPX")

        after = (tmp_path / "vix_fred.json").read_text()
        assert after == before
        assert json.loads(after)["value"]  # sanity: not an empty payload
        # The series itself still answers — degraded to STALE, not blank.
        reader = CboeFredProvider(
            cache_dir=tmp_path,
            ttl=timedelta(seconds=0),
            session=_dispatching_session(
                fail_url_substrings=frozenset({"VIXCLS"})
            ),
        )
        stale = reader.get_vix()
        assert stale.source is Source.STALE
        assert stale.value == pytest.approx(21.0, rel=1e-6)


class TestMain:
    """main() — CLI wiring: exit codes and provider construction."""

    def test_exit_code_zero_on_full_success(self, tmp_path: Path) -> None:
        """All-series success is exit 0."""
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            session=_dispatching_session(),
        )
        with patch.object(
            refresh_module,
            "CboeFredProvider",
            return_value=provider,
        ):
            exit_code = main(["--cache-dir", str(tmp_path)])

        assert exit_code == 0

    def test_exit_code_two_on_total_failure(self, tmp_path: Path) -> None:
        """Every series failing is exit 2."""
        session = MagicMock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError("offline")
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)
        with patch.object(
            refresh_module,
            "CboeFredProvider",
            return_value=provider,
        ):
            exit_code = main(["--cache-dir", str(tmp_path)])

        assert exit_code == 2

    def test_exit_code_one_on_partial_failure(self, tmp_path: Path) -> None:
        """Some-but-not-all series failing is exit 1, not 0 or 2."""
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            session=_dispatching_session(
                fail_url_substrings=frozenset({"VIXCLS"})
            ),
        )
        with patch.object(
            refresh_module,
            "CboeFredProvider",
            return_value=provider,
        ):
            exit_code = main(["--cache-dir", str(tmp_path)])

        assert exit_code == 1

    def test_constructs_provider_not_read_only(self, tmp_path: Path) -> None:
        """The refresh job's provider must be the one allowed to fetch."""
        with patch.object(refresh_module, "CboeFredProvider") as mock_provider:
            main(
                [
                    "--cache-dir",
                    str(tmp_path),
                    "--ips-path",
                    str(tmp_path / "does-not-exist-ips.yaml"),
                ],
            )

        mock_provider.assert_called_once()
        _, kwargs = mock_provider.call_args
        assert kwargs["read_only"] is False
        assert kwargs["cache_dir"] == tmp_path

    def test_missing_ips_path_falls_back_to_default_ttl(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A missing --ips-path warns and still runs, never raises."""
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            session=_dispatching_session(),
        )
        with (
            patch.object(
                refresh_module,
                "CboeFredProvider",
                return_value=provider,
            ),
            caplog.at_level(logging.WARNING),
        ):
            exit_code = main(
                [
                    "--cache-dir",
                    str(tmp_path),
                    "--ips-path",
                    str(tmp_path / "does-not-exist-ips.yaml"),
                ],
            )

        assert exit_code == 0
        assert "unavailable" in caplog.text
