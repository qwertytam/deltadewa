"""Tests for the option-chain and rate readings (9b).

The chain is a ~13 MB payload, so these pin what is specific to it: it is
cached raw and parsed on read, the previous night's copy is kept, a payload
that does not parse never replaces a good cache entry, the write is atomic,
and a read-only app does not decode it again on every page render.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from deltadewa.marketdata import (
    CboeFredProvider,
    MarketDataError,
    MarketDataUnavailableError,
    Source,
    StaticProvider,
)
from deltadewa.marketdata import cboe_fred_provider as provider_module
from deltadewa.marketdata.chain import parse_cboe_chain
from tests.chain_builders import SESSION, standard_chain

_DGS_CSV = (
    "observation_date,DGS1\n2026-11-11,.\n2026-11-12,4.55\n2026-11-13,4.60\n"
)


def _chain_response(payload: object) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    return response


def _csv_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    response.raise_for_status = MagicMock()
    return response


def _session(payload: object | None = None) -> MagicMock:
    session = MagicMock(spec=requests.Session)
    session.get.return_value = _chain_response(
        payload if payload is not None else standard_chain(),
    )
    return session


class TestOptionChain:
    """CboeFredProvider.get_option_chain."""

    def test_live_fetch_parses_dates_and_caches_the_raw_payload(
        self,
        tmp_path: Path,
    ) -> None:
        session = _session()
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        observation = provider.get_option_chain("SPX")

        assert observation.source is Source.LIVE
        assert observation.value.session_date == SESSION
        assert observation.as_of == datetime(
            2026, 11, 17, 1, 33, 27, tzinfo=UTC
        )
        assert observation.fetched_at is not None
        cached = json.loads((tmp_path / "chain_SPX.json").read_text())
        assert cached["value"]["data"]["current_price"] == pytest.approx(5000.0)
        assert (
            "https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json"
            in (session.get.call_args.args[0])
        )

    def test_the_chain_gets_a_longer_timeout_than_a_csv(
        self,
        tmp_path: Path,
    ) -> None:
        session = _session()

        CboeFredProvider(cache_dir=tmp_path, session=session).get_option_chain(
            "SPX",
        )

        assert session.get.call_args.kwargs["timeout"] > 10

    def test_a_fresh_cache_entry_avoids_a_second_download(
        self,
        tmp_path: Path,
    ) -> None:
        session = _session()
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        provider.get_option_chain("SPX")
        second = provider.get_option_chain("SPX")

        assert session.get.call_count == 1
        assert second.source is Source.CACHED

    def test_the_previous_payload_is_kept_beside_the_new_one(
        self,
        tmp_path: Path,
    ) -> None:
        first = standard_chain(spot=5000.0)
        second = standard_chain(spot=5100.0)
        session = _session(first)
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            session=session,
            force_fetch=True,
        )
        provider.get_option_chain("SPX")
        session.get.return_value = _chain_response(second)

        provider.get_option_chain("SPX")

        current = json.loads((tmp_path / "chain_SPX.json").read_text())
        previous = json.loads((tmp_path / "chain_SPX.prev.json").read_text())
        assert current["value"]["data"]["current_price"] == pytest.approx(
            5100.0
        )
        assert previous["value"]["data"]["current_price"] == pytest.approx(
            5000.0,
        )

    def test_no_temporary_file_is_left_behind(self, tmp_path: Path) -> None:
        CboeFredProvider(
            cache_dir=tmp_path, session=_session()
        ).get_option_chain(
            "SPX",
        )

        assert sorted(p.name for p in tmp_path.iterdir()) == ["chain_SPX.json"]

    def test_an_unparseable_payload_never_replaces_a_good_cache_entry(
        self,
        tmp_path: Path,
    ) -> None:
        session = _session()
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            session=session,
            force_fetch=True,
        )
        provider.get_option_chain("SPX")
        before = (tmp_path / "chain_SPX.json").read_text()
        broken = deepcopy(standard_chain())
        broken["data"].pop("current_price")
        session.get.return_value = _chain_response(broken)

        observation = provider.get_option_chain("SPX")

        assert observation.source is Source.STALE
        assert observation.value.spot == pytest.approx(5000.0)
        assert (tmp_path / "chain_SPX.json").read_text() == before

    def test_an_unparseable_payload_with_no_cache_raises_market_data_error(
        self,
        tmp_path: Path,
    ) -> None:
        broken = deepcopy(standard_chain())
        broken["data"]["options"] = []
        provider = CboeFredProvider(
            cache_dir=tmp_path, session=_session(broken)
        )

        with pytest.raises(MarketDataError):
            provider.get_option_chain("SPX")

        assert not (tmp_path / "chain_SPX.json").exists()

    def test_a_response_that_is_not_json_falls_back_to_the_cache(
        self,
        tmp_path: Path,
    ) -> None:
        session = _session()
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            session=session,
            force_fetch=True,
        )
        provider.get_option_chain("SPX")
        html = _chain_response(None)
        html.json.side_effect = ValueError("not json")
        session.get.return_value = html

        observation = provider.get_option_chain("SPX")

        assert observation.source is Source.STALE

    def test_a_network_failure_falls_back_to_the_stale_chain(
        self,
        tmp_path: Path,
    ) -> None:
        session = _session()
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            ttl=timedelta(seconds=0),
            session=session,
        )
        provider.get_option_chain("SPX")
        session.get.side_effect = requests.ConnectionError("offline")

        observation = provider.get_option_chain("SPX")

        assert observation.source is Source.STALE
        assert observation.value.session_date == SESSION

    def test_no_cache_and_no_network_raises(self, tmp_path: Path) -> None:
        session = MagicMock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError("offline")
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        with pytest.raises(MarketDataError):
            provider.get_option_chain("SPX")

    def test_only_spx_is_supported(self, tmp_path: Path) -> None:
        session = _session()
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        with pytest.raises(MarketDataError, match="SPX only"):
            provider.get_option_chain("NDX")

        session.get.assert_not_called()

    def test_a_write_that_fails_part_way_leaves_the_old_entry_readable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        session = _session()
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            session=session,
            force_fetch=True,
        )
        provider.get_option_chain("SPX")
        before = (tmp_path / "chain_SPX.json").read_text()
        session.get.return_value = _chain_response(standard_chain(spot=5100.0))
        real_replace = Path.replace

        def failing_replace(self: Path, target: Path) -> Path:
            if Path(target).name == "chain_SPX.json":
                raise OSError("disk full")
            return real_replace(self, target)

        monkeypatch.setattr(Path, "replace", failing_replace)

        with pytest.raises(OSError, match="disk full"):
            provider.get_option_chain("SPX")

        monkeypatch.undo()
        assert (tmp_path / "chain_SPX.json").read_text() == before
        assert not list(tmp_path.glob("*.tmp"))


class TestReadOnlyChain:
    """The app's read-only provider reads what the job wrote."""

    def _write(self, tmp_path: Path) -> None:
        CboeFredProvider(
            cache_dir=tmp_path,
            session=_session(),
            force_fetch=True,
        ).get_option_chain("SPX")

    def test_reads_a_warm_cache_without_a_network(self, tmp_path: Path) -> None:
        self._write(tmp_path)
        session = MagicMock(spec=requests.Session)
        reader = CboeFredProvider(
            cache_dir=tmp_path,
            session=session,
            read_only=True,
        )

        observation = reader.get_option_chain("SPX")

        assert observation.source is Source.CACHED
        assert observation.value.session_date == SESSION
        session.get.assert_not_called()

    def test_a_cache_past_its_ttl_reads_stale_never_fails(
        self,
        tmp_path: Path,
    ) -> None:
        self._write(tmp_path)
        reader = CboeFredProvider(
            cache_dir=tmp_path,
            ttl=timedelta(seconds=0),
            read_only=True,
        )

        assert reader.get_option_chain("SPX").source is Source.STALE

    def test_a_cold_cache_raises_market_data_error(
        self, tmp_path: Path
    ) -> None:
        reader = CboeFredProvider(cache_dir=tmp_path, read_only=True)

        with pytest.raises(MarketDataError):
            reader.get_option_chain("SPX")

    def test_the_parse_is_not_repeated_while_the_file_is_unchanged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        self._write(tmp_path)
        calls: list[int] = []

        def counting(payload):
            calls.append(1)
            return parse_cboe_chain(payload)

        monkeypatch.setattr(provider_module, "parse_cboe_chain", counting)
        reader = CboeFredProvider(cache_dir=tmp_path, read_only=True)

        first = reader.get_option_chain("SPX")
        second = reader.get_option_chain("SPX")

        assert len(calls) == 1
        assert second.value is first.value
        assert second.source is Source.CACHED

    def test_a_new_file_is_parsed_again(
        self,
        tmp_path: Path,
    ) -> None:
        self._write(tmp_path)
        reader = CboeFredProvider(cache_dir=tmp_path, read_only=True)
        assert reader.get_option_chain("SPX").value.spot == pytest.approx(
            5000.0
        )
        CboeFredProvider(
            cache_dir=tmp_path,
            session=_session(standard_chain(spot=5100.0)),
            force_fetch=True,
        ).get_option_chain("SPX")

        assert reader.get_option_chain("SPX").value.spot == pytest.approx(
            5100.0
        )


