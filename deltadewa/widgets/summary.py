"""Net hedge summary widget for portfolio metrics.

This module provides a widget that displays key portfolio metrics and health
indicators in a compact, always-visible format.
"""

from typing import TYPE_CHECKING

import ipywidgets as widgets
import numpy as np

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import crash_convexity_pct
from deltadewa.analysis.volatility import get_volatility_stats
from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.formatters.html import format_html_badge, format_html_metric
from deltadewa.portfolio.monte_carlo import drift_measure_label

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


class NetHedgeSummary:
    """Always-visible KPI header showing key portfolio hedge metrics.

    Displays core Greeks, crash convexity indicators, and probabilistic
    stats in a compact, color-coded format. Designed to be shown at the
    top of all dashboard modes for at-a-glance portfolio health.

    Attributes:
        portfolio: OptionPortfolio instance to analyze
        widget: VBox containing the KPI display

    Example:
        summary = NetHedgeSummary(portfolio)
        summary.display()

        # Update when portfolio changes
        summary.update()

    """

    # Fixed presentation gridpoints for the crash-convexity profile.
    # Future refinement: fold these and the crash scenario-table gridpoints
    # into a single IPS-defined crash scenario *set* (not the single
    # crash_scenario_pct scalar) so the ladder is policy-driven, not
    # hardcoded. Deliberately NOT single-sourced to crash_scenario_pct.
    _CRASH_RUNG_SHOCKS: tuple[float, ...] = (-10.0, -20.0, -30.0)

    def __init__(
        self,
        portfolio: "OptionPortfolio",
        *,
        crash_vol_shock: float = 0.0,
    ) -> None:
        """Initialize net hedge summary widget.

        Args:
            portfolio: OptionPortfolio instance
            crash_vol_shock: Flat additive crash vol bump as a decimal,
                single-sourced from ``IpsConvexity.crash_vol_shock`` (pass
                ``ctx.ips_config.convexity.crash_vol_shock``). Used to reprice
                the hedge-only crash-convexity ladder. Defaults to ``0.0``.

        """
        self.portfolio = portfolio
        self._crash_vol_shock = crash_vol_shock
        self.widget = None
        self._create_widget()

    def _crash_convexity_rungs(self) -> list[tuple[float, float]]:
        """Hedge-only repriced crash convexity at the fixed ladder gridpoints.

        Returns ``(shock_pct, convexity_pct)`` pairs at -10/-20/-30% - the
        same hedge-only repriced basis (crash spot + IPS vol shock, underlying
        excluded) as the health convexity gauge, so a rung equals the gauge
        exactly at an equal crash depth. See ``docs/repricing-methodology.md``.
        """
        return [
            (
                shock,
                crash_convexity_pct(
                    self.portfolio,
                    crash_move=shock / 100.0,
                    vol_shock=self._crash_vol_shock,
                ),
            )
            for shock in self._CRASH_RUNG_SHOCKS
        ]

    def _format_large_block(
        self,
        color: str,
        text_color: str,
        name: str,
        value_str: str,
    ) -> str:
        """Return formatted HTML for large block.

        Note:
            Uses centralized formatter from deltadewa.formatters

        """
        return format_html_badge(
            label=name,
            value=value_str,
            color=color,
            text_color=text_color,
            size="large",
        )

    def _format_greek(
        self,
        name: str,
        value: float,
        is_cost: bool = False,
        is_neutral: bool = False,
    ) -> str:
        """Format a Greek metric as colored HTML badge.

        Args:
            name: Greek name
            value: Greek value
            is_cost: Whether this represents a cost (red) vs profit (green)
            is_neutral: Whether to ignore the value and use a netural colour

        Returns:
            HTML string with formatted badge

        Note:
            Uses centralized formatter from deltadewa.formatters

        """
        # Determine the format type based on the metric name
        matches_to_format_as_currency = [
            "Value",
            "Cost",
            "Theta",
            "P&L",
            "Profit",
            "Loss",
            "Carry",
            "Price",
        ]
        format_type = (
            "currency"
            if any(
                sub.lower() in (name or "").lower()
                for sub in matches_to_format_as_currency
            )
            else "number"
        )

        return format_html_metric(
            name=name,
            value=value,
            format_type=format_type,
            is_cost=is_cost,
            is_neutral=is_neutral,
        )

    def _format_pct(
        self,
        name: str,
        value: float,
        is_neutral: bool = False,
    ) -> str:
        """Format a percentage metric as colored HTML badge.

        Args:
            name: Percent metric name
            value: Percent metric value
            is_neutral: Whether to ignore the value and use a netural colour

        Returns:
            HTML string with formatted badge

        Note:
            Uses centralized formatter from deltadewa.formatters

        """
        return format_html_metric(
            name=name,
            value=value,
            format_type="percentage",
            is_cost=False,
            is_neutral=is_neutral,
        )

    def _create_widget(self) -> None:
        """Create the KPI display widget."""
        self.value_metrics_html = widgets.HTML(value="")
        self.health_indicators_r1_html = widgets.HTML(value="")
        self.health_indicators_r2_html = widgets.HTML(value="")
        self.diagnostics_html = widgets.HTML(value="")
        self.vol_metrics_html = widgets.HTML(value="")
        self.crash_indicators_html = widgets.HTML(value="")
        self.prob_stats_html = widgets.HTML(value="")

        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    f"""
                    <div style="background-color:"""
                    f"""{DEFAULT_PALETTE.med_dark_background};"""
                    """ color:white; padding:10px; border-radius:5px 5px 0 0;">
                    <h3 style="margin:0;">Hedge Summary</h3>
                    </div>
                    """,
                ),
                widgets.HTML(
                    """
                    <h4 style='margin:10px 10px 5px 10px;'>"""
                    """Portfolio Value</h4>""",
                ),
                self.value_metrics_html,
                widgets.HTML(
                    """
                    <h4 style='margin:10px 10px 5px 10px;'>"""
                    """Health Indicators</h4>""",
                ),
                self.health_indicators_r1_html,
                self.health_indicators_r2_html,
                widgets.Accordion(
                    children=[
                        widgets.VBox(
                            [
                                self.diagnostics_html,
                                self.vol_metrics_html,
                                self.crash_indicators_html,
                            ],
                        ),
                    ],
                    titles=("Diagnostics (Expandable)",),
                ),
            ],
            layout=widgets.Layout(
                border=f"2px solid {DEFAULT_PALETTE.med_dark_background}",
                margin="10px 0",
            ),
        )

        self.update()

    def update(self) -> None:  # pylint: disable=R0914,R0912,R0915
        """Update all metrics with current portfolio data."""
        stats = self.portfolio.summary_stats()
        vol_stats = get_volatility_stats(self.portfolio)

        value_html = (
            self._format_greek(
                "Underlying Value",
                stats["total_underlying_value"],
            )
            + self._format_greek("Option Value", stats["total_value"])
            + self._format_greek(
                "Total Portfolio Value",
                stats["total_portfolio_value"],
            )
        )
        self.value_metrics_html.value = (
            f'<div style="padding:10px;">{value_html}</div>'
        )

        # Crash convexity: hedge-only, repriced (docs/repricing-methodology).
        # These rungs express the option legs' convexity; the net book-P&L
        # question is answered by the separate "P&L @ -20%" indicator below.
        crash_html = "".join(
            self._format_pct(
                f"Convexity @ {shock:+.0f}% (hedge-only)",
                convexity / 100.0,
            )
            for shock, convexity in self._crash_convexity_rungs()
        )
        self.crash_indicators_html.value = (
            f'<div style="padding:10px;">{crash_html}</div>'
        )

        # Core Greeks
        health_indicators_r1_html = (
            self._format_greek("Total Delta", stats["total_delta"])
            + self._format_greek("Net Delta", stats["net_delta"])
            + self._format_greek("Theta (Daily)", stats["total_theta"])
        )
        self.health_indicators_r1_html.value = (
            f'<div style="padding:10px;">{health_indicators_r1_html}</div>'
        )

        # Net book P&L at -20% (includes the underlying) — the legitimately
        # equity-netted figure, kept separate from the hedge-only convexity
        # ladder above.
        net_pnl_20 = self.portfolio.calculate_pnl_at_expiry(
            self.portfolio.spot_price * 0.80,
            include_underlying=True,
        )
        health_indicators_r2_html = (
            self._format_greek("Vega", stats["total_vega"])
            + self._format_greek("Gamma", stats["total_gamma"])
            + self._format_greek("P&L @ -20%", net_pnl_20)
        )
        self.health_indicators_r2_html.value = (
            f'<div style="padding:10px;">{health_indicators_r2_html}</div>'
        )

        diagnostics_html = (
            self._format_greek("Hedge Ratio", stats["hedge_ratio"])
            + self._format_greek("Delta Adj.", stats["delta_adjustment"])
            + self._format_greek("Rho", stats["total_rho"])
        )
        self.diagnostics_html.value = (
            f'<div style="padding:10px;">{diagnostics_html}</div>'
        )

        vol_html = (
            self._format_pct(
                "Min Vol",
                stats["volatility_min"],
                is_neutral=True,
            )
            + self._format_pct(
                "Max Vol",
                stats["volatility_max"],
                is_neutral=True,
            )
            + self._format_pct(
                "Vega-W.Avg Vol",
                vol_stats.get("avg_volatility", 0.0),
                is_neutral=True,
            )
            + self._format_greek(
                "Custom Vol Count",
                stats["custom_volatility_count"],
                is_neutral=True,
            )
        )
        self.vol_metrics_html.value = (
            f'<div style="padding:10px;">{vol_html}</div>'
        )

        # Probabilistic stats (expandable)
        analyzer = PortfolioAnalyzer(self.portfolio)
        analysis = analyzer.risk_reward_analysis()

        prob_html = "<div style='padding:10px;'>"

        # Check if Monte Carlo results exist and contain a sized array
        mc_results = self.portfolio.monte_carlo_results
        if mc_results is not None:
            sim_pnls = mc_results.get("simulated_pnls")
            if (
                isinstance(sim_pnls, (list, tuple, np.ndarray))
                and len(sim_pnls) > 0
            ):
                expected_pnl = mc_results.get("expected_pnl", 0)

                prob_profit = mc_results.get("prob_profit", 0)
                measure = drift_measure_label(
                    str(mc_results.get("drift_measure", "risk_neutral")),
                )
                prob_html += "<p><strong>Probability of Profit:"
                prob_html += f"</strong> {prob_profit * 100:.1f}% "
                prob_html += f"<em>({measure} drift)</em></p>"
                prob_html += "<p><strong>Expected Value:</strong> $"
                prob_html += f"{expected_pnl:,.2f}</p>"
        else:
            prob_html += "<p><strong>Probability of Profit:</strong>"
            prob_html += " N/A (requires Monte Carlo)</p>"
            prob_html += "<p><strong>Expected Value:</strong>"
            prob_html += " N/A (requires Monte Carlo)</p>"

        max_loss_opt = analysis.get("max_loss_options", None)
        max_loss_total = analysis.get("max_loss_total", None)
        max_loss_result = "<p><strong>Max Loss:</strong> Options: "
        if max_loss_opt is None:
            max_loss_result += "N/A"
        elif not max_loss_opt.get("is_unlimited", True):
            max_loss_result += f"${-max_loss_opt.get('max_loss', 0):,.2f}"
        else:
            max_loss_result += "Unlimited"

        max_loss_result += ";&nbsp;&nbsp;&nbsp;Total: "
        if max_loss_total is None:
            max_loss_result += "N/A"
        elif not max_loss_total.get("is_unlimited", True):
            max_loss_result += f"${-max_loss_total.get('max_loss', 0):,.2f}"
        else:
            max_loss_result += "Unlimited"
        max_loss_result += "</p>"
        prob_html += max_loss_result

        max_profit_opt = analysis.get("max_profit_options", None)
        max_profit_total = analysis.get("max_profit_total", None)
        max_profit_result = "<p><strong>Max Profit:</strong> Options: "
        if max_profit_opt is None:
            max_profit_result += "N/A"
        elif not max_profit_opt.get("is_unlimited", True):
            max_profit_result += f"${-max_profit_opt.get('max_profit', 0):,.2f}"
        else:
            max_profit_result += "Unlimited"

        max_profit_result += ";&nbsp;&nbsp;&nbsp;Total: "
        if max_profit_total is None:
            max_profit_result += "N/A"
        elif not max_profit_total.get("is_unlimited", True):
            max_profit_result += (
                f"${-max_profit_total.get('max_profit', 0):,.2f}"
            )
        else:
            max_profit_result += "Unlimited"
        max_profit_result += "</p>"
        prob_html += max_profit_result

        breakevens = analysis.get("breakeven_total", [])
        if breakevens:
            be_str = ", ".join([f"${be:.2f}" for be in breakevens])
        else:
            be_str = "N/A"
        prob_html += f"<p><strong>Breakeven Points:</strong> {be_str}</p>"

        prob_html += "</div>"
        self.prob_stats_html.value = prob_html

    def display(self) -> widgets.VBox | None:
        """Get the display widget.

        Returns:
            VBox widget containing the KPI summary

        """
        return self.widget
