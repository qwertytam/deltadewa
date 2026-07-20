"""Tests for deltadewa.analysis.crash_repricing (M1.2 / C1).

Pins the normative crash-repricing methodology in
``docs/repricing-methodology.md``: hedge-only, repriced (not intrinsic, not
expiry), instantaneous. §4's worked example is the regression anchor; the
remaining tests guard the C1 (hedge-only) and C4 (repriced) invariants and the
single-basis consistency across the health gauge, the crash scenario table, and
the summary crash-convexity ladder.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from deltadewa.analysis import classify_portfolio_shape
from deltadewa.analysis import crash_repricing as cr
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_payoff import compute_crash_convexity
from deltadewa.analysis.health import HealthMixin
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsConvexity
from deltadewa.persistence import PortfolioSerializer
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.widgets.summary import NetHedgeSummary

# §4 worked-example crash state.
_APPENDIX_SPOT = 6600.0
_APPENDIX_BOOK = 20_000_000.0
_APPENDIX_MOVE = -0.25
_APPENDIX_VOL_SHOCK = 0.15
# (strike, contract count) for the 20/30/40%-OTM three-rung ladder.
_APPENDIX_LEGS = ((5280.0, 23), (4620.0, 26), (3960.0, 16))


def _make_appendix_book(
    *,
    underlying_quantity: float | None = None,
) -> OptionPortfolio:
    """Build the conformant $20M book from ``docs/repricing-methodology.md`` §4.

    Args:
        underlying_quantity: Override the equity leg size. Defaults to the
            share count that makes the book worth $20M at the appendix spot.

    Returns:
        A portfolio matching the appendix inputs (European puts, 18-month
        tenor, 20% flat today-vol, r=4.5%, q=1.5%).
    """
    valuation_date = datetime(2026, 1, 2, tzinfo=UTC)
    maturity = valuation_date + timedelta(days=round(1.5 * 365))
    uq = (
        _APPENDIX_BOOK / _APPENDIX_SPOT
        if underlying_quantity is None
        else underlying_quantity
    )
    portfolio = OptionPortfolio(
        spot_price=_APPENDIX_SPOT,
        volatility=0.20,
        risk_free_rate=0.045,
        dividend_yield=0.015,
        underlying_quantity=uq,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        valuation_date=valuation_date,
    )
    for strike, quantity in _APPENDIX_LEGS:
        portfolio.add_position(
            strike_price=strike,
            maturity_date=maturity,
            quantity=quantity,
            option_type=OptionType.PUT,
            volatility=0.20,
        )
    return portfolio


def _load_canonical_example() -> OptionPortfolio:
    """Load examples/portfolios/spx_protective_put.yaml (European)."""
    path = (
        Path(__file__).parent.parent.parent
        / "examples"
        / "portfolios"
        / "spx_protective_put.yaml"
    )
    result = PortfolioSerializer(Path()).import_from_yaml(
        path,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    return result["portfolio"]


def _load_golden_20m_example() -> OptionPortfolio:
    """Load examples/portfolios/spx_tail_20m.yaml — the §4 golden book."""
    path = (
        Path(__file__).parent.parent.parent
        / "examples"
        / "portfolios"
        / "spx_tail_20m.yaml"
    )
    result = PortfolioSerializer(Path()).import_from_yaml(
        path,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    return result["portfolio"]


class TestAppendixGoldenValues:
    """§7.1 — the §4 worked example reprices to the published figures."""

    def test_hedge_values_within_tolerance(self) -> None:
        """V_today and V_crash sit within ~0.5% of the §4 table."""
        portfolio = _make_appendix_book()

        v_today = cr.hedge_value(portfolio)
        v_crash = cr.crash_hedge_value(
            portfolio,
            crash_move=_APPENDIX_MOVE,
            vol_shock=_APPENDIX_VOL_SHOCK,
        )

        assert v_today == pytest.approx(297_715.0, rel=0.005)
        assert v_crash == pytest.approx(3_895_901.0, rel=0.005)

    def test_convexity_is_plus_18_pct(self) -> None:
        """Crash convexity is +18.0% ± epsilon — inside the IPS band."""
        portfolio = _make_appendix_book()

        convexity = cr.crash_convexity_pct(
            portfolio,
            crash_move=_APPENDIX_MOVE,
            vol_shock=_APPENDIX_VOL_SHOCK,
        )

        assert convexity == pytest.approx(18.0, abs=0.5)

    def test_payoff_ratio_is_about_13x(self) -> None:
        """The repriced headline payoff ratio is ~13x (not the 2.5x floor)."""
        portfolio = _make_appendix_book()
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
        )

        result = compute_crash_convexity(portfolio, ips_convexity=ips)

        assert result.payoff_ratio is not None
        assert result.payoff_ratio == pytest.approx(13.1, rel=0.02)

    def test_intrinsic_floor_is_the_conservative_759k(self) -> None:
        """The intrinsic floor (~$759k) is far below the repriced value."""
        portfolio = _make_appendix_book()

        floor = cr.crash_intrinsic_floor(portfolio, crash_move=_APPENDIX_MOVE)

        assert floor == pytest.approx(759_000.0, rel=0.005)
        assert floor < cr.crash_hedge_value(
            portfolio,
            crash_move=_APPENDIX_MOVE,
            vol_shock=_APPENDIX_VOL_SHOCK,
        )


class TestBand:
    """§7.2 (D3) — the band test anchors on the §4 fixture, not the example."""

    def test_appendix_book_meets_target_in_band(self) -> None:
        """The §4 book's -25% row is inside +15..+25% and meets_target."""
        portfolio = _make_appendix_book()
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
        )

        result = compute_crash_convexity(portfolio, ips_convexity=ips)
        ips_row = next(r for r in result.scenario_rows if r.shock_pct == -25.0)

        assert 15.0 <= ips_row.convexity_pct <= 25.0
        assert ips_row.meets_target is True