class TestRate:
    """CboeFredProvider.get_rate."""

    def test_returns_the_latest_yield_in_percent_skipping_gaps(
        self,
        tmp_path: Path,
    ) -> None:
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _csv_response(_DGS_CSV)
        provider = CboeFredProvider(cache_dir=tmp_path, session=session)

        observation = provider.get_rate("DGS1")

        assert observation.value == pytest.approx(4.60)
        assert observation.as_of == datetime(2026, 11, 13, tzinfo=UTC)
        assert observation.source is Source.LIVE
        assert "id=DGS1" in session.get.call_args.args[0]
        assert (tmp_path / "rate_DGS1.json").exists()

    def test_falls_back_to_the_stale_cache(self, tmp_path: Path) -> None:
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _csv_response(_DGS_CSV)
        provider = CboeFredProvider(
            cache_dir=tmp_path,
            ttl=timedelta(seconds=0),
            session=session,
        )
        provider.get_rate("DGS1")
        session.get.side_effect = requests.ConnectionError("offline")

        observation = provider.get_rate("DGS1")

        assert observation.source is Source.STALE
        assert observation.value == pytest.approx(4.60)


class TestStaticProvider:
    """StaticProvider serves registered rates and chains, deterministically."""

    def test_rate_and_chain_are_static_observations(self) -> None:
        chain = parse_cboe_chain(standard_chain())
        provider = StaticProvider(rates={"DGS1": 4.6}, chains={"SPX": chain})

        rate = provider.get_rate("DGS1")
        observed = provider.get_option_chain("SPX")

        assert rate.value == pytest.approx(4.6)
        assert rate.source is Source.STATIC
        assert observed.value is chain
        assert observed.source is Source.STATIC

    def test_unregistered_series_and_underlying_raise(self) -> None:
        provider = StaticProvider()

        with pytest.raises(MarketDataUnavailableError):
            provider.get_rate("DGS1")
        with pytest.raises(MarketDataUnavailableError):
            provider.get_option_chain("SPX")
