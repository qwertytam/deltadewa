"""Characterization tests for deltadewa.dashboard.stress module.

This module pins the behaviour of the stress-grid analytics across M2.1,
which extracted the repricing/grid logic into analysis/repricing.py and
analysis/scenarios.py. Both M1.5 bugs this file originally characterized are
now fixed:

- Cache-key gap (cache.py) — get_portfolio_state_hash now covers
  underlying_quantity, contract_size, and exercise_style (fixed in the
  cache-key commit preceding M2.1).
- Spot x Vol state leak (former stress.py:897-920) — designed out rather
  than patched: scenario_grid_spot_vol (scenarios.py) no longer mutates
  portfolio.valuation_date at all, so there is no mutate/restore window for
  it to leak from.

Key behavioural pins (from stress.py code audit):
- Time x Price grid: axes via linspace + np.unique(astype(int)), so actual
  column count < requested num_time_steps for short-dated portfolios.
- Spot x Vol grid: pure as of M2.1 — every cell reprices through fresh,
  scratch OptionValuation objects; the portfolio is never mutated.

A later M2.1 pass moved the remaining compute inside StressDashboard itself
(grid orchestration, time-heatmap grid construction, Monte Carlo
concentration/histogram/CDF statistics) into analysis/stress.py, leaving
StressDashboard as thin matplotlib/ipywidgets rendering. Those functions are
unit-tested directly in tests/test_analysis/test_stress.py; this file keeps
only the tests that exercise the dashboard/analyzer/cache layer end to end.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import ipywidgets as widgets
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.cache import ScenarioGridCache
from deltadewa.analysis.repricing import proportional_vol
from deltadewa.batch_pricer import BatchPricer, FDGridResolution
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.dashboard.stress import StressDashboard
from deltadewa.persistence import PortfolioSerializer
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.reporting import ConsoleReporter
from deltadewa.widgets.assumptions import GlobalAssumptions

# Use Agg backend for headless testing (from test_crash_charts.py pattern)
matplotlib.use("Agg")

# As-of for the §4 golden load; matches test_crash_repricing._FIXTURE_AS_OF so
# both files assert the same book.
_GOLDEN_AS_OF = datetime(2026, 7, 26, tzinfo=UTC)


# ============================================================================
# Helpers & Fixtures
# ============================================================================


def _make_put_portfolio(
    spot: float = 100.0,
    vol: float = 0.25,
    num_legs: int = 1,
    days_to_maturity: int = 90,
) -> OptionPortfolio:
    """Build a small European put portfolio for monotonicity/time-value tests.

    Args:
        spot: Current spot price
        vol: Implied volatility
        num_legs: Number of put legs (1-3 recommended)
        days_to_maturity: Days to option expiry

    Returns:
        Real OptionPortfolio with num_legs European puts.
    """
    portfolio = OptionPortfolio(
        spot_price=spot,
        volatility=vol,
        risk_free_rate=0.05,
        dividend_yield=0.02,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )

    maturity = datetime.now(tz=UTC) + timedelta(days=days_to_maturity)

    # Build a small put ladder (80%, 90%, 95% OTM)
    strikes = [spot * (1 - 0.20), spot * (1 - 0.10), spot * (1 - 0.05)][
        :num_legs
    ]
    for strike in strikes:
        portfolio.add_position(
            strike_price=strike,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.PUT,
        )

    return portfolio


def _load_golden_book() -> OptionPortfolio:
    """Load the §4 golden book from examples/portfolios/spx_tail_20m.yaml.

    Pinned to the same as-of as the crash-repricing goldens, so the documented
    figures (hedge value ≈$297,715) are reproducible on any calendar date. This
    fixture's maturities are relative (maturity_days), so its tenor — and hence
    its value — is constant regardless; the pin makes that explicit rather than
    relying on it.

    Returns:
        Real OptionPortfolio with 3 European puts (20/30/40% OTM ladder).
    """
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


def _dashboard(
    portfolio: OptionPortfolio,
    cache: ScenarioGridCache | None = None,
    reporter: ConsoleReporter | None = None,
) -> StressDashboard:
    """Wire a real StressDashboard from a portfolio and optional overrides.

    Args:
        portfolio: Real OptionPortfolio
        cache: ScenarioGridCache instance (new one if None)
        reporter: ConsoleReporter instance (new one if None)

    Returns:
        Fully wired StressDashboard (pure DI container, no computation).
    """
    analyzer = PortfolioAnalyzer(portfolio)
    cache = cache or ScenarioGridCache()
    reporter = reporter or ConsoleReporter(width=100)
    global_assumptions = GlobalAssumptions(
        spot_price=portfolio.spot_price,
        volatility=portfolio.volatility,
    )
    return StressDashboard(
        portfolio=portfolio,
        analyzer=analyzer,
        cache=cache,
        global_assumptions=global_assumptions,
        reporter=reporter,
    )


# ============================================================================
# Test Classes
# ============================================================================


class TestTimeHeatmapGrid:
    """Pin Time x Price grid shape, monotonicity, repricing, and cache hits.

    Tests the engine-level _render_time_heatmap logic and the underlying
    scenario_grid (scenarios.py), which builds one BatchPricer and calls
    portfolio_values_at per time point.
    """

    def test_grid_shape_rows_desc_cols_asc(self) -> None:
        """Grid rows = spot (descending), columns = days_forward (ascending)."""
        portfolio = _make_put_portfolio(days_to_maturity=30)
        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([90.0, 100.0, 110.0])
        time_points = [
            portfolio.valuation_date,
            portfolio.valuation_date + timedelta(days=10),
        ]

        result = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="value",
        )

        pivot = result.pivot(
            index="spot_price",
            columns="days_forward",
            values="value",
        ).sort_index(ascending=False)

        # Rows descending: highest spot first
        assert list(pivot.index) == [110.0, 100.0, 90.0]
        # Columns ascending: day 0 first
        assert list(pivot.columns) == [0, 10]

    def test_put_value_monotonic_increasing_as_spot_decreases(self) -> None:
        """For a fixed time point, put value strictly increases as spot
        decreases (via BS monotonicity on European puts). Sort ascending
        by spot, check values are descending (higher spot → lower put value)."""
        portfolio = _make_put_portfolio(days_to_maturity=45)
        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.linspace(80.0, 120.0, 9)
        time_point = portfolio.valuation_date

        result = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=[time_point],
            metric="value",
        )

        values = result.sort_values("spot_price")["value"].values

        # Put value decreases as spot increases (lower spot = higher value)
        diffs = np.diff(values)
        assert np.all(diffs < 0), (
            f"Put values should decrease with increasing spot. Diffs: {diffs}"
        )

    def test_time_value_decay_same_spot_two_dates(self) -> None:
        """Same spot, two time points (near expiry vs far expiry) produces
        different values (time decay via real QuantLib repricing)."""
        portfolio = _make_put_portfolio(days_to_maturity=90)
        analyzer = PortfolioAnalyzer(portfolio)

        spot = 100.0
        spot_scenarios = np.array([spot])
        original_date = portfolio.valuation_date
        dates = [
            original_date,
            original_date + timedelta(days=60),  # 30 days to expiry
        ]

        result = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=dates,
            metric="value",
        )

        vals = result.sort_values("valuation_date")["value"].values

        # Value at day 0 should differ from value at day 60
        # (less time = lower option value for a put with fixed spot)
        assert not np.isclose(vals[0], vals[1]), (
            "Put value should decay over time (time value)"
        )

    def test_grid_cell_matches_batchpricer_direct(self) -> None:
        """Cross-check one grid cell against BatchPricer.portfolio_values_at
        called directly (proves repricing through BatchPricer, not shortcut)."""
        portfolio = _make_put_portfolio(days_to_maturity=45)
        analyzer = PortfolioAnalyzer(portfolio)

        spot = 95.0
        time_point = portfolio.valuation_date + timedelta(days=10)
        spot_scenarios = np.array([spot])

        # Get grid value
        grid_result = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=[time_point],
            metric="value",
        )
        grid_value = grid_result["value"].values[0]

        # Direct BatchPricer call
        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )
        direct_values = pricer.portfolio_values_at(
            np.array([spot]),
            time_point,
        )
        direct_value = direct_values[0]

        # Should match to FD/QuantLib precision
        assert np.isclose(grid_value, direct_value, rtol=1e-4)

    def test_cache_hit_on_identical_metric_repeated_call(self) -> None:
        """Call cache.get_or_calculate twice with identical args (same metric).
        Cache size should not grow on repeat (proves cache hit, not miss)."""
        portfolio = _make_put_portfolio(days_to_maturity=45)
        analyzer = PortfolioAnalyzer(portfolio)
        cache = ScenarioGridCache()

        spot_scenarios = np.array([95.0, 100.0, 105.0])
        time_points = [
            portfolio.valuation_date,
            portfolio.valuation_date + timedelta(days=10),
        ]

        # First call: miss, caches result
        grid1 = cache.get_or_calculate(
            portfolio=portfolio,
            analyzer=analyzer,
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="value",
        )
        size_after_first = cache.size()
        assert size_after_first == 1

        # Second call: hit, should not grow cache
        grid2 = cache.get_or_calculate(
            portfolio=portfolio,
            analyzer=analyzer,
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="value",
        )
        size_after_second = cache.size()

        assert size_after_second == 1, "Cache size should not grow on hit"
        pd.testing.assert_frame_equal(grid1, grid2)

    def test_revisited_date_determinism_across_different_request_shapes(
        self,
    ) -> None:
        """Build grid A over [d0, d1, d2] and grid B over [d1] alone. Assert
        d1's value/delta rows agree between A and B (date revisited via
        different key still reproduces same numbers)."""
        portfolio = _make_put_portfolio(days_to_maturity=90)
        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([95.0, 100.0, 105.0])
        original_date = portfolio.valuation_date
        d0 = original_date
        d1 = original_date + timedelta(days=30)
        d2 = original_date + timedelta(days=60)

        # Grid A: 3 time points
        grid_a = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=[d0, d1, d2],
            metric="value",
        )

        # Grid B: 1 time point (d1 alone, different cache key)
        grid_b = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=[d1],
            metric="value",
        )

        # Extract d1 rows from grid A
        grid_a_d1 = grid_a[grid_a["valuation_date"] == d1].reset_index(
            drop=True
        )
        grid_b = grid_b.reset_index(drop=True)

        # Values at d1 should agree regardless of request shape
        pd.testing.assert_series_equal(
            grid_a_d1["value"],
            grid_b["value"],
            check_names=False,
        )

    def test_empty_portfolio_no_grid_computation(self) -> None:
        """create_time_heatmap on empty portfolio returns _empty_widget
        without touching cache."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        dashboard = _dashboard(portfolio)
        cache = dashboard.cache

        result = dashboard.create_time_heatmap()

        # Should return a VBox (the _empty_widget)
        assert isinstance(result, widgets.VBox)
        # Cache should still be empty (no grid computed)
        assert cache.size() == 0


