"""Insights and summary formatting mixin for portfolio analysis."""

from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from deltadewa.portfolio import OptionPortfolio


class InsightsMixin:
    """
    Mixin for insights generation and risk summary formatting.

    Provides methods for generating formatted risk summaries
    and actionable insights based on portfolio analysis.
    """

    if TYPE_CHECKING:
        portfolio: OptionPortfolio

        # pylint: disable=missing-function-docstring
        def calculate_carry_metrics(self) -> Dict: ...

        # pylint: disable=missing-function-docstring
        def analyze_risk_concentration(self) -> Dict: ...

    def format_risk_summary(self, stats: Optional[Dict] = None) -> str:
        """
        Generate formatted risk summary text.

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
            f"  Notional Position: {stats['underlying_quantity']:,.2f}"
        )
        lines.append(f"  Net Delta: {stats['net_delta']:,.2f}")
        lines.append(f"  Hedge Ratio: {stats['hedge_ratio']:.2f}%")

        if abs(stats["net_delta"]) < abs(stats["underlying_quantity"]) * 0.1:
            lines.append("  ✓ Well hedged (net delta < 10% of notional)")
        elif stats["net_delta"] > 0:
            lines.append("  ⚠ Net long exposure - vulnerable to price decline")
        else:
            lines.append(
                "  ⚠ Net short exposure - vulnerable to price increase"
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

    def generate_insights(self) -> List[str]:
        """
        Generate actionable insights based on portfolio analysis.

        Returns:
            List of insight strings
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
                "consider rebalancing hedge"
            )

        # Theta insights
        if carry_metrics["is_positive_carry"]:
            insights.append(
                f"✓ Positive carry: Earning ${carry_metrics['total_theta_daily']:.2f}/day "
                f"(${carry_metrics['total_theta_monthly']:.0f}/month)"
            )
        else:
            insights.append(
                f"⚠ Negative carry: Paying ${-carry_metrics['total_theta_daily']:.2f}/day "
                "for options positions"
            )

        # Concentration insights
        for metric, score in concentration["concentration_scores"].items():
            if "strike" in metric and score > 30:
                insights.append(
                    f"⚠ {metric.split('_')[0].upper()} concentrated in single strike "
                    f"({score:.1f}%) - consider diversifying"
                )

        # Gamma insights
        if abs(stats["total_gamma"]) > 0.1:
            direction = "long" if stats["total_gamma"] > 0 else "short"
            insights.append(
                f"ℹ High {direction} gamma ({abs(stats['total_gamma']):.4f}) - "
                "delta will change significantly with spot moves"
            )

        # Vega insights
        if abs(stats["total_vega"]) > 100:
            direction = (
                "benefits from" if stats["total_vega"] > 0 else "hurt by"
            )
            insights.append(
                f"ℹ Significant vega exposure ({abs(stats['total_vega']):.0f}) - "
                f"portfolio {direction} volatility increases"
            )

        return insights
