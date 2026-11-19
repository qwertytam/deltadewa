"""Tests for analysis.liquidity — Part X #12 as a checklist (8c, N10)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from deltadewa.analysis.chain_quotes import ChainReading
from deltadewa.analysis.liquidity import (
    OpenInterestGrade,
    SpreadGrade,
    assess_liquidity,
    effective_observation,
    fetched_observation,
    roll_due_position_ids,
)
from deltadewa.analysis.provenance import Freshness
from deltadewa.analysis.roll_status import RollVerdict
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsLiquidity
from deltadewa.marketdata.chain import ChainQuote, MatchFlag
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.liquidity import (
    LiquidityObservation,
    LiquiditySource,
)
from tests.clock_helpers import days_from_today

_AS_OF = date(2026, 11, 9)
_POLICY = IpsLiquidity(
    spread_warn_pct=10.0,
    observation_max_age_days=30,
    open_interest_min=500,
)


def _book(n_legs: int = 3) -> OptionPortfolio:
    portfolio = OptionPortfolio(
        spot_price=100.0,
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    for i in range(n_legs):
        portfolio.add_position(
            strike_price=80.0 - 5 * i,
            maturity_date=days_from_today(365),
            quantity=10,
            option_type=OptionType.PUT,
        )
    return portfolio


def _record(
    portfolio: OptionPortfolio,
    index: int,
    *,
    bid: float = 2.40,
    ask: float = 2.60,
    open_interest: int | None = 3_400,
    observed: date = date(2026, 11, 6),
) -> None:
    portfolio.record_liquidity(
        portfolio.positions[index].position_id,
        bid=bid,
        ask=ask,
        open_interest=open_interest,
        observed_at=datetime(
            observed.year,
            observed.month,
            observed.day,
            15,
            tzinfo=UTC,
        ),
    )


class TestGrades:
    """Spread, open interest and age, each against IPS policy."""

    def test_never_checked_leg(self) -> None:
        checklist = assess_liquidity(_book(1), _POLICY, as_of=_AS_OF)
        leg = checklist.legs[0]

        assert leg.observation is None
        assert leg.spread_grade is None
        assert leg.open_interest_grade is None
        assert leg.freshness is not None
        assert leg.freshness.freshness is Freshness.UNKNOWN
        assert leg.capture_due

    def test_within_spread_adequate_oi_fresh(self) -> None:
        portfolio = _book(1)
        _record(portfolio, 0)  # 8% spread, OI 3,400, 3 days old

        leg = assess_liquidity(portfolio, _POLICY, as_of=_AS_OF).legs[0]

        assert leg.spread_grade is SpreadGrade.WITHIN
        assert leg.open_interest_grade is OpenInterestGrade.ADEQUATE
        assert leg.freshness is not None
        assert leg.freshness.freshness is Freshness.FRESH
        assert leg.held_share_of_oi_pct == pytest.approx(10 / 3_400 * 100)
        assert not leg.capture_due

    def test_spread_at_the_threshold_is_within(self) -> None:
        """The threshold is inclusive: only *wider* than it grades WIDE."""
        portfolio = _book(1)
        # (2.10 - 1.90) / 2.00 = 10.0% exactly.
        _record(portfolio, 0, bid=1.90, ask=2.10)

        leg = assess_liquidity(portfolio, _POLICY, as_of=_AS_OF).legs[0]

        assert leg.spread_grade is SpreadGrade.WITHIN

    def test_wide_spread_and_low_oi(self) -> None:
        portfolio = _book(1)
        _record(portfolio, 0, bid=1.00, ask=1.40, open_interest=120)

        leg = assess_liquidity(portfolio, _POLICY, as_of=_AS_OF).legs[0]

        assert leg.spread_grade is SpreadGrade.WIDE
        assert leg.open_interest_grade is OpenInterestGrade.LOW

    def test_overdue_quote_is_aging_and_due(self) -> None:
        portfolio = _book(1)
        _record(portfolio, 0, observed=date(2026, 9, 1))  # 69 days

        leg = assess_liquidity(portfolio, _POLICY, as_of=_AS_OF).legs[0]

        assert leg.freshness is not None
        assert leg.freshness.freshness is Freshness.AGING
        assert leg.freshness.age_days == 69
        assert leg.capture_due
        # The grade still describes the moment it was read.
        assert leg.spread_grade is SpreadGrade.WITHIN

    def test_quote_without_oi_leaves_oi_ungraded(self) -> None:
        portfolio = _book(1)
        _record(portfolio, 0, open_interest=None)

        leg = assess_liquidity(portfolio, _POLICY, as_of=_AS_OF).legs[0]

        assert leg.open_interest_grade is OpenInterestGrade.UNGRADED
        assert leg.held_share_of_oi_pct is None

    def test_no_oi_minimum_leaves_oi_ungraded(self) -> None:
        portfolio = _book(1)
        _record(portfolio, 0, open_interest=10)
        policy = IpsLiquidity(spread_warn_pct=10.0, observation_max_age_days=30)

        leg = assess_liquidity(portfolio, policy, as_of=_AS_OF).legs[0]

        assert leg.open_interest_grade is OpenInterestGrade.UNGRADED

    def test_no_policy_grades_nothing(self) -> None:
        """Without a liquidity: section there is no threshold to invent."""
        portfolio = _book(1)
        _record(portfolio, 0, bid=0.0, ask=1.0)  # 200% spread

        checklist = assess_liquidity(portfolio, None, as_of=_AS_OF)
        leg = checklist.legs[0]

        assert not checklist.policy_present
        assert leg.spread_grade is SpreadGrade.UNGRADED
        assert leg.open_interest_grade is OpenInterestGrade.UNGRADED
        assert leg.freshness is None
        assert checklist.wide_at_last_check == 0


class TestRollWindow:
    """A leg about to be traded needs a fresh quote regardless."""

    def test_roll_due_leg_needs_a_capture_even_with_a_fresh_quote(
        self,
    ) -> None:
        """Fresh by cadence (3 days old) is not good enough for a roll."""
        portfolio = _book(1)
        _record(portfolio, 0)  # 2026-11-06, as_of 2026-11-09
        leg_id = portfolio.positions[0].position_id

        leg = assess_liquidity(
            portfolio,
            _POLICY,
            as_of=_AS_OF,
            roll_due_ids=frozenset({leg_id}),
        ).legs[0]

        assert leg.roll_due
        assert leg.capture_due

    def test_a_quote_read_today_satisfies_the_roll(self) -> None:
        """Recording the roll's quote clears the flag the same day."""
        portfolio = _book(1)
        _record(portfolio, 0, observed=_AS_OF)
        leg_id = portfolio.positions[0].position_id

        leg = assess_liquidity(
            portfolio,
            _POLICY,
            as_of=_AS_OF,
            roll_due_ids=frozenset({leg_id}),
        ).legs[0]

        assert leg.roll_due
        assert not leg.capture_due

    @pytest.mark.parametrize(
        ("verdict", "due"),
        [
            (RollVerdict.HOLD, False),
            (RollVerdict.MONITOR, False),
            (RollVerdict.REVIEW, True),
            (RollVerdict.ROLL, True),
            (RollVerdict.EXPIRED, False),
        ],
    )
    def test_roll_due_ids_from_verdicts(
        self,
        verdict: RollVerdict,
        *,
        due: bool,
    ) -> None:
        record = SimpleNamespace(
            position=SimpleNamespace(position_id="leg-1"),
            verdict=verdict,
        )

        ids = roll_due_position_ids([record])  # type: ignore[list-item]

        assert ("leg-1" in ids) is due