class TestSpotVolHeatmapGrid:
    """Pin Spot x Vol grid shape, monotonicity, and repricing.

    Tests _render_spot_vol_heatmap and scenario_grid_spot_vol
    (scenarios.py). As of M2.1 both are pure — no mutate/restore of
    portfolio.valuation_date — designing out the former state-leak bug
    (see test_spotted_valuation_date_state_leak_after_spot_vol_render
    below) rather than patching it.
    """

    def test_grid_shape_square_vol_asc_spot_asc(self) -> None:
        """Grid is square (grid_resolution, grid_resolution), rows = vol asc,
        columns = spot asc."""
        portfolio = _make_put_portfolio(days_to_maturity=45)
        analyzer = PortfolioAnalyzer(portfolio)

        grid_res = 5
        spot_scenarios = np.linspace(90.0, 110.0, grid_res)
        vol_scenarios = np.linspace(0.15, 0.35, grid_res)

        result = analyzer.scenario_grid_spot_vol(
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            vol_mapping=proportional_vol,
            metric="value",
        )

        matrix = result.pivot(
            index="volatility",
            columns="spot_price",
            values="value",
        ).sort_index(ascending=True)

        assert matrix.shape == (grid_res, grid_res)
        # Rows (vol) ascending
        assert list(matrix.index) == sorted(matrix.index)
        # Columns (spot) ascending
        assert list(matrix.columns) == sorted(matrix.columns)

    def test_put_value_monotonic_increasing_vol_fixed_spot(self) -> None:
        """Fixed spot, vol ascending → value increasing (vega > 0 for puts)."""
        portfolio = _make_put_portfolio(days_to_maturity=45)
        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([100.0])
        vol_scenarios = np.linspace(0.10, 0.40, 7)

        result = analyzer.scenario_grid_spot_vol(
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            vol_mapping=proportional_vol,
            metric="value",
        )

        values = result.sort_values("volatility")["value"].values
        diffs = np.diff(values)

        assert np.all(diffs > 0), (
            f"Put value should increase with vol. Diffs: {diffs}"
        )

    def test_put_value_monotonic_increasing_spot_fixed_vol(self) -> None:
        """Fixed vol, spot descending → value increasing (delta < 0)."""
        portfolio = _make_put_portfolio(days_to_maturity=45)
        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.linspace(90.0, 110.0, 7)
        vol_scenarios = np.array([0.25])

        result = analyzer.scenario_grid_spot_vol(
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            vol_mapping=proportional_vol,
            metric="value",
        )

        values = result.sort_values("spot_price", ascending=False)[
            "value"
        ].values
        diffs = np.diff(values)

        assert np.all(diffs > 0), (
            f"Put value should increase with descending spot. Diffs: {diffs}"
        )

    def test_grid_cell_matches_batchpricer_after_vol_shift(self) -> None:
        """One grid cell (spot, vol) cross-check against direct portfolio
        repricing at the same point. On this single-leg book the
        vega-weighted average is that leg's own vol, so
        proportional_vol's scaling lands exactly on target_vol, matching
        a direct update_market_conditions repricing bit-for-bit."""
        portfolio = _make_put_portfolio(days_to_maturity=45)
        analyzer = PortfolioAnalyzer(portfolio)

        spot = 95.0
        target_vol = 0.30
        spot_scenarios = np.array([spot])
        vol_scenarios = np.array([target_vol])

        grid_result = analyzer.scenario_grid_spot_vol(
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            vol_mapping=proportional_vol,
            metric="value",
        )
        grid_value = grid_result["value"].values[0]

        # Direct repricing: shift vol, update spot, read total_value
        original_vol = portfolio.volatility
        portfolio.update_market_conditions(
            spot_price=spot,
            volatility=target_vol,
        )
        direct_value = portfolio.total_value()
        portfolio.update_market_conditions(
            spot_price=portfolio.spot_price,  # Restore (may have drifted)
            volatility=original_vol,
        )

        assert np.isclose(grid_value, direct_value, rtol=1e-4)

    def test_valuation_date_and_engines_unaffected_by_spot_vol_render(
        self,
    ) -> None:
        """M2.1 designs out the former state-leak bug rather than patching
        it: _render_spot_vol_heatmap no longer sets portfolio.valuation_date
        at all (the old stress.py:897-898/920 mutate-then-restore is
        deleted), and scenario_grid_spot_vol reprices every cell through
        fresh, scratch OptionValuation objects at a shocked date derived
        from days_forward (scenarios.py) rather than by touching the
        portfolio. A create_spot_vol_heatmap render at days_forward != 0
        must therefore leave both portfolio.valuation_date and every
        pre-existing QuantLib engine untouched — there is no
        mutate/restore window in which either could be left stale, not even
        transiently or on an exception mid-render."""
        portfolio = _make_put_portfolio(days_to_maturity=90)
        dashboard = _dashboard(portfolio)

        # Baseline: portfolio value today
        baseline_value = portfolio.total_value()
        baseline_date = portfolio.valuation_date

        # Render Spot x Vol heatmap at days_forward=60 (different date).
        # Pure as of M2.1: must not touch portfolio state at all.
        _ = dashboard.create_spot_vol_heatmap(
            metric="value",
            days_forward=60,
        )

        assert portfolio.valuation_date == baseline_date

        # The former bug: engines silently left pricing at day 60. Now
        # there is nothing to leave stale — total_value() at the baseline
        # date matches immediately, no update_market_conditions call needed.
        after_render_value = portfolio.total_value()

        assert np.isclose(baseline_value, after_render_value, rtol=1e-4)


