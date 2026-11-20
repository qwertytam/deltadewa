"""/health's ``market_data.feed``: the 9b feed series, listed not counted.

The option chain and the policy's FRED rate are reported beside the
environment's four series, never inside them. ``market_data.series`` (and
with it ``oldest_series``, the banner and ``status``) is the reduction
``assess_market_environment`` builds, so a series added there would count at
once. Nothing is priced on the feed yet, so a missing or stale chain must
not degrade ``/health`` for an input nothing reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deltadewa.app.factory import create_app
from deltadewa.marketdata import StaticProvider, write_cache_manifest
from deltadewa.marketdata.chain import parse_cboe_chain
from tests.chain_builders import standard_chain
from tests.test_app.freshness_fixtures import cached_provider
from tests.test_app.test_health import (
    _fully_wired_state,
    _provider,
    _state,
    _write_matching_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolated_cache_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-test cache dir, as ``test_health`` does (#309's write probe)."""
    monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))


_UNAVAILABLE = {"quality": "UNAVAILABLE", "as_of": None, "fetched_at": None}


def _health(app) -> dict:
    return app.server.test_client().get("/health").get_json()


class TestFeedSeries:
    """What /health says about the chain and the rate."""

    def test_both_series_are_listed_when_the_policy_has_a_feed(
        self,
        tmp_path: Path,
    ) -> None:
        provider = cached_provider(
            rates={"DGS1": 4.6},
            chains={"SPX": parse_cboe_chain(standard_chain())},
        )
        state = _fully_wired_state(tmp_path)
        app = create_app(
            state=state,
            market_data=provider,
            ips_config=state.ips_config,
        )

        feed = _health(app)["market_data"]["feed"]

        assert set(feed) == {"chain", "rate"}
        assert feed["chain"]["quality"] == "STATIC"
        assert feed["rate"]["quality"] == "STATIC"

    def test_they_are_not_in_the_environments_series(
        self,
        tmp_path: Path,
    ) -> None:
        state = _fully_wired_state(tmp_path)
        app = create_app(
            state=state,
            market_data=cached_provider(),
            ips_config=state.ips_config,
        )

        series = _health(app)["market_data"]["series"]

        assert set(series) == {
            "vix",
            "vix_term_structure",
            "skew_index",
            "skew_percentile",
        }

    def test_a_series_nothing_has_cached_reads_unavailable_not_an_error(
        self,
        tmp_path: Path,
    ) -> None:
        state = _fully_wired_state(tmp_path)
        app = create_app(
            state=state,
            market_data=cached_provider(),
            ips_config=state.ips_config,
        )

        payload = _health(app)

        assert payload["market_data"]["feed"] == {
            "chain": {
                "quality": "UNAVAILABLE",
                "as_of": None,
                "fetched_at": None,
                "adopted": False,
            },
            "rate": {
                "quality": "UNAVAILABLE",
                "as_of": None,
                "fetched_at": None,
                "adopted": False,
            },
        }
        assert payload["provenance_error"] is None

    def test_a_missing_chain_does_not_degrade_status(
        self,
        tmp_path: Path,
    ) -> None:
        """Listed, not counted: no input adopts it (the example's adopt: [])."""
        _write_matching_manifest(tmp_path)
        state = _fully_wired_state(tmp_path)
        app = create_app(
            state=state,
            market_data=cached_provider(),
            ips_config=state.ips_config,
        )

        payload = _health(app)

        assert (
            payload["market_data"]["feed"]["chain"]["quality"] == "UNAVAILABLE"
        )
        assert payload["status"] == "ok"
        assert payload["freshness_reason"] is None

    def test_a_code_fault_reads_error_and_is_logged_not_unavailable(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An empty cache and a bug must not look the same."""

        class Faulty(StaticProvider):
            def get_option_chain(self, underlying: str):
                raise RuntimeError("parser bug")

        state = _fully_wired_state(tmp_path)
        app = create_app(
            state=state,
            market_data=Faulty(spot_prices={"SPX": 5000.0}, vix=18.0),
            ips_config=state.ips_config,
        )

        with caplog.at_level("ERROR"):
            payload = _health(app)

        assert payload["market_data"]["feed"]["chain"]["quality"] == "ERROR"
        assert (
            payload["market_data"]["feed"]["rate"]["quality"] == "UNAVAILABLE"
        )
        assert "parser bug" in caplog.text
        assert payload["provenance_error"] is None

    def test_no_policy_section_means_no_feed_object(
        self,
        tmp_path: Path,
    ) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())

        assert _health(app)["market_data"]["feed"] is None

    def test_the_timestamps_of_a_cached_chain_are_reported(
        self,
        tmp_path: Path,
    ) -> None:
        """Through a real read-only provider over a warm cache."""
        from unittest.mock import MagicMock

        import requests

        from deltadewa.marketdata import CboeFredProvider
        from tests.chain_builders import standard_chain as chain_payload

        cache = tmp_path / "cache"
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = chain_payload()
        session = MagicMock(spec=requests.Session)
        session.get.return_value = response
        CboeFredProvider(
            cache_dir=cache,
            session=session,
            force_fetch=True,
        ).get_option_chain("SPX")
        write_cache_manifest(cache, {})
        reader = CboeFredProvider(cache_dir=cache, read_only=True)
        state = _fully_wired_state(tmp_path)
        app = create_app(
            state=state,
            market_data=reader,
            ips_config=state.ips_config,
        )

        feed = _health(app)["market_data"]["feed"]

        assert feed["chain"]["quality"] in {"CACHED", "STALE"}
        assert feed["chain"]["as_of"].startswith("2026-11-17T01:33:27")
        assert feed["chain"]["fetched_at"] is not None
        assert feed["rate"]["quality"] == "UNAVAILABLE"
