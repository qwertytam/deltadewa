"""Scenario analysis mixin for option portfolios."""

import pandas as pd
import numpy as np
from typing import Optional
from deltadewa.utils import (
    calculate_portfolio_avg_volatility,
    apply_proportional_volatility_shift,
    restore_volatilities,
)


class ScenarioMixin:
    """Mixin providing scenario analysis for OptionPortfolio."""

    def scenario_analysis(
        self,
        spot_range: np.ndarray,
        vol_range: Optional[np.ndarray] = None,
        proportional_vol_scaling: bool = True,
    ) -> pd.DataFrame:
        """
        Perform scenario analysis across different spot prices and volatilities.

        Args:
            spot_range: Array of spot prices to analyze
            vol_range: Array of volatilities to analyze (optional)
            proportional_vol_scaling: If True (default), scale position volatilities
                proportionally to maintain volatility skew structure. If False,
                apply volatility uniformly to all positions.

        Returns:
            DataFrame with scenario results

        Notes:
            When proportional_vol_scaling=True:
            - Each vol_range value is treated as a target vega-weighted average
            - Position volatilities are scaled proportionally to maintain skew
            - Example: positions [30%, 20%, 25%] at avg 25% -> at 30% become [36%, 24%, 30%]

            When proportional_vol_scaling=False (legacy behavior):
            - Each vol_range value is applied uniformly to all positions
            - Volatility skew structure is not preserved
        """

        results = []
        original_spot = self.spot_price
        original_vol = self.volatility

        # Store original position volatilities for restoration
        original_position_vols = {}
        for i, pos in enumerate(self.positions):
            original_position_vols[i] = pos.option.volatility

        if vol_range is None:
            # Single volatility analysis
            for spot in spot_range:
                self.update_market_conditions(spot_price=spot)

                results.append(
                    {
                        "spot_price": spot,
                        "volatility": self.volatility,
                        "portfolio_value": self.total_value(),
                        "total_delta": self.total_delta(),
                        "net_delta": self.net_delta(),
                        "total_gamma": self.total_gamma(),
                        "total_vega": self.total_vega(),
                    }
                )
        else:
            # Full grid analysis
            for vol in vol_range:
                if proportional_vol_scaling:
                    # Use proportional volatility scaling
                    # Restore original volatilities first
                    restore_volatilities(self, original_position_vols)
                    # Apply proportional shift to target vol once per volatility level
                    apply_proportional_volatility_shift(
                        self, vol, preserve_structure=True
                    )
                    # Calculate actual average for reporting
                    actual_avg_vol = calculate_portfolio_avg_volatility(self)
                else:
                    # Legacy behavior: uniform volatility update
                    self.update_market_conditions(volatility=vol)
                    actual_avg_vol = vol

                # Now iterate through spot prices for this volatility level
                for spot in spot_range:
                    self.update_market_conditions(spot_price=spot)

                    results.append(
                        {
                            "spot_price": spot,
                            "volatility": actual_avg_vol,
                            "portfolio_value": self.total_value(),
                            "total_delta": self.total_delta(),
                            "net_delta": self.net_delta(),
                            "total_gamma": self.total_gamma(),
                            "total_vega": self.total_vega(),
                        }
                    )

        # Restore original market conditions and position volatilities
        restore_volatilities(self, original_position_vols)
        self.update_market_conditions(
            spot_price=original_spot, volatility=original_vol
        )

        return pd.DataFrame(results)