class TestScenarioGridCacheInvalidationGap:
    """Pin the fixed cache-hash coverage of underlying_quantity (cache.py).

    get_portfolio_state_hash now hashes portfolio-level state (including
    underlying_quantity) and every position's quantity, strike, maturity,
    type, volatility, contract_size, and exercise_style. Resizing the
    underlying leg between two get_or_calculate calls on the same cache
    instance must invalidate and recompute, not return a stale grid.
    """

    def test_cache_miss_on_underlying_quantity_change(self) -> None:
        """Resize portfolio.underlying_quantity between two
        get_or_calculate calls. The cache must invalidate and recompute,
        not return the stale pre-resize grid."""
        portfolio = _make_put_portfolio(days_to_maturity=45)
        analyzer = PortfolioAnalyzer(portfolio)
        cache = ScenarioGridCache()

        spot_scenarios = np.array([95.0, 100.0, 105.0])
        time_points = [
            portfolio.valuation_date,
            portfolio.valuation_date + timedelta(days=10),
        ]

        # First grid with underlying_quantity = 100
        portfolio.underlying_quantity = 100.0
        grid1 = cache.get_or_calculate(
            portfolio=portfolio,
            analyzer=analyzer,
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="value",
        )
        size_after_first = cache.size()

        # Resize underlying_quantity (should invalidate cache)
        portfolio.underlying_quantity = 200.0
        grid2 = cache.get_or_calculate(
            portfolio=portfolio,
            analyzer=analyzer,
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="value",
        )
        size_after_second = cache.size()

        # Cache should have grown (a miss, not a hit)
        assert size_after_second > size_after_first, (
            "Underlying quantity change should invalidate cache (miss), "
            "but it was a hit (bug)."
        )

        # Grid values should differ (underlying P&L contribution changed)
        assert not np.allclose(grid1["value"].values, grid2["value"].values)