class TestCounts:
    """The headline is counts, never one verdict word."""

    def test_counts(self) -> None:
        portfolio = _book(4)
        _record(portfolio, 0)  # fresh, within
        _record(portfolio, 1, bid=1.0, ask=1.4)  # fresh, wide
        _record(portfolio, 2, observed=date(2026, 8, 1))  # overdue
        # leg 3 never checked

        checklist = assess_liquidity(portfolio, _POLICY, as_of=_AS_OF)

        assert checklist.policy_present
        assert checklist.never_checked == 1
        assert checklist.overdue == 1
        assert checklist.wide_at_last_check == 1
        assert checklist.capture_due == 2  # overdue + never checked
        assert [leg.position_id for leg in checklist.legs] == [
            p.position_id for p in portfolio.positions
        ]


_SESSION = date(2026, 11, 6)


def _quote(
    *,
    bid: float = 2.4,
    ask: float = 2.6,
    open_interest: int | None = 3_400,
) -> ChainQuote:
    return ChainQuote(
        symbol="SPX271217P04000000",
        root="SPX",
        expiry=date(2027, 12, 17),
        option_type=OptionType.PUT,
        strike=4000.0,
        bid=bid,
        ask=ask,
        vendor_iv=0.3,
        open_interest=open_interest,
        volume=1,
    )


