"""Tests for deltadewa.analysis.monetization."""

from __future__ import annotations

import datetime

import pytest

from deltadewa.analysis.market_environment import (
    DataQuality,
    MarketEnvironment,
    RegimeLabel,
)
from deltadewa.analysis.monetization import (
    MonetizationPlan,
    MonetizationStepStatus,
    build_monetization_plan,
    compute_hedge_gain_pct,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMonetization,
    IpsMonetizationStep,
    IpsPricing,
    IpsProgram,
    IpsTriggers,
)
from deltadewa.portfolio.core import OptionPortfolio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SPOT = 5000.0
_MATURITY = datetime.datetime.now(tz=datetime.UTC) + datetime.timedelta(
    days=180,
)

# IPS with three-step schedule: +100%→sell 25%, +200%→sell 25%, +400%→sell 25%
_THREE_STEP_IPS = IpsConfig(
    program=IpsProgram(name="Test", instrument="SPX"),
    pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
    budget=IpsBudget(annual_carry_pct=2.0),
    convexity=IpsConvexity(
        crash_scenario_pct=-25.0,
        target_min_pct=5.0,
        target_max_pct=30.0,
    ),
    drawdown=IpsDrawdown(max_tolerance_pct=20.0),
    triggers=IpsTriggers(
        delta_drift_warn_pct=5.0,
        delta_drift_action_pct=10.0,
        theta_cost_acceptable_pct=3.0,
        roll_time_months=1.0,
        rally_rebalance_pct=10.0,
        strike_drift_max_otm_pct=15.0,
    ),
    monetization=IpsMonetization(
        schedule=(
            IpsMonetizationStep(gain_pct=100.0, sell_pct=25.0),
            IpsMonetizationStep(gain_pct=200.0, sell_pct=25.0),
            IpsMonetizationStep(gain_pct=400.0, sell_pct=25.0),
        ),
    ),
)


def _portfolio_with_put(
    *,
    strike: float = 4500.0,
    quantity: int = 1,
    contract_size: int = 100,
) -> OptionPortfolio:
    """Return a European SPX portfolio with one long put position."""
    portfolio = OptionPortfolio(
        spot_price=_SPOT,
        underlying_quantity=100.0,
        volatility=0.20,
        risk_free_rate=0.04,
        dividend_yield=0.015,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=strike,
        maturity_date=_MATURITY,
        quantity=quantity,
        option_type=OptionType.PUT,
        contract_size=contract_size,
        exercise_style=ExerciseStyle.EUROPEAN,
    )
    return portfolio


def _make_market_env(regime: RegimeLabel) -> MarketEnvironment:
    """Return a minimal MarketEnvironment with the given regime label."""
    return MarketEnvironment(
        vix=None,
        regime_percentile=None,
        regime_label=regime,
        skew_index=None,
        skew_percentile=None,
        term_structure=None,
        term_shape=None,
        forward_vol_front_3m=None,
        hedge_cost_verdict=None,
        data_quality=DataQuality.LIVE,
        as_of=datetime.datetime(2026, 7, 24, tzinfo=datetime.UTC),
    )


# ---------------------------------------------------------------------------
# compute_hedge_gain_pct
# ---------------------------------------------------------------------------