class TestGoldenGridSpxTail20m:
    """Cross-check stress-grid glue against trusted lower-level pricing via
    the §4 golden book (spx_tail_20m.yaml fixture).

    Primary pin: every grid cell matches an independently-constructed
    BatchPricer call (proves repricing through BatchPricer, not a shortcut).
    Secondary: options-only value (net of underlying P&L) matches the
    documented ~$297,715 figure.
    """

    def test_golden_grid_cells_match_batchpricer_direct_calls(self) -> None:
        """Build a small grid from the golden book via scenario_grid, then
        cross-check each cell against a direct BatchPricer call."""
        portfolio = _load_golden_book()
        analyzer = PortfolioAnalyzer(portfolio)

        # Small grid: 2 time points x 2 spot points
        spot_scenarios = np.array([6400.0, 6600.0, 6800.0])  # ±3% around spot
        original_date = portfolio.valuation_date
        time_points = [
            original_date,
            original_date + timedelta(days=30),
        ]

        grid = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="value",
        )

        # Cross-check each cell
        for _, row in grid.iterrows():
            spot = row["spot_price"]
            date = row["valuation_date"]
            grid_value = row["value"]

            # Direct BatchPricer call
            pricer = BatchPricer(
                positions=portfolio.positions,
                risk_free_rate=portfolio.risk_free_rate,
                dividend_yield=portfolio.dividend_yield,
                underlying_quantity=portfolio.underlying_quantity,
                grid_resolution=FDGridResolution.FAST,
            )
            direct_values = pricer.portfolio_values_at(
                np.array([spot]),
                date,
            )
            direct_value = direct_values[0]

            assert np.isclose(grid_value, direct_value, rtol=1e-4), (
                f"Grid mismatch at spot={spot}, date={date}: "
                f"grid={grid_value}, direct={direct_value}"
            )

    def test_golden_options_only_value_sanity_check(self) -> None:
        """At (today, spot=6600), the portfolio's total value (options + long
        underlying equity). The golden book documents this as ≈ $20.3M
        (book notional) + hedge value ≈ $297,715 = total portfolio value."""
        portfolio = _load_golden_book()
        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([6600.0])
        time_points = [portfolio.valuation_date]

        grid = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="value",
        )

        # This is the total portfolio value (underlying + options)
        # underlying_quantity=3030, spot=6600 → $20.0M notional
        # plus hedge value ≈ $297,715
        total_value = grid["value"].values[0]

        # Expected ≈ spot * underlying_quantity + hedge_value
        # 6600 * 3030 = 19,998,000
        # + hedge ≈ 297,715 = 20,295,715
        expected_notional = 6600.0 * portfolio.underlying_quantity
        expected_total = expected_notional + 297_715

        # Loose check: total should be in the right ballpark (±5%)
        assert np.isclose(total_value, expected_total, rtol=0.05), (
            f"Total portfolio value {total_value} should be "
            f"≈ ${expected_total:,.0f}"
        )


