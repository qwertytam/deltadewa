"""Monte Carlo simulation mixin for option portfolio."""

from typing import TYPE_CHECKING, Optional
import numpy as np
from deltadewa import constants as const

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolioBase


class MonteCarloMixin:
    """Mixin providing Monte Carlo simulation for option portfolio."""

    def calculate_probability_of_profit(
        self: "OptionPortfolioBase",
        method: str = "monte_carlo",
        num_simulations: int = 10000,
        include_underlying: bool = False,
        days_to_expiry: Optional[int] = None,
    ) -> dict:
        """
        Calculate probability that portfolio will be profitable at expiration.

        Args:
            method: Calculation method ('monte_carlo' or 'normal')
            num_simulations: Number of Monte Carlo simulations
            include_underlying: Whether to include underlying position
            days_to_expiry: Days to expiration (uses nearest maturity if None)

        Returns:
            Dict with 'probability', 'expected_value', and 'breakeven_points'
        """
        # Determine time to expiration
        if days_to_expiry is None:
            if not self.positions:
                days_to_expiry = 30
            else:
                # Use the nearest maturity
                min_maturity = min(
                    pos.option.maturity_date for pos in self.positions
                )
                days_to_expiry = max(
                    1, (min_maturity - self.valuation_date).days
                )

        time_to_expiry = days_to_expiry / const.DAYS_PER_YEAR

        if method == "monte_carlo":
            # Monte Carlo simulation
            profitable_count = 0
            total_pnl = 0.0

            for _ in range(num_simulations):
                # Simulate final spot price using geometric Brownian motion
                z = np.random.standard_normal()
                drift = (
                    self.risk_free_rate
                    - self.dividend_yield
                    - 0.5 * self.volatility**2
                ) * time_to_expiry
                diffusion = self.volatility * np.sqrt(time_to_expiry) * z
                final_spot = self.spot_price * np.exp(drift + diffusion)

                # Calculate P&L at this simulated spot
                pnl = self.calculate_pnl_at_expiry(
                    final_spot, include_underlying=include_underlying
                )
                total_pnl += pnl

                if pnl > 0:
                    profitable_count += 1

            probability = profitable_count / num_simulations
            expected_value = total_pnl / num_simulations

        else:
            # Normal distribution method not fully implemented
            # Fall back to Monte Carlo
            probability = 0.0
            expected_value = 0.0

            for _ in range(num_simulations):
                z = np.random.standard_normal()
                drift = (
                    self.risk_free_rate
                    - self.dividend_yield
                    - 0.5 * self.volatility**2
                ) * time_to_expiry
                diffusion = self.volatility * np.sqrt(time_to_expiry) * z
                final_spot = self.spot_price * np.exp(drift + diffusion)

                pnl = self.calculate_pnl_at_expiry(
                    final_spot, include_underlying=include_underlying
                )
                expected_value += pnl

                if pnl > 0:
                    probability += 1

            probability = probability / num_simulations
            expected_value = expected_value / num_simulations

        # Calculate breakeven points
        breakeven_points = self.calculate_breakeven_points(
            include_underlying=include_underlying
        )

        return {
            "probability": probability,
            "expected_value": expected_value,
            "breakeven_points": breakeven_points,
        }