class TestGoldenExampleFile:
    """The shipped spx_tail_20m.yaml reproduces the §4 golden book on load.

    Guards the loadable demo/smoke fixture (as opposed to the in-code
    ``_make_appendix_book``): it must stay conforming and in-band so it can be
    opened in the monitor as the reference conformant book.
    """

    def test_example_is_shape_conforming(self) -> None:
        """Long underlying + long puts — the monitor shows no shape warning."""
        shape = classify_portfolio_shape(_load_golden_20m_example())
        assert shape.is_conforming is True

    def test_example_hedge_values_within_tolerance(self) -> None:
        """Loaded V_today / V_crash sit within ~0.5% of the §4 table."""
        portfolio = _load_golden_20m_example()

        v_today = cr.hedge_value(portfolio)
        v_crash = cr.crash_hedge_value(
            portfolio,
            crash_move=_APPENDIX_MOVE,
            vol_shock=_APPENDIX_VOL_SHOCK,
        )

        assert v_today == pytest.approx(297_715.0, rel=0.005)
        assert v_crash == pytest.approx(3_895_901.0, rel=0.005)

    def test_example_convexity_is_in_band(self) -> None:
        """Loaded book reprices to +18.0% ± epsilon — inside +15..+25%."""
        portfolio = _load_golden_20m_example()

        convexity = cr.crash_convexity_pct(
            portfolio,
            crash_move=_APPENDIX_MOVE,
            vol_shock=_APPENDIX_VOL_SHOCK,
        )

        assert convexity == pytest.approx(18.0, abs=0.5)
        assert 15.0 <= convexity <= 25.0


