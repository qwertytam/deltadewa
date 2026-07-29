"""Tests for deltadewa.analysis.repricing — the M2.1 shared seam.

``test_crash_repricing.py`` pins the crash policy/basis and skew methodology
(§4 worked example, wing anchoring, IPS provenance). This module pins the
*seam* those goldens now sit on top of: the general
:class:`~deltadewa.analysis.repricing.MarketShock` /
:class:`~deltadewa.analysis.repricing.MarketState` / ``VolMapping``
plumbing, cross-path agreement between the crash gauge and the general
scenario grid, the mappings' distinctness on a non-flat book, and the
cache/``days_forward`` wiring the fixed state leak now depends on.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from deltadewa.analysis import crash_repricing as cr
from deltadewa.analysis import scenarios as scenarios_module
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.cache import (
    ScenarioGridCache,
    create_spot_vol_cache_key,
    get_portfolio_state_hash,
)
from deltadewa.analysis.crash_repricing import CrashShock, crash_skew_vol
from deltadewa.analysis.repricing import (
    MarketShock,
    MarketState,
    flat_bump_vol,
    proportional_vol,
    reprice_leg,
    reprice_portfolio,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.dashboard import stress as stress_module
from deltadewa.persistence import PortfolioSerializer
from deltadewa.portfolio.core import OptionPortfolio

# Same fixture, same as-of date, and the same shock knobs as the M2.1
# planning measurement (spot -25%, vol +0.15, skew +0.10 @ 10-delta) — the
# golden crash values pinned below (0.4446 / 0.4500 / 0.4500,
# $5,226,004.24) are that measurement, not independently re-derived here.
_GOLDEN_AS_OF = datetime(2026, 7, 26, tzinfo=UTC)
_GOLDEN_SHOCK = CrashShock(
    crash_scenario_pct=-25.0,
    crash_vol_shock=0.15,
    skew_steepening=0.10,
    skew_reference_delta=0.10,
)


def _load_golden_book() -> OptionPortfolio:
    """Load examples/portfolios/spx_tail_20m.yaml, pinned to the golden date."""
    path = (
        Path(__file__).parent.parent.parent
        / "examples"
        / "portfolios"
        / "spx_tail_20m.yaml"
    )
    result = PortfolioSerializer(Path()).import_from_yaml(
        path,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        valuation_date=_GOLDEN_AS_OF,
    )
    return result["portfolio"]


class TestCrashSkewVolNoOpProof:
    """crash_skew_vol, called directly through its public factory (not the
    legacy _leg_crash_vol shim), reproduces the pinned §4 golden crash vols
    to the cent — proof the M2.1 extraction preserved the skew calibration
    every generic entry point now shares with the crash gauge.
    """

    def test_matches_golden_appendix_crash_vols(self) -> None:
        """Golden rungs: base 0.35 (0.20 + 0.15) plus per-leg wing
        steepening. The two deeper rungs sit at/beyond their own ~10-delta
        wing and cap at the full +0.10."""
        portfolio = _load_golden_book()
        state = MarketState.from_portfolio(portfolio)
        mapping = crash_skew_vol(
            skew_steepening=_GOLDEN_SHOCK.skew_steepening,
            skew_reference_delta=_GOLDEN_SHOCK.skew_reference_delta,
        )
        shock = _GOLDEN_SHOCK.to_shock()

        crash_vols = {
            pos.option.strike_price: mapping(pos, state, shock)
            for pos in portfolio.positions
        }

        assert crash_vols[5280.0] == pytest.approx(0.4446, abs=0.0015)
        assert crash_vols[4620.0] == pytest.approx(0.4500, abs=1e-9)
        assert crash_vols[3960.0] == pytest.approx(0.4500, abs=1e-9)

    def test_caps_at_a_strike_materially_deeper_than_the_wing(self) -> None:
        """A strike well beyond the wing still caps at skew_steepening —
        exercises the min() in _CrashSkewVolMapping.__call__, through the
        public factory rather than the internal class."""
        portfolio = _load_golden_book()
        maturity = portfolio.positions[0].option.maturity_date
        k_wing = cr._solve_wing_strike(
            spot=portfolio.spot_price,
            maturity_date=maturity,
            volatility=0.20,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            valuation_date=portfolio.valuation_date,
            anchor_delta=_GOLDEN_SHOCK.skew_reference_delta,
        )
        portfolio.add_position(
            strike_price=k_wing * 0.7,  # materially deeper than the wing
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.PUT,
            volatility=0.20,
        )
        deep_leg = portfolio.positions[-1]

        state = MarketState.from_portfolio(portfolio)
        mapping = crash_skew_vol(
            skew_steepening=_GOLDEN_SHOCK.skew_steepening,
            skew_reference_delta=_GOLDEN_SHOCK.skew_reference_delta,
        )
        shock = MarketShock(
            spot_shock=0.0,
            vol_shock=_GOLDEN_SHOCK.crash_vol_shock,
        )

        vol = mapping(deep_leg, state, shock)

        expected = (
            0.20 + _GOLDEN_SHOCK.crash_vol_shock + _GOLDEN_SHOCK.skew_steepening
        )
        assert vol == pytest.approx(expected, abs=1e-9)


class TestReprisePortfolioAgreesWithCrashHedgeValue:
    """reprice_portfolio(shock=cs.to_shock(), vol_mapping=cs.vol_mapping())
    reproduces crash_hedge_value(portfolio, shock=cs) to the cent — the
    structural guarantee that makes the monitor's crash-anchored explorer
    and the crash gauge agree (M2.1's whole point).
    """

    def test_agrees_to_the_cent_at_the_ips_crash_point(self) -> None:
        portfolio = _load_golden_book()

        via_crash_hedge_value = cr.crash_hedge_value(
            portfolio,
            shock=_GOLDEN_SHOCK,
        )
        via_reprice_portfolio = reprice_portfolio(
            portfolio,
            shock=_GOLDEN_SHOCK.to_shock(),
            vol_mapping=_GOLDEN_SHOCK.vol_mapping(),
        )

        assert via_reprice_portfolio == pytest.approx(
            via_crash_hedge_value,
            abs=0.005,
        )
        # And matches the M2.1 planning measurement to the cent.
        assert via_crash_hedge_value == pytest.approx(5_226_004.24, abs=0.5)


class TestMappingsDistinguishOnASkewedBook:
    """The flat-20% golden cannot tell proportional from flat-set (measured
    identical during M2.1 planning) — a skewed surface is required to prove
    the three mappings are actually different rules, not aliases.
    """

    def test_three_mappings_give_three_different_values(self) -> None:
        portfolio = _load_golden_book()
        skewed_vols = {5280.0: 0.30, 4620.0: 0.25, 3960.0: 0.20}
        for pos in portfolio.positions:
            pos.option.update_volatility(skewed_vols[pos.option.strike_price])

        shock = MarketShock(spot_shock=-0.25, vol_shock=0.15)
        mapping_crash = crash_skew_vol(
            skew_steepening=0.10,
            skew_reference_delta=0.10,
        )

        v_flat = reprice_portfolio(
            portfolio,
            shock=shock,
            vol_mapping=flat_bump_vol,
        )
        v_crash = reprice_portfolio(
            portfolio,
            shock=shock,
            vol_mapping=mapping_crash,
        )
        v_prop = reprice_portfolio(
            portfolio,
            shock=shock,
            vol_mapping=proportional_vol,
        )

        assert v_flat != pytest.approx(v_prop, rel=1e-6)
        assert v_flat != pytest.approx(v_crash, rel=1e-6)
        assert v_crash != pytest.approx(v_prop, rel=1e-6)

        # flat_bump_vol checked against its own closed form: sigma_i + vol_shock
        # per leg, independent of any mapping under test.
        state = MarketState.from_portfolio(portfolio)
        shocked_spot = shock.shocked_spot(state)
        shocked_date = shock.shocked_valuation_date(state)
        expected_flat = sum(
            reprice_leg(
                pos,
                state,
                spot=shocked_spot,
                volatility=pos.option.volatility + shock.vol_shock,
                valuation_date=shocked_date,
            )
            for pos in portfolio.positions
        )
        assert v_flat == pytest.approx(expected_flat, abs=0.01)

        # proportional_vol checked against its own closed form: every leg
        # scaled by the same factor so the vega-weighted average moves by
        # vol_shock.
        target_avg = state.avg_volatility + shock.vol_shock
        scale = target_avg / state.avg_volatility
        expected_prop = sum(
            reprice_leg(
                pos,
                state,
                spot=shocked_spot,
                volatility=pos.option.volatility * scale,
                valuation_date=shocked_date,
            )
            for pos in portfolio.positions
        )
        assert v_prop == pytest.approx(expected_prop, abs=0.01)

        # crash_skew_vol at skew_steepening=0.0 must reproduce flat_bump_vol
        # bit-for-bit (documented invariant of _CrashSkewVolMapping) — a
        # second, independent closed form for the crash-conditional mapping.
        mapping_crash_zero = crash_skew_vol(
            skew_steepening=0.0,
            skew_reference_delta=0.10,
        )
        v_crash_zero = reprice_portfolio(
            portfolio,
            shock=shock,
            vol_mapping=mapping_crash_zero,
        )
        assert v_crash_zero == pytest.approx(v_flat, abs=0.01)


class TestReprisePortfolioNeverMutates:
    """reprice_portfolio must leave the portfolio exactly as it found it —
    the whole point of replacing the mutate-then-restore grid."""

    def test_portfolio_state_hash_unchanged_after_reprice(self) -> None:
        portfolio = _load_golden_book()
        before = get_portfolio_state_hash(portfolio)

        reprice_portfolio(
            portfolio,
            shock=MarketShock(
                spot_shock=-0.25,
                vol_shock=0.15,
                days_forward=30,
            ),
            vol_mapping=proportional_vol,
        )

        after = get_portfolio_state_hash(portfolio)
        assert before == after


class TestDaysForwardMovesTheValuationDate:
    """days_forward must move the reprice to the correct date without
    mutating the portfolio — the dial that designs out the M1.5 state
    leak (see also test_stress.py's leak-freedom render test)."""

    def test_matches_a_portfolio_already_advanced_to_that_date(self) -> None:
        """Repricing today's portfolio with days_forward=45 must exactly
        match repricing a portfolio whose valuation_date was already
        advanced 45 days, under a mapping (flat_bump_vol) with no
        base-state averaging dependency to complicate the comparison."""
        portfolio_today = _load_golden_book()
        portfolio_advanced = _load_golden_book()
        portfolio_advanced.update_market_conditions(
            valuation_date=portfolio_advanced.valuation_date
            + timedelta(days=45),
        )

        v_via_days_forward = reprice_portfolio(
            portfolio_today,
            shock=MarketShock(
                spot_shock=-0.10,
                vol_shock=0.05,
                days_forward=45,
            ),
            vol_mapping=flat_bump_vol,
        )
        v_via_advanced_portfolio = reprice_portfolio(
            portfolio_advanced,
            shock=MarketShock(spot_shock=-0.10, vol_shock=0.05),
            vol_mapping=flat_bump_vol,
        )

        assert v_via_days_forward == pytest.approx(
            v_via_advanced_portfolio,
            rel=1e-9,
        )


class TestCacheKeyingCoversMappingAndDaysForward:
    """Once the state leak stopped smuggling days_forward through a mutated
    valuation_date, the cache key must carry it explicitly — otherwise a
    T+0 and a T+60 grid collide. Likewise two different mappings must
    never share a cache entry.
    """

    def test_different_days_forward_do_not_collide(self) -> None:
        portfolio = _load_golden_book()
        state_hash = get_portfolio_state_hash(portfolio)
        spot_scenarios = np.array([6600.0])
        vol_scenarios = np.array([0.20])

        key_t0 = create_spot_vol_cache_key(
            spot_scenarios,
            vol_scenarios,
            "value",
            state_hash,
            proportional_vol,
            0,
        )
        key_t60 = create_spot_vol_cache_key(
            spot_scenarios,
            vol_scenarios,
            "value",
            state_hash,
            proportional_vol,
            60,
        )

        assert key_t0 != key_t60

    def test_different_mappings_do_not_collide(self) -> None:
        portfolio = _load_golden_book()
        state_hash = get_portfolio_state_hash(portfolio)
        spot_scenarios = np.array([6600.0])
        vol_scenarios = np.array([0.20])
        mapping_crash = crash_skew_vol(
            skew_steepening=0.10,
            skew_reference_delta=0.10,
        )

        key_flat = create_spot_vol_cache_key(
            spot_scenarios,
            vol_scenarios,
            "value",
            state_hash,
            flat_bump_vol,
            0,
        )
        key_crash = create_spot_vol_cache_key(
            spot_scenarios,
            vol_scenarios,
            "value",
            state_hash,
            mapping_crash,
            0,
        )

        assert key_flat != key_crash

    def test_end_to_end_cache_does_not_collide_at_t60(self) -> None:
        """A real cache must not share one entry across T+0 and T+60.

        ScenarioGridCache.get_or_calculate_spot_vol at T+0 and T+60 must
        independently compute and store two entries with two different
        results.
        """
        portfolio = _load_golden_book()
        analyzer = PortfolioAnalyzer(portfolio)
        cache = ScenarioGridCache()

        spot_scenarios = np.array([6400.0, 6600.0, 6800.0])
        vol_scenarios = np.array([0.20, 0.30])

        grid_t0 = cache.get_or_calculate_spot_vol(
            portfolio=portfolio,
            analyzer=analyzer,
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            vol_mapping=proportional_vol,
            metric="value",
            days_forward=0,
        )
        size_after_t0 = cache.size()

        grid_t60 = cache.get_or_calculate_spot_vol(
            portfolio=portfolio,
            analyzer=analyzer,
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            vol_mapping=proportional_vol,
            metric="value",
            days_forward=60,
        )
        size_after_t60 = cache.size()

        assert size_after_t60 > size_after_t0
        assert not np.allclose(
            grid_t0["value"].to_numpy(),
            grid_t60["value"].to_numpy(),
        )


class TestNoMutationSurvivesInTheScenarioPath:
    """M2.1 deleted the mutate-then-restore path entirely; guard against a
    regression reintroducing a portfolio.valuation_date assignment in
    either the pure grid or the dashboard render it backs.
    """

    @staticmethod
    def _valuation_date_assignments(node: ast.AST) -> list[ast.Attribute]:
        return [
            target
            for child in ast.walk(node)
            if isinstance(child, ast.Assign)
            for target in child.targets
            if isinstance(target, ast.Attribute)
            and target.attr == "valuation_date"
        ]

    def test_scenarios_module_never_assigns_valuation_date(self) -> None:
        tree = ast.parse(
            Path(scenarios_module.__file__).read_text(encoding="utf-8"),
        )
        assert not self._valuation_date_assignments(tree), (
            "scenarios.py must never assign .valuation_date — the pure "
            "grid derives the shocked date from MarketShock.days_forward "
            "instead of mutating the portfolio"
        )

    def test_render_spot_vol_heatmap_never_assigns_valuation_date(self) -> None:
        tree = ast.parse(
            Path(stress_module.__file__).read_text(encoding="utf-8"),
        )
        render_fn = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_render_spot_vol_heatmap"
        )
        assert not self._valuation_date_assignments(render_fn), (
            "_render_spot_vol_heatmap must never assign "
            "portfolio.valuation_date — this is the exact former state-leak "
            "site (stress.py:897-920), now designed out rather than patched"
        )
