"""Monte Carlo simulation mixin for option portfolio."""

from collections import Counter
from typing import TYPE_CHECKING, Any

import numpy as np

from deltadewa import constants as const

if TYPE_CHECKING:
    from deltadewa.portfolio._protocols import _PortfolioProtocol


class MonteCarloMixin:
    """Mixin providing Monte Carlo simulation for option portfolio."""

    if TYPE_CHECKING:
        _self: "_PortfolioProtocol"

    # Declare attribute for static type checkers. The concrete
    # `OptionPortfolioBase` provides a property for this name at runtime.
    monte_carlo_results: dict[str, float | int | np.ndarray] | None

    def _calculate_theoretical_max_loss(
        self: "_PortfolioProtocol",
    ) -> float | None:
        """Calculate theoretical max loss based on position structure."""
        if not hasattr(self, "positions") or not self.positions:
            return None

        max_loss_theoretical = 0.0
        for pos in self.positions:
            if pos.quantity < 0:  # Short position
                if pos.option.option_type == const.OptionType.PUT:
                    # Short put max loss = strike * quantity
                    loss = (
                        pos.option.strike_price
                        * abs(pos.quantity)
                        * pos.contract_size
                    )
                    max_loss_theoretical += loss
                else:
                    # Short call = unlimited loss
                    return float("inf")

        if max_loss_theoretical > 0:
            return -max_loss_theoretical
        return None

    def _analyze_concentration(
        self: "_PortfolioProtocol",
        pnls: np.ndarray,
    ) -> tuple[bool, float, tuple[float, int] | None]:
        """Analyze P&L distribution concentration."""
        unique_rounded = np.unique(np.round(pnls, 2))
        is_concentrated = len(unique_rounded) < (len(pnls) / 100)

        concentration_pct = 0.0
        most_common_pnl = None

        if is_concentrated:
            most_common = Counter(np.round(pnls, 2)).most_common(1)
            if most_common:
                most_common_pnl = most_common[0]
                concentration_pct = most_common_pnl[1] / len(pnls) * 100

        return is_concentrated, concentration_pct, most_common_pnl

    def _empty_monte_carlo_results(
        self: "_PortfolioProtocol",
        days_to_expiry: int,
    ) -> dict[str, Any]:
        """Return safe empty results structure."""
        return {
            "simulated_pnls": np.array([]),
            "num_simulations": 0,
            "days_to_expiry": days_to_expiry,
            "expected_pnl": 0.0,
            "median_pnl": 0.0,
            "std_pnl": 0.0,
            "min_pnl": 0.0,
            "max_pnl": 0.0,
            "prob_profit": 0.0,
            "prob_loss": 0.0,
            "avg_loss": 0.0,
            "max_loss": 0.0,
            "median_loss": 0.0,
            "var_95": 0.0,
            "var_99": 0.0,
            "cvar_95": 0.0,
            "cvar_99": 0.0,
            "breakeven_points": [],
            "theoretical_max_loss": None,
            "is_concentrated": False,
            "concentration_pct": 0.0,
            "most_common_pnl": None,
        }

    def run_monte_carlo_simulation(
        self: "_PortfolioProtocol",
        num_simulations: int = 10**5,
        include_underlying: bool = True,
        random_seed: int | None = 42,  # Set to None for true randomness
        days_to_expiry: int | None = None,
    ) -> dict[str, Any]:
        """Run Monte Carlo simulation and store results on portfolio object.

        This is the core simulation engine. It vectorizes the Geometric
        Brownian Motion path generation and P&L calculation for maximum
        performance.

        Args:
            num_simulations: Number of simulation paths
            include_underlying: Include underlying position in P&L
            random_seed: Random seed for reproducibility (None for true
            randomness)
            days_to_expiry: Days to expiration (uses nearest maturity if None)

        Returns:
            dict: Monte Carlo results dictionary

        """
        # 1. Determine time horizon (days to expiry)
        min_time_horizon = 1
        if days_to_expiry is None:
            if len(self.positions) > 0:
                min_maturity = min(
                    pos.option.maturity_date for pos in self.positions
                )
                days_to_expiry = max(
                    min_time_horizon,
                    (min_maturity - self.valuation_date).days,
                )
            else:
                days_to_expiry = const.CALENDAR_DAYS_PER_MONTH  # Default

        year_frac_to_expiry = days_to_expiry / const.DAYS_PER_YEAR

        # 2. Setup market parameters
        spot_price = self.spot_price
        volatility = self.volatility
        risk_free_rate = self.risk_free_rate
        dividend_yield = self.dividend_yield

        if random_seed is not None:
            np.random.seed(random_seed)

        # 3. Vectorized simulation  (Geometric Brownian Motion)
        # Generate all random numbers at once (50-100x faster than loop)
        z = np.random.standard_normal(num_simulations)
        drift = (
            risk_free_rate - dividend_yield - 0.5 * volatility**2
        ) * year_frac_to_expiry
        diffusion = volatility * np.sqrt(year_frac_to_expiry) * z
        final_spots = spot_price * np.exp(drift + diffusion)

        # 4. Vectorized P&L Calculation
        # This calls the portfolio's vectorized P&L method which handles all
        # positions
        simulated_pnls = np.array(
            [
                self.calculate_pnl_at_expiry(
                    spot,
                    include_underlying=include_underlying,
                )
                for spot in final_spots
            ],
        )

        # 5. Clean data
        pnls_clean = simulated_pnls[np.isfinite(simulated_pnls)]
        num_valid = len(pnls_clean)

        if num_valid == 0:
            return self._empty_monte_carlo_results(days_to_expiry)

        # 6. Metric calculations
        expected_pnl = np.mean(pnls_clean)
        median_pnl = np.median(pnls_clean)
        std_pnl = np.std(pnls_clean)
        min_pnl = np.min(pnls_clean)
        max_pnl = np.max(pnls_clean)

        # Wing/loss ratios
        profits = pnls_clean[pnls_clean >= 0]
        losses = pnls_clean[pnls_clean < 0]
        prob_profit = len(profits) / num_valid
        prob_loss = len(losses) / num_valid

        # VaR and CVaR risk metrics
        var_95 = np.percentile(pnls_clean, 5)  # 5th percentile = 95% VaR
        var_99 = np.percentile(pnls_clean, 1)  # 1st percentile = 99% VaR
        cvar_95 = np.mean(pnls_clean[pnls_clean <= var_95])
        cvar_99 = np.mean(pnls_clean[pnls_clean <= var_99])

        # Conditional loss analysis
        if len(losses) > 0:
            avg_loss = np.mean(losses)
            max_loss = np.min(losses)  # Most negative = worst loss
            median_loss = np.median(losses)
        else:
            avg_loss = max_loss = median_loss = 0.0

        # 7. Theoretical Maximum Loss (for short options)
        theoretical_max_loss = self._calculate_theoretical_max_loss()

        # 8. Distribution analysis (for short option strategies)
        unique_rounded = np.unique(np.round(pnls_clean, 2))
        is_concentrated, concentration_pct, most_common_pnl = (
            self._analyze_concentration(pnls_clean)
        )

        # 9. Breakeven Analysis (Delegate to existing method)
        breakeven_points = self.calculate_breakeven_points(
            include_underlying=include_underlying,
        )

        results = {
            # Raw data
            "simulated_pnls": pnls_clean,
            "num_simulations": num_valid,
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
            "breakeven_points": breakeven_points,
            "is_concentrated": is_concentrated,
            "most_common_pnl": most_common_pnl,
            "concentration_pct": concentration_pct,
            "unique_values": len(unique_rounded),
            # Theoretical bounds
            "theoretical_max_loss": theoretical_max_loss,
        }

        # Cache results on the object
        self.monte_carlo_results = results

        return results