class TestHedgeOnlyInvariant:
    """§7.3 — the numerator is hedge-only (guards C1 from regressing)."""

    def test_hedge_values_independent_of_equity_leg(self) -> None:
        """Scaling the equity leg leaves V_today and V_crash unchanged."""
        base = _make_appendix_book()
        doubled = _make_appendix_book(
            underlying_quantity=base.underlying_quantity * 2,
        )

        assert cr.hedge_value(doubled) == pytest.approx(cr.hedge_value(base))
        assert cr.crash_hedge_value(
            doubled,
            crash_move=_APPENDIX_MOVE,
            vol_shock=_APPENDIX_VOL_SHOCK,
        ) == pytest.approx(
            cr.crash_hedge_value(
                base,
                crash_move=_APPENDIX_MOVE,
                vol_shock=_APPENDIX_VOL_SHOCK,
            ),
        )

    def test_convexity_scales_inversely_with_book(self) -> None:
        """A twice-as-big book halves convexity (denominator is the book)."""
        base = _make_appendix_book()
        doubled = _make_appendix_book(
            underlying_quantity=base.underlying_quantity * 2,
        )

        conv_base = cr.crash_convexity_pct(
            base,
            crash_move=_APPENDIX_MOVE,
            vol_shock=_APPENDIX_VOL_SHOCK,
        )
        conv_doubled = cr.crash_convexity_pct(
            doubled,
            crash_move=_APPENDIX_MOVE,
            vol_shock=_APPENDIX_VOL_SHOCK,
        )

        assert conv_doubled == pytest.approx(conv_base / 2.0)

    def test_empty_book_convexity_is_zero(self) -> None:
        """No equity leg -> undefined book -> convexity reads 0.0."""
        portfolio = _make_appendix_book(underlying_quantity=0.0)

        assert (
            cr.crash_convexity_pct(
                portfolio,
                crash_move=_APPENDIX_MOVE,
                vol_shock=_APPENDIX_VOL_SHOCK,
            )
            == 0.0
        )


class TestRepricedInvariant:
    """§7.4 — deep-OTM legs carry value; the floor is strictly below."""

    def test_deep_otm_legs_contribute_at_crash(self) -> None:
        """The 30% and 40%-OTM legs are worth >0 at the -25% crash."""
        portfolio = _make_appendix_book()
        crash_spot = _APPENDIX_SPOT * (1 + _APPENDIX_MOVE)

        for strike in (4620.0, 3960.0):
            leg = next(
                pos
                for pos in portfolio.positions
                if pos.option.strike_price == strike
            )
            value = cr._reprice_leg(
                leg,
                portfolio,
                crash_spot,
                leg.option.volatility + _APPENDIX_VOL_SHOCK,
            )
            assert value > 0.0

    def test_floor_below_repriced_beyond_crash_move(self) -> None:
        """For a strike still OTM after the crash, floor < repriced value."""
        portfolio = _make_appendix_book()
        crash_spot = _APPENDIX_SPOT * (1 + _APPENDIX_MOVE)
        # 3960 strike is below the crash spot (4950) -> zero intrinsic.
        leg = next(
            pos
            for pos in portfolio.positions
            if pos.option.strike_price == 3960.0
        )
        floor = cr.crash_intrinsic_floor(
            portfolio,
            crash_move=_APPENDIX_MOVE,
            positions=[leg],
        )
        repriced = cr._reprice_leg(
            leg,
            portfolio,
            crash_spot,
            leg.option.volatility + _APPENDIX_VOL_SHOCK,
        )

        assert floor == pytest.approx(0.0)
        assert floor < repriced


class TestConsistencyAcrossSurfaces:
    """§7.5 — one basis: gauge == scenario table == summary ladder."""

    def test_summary_rung_equals_health_gauge_and_helper(self) -> None:
        """The summary -20% rung equals the gauge and the helper exactly."""
        portfolio = _make_appendix_book()
        vol_shock = _APPENDIX_VOL_SHOCK

        summary = NetHedgeSummary(portfolio, crash_vol_shock=vol_shock)
        rungs = dict(summary._crash_convexity_rungs())

        analyzer = PortfolioAnalyzer(portfolio)
        gauge = analyzer.calculate_crash_convexity_pct(
            crash_scenario_pct=-20.0,
            crash_vol_shock=vol_shock,
        )
        helper = cr.crash_convexity_pct(
            portfolio,
            crash_move=-0.20,
            vol_shock=vol_shock,
        )

        assert rungs[-20.0] == pytest.approx(gauge)
        assert rungs[-20.0] == pytest.approx(helper)

    def test_scenario_table_convexity_equals_gauge(self) -> None:
        """The scenario table's convexity column matches the health gauge."""
        portfolio = _make_appendix_book()
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
        )

        result = compute_crash_convexity(portfolio, ips_convexity=ips)
        ips_row = next(r for r in result.scenario_rows if r.shock_pct == -25.0)
        gauge = PortfolioAnalyzer(portfolio).calculate_crash_convexity_pct(
            crash_scenario_pct=-25.0,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
        )

        assert ips_row.convexity_pct == pytest.approx(gauge)