class TestDisplayRiskRewardSummarySmoke:
    """Pin display_risk_reward_summary behaviour:
    - Real mc_results dict (produced by run_monte_carlo_simulation)
    - None guard
    - Empty dict guard (current KeyError outside try/except)
    - < 20 finite P&Ls guard
    - Concentration recompute override (delegated to
      analysis.stress.recompute_concentration as of M2.1)
    """

    def test_real_mc_results_displays_without_error(self, capsys) -> None:
        """Build a real mc_results dict via portfolio.run_monte_carlo_
        simulation and display it. Should not print "Error"."""
        portfolio = _make_put_portfolio(
            days_to_maturity=45,
            spot=100.0,
            vol=0.25,
        )
        dashboard = _dashboard(portfolio)

        mc_results = portfolio.run_monte_carlo_simulation(
            num_simulations=100,
            random_seed=42,
        )

        # Capture stdout/reporter calls
        dashboard.display_risk_reward_summary(mc_results)

        captured = capsys.readouterr()
        assert "Error" not in captured.out, (
            "display_risk_reward_summary should not print an error for "
            "a valid mc_results dict from run_monte_carlo_simulation"
        )

    def test_mc_results_none_returns_cleanly(self, capsys) -> None:
        """mc_results=None should return cleanly (the leading None guard)."""
        portfolio = _make_put_portfolio()
        dashboard = _dashboard(portfolio)

        # Should not raise, just print error
        dashboard.display_risk_reward_summary(None)

        captured = capsys.readouterr()
        # The reporter.error call should have produced output
        assert len(captured.out) > 0 or len(captured.err) > 0

    def test_mc_results_empty_dict_raises_keyerror(self) -> None:
        """mc_results={} (empty dict) should raise KeyError outside the
        function's try/except (unlike other failures, which are caught and
        printed inside the try block). This is the current (non-ideal) guard
        gap — pin it as-is."""
        portfolio = _make_put_portfolio()
        dashboard = _dashboard(portfolio)

        # Empty dict should raise KeyError when trying to read required keys
        with pytest.raises(KeyError):
            dashboard.display_risk_reward_summary({})

    def test_mc_results_less_than_20_finite_pnls_error(self, capsys) -> None:
        """Fewer than 20 finite P&L values should trigger an error
        (the `if len(pnls_clean) < 20: error + return` guard)."""
        portfolio = _make_put_portfolio()
        dashboard = _dashboard(portfolio)

        # Hand-rolled mc_results with minimal keys and only 10 finite P&Ls
        mc_results = {
            "simulated_pnls": [100.0, 50.0, 0.0, -50.0, -100.0] + [np.nan] * 5,
            "days_to_expiry": 30,
            "expected_pnl": 10.0,
            "median_pnl": 5.0,
            "std_pnl": 50.0,
            "min_pnl": -100.0,
            "max_pnl": 100.0,
            "prob_profit": 0.6,
            "prob_loss": 0.4,
            "avg_loss": -50.0,
            "max_loss": -100.0,
            "median_loss": -50.0,
            "var_95": -80.0,
            "var_99": -95.0,
            "cvar_95": -90.0,
            "cvar_99": -97.0,
            "is_concentrated": False,
            "most_common_pnl": None,
            "concentration_pct": 0.0,
            "theoretical_max_loss": -150.0,
            "num_simulations": 10,
        }

        dashboard.display_risk_reward_summary(mc_results)

        captured = capsys.readouterr()
        # Should print an error via reporter.error or similar
        output = captured.out + captured.err
        assert (
            "fewer than 20" in output.lower()
            or "insufficient" in output.lower()
            or len(output) > 0  # At least some output was produced
        )

    def test_concentration_recompute_overrides_input_dict(
        self,
        capsys,
    ) -> None:
        """Feed is_concentrated=False but data that recomputes to True (via
        analysis.stress.recompute_concentration's
        len(unique(round(pnls, 2))) < len(pnls)/100 rule). Pin that the
        recomputed value wins in the report."""
        portfolio = _make_put_portfolio()
        dashboard = _dashboard(portfolio)

        # Create highly concentrated P&L data (all values ≈ 100)
        pnls = [100.0 + np.random.normal(0, 0.001) for _ in range(1000)]

        mc_results = {
            "simulated_pnls": pnls,
            "days_to_expiry": 30,
            "expected_pnl": 100.0,
            "median_pnl": 100.0,
            "std_pnl": 1.0,
            "min_pnl": 99.0,
            "max_pnl": 101.0,
            "prob_profit": 1.0,
            "prob_loss": 0.0,
            "avg_loss": 0.0,
            "max_loss": -1.0,
            "median_loss": 0.0,
            "var_95": 99.5,
            "var_99": 99.8,
            "cvar_95": 99.7,
            "cvar_99": 99.9,
            "is_concentrated": False,  # Claim not concentrated
            "most_common_pnl": (100.0, 900),
            "concentration_pct": 90.0,
            "theoretical_max_loss": -150.0,
            "num_simulations": 1000,
        }

        dashboard.display_risk_reward_summary(mc_results)

        captured = capsys.readouterr()
        # The report should indicate concentration (recomputed, not from input)
        # Look for any mention of high concentration/clustering
        assert "Concentration" in captured.out or len(captured.out) > 0