def _reading(quote: ChainQuote | None) -> ChainReading:
    return ChainReading(
        label="L1",
        quote=quote,
        solved_iv=0.3 if quote is not None else None,
        flags=(
            frozenset() if quote is not None else frozenset({MatchFlag.ABSENT})
        ),
        session_date=_SESSION,
        quoted_at=datetime(2026, 11, 7, 1, 33, tzinfo=UTC),
    )


def _fetched(
    *, observed: date = _SESSION, bid: float = 2.4
) -> LiquidityObservation:
    return LiquidityObservation(
        bid=bid,
        ask=bid + 0.2,
        open_interest=3_400,
        observed_at=datetime(
            observed.year,
            observed.month,
            observed.day,
            21,
            15,
            tzinfo=UTC,
        ),
        source=LiquiditySource.FETCHED,
    )


class TestFetchedObservation:
    """A chain reading becomes a fetched quote, dated to its session close."""

    def test_close_quote_carries_bid_ask_open_interest_and_source(self) -> None:
        observation = fetched_observation(_reading(_quote()))

        assert observation is not None
        assert observation.source is LiquiditySource.FETCHED
        assert (observation.bid, observation.ask) == (2.4, 2.6)
        assert observation.open_interest == 3_400

    def test_it_is_dated_to_the_session_close_not_the_fetch(self) -> None:
        observation = fetched_observation(_reading(_quote()))

        assert observation is not None
        assert observation.observed_at.date() == _SESSION
        assert observation.observed_at.utcoffset() is not None
        assert (
            observation.observed_at.hour,
            observation.observed_at.minute,
        ) == (
            16,
            15,
        )

    def test_an_intraday_payload_is_not_dated_after_it_was_generated(
        self,
    ) -> None:
        """Generated at 12:00 New York, the quote is not dated to 16:15."""
        reading = _reading(_quote())
        intraday = ChainReading(
            label=reading.label,
            quote=reading.quote,
            solved_iv=reading.solved_iv,
            flags=reading.flags,
            session_date=_SESSION,
            quoted_at=datetime(2026, 11, 6, 17, 0, tzinfo=UTC),
        )

        observation = fetched_observation(intraday)

        assert observation is not None
        assert observation.observed_at == intraday.quoted_at

    def test_a_chain_past_max_quote_age_is_not_used(self) -> None:
        """pricing_feed.max_quote_age_days owns how old a fetched close may be.

        A dead feed must stop filling the checklist, not pass as a recent
        read under the (longer) operator-quote cadence.
        """
        reading = _reading(_quote())
        stale = ChainReading(
            label=reading.label,
            quote=reading.quote,
            solved_iv=reading.solved_iv,
            flags=frozenset({MatchFlag.STALE_QUOTE}),
            session_date=_SESSION,
            quoted_at=reading.quoted_at,
        )

        assert fetched_observation(stale) is None

    def test_a_no_bid_quote_is_kept_as_the_strongest_warning(self) -> None:
        observation = fetched_observation(_reading(_quote(bid=0.0, ask=0.4)))

        assert observation is not None
        assert observation.bid == pytest.approx(0.0)
        assert observation.spread_pct == pytest.approx(200.0)

    @pytest.mark.parametrize(
        "quote",
        [None, _quote(bid=0.0, ask=0.0), _quote(bid=3.0, ask=2.0)],
    )
    def test_unlisted_askless_or_crossed_has_no_observation(
        self, quote
    ) -> None:
        assert fetched_observation(_reading(quote)) is None

    def test_a_recorded_operator_quote_is_the_default_source(self) -> None:
        book = _book(1)
        _record(book, 0)

        assert book.positions[0].liquidity is not None
        assert book.positions[0].liquidity.source is LiquiditySource.OPERATOR