class TestNoLegacyBasisInConvexityPaths:
    """§7.5 grep guard — the equity-netted expiry basis is gone (scoped).

    Scoped to the convexity code paths, not whole files: hedge_success
    (M2.4/#70) and the summary net "P&L @ -20%" indicator legitimately retain
    ``include_underlying`` and are out of this milestone's scope.
    """

    def test_health_gauge_source_is_repriced(self) -> None:
        """calculate_crash_convexity_pct drops the old expiry/equity basis."""
        source = inspect.getsource(
            HealthMixin.calculate_crash_convexity_pct,
        )

        assert "include_underlying" not in source
        assert "calculate_pnl_at_expiry" not in source

    def test_summary_ladder_source_is_repriced(self) -> None:
        """The summary crash-convexity ladder drops the old basis."""
        source = inspect.getsource(
            NetHedgeSummary._crash_convexity_rungs,
        )

        assert "include_underlying" not in source
        assert "calculate_pnl_at_expiry" not in source

    def test_crash_payoff_headline_source_is_repriced(self) -> None:
        """compute_crash_convexity's headline drops the old basis."""
        source = inspect.getsource(compute_crash_convexity)

        assert "include_underlying" not in source
        assert "calculate_pnl_at_expiry" not in source

    def test_crash_vol_shock_is_required_on_the_gauge(self) -> None:
        """crash_vol_shock has no default — every caller must pass it.

        Making it required is the enforcement point: no site (gauge, roll
        trigger, summary ladder) can silently reprice spot-only by omission.
        """
        param = inspect.signature(
            HealthMixin.calculate_crash_convexity_pct,
        ).parameters["crash_vol_shock"]

        assert param.default is inspect.Parameter.empty

    def test_roll_status_sources_vol_shock_from_ips(self) -> None:
        """The roll trigger passes the IPS vol shock, matching the gauge."""
        source = inspect.getsource(evaluate_roll_status)

        assert "crash_vol_shock=convexity.crash_vol_shock" in source


class TestCanonicalExampleInvariants:
    """§7 — invariants only on spx_protective_put.yaml (not the band).

    Measured corrected convexity at the IPS scenario (-25%, vol_shock 0.15) is
    ~+14.3% of the ~$5.8M book — positive, hedge-only, and repriced, but a
    touch below the +15..+25% band floor. That marginal under-sizing is an
    M1.4 (Mo3) re-sizing item; it is deliberately not re-sized here.
    """

    def test_convexity_is_positive(self) -> None:
        """The corrected convexity is positive (hedge gains in a crash)."""
        portfolio = _load_canonical_example()

        convexity = cr.crash_convexity_pct(
            portfolio,
            crash_move=-0.25,
            vol_shock=0.15,
        )

        assert convexity > 0.0

    def test_hedge_only_invariant(self) -> None:
        """Removing the equity leg leaves the hedge value unchanged."""
        portfolio = _load_canonical_example()
        before = cr.hedge_value(portfolio)
        portfolio.underlying_quantity = 0.0

        assert cr.hedge_value(portfolio) == pytest.approx(before)

    def test_repriced_legs_positive_at_crash(self) -> None:
        """Every put leg is worth >0 at the -25% crash (repriced)."""
        portfolio = _load_canonical_example()
        crash_spot = portfolio.spot_price * 0.75

        for pos in portfolio.positions:
            value = cr._reprice_leg(
                pos,
                portfolio,
                crash_spot,
                pos.option.volatility + 0.15,
            )
            assert value > 0.0
