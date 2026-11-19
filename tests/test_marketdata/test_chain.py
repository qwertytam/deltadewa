"""Tests for deltadewa.marketdata.chain: parse, date, match."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from deltadewa.constants import OptionType
from deltadewa.marketdata import MarketDataError
from deltadewa.marketdata.chain import (
    MatchFlag,
    parse_cboe_chain,
    quote_session_date,
    session_close,
)
from tests.chain_builders import (
    BOTH_ROOTS,
    DECEMBER,
    JUNE_THURSDAY,
    SESSION,
    WEEKLY_ONLY,
    occ,
    payload,
    raw_contract,
    standard_chain,
)

_NEW_YORK = ZoneInfo("America/New_York")
_MAX_SPREAD = 25.0


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


class TestParse:
    """parse_cboe_chain turns a payload into a snapshot."""

    def test_snapshot_carries_spot_time_and_session(self) -> None:
        """The index level, the UTC stamp and the session come through."""
        snapshot = parse_cboe_chain(standard_chain(spot=5123.5))

        assert snapshot.spot == pytest.approx(5123.5)
        assert snapshot.quoted_at == _utc(2026, 11, 17, 1, 33, 27)
        assert snapshot.session_date == SESSION
        assert snapshot.underlying == "_SPX"

    def test_spxo_is_dropped(self) -> None:
        """The unidentified third root is never kept."""
        snapshot = parse_cboe_chain(standard_chain())

        assert {quote.root for quote in snapshot.quotes} == {"SPX", "SPXW"}

    def test_expiry_is_read_from_the_symbol(self) -> None:
        """A monthly on a holiday-Friday week keeps its Thursday date."""
        snapshot = parse_cboe_chain(standard_chain())

        assert JUNE_THURSDAY in snapshot.expiries()
        assert JUNE_THURSDAY.weekday() == 3

    def test_strike_is_scaled_from_eight_digits(self) -> None:
        """``05400000`` is a 5,400 strike."""
        symbol = occ("SPX", DECEMBER, OptionType.PUT, 5400.0)
        snapshot = parse_cboe_chain(
            payload([raw_contract(symbol, bid=99.0, ask=101.0, iv=0.29)]),
        )

        assert snapshot.quotes[0].strike == pytest.approx(5400.0)
        assert snapshot.quotes[0].option_type is OptionType.PUT

    def test_vendor_iv_is_a_fraction_and_zero_means_unsolved(self) -> None:
        """``iv: 0`` is None, never a 0% volatility; a bid is separate."""
        symbol = occ("SPX", DECEMBER, OptionType.PUT, 5400.0)
        snapshot = parse_cboe_chain(
            payload([raw_contract(symbol, bid=99.0, ask=101.0, iv=0.0)]),
        )

        quote = snapshot.quotes[0]
        assert quote.vendor_iv is None
        assert quote.bid == pytest.approx(99.0)

    def test_null_open_interest_and_volume_stay_none(self) -> None:
        """Absent counts are None, not zero."""
        symbol = occ("SPX", DECEMBER, OptionType.PUT, 5400.0)
        snapshot = parse_cboe_chain(
            payload(
                [
                    raw_contract(
                        symbol,
                        bid=1.0,
                        ask=2.0,
                        iv=0.3,
                        open_interest=None,
                        volume=None,
                    ),
                ],
            ),
        )

        assert snapshot.quotes[0].open_interest is None
        assert snapshot.quotes[0].volume is None

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda p: p.pop("data"),
            lambda p: p.pop("timestamp"),
            lambda p: p.update(timestamp="not a time"),
            lambda p: p["data"].pop("current_price"),
            lambda p: p["data"].update(current_price="x"),
            lambda p: p["data"].update(current_price=0.0),
            lambda p: p["data"].update(current_price=float("nan")),
            lambda p: p["data"].update(current_price=float("inf")),
            lambda p: p["data"].update(current_price=float("-inf")),
            lambda p: p["data"].update(options=[]),
            lambda p: p["data"].update(options=None),
            lambda p: p["data"]["options"][0].update(option="NOT-OCC"),
            lambda p: p["data"]["options"][0].update(bid="x"),
            lambda p: p["data"]["options"][0].update(
                open_interest=float("inf"),
            ),
            lambda p: p["data"]["options"][0].update(volume=float("nan")),
            lambda p: p["data"]["options"][0].update(bid=float("inf")),
            lambda p: p["data"]["options"][0].pop("option"),
            lambda p: p["data"]["options"][0].update(
                option="SPX261399P00500000"
            ),
        ],
    )
    def test_malformed_payload_raises_market_data_error_only(
        self,
        mutate,
    ) -> None:
        """Every failure is MarketDataError, which the job contains."""
        bad = deepcopy(standard_chain())
        mutate(bad)

        with pytest.raises(MarketDataError):
            parse_cboe_chain(bad)


class TestSessionDate:
    """quote_session_date names the session a payload's quotes belong to."""

    def test_overnight_payload_after_a_weekday_close(self) -> None:
        """01:33 UTC Tuesday is 20:33 Monday in New York: Monday's close."""
        assert quote_session_date(_utc(2026, 11, 17, 1, 33)) == date(
            2026,
            11,
            16,
        )

    def test_payload_during_a_trading_day_is_that_day(self) -> None:
        """From 09:30 New York a payload belongs to the same day."""
        moment = datetime(2026, 11, 17, 12, 0, tzinfo=_NEW_YORK)

        assert quote_session_date(moment) == date(2026, 11, 17)

    def test_pre_open_payload_is_the_previous_session(self) -> None:
        """Before 09:30 New York the quotes are still yesterday's close."""
        moment = datetime(2026, 11, 17, 8, 0, tzinfo=_NEW_YORK)

        assert quote_session_date(moment) == date(2026, 11, 16)

    def test_saturday_payload_is_friday(self) -> None:
        """A weekend payload describes Friday's close."""
        assert quote_session_date(_utc(2026, 11, 21, 15, 0)) == date(
            2026,
            11,
            20,
        )

    def test_monday_pre_open_is_friday(self) -> None:
        """Monday before the open is Friday's close, across the weekend."""
        moment = datetime(2026, 11, 23, 7, 0, tzinfo=_NEW_YORK)

        assert quote_session_date(moment) == date(2026, 11, 20)

    def test_thanksgiving_evening_is_wednesday(self) -> None:
        """A holiday is not a session: back to the previous trading day."""
        moment = datetime(2026, 11, 26, 20, 0, tzinfo=_NEW_YORK)

        assert quote_session_date(moment) == date(2026, 11, 25)

    def test_juneteenth_is_not_a_session(self) -> None:
        """The June 2026 observed holiday (Friday) is skipped."""
        moment = datetime(2026, 6, 19, 20, 0, tzinfo=_NEW_YORK)

        assert quote_session_date(moment) == date(2026, 6, 18)

    def test_naive_datetime_is_refused(self) -> None:
        """A naive stamp has no zone to date it in."""
        with pytest.raises(ValueError, match="timezone-aware"):
            quote_session_date(datetime(2026, 11, 17, 1, 33))

    def test_session_close_is_1615_new_york(self) -> None:
        """SPX options close at 16:15 New York."""
        close = session_close(SESSION)

        assert close.astimezone(_NEW_YORK).time().isoformat() == "16:15:00"


