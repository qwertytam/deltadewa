"""Stress Dashboard module for the deltadewa options management dashboard.

This module encapsulates the stress-testing logic used by both
monitor_dashboard.ipynb (a single current-structure snapshot) and
hedge_design.ipynb (the full stress workbench), providing three main
capabilities:
  - Time vs Price heatmap  (create_time_heatmap)
  - Spot vs Volatility heatmap  (create_spot_vol_heatmap)
  - Risk / Reward summary from Monte Carlo results (display_risk_reward_summary)
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime, timedelta
from typing import Any, cast

import ipywidgets as widgets
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display
from matplotlib.axes import Axes
from matplotlib.ticker import FuncFormatter

from deltadewa.analysis import PortfolioAnalyzer, ScenarioGridCache
from deltadewa.analysis.volatility import calculate_portfolio_avg_volatility
from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.formatters.gradients import (
    apply_financial_gradient_2d,
    get_matplotlib_norm_and_cmap,
)
from deltadewa.formatters.values import format_currency_for_axis
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.monte_carlo import drift_measure_label
from deltadewa.reporting import ConsoleReporter
from deltadewa.widgets import GlobalAssumptions

# ---------------------------------------------------------------------------
# Metric configuration shared across heatmap methods
# ---------------------------------------------------------------------------
_METRIC_CONFIG: dict[str, dict[str, Any]] = {
    "pnl": {"title": "P&L", "fmt": "${:,.0f}"},
    "value": {"title": "Value", "fmt": "${:,.0f}"},
    "net_delta": {"title": "Net Delta", "fmt": "{:,.1f}"},
    "delta": {"title": "Delta", "fmt": "{:,.1f}"},
    "gamma": {"title": "Gamma", "fmt": "{:,.4f}"},
    "vega": {"title": "Vega", "fmt": "{:,.2f}"},
    "theta": {"title": "Theta", "fmt": "${:,.2f}"},
    "rho": {"title": "Rho", "fmt": "{:,.2f}"},
}

_METRIC_LABELS: dict[str, str] = {
    "pnl": "Total Portfolio P&L vs Current ($)",
    "value": "Total Portfolio Value ($)",
    "net_delta": "Net Delta (shares equiv., inc. underlying)",
    "delta": "Total Delta (shares equiv., options only)",
    "gamma": "Total Gamma (Δ per $1 spot move)",
    "vega": "Total Vega ($/1% vol)",
    "theta": "Total Theta ($/day)",
    "rho": "Total Rho ($/1% rate)",
}


class StressDashboard:
    """Encapsulates all STRESS-mode visualisations for the options dashboard.

    Parameters
    ----------
    portfolio : OptionPortfolio
        Live portfolio object (shared reference; state is read and temporarily
        mutated for scenario calculations, then restored).
    analyzer : PortfolioAnalyzer
        Portfolio analyser used by the scenario cache.
    cache : ScenarioGridCache
        Scenario grid cache for performance-optimised calculations.
    global_assumptions : GlobalAssumptions
        Widget panel providing spot/vol shock parameters and grid resolution.
    reporter : ConsoleReporter, optional
        Console reporter for section headers and dividers.  A default instance
        (width=100) is created when *None* is supplied.

    """

    def __init__(
        self,
        portfolio: OptionPortfolio,
        analyzer: PortfolioAnalyzer,
        cache: ScenarioGridCache,
        global_assumptions: GlobalAssumptions,
        reporter: ConsoleReporter | None = None,
    ) -> None:
        """Initialize StressDashboard instance."""
        self.portfolio = portfolio
        self.analyzer = analyzer
        self.cache = cache
        self.global_assumptions = global_assumptions
        self.reporter = reporter or ConsoleReporter(width=100)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_time_heatmap(
        self,
        metric: str = "pnl",
        *,
        num_time_steps: int = 10,
        num_price_steps: int = 13,
    ) -> widgets.VBox:
        """Build and return an interactive Time vs Price heatmap widget.

        The widget contains a metric dropdown and step-count sliders; the
        heatmap re-renders whenever a control changes.

        Parameters
        ----------
        metric : str
            Initial metric to display (default ``"pnl"``).
        num_time_steps : int
            Initial number of time-axis grid points (5-20).
        num_price_steps : int
            Initial number of price-axis grid points (5-19, odd values only).

        Returns
        -------
        widgets.VBox
            The fully wired interactive widget ready to be ``display()``-ed.

        """
        portfolio = self.portfolio
        if not portfolio.positions:
            return self._empty_widget(
                "No positions to analyse. Add positions in BUILD mode first.",
            )

        original_spot: float = self.global_assumptions.spot_price.value
        original_date: datetime = portfolio.valuation_date
        max_maturity = max(
            pos.option.maturity_date for pos in portfolio.positions
        )
        days_to_max_maturity = (max_maturity - original_date).days

        # --- widgets ---
        metric_selector = widgets.Dropdown(
            options=[
                ("P&L", "pnl"),
                ("Value", "value"),
                ("Net Delta", "net_delta"),
                ("Delta", "delta"),
                ("Gamma", "gamma"),
                ("Vega", "vega"),
                ("Theta", "theta"),
            ],
            value=metric,
            description="Metric:",
            style={"description_width": "120px"},
        )

        time_steps_slider = widgets.IntSlider(
            value=num_time_steps,
            min=5,
            max=20,
            step=1,
            description="Time Steps:",
            continuous_update=False,
            style={"description_width": "120px"},
        )

        price_steps_slider = widgets.IntSlider(
            value=num_price_steps,
            min=5,
            max=19,
            step=2,
            description="Price Steps:",
            continuous_update=False,
            style={"description_width": "120px"},
        )

        heatmap_output = widgets.Output()

        def _render(
            spot_range_pct: float,
            metric_type: str,
            n_time: int,
            n_price: int,
        ) -> None:
            self._render_time_heatmap(
                heatmap_output,
                spot_range_pct=spot_range_pct,
                metric_type=metric_type,
                num_time_steps=n_time,
                num_price_steps=n_price,
                original_spot=original_spot,
                original_date=original_date,
                days_to_max_maturity=days_to_max_maturity,
            )

        def _on_change(_change: object) -> None:
            _render(
                self.global_assumptions.spot_shock_pct.value,
                metric_selector.value,
                time_steps_slider.value,
                price_steps_slider.value,
            )

        metric_selector.observe(_on_change, names="value")
        time_steps_slider.observe(_on_change, names="value")
        price_steps_slider.observe(_on_change, names="value")

        header = widgets.HTML(
            f"""
            <div style="background-color:"""
            f"""{DEFAULT_PALETTE.med_dark_background};color:white; """
            f"""padding:10px; border-radius:5px; """
            f"""margin-bottom:10px;">
                <h3 style="margin:0;">📅 Time vs Price Analysis</h3>
                <p style="margin:5px 0 0 0; font-size:14px;">
                    See how portfolio metrics evolve across spot prices and"""
            f""" time (theta decay)
                </p>
            </div>
            """,
        )

        vbox = widgets.VBox(
            [
                header,
                widgets.HBox(
                    [metric_selector, time_steps_slider, price_steps_slider],
                ),
                heatmap_output,
            ],
        )

        # Generate initial render
        _render(
            self.global_assumptions.spot_shock_pct.value,
            metric_selector.value,
            time_steps_slider.value,
            price_steps_slider.value,
        )

        return vbox

    def create_spot_vol_heatmap(  # pylint: disable=too-many-locals
        self,
        metric: str = "pnl",
        days_forward: int = 0,
    ) -> widgets.VBox:
        """Build and return an interactive Spot x Volatility heatmap widget.

        The widget contains a date selector (days forward) and metric selector;
        the heatmap re-renders via ``widgets.interactive``.

        Parameters
        ----------
        metric : str
            Initial metric to display (default ``"pnl"``).
        days_forward : int
            Initial days-forward offset (0 = today).

        Returns
        -------
        widgets.VBox
            The fully wired interactive widget ready to be ``display()``-ed.

        """
        portfolio = self.portfolio
        if not portfolio.positions:
            return self._empty_widget(
                "No positions to analyse. Add positions in BUILD mode first.",
            )

        # Scenario parameters from global assumptions
        spot_shock_pct: float = self.global_assumptions.spot_shock_pct.value
        vol_shock_pct: float = self.global_assumptions.vol_shock_pct.value
        grid_resolution: int = self.global_assumptions.grid_resolution.value

        original_spot: float = portfolio.spot_price
        original_val_date: datetime = portfolio.valuation_date
        baseline_value: float = portfolio.total_value()

        avg_vol: float = calculate_portfolio_avg_volatility(portfolio)

        # Scenario grids
        spot_min = original_spot * (1 - spot_shock_pct)
        spot_max = original_spot * (1 + spot_shock_pct)
        spot_scenarios = np.linspace(spot_min, spot_max, grid_resolution)

        vol_min = max(avg_vol * (1 - vol_shock_pct), 0.05)
        vol_max = min(avg_vol * (1 + vol_shock_pct), 3.0)
        vol_scenarios = np.linspace(vol_min, vol_max, grid_resolution)

        if portfolio.positions:
            max_maturity = max(
                pos.option.maturity_date for pos in portfolio.positions
            )
            max_days = (max_maturity - portfolio.valuation_date).days
        else:
            max_days = 90

        # PortfolioWidgets helpers are not available here; build widgets
        # directly
        # pylint: disable=import-outside-toplevel
        from deltadewa.widgets.portfolio_controls import (
            PortfolioWidgets as _PfW,  # local import to avoid hard dep
        )

        _pw_stub = _PfW.__new__(_PfW)  # noqa: RUF052
        _pw_stub.portfolio = portfolio

        # date selector via PortfolioWidgets helper
        try:
            date_selector = _pw_stub.create_date_selector(
                max_days=max_days,
                description="Valuation Date:",
                num_steps=20,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # Fallback: plain IntSlider
            date_selector = widgets.IntSlider(
                value=days_forward,
                min=0,
                max=max_days,
                step=max(1, max_days // 20),
                description="Valuation Date:",
                style={"description_width": "150px"},
                continuous_update=False,
            )

        # metric selector via PortfolioWidgets helper
        try:
            metric_selector = _pw_stub.create_metric_selector(
                metrics=[
                    ("Total P&L ($)", "pnl"),
                    ("Total Portfolio Value ($)", "value"),
                    ("Net Delta (shares equiv., inc. underlying)", "net_delta"),
                    ("Total Delta (shares equiv., options only)", "delta"),
                    ("Total Gamma", "gamma"),
                    ("Total Vega ($/1% vol)", "vega"),
                    ("Theta ($/day)", "theta"),
                    ("Rho ($/1% rate)", "rho"),
                ],
                default=metric,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            metric_selector = widgets.Dropdown(
                options=[
                    ("Total P&L ($)", "pnl"),
                    ("Total Portfolio Value ($)", "value"),
                    ("Net Delta", "net_delta"),
                    ("Total Delta", "delta"),
                    ("Total Gamma", "gamma"),
                    ("Total Vega ($/1% vol)", "vega"),
                    ("Theta ($/day)", "theta"),
                    ("Rho ($/1% rate)", "rho"),
                ],
                value=metric,
                description="Metric:",
                style={"description_width": "150px"},
            )

        heatmap_output = widgets.Output()

        def _render(days_fwd: int, metric_type: str) -> None:
            self._render_spot_vol_heatmap(
                heatmap_output,
                days_forward=days_fwd,
                metric_type=metric_type,
                original_spot=original_spot,
                original_val_date=original_val_date,
                avg_vol=avg_vol,
                spot_min=spot_min,
                spot_max=spot_max,
                vol_min=vol_min,
                vol_max=vol_max,
                spot_scenarios=spot_scenarios,
                vol_scenarios=vol_scenarios,
                grid_resolution=grid_resolution,
                spot_shock_pct=spot_shock_pct,
                vol_shock_pct=vol_shock_pct,
                baseline_value=baseline_value,
            )

        def _on_change(_change: object) -> None:
            if metric_selector.value is not None:
                _render(
                    date_selector.value,
                    metric_selector.value,
                )

        date_selector.observe(_on_change, names="value")
        metric_selector.observe(_on_change, names="value")

        header = widgets.HTML(
            value=f"""
            <div style="
                background-color: {DEFAULT_PALETTE.med_dark_background};
                color: white;
                padding: 15px 20px;
                border-radius: 5px;
                margin-bottom: 15px;
            ">
                <h3 style="margin: 0;">Interactive Stress Test Heatmap</h3>
                <p style="margin: 5px 0 0 0; font-size: 14px;">
                    Analyse portfolio behaviour across spot price and """
            f"""volatility scenarios
                </p>
            </div>
            """,
        )

        vbox = widgets.VBox(
            [header, date_selector, metric_selector, heatmap_output],
        )

        # Generate initial render
        _render(days_forward, metric)

        return vbox

    def display_risk_reward_summary(  # pylint: disable=R0914,R0912,R0915
        self,
        mc_results: dict[str, Any],
    ) -> None:
        """Print and plot the Monte Carlo risk/reward summary.

        Displays:
        - Distribution summary statistics (expected P&L, VaR, CVaR, …)
        - Side-by-side PDF histogram and CDF charts

        Parameters
        ----------
        mc_results : dict
            Dictionary returned by ``portfolio.run_monte_carlo_simulation()``.
            Must contain keys: ``simulated_pnls``, ``days_to_expiry``,
            ``expected_pnl``, ``median_pnl``, ``std_pnl``, ``min_pnl``,
            ``max_pnl``, ``prob_profit``, ``prob_loss``, ``avg_loss``,
            ``max_loss``, ``median_loss``, ``var_95``, ``var_99``,
            ``cvar_95``, ``cvar_99``, ``is_concentrated``,
            ``most_common_pnl``, ``concentration_pct``,
            ``theoretical_max_loss``, ``num_simulations``.

        """
        if mc_results is None:
            self.reporter.error("No Monte Carlo results provided.")
            return

        simulated_pnls = mc_results["simulated_pnls"]
        days_to_expiry = mc_results["days_to_expiry"]
        expected_pnl = mc_results["expected_pnl"]
        median_pnl = mc_results["median_pnl"]
        std_pnl = mc_results["std_pnl"]
        min_pnl = mc_results["min_pnl"]
        max_pnl = mc_results["max_pnl"]
        prob_profit = mc_results["prob_profit"]
        prob_loss = mc_results["prob_loss"]
        avg_loss = mc_results["avg_loss"]
        max_loss = mc_results["max_loss"]
        median_loss = mc_results["median_loss"]
        var_95 = mc_results["var_95"]
        var_99 = mc_results["var_99"]
        cvar_95 = mc_results["cvar_95"]
        cvar_99 = mc_results["cvar_99"]
        is_concentrated = mc_results["is_concentrated"]
        most_common_pnl = mc_results["most_common_pnl"]
        concentration_pct = mc_results["concentration_pct"]
        theoretical_max_loss = mc_results["theoretical_max_loss"]

        pnls = np.array(simulated_pnls, dtype=float)
        pnls_clean = pnls[np.isfinite(pnls)]

        if len(pnls_clean) < 20:
            self.reporter.error(
                f"Insufficient valid data: {len(pnls_clean)} points "
                "(need at least 20)",
            )
            return

        try:
            profits = pnls_clean[pnls_clean >= 0]
            losses = pnls_clean[pnls_clean < 0]

            unique_rounded = np.unique(np.round(pnls_clean, 2))
            is_concentrated = len(unique_rounded) < (len(pnls_clean) / 100)

            if is_concentrated and most_common_pnl is not None:
                concentration_pct = most_common_pnl[1] / len(pnls_clean) * 100

            # ---- textual summary ----
            print("\n📊 Distribution Summary:")
            print(f"   Simulations:      {len(pnls_clean):,}")
            print(f"   Unique P&L values: {len(unique_rounded):,}")
            print(
                f"   Time horizon:     {days_to_expiry} days to nearest expiry",
            )

            if is_concentrated and most_common_pnl is not None:
                self.reporter.warning(
                    "Highly Concentrated Distribution Detected",
                )
                print(
                    f"   Most common outcome: ${most_common_pnl[0]:,.2f} "
                    f"({concentration_pct:.1f}% of scenarios)",
                )
                print(
                    "   → This is NORMAL for short option strategies "
                    "where options expire worthless most of the time",
                )

            print("\n💰 Expected Returns:")
            print(f"   Expected P&L (mean):     ${expected_pnl:>10,.2f}")
            print(f"   Median P&L (50th %ile):  ${median_pnl:>10,.2f}")
            print(f"   Standard Deviation:      ${std_pnl:>10,.2f}")

            print("\n📈 Profit Analysis:")
            measure = drift_measure_label(
                mc_results.get("drift_measure", "risk_neutral"),
            )
            print(
                f"   Probability of Profit:   {prob_profit:>6.1%} "
                f"({measure} drift)",
            )
            if len(profits) > 0:
                print(
                    f"   Average Profit:          ${np.mean(profits):>10,.2f}",
                )
                print(f"   Best Case:               ${max_pnl:>10,.2f}")

            print("\n📉 Loss Analysis:")
            print(f"   Probability of Loss:     {prob_loss:>6.1%}")
            if len(losses) > 0:
                print(f"   Average Loss (when occurs): ${avg_loss:>10,.2f}")
                print(f"   Median Loss (when occurs):  ${median_loss:>10,.2f}")
                print(f"   Worst Case in Sims:         ${max_loss:>10,.2f}")
            else:
                print("   No losses in any simulation")

            print("\n⚠️  Value at Risk (VaR):")
            print(f"   95% VaR (5th percentile): ${var_95:>10,.2f}")
            if var_95 >= 0:
                print(f"   → 95% of outcomes are BETTER than ${var_95:,.2f}")
                print(
                    "   → Only 5% of scenarios result in less than $"
                    f"{var_95:,.2f}",
                )
            else:
                print(
                    "   → 5% of scenarios result in worse than $"
                    f"{var_95:,.2f} loss",
                )

            print(f"   99% VaR (1st percentile): ${var_99:>10,.2f}")

            print("\n💥 Conditional VaR (Expected Shortfall):")
            print(f"   95% CVaR (avg worst 5%):  ${cvar_95:>10,.2f}")
            print(f"   99% CVaR (avg worst 1%):  ${cvar_99:>10,.2f}")
            print("   → Average P&L of the worst 5% of scenarios")

            if theoretical_max_loss is not None:
                print("\n🔴 Theoretical Maximum Loss:")
                print(
                    "   Max possible loss:        $"
                    f"{theoretical_max_loss:>10,.2f}",
                )
                print(
                    "   → If all short options go fully ITM "
                    "(spot → $0 for puts)",
                )
                if abs(max_loss) < abs(theoretical_max_loss) * 0.1:
                    self.reporter.warning(
                        f"     WARNING: Monte Carlo worst case ($"
                        f"{max_loss:,.2f}) is much",
                    )
                    print(
                        f"      better than theoretical max ($"
                        f"{theoretical_max_loss:,.2f})",
                    )
                    print(
                        "      → Consider running simulations with extreme "
                        "scenarios",
                    )

            print("\n📊 Percentile Breakdown:")
            for p in [0.1, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.9]:
                val = np.percentile(pnls_clean, p)
                if p <= 5:
                    marker = " ⚠️  TAIL RISK"
                elif p >= 95:
                    marker = " 🎯 UPSIDE"
                else:
                    marker = ""
                print(f"   {p:>5.1f}th percentile: ${val:>10,.2f}{marker}")

            self.reporter.divider()

            # ---- charts ----
            self._plot_mc_distribution(
                pnls_clean=pnls_clean,
                expected_pnl=expected_pnl,
                median_pnl=median_pnl,
                min_pnl=min_pnl,
                max_pnl=max_pnl,
                var_95=var_95,
                cvar_95=cvar_95,
                max_loss=max_loss,
                is_concentrated=is_concentrated,
                most_common_pnl=most_common_pnl,
                concentration_pct=concentration_pct,
            )

            self.reporter.success(
                f"Successfully plotted {len(pnls_clean):,} simulations",
            )

            if std_pnl < 100:
                self.reporter.warning(
                    f"WARNING: Very low standard deviation (${std_pnl:.2f})",
                )
                print("   → Check if volatility parameter is set correctly")

            if abs(expected_pnl - median_pnl) > std_pnl:
                self.reporter.warning("WARNING: Large skew detected")
                print(
                    f"   Mean: ${expected_pnl:,.2f}, Median: $"
                    f"{median_pnl:,.2f}",
                )
                print(
                    "   → Distribution is highly asymmetric "
                    "(typical for options)",
                )

        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.reporter.error("ERROR in visualisation:")
            print(f"   {exc}")
            print("\nFull traceback:")
            traceback.print_exc()

    # ------------------------------------------------------------------
    # Internal rendering helpers
    # ------------------------------------------------------------------

    def _render_time_heatmap(  # pylint: disable=R0913,R0914,R0915
        self,
        output_widget: widgets.Output,
        *,
        spot_range_pct: float,
        metric_type: str,
        num_time_steps: int,
        num_price_steps: int,
        original_spot: float,
        original_date: datetime,
        days_to_max_maturity: int,
    ) -> None:
        """Render (or re-render) the Time vs Price styled table.

        Render inside *output_widget*.
        """

        def _spot_formatter(x: float) -> str:
            try:
                x = float(x)
            except Exception:  # pylint: disable=broad-exception-caught
                return str(x)
            if x < 100:
                return f"{x:.2f}"
            return f"{x:,.0f}"

        with output_widget:
            output_widget.clear_output(wait=True)
            try:
                spot_min = original_spot * (1 - spot_range_pct)
                spot_max = original_spot * (1 + spot_range_pct)
                spot_scenarios = np.linspace(
                    spot_min,
                    spot_max,
                    num_price_steps,
                )

                time_days = np.unique(
                    np.linspace(0, days_to_max_maturity, num_time_steps).astype(
                        int,
                    ),
                )
                time_points = [
                    original_date + timedelta(days=int(d)) for d in time_days
                ]

                result_df = self.cache.get_or_calculate(
                    portfolio=self.portfolio,
                    analyzer=self.analyzer,
                    spot_scenarios=spot_scenarios,
                    time_points=time_points,
                    metric=metric_type,
                    baseline_spot=self.portfolio.spot_price,
                    baseline_valuation_date=original_date,
                )

                pivot_df = result_df.pivot(
                    index="spot_price",
                    columns="days_forward",
                    values="value",
                ).sort_index(ascending=False)

                def _col_label(d: str | float) -> str:
                    try:
                        di = int(float(d))
                    except Exception:  # pylint: disable=broad-exception-caught
                        return str(d)
                    future_date = original_date + timedelta(days=di)
                    date_str = future_date.strftime("%Y-%m-%d")
                    return (
                        f"Today\n{date_str}"
                        if di == 0
                        else f"T+{di}\n{date_str}"
                    )

                def _row_label(s: str | float) -> str:
                    try:
                        si = float(s)
                    except Exception:  # pylint: disable=broad-exception-caught
                        return str(s)
                    pct = (si - original_spot) / original_spot
                    if abs(pct) < 0.001:
                        return f"${_spot_formatter(si)}\n(~0%)"
                    sign = "+" if pct > 0 else ""
                    return f"${_spot_formatter(si)}\n({sign}{pct:.0%})"

                pivot_df.columns = pd.Index(
                    [_col_label(d) for d in pivot_df.columns],
                )
                pivot_df.index = pd.Index(
                    [_row_label(s) for s in pivot_df.index],
                )
                pivot_df.index.name = "Spot Price"

                styled = apply_financial_gradient_2d(
                    pivot_df.style,
                    center=0.0,
                    cmap="RdYlGn",
                )

                current_spot_label = _row_label(original_spot)
                if current_spot_label in pivot_df.index:
                    styled = styled.set_properties(
                        subset=cast(Any, pd.IndexSlice[current_spot_label, :]),
                        **{
                            "border-top": "1px solid black",
                            "border-bottom": "1px solid black",
                            "font-weight": "bold",
                        },
                    )

                config = _METRIC_CONFIG.get(metric_type, _METRIC_CONFIG["pnl"])
                styled = styled.format(config["fmt"])
                styled = styled.set_caption(
                    f"<strong>Time vs Price Analysis - "
                    f"{config['title']}</strong>",
                )
                styled = styled.set_table_styles(
                    [
                        {
                            "selector": "th",
                            "props": [
                                (
                                    "background-color",
                                    DEFAULT_PALETTE.dark_background,
                                ),
                                ("color", DEFAULT_PALETTE.white),
                                ("padding", "8px"),
                                ("text-align", "center"),
                                ("white-space", "pre-line"),
                            ],
                        },
                        {
                            "selector": "td",
                            "props": [
                                ("padding", "8px"),
                                ("text-align", "right"),
                            ],
                        },
                        {
                            "selector": "caption",
                            "props": [
                                ("caption-side", "top"),
                                ("font-size", "16px"),
                                ("padding", "10px"),
                            ],
                        },
                    ],
                )

                display(styled)

                # ---- summary stats ----
                spot_range_str = (
                    f"${_spot_formatter(spot_min)} to $"
                    f"{_spot_formatter(spot_max)} "
                    f"(±{spot_range_pct:.0%})"
                )
                time_range_str = (
                    f"{time_days[0]} to {time_days[-1]} days "
                    f"({len(time_days)} points)"
                )

                today_col = next(
                    (c for c in pivot_df.columns if c.startswith("Today")),
                    pivot_df.columns[0],
                )
                min_val = pivot_df.min().min()
                max_val = pivot_df.max().max()
                current_val = (
                    cast(
                        "float",
                        pivot_df.loc[current_spot_label, today_col],
                    )
                    if current_spot_label in pivot_df.index
                    else None
                )

                self.reporter.header(
                    f"Time vs Price Summary - {config['title']}",
                )
                print(f"Spot Range:  {spot_range_str}")
                print(f"Time Range:  {time_range_str}")
                if metric_type in ("pnl", "value", "theta"):
                    print(f"Minimum:     ${min_val:,.0f}")
                    print(f"Maximum:     ${max_val:,.0f}")
                    if current_val is not None:
                        print(f"Current:     ${current_val:,.0f}")
                else:
                    print(f"Minimum:     {min_val:,.2f}")
                    print(f"Maximum:     {max_val:,.2f}")
                    if current_val is not None:
                        print(f"Current:     {current_val:,.2f}")
                self.reporter.divider()

            except Exception as exc:  # pylint: disable=broad-exception-caught
                print(f"Error generating heatmap: {exc}")
                traceback.print_exc()

    def _render_spot_vol_heatmap(  # pylint: disable=R0913,R0914,R0915
        self,
        output_widget: widgets.Output,
        *,
        days_forward: int,
        metric_type: str,
        original_spot: float,
        original_val_date: datetime,
        avg_vol: float,
        spot_min: float,
        spot_max: float,
        vol_min: float,
        vol_max: float,
        spot_scenarios: np.ndarray[Any, np.dtype[Any]],
        vol_scenarios: np.ndarray[Any, np.dtype[Any]],
        grid_resolution: int,
        spot_shock_pct: float,
        vol_shock_pct: float,
        baseline_value: float,
    ) -> None:
        """Render (or re-render) the Spot x Volatility matplotlib heatmap.

        Render inside *output_widget*.
        """
        with output_widget:
            output_widget.clear_output(wait=True)

            # --- calculating status ---
            status = self._make_status_widget(
                "calculating",
                metric=metric_type,
                grid_size=grid_resolution,
            )
            display(status)

            start_time = time.time()

            try:
                valuation_date = original_val_date + timedelta(
                    days=days_forward,
                )

                if self.portfolio.positions:
                    earliest_expiry = min(
                        pos.option.maturity_date
                        for pos in self.portfolio.positions
                    )
                    if valuation_date > earliest_expiry:
                        print(
                            f"⚠️  Warning: Some positions expired before "
                            f"{valuation_date.strftime('%Y-%m-%d')}",
                        )

                original_calc_date = self.portfolio.valuation_date
                self.portfolio.valuation_date = valuation_date

                result_df = self.cache.get_or_calculate_spot_vol(
                    portfolio=self.portfolio,
                    analyzer=self.analyzer,
                    spot_scenarios=spot_scenarios,
                    vol_scenarios=vol_scenarios,
                    metric=metric_type,
                    baseline_value=baseline_value,
                    proportional_vol_scaling=True,
                )

                elapsed_time = time.time() - start_time
                output_widget.clear_output(wait=True)
                display(
                    self._make_status_widget(
                        "complete",
                        grid_size=grid_resolution,
                        elapsed_time=elapsed_time,
                    ),
                )

                self.portfolio.valuation_date = original_calc_date

                result_matrix = (
                    result_df.pivot(
                        index="volatility",
                        columns="spot_price",
                        values="value",
                    )
                    .sort_index(ascending=True)
                    .values
                )

                _, ax = plt.subplots(figsize=(12, 8))

                norm, cmap_obj = get_matplotlib_norm_and_cmap(
                    result_matrix,
                    center=0.0,
                    cmap_name="RdYlGn",
                )

                im = ax.imshow(
                    result_matrix,
                    extent=(
                        float(spot_min),
                        float(spot_max),
                        float(vol_min),
                        float(vol_max),
                    ),
                    origin="lower",
                    aspect="auto",
                    norm=norm,
                    cmap=cmap_obj,
                )

                x1, y1 = np.meshgrid(spot_scenarios, vol_scenarios)
                contours = ax.contour(
                    x1,
                    y1,
                    result_matrix,
                    levels=10,
                    colors=DEFAULT_PALETTE.black,
                    alpha=0.4,
                    linewidths=0.5,
                )
                ax.clabel(
                    contours,
                    inline=True,
                    fontsize=8,
                    fmt=lambda x: f"{x:,.0f}" if abs(x) >= 1 else f"{x:.2f}",
                )

                cbar = plt.colorbar(im, ax=ax)
                if metric_type in ("pnl", "value"):
                    vmin_, vmax_ = (
                        np.nanmin(result_matrix),
                        np.nanmax(
                            result_matrix,
                        ),
                    )
                    if (
                        np.isfinite(vmin_)
                        and np.isfinite(vmax_)
                        and vmin_ != vmax_
                    ):
                        ticks = np.linspace(vmin_, vmax_, 6)
                        cbar.set_ticks(ticks.tolist())
                        cbar.set_ticklabels(
                            [format_currency_for_axis(t, None) for t in ticks],
                        )

                cbar.set_label(
                    _METRIC_LABELS.get(metric_type, "Value"),
                    rotation=270,
                    labelpad=20,
                )

                ax.axhline(
                    y=avg_vol,
                    color=DEFAULT_PALETTE.black,
                    linestyle="--",
                    linewidth=1,
                    alpha=0.7,
                )
                ax.axvline(
                    x=original_spot,
                    color=DEFAULT_PALETTE.black,
                    linestyle="--",
                    linewidth=1,
                    alpha=0.7,
                )
                ax.plot(
                    original_spot,
                    avg_vol,
                    "o",
                    markersize=10,
                    markerfacecolor=DEFAULT_PALETTE.white,
                    markeredgecolor=DEFAULT_PALETTE.black,
                    markeredgewidth=2,
                    label="Current Position",
                )

                def _fmt_spot(x: float, _pos: int | None) -> str:
                    pct = (x - original_spot) / original_spot
                    if abs(pct) < 0.001:
                        return f"${x:,.0f}\n(~0%)"
                    sign = "+" if pct > 0 else ""
                    return f"${x:,.0f}\n({sign}{pct:.0%})"

                ax.xaxis.set_major_formatter(FuncFormatter(_fmt_spot))
                ax.yaxis.set_major_formatter(
                    FuncFormatter(lambda y, _p: f"{y:.0%}"),
                )

                date_str = valuation_date.strftime("%Y-%m-%d")
                title_suffix = (
                    f" (Today - {date_str})"
                    if days_forward == 0
                    else f" (T+{days_forward} - {date_str})"
                )
                if metric_type == "pnl":
                    subtitle = (
                        "\n(Relative to current market: "
                        "showing change from baseline)"
                    )
                elif metric_type == "value":
                    subtitle = (
                        "\n(Absolute values: showing total portfolio value)"
                    )
                else:
                    subtitle = (
                        "\n(Absolute values: showing metric at "
                        "each scenario point)"
                    )

                ax.set_xlabel("Spot Price", fontsize=12)
                ax.set_ylabel("Volatility", fontsize=12)
                ax.set_title(
                    f"Stress Test Heatmap: "
                    f"{_METRIC_LABELS.get(metric_type, 'Value')}"
                    f"{title_suffix}{subtitle}",
                    fontsize=14,
                    fontweight="bold",
                )
                ax.legend(loc="upper left")
                ax.grid(True, alpha=0.3, linestyle="--")
                plt.tight_layout()
                plt.show()

                # ---- summary stats ----
                current_spot_idx = np.argmin(
                    np.abs(spot_scenarios - original_spot),
                )
                current_vol_idx = np.argmin(np.abs(vol_scenarios - avg_vol))
                current_value = result_matrix[current_vol_idx, current_spot_idx]

                self.reporter.header(
                    f"Stress Test Summary - "
                    f"{_METRIC_LABELS.get(metric_type, 'Value')}",
                )
                print(f"Valuation Date: {date_str} (T+{days_forward})")
                print(
                    f"Current Market: Spot=$"
                    f"{original_spot:.2f}, Vol={avg_vol:.2%}",
                )
                print(
                    f"Stress Range:   Spot ±"
                    f"{spot_shock_pct:.0%}, Vol ±{vol_shock_pct:.0%}",
                )
                print(f"Grid Resolution: {grid_resolution}x{grid_resolution}")
                print("\nMetric Statistics:")

                if metric_type in ("pnl", "value"):
                    print(f"  Minimum:  ${result_matrix.min():,.0f}")
                    print(f"  Maximum:  ${result_matrix.max():,.0f}")
                    print(f"  Current:  ${current_value:,.0f}")
                    print(
                        f"  Range:    $"
                        f"{result_matrix.max() - result_matrix.min():,.0f}",
                    )
                else:
                    print(f"  Minimum:  {result_matrix.min():,.2f}")
                    print(f"  Maximum:  {result_matrix.max():,.2f}")
                    print(f"  Current:  {current_value:,.2f}")
                    print(
                        f"  Range:    "
                        f"{result_matrix.max() - result_matrix.min():,.2f}",
                    )
                self.reporter.divider()

            except Exception as exc:  # pylint: disable=broad-exception-caught
                elapsed_time = time.time() - start_time
                output_widget.clear_output(wait=True)
                display(self._make_status_widget("error", error_msg=str(exc)))
                print(f"\nError occurred after {elapsed_time:.2f} seconds")
                print(f"Error details: {exc}")
                traceback.print_exc()

    # ------------------------------------------------------------------
    # Private utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _make_status_widget(
        status_type: str,
        **kwargs: Any,  # noqa: ANN401  # ipywidgets **kwargs passthrough
    ) -> widgets.HTML:
        """Return a styled HTML status indicator widget."""
        styles = {
            "calculating": {
                "bg": "#FFF3CD",
                "border": "#FFECB5",
                "icon": "⏳",
                "title": "Calculating...",
            },
            "complete": {
                "bg": "#D4EDDA",
                "border": "#C3E6CB",
                "icon": "✅",
                "title": "Complete",
            },
            "error": {
                "bg": "#F8D7DA",
                "border": "#F5C6CB",
                "icon": "❌",
                "title": "Error",
            },
        }
        style = styles.get(status_type, styles["error"])

        if status_type == "calculating":
            metric = kwargs.get("metric", "portfolio")
            grid_size = kwargs.get("grid_size", "?")
            message = (
                f"<strong>{style['icon']} {style['title']}</strong><br/>"
                f"Computing {metric.upper()} across "
                f"{grid_size}x{grid_size} scenario grid..."
            )
        elif status_type == "complete":
            elapsed = kwargs.get("elapsed_time", 0)
            grid_size = kwargs.get("grid_size", "?")
            message = (
                f"<strong>{style['icon']} {style['title']}</strong><br/>"
                f"Generated {grid_size}x{grid_size} heatmap "
                f"in {elapsed:.2f} seconds"
            )
        else:
            error_msg = kwargs.get("error_msg", "Unknown error")
            message = (
                f"<strong>{style['icon']} "
                f"{style['title']}</strong><br/>{error_msg}"
            )

        return widgets.HTML(
            value=f"""
            <div style='
                background: {style["bg"]};
                border: 1px solid {style["border"]};
                padding: 12px 15px;
                border-radius: 5px;
                margin-bottom: 10px;
                font-size: 14px;
            '>
                {message}
            </div>
            """,
        )

    @staticmethod
    def _empty_widget(message: str) -> widgets.VBox:
        """Return a simple VBox containing a plain-text HTML label."""
        return widgets.VBox([widgets.HTML(f"<p>{message}</p>")])

    def _plot_mc_distribution(  # pylint: disable=R0913,R0914,R0915
        self,
        *,
        pnls_clean: np.ndarray[Any, np.dtype[Any]],
        expected_pnl: float,
        median_pnl: float,
        min_pnl: float,
        max_pnl: float,
        var_95: float,
        cvar_95: float,
        max_loss: float,
        is_concentrated: bool,
        most_common_pnl: tuple[float, int] | None,
        concentration_pct: float,
    ) -> None:
        """Render the side-by-side PDF histogram and CDF charts."""

        def _axis_fmt(
            ax: Axes,
            title: str,
            ylbl: str,
            yint: float = 0.0,
            xint: float = 0.0,
        ) -> None:
            ax.grid(False)
            ax.axhline(y=yint, color=DEFAULT_PALETTE.axis, linewidth=1)
            ax.axvline(x=xint, color=DEFAULT_PALETTE.axis, linewidth=1)
            ax.set_title(title, fontsize=14, fontweight="bold")
            ax.legend(fontsize=9, loc="best", framealpha=0.95)
            ax.xaxis.set_major_formatter(
                FuncFormatter(lambda x, _p: f"${x:,.0f}"),
            )
            ax.set_xlabel("P&L ($)", fontsize=13, fontweight="bold")
            ax.set_ylabel(ylbl, fontsize=13, fontweight="bold")

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 7))
        fig.patch.set_alpha(0.0)
        ax1.patch.set_alpha(0.0)
        ax2.patch.set_alpha(0.0)

        # ---- LEFT: PDF histogram ----
        n_bins = (
            30 if is_concentrated else min(50, max(20, len(pnls_clean) // 100))
        )
        bin_edges = np.linspace(min_pnl, max_pnl, n_bins + 1)
        bin_edges[-1] += 1e-10
        counts, bin_edges = np.histogram(pnls_clean, bins=bin_edges)
        bin_width = bin_edges[1] - bin_edges[0]
        total_count = counts.sum()
        density = (
            (counts / (total_count * bin_width))
            if (total_count > 0 and bin_width > 0)
            else counts.astype(float)
        )
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

        colors = [
            DEFAULT_PALETTE.negative if bc < 0 else "steelblue"
            for bc in bin_centers
        ]
        ax1.bar(
            bin_centers,
            density,
            width=bin_width * 0.9,
            alpha=0.7,
            edgecolor=DEFAULT_PALETTE.black,
            linewidth=0.5,
            color=colors,
        )

        ax1.axvline(
            expected_pnl,
            color=DEFAULT_PALETTE.medium_background,
            linestyle="--",
            linewidth=2.5,
            label=f"Expected: ${expected_pnl:,.0f}",
            zorder=10,
            alpha=0.8,
        )

        var_label = (
            f"95% VaR (5th %ile): ${var_95:,.0f}"
            if var_95 < 0
            else f"95% Confidence Floor: ${var_95:,.0f}"
        )
        ax1.axvline(
            var_95,
            color="orange",
            linestyle="--",
            linewidth=2,
            label=var_label,
            zorder=10,
            alpha=0.8,
        )

        if cvar_95 < expected_pnl:
            ax1.axvline(
                cvar_95,
                color=DEFAULT_PALETTE.negative,
                linestyle="--",
                linewidth=2,
                label=f"95% CVaR (avg worst 5%): ${cvar_95:,.0f}",
                zorder=10,
                alpha=0.8,
            )

        ax1.axvline(
            0,
            color=DEFAULT_PALETTE.black,
            linestyle="-",
            linewidth=1,
            alpha=0.3,
            zorder=5,
        )

        if max_loss < 0:
            ax1.axvline(
                max_loss,
                color=DEFAULT_PALETTE.negative,
                linestyle=":",
                linewidth=2,
                label=f"Worst Case: ${max_loss:,.0f}",
                zorder=10,
                alpha=0.6,
            )

        x_buffer = (max_pnl - min_pnl) * 0.05
        x_min, x_max = min_pnl - x_buffer, max_pnl + x_buffer
        ax1.set_xlim(x_min, x_max)
        ax1.yaxis.set_major_formatter(FuncFormatter(lambda y, _p: f"{y:.4%}"))

        yint_, _ = ax1.get_ylim()
        xint_, _ = ax1.get_xlim()
        title = (
            (
                "Monte Carlo P&L Distribution\n(Concentrated"
                " - Typical for Short Options)"
            )
            if is_concentrated
            else "Monte Carlo P&L Distribution"
        )
        _axis_fmt(
            ax1,
            title,
            ylbl="Probability Density",
            yint=yint_,
            xint=xint_,
        )

        if is_concentrated and most_common_pnl is not None:
            ax1.text(
                0.02,
                0.98,
                f"Most Common: ${most_common_pnl[0]:,.2f}\n"
                f"({concentration_pct:.1f}% of scenarios)",
                transform=ax1.transAxes,
                fontsize=10,
                verticalalignment="top",
                bbox={"boxstyle": "round", "facecolor": "wheat", "alpha": 0.7},
            )

        # ---- RIGHT: CDF ----
        sorted_pnls = np.sort(pnls_clean)
        cdf = np.arange(1, len(sorted_pnls) + 1) / len(sorted_pnls)

        ax2.plot(
            sorted_pnls,
            cdf,
            linewidth=2.5,
            color=DEFAULT_PALETTE.dark_background,
            label="Empirical CDF",
            zorder=10,
        )
        ax2.axhline(
            0.05,
            color="orange",
            linestyle="--",
            linewidth=1.5,
            alpha=0.6,
            zorder=5,
            label="5th Percentile",
        )
        ax2.axvline(
            var_95,
            color="orange",
            linestyle="--",
            linewidth=1.5,
            alpha=0.6,
            zorder=5,
        )
        ax2.axhline(
            0.50,
            color=DEFAULT_PALETTE.medium_grey,
            linestyle=":",
            linewidth=1.5,
            alpha=0.5,
            zorder=5,
            label="Median",
        )
        ax2.axvline(
            median_pnl,
            color=DEFAULT_PALETTE.medium_grey,
            linestyle=":",
            linewidth=1.5,
            alpha=0.5,
            zorder=5,
        )

        idx_exp = np.searchsorted(sorted_pnls, expected_pnl)
        cdf_at_exp = (
            idx_exp / len(sorted_pnls) if idx_exp < len(sorted_pnls) else 1.0
        )
        ax2.axvline(
            expected_pnl,
            color=DEFAULT_PALETTE.medium_background,
            linestyle="--",
            linewidth=1.5,
            label=f"Expected (~{cdf_at_exp * 100:.0f}th %ile)",
            alpha=0.7,
            zorder=8,
        )

        if min_pnl < 0 < max_pnl:
            ax2.axvline(
                0,
                color=DEFAULT_PALETTE.black,
                linestyle="-",
                linewidth=1,
                alpha=0.4,
                zorder=3,
                label="Break-even (P&L=0)",
            )

        ax2.set_ylim(-0.02, 1.05)
        ax2.set_xlim(x_min, x_max)
        # Safety check - ensure x-axis is not inverted
        if ax2.get_xlim()[0] > ax2.get_xlim()[1]:
            ax2.set_xlim(ax2.get_xlim()[1], ax2.get_xlim()[0])

        ax2.yaxis.set_major_formatter(FuncFormatter(lambda y, _p: f"{y:.0%}"))
        yint_, _ = ax1.get_ylim()
        xint_, _ = ax1.get_xlim()
        cdf_title = (
            "Cumulative Distribution Function\n"
            '(Shows: "What % of outcomes are ≤ this P&L?")'
        )
        _axis_fmt(
            ax2,
            cdf_title,
            ylbl="Cumulative Probability",
            yint=yint_,
            xint=xint_,
        )

        plt.tight_layout()
        plt.show()
