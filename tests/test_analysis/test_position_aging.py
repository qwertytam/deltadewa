"""Tests for deltadewa.analysis.position_aging."""

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa import constants as const
from deltadewa.analysis.position_aging import (
    BUCKET_ORDER,
    ExpiryBucketLabel,
    classify_expiry_bucket,
    evaluate_position_aging,
    expiry_boundaries,
)
from deltadewa.analysis.roll_status import RollVerdict, evaluate_roll_status
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMonetization,
    IpsPricing,
    IpsProgram,
    IpsTriggers,
)
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.position import OptionPosition
from deltadewa.valuation import OptionValuation
from tests.clock_helpers import days_from_today, program_date


def _make_ips_config(
    *,
    expiry_urgent_days: int = 7,
    expiry_soon_days: int = 21,
    roll_at_months_remaining: float = 9.0,
    roll_review_buffer: float = 1.5,
) -> IpsConfig:
    return IpsConfig(
        program=IpsProgram(name="test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=20.0),
        triggers=IpsTriggers(
            delta_ratio_deviation_warn_pct=5.0,
            delta_ratio_deviation_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_at_months_remaining=roll_at_months_remaining,
            rally_rebalance_pct=15.0,
            strike_drift_max_otm_pct=45.0,
            roll_review_buffer=roll_review_buffer,
            expiry_urgent_days=expiry_urgent_days,
            expiry_soon_days=expiry_soon_days,
        ),
        monetization=IpsMonetization(schedule=()),
    )


def _make_position(
    days_to_maturity: int = 200,
    quantity: int = 10,
    strike_price: float = 90.0,
    spot_price: float = 100.0,
    option_type: OptionType = OptionType.PUT,
    now: datetime | None = None,
) -> OptionPosition:
    option = OptionValuation(
        spot_price=spot_price,
        strike_price=strike_price,
        maturity_date=days_from_today(days_to_maturity, now=now),
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        option_type=option_type,
        exercise_style=ExerciseStyle.EUROPEAN,
    )
    return OptionPosition(
        option=option,
        quantity=quantity,
        exercise_style=ExerciseStyle.EUROPEAN,
        entry_spot=spot_price,
        entry_date=days_from_today(-30, now=now),
    )


def _portfolio_with(
    *positions: OptionPosition,
    now: datetime | None = None,
) -> OptionPortfolio:
    spot = positions[0].option.spot_price if positions else 100.0
    portfolio = OptionPortfolio(
        spot_price=spot,
        valuation_date=program_date(now=now),
    )
    portfolio.positions.extend(positions)
    return portfolio


class TestExpiryBoundaries:
    """Every boundary must come from an existing IPS trigger key."""

    def test_all_four_boundaries_come_from_the_ips(self) -> None:
        """Test the defaults resolve to the documented ladder."""
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert boundaries.urgent_days == 7
        assert boundaries.soon_days == 21
        assert boundaries.roll_due_days == 9 * const.CALENDAR_DAYS_PER_MONTH
        assert boundaries.roll_review_days == round(
            9 * const.CALENDAR_DAYS_PER_MONTH * 1.5,
        )

    def test_expiry_urgent_days_moves_the_urgent_boundary(self) -> None:
        """Test the URGENT boundary tracks expiry_urgent_days."""
        boundaries = expiry_boundaries(
            _make_ips_config(expiry_urgent_days=3).triggers,
        )

        assert boundaries.urgent_days == 3

    def test_expiry_soon_days_moves_the_soon_boundary(self) -> None:
        """Test the SOON boundary tracks expiry_soon_days."""
        boundaries = expiry_boundaries(
            _make_ips_config(expiry_soon_days=30).triggers,
        )

        assert boundaries.soon_days == 30

    def test_roll_at_months_remaining_moves_the_roll_due_boundary(self) -> None:
        """Test the ROLL DUE boundary tracks roll_at_months_remaining."""
        boundaries = expiry_boundaries(
            _make_ips_config(roll_at_months_remaining=12.0).triggers,
        )

        assert boundaries.roll_due_days == 12 * const.CALENDAR_DAYS_PER_MONTH

    def test_roll_review_buffer_moves_the_review_boundary(self) -> None:
        """Test the ROLL REVIEW boundary tracks roll_review_buffer."""
        boundaries = expiry_boundaries(
            _make_ips_config(roll_review_buffer=2.0).triggers,
        )

        assert boundaries.roll_review_days == 2 * boundaries.roll_due_days

    def test_short_roll_window_clamps_instead_of_inverting(self) -> None:
        """Test a legal but tiny roll window keeps the ladder monotonic."""
        boundaries = expiry_boundaries(
            _make_ips_config(
                expiry_soon_days=60,
                roll_at_months_remaining=0.5,
                roll_review_buffer=1.0,
            ).triggers,
        )

        assert boundaries.urgent_days <= boundaries.soon_days
        assert boundaries.soon_days <= boundaries.roll_due_days
        assert boundaries.roll_due_days <= boundaries.roll_review_days


class TestClassifyExpiryBucket:
    """Bucket edges, including the comparisons each boundary's owner uses."""

    def test_zero_days_is_expired(self) -> None:
        """#365: days_to_expiry == 0 grades EXPIRED, matching is_expired's
        maturity.date() <= valuation_date.date() boundary.
        """
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert classify_expiry_bucket(0, boundaries) == (
            ExpiryBucketLabel.EXPIRED
        )

    def test_negative_days_is_expired(self) -> None:
        """A maturity strictly in the past also grades EXPIRED."""
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert classify_expiry_bucket(-5, boundaries) == (
            ExpiryBucketLabel.EXPIRED
        )

    def test_one_day_is_not_expired(self) -> None:
        """The boundary is exclusive above zero — one day out is URGENT."""
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert classify_expiry_bucket(1, boundaries) == (
            ExpiryBucketLabel.URGENT
        )

    def test_below_urgent_is_urgent(self) -> None:
        """Test a leg inside the urgent window grades URGENT."""
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert classify_expiry_bucket(6, boundaries) == ExpiryBucketLabel.URGENT

    def test_exactly_urgent_days_is_soon_not_urgent(self) -> None:
        """Test URGENT uses `<`, matching hedge_triggers' urgent count."""
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert classify_expiry_bucket(7, boundaries) == ExpiryBucketLabel.SOON

    def test_exactly_soon_days_is_roll_due_not_soon(self) -> None:
        """Test SOON uses `<` on its upper edge."""
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert (
            classify_expiry_bucket(21, boundaries) == ExpiryBucketLabel.ROLL_DUE
        )

    def test_exactly_roll_due_days_is_roll_due(self) -> None:
        """Test ROLL DUE uses `<=`, matching roll_status' time trigger."""
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert (
            classify_expiry_bucket(boundaries.roll_due_days, boundaries)
            == ExpiryBucketLabel.ROLL_DUE
        )

    def test_one_day_past_roll_due_is_roll_review(self) -> None:
        """Test the ROLL REVIEW band opens above the roll window."""
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert (
            classify_expiry_bucket(boundaries.roll_due_days + 1, boundaries)
            == ExpiryBucketLabel.ROLL_REVIEW
        )

    def test_roll_due_edge_holds_at_twelve_months(self) -> None:
        """Test the ROLL DUE edge at the top of the handbook's 9-12 band."""
        boundaries = expiry_boundaries(
            _make_ips_config(roll_at_months_remaining=12.0).triggers,
        )

        assert (
            classify_expiry_bucket(boundaries.roll_due_days, boundaries)
            == ExpiryBucketLabel.ROLL_DUE
        )
        assert (
            classify_expiry_bucket(boundaries.roll_due_days + 1, boundaries)
            == ExpiryBucketLabel.ROLL_REVIEW
        )

    def test_exactly_review_days_is_roll_review(self) -> None:
        """Test ROLL REVIEW uses `<=` on its upper edge."""
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert (
            classify_expiry_bucket(boundaries.roll_review_days, boundaries)
            == ExpiryBucketLabel.ROLL_REVIEW
        )

    def test_beyond_review_is_long_term(self) -> None:
        """Test the longest bucket opens above the review window."""
        boundaries = expiry_boundaries(_make_ips_config().triggers)

        assert (
            classify_expiry_bucket(boundaries.roll_review_days + 1, boundaries)
            == ExpiryBucketLabel.LONG_TERM
        )


class TestAgreementWithRollStatus:
    """The aging ladder and the roll table must not disagree.

    The two upper buckets read the same IPS keys as
    ``roll_status._time_trigger_verdict``; these guard that they stay in
    step, which the `handbook
    <https://qwertytam.github.io/deltadewa-handbook/part-10/>`_
    (Part X close) requires of any two panels grading the same quantity.
    """

    @staticmethod
    def _compare(
        days: int,
        ips: IpsConfig,
    ) -> tuple[ExpiryBucketLabel, RollVerdict]:
        """Age and roll-status one leg pinned to exactly *days* of runway."""
        position = _make_position(days_to_maturity=days + 1)
        portfolio = _portfolio_with(position)
        # Pin the runway exactly rather than trusting the default valuation
        # date, so the boundary edges under test are the ones evaluated.
        portfolio.valuation_date = position.option.maturity_date - timedelta(
            days=days,
        )

        aging = evaluate_position_aging(portfolio, ips)
        record = evaluate_roll_status(portfolio, ips)[0]

        assert aging.positions[0].days_to_expiry == days
        assert record.days_to_maturity == days
        return aging.positions[0].bucket, record.time_trigger.verdict

    def test_roll_due_bucket_matches_the_roll_verdict(self) -> None:
        """Test a leg on the roll window is ROLL DUE here and ROLL there."""
        ips = _make_ips_config()
        bucket, verdict = self._compare(
            expiry_boundaries(ips.triggers).roll_due_days,
            ips,
        )

        assert bucket == ExpiryBucketLabel.ROLL_DUE
        assert verdict == RollVerdict.ROLL

    def test_roll_review_bucket_matches_the_review_verdict(self) -> None:
        """Test a leg in the buffer band is ROLL REVIEW here, REVIEW there."""
        ips = _make_ips_config()
        bucket, verdict = self._compare(
            expiry_boundaries(ips.triggers).roll_review_days,
            ips,
        )

        assert bucket == ExpiryBucketLabel.ROLL_REVIEW
        assert verdict == RollVerdict.REVIEW

    def test_long_term_bucket_matches_the_hold_verdict(self) -> None:
        """Test a leg beyond the buffer is LONG-TERM here and HOLD there."""
        ips = _make_ips_config()
        bucket, verdict = self._compare(
            expiry_boundaries(ips.triggers).roll_review_days + 1,
            ips,
        )

        assert bucket == ExpiryBucketLabel.LONG_TERM
        assert verdict == RollVerdict.HOLD


class TestEvaluatePositionAging:
    """End-to-end aging of a portfolio."""

    def test_empty_book_returns_zero_filled_buckets(self) -> None:
        """Test an empty book still reports real boundaries."""
        aging = evaluate_position_aging(
            _portfolio_with(),
            _make_ips_config(),
        )

        assert aging.boundaries.urgent_days == 7
        assert len(aging.buckets) == len(BUCKET_ORDER)
        assert all(bucket.legs == 0 for bucket in aging.buckets)
        assert all(bucket.contracts == 0 for bucket in aging.buckets)
        assert aging.positions == ()
        assert aging.calendar == ()

    def test_every_canonical_bucket_is_present_and_ordered(self) -> None:
        """Test buckets come back in urgency order, zero-filled."""
        aging = evaluate_position_aging(
            _portfolio_with(_make_position(days_to_maturity=500)),
            _make_ips_config(),
        )

        assert tuple(b.label for b in aging.buckets) == BUCKET_ORDER

    def test_legs_are_bucketed_and_sorted_by_runway(self) -> None:
        """Test each leg lands in its bucket, shortest runway first."""
        aging = evaluate_position_aging(
            _portfolio_with(
                _make_position(days_to_maturity=500, strike_price=80.0),
                _make_position(days_to_maturity=3, strike_price=81.0),
                _make_position(days_to_maturity=100, strike_price=82.0),
            ),
            _make_ips_config(),
        )

        assert [entry.days_to_expiry for entry in aging.positions] == [
            3,
            100,
            500,
        ]
        assert [entry.bucket for entry in aging.positions] == [
            ExpiryBucketLabel.URGENT,
            ExpiryBucketLabel.ROLL_DUE,
            ExpiryBucketLabel.LONG_TERM,
        ]

    def test_bucket_totals_reconcile_to_the_book(self) -> None:
        """Test summing the buckets reproduces the book's own totals."""
        positions = (
            _make_position(days_to_maturity=3, quantity=2, strike_price=80.0),
            _make_position(days_to_maturity=100, quantity=5, strike_price=81.0),
            _make_position(days_to_maturity=500, quantity=7, strike_price=82.0),
        )
        aging = evaluate_position_aging(
            _portfolio_with(*positions),
            _make_ips_config(),
        )

        assert sum(b.legs for b in aging.buckets) == len(positions)
        assert sum(b.contracts for b in aging.buckets) == sum(
            p.quantity for p in positions
        )
        assert sum(b.position_value for b in aging.buckets) == sum(
            p.position_value() for p in positions
        )
        assert sum(b.position_theta for b in aging.buckets) == sum(
            p.position_theta() for p in positions
        )

    def test_short_legs_net_against_long_in_a_bucket(self) -> None:
        """Test contracts are signed, so a spread nets rather than doubles."""
        aging = evaluate_position_aging(
            _portfolio_with(
                _make_position(
                    days_to_maturity=100,
                    quantity=10,
                    strike_price=90.0,
                ),
                _make_position(
                    days_to_maturity=100,
                    quantity=-4,
                    strike_price=80.0,
                ),
            ),
            _make_ips_config(),
        )
        roll_due = next(
            b for b in aging.buckets if b.label == ExpiryBucketLabel.ROLL_DUE
        )

        assert roll_due.legs == 2
        assert roll_due.contracts == 6


class TestExpirationCalendar:
    """The 'how much at a time' half of the panel."""

    def test_legs_sharing_a_maturity_collapse_to_one_entry(self) -> None:
        """Test two legs on one expiry make a single dated roll-off."""
        maturity = days_from_today(120)
        first = _make_position(days_to_maturity=120, strike_price=90.0)
        second = _make_position(days_to_maturity=120, strike_price=80.0)
        first.option.maturity_date = maturity
        second.option.maturity_date = maturity

        aging = evaluate_position_aging(
            _portfolio_with(first, second),
            _make_ips_config(),
        )

        assert len(aging.calendar) == 1
        assert aging.calendar[0].legs == 2
        assert aging.calendar[0].contracts == 20
        assert aging.calendar[0].maturity_date == maturity

    def test_distinct_maturities_are_listed_ascending(self) -> None:
        """Test the calendar reads soonest roll-off first."""
        aging = evaluate_position_aging(
            _portfolio_with(
                _make_position(days_to_maturity=400, strike_price=80.0),
                _make_position(days_to_maturity=30, strike_price=81.0),
                _make_position(days_to_maturity=200, strike_price=82.0),
            ),
            _make_ips_config(),
        )

        assert [entry.days_to_expiry for entry in aging.calendar] == [
            30,
            200,
            400,
        ]

    def test_calendar_carries_each_entry_s_bucket(self) -> None:
        """Test each dated roll-off is graded like its legs."""
        aging = evaluate_position_aging(
            _portfolio_with(_make_position(days_to_maturity=4)),
            _make_ips_config(),
        )

        assert aging.calendar[0].bucket == ExpiryBucketLabel.URGENT


class TestValuationDateDrivesAging:
    """DTE comes from the portfolio's what-if date, never the wall clock."""

    def test_moving_the_valuation_date_rebuckets_a_leg(self) -> None:
        """Test a what-if date forward re-grades a LONG-TERM leg as URGENT."""
        position = _make_position(days_to_maturity=500)
        portfolio = _portfolio_with(position)
        ips = _make_ips_config()

        before = evaluate_position_aging(portfolio, ips)
        assert before.positions[0].bucket == ExpiryBucketLabel.LONG_TERM

        portfolio.valuation_date = position.option.maturity_date - timedelta(
            days=5,
        )
        after = evaluate_position_aging(portfolio, ips)

        assert after.positions[0].days_to_expiry == 5
        assert after.positions[0].bucket == ExpiryBucketLabel.URGENT


class TestFixturesAgreeWithTheProgramClock:
    """#321/#343: a fixture's "today" must match the portfolio's.

    Between 20:00 and 24:00 America/New_York, ``datetime.now(tz=UTC)`` and
    ``program_trading_date()`` disagree on the calendar date. A fixture
    that seeds a maturity from the former while the portfolio defaults its
    valuation date from the latter reports a day count off by one during
    that window -- this is what made the nightly clock-shift run red.

    Pinned instants rather than a probe-level shift: the divergence is a
    time-of-day boundary, not a day-granularity one, so a whole-day clock
    shift moves both sides together and cannot expose it (see the note in
    ``tests/clockshift_plugin.py``). Threading ``now`` through
    ``_make_position``/``_portfolio_with`` reaches the real bug directly,
    at every hour of the program day, in the ordinary gate.
    """

    @pytest.mark.parametrize(
        ("label", "instant"),
        [
            ("morning ET", datetime(2026, 3, 14, 12, 0, tzinfo=UTC)),
            (
                "21:00 ET -- inside the window",
                datetime(2026, 8, 21, 1, 0, tzinfo=UTC),
            ),
            (
                "23:59 ET -- window edge",
                datetime(2026, 8, 21, 3, 59, tzinfo=UTC),
            ),
            (
                "00:00 ET -- just outside",
                datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
            ),
            ("DST fold", datetime(2026, 11, 1, 5, 30, tzinfo=UTC)),
        ],
    )
    def test_runway_is_exact_at_every_hour_of_the_program_day(
        self,
        label: str,
        instant: datetime,
    ) -> None:
        """Test days_to_expiry and bucket hold no matter when "now" falls."""
        del label  # pytest id only
        aging = evaluate_position_aging(
            _portfolio_with(
                _make_position(days_to_maturity=3, now=instant),
                now=instant,
            ),
            _make_ips_config(),
        )

        assert aging.positions[0].days_to_expiry == 3
        assert aging.positions[0].bucket == ExpiryBucketLabel.URGENT
