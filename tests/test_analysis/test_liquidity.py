"""Tests for analysis.liquidity — Part X #12 as a checklist (8c, N10)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from deltadewa.analysis.liquidity import (
    OpenInterestGrade,
    SpreadGrade,
    assess_liquidity,
    roll_due_position_ids,
)
from deltadewa.analysis.provenance import Freshness
from deltadewa.analysis.roll_status import RollVerdict
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsLiquidity
from deltadewa.portfolio.core import OptionPortfolio
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