class TestEffectiveObservation:
    """The later quote is graded, the other shown; a tie is the operator's."""

    def _operator(self, observed: date) -> LiquidityObservation:
        return LiquidityObservation(
            bid=2.0,
            ask=2.2,
            open_interest=100,
            observed_at=datetime(
                observed.year,
                observed.month,
                observed.day,
                21,
                15,
                tzinfo=UTC,
            ),
        )

    def test_only_one_source_is_graded_with_nothing_beside_it(self) -> None:
        fetched = _fetched()
        operator = self._operator(date(2026, 11, 5))

        assert effective_observation(None, fetched) == (fetched, None)
        assert effective_observation(operator, None) == (operator, None)
        assert effective_observation(None, None) == (None, None)

    def test_a_newer_fetched_quote_is_graded_and_the_operators_shown(
        self,
    ) -> None:
        fetched = _fetched(observed=date(2026, 11, 6))
        operator = self._operator(date(2026, 11, 5))

        assert effective_observation(operator, fetched) == (fetched, operator)

    def test_a_newer_operator_quote_outranks_last_nights_close(self) -> None:
        fetched = _fetched(observed=date(2026, 11, 6))
        operator = self._operator(date(2026, 11, 9))

        assert effective_observation(operator, fetched) == (operator, fetched)

    def test_a_tie_goes_to_the_operator(self) -> None:
        fetched = _fetched(observed=date(2026, 11, 6))
        operator = self._operator(date(2026, 11, 6))

        assert effective_observation(operator, fetched)[0] is operator


class TestAssessWithFetched:
    """assess_liquidity with fetched quotes beside the book's own."""

    def test_a_fetched_quote_satisfies_never_checked_without_touching_the_book(
        self,
    ) -> None:
        book = _book(2)
        fetched = {book.positions[0].position_id: _fetched()}

        checklist = assess_liquidity(
            book,
            _POLICY,
            as_of=date(2026, 11, 9),
            fetched=fetched,
        )

        assert checklist.legs[0].observation is not None
        assert checklist.legs[0].observation.source is LiquiditySource.FETCHED
        assert checklist.legs[0].capture_due is False
        assert checklist.legs[1].observation is None
        assert checklist.never_checked == 1
        assert book.positions[0].liquidity is None  # never stored

    def test_the_operators_quote_is_never_overwritten(self) -> None:
        book = _book(1)
        _record(book, 0, observed=date(2026, 11, 9))
        before = book.positions[0].liquidity

        checklist = assess_liquidity(
            book,
            _POLICY,
            as_of=date(2026, 11, 9),
            fetched={book.positions[0].position_id: _fetched()},
        )

        assert book.positions[0].liquidity is before
        leg = checklist.legs[0]
        assert leg.observation is before
        assert leg.other is not None
        assert leg.other.source is LiquiditySource.FETCHED

    def test_a_roll_window_leg_still_wants_a_quote_read_today(self) -> None:
        """Last night's close does not satisfy a leg about to be traded."""
        book = _book(1)
        position_id = book.positions[0].position_id

        checklist = assess_liquidity(
            book,
            _POLICY,
            as_of=date(2026, 11, 9),
            roll_due_ids=frozenset({position_id}),
            fetched={position_id: _fetched()},
        )

        assert checklist.legs[0].capture_due is True

    def test_it_is_graded_against_policy_like_any_other_quote(self) -> None:
        book = _book(1)
        wide = _fetched(bid=1.0)
        wide = LiquidityObservation(
            bid=1.0,
            ask=2.0,
            open_interest=10,
            observed_at=wide.observed_at,
            source=LiquiditySource.FETCHED,
        )

        checklist = assess_liquidity(
            book,
            _POLICY,
            as_of=date(2026, 11, 9),
            fetched={book.positions[0].position_id: wide},
        )

        leg = checklist.legs[0]
        assert leg.spread_grade is SpreadGrade.WIDE
        assert leg.open_interest_grade is OpenInterestGrade.LOW
        assert leg.freshness is not None
        assert leg.freshness.freshness is Freshness.FRESH
