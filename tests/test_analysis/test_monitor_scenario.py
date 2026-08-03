"""Tests for deltadewa.analysis.monitor_scenario.

Pins the M2.4 guarantee: at the IPS's own crash depth/vol shock,
``build_scenario`` reproduces ``crash_hedge_value`` to the cent — the same
structural agreement M2.1 established between the crash gauge and any
surface reproducing it — on a genuinely mixed-leg book (not just the
all-long-puts fixtures elsewhere in this suite).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis.crash_repricing import CrashShock, crash_hedge_value
from deltadewa.analysis.monitor_scenario import build_scenario
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

_SPOT = 6600.0
_BOOK = 20_000_000.0
_CRASH_PCT = -25.0
_VOL_SHOCK = 0.15
_SKEW = 0.10
_SKEW_ANCHOR = 0.10
_VALUATION_DATE = datetime(2026, 1, 2, tzinfo=UTC)
_MATURITY = _VALUATION_DATE + timedelta(days=round(1.5 * 365))
# (strike, contract count) three-rung put ladder.
_LEGS = ((5280.0, 23), (4620.0, 26), (3960.0, 16))


def _make_mixed_leg_book() -> OptionPortfolio:
    """A long-underlying book with a put ladder plus one short (covered) call.

    Deliberately not all-long-puts, so the pinning test exercises a book
    where an all-legs repricer and a puts-only repricer would disagree.
    """
    portfolio = OptionPortfolio(
        spot_price=_SPOT,
        volatility=0.20,
        risk_free_rate=0.045,
        dividend_yield=0.015,
        underlying_quantity=_BOOK / _SPOT,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        valuation_date=_VALUATION_DATE,
    )
    for strike, quantity in _LEGS:
        portfolio.add_position(
            strike_price=strike,
            maturity_date=_MATURITY,
            quantity=quantity,
            option_type=OptionType.PUT,
            volatility=0.20,
        )
    portfolio.add_position(
        strike_price=7260.0,
        maturity_date=_MATURITY,
        quantity=-10,
        option_type=OptionType.CALL,
        volatility=0.20,
    )
    return portfolio


def _make_ips_config() -> IpsConfig:
    """Full IpsConfig carrying the shipped skew-aware crash shock."""
    return IpsConfig(
        program=IpsProgram(name="test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=_CRASH_PCT,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_VOL_SHOCK,
            skew_steepening=_SKEW,
            skew_reference_delta=_SKEW_ANCHOR,
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=20.0),
        triggers=IpsTriggers(
            delta_drift_warn_pct=5.0,
            delta_drift_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_time_months=1.0,
            rally_rebalance_pct=15.0,
            strike_drift_max_otm_pct=45.0,
        ),
        monetization=IpsMonetization(schedule=()),
    )


class TestBuildScenarioPinning:
    """The scenario reproduces crash_hedge_value at the IPS's own point."""

    def test_pins_to_crash_hedge_value_on_mixed_leg_book(self) -> None:
        """hedge_value_shocked matches crash_hedge_value to the cent."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        result = build_scenario(
            portfolio,
            ips,
            spot_pct=ips.convexity.crash_scenario_pct,
            vol_points=ips.convexity.crash_vol_shock,
            quantity=portfolio.underlying_quantity,
        )
        expected = crash_hedge_value(
            portfolio,
            shock=CrashShock.from_ips(ips.convexity),
        )

        assert result.hedge_value_shocked == pytest.approx(
            expected,
            rel=1e-9,
        )


class TestOffsetRatio:
    """offset_ratio is undefined (None), never a fallback value, at 0 loss."""

    def test_zero_spot_move_yields_none_offset_ratio(self) -> None:
        """spot_pct=0.0 means underlying_loss == 0 -> offset_ratio is None."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        result = build_scenario(
            portfolio,
            ips,
            spot_pct=0.0,
            vol_points=ips.convexity.crash_vol_shock,
            quantity=portfolio.underlying_quantity,
        )

        assert result.underlying_loss == pytest.approx(0.0)
        assert result.offset_ratio is None


class TestQuantityDecoupling:
    """Moving the quantity dial never moves the option repricing."""

    def test_quantity_moves_carry_not_hedge_values(self) -> None:
        """carry/book_notional change with quantity; hedge_value_* do not."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        small = build_scenario(
            portfolio,
            ips,
            spot_pct=_CRASH_PCT,
            vol_points=_VOL_SHOCK,
            quantity=1_000.0,
        )
        large = build_scenario(
            portfolio,
            ips,
            spot_pct=_CRASH_PCT,
            vol_points=_VOL_SHOCK,
            quantity=5_000.0,
        )

        assert small.hedge_value_today == large.hedge_value_today
        assert small.hedge_value_shocked == large.hedge_value_shocked
        assert small.hedge_gain == large.hedge_gain
        assert small.book_notional != large.book_notional
        assert (
            small.carry.carry_pct_of_notional
            != large.carry.carry_pct_of_notional
        )


class TestNoLongPuts:
    """build_scenario does not raise on books without long puts."""

    def test_empty_portfolio_does_not_raise(self) -> None:
        """An empty portfolio (no positions at all) reprices without error."""
        portfolio = OptionPortfolio(
            spot_price=_SPOT,
            default_exercise_style=ExerciseStyle.EUROPEAN,
            valuation_date=_VALUATION_DATE,
        )
        ips = _make_ips_config()

        result = build_scenario(
            portfolio,
            ips,
            spot_pct=_CRASH_PCT,
            vol_points=_VOL_SHOCK,
            quantity=0.0,
        )

        assert result.hedge_value_today == pytest.approx(0.0)
        assert result.hedge_value_shocked == pytest.approx(0.0)

    def test_all_calls_book_does_not_raise(self) -> None:
        """A book with only (long) calls, no puts, reprices without error."""
        portfolio = OptionPortfolio(
            spot_price=_SPOT,
            volatility=0.20,
            risk_free_rate=0.045,
            dividend_yield=0.015,
            underlying_quantity=_BOOK / _SPOT,
            default_exercise_style=ExerciseStyle.EUROPEAN,
            valuation_date=_VALUATION_DATE,
        )
        portfolio.add_position(
            strike_price=7260.0,
            maturity_date=_MATURITY,
            quantity=10,
            option_type=OptionType.CALL,
            volatility=0.20,
        )
        ips = _make_ips_config()

        result = build_scenario(
            portfolio,
            ips,
            spot_pct=_CRASH_PCT,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )

        assert result.hedge_value_shocked > 0.0
