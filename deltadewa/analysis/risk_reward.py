"""Risk/reward analysis mixin for portfolio analysis."""

from typing import TYPE_CHECKING, Any

import numpy as np

from deltadewa.spot_utils import generate_spot_range

if TYPE_CHECKING:
    from deltadewa.analysis._protocols import _AnalyzerProtocol


class RiskRewardMixin:
    """Mixin for comprehensive risk/reward analysis.

    Provides methods for generating risk/reward metrics including
    max loss, max profit, breakeven points, and probability analysis.
    """

    if TYPE_CHECKING:
        _self: "_AnalyzerProtocol"

    def risk_reward_analysis(
        self: "_AnalyzerProtocol",
        spot_range: np.ndarray[Any, np.dtype[Any]] | None = None,
        num_simulations: int = 10**4,
    ) -> dict[str, Any]:
        """Generate comprehensive risk/reward analysis of the portfolio.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            num_simulations: Number of Monte Carlo simulations for probability

        Returns:
            dict containing all risk/reward metrics

        """
        net_debit = self.portfolio.calculate_net_debit()

        # Generate comprehensive spot range once if not provided
        if spot_range is None:
            spot_range = generate_spot_range(
                self.portfolio.spot_price,
                use_comprehensive_range=True,
            )

        # Options only analysis - pass the spot range
        max_loss_opts = self.portfolio.calculate_max_loss_options(spot_range)
        max_profit_opts = self.portfolio.calculate_max_profit_options(
            spot_range,
        )
        breakeven_opts = self.portfolio.calculate_breakeven_points(
            spot_range,
            include_underlying=False,
        )

        # Total portfolio analysis - pass the spot range
        max_loss_total = self.portfolio.calculate_max_loss_total(spot_range)
        max_profit_total = self.portfolio.calculate_max_profit_total(spot_range)
        breakeven_total = self.portfolio.calculate_breakeven_points(
            spot_range,
            include_underlying=True,
        )

        # Probability analysis
        prob_analysis = self.portfolio.run_monte_carlo_simulation(
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
            "prob_profit": prob_analysis["prob_profit"],
            "expected_pnl": prob_analysis["expected_pnl"],
        }
