"""Risk/reward analysis mixin for portfolio analysis."""

from typing import TYPE_CHECKING, Optional
import numpy as np
from deltadewa.analysis.functions import generate_spot_range

if TYPE_CHECKING:
    from deltadewa.portfolio import OptionPortfolio


class RiskRewardMixin:
    """
    Mixin for comprehensive risk/reward analysis.

    Provides methods for generating risk/reward metrics including
    max loss, max profit, breakeven points, and probability analysis.
    """

    if TYPE_CHECKING:
        portfolio: OptionPortfolio

    def risk_reward_analysis(
        self,
        spot_range: Optional[np.ndarray] = None,
        num_simulations: int = 10000,
    ) -> dict:
        """
        Generate comprehensive risk/reward analysis of the portfolio.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            num_simulations: Number of Monte Carlo simulations for probability

        Returns:
            Dict containing all risk/reward metrics
        """
        net_debit = self.portfolio.calculate_net_debit()

        # Generate comprehensive spot range once if not provided
        if spot_range is None:
            spot_range = generate_spot_range(
                self.portfolio.spot_price, use_comprehensive_range=True
            )

        # Options only analysis - pass the spot range
        max_loss_opts = self.portfolio.calculate_max_loss_options(spot_range)
        max_profit_opts = self.portfolio.calculate_max_profit_options(
            spot_range
        )
        breakeven_opts = self.portfolio.calculate_breakeven_points(
            spot_range, include_underlying=False
        )

        # Total portfolio analysis - pass the spot range
        max_loss_total = self.portfolio.calculate_max_loss_total(spot_range)
        max_profit_total = self.portfolio.calculate_max_profit_total(spot_range)
        breakeven_total = self.portfolio.calculate_breakeven_points(
            spot_range, include_underlying=True
        )

        # Probability analysis
        prob_analysis = self.portfolio.calculate_probability_of_profit(
            method="monte_carlo",
            num_simulations=num_simulations,
            include_underlying=True,
        )

        return {
            "net_debit": net_debit,
            "max_loss_options": max_loss_opts,
            "max_profit_options": max_profit_opts,
            "breakeven_options": breakeven_opts,
            "max_loss_total": max_loss_total,
            "max_profit_total": max_profit_total,
            "breakeven_total": breakeven_total,
            "probability_of_profit": prob_analysis["probability"],
            "expected_value": prob_analysis["expected_value"],
        }

    def format_risk_reward_summary(
        self, spot_range: Optional[np.ndarray] = None
    ) -> str:
        """
        Generate formatted risk/reward summary text.

        Args:
            spot_range: Array of spot prices to analyze (optional)

        Returns:
            Formatted string with risk/reward analysis
        """
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
                f"  Net Debit: ${net_debit:,.2f} (capital required to implement)"
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
                f"    └─ Occurs at spot price: ${max_loss_opts['spot_at_max_loss']:.2f}"
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
                f"    └─ Occurs at spot price: ${max_profit_opts['spot_at_max_profit']:.2f}"
            )

        if analysis["breakeven_options"]:
            breakevens_str = ", ".join(
                [f"${be:.2f}" for be in analysis["breakeven_options"]]
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
                    "  Max Loss: UNLIMITED (short underlying position)"
                )
            else:
                portfolio_value = self.portfolio.total_portfolio_value()
                loss_line = f"  Max Loss: ${-max_loss_total['max_loss']:,.2f}"
                if portfolio_value > 0:
                    loss_pct = (
                        -max_loss_total["max_loss"] / portfolio_value
                    ) * 100
                    loss_line += f" ({loss_pct:.1f}% of portfolio value)"
                lines.append(loss_line)
                lines.append(
                    f"    └─ Occurs at spot price: ${max_loss_total['spot_at_max_loss']:.2f}"
                )

            if max_profit_total["is_unlimited"]:
                if self.portfolio.underlying_quantity > 0:
                    lines.append(
                        "  Max Profit: UNLIMITED (long underlying position)"
                    )
                else:
                    lines.append("  Max Profit: UNLIMITED")
                lines.append("    └─ Profit increases with spot price")
            else:
                profit_line = (
                    f"  Max Profit: ${max_profit_total['max_profit']:,.2f}"
                )
                if portfolio_value > 0:
                    profit_pct = (
                        max_profit_total["max_profit"] / portfolio_value
                    ) * 100
                    profit_line += f" ({profit_pct:.1f}% of portfolio value)"
                lines.append(profit_line)
                lines.append(
                    f"    └─ Occurs at spot price: ${max_profit_total['spot_at_max_profit']:.2f}"
                )

            if analysis["breakeven_total"]:
                breakevens_str = ", ".join(
                    [f"${be:.2f}" for be in analysis["breakeven_total"]]
                )
                lines.append(f"  Breakeven Points: {breakevens_str}")
            else:
                lines.append("  Breakeven Points: None identified")
            lines.append("")

        # Probability Analysis
        lines.append("PROBABILITY ANALYSIS:")
        prob = analysis["probability_of_profit"]
        lines.append(f"  Chance of Profit: {prob*100:.1f}%")
        lines.append(
            f"  Expected Value: ${analysis['expected_value']:,.2f} (probabilistic weighted average)"
        )
        lines.append("")

        # Risk/Reward Ratio
        if (
            not max_loss_opts["is_unlimited"]
            and not max_profit_opts["is_unlimited"]
        ):
            if (
                max_profit_opts["max_profit"] > 0
                and max_loss_opts["max_loss"] < 0
            ):
                # Standard risk/reward ratio: profit potential to loss potential
                rr_ratio = (
                    max_profit_opts["max_profit"] / -max_loss_opts["max_loss"]
                )
                lines.append(
                    f"RISK/REWARD RATIO: {rr_ratio:.2f}:1 (max profit to max loss)"
                )
        lines.append("=" * 80)

        return "\n".join(lines)

    def print_risk_reward_summary(
        self, spot_range: Optional[np.ndarray] = None
    ):
        """
        Print a formatted risk/reward summary of the portfolio.

        Args:
            spot_range: Array of spot prices to analyze (optional)
        """
        summary = self.format_risk_reward_summary(spot_range)
        print(summary)
