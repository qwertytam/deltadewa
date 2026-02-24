"""Risk analysis mixin for option portfolio."""

from typing import TYPE_CHECKING, List

import numpy as np

from deltadewa.constants import OptionType
from deltadewa.spot_utils import generate_spot_range

if TYPE_CHECKING:
    from deltadewa.portfolio.position import OptionPosition


class RiskMixin:
    """Mixin providing risk analysis for option portfolio."""

    if TYPE_CHECKING:
        spot_price: float
        underlying_quantity: float
        positions: list["OptionPosition"]

        # pylint: disable=missing-function-docstring, unused-argument
        def calculate_pnl_at_expiry(
            self, spot_price: float, include_underlying: bool = True
        ) -> float: ...

        # pylint: disable=missing-function-docstring, unused-argument
        def vectorized_pnl_at_expiry(
            self, spot_scenarios: np.ndarray, include_underlying: bool = True
        ) -> np.ndarray: ...

    def _get_spot_range(
        self,
        spot_range: np.ndarray | None = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
        num_points: int = 250,
        use_comprehensive_range: bool = False,
    ) -> np.ndarray:
        """
        Get or create a spot price range for analysis.

        Delegates to analysis.functions.generate_spot_range() for consistent
        spot range generation across the codebase.

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
        return generate_spot_range(
            spot_price=self.spot_price,
            spot_range=spot_range,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
            num_points=num_points,
            use_comprehensive_range=use_comprehensive_range,
        )

    def _check_unlimited_trend(
        self,
        pnl_array: np.ndarray,
        check_increasing: bool,
    ) -> bool:
        """
        Check if P&L trend continues at the extreme end of the PnL array.

        This helps detect unlimited profit/loss scenarios by examining if
        the trend continues beyond the sampled range.

        Args:
            pnl_array: Pre-computed P&L array across spot range
            check_increasing: If True, check for increasing trend (profit).
                            If False, check for decreasing trend (loss).

        Returns:
            True if unlimited trend is detected, False otherwise
        """
        if len(pnl_array) < 10:
            return False

        # Check if P&L trend continues at the high end of range
        high_end_pnls = pnl_array[-5:]

        if check_increasing:
            # Check if profits are consistently increasing
            # Use np.diff to check if all differences are positive
            return bool(np.all(np.diff(high_end_pnls) > 0))
        else:
            # Check if losses are consistently increasing (P&L decreasing)
            # Use np.diff to check if all differences are negative
            return bool(np.all(np.diff(high_end_pnls) < 0))

    def calculate_max_loss_options(
        self,
        spot_range: np.ndarray | None = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> dict:
        """
        Calculate maximum loss from options positions only.

        CRITICAL: Checks extreme scenarios including spot = $0 and high spot values
        to ensure accurate max loss detection for all portfolio types.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            spot_min_pct: Minimum spot price as percentage of current spot
            (default: 0% i.e., spot = 0.0)
            spot_max_pct: Maximum spot price as percentage of current spot
            (default: 200% i.e., spot = 2x current spot)

        Returns:
            Dict with 'max_loss', 'spot_at_max_loss', and 'is_unlimited'
        """
        # Use comprehensive range to check extreme scenarios
        spot_range = self._get_spot_range(
            spot_range,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
            use_comprehensive_range=(
                spot_range is None
            ),  # Only for auto-generated ranges
        )

        # Vectorized P&L calculation
        # pylint: disable=assignment-from-no-return
        pnl_array = self.vectorized_pnl_at_expiry(
            spot_range, include_underlying=False
        )
        idx = int(np.argmin(pnl_array))
        max_loss = float(pnl_array[idx])
        spot_at_max_loss = float(spot_range[idx])

        # Check for unlimited loss (naked short calls have unlimited loss potential)
        has_naked_short_calls = any(
            pos.quantity < 0 and pos.option.option_type == OptionType.CALL
            for pos in self.positions
        )

        # Enhanced unlimited loss detection using helper method
        is_unlimited = has_naked_short_calls or self._check_unlimited_trend(
            pnl_array, check_increasing=False
        )

        return {
            "max_loss": max_loss,
            "spot_at_max_loss": spot_at_max_loss,
            "is_unlimited": is_unlimited,
        }

    def calculate_max_profit_options(
        self,
        spot_range: np.ndarray | None = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> dict:
        """
        Calculate maximum profit from options positions only.

        CRITICAL: Checks extreme scenarios including spot = $0 and high spot values
        to ensure accurate max profit detection for all portfolio types.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            spot_min_pct: Minimum spot price as percentage of current spot
            (default: 0% i.e., spot = 0.0)
            spot_max_pct: Maximum spot price as percentage of current spot
            (default: 200% i.e., spot = 2x current spot)

        Returns:
            Dict with 'max_profit', 'spot_at_max_profit', and 'is_unlimited'
        """
        # Use comprehensive range to check extreme scenarios
        spot_range = self._get_spot_range(
            spot_range,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
            use_comprehensive_range=(
                spot_range is None
            ),  # Only for auto-generated ranges
        )

        # Vectorized P&L calculation
        # pylint: disable=assignment-from-no-return
        pnl_array = self.vectorized_pnl_at_expiry(
            spot_range, include_underlying=False
        )
        idx = int(np.argmax(pnl_array))
        max_profit = float(pnl_array[idx])
        spot_at_max_profit = float(spot_range[idx])

        # Check for unlimited profit (long calls have unlimited profit potential)
        has_long_calls = any(
            pos.quantity > 0 and pos.option.option_type == OptionType.CALL
            for pos in self.positions
        )

        # Enhanced unlimited profit detection using helper method
        is_unlimited = has_long_calls or self._check_unlimited_trend(
            pnl_array, check_increasing=True
        )

        return {
            "max_profit": max_profit,
            "spot_at_max_profit": spot_at_max_profit,
            "is_unlimited": is_unlimited,
        }

    def calculate_max_loss_total(
        self,
        spot_range: np.ndarray | None = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> dict:
        """
        Calculate maximum loss including underlying position.

        CRITICAL: Checks extreme scenarios including spot = $0 and high spot values
        to ensure accurate max loss detection for all portfolio types.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            spot_min_pct: Minimum spot price as percentage of current spot
            (default: 0% i.e., spot = 0.0)
            spot_max_pct: Maximum spot price as percentage of current spot
            (default: 200% i.e., spot = 2x current spot)

        Returns:
            Dict with 'max_loss', 'spot_at_max_loss', and 'is_unlimited'
        """
        # Use comprehensive range to check extreme scenarios
        spot_range = self._get_spot_range(
            spot_range,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
            use_comprehensive_range=(
                spot_range is None
            ),  # Only for auto-generated ranges
        )

        # Vectorized P&L calculation
        # pylint: disable=assignment-from-no-return
        pnl_array = self.vectorized_pnl_at_expiry(
            spot_range, include_underlying=True
        )
        idx = int(np.argmin(pnl_array))
        max_loss = float(pnl_array[idx])
        spot_at_max_loss = float(spot_range[idx])

        # Check if loss is potentially unlimited
        is_unlimited = False
        if self.underlying_quantity > 0:
            # Long underlying has unlimited upside, but loss capped at zero
            pass
        elif self.underlying_quantity < 0:
            # Short underlying has unlimited loss potential
            is_unlimited = True

        # Also check for naked short calls in options
        has_naked_short_calls = any(
            pos.quantity < 0 and pos.option.option_type == OptionType.CALL
            for pos in self.positions
        )
        is_unlimited = is_unlimited or has_naked_short_calls

        # Enhanced unlimited loss detection using helper method
        if not is_unlimited:
            is_unlimited = self._check_unlimited_trend(
                pnl_array, check_increasing=False
            )

        return {
            "max_loss": max_loss,
            "spot_at_max_loss": spot_at_max_loss,
            "is_unlimited": is_unlimited,
        }

    def calculate_max_profit_total(
        self,
        spot_range: np.ndarray | None = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> dict:
        """
        Calculate maximum profit including underlying position.

        CRITICAL: Checks extreme scenarios including spot = $0 and high spot values
        to ensure accurate max profit detection for all portfolio types.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            spot_min_pct: Minimum spot price as percentage of current spot
            (default: 0% i.e., spot = 0.0)
            spot_max_pct: Maximum spot price as percentage of current spot
            (default: 200% i.e., spot = 2x current spot)

        Returns:
            Dict with 'max_profit', 'spot_at_max_profit', and 'is_unlimited'
        """
        # Use comprehensive range to check extreme scenarios
        spot_range = self._get_spot_range(
            spot_range,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
            use_comprehensive_range=(
                spot_range is None
            ),  # Only for auto-generated ranges
        )

        # Vectorized P&L calculation
        # pylint: disable=assignment-from-no-return
        pnl_array = self.vectorized_pnl_at_expiry(
            spot_range, include_underlying=True
        )
        idx = int(np.argmax(pnl_array))
        max_profit = float(pnl_array[idx])
        spot_at_max_profit = float(spot_range[idx])

        # Check if profit is potentially unlimited
        is_unlimited = False
        if self.underlying_quantity > 0:
            # Long underlying has unlimited upside
            is_unlimited = True

        # Also check for long calls in options
        has_long_calls = any(
            pos.quantity > 0 and pos.option.option_type == OptionType.CALL
            for pos in self.positions
        )
        is_unlimited = is_unlimited or has_long_calls

        # Enhanced unlimited profit detection using helper method
        if not is_unlimited:
            is_unlimited = self._check_unlimited_trend(
                pnl_array, check_increasing=True
            )

        return {
            "max_profit": max_profit,
            "spot_at_max_profit": spot_at_max_profit,
            "is_unlimited": is_unlimited,
        }

    def calculate_breakeven_points(
        self,
        spot_range: np.ndarray | None = None,
        include_underlying: bool = False,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> List[float]:
        """
        Calculate breakeven spot prices at expiration.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            include_underlying: Whether to include underlying position
            spot_min_pct: Minimum spot price as percentage of current spot
            (default: 0% i.e., spot = 0.0)
            spot_max_pct: Maximum spot price as percentage of current spot
            (default: 200% i.e., spot = 2x current spot)

        Returns:
            List of breakeven spot prices
        """
        spot_range = self._get_spot_range(
            spot_range,
            num_points=500,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
        )

        # Vectorized P&L calculation
        # pylint: disable=assignment-from-no-return
        pnl_array = self.vectorized_pnl_at_expiry(
            spot_range, include_underlying=include_underlying
        )

        # Find sign changes to detect breakeven points
        sign_changes = np.diff(np.sign(pnl_array))
        crossing_indices = np.where(sign_changes != 0)[0]

        # Return the spot prices after the sign change
        return [float(spot_range[i + 1]) for i in crossing_indices]
