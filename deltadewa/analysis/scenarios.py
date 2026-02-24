"""Scenario grid generation mixin for portfolio analysis."""

from typing import TYPE_CHECKING, List, Dict, Any
from datetime import datetime
import pandas as pd
import numpy as np

from deltadewa.analysis.volatility import (
    apply_proportional_volatility_shift,
    restore_volatilities,
)
from deltadewa.batch_pricer import BatchPricer

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


class ScenariosMixin:
    """
    Mixin for scenario grid generation.

    Provides methods for calculating portfolio metrics across 2D grids
    of spot prices and time, or spot prices and volatilities.
    """

    if TYPE_CHECKING:
        portfolio: "OptionPortfolio"

    def _create_batch_pricer(self) -> BatchPricer:
        """
        Creates a BatchPricer instance from the current portfolio state.

        This serves as a 'shadow' copy of the pricing engines that we can
        manipulate safely during calculations without affecting the main
        portfolio state.
        """
        return BatchPricer(
            positions=self.portfolio.positions,
            risk_free_rate=self.portfolio.risk_free_rate,
            dividend_yield=self.portfolio.dividend_yield,
            underlying_quantity=self.portfolio.underlying_quantity,
        )

    def _calculate_portfolio_value_at(
        self,
        spot: float,
        valuation_date: datetime,
        pricer: BatchPricer | None = None,
    ) -> float:
        """
        Calculate total portfolio value at given spot and date.

        Optimized to use an existing BatchPricer if provided, avoiding
        expensive QuantLib engine reconstruction.

        Args:
            spot: Spot price to use for valuation
            valuation_date: Date to use for valuation
            pricer: Optional existing BatchPricer instance for performance

        Returns:
            Total portfolio value (options + underlying)
        """
        # If a pricer is provided, use its optimized single-point lookup
        # This reuses the pre-built QuantLib engines
        if pricer:
            # We treat the single spot as a 1-item array
            values = pricer.portfolio_values_at(
                np.array([spot]), valuation_date
            )
            return values[0]

        # Fallback to creating a temporary pricer if none provided
        # This is still cleaner than the old loop as it delegates to the optimized class
        temp_pricer = self._create_batch_pricer()
        return temp_pricer.portfolio_values_at(
            np.array([spot]), valuation_date
        )[0]

    def _calculate_pnl_at_expiry_vectorized(
        self,
        spot_scenarios: np.ndarray,
        include_underlying: bool = True,
    ) -> np.ndarray:
        """
        Calculate P&L at expiry using vectorized NumPy operations.

        This method should only be used for at-expiry calculations where all
        positions have expired (days_to_maturity <= 0). At expiry, options have
        only intrinsic value and no time value, so volatility doesn't affect
        the results.

        This is much faster than iterating for large grids because:
        - Intrinsic value is element-wise max operation
        - All positions computed simultaneously across all spots
        - NumPy broadcasting handles grid expansion

        Delegates to portfolio implementation for consistency.

        Args:
            spot_scenarios: Array of spot prices to evaluate
            include_underlying: Whether to include underlying position P&L

        Returns:
            np.ndarray of P&L values for each spot scenario
        """
        return self.portfolio.vectorized_pnl_at_expiry(
            spot_scenarios, include_underlying=include_underlying
        )

    def scenario_grid(
        self,
        spot_scenarios: np.ndarray,
        time_points: List[datetime],
        metric: str = "pnl",
        baseline_spot: float | None = None,
        baseline_valuation_date: datetime | None = None,
    ) -> pd.DataFrame:
        """
        Calculate portfolio metrics across 2D grid of spot prices and time.

        Useful for heatmap generation showing how portfolio evolves across
        different price levels and time horizons.

        Args:
            spot_scenarios: Array of spot prices to test
            time_points: List of valuation dates to test
            metric: Metric to calculate ('pnl', 'value', 'delta', 'net_delta',
            'gamma', 'vega', 'theta')
            baseline_spot: Spot price for P&L baseline (default: current portfolio spot)
            baseline_valuation_date: Valuation date for P&L baseline (default:
            current portfolio date)

        Returns:
            DataFrame with columns: spot_price, valuation_date, metric_value
        """
        results: List[Dict[str, Any]] = []
        original_spot = self.portfolio.spot_price
        original_date = self.portfolio.valuation_date

        # Setup defaults and validate
        if baseline_spot is None:
            baseline_spot = original_spot
        if baseline_spot is None:
            raise ValueError(
                "Portfolio spot price is not set for baseline calculation."
            )

        if baseline_valuation_date is None:
            baseline_valuation_date = original_date
        if baseline_valuation_date is None:
            raise ValueError(
                "Portfolio valuation date is not set for baseline calculation."
            )

        # Create the BatchPricer ONCE.
        # This builds the QuantLib engines for all positions one time.
        pricer = self._create_batch_pricer()

        # Calculate baseline value efficiently using the pricer
        baseline_value = 0.0
        if metric == "pnl":
            baseline_value = self._calculate_portfolio_value_at(
                baseline_spot, baseline_valuation_date, pricer=pricer
            )

        # Main Grid Loop
        for time_point in time_points:
            days_forward = (time_point - original_date).days

            # STRATEGY 1: Efficient Value/PnL (No Greeks)
            if metric in ("pnl", "value"):
                # BatchPricer is optimized for this exact operation
                portfolio_values = pricer.portfolio_values_at(
                    spot_scenarios, time_point
                )

                # Vectorized construction of result rows
                for j, spot in enumerate(spot_scenarios):
                    val = portfolio_values[j]
                    if metric == "pnl":
                        val = val - baseline_value

                    results.append(
                        {
                            "spot_price": spot,
                            "valuation_date": time_point,
                            "days_forward": days_forward,
                            "metric": metric,
                            "value": val,
                        }
                    )

            # STRATEGY 2: Greeks (Requires state updates)
            # Currently BatchPricer primarily handles 'value'.
            # Ideally, BatchPricer would be extended to return Greeks arrays.
            # However, to avoid 'feature restriction' or major refactor of BatchPricer
            # right now, we will stick to the existing method for Greeks but
            # clean up the loop structure.
            else:
                for spot in spot_scenarios:
                    # We must update the actual portfolio for Greek calculations
                    # because the Greek methods (total_delta etc) live on the portfolio
                    self.portfolio.update_market_conditions(
                        spot_price=spot, valuation_date=time_point
                    )

                    if metric == "delta":
                        metric_value = self.portfolio.total_delta()
                    elif metric == "net_delta":
                        metric_value = self.portfolio.net_delta()
                    elif metric == "gamma":
                        metric_value = self.portfolio.total_gamma()
                    elif metric == "vega":
                        metric_value = self.portfolio.total_vega()
                    elif metric == "theta":
                        metric_value = self.portfolio.total_theta()
                    else:
                        metric_value = 0.0

                    results.append(
                        {
                            "spot_price": spot,
                            "valuation_date": time_point,
                            "days_forward": days_forward,
                            "metric": metric,
                            "value": metric_value,
                        }
                    )

        # ALWAYS Restore original state
        self.portfolio.update_market_conditions(
            spot_price=original_spot, valuation_date=original_date
        )

        return pd.DataFrame(results)

    def scenario_grid_spot_vol(
        self,
        spot_scenarios: np.ndarray,
        vol_scenarios: np.ndarray,
        metric: str = "pnl",
        baseline_value: float | None = None,
        proportional_vol_scaling: bool = True,
    ) -> pd.DataFrame:
        """
        Calculate portfolio metrics across 2D grid of spot prices and volatilities.

        For P&L at expiry (intrinsic value), uses vectorized calculation for
        maximum performance. For other metrics requiring repricing, uses
        iterative approach with proportional vol scaling.

        Args:
            spot_scenarios: Array of spot prices to test
            vol_scenarios: Array of volatilities to test
            metric: Metric to calculate ('pnl', 'value', 'delta', 'net_delta', 'gamma', 'vega', 'theta', 'rho')
            baseline_value: Portfolio value for P&L baseline (default: current value)
            proportional_vol_scaling: If True, scale position vols proportionally

        Returns:
            DataFrame with columns: spot_price, volatility, value
        """
        results: List[Dict[str, Any]] = []
        original_spot = self.portfolio.spot_price
        original_vol = self.portfolio.volatility
        original_date = self.portfolio.valuation_date

        if baseline_value is None:
            baseline_value = self.portfolio.total_value()

        # Optimization: Vectorized PnL at expiry check
        if metric == "pnl":
            # Check if all positions are at expiry (days_to_maturity == 0)
            # We check for exactly 0 to avoid issues with historical valuations
            all_at_expiry = all(
                (pos.option.maturity_date - original_date).days == 0
                for pos in self.portfolio.positions
            )
            if all_at_expiry:
                # Use vectorized calculation for maximum speed
                # Volatility doesn't affect intrinsic value at expiry
                pnl_values = self._calculate_pnl_at_expiry_vectorized(
                    spot_scenarios, include_underlying=True
                )
                # Expand to full grid
                for vol in vol_scenarios:
                    for j, spot in enumerate(spot_scenarios):
                        results.append(
                            {
                                "spot_price": spot,
                                "volatility": vol,
                                "value": pnl_values[j],
                            }
                        )
                return pd.DataFrame(results)

        # Store original position vols
        original_position_vols = {
            i: pos.option.volatility
            for i, pos in enumerate(self.portfolio.positions)
        }

        # Initialize BatchPricer for Non-Greek calculations if applicable
        # Note: Volatility changes require deep updates, so BatchPricer usage
        # here is tricky unless we rebuild it per vol-slice.
        # For now, we rely on the portfolio update mechanism which is robust.

        for vol in vol_scenarios:
            # Apply Volatility Shift
            if proportional_vol_scaling:
                apply_proportional_volatility_shift(
                    self.portfolio, vol, preserve_structure=True
                )
            else:
                for pos in self.portfolio.positions:
                    pos.option.volatility = vol

            # Inner Loop: Spot Prices
            for spot in spot_scenarios:
                self.portfolio.update_market_conditions(
                    spot_price=spot, valuation_date=original_date
                )

                if metric == "pnl":
                    current_value = self.portfolio.total_value()
                    # Manual underlying PnL calc
                    underlying_pnl = (
                        spot - original_spot
                    ) * self.portfolio.underlying_quantity
                    metric_value = (
                        current_value - baseline_value
                    ) + underlying_pnl
                elif metric == "value":
                    metric_value = self.portfolio.total_value()
                elif metric == "delta":
                    metric_value = self.portfolio.total_delta()
                elif metric == "net_delta":
                    metric_value = self.portfolio.net_delta()
                elif metric == "gamma":
                    metric_value = self.portfolio.total_gamma()
                elif metric == "vega":
                    metric_value = self.portfolio.total_vega()
                elif metric == "theta":
                    metric_value = self.portfolio.total_theta()
                elif metric == "rho":
                    metric_value = self.portfolio.total_rho()
                else:
                    raise ValueError(
                        f"Unsupported metric: {metric}. "
                        f"Supported: pnl, value, delta, net_delta, gamma, vega, theta, rho"
                    )

                results.append(
                    {
                        "spot_price": spot,
                        "volatility": vol,
                        "value": metric_value,
                    }
                )

            # Reset Volatility for next loop iteration
            restore_volatilities(self.portfolio, original_position_vols)

        # Restore everything
        self.portfolio.update_market_conditions(
            spot_price=original_spot,
            volatility=original_vol,
            valuation_date=original_date,
        )

        return pd.DataFrame(results)