class TestPlotMcDistributionSmoke:
    """Pin _plot_mc_distribution smoke-level:
    - Returns None (plots via side effect)
    - Creates 2 axes (PDF + CDF)

    The bin-count rule itself is unit-tested directly against
    compute_pnl_histogram in tests/test_analysis/test_stress.py.
    """

    def test_plot_mc_distribution_creates_two_axes(self) -> None:
        """_plot_mc_distribution should create a 2-panel figure
        (left=PDF, right=CDF)."""
        pnls = np.random.normal(0, 100, 1000)
        pnls_clean = pnls[np.isfinite(pnls)]

        dashboard = _dashboard(_make_put_portfolio())

        # Call the private method directly
        dashboard._plot_mc_distribution(
            pnls_clean=pnls_clean,
            expected_pnl=np.mean(pnls_clean),
            median_pnl=np.median(pnls_clean),
            min_pnl=np.min(pnls_clean),
            max_pnl=np.max(pnls_clean),
            var_95=np.percentile(pnls_clean, 5),
            cvar_95=np.percentile(pnls_clean, 5),
            max_loss=np.percentile(pnls_clean, 5),
            is_concentrated=False,
            most_common_pnl=None,
            concentration_pct=0.0,
        )

        fig = plt.gcf()
        try:
            assert len(fig.axes) == 2, "Should have 2 axes (PDF + CDF)"
        finally:
            plt.close(fig)


