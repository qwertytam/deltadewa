"""Scenario grid generation mixin for portfolio analysis."""

from typing import TYPE_CHECKING, List, Optional
from datetime import datetime
import pandas as pd
import numpy as np
from deltadewa.american_option import AmericanOption
from deltadewa.analysis.volatility import (
    apply_proportional_volatility_shift,
    restore_volatilities,
)


if TYPE_CHECKING:
    from deltadewa.portfolio import OptionPortfolio


class ScenariosMixin:
    """
    Mixin for scenario grid generation.

    Provides methods for calculating portfolio metrics across 2D grids
    of spot prices and time, or spot prices and volatilities.
    """

    if TYPE_CHECKING:
        portfolio: "OptionPortfolio"

    def _calculate_portfolio_value_at(
        self,
        spot: float,
        valuation_date: datetime,
    ) -> float:
        """
        Calculate total portfolio value at given spot and date.

        Args:
            spot: Spot price to use for valuation
            valuation_date: Date to use for valuation

        Returns:
            Total portfolio value (options + underlying)
        """
        total_value = 0.0

        for position in self.portfolio.positions:
            days_to_maturity = (
                position.option.maturity_date - valuation_date
            ).days

            if days_to_maturity <= 0:
                # Option expired - use intrinsic value
                if position.option.option_type == "call":
                    intrinsic = max(0, spot - position.option.strike_price)
                else:
                    intrinsic = max(0, position.option.strike_price - spot)
                total_value += (
                    intrinsic * position.quantity * position.contract_size
                )
            else:
                # Option still alive - price it
                opt = AmericanOption(
                    spot_price=spot,
                    strike_price=position.option.strike_price,
                    maturity_date=position.option.maturity_date,
                    volatility=position.option.volatility,  # Use position volatility
                    risk_free_rate=self.portfolio.risk_free_rate,
                    dividend_yield=self.portfolio.dividend_yield,
                    option_type=position.option.option_type,
                    valuation_date=valuation_date,
                )
                total_value += (
                    opt.price() * position.quantity * position.contract_size
                )

        # Add underlying position value
        total_value += self.portfolio.underlying_quantity * spot

        return total_value

    def _calculate_pnl_at_expiry_vectorized(
        self,
        spot_scenarios: np.ndarray,
        include_underlying: bool = True,
    ) -> np.ndarray:
        """
        Calculate P&L at expiry using vectorized NumPy operations.

        This method delegates to the portfolio's canonical vectorized implementation
        for consistency and maintainability.

        This method should only be used for at-expiry calculations where all
        positions have expired (days_to_maturity <= 0). At expiry, options have
        only intrinsic value and no time value, so volatility doesn't affect
        the results.

        This is much faster than iterating for large grids because:
        - Intrinsic value is element-wise max operation
        - All positions computed simultaneously across all spots
        - NumPy broadcasting handles grid expansion

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
        baseline_spot: Optional[float] = None,
        baseline_valuation_date: Optional[datetime] = None,
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

        results = []
        original_spot = self.portfolio.spot_price
        original_date = self.portfolio.valuation_date

        # For P&L calculation, use the baseline values if provided
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

        # Calculate baseline value at baseline date/spot for P&L calculations
        baseline_value = self._calculate_portfolio_value_at(
            baseline_spot, baseline_valuation_date
        )

        # Use BatchPricer for efficient valuation of 'pnl' and 'value' metrics
        # Greeks still need portfolio state updates, so they use the old path
        if metric in ("pnl", "value"):
            from deltadewa.batch_pricer import (
                BatchPricer,
            )  # Import locally to avoid circular dependency

            pricer = BatchPricer(
                positions=self.portfolio.positions,
                risk_free_rate=self.portfolio.risk_free_rate,
                dividend_yield=self.portfolio.dividend_yield,
                underlying_quantity=self.portfolio.underlying_quantity,
            )

            for time_point in time_points:
                # Get all portfolio values at this time_point efficiently
                portfolio_values = pricer.portfolio_values_at(
                    spot_scenarios, time_point
                )

                for j, spot in enumerate(spot_scenarios):
                    if metric == "pnl":
                        metric_value = portfolio_values[j] - baseline_value
                    else:  # metric == "value"
                        metric_value = portfolio_values[j]

                    results.append(
                        {
                            "spot_price": spot,
                            "valuation_date": time_point,
                            "days_forward": (time_point - original_date).days,
                            "metric": metric,
                            "value": metric_value,
                        }
                    )

        else:
            # For Greeks, we need to update portfolio state, so use old path
            for time_point in time_points:
                for spot in spot_scenarios:
                    # For Greeks, update portfolio and calculate
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
                            "days_forward": (time_point - original_date).days,
                            "metric": metric,
                            "value": metric_value,
                        }
                    )

        # Restore original state
        self.portfolio.update_market_conditions(
            spot_price=original_spot, valuation_date=original_date
        )

        return pd.DataFrame(results)

    def scenario_grid_spot_vol(
        self,
        spot_scenarios: np.ndarray,
        vol_scenarios: np.ndarray,
        metric: str = "pnl",
        baseline_value: Optional[float] = None,
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
            metric: Metric to calculate ('pnl', 'value', 'delta', 'gamma', 'vega', 'theta')
            baseline_value: Portfolio value for P&L baseline (default: current value)
            proportional_vol_scaling: If True, scale position vols proportionally

        Returns:
            DataFrame with columns: spot_price, volatility, value
        """

        results = []
        original_spot = self.portfolio.spot_price
        original_vol = self.portfolio.volatility
        original_date = self.portfolio.valuation_date

        # Calculate baseline value if not provided
        if baseline_value is None:
            baseline_value = self.portfolio.total_value()

        # Store original position volatilities for restoration
        original_position_vols = {
            i: pos.option.volatility
            for i, pos in enumerate(self.portfolio.positions)
        }

        # For P&L metric, check if we can use vectorized calculation
        # (only applicable at expiry where volatility doesn't matter)
        if metric == "pnl":
            # Check if all positions are at expiry (days_to_maturity == 0)
            # We check for exactly 0 to avoid issues with historical valuations
            all_at_expiry = all(
                (pos.option.maturity_date - original_date).days == 0
                for pos in self.portfolio.positions
            )

            if all_at_expiry:
                # Use vectorized calculation for maximum speed
                # Create meshgrid of spot and vol scenarios
                # spot_grid, vol_grid = np.meshgrid(spot_scenarios, vol_scenarios)

                # Calculate PnL using vectorized method (vol doesn't affect intrinsic value)
                pnl_values = self._calculate_pnl_at_expiry_vectorized(
                    spot_scenarios, include_underlying=True
                )

                # Expand to full grid
                for i, vol in enumerate(vol_scenarios):
                    for j, spot in enumerate(spot_scenarios):
                        results.append(
                            {
                                "spot_price": spot,
                                "volatility": vol,
                                "value": pnl_values[j],
                            }
                        )

                return pd.DataFrame(results)

        # For other metrics or non-expiry PnL, iterate with vol scaling
        for vol in vol_scenarios:
            # Apply proportional volatility shift
            if proportional_vol_scaling:
                apply_proportional_volatility_shift(
                    self.portfolio, vol, preserve_structure=True
                )
            else:
                # Set all positions to same volatility
                for pos in self.portfolio.positions:
                    pos.option.volatility = vol

            for spot in spot_scenarios:
                # Update market conditions
                self.portfolio.update_market_conditions(
                    spot_price=spot, valuation_date=original_date
                )

                # Calculate metric
                if metric == "pnl":
                    current_value = self.portfolio.total_value()
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
                elif metric == "gamma":
                    metric_value = self.portfolio.total_gamma()
                elif metric == "vega":
                    metric_value = self.portfolio.total_vega()
                elif metric == "theta":
                    metric_value = self.portfolio.total_theta()
                else:
                    raise ValueError(
                        f"Unsupported metric: {metric}. "
                        f"Supported: pnl, value, delta, gamma, vega, theta"
                    )

                results.append(
                    {
                        "spot_price": spot,
                        "volatility": vol,
                        "value": metric_value,
                    }
                )

            # Restore volatilities after each volatility level
            restore_volatilities(self.portfolio, original_position_vols)

        # Restore original portfolio state
        self.portfolio.update_market_conditions(
            spot_price=original_spot,
            volatility=original_vol,
            valuation_date=original_date,
        )

        return pd.DataFrame(results)
