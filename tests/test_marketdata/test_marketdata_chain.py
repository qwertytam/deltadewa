"""MarketData.app as the chain source (9b, ``chain_source: marketdata``).

Synthetic responses only (``tests/marketdata_builders``): the contracts are
priced by this repo's own engine; no network, no vendor payload.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
import requests

from deltadewa.constants import OptionType
from deltadewa.ips_config import ChainSource, load_ips_config
from deltadewa.marketdata import (
    CboeFredProvider,
    MarketDataError,
    Source,
    read_only_provider_for,
)
from deltadewa.marketdata import refresh as refresh_module
from deltadewa.marketdata.chain import parse_cboe_chain
from deltadewa.marketdata.marketdata_chain import (
    fetch_marketdata_chain,
    latest_closed_session,
    marketdata_session_date,
    parse_marketdata_chain,
)
from deltadewa.marketdata.refresh import main
from tests.chain_builders import DECEMBER, SESSION, SPOT, standard_chain
from tests.marketdata_builders import close_stamp, md_payload, md_response
from tests.test_marketdata.test_refresh import (
    _dispatching_session as _csv_dispatching_session,
)
from tests.test_marketdata.test_refresh import _factory

_NEW_YORK = ZoneInfo("America/New_York")
_EXAMPLE_IPS = Path(__file__).parents[2] / "config" / "ips.example.yaml"
_TOKEN = "test-token-not-a-secret"  # ruff: ignore[hardcoded-password-string]


def _ny(
    year: int, month: int, day: int, hour: int, minute: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=_NEW_YORK)


def _response(status: int, body: object) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.json.return_value = body
    return response


def _dated_session(
    *,
    latest: date | None = None,
    status_for: dict[str, int] | None = None,
) -> MagicMock:
    """A fake session answering each dated request with that session's chain.

    *latest*, when set, refuses any later date the way the vendor does (402,
    naming the latest it serves). *status_for* forces a status per date.
    """
    session = MagicMock(spec=requests.Session)

    def get(url: str, **kwargs: Any) -> MagicMock:
        del url
        day = date.fromisoformat(kwargs["params"]["date"])
        forced = (status_for or {}).get(day.isoformat())
        if forced is not None:
            return _response(forced, {"s": "error", "errmsg": "forced"})
        if latest is not None and day > latest:
            return _response(
                402,
                {
                    "s": "error",
                    "errmsg": (
                        "Your plan can only access fully-closed sessions; "
                        f"the latest available is {latest.isoformat()}."
                    ),
                },
            )
        return _response(203, md_response(session=day))

    session.get.side_effect = get
    return session


class TestLatestClosedSession:
    """A session is served from 09:30 New York on the next trading day."""

    @pytest.mark.parametrize(
        ("now", "expected"),
        [
            (_ny(2026, 11, 21, 12), date(2026, 11, 19)),  # Saturday
            (_ny(2026, 11, 20, 21, 30), date(2026, 11, 19)),  # Friday night
            (_ny(2026, 11, 23, 9, 29), date(2026, 11, 19)),  # Monday, pre-open
            (_ny(2026, 11, 23, 9, 30), date(2026, 11, 20)),  # Monday, release
            (_ny(2026, 11, 24, 10), date(2026, 11, 23)),
            (_ny(2026, 11, 26, 10), date(2026, 11, 24)),  # Thanksgiving
            (_ny(2026, 11, 27, 10), date(2026, 11, 25)),  # the day after
        ],
    )
    def test_the_session_served_at_each_instant(
        self,
        now: datetime,
        expected: date,
    ) -> None:
        assert latest_closed_session(now) == expected

    def test_the_same_instant_in_utc_gives_the_same_answer(self) -> None:
        now = _ny(2026, 11, 23, 9, 30)

        assert latest_closed_session(now.astimezone(UTC)) == date(2026, 11, 20)

    def test_a_naive_instant_is_refused(self) -> None:
        with pytest.raises(ValueError, match="aware"):
            latest_closed_session(datetime(2026, 11, 23, 10))


class TestParse:
    """A dated response becomes the same snapshot a Cboe payload would."""

    def test_the_same_contracts_as_the_cboe_parse_of_the_same_chain(
        self,
    ) -> None:
        cboe = standard_chain()

        snapshot = parse_marketdata_chain(md_payload(md_response(cboe)))

        expected = parse_cboe_chain(cboe)
        assert {q.symbol for q in snapshot.quotes} == {
            q.symbol for q in expected.quotes
        }
        assert all(q.root in {"SPX", "SPXW"} for q in snapshot.quotes)

    def test_spot_session_and_quote_time_come_from_the_response(self) -> None:
        snapshot = parse_marketdata_chain(md_payload())

        assert snapshot.spot == pytest.approx(SPOT)
        assert snapshot.session_date == SESSION
        assert snapshot.quoted_at == datetime.fromtimestamp(
            close_stamp(SESSION),
            tz=UTC,
        )
        assert snapshot.quoted_at.tzinfo is not None

    def test_no_vendor_iv_is_none_and_the_quote_still_solves(self) -> None:
        snapshot = parse_marketdata_chain(md_payload())

        assert all(q.vendor_iv is None for q in snapshot.quotes)
        match = snapshot.match(
            expiry=DECEMBER,
            option_type=OptionType.PUT,
            strike=4000.0,
            max_spread_pct=25.0,
        )
        assert match.quote is not None
        assert not match.flags
        assert match.quote.bid > 0.0
        assert match.quote.open_interest is not None

    def test_the_session_is_read_back_from_the_payload(self) -> None:
        assert marketdata_session_date(md_payload()) == SESSION
        assert marketdata_session_date({"session_date": "bad"}) is None
        assert marketdata_session_date({}) is None

    @pytest.mark.parametrize(
        ("mutate", "match"),
        [
            (lambda p: p.update(source="cboe"), "not a MarketData"),
            (lambda p: p["response"].pop("bid"), "bid"),
            (lambda p: p["response"]["ask"].pop(), "length"),
            (
                lambda p: p["response"]["bid"].__setitem__(0, "x"),
                "not a number",
            ),
            (
                lambda p: p["response"]["bid"].__setitem__(0, float("inf")),
                "not finite",
            ),
            (
                lambda p: p["response"].update(
                    underlyingPrice=[0.0] * len(p["response"]["bid"]),
                ),
                "index level",
            ),
            (
                lambda p: p["response"].update(
                    updated=[close_stamp(date(2026, 11, 13))]
                    * len(p["response"]["bid"]),
                ),
                "carries quotes from",
            ),
            (lambda p: p.pop("session_date"), "unreadable"),
        ],
    )
    def test_a_malformed_payload_is_a_market_data_error(
        self,
        mutate: Any,
        match: str,
    ) -> None:
        payload = md_payload()
        mutate(payload)

        with pytest.raises(MarketDataError, match=match):
            parse_marketdata_chain(payload)

    def test_no_contracts_is_an_error(self) -> None:
        empty = {
            "s": "ok",
            "optionSymbol": [],
            "bid": [],
            "ask": [],
            "underlyingPrice": [],
        }

        with pytest.raises(MarketDataError, match="contracts"):
            parse_marketdata_chain(md_payload(empty))


class TestFetch:
    """One dated request; the token only ever in the header."""

    _MONDAY_10 = _ny(2026, 11, 23, 10)

    def test_asks_for_the_whole_chain_of_the_last_closed_session(self) -> None:
        session = _dated_session()

        payload = fetch_marketdata_chain(
            session,
            token=_TOKEN,
            underlying="SPX",
            now=self._MONDAY_10,
        )

        call = session.get.call_args
        assert call.kwargs["params"] == {
            "date": "2026-11-20",
            "expiration": "all",
        }
        assert call.kwargs["headers"]["Authorization"] == f"Bearer {_TOKEN}"
        assert _TOKEN not in call.args[0]
        assert payload["session_date"] == "2026-11-20"
        assert parse_marketdata_chain(payload).session_date == date(
            2026,
            11,
            20,
        )

    def test_a_late_release_falls_back_once_to_the_latest_served(
        self,
    ) -> None:
        session = _dated_session(latest=date(2026, 11, 19))

        payload = fetch_marketdata_chain(
            session,
            token=_TOKEN,
            underlying="SPX",
            now=self._MONDAY_10,
        )

        assert payload["session_date"] == "2026-11-19"
        assert session.get.call_count == 2

    def test_no_token_fails_before_any_request(self) -> None:
        session = _dated_session()

        with pytest.raises(MarketDataError, match="MARKETDATA_TOKEN"):
            fetch_marketdata_chain(
                session,
                token=None,
                underlying="SPX",
                now=self._MONDAY_10,
            )
        session.get.assert_not_called()

    @pytest.mark.parametrize("status", [401, 402, 403, 429, 500])
    def test_an_error_status_is_a_market_data_error_without_the_token(
        self,
        status: int,
    ) -> None:
        session = _dated_session(status_for={"2026-11-20": status})

        with pytest.raises(MarketDataError, match=str(status)) as raised:
            fetch_marketdata_chain(
                session,
                token=_TOKEN,
                underlying="SPX",
                now=self._MONDAY_10,
            )
        assert _TOKEN not in str(raised.value)

    def test_a_transport_failure_never_carries_the_request(self) -> None:
        session = MagicMock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError(
            f"https://example.invalid/?token={_TOKEN}",
        )

        with pytest.raises(MarketDataError, match="ConnectionError") as raised:
            fetch_marketdata_chain(
                session,
                token=_TOKEN,
                underlying="SPX",
                now=self._MONDAY_10,
            )
        assert _TOKEN not in str(raised.value)

    def test_no_data_is_an_error(self) -> None:
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _response(200, {"s": "no_data"})

        with pytest.raises(MarketDataError, match="no_data"):
            fetch_marketdata_chain(
                session,
                token=_TOKEN,
                underlying="SPX",
                now=self._MONDAY_10,
            )


class TestProvider:
    """The provider fetches, caches and reads per chain source."""

    def _writer(self, tmp_path: Path, session: MagicMock) -> CboeFredProvider:
        return CboeFredProvider(
            cache_dir=tmp_path,
            session=session,
            force_fetch=True,
            chain_source=ChainSource.MARKETDATA,
            marketdata_token=_TOKEN,
        )

    def test_a_live_fetch_caches_under_its_own_key(
        self,
        tmp_path: Path,
    ) -> None:
        observation = self._writer(tmp_path, _dated_session()).get_option_chain(
            "SPX",
        )

        assert observation.source is Source.LIVE
        assert (tmp_path / "mdchain_SPX.json").exists()
        assert not (tmp_path / "chain_SPX.json").exists()
        cached = json.loads((tmp_path / "mdchain_SPX.json").read_text())
        assert cached["value"]["session_date"] == (
            observation.value.session_date.isoformat()
        )

    def test_a_read_only_reader_of_the_same_source_reads_it(
        self,
        tmp_path: Path,
    ) -> None:
        written = self._writer(tmp_path, _dated_session()).get_option_chain(
            "SPX",
        )
        reader = CboeFredProvider(
            cache_dir=tmp_path,
            read_only=True,
            chain_source=ChainSource.MARKETDATA,
        )

        read = reader.get_option_chain("SPX")

        assert read.value.session_date == written.value.session_date
        assert read.source in {Source.CACHED, Source.STALE}

    def test_another_sources_reader_never_sees_it(
        self,
        tmp_path: Path,
    ) -> None:
        self._writer(tmp_path, _dated_session()).get_option_chain("SPX")

        for source in (ChainSource.CBOE, ChainSource.NONE):
            reader = CboeFredProvider(
                cache_dir=tmp_path,
                read_only=True,
                chain_source=source,
            )
            with pytest.raises(MarketDataError):
                reader.get_option_chain("SPX")

    def test_prev_keeps_the_previous_session_only(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / "mdchain_SPX.json").write_text(
            json.dumps(
                {
                    "value": md_payload(session=date(2026, 11, 13)),
                    "fetched_at": "2026-11-16T15:00:00+00:00",
                },
            ),
        )
        writer = self._writer(tmp_path, _dated_session())

        writer.get_option_chain("SPX")
        writer.get_option_chain("SPX")  # the same session again

        previous = json.loads((tmp_path / "mdchain_SPX.prev.json").read_text())
        assert previous["value"]["session_date"] == "2026-11-13"

    def test_a_missing_token_is_a_failed_fetch_not_a_crash(
        self,
        tmp_path: Path,
    ) -> None:
        writer = CboeFredProvider(
            cache_dir=tmp_path,
            session=_dated_session(),
            force_fetch=True,
            chain_source=ChainSource.MARKETDATA,
        )

        with pytest.raises(MarketDataError):
            writer.get_option_chain("SPX")
        assert not (tmp_path / "mdchain_SPX.json").exists()


class TestTheAppReadsThePolicysSource:
    """read_only_provider_for wires pricing_feed.chain_source (boot path)."""

    def test_a_marketdata_policy_reads_the_marketdata_entry(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cache = tmp_path / "cache"
        monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(cache))
        CboeFredProvider(
            cache_dir=cache,
            session=_dated_session(),
            force_fetch=True,
            chain_source=ChainSource.MARKETDATA,
            marketdata_token=_TOKEN,
        ).get_option_chain("SPX")
        ips_path = tmp_path / "ips.yaml"
        ips_path.write_text(
            _EXAMPLE_IPS.read_text().replace(
                "  chain_source: none ",
                "  chain_source: marketdata ",
                1,
            ),
        )

        provider = read_only_provider_for(load_ips_config(ips_path))

        assert provider.get_option_chain("SPX").value.quotes


class TestTheRefreshJob:
    """main() with ``chain_source: marketdata``, end to end."""

    def _run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        token: str | None,
    ) -> int:
        csv_session = _csv_dispatching_session()
        chain_session = _dated_session()

        def get(url: str, **kwargs: Any) -> MagicMock:
            if "api.marketdata.app" in url:
                return chain_session.get(url, **kwargs)
            return csv_session.get(url, timeout=kwargs.get("timeout", 10))

        session = MagicMock(spec=requests.Session)
        session.get.side_effect = get
        if token is None:
            monkeypatch.delenv("MARKETDATA_TOKEN", raising=False)
        else:
            monkeypatch.setenv("MARKETDATA_TOKEN", token)
        ips_path = tmp_path / "ips.yaml"
        ips_path.write_text(
            _EXAMPLE_IPS.read_text().replace(
                "  chain_source: none ",
                "  chain_source: marketdata ",
                1,
            ),
        )
        self.session = session
        with (
            patch.object(
                refresh_module,
                "CboeFredProvider",
                side_effect=_factory(session),
            ),
            patch.object(refresh_module, "ping") as ping,
        ):
            code = main(
                [
                    "--cache-dir",
                    str(tmp_path / "cache"),
                    "--ips-path",
                    str(ips_path),
                    "--exports-dir",
                    str(tmp_path / "exports"),
                ],
            )
        self.pinged = ping.called
        return code

    def test_with_the_token_the_chain_refreshes_and_is_recorded(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        code = self._run(tmp_path, monkeypatch, token=_TOKEN)

        assert code == 0
        assert self.pinged
        assert (tmp_path / "cache" / "mdchain_SPX.json").exists()
        assert not (tmp_path / "cache" / "chain_SPX.json").exists()
        assert list(
            (tmp_path / "exports" / "chain-history").glob("SPX-*.jsonl")
        )
        requested = [str(c.args[0]) for c in self.session.get.call_args_list]
        assert not any(
            "cboe.com/api/global/delayed_quotes" in u for u in requested
        )

    def test_without_the_token_it_is_a_partial_run_that_still_pings(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        code = self._run(tmp_path, monkeypatch, token=None)

        assert code == 1
        assert self.pinged
        assert "MARKETDATA_TOKEN is not set" in caplog.text
        assert not (tmp_path / "cache" / "mdchain_SPX.json").exists()
        assert _TOKEN not in caplog.text