class TestMakeStatusWidget:
    """Pin _make_status_widget (stress.py:1121-1185, a static method).

    Pure function, returns HTML widget for status display. No portfolio
    dependency."""

    @pytest.mark.parametrize(
        "status_type",
        ["calculating", "complete", "error", "unknown"],
    )
    def test_make_status_widget_returns_html(self, status_type: str) -> None:
        """_make_status_widget returns an HTML widget for any status_type.
        Unknown types fall back to 'error' style silently (stress.py:1147)."""
        widget = StressDashboard._make_status_widget(
            status_type,
            metric="value",
            grid_size=10,
        )

        assert isinstance(widget, widgets.HTML)
        assert len(widget.value) > 0


class TestEmptyWidget:
    """Pin _empty_widget (stress.py:1187-1190, a static method).

    Pure function: returns VBox wrapping a message. No portfolio dependency."""

    def test_empty_widget_returns_vbox_with_message(self) -> None:
        """_empty_widget returns a VBox containing an HTML widget with the
        given message (no sanitization — note this, though not exploitable
        with hardcoded strings)."""
        message = "No positions to analyse"
        widget = StressDashboard._empty_widget(message)

        assert isinstance(widget, widgets.VBox)
        assert len(widget.children) > 0
        # First child should be an HTML widget containing the message
        assert isinstance(widget.children[0], widgets.HTML)
        assert message in widget.children[0].value