class TestMatch:
    """ChainSnapshot.match finds one contract and flags an unusable quote."""

    def _snapshot(self):
        return parse_cboe_chain(standard_chain())

    def test_spx_only_date_matches_spx(self) -> None:
        """A monthly lists on SPX only."""
        match = self._snapshot().match(
            expiry=JUNE_THURSDAY,
            option_type=OptionType.PUT,
            strike=4600.0,
            max_spread_pct=_MAX_SPREAD,
        )

        assert match.quote is not None
        assert match.quote.root == "SPX"
        assert match.flags == frozenset()

    def test_weekly_only_date_falls_to_spxw(self) -> None:
        """SPXW is used where SPX does not list the date."""
        match = self._snapshot().match(
            expiry=WEEKLY_ONLY,
            option_type=OptionType.PUT,
            strike=4600.0,
            max_spread_pct=_MAX_SPREAD,
        )

        assert match.quote is not None
        assert match.quote.root == "SPXW"

    def test_both_roots_prefers_spx_and_says_so(self) -> None:
        """Where both list the date SPX wins and the match is ambiguous."""
        match = self._snapshot().match(
            expiry=BOTH_ROOTS,
            option_type=OptionType.PUT,
            strike=4600.0,
            max_spread_pct=_MAX_SPREAD,
        )

        assert match.quote is not None
        assert match.quote.root == "SPX"
        assert match.other_root is not None
        assert match.other_root.root == "SPXW"
        assert match.flags == frozenset({MatchFlag.AMBIGUOUS_ROOT})

    def test_unlisted_contract_is_absent(self) -> None:
        """No strike, no match."""
        match = self._snapshot().match(
            expiry=DECEMBER,
            option_type=OptionType.PUT,
            strike=4650.0,
            max_spread_pct=_MAX_SPREAD,
        )

        assert match.quote is None
        assert match.flags == frozenset({MatchFlag.ABSENT})

    def test_a_call_is_not_a_put(self) -> None:
        """Type is part of the key."""
        match = self._snapshot().match(
            expiry=DECEMBER,
            option_type=OptionType.CALL,
            strike=4600.0,
            max_spread_pct=_MAX_SPREAD,
        )

        assert MatchFlag.ABSENT in match.flags

    def test_spxo_is_never_matched(self) -> None:
        """The SPXO Wednesday has no match even where it is the only line."""
        match = self._snapshot().match(
            expiry=date(2026, 11, 18),
            option_type=OptionType.PUT,
            strike=5000.0,
            max_spread_pct=_MAX_SPREAD,
        )

        assert match.flags == frozenset({MatchFlag.ABSENT})

    @pytest.mark.parametrize(
        ("bid", "ask", "expected"),
        [
            (0.0, 2.0, {MatchFlag.ZERO_BID}),
            (1.0, 0.0, {MatchFlag.NO_ASK}),
            (0.0, 0.0, {MatchFlag.ZERO_BID, MatchFlag.NO_ASK}),
            (10.0, 20.0, {MatchFlag.WIDE}),
            (11.0, 10.0, {MatchFlag.CROSSED}),
            (10.0, 11.0, set()),
        ],
    )
    def test_quote_flags(
        self,
        bid: float,
        ask: float,
        expected: set[MatchFlag],
    ) -> None:
        """Bid, ask and spread are tested separately from the vendor IV."""
        symbol = occ("SPX", DECEMBER, OptionType.PUT, 4000.0)
        snapshot = parse_cboe_chain(
            payload([raw_contract(symbol, bid=bid, ask=ask, iv=0.0)]),
        )

        match = snapshot.match(
            expiry=DECEMBER,
            option_type=OptionType.PUT,
            strike=4000.0,
            max_spread_pct=_MAX_SPREAD,
        )

        assert match.flags == frozenset(expected)

    def test_listed_strikes_span_both_roots(self) -> None:
        """The strike list for a date is the union over the roots."""
        strikes = self._snapshot().listed_strikes(
            expiry=BOTH_ROOTS,
            option_type=OptionType.PUT,
        )

        assert strikes[0] == pytest.approx(2500.0)
        assert strikes[-1] == pytest.approx(5100.0)
        assert len(strikes) == len(set(strikes))
