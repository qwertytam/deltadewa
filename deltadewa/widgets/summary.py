"""Net hedge summary widget for portfolio metrics.

This module provides a widget that displays key portfolio metrics and health
indicators in a compact, always-visible format.
"""

from typing import TYPE_CHECKING

import ipywidgets as widgets  # type: ignore[import-untyped]
import numpy as np

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.volatility import get_volatility_stats
from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.formatters.html import format_html_badge, format_html_metric

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

    def __init__(self, portfolio: "OptionPortfolio") -> None:
        """Initialize net hedge summary widget.

        Args:
            portfolio: OptionPortfolio instance

        """
        self.portfolio = portfolio
        self.widget = None
        self._create_widget()

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

    def _format_crash_indicator(self, shock_pct: float, pnl: float) -> str:
        """Format crash convexity indicator.

        Args:
            shock_pct: Spot price shock percentage
            pnl: P&L at that shock level

        Returns:
            HTML string with formatted indicator

        """
        if pnl >= 0:
            color = DEFAULT_PALETTE.positive
        elif pnl > -1000:
            color = DEFAULT_PALETTE.orange
        else:
            color = DEFAULT_PALETTE.negative

        return (
            f'<div style="display:inline-block; background-color:{color}; '
            f"color:white; padding:6px 10px; margin:3px; "
            f'border-radius:3px; font-size:12px; min-width:100px;">'
            f"<strong>{shock_pct:+.0f}%:</strong> ${pnl:,.0f}"
            f"</div>"
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
                    <div style="background-color:{DEFAULT_PALETTE.med_dark_background};"""
                    """ color:white; padding:10px; border-radius:5px 5px 0 0;">
                    <h3 style="margin:0;">Hedge Summary</h3>
                    </div>
                    """,
                ),
                widgets.HTML(
                    "<h4 style='margin:10px 10px 5px 10px;'>Portfolio Value</h4>",
                ),
                self.value_metrics_html,
                widgets.HTML(
                    "<h4 style='margin:10px 10px 5px 10px;'>Health Indicators</h4>",
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

    def update(self) -> None:
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
        self.value_metrics_html.value = f'<div style="padding:10px;">{value_html}</div>'

        # Crash convexity
        current_spot = self.portfolio.spot_price
        pnl_0 = self.portfolio.calculate_pnl_at_expiry(
            current_spot * 1.00,
            include_underlying=True,
        )
        pnl_10 = self.portfolio.calculate_pnl_at_expiry(
            current_spot * 0.90,
            include_underlying=True,
        )
        pnl_20 = self.portfolio.calculate_pnl_at_expiry(
            current_spot * 0.80,
            include_underlying=True,
        )
        pnl_30 = self.portfolio.calculate_pnl_at_expiry(
            current_spot * 0.70,
            include_underlying=True,
        )

        crash_html = (
            self._format_greek("Current Price", pnl_0)
            + self._format_greek("Price -10%", pnl_10)
            + self._format_greek("Price -20%", pnl_20)
            + self._format_greek("Price -30%", pnl_30)
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

        health_indicators_r2_html = (
            self._format_greek("Vega", stats["total_vega"])
            + self._format_greek("Gamma", stats["total_gamma"])
            + self._format_greek("P&L @ -20%", pnl_20)
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
                vol_stats["avg_volatility"],
                is_neutral=True,
            )
            + self._format_greek(
                "Custom Vol Count",
                stats["custom_volatility_count"],
                is_neutral=True,
            )
        )
        self.vol_metrics_html.value = f'<div style="padding:10px;">{vol_html}</div>'

        # Probabilistic stats (expandable)
        analyzer = PortfolioAnalyzer(self.portfolio)
        analysis = analyzer.risk_reward_analysis()

        prob_html = "<div style='padding:10px;'>"

        # Check if Monte Carlo results exist and contain a sized array
        mc_results = self.portfolio.monte_carlo_results
        if mc_results is not None:
            sim_pnls = mc_results.get("simulated_pnls")
            if isinstance(sim_pnls, (list, tuple, np.ndarray)) and len(sim_pnls) > 0:
                expected_pnl = mc_results.get("expected_pnl", 0)

                prob_profit = mc_results.get("prob_profit", 0)
                prob_html += f"<p><strong>Probability of Profit:</strong> {prob_profit*100:.1f}%</p>"
                prob_html += (
                    f"<p><strong>Expected Value:</strong> ${expected_pnl:,.2f}</p>"
                )
        else:
            prob_html += "<p><strong>Probability of Profit:</strong> N/A (requires Monte Carlo)</p>"
            prob_html += (
                "<p><strong>Expected Value:</strong> N/A (requires Monte Carlo)</p>"
            )

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
            max_profit_result += f"${-max_profit_total.get('max_profit', 0):,.2f}"
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