class TestComputeHedgeGainPct:
    """Tests for compute_hedge_gain_pct."""

    def test_empty_portfolio_returns_none(self) -> None:
        """Empty portfolio → None, no raise."""
        portfolio = OptionPortfolio(
            spot_price=_SPOT,
            underlying_quantity=100.0,
            volatility=0.20,
            risk_free_rate=0.04,
            dividend_yield=0.015,
        )
        assert compute_hedge_gain_pct(portfolio) is None

    def test_no_long_puts_returns_none(self) -> None:
        """A portfolio with only calls (no puts) → None."""
        portfolio = OptionPortfolio(
            spot_price=_SPOT,
            underlying_quantity=100.0,
            volatility=0.20,
            risk_free_rate=0.04,
            dividend_yield=0.015,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=5500.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.CALL,
        )
        portfolio.positions[0].entry_premium = 10.0
        assert compute_hedge_gain_pct(portfolio) is None

    def test_missing_entry_premium_returns_none(self) -> None:
        """Long put with entry_premium=None → None, no raise."""
        portfolio = _portfolio_with_put()
        assert portfolio.positions[0].entry_premium is None
        assert compute_hedge_gain_pct(portfolio) is None

    def test_positive_gain(self) -> None:
        """entry_premium set to price/2.5 → gain ≈ 150%."""
        portfolio = _portfolio_with_put()
        pos = portfolio.positions[0]
        pos.entry_premium = pos.option.price() / 2.5
        gain = compute_hedge_gain_pct(portfolio)
        assert gain is not None
        assert gain == pytest.approx(150.0, rel=1e-6)

    def test_negative_gain(self) -> None:
        """entry_premium set to price/0.6 → gain ≈ -40%."""
        portfolio = _portfolio_with_put()
        pos = portfolio.positions[0]
        pos.entry_premium = pos.option.price() / 0.6
        gain = compute_hedge_gain_pct(portfolio)
        assert gain is not None
        assert gain == pytest.approx(-40.0, rel=1e-6)

    def test_partial_missing_premium_returns_none(self) -> None:
        """Two long puts, one missing entry_premium → None."""
        portfolio = OptionPortfolio(
            spot_price=_SPOT,
            underlying_quantity=100.0,
            volatility=0.20,
            risk_free_rate=0.04,
            dividend_yield=0.015,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        for strike in (4500.0, 4000.0):
            portfolio.add_position(
                strike_price=strike,
                maturity_date=_MATURITY,
                quantity=1,
                option_type=OptionType.PUT,
                exercise_style=ExerciseStyle.EUROPEAN,
            )
        portfolio.positions[0].entry_premium = 5.0
        # positions[1].entry_premium remains None
        assert compute_hedge_gain_pct(portfolio) is None

    def test_short_put_excluded(self) -> None:
        """Short put (quantity < 0) is not counted; portfolio → None."""
        portfolio = OptionPortfolio(
            spot_price=_SPOT,
            underlying_quantity=100.0,
            volatility=0.20,
            risk_free_rate=0.04,
            dividend_yield=0.015,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=4500.0,
            maturity_date=_MATURITY,
            quantity=-1,
            option_type=OptionType.PUT,
            exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.positions[0].entry_premium = 5.0
        assert compute_hedge_gain_pct(portfolio) is None


# ---------------------------------------------------------------------------
# build_monetization_plan — trigger thresholds
# ---------------------------------------------------------------------------


class TestBuildMonetizationPlanTriggers:
    """Step-trigger tests for build_monetization_plan."""

    def test_below_first_threshold_no_steps_triggered(self) -> None:
        """Gain < 100% → all steps untriggered, recommended = 0."""
        portfolio = _portfolio_with_put()
        pos = portfolio.positions[0]
        pos.entry_premium = pos.option.price() / 1.5  # gain ≈ 50%
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.recommended_cumulative_sell_pct == pytest.approx(0.0)
        assert all(not s.triggered for s in plan.steps)
        assert plan.value_to_harvest == pytest.approx(0.0)

    def test_above_first_threshold_only(self) -> None:
        """Gain ≈ 150% → only the +100% step triggered, recommended = 25%."""
        portfolio = _portfolio_with_put()
        pos = portfolio.positions[0]
        pos.entry_premium = pos.option.price() / 2.5  # gain ≈ 150%
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.recommended_cumulative_sell_pct == pytest.approx(25.0)
        triggered = [s for s in plan.steps if s.triggered]
        assert len(triggered) == 1
        assert triggered[0].gain_pct == pytest.approx(100.0)

    def test_above_second_threshold(self) -> None:
        """Gain ≈ 250% → first two steps triggered, recommended = 50%."""
        portfolio = _portfolio_with_put()
        pos = portfolio.positions[0]
        pos.entry_premium = pos.option.price() / 3.5  # gain ≈ 250%
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.recommended_cumulative_sell_pct == pytest.approx(50.0)
        triggered = [s for s in plan.steps if s.triggered]
        assert len(triggered) == 2

    def test_exact_threshold_triggers(self) -> None:
        """Gain == threshold → step is triggered (>= boundary)."""
        portfolio = _portfolio_with_put()
        pos = portfolio.positions[0]
        pos.entry_premium = pos.option.price() / 2.0  # gain exactly 100%
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.steps[0].triggered is True

    def test_step_statuses_mirror_ips_schedule(self) -> None:
        """Steps list matches IPS schedule order and values."""
        portfolio = _portfolio_with_put()
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert len(plan.steps) == 3
        assert plan.steps[0].gain_pct == pytest.approx(100.0)
        assert plan.steps[1].gain_pct == pytest.approx(200.0)
        assert plan.steps[2].gain_pct == pytest.approx(400.0)
        for s in plan.steps:
            assert s.sell_pct == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# build_monetization_plan — value_to_harvest
# ---------------------------------------------------------------------------


class TestValueToHarvest:
    """value_to_harvest arithmetic tests."""

    def test_harvest_equals_recommended_pct_times_mark(self) -> None:
        """value_to_harvest == recommended_sell_pct/100 * hedge mark."""
        portfolio = _portfolio_with_put()
        pos = portfolio.positions[0]
        pos.entry_premium = pos.option.price() / 2.5  # gain ≈ 150%
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        expected_mark = pos.position_value()
        expected_harvest = (
            plan.recommended_cumulative_sell_pct / 100.0 * expected_mark
        )
        assert plan.value_to_harvest == pytest.approx(
            expected_harvest,
            rel=1e-9,
        )

    def test_zero_harvest_when_no_triggers(self) -> None:
        """No steps triggered → value_to_harvest == 0."""
        portfolio = _portfolio_with_put()
        # No entry_premium → gain None → no triggers
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.value_to_harvest == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# build_monetization_plan — gain_basis and missing cost basis
# ---------------------------------------------------------------------------


class TestGainBasis:
    """Tests for gain_basis field and graceful degradation."""

    def test_paid_when_all_premiums_known(self) -> None:
        """All positions with entry_premium → gain_basis == 'paid'."""
        portfolio = _portfolio_with_put()
        pos = portfolio.positions[0]
        pos.entry_premium = pos.option.price() / 2.5
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.gain_basis == "paid"

    def test_unknown_when_entry_premium_missing(self) -> None:
        """Missing entry_premium → gain_basis == 'unknown', no raise."""
        portfolio = _portfolio_with_put()
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.gain_basis == "unknown"
        assert plan.current_gain_pct is None

    def test_unknown_when_no_long_puts(self) -> None:
        """No long puts → gain_basis == 'unknown'."""
        portfolio = OptionPortfolio(
            spot_price=_SPOT,
            underlying_quantity=100.0,
            volatility=0.20,
            risk_free_rate=0.04,
            dividend_yield=0.015,
        )
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.gain_basis == "unknown"
        assert plan.current_gain_pct is None

    def test_no_triggers_when_gain_unknown(self) -> None:
        """Unknown gain → all steps untriggered regardless of schedule."""
        portfolio = _portfolio_with_put()
        # entry_premium not set → None
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert all(not s.triggered for s in plan.steps)
        assert plan.recommended_cumulative_sell_pct == pytest.approx(0.0)

    def test_empty_portfolio_no_raise(self) -> None:
        """Empty portfolio → MonetizationPlan returned, no exception."""
        portfolio = OptionPortfolio(
            spot_price=_SPOT,
            underlying_quantity=100.0,
            volatility=0.20,
            risk_free_rate=0.04,
            dividend_yield=0.015,
        )
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert isinstance(plan, MonetizationPlan)
        assert plan.current_gain_pct is None
        assert plan.gain_basis == "unknown"


# ---------------------------------------------------------------------------
# build_monetization_plan — remaining_sell_capacity
# ---------------------------------------------------------------------------


class TestRemainingSellCapacity:
    """Tests for remaining_sell_capacity."""

    def test_full_capacity_when_none_triggered(self) -> None:
        """No triggers → remaining == sum of all steps' sell_pct (75)."""
        portfolio = _portfolio_with_put()
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.remaining_sell_capacity == pytest.approx(75.0)

    def test_reduced_capacity_when_first_triggered(self) -> None:
        """First step triggered → remaining = 50 (steps 2 and 3 unused)."""
        portfolio = _portfolio_with_put()
        pos = portfolio.positions[0]
        pos.entry_premium = pos.option.price() / 2.5  # gain ≈ 150%
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.remaining_sell_capacity == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# build_monetization_plan — vol-spike context
# ---------------------------------------------------------------------------


class TestVolSpikeContext:
    """Tests for vol_spike_context."""

    def test_no_market_env_no_context(self) -> None:
        """market_env=None → vol_spike_context is None."""
        portfolio = _portfolio_with_put()
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert plan.vol_spike_context is None

    def test_high_regime_sets_context(self) -> None:
        """regime_label=HIGH → vol_spike_context is not None."""
        portfolio = _portfolio_with_put()
        env = _make_market_env(RegimeLabel.HIGH)
        plan = build_monetization_plan(
            portfolio,
            _THREE_STEP_IPS,
            market_env=env,
        )
        assert plan.vol_spike_context is not None
        assert "HIGH" in plan.vol_spike_context

    def test_normal_regime_no_context(self) -> None:
        """regime_label=NORMAL → vol_spike_context is None."""
        portfolio = _portfolio_with_put()
        env = _make_market_env(RegimeLabel.NORMAL)
        plan = build_monetization_plan(
            portfolio,
            _THREE_STEP_IPS,
            market_env=env,
        )
        assert plan.vol_spike_context is None

    def test_low_regime_no_context(self) -> None:
        """regime_label=LOW → vol_spike_context is None."""
        portfolio = _portfolio_with_put()
        env = _make_market_env(RegimeLabel.LOW)
        plan = build_monetization_plan(
            portfolio,
            _THREE_STEP_IPS,
            market_env=env,
        )
        assert plan.vol_spike_context is None


# ---------------------------------------------------------------------------
# Return-type contract
# ---------------------------------------------------------------------------


class TestReturnTypes:
    """Verify MonetizationPlan and MonetizationStepStatus types."""

    def test_plan_is_dataclass_instance(self) -> None:
        """build_monetization_plan always returns a MonetizationPlan."""
        portfolio = _portfolio_with_put()
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert isinstance(plan, MonetizationPlan)

    def test_steps_are_step_status_instances(self) -> None:
        """Every element of plan.steps is a MonetizationStepStatus."""
        portfolio = _portfolio_with_put()
        plan = build_monetization_plan(portfolio, _THREE_STEP_IPS)
        assert all(isinstance(s, MonetizationStepStatus) for s in plan.steps)