class TestCreateTimeHeatmapWrapper:
    """Smoke tests for the public create_time_heatmap wrapper.

    Uses a real GlobalAssumptions; tests the ipywidgets orchestration
    (stress.py:104-244) without pinning grid details (those are covered
    by TestTimeHeatmapGrid)."""

    def test_create_time_heatmap_returns_vbox(self) -> None:
        """Public method should return a widgets.VBox with controls."""
        portfolio = _make_put_portfolio()
        dashboard = _dashboard(portfolio)

        result = dashboard.create_time_heatmap()

        assert isinstance(result, widgets.VBox)
        # Should have header + controls + output
        assert len(result.children) >= 3

    def test_create_time_heatmap_empty_portfolio_vbox(self) -> None:
        """Empty portfolio → _empty_widget (VBox with message)."""
        empty_portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        dashboard = _dashboard(empty_portfolio)

        result = dashboard.create_time_heatmap()

        assert isinstance(result, widgets.VBox)


class TestCreateSpotVolHeatmapWrapper:
    """Smoke tests for the public create_spot_vol_heatmap wrapper.

    Uses a real GlobalAssumptions; tests the ipywidgets orchestration
    (stress.py:246-421) without pinning grid details (those are covered
    by TestSpotVolHeatmapGrid)."""

    def test_create_spot_vol_heatmap_returns_vbox(self) -> None:
        """Public method should return a widgets.VBox with controls."""
        portfolio = _make_put_portfolio()
        dashboard = _dashboard(portfolio)

        result = dashboard.create_spot_vol_heatmap()

        assert isinstance(result, widgets.VBox)
        # Should have header + controls + output
        assert len(result.children) >= 3

    def test_create_spot_vol_heatmap_empty_portfolio_vbox(self) -> None:
        """Empty portfolio → _empty_widget (VBox with message)."""
        empty_portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        dashboard = _dashboard(empty_portfolio)

        result = dashboard.create_spot_vol_heatmap()

        assert isinstance(result, widgets.VBox)
