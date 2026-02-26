"""Summary and insights mixin for portfolio analysis."""

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


class SummaryMixin:
    """Mixin for insights generation and summary formatting.

    Provides methods for generating formatted risk summaries,
    risk/reward summaries, and actionable insights based on portfolio analysis.
    """

    if TYPE_CHECKING:
        portfolio: "OptionPortfolio"

        # pylint: disable=missing-function-docstring
        def calculate_carry_metrics(self) -> dict: ...

        # pylint: disable=missing-function-docstring
        def analyze_risk_concentration(self) -> dict: ...

        # pylint: disable=missing-function-docstring, unused-argument
        def risk_reward_analysis(
            self,
            spot_range: np.ndarray | None = None,
            num_simulations: int = 10000,
        ) -> dict: ...

    def format_risk_summary(self, stats: dict | None = None) -> str:
        """Generate formatted risk summary text.

        Args:
            stats: Portfolio summary stats (uses current if None)

        Returns:
            Formatted string with risk analysis

        """
        if stats is None:
            stats = self.portfolio.summary_stats()
        if stats is None:
            return "No portfolio data available."

        lines = []
        lines.append("=" * 70)
        lines.append("PORTFOLIO RISK SUMMARY")
        lines.append("=" * 70)
        lines.append("")

        # Delta analysis
        lines.append("DIRECTIONAL RISK (DELTA):")
        lines.append(f"  Portfolio Delta: {stats['total_delta']:,.2f}")
        lines.append(
            f"  Notional Position: {stats['underlying_quantity']:,.2f}",
        )
        lines.append(f"  Net Delta: {stats['net_delta']:,.2f}")
        lines.append(f"  Hedge Ratio: {stats['hedge_ratio']:.2f}%")

        if abs(stats["net_delta"]) < abs(stats["underlying_quantity"]) * 0.1:
            lines.append("  ✓ Well hedged (net delta < 10% of notional)")
        elif stats["net_delta"] > 0:
            lines.append("  ⚠ Net long exposure - vulnerable to price decline")
        else:
            lines.append(
                "  ⚠ Net short exposure - vulnerable to price increase",
            )

        lines.append("")

        # Gamma analysis
        lines.append("CONVEXITY RISK (GAMMA):")
        lines.append(f"  Total Gamma: {stats['total_gamma']:.4f}")
        if stats["total_gamma"] > 0:
            lines.append("  → Long gamma: Delta increases as spot rises")
        else:
            lines.append("  → Short gamma: Delta decreases as spot rises")

        lines.append("")

        # Vega analysis
        lines.append("VOLATILITY RISK (VEGA):")
        lines.append(f"  Total Vega: {stats['total_vega']:.2f}")
        if stats["total_vega"] > 0:
            lines.append("  → Long vega: Benefits from volatility increase")
        else:
            lines.append("  → Short vega: Benefits from volatility decrease")

        lines.append("")

        # Theta analysis
        lines.append("TIME DECAY (THETA):")
        lines.append(f"  Total Theta: ${stats['total_theta']:.2f}/day")
        if stats["total_theta"] > 0:
            lines.append("  → Positive theta: Earning from time decay")
        else:
            lines.append("  → Negative theta: Paying for time decay")

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)

    def generate_insights(self) -> list[str]:
        """Generate actionable insights based on portfolio analysis.

        Returns:
            list of insight strings

        """
        insights = []
        stats = self.portfolio.summary_stats()

        # pylint: disable=assignment-from-no-return
        carry_metrics = self.calculate_carry_metrics()

        # pylint: disable=assignment-from-no-return
        concentration = self.analyze_risk_concentration()

        # Delta insights
        if abs(stats["net_delta"]) > abs(stats["underlying_quantity"]) * 0.2:
            insights.append(
                f"⚠ High net delta exposure ({stats['net_delta']:.0f}) - "
                "consider rebalancing hedge",
            )

        # Theta insights
        if carry_metrics["is_positive_carry"]:
            insights.append(
                f"✓ Positive carry: Earning ${carry_metrics['total_theta_daily']:.2f}/day "
                f"(${carry_metrics['total_theta_monthly']:.0f}/month)",
            )
        else:
            insights.append(
                f"⚠ Negative carry: Paying ${-carry_metrics['total_theta_daily']:.2f}/day "
                "for options positions",
            )

        # Concentration insights
        for metric, score in concentration["concentration_scores"].items():
            if "strike" in metric and score > 30:
                insights.append(
                    f"⚠ {metric.split('_')[0].upper()} concentrated in single strike "
                    f"({score:.1f}%) - consider diversifying",
                )

        # Gamma insights
        if abs(stats["total_gamma"]) > 0.1:
            direction = "long" if stats["total_gamma"] > 0 else "short"
            insights.append(
                f"ℹ High {direction} gamma ({abs(stats['total_gamma']):.4f}) - "
                "delta will change significantly with spot moves",
            )

        # Vega insights
        if abs(stats["total_vega"]) > 100:
            direction = "benefits from" if stats["total_vega"] > 0 else "hurt by"
            insights.append(
                f"ℹ Significant vega exposure ({abs(stats['total_vega']):.0f}) - "
                f"portfolio {direction} volatility increases",
            )

        return insights

    def format_risk_reward_summary(
        self,
        spot_range: np.ndarray | None = None,
    ) -> str:
        """Generate formatted risk/reward summary text.

        Args:
            spot_range: Array of spot prices to analyze (optional)

        Returns:
            Formatted string with risk/reward analysis

        """
        # pylint: disable=assignment-from-no-return
        analysis = self.risk_reward_analysis(spot_range)
        portfolio_value = 0.0

        lines = []
        lines.append("=" * 80)
        lines.append("PORTFOLIO RISK/REWARD ANALYSIS")
        lines.append("=" * 80)
        lines.append("")

        # Capital Requirements
        lines.append("CAPITAL REQUIREMENTS:")
        net_debit = analysis["net_debit"]
        if net_debit > 0:
            lines.append(
                f"  Net Debit: ${net_debit:,.2f} (capital required to implement)",
            )
        else:
            lines.append(f"  Net Credit: ${-net_debit:,.2f} (capital received)")
        lines.append("")

        # Options Only Risk/Reward
        lines.append("OPTIONS ONLY RISK/REWARD:")
        max_loss_opts = analysis["max_loss_options"]
        max_profit_opts = analysis["max_profit_options"]

        if max_loss_opts["is_unlimited"]:
            lines.append("  Max Loss: UNLIMITED (naked short positions)")
        else:
            loss_line = f"  Max Loss: ${-max_loss_opts['max_loss']:,.2f}"
            if net_debit != 0:
                loss_pct = (-max_loss_opts["max_loss"] / abs(net_debit)) * 100
                loss_line += f" ({loss_pct:.1f}% of net debit)"
            lines.append(loss_line)
            lines.append(
                f"    └─ Occurs at spot price: ${max_loss_opts['spot_at_max_loss']:.2f}",
            )

        if max_profit_opts["is_unlimited"]:
            lines.append("  Max Profit: UNLIMITED")
        else:
            profit_line = f"  Max Profit: ${max_profit_opts['max_profit']:,.2f}"
            if net_debit > 0:
                roi = (max_profit_opts["max_profit"] / net_debit) * 100
                profit_line += f" ({roi:.1f}% return on net debit)"
            lines.append(profit_line)
            lines.append(
                f"    └─ Occurs at spot price: ${max_profit_opts['spot_at_max_profit']:.2f}",
            )

        if analysis["breakeven_options"]:
            breakevens_str = ", ".join(
                [f"${be:.2f}" for be in analysis["breakeven_options"]],
            )
            lines.append(f"  Breakeven Points: {breakevens_str}")
        else:
            lines.append("  Breakeven Points: None identified")
        lines.append("")

        # Total Portfolio Risk/Reward
        if self.portfolio.underlying_quantity != 0:
            lines.append("TOTAL PORTFOLIO RISK/REWARD (Options + Underlying):")
            max_loss_total = analysis["max_loss_total"]
            max_profit_total = analysis["max_profit_total"]

            if max_loss_total["is_unlimited"]:
                lines.append(
                    "  Max Loss: UNLIMITED (short underlying position)",
                )
            else:
                portfolio_value = self.portfolio.total_portfolio_value()
                loss_line = f"  Max Loss: ${-max_loss_total['max_loss']:,.2f}"
                if portfolio_value > 0:
                    loss_pct = (-max_loss_total["max_loss"] / portfolio_value) * 100
                    loss_line += f" ({loss_pct:.1f}% of portfolio value)"
                lines.append(loss_line)
                lines.append(
                    f"    └─ Occurs at spot price: ${max_loss_total['spot_at_max_loss']:.2f}",
                )

            if max_profit_total["is_unlimited"]:
                if self.portfolio.underlying_quantity > 0:
                    lines.append(
                        "  Max Profit: UNLIMITED (long underlying position)",
                    )
                else:
                    lines.append("  Max Profit: UNLIMITED")
                lines.append("    └─ Profit increases with spot price")
            else:
                profit_line = f"  Max Profit: ${max_profit_total['max_profit']:,.2f}"
                if portfolio_value > 0:
                    profit_pct = (
                        max_profit_total["max_profit"] / portfolio_value
                    ) * 100
                    profit_line += f" ({profit_pct:.1f}% of portfolio value)"
                lines.append(profit_line)
                lines.append(
                    f"    └─ Occurs at spot price: ${max_profit_total['spot_at_max_profit']:.2f}",
                )

            if analysis["breakeven_total"]:
                breakevens_str = ", ".join(
                    [f"${be:.2f}" for be in analysis["breakeven_total"]],
                )
                lines.append(f"  Breakeven Points: {breakevens_str}")
            else:
                lines.append("  Breakeven Points: None identified")
            lines.append("")

        # Probability Analysis
        lines.append("PROBABILITY ANALYSIS:")
        prob = analysis["prob_profit"]
        lines.append(f"  Chance of Profit: {prob*100:.1f}%")
        lines.append(
            f"  Expected Value: ${analysis['expected_pnl']:,.2f} (probabilistic weighted average)",
        )
        lines.append("")

        # Risk/Reward Ratio
        if not max_loss_opts["is_unlimited"] and not max_profit_opts["is_unlimited"]:
            if max_profit_opts["max_profit"] > 0 and max_loss_opts["max_loss"] < 0:
                # Standard risk/reward ratio: profit potential to loss potential
                rr_ratio = max_profit_opts["max_profit"] / -max_loss_opts["max_loss"]
                lines.append(
                    f"RISK/REWARD RATIO: {rr_ratio:.2f}:1 (max profit to max loss)",
                )
        lines.append("=" * 80)

        return "\n".join(lines)

    def print_risk_reward_summary(self, spot_range: np.ndarray | None = None):
        """Print a formatted risk/reward summary of the portfolio.

        Args:
            spot_range: Array of spot prices to analyze (optional)

        """
        summary = self.format_risk_reward_summary(spot_range)
        print(summary)
