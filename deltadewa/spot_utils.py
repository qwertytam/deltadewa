"""Pure spot price utility functions with zero internal dependencies.

This module contains pure mathematical utilities for spot price range
generation. It exists as a leaf module to avoid circular dependencies between
the portfolio and analysis layers:

- portfolio layer: data + computation (should not depend on analysis)
- analysis layer: aggregation + interpretation (depends on portfolio)
- visualization/widgets layer: presentation (depends on both)

By extracting these pure utilities here, portfolio.risk can use them without
depending on the analysis layer.
"""

import numpy as np


def generate_spot_range(
    spot_price: float,
    spot_range: np.ndarray | None = None,
    spot_min_pct: float = 0.0,
    spot_max_pct: float = 200.0,
    num_points: int = 250,
    use_comprehensive_range: bool = False,
) -> np.ndarray:
    """Generate a spot price range for analysis.

    This is the single source of truth for spot range generation across
    the entire codebase. All consumers (portfolio/risk.py, visualization
    pnl_charts.py, analysis/risk_reward.py) should use this function.

    Args:
        spot_price: Current spot price of the underlying asset
        spot_range: Existing spot range to use (returned as-is if provided)
        spot_min_pct: Minimum spot price as percentage of current spot
        (default: 0%)
        spot_max_pct: Maximum spot price as percentage of current spot
        (default: 200%)
        num_points: Number of points in the range (default: 250)
        use_comprehensive_range: If True, creates a comprehensive range that
        includes extreme scenarios (spot near $0, very high spot prices) with
        critical points to ensure accurate max loss/profit detection (default:
        False)

    Returns:
        NumPy array of spot prices for analysis

    Examples:
        >>> # Standard range from 80% to 120% of spot
        >>> generate_spot_range(100.0, spot_min_pct=80.0, spot_max_pct=120.0)

        >>> # Comprehensive range with critical points
        >>> generate_spot_range(100.0, use_comprehensive_range=True)

        >>> # Use existing range (passthrough)
        >>> existing = np.array([90, 100, 110])
        >>> generate_spot_range(100.0, spot_range=existing)

    """
    if spot_range is not None:
        return spot_range

    if use_comprehensive_range:
        # Create comprehensive range that includes extreme scenarios
        # Near-zero value scaled appropriately for the asset price
        # Use 0.01% of current spot, but ensure minimum of 0.01
        near_zero = max(0.01, spot_price * 0.0001)

        # Critical points to always check for accurate max/min detection
        critical_points = [
            # Near zero (important for puts - can't use exact 0 due to
            # log calculations)
            near_zero,
            spot_price * 0.1,  # 90% down
            spot_price * 0.25,  # 75% down
            spot_price * 0.5,  # 50% down
            spot_price * 0.75,  # 25% down
            spot_price,  # Current spot
            spot_price * 1.25,  # 25% up
            spot_price * 1.5,  # 50% up
            spot_price * 2.0,  # 100% up
            spot_price * 3.0,  # 200% up
            spot_price * 5.0,  # 400% up
            spot_price * 10.0,  # 900% up
        ]

        # Dense range for main area - from near-zero to highest critical point
        spot_min = near_zero
        spot_max = spot_price * 10.0  # Maximum is 10x current spot
        main_range = np.linspace(spot_min, spot_max, 300)

        # Combine and sort
        spot_range = np.unique(np.concatenate([critical_points, main_range]))
        return np.sort(spot_range)

    # Standard range
    spot_min = max(0.01, spot_price * spot_min_pct / 100)
    spot_max = spot_price * spot_max_pct / 100
    return np.linspace(spot_min, spot_max, num_points)
