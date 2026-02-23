"""Monte Carlo simulation mixin for option portfolio."""

from typing import TYPE_CHECKING, Optional, List
from datetime import datetime
from collections import Counter
import numpy as np
from deltadewa import constants as const

if TYPE_CHECKING:
    from deltadewa.portfolio.position import OptionPosition


class MonteCarloMixin:
    """Mixin providing Monte Carlo simulation for option portfolio."""

    if TYPE_CHECKING:
        positions: List["OptionPosition"]
        valuation_date: datetime
        risk_free_rate: float
        dividend_yield: float
        volatility: float
        spot_price: float

        # pylint: disable=missing-function-docstring, unused-argument
        def vectorized_pnl_at_expiry(
            self, spots: np.ndarray, include_underlying: bool = False
        ) -> np.ndarray: ...

        # pylint: disable=missing-function-docstring, unused-argument
        def calculate_breakeven_points(
            self,
            spot_range: Optional[np.ndarray] = None,
            include_underlying: bool = False,
            spot_min_pct: float = 0.0,
            spot_max_pct: float = 200.0,
        ) -> List[float]: ...

        # pylint: disable=missing-function-docstring, unused-argument
        def calculate_pnl_at_expiry(
            self, spot: float, include_underlying: bool = False
        ) -> float: ...

    def calculate_probability_of_profit(
        self,
        method: str = "monte_carlo",
        num_simulations: int = 10000,
        include_underlying: bool = False,
        days_to_expiry: Optional[int] = None,
    ) -> dict:
        """
        Calculate probability that portfolio will be profitable at expiration.

        Uses vectorized Monte Carlo simulation with geometric Brownian motion
        to generate spot price scenarios and compute P&L distribution.

        Args:
            method: Calculation method ('monte_carlo' only - 'normal' is deprecated)
            num_simulations: Number of Monte Carlo simulations
            include_underlying: Whether to include underlying position
            days_to_expiry: Days to expiration (uses nearest maturity if None)

        Returns:
            Dict with rich risk metrics:
                - breakeven_points: List of breakeven spot prices
                - simulated_pnls: Raw P&L array for visualization
                - num_simulations: Actual count of valid simulations
                - days_to_expiry: Time horizon used
                - expected_pnl: Mean P&L
                - median_pnl: Median P&L
                - std_pnl: Standard deviation of P&L
                - min_pnl: Minimum P&L in simulations
                - max_pnl: Maximum P&L in simulations
                - prob_profit: Probability of profit
                - prob_loss: Probability of loss
                - var_95: Value at Risk (5th percentile)
                - var_99: Value at Risk (1st percentile)
                - cvar_95: Conditional VaR (expected shortfall at 95%)
                - cvar_99: Conditional VaR (expected shortfall at 99%)
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

        if method != "monte_carlo":
            # Only monte_carlo method is supported
            raise NotImplementedError(
                f"Method '{method}' is not implemented. Only 'monte_carlo' is supported."
            )

        # Vectorized Monte Carlo simulation
        # Generate all random numbers at once (50-100x faster than loop)
        z = np.random.standard_normal(num_simulations)
        drift = (
            self.risk_free_rate - self.dividend_yield - 0.5 * self.volatility**2
        ) * time_to_expiry
        diffusion = self.volatility * np.sqrt(time_to_expiry) * z
        final_spots = self.spot_price * np.exp(drift + diffusion)

        # Vectorized P&L calculation for all spots at once
        # pylint: disable=assignment-from-no-return
        simulated_pnls = self.vectorized_pnl_at_expiry(
            final_spots, include_underlying=include_underlying
        )

        # Clean data (remove any non-finite values)
        # Non-finite values could theoretically occur from extreme parameter combinations
        # (e.g., very high volatility causing numerical overflow in exp()), though
        # this is rare in practice with typical option parameters
        pnls_clean = simulated_pnls[np.isfinite(simulated_pnls)]
        num_valid = len(pnls_clean)

        # Basic statistics
        expected_pnl = float(np.mean(pnls_clean))
        median_pnl = float(np.median(pnls_clean))
        std_pnl = float(np.std(pnls_clean))
        min_pnl = float(np.min(pnls_clean))
        max_pnl = float(np.max(pnls_clean))

        # Profit/Loss probabilities
        profitable_count = np.sum(pnls_clean > 0)
        prob_profit = float(profitable_count / num_valid)
        prob_loss = float(1.0 - prob_profit)

        # Value at Risk (VaR)
        var_95 = float(np.percentile(pnls_clean, 5))  # 5th percentile
        var_99 = float(np.percentile(pnls_clean, 1))  # 1st percentile

        # Conditional VaR (CVaR / Expected Shortfall)
        cvar_95 = float(np.mean(pnls_clean[pnls_clean <= var_95]))
        cvar_99 = float(np.mean(pnls_clean[pnls_clean <= var_99]))

        # Calculate breakeven points
        # pylint: disable=assignment-from-no-return
        breakeven_points = self.calculate_breakeven_points(
            include_underlying=include_underlying
        )

        return {
            "breakeven_points": breakeven_points,
            "simulated_pnls": pnls_clean,
            "num_simulations": num_valid,
            "days_to_expiry": days_to_expiry,
            "expected_pnl": expected_pnl,
            "median_pnl": median_pnl,
            "std_pnl": std_pnl,
            "min_pnl": min_pnl,
            "max_pnl": max_pnl,
            "prob_profit": prob_profit,
            "prob_loss": prob_loss,
            "var_95": var_95,
            "var_99": var_99,
            "cvar_95": cvar_95,
            "cvar_99": cvar_99,
        }

    def run_monte_carlo_simulation(
        self,
        num_simulations: int = 10**5,
        include_underlying: bool = True,
        random_seed: Optional[int] = 42,  # Set to None for true randomness
    ):
        """
        Run Monte Carlo simulation and store results on portfolio object.

        Args:
            num_simulations: Number of simulation paths
            include_underlying: Include underlying position in P&L
            random_seed: Random seed for reproducibility (None for true randomness)

        Returns:
            dict: Monte Carlo results dictionary
        """
        # Get time to expiry from nearest maturity
        min_time_horizon = 1  # Minimum days to expiry
        if len(self.positions) > 0:
            min_maturity = min(
                pos.option.maturity_date for pos in self.positions
            )
            days_to_expiry = max(
                min_time_horizon, (min_maturity - self.valuation_date).days
            )
        else:
            days_to_expiry = const.CALENDAR_DAYS_PER_MONTH  # Default

        time_to_expiry = days_to_expiry / const.DAYS_PER_YEAR

        # Get market parameters
        spot_price = self.spot_price
        volatility = self.volatility
        risk_free_rate = self.risk_free_rate
        dividend_yield = self.dividend_yield

        if random_seed is not None:
            np.random.seed(random_seed)

        # Vectorized simulation for performance
        z = np.random.standard_normal(num_simulations)
        drift = (
            risk_free_rate - dividend_yield - 0.5 * volatility**2
        ) * time_to_expiry
        diffusion = volatility * np.sqrt(time_to_expiry) * z
        final_spots = spot_price * np.exp(drift + diffusion)

        # Calculate P&L for each simulated spot price
        simulated_pnls = np.array(
            [
                self.calculate_pnl_at_expiry(
                    spot, include_underlying=include_underlying
                )
                for spot in final_spots
            ]
        )

        # Clean data
        pnls_clean = simulated_pnls[np.isfinite(simulated_pnls)]

        # Basic statistics
        expected_pnl = np.mean(pnls_clean)
        median_pnl = np.median(pnls_clean)
        std_pnl = np.std(pnls_clean)
        min_pnl = np.min(pnls_clean)
        max_pnl = np.max(pnls_clean)

        # Profit/Loss breakdown
        profits = pnls_clean[pnls_clean >= 0]
        losses = pnls_clean[pnls_clean < 0]
        prob_profit = len(profits) / len(pnls_clean)
        prob_loss = len(losses) / len(pnls_clean)

        # VaR and CVaR
        var_95 = np.percentile(pnls_clean, 5)  # 5th percentile = 95% VaR
        var_99 = np.percentile(pnls_clean, 1)  # 1st percentile = 99% VaR
        cvar_95 = np.mean(pnls_clean[pnls_clean <= var_95])
        cvar_99 = np.mean(pnls_clean[pnls_clean <= var_99])

        # Loss analysis (conditional on losses occurring)
        if len(losses) > 0:
            avg_loss = np.mean(losses)
            max_loss = np.min(losses)  # Most negative = worst loss
            median_loss = np.median(losses)
        else:
            avg_loss = max_loss = median_loss = 0.0

        # Distribution concentration check (for short option strategies)
        unique_rounded = np.unique(np.round(pnls_clean, 2))
        is_concentrated = len(unique_rounded) < (len(pnls_clean) / 100)

        most_common_pnl = None
        concentration_pct = 0.0
        if is_concentrated:
            most_common_pnl = Counter(np.round(pnls_clean, 2)).most_common(1)[0]
            concentration_pct = most_common_pnl[1] / len(pnls_clean) * 100

        # Theoretical maximum loss (for short options)
        theoretical_max_loss = None
        if hasattr(self, "positions") and len(self.positions) > 0:
            max_loss_theoretical = 0.0
            for pos in self.positions:
                if pos.quantity < 0:  # Short position
                    if pos.option.option_type.lower() == "put":
                        max_loss_this = (
                            pos.option.strike_price
                            * abs(pos.quantity)
                            * pos.contract_size
                        )
                    else:  # Short call = unlimited
                        max_loss_this = float("inf")

                    if max_loss_this == float("inf"):
                        max_loss_theoretical = float("inf")
                        break
                    max_loss_theoretical += max_loss_this

            if (
                max_loss_theoretical != float("inf")
                and max_loss_theoretical > 0
            ):
                theoretical_max_loss = -max_loss_theoretical

        # Build results dictionary
        mc_results = {
            # Raw data
            "simulated_pnls": pnls_clean,
            "num_simulations": len(pnls_clean),
            "days_to_expiry": days_to_expiry,
            # Basic statistics
            "expected_pnl": expected_pnl,
            "median_pnl": median_pnl,
            "std_pnl": std_pnl,
            "min_pnl": min_pnl,
            "max_pnl": max_pnl,
            # Profit/Loss breakdown
            "prob_profit": prob_profit,
            "prob_loss": prob_loss,
            "avg_loss": avg_loss,
            "max_loss": max_loss,
            "median_loss": median_loss,
            # Risk metrics
            "var_95": var_95,
            "var_99": var_99,
            "cvar_95": cvar_95,
            "cvar_99": cvar_99,
            # Distribution characteristics
            "is_concentrated": is_concentrated,
            "most_common_pnl": most_common_pnl,
            "concentration_pct": concentration_pct,
            "unique_values": len(unique_rounded),
            # Theoretical bounds
            "theoretical_max_loss": theoretical_max_loss,
        }

        # Store on portfolio using public property
        self.monte_carlo_results = mc_results

        return mc_results
