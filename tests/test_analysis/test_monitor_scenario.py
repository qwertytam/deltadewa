"""Tests for deltadewa.analysis.monitor_scenario.

Pins the M2.4 guarantee: at the IPS's own crash depth/vol shock,
``build_scenario`` reproduces ``crash_hedge_value`` to the cent — the same
structural agreement M2.1 established between the crash gauge and any
surface reproducing it — on a genuinely mixed-leg book (not just the
all-long-puts fixtures elsewhere in this suite).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_convexity_pct,
    crash_hedge_value,
    crash_value_curve,
)
from deltadewa.analysis.hedge_efficiency import EfficiencyVerdict
from deltadewa.analysis.monitor_scenario import (
    _OFFSET_RATIO_MATERIAL_SHOCK_PCT,
    build_scenario,
    build_scenario_curve,
)
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
        assert small.carry.theta_annual == large.carry.theta_annual


class TestHedgeEfficiency:
    """The scenario carries the Part X #5/#15 ratio, on the same basis."""

    def test_ratio_is_hedge_gain_over_absolute_carry(self) -> None:
        """The dollar form, straight off the two terms already on the result."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        result = build_scenario(
            portfolio,
            ips,
            spot_pct=_CRASH_PCT,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )

        assert result.efficiency.ratio == pytest.approx(
            result.hedge_gain / abs(result.carry.theta_annual),
            rel=1e-12,
        )

    def test_dollar_and_percentage_forms_are_the_same_number(self) -> None:
        """#5 and #15 are one metric, not two.

        The handbook states the ratio in dollars (`HER Metric
        <https://qwertytam.github.io/deltadewa-handbook/0.1/part-6/hedge-efficiency-ratio/#her-metric>`_)
        and in percentages (`Mathematical Definition of the Ratio
        <https://qwertytam.github.io/deltadewa-handbook/0.1/part-6/hedge-efficiency-ratio/#mathematical-definition-of-the-ratio>`_).
        Both percentages here normalize by the same protected book, so the
        normalizer cancels — this pins that identity rather than leaving it
        as a docstring claim.

        Both links are pinned to handbook version 0.1: what this test asserts
        is that the handbook's two stated forms are one number, so it has to
        keep citing the two statements it was written against. Drop the
        ``/0.1/`` segment for the current pages.
        """
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        result = build_scenario(
            portfolio,
            ips,
            spot_pct=ips.convexity.crash_scenario_pct,
            vol_points=ips.convexity.crash_vol_shock,
            quantity=portfolio.underlying_quantity,
        )

        convexity_pct = crash_convexity_pct(
            portfolio,
            shock=CrashShock.from_ips(ips.convexity),
        )
        percentage_form = convexity_pct / result.carry.carry_pct_of_notional

        assert result.efficiency.ratio == pytest.approx(
            percentage_form,
            rel=1e-9,
        )

    def test_band_comes_from_the_ips_not_a_literal(self) -> None:
        """A program running a different mandate gets a different reading."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()
        default = build_scenario(
            portfolio,
            ips,
            spot_pct=_CRASH_PCT,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )
        assert default.efficiency.ratio is not None
        # A band this book cannot reach, derived from its own ratio rather
        # than a literal — the fixture's carry is small enough that any
        # fixed band would be a guess about the resulting magnitude.
        unreachable = default.efficiency.ratio * 10
        strict = dataclasses.replace(
            ips,
            convexity=dataclasses.replace(
                ips.convexity,
                efficiency_min_ratio=unreachable,
                efficiency_max_ratio=unreachable * 2,
            ),
        )

        demanding = build_scenario(
            portfolio,
            strict,
            spot_pct=_CRASH_PCT,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )

        assert default.efficiency.ratio == pytest.approx(
            demanding.efficiency.ratio,
        )
        assert demanding.efficiency.verdict is EfficiencyVerdict.POOR
        assert default.efficiency.verdict is not EfficiencyVerdict.POOR

    def test_quantity_dial_does_not_move_the_ratio(self) -> None:
        """Neither term depends on the scenario book, so the ratio doesn't."""
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

        assert small.efficiency.ratio == pytest.approx(large.efficiency.ratio)

    def test_shallower_shock_gives_a_smaller_ratio(self) -> None:
        """The ratio is scenario-local — the spot dial moves it, by design."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        shallow = build_scenario(
            portfolio,
            ips,
            spot_pct=-5.0,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )
        crash = build_scenario(
            portfolio,
            ips,
            spot_pct=_CRASH_PCT,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )

        assert shallow.efficiency.ratio is not None
        assert crash.efficiency.ratio is not None
        assert shallow.efficiency.ratio < crash.efficiency.ratio


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


class TestBuildScenarioCurve:
    """The four-series scenario curve: shape, sign convention, agreement."""

    def test_returns_documented_series_per_point(self) -> None:
        """Every point exposes all six documented fields."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        curve = build_scenario_curve(
            portfolio,
            ips,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )

        assert curve
        for point in curve:
            assert isinstance(point.shock_pct, float)
            assert isinstance(point.shocked_spot_price, float)
            assert isinstance(point.hedge_value, float)
            assert isinstance(point.underlying_loss, float)
            assert isinstance(point.net, float)
            assert point.offset_ratio is None or isinstance(
                point.offset_ratio,
                float,
            )

    def test_underlying_loss_is_negative_on_a_down_shock(self) -> None:
        """Sign convention: underlying_loss is negative P&L on a down move."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        curve = build_scenario_curve(
            portfolio,
            ips,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )

        down_shocks = [point for point in curve if point.shock_pct < -1.0]
        assert down_shocks
        assert all(point.underlying_loss < 0.0 for point in down_shocks)

    def test_hedge_value_matches_crash_value_curve(self) -> None:
        """hedge_value is crash_value_curve's value, not a reimplementation."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        curve = build_scenario_curve(
            portfolio,
            ips,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )
        base_shock = CrashShock.from_ips(ips.convexity)
        expected = dict(
            crash_value_curve(
                portfolio,
                shock=dataclasses.replace(
                    base_shock,
                    crash_vol_shock=_VOL_SHOCK,
                ),
            ),
        )

        for point in curve:
            assert point.hedge_value == pytest.approx(
                expected[point.shock_pct],
                rel=1e-9,
            )

    def test_shocked_spot_price_matches_spot_times_shock(self) -> None:
        """shocked_spot_price is spot * (1 + shock_pct/100), per point."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        curve = build_scenario_curve(
            portfolio,
            ips,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )

        for point in curve:
            expected = portfolio.spot_price * (1.0 + point.shock_pct / 100.0)
            assert point.shocked_spot_price == pytest.approx(expected)

    def test_offset_ratio_none_near_zero_shock(self) -> None:
        """offset_ratio is None near 0% shock, real away from it."""
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        curve = build_scenario_curve(
            portfolio,
            ips,
            vol_points=_VOL_SHOCK,
            quantity=portfolio.underlying_quantity,
        )

        near_zero = [
            point
            for point in curve
            if abs(point.shock_pct) < _OFFSET_RATIO_MATERIAL_SHOCK_PCT
        ]
        assert near_zero
        assert all(point.offset_ratio is None for point in near_zero)

        away_from_zero = [
            point
            for point in curve
            if abs(point.shock_pct) >= _OFFSET_RATIO_MATERIAL_SHOCK_PCT
        ]
        assert away_from_zero
        assert all(point.offset_ratio is not None for point in away_from_zero)

    def test_agrees_with_build_scenario_at_matching_point(self) -> None:
        """A single-point curve at the dial's own pct matches build_scenario.

        Mirrors the explorer-equals-gauge pinning: the curve and the
        single-point scenario explorer must never disagree at the same
        (spot_pct, vol_points, quantity).
        """
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()
        quantity = portfolio.underlying_quantity

        (point,) = build_scenario_curve(
            portfolio,
            ips,
            vol_points=_VOL_SHOCK,
            quantity=quantity,
            shock_range=(_CRASH_PCT, _CRASH_PCT),
            n_points=1,
        )
        result = build_scenario(
            portfolio,
            ips,
            spot_pct=_CRASH_PCT,
            vol_points=_VOL_SHOCK,
            quantity=quantity,
        )

        assert point.net == pytest.approx(result.net, rel=1e-9)
        assert point.offset_ratio == pytest.approx(
            result.offset_ratio,
            rel=1e-9,
        )

    def test_recomputes_with_quantity(self) -> None:
        """underlying_loss/net/offset_ratio scale with qty; hedge_value not.

        Pins the (c) regression: the curve must recompute when the quantity
        dial moves, not just the numbers panel.
        """
        portfolio = _make_mixed_leg_book()
        ips = _make_ips_config()

        small = build_scenario_curve(
            portfolio,
            ips,
            vol_points=_VOL_SHOCK,
            quantity=1_000.0,
        )
        large = build_scenario_curve(
            portfolio,
            ips,
            vol_points=_VOL_SHOCK,
            quantity=5_000.0,
        )

        for small_point, large_point in zip(small, large, strict=True):
            assert small_point.hedge_value == pytest.approx(
                large_point.hedge_value,
            )
            if abs(small_point.shock_pct) >= _OFFSET_RATIO_MATERIAL_SHOCK_PCT:
                assert small_point.underlying_loss != pytest.approx(
                    large_point.underlying_loss,
                )
                assert small_point.net != pytest.approx(large_point.net)
