"""P&L calculation mixin for option portfolios."""

import numpy as np
from typing import Optional
from deltadewa import constants as const


class PnLMixin:
    """Mixin providing P&L calculations for OptionPortfolio."""

    def _get_spot_range(
        self,
        spot_range: Optional[np.ndarray] = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
        num_points: int = 250,
        use_comprehensive_range: bool = False,
    ) -> np.ndarray:
        """
        Get or create a spot price range for analysis.

        Args:
            spot_range: Existing spot range to use (returned as-is if provided)
            spot_min_pct: Minimum spot price as percentage of current spot (default: 0%)
            spot_max_pct: Maximum spot price as percentage of current spot (default: 200%)
            num_points: Number of points in the range (default: 250)
            use_comprehensive_range: If True, creates a comprehensive range that includes
                extreme scenarios (spot near $0, very high spot prices) with critical
                points to ensure accurate max loss/profit detection (default: False)

        Returns:
            NumPy array of spot prices for analysis
        """
        if spot_range is not None:
            return spot_range

        if use_comprehensive_range:
            # Create comprehensive range that includes extreme scenarios
            current_spot = self.spot_price

            # Near-zero value scaled appropriately for the asset price
            # Use 0.01% of current spot, but ensure minimum of 0.01
            near_zero = max(0.01, current_spot * 0.0001)

            # Critical points to always check for accurate max/min detection
            critical_points = [
                # Near zero (important for puts - can't use exact 0 due to
                # log calculations)
                near_zero,
                current_spot * 0.1,  # 90% down
                current_spot * 0.25,  # 75% down
                current_spot * 0.5,  # 50% down
                current_spot * 0.75,  # 25% down
                current_spot,  # Current spot
                current_spot * 1.25,  # 25% up
                current_spot * 1.5,  # 50% up
                current_spot * 2.0,  # 100% up
                current_spot * 3.0,  # 200% up
                current_spot * 5.0,  # 400% up
                current_spot * 10.0,  # 900% up
            ]

            # Dense range for main area - from near-zero to highest critical point
            spot_min = near_zero
            spot_max = current_spot * 10.0  # Maximum is 10x current spot
            main_range = np.linspace(spot_min, spot_max, 300)

            # Combine and sort
            spot_range = np.unique(
                np.concatenate([critical_points, main_range])
            )
            return np.sort(spot_range)
        else:
            # Standard range
            spot_min = max(0.01, self.spot_price * spot_min_pct / 100)
            spot_max = self.spot_price * spot_max_pct / 100
            return np.linspace(spot_min, spot_max, num_points)

    def calculate_net_debit(self) -> float:
        """
        Calculate the net debit/credit for implementing the portfolio.

        Returns:
            Net debit (positive) or net credit (negative) in dollars
        """
        return self.total_value()

    def calculate_pnl_at_expiry(
        self, spot_price_at_expiry: float, include_underlying: bool = False
    ) -> float:
        """
        Calculate P&L at expiration for a given spot price.

        Args:
            spot_price_at_expiry: Spot price at expiration
            include_underlying: Whether to include underlying position P&L

        Returns:
            Total P&L at expiration
        """
        initial_cost = self.total_value()
        pnl = -initial_cost  # Start with negative of initial cost

        # Calculate intrinsic value at expiry for each position
        for pos in self.positions:
            if pos.option.option_type.lower() == "call":
                intrinsic = max(
                    0, spot_price_at_expiry - pos.option.strike_price
                )
            else:  # put
                intrinsic = max(
                    0, pos.option.strike_price - spot_price_at_expiry
                )

            pnl += intrinsic * pos.quantity * pos.contract_size

        # Add underlying P&L if requested
        if include_underlying and self.underlying_quantity != 0:
            underlying_pnl = (
                spot_price_at_expiry - self.spot_price
            ) * self.underlying_quantity
            pnl += underlying_pnl

        return pnl
