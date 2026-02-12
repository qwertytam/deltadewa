"""Module-level convenience functions for portfolio analysis."""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
import hashlib
import pandas as pd
import numpy as np
from deltadewa.analysis.base import PortfolioAnalyzer


def generate_spot_range(
    spot_price: float,
    spot_range: Optional[np.ndarray] = None,
    spot_min_pct: float = 0.0,
    spot_max_pct: float = 200.0,
    num_points: int = 250,
    use_comprehensive_range: bool = False,
) -> np.ndarray:
    """
    Generate a spot price range for analysis.

    This is the single source of truth for spot range generation across
    the entire codebase. All consumers (portfolio/risk.py, visualization/pnl_charts.py,
    analysis/risk_reward.py) should use this function.

    Args:
        spot_price: Current spot price of the underlying asset
        spot_range: Existing spot range to use (returned as-is if provided)
        spot_min_pct: Minimum spot price as percentage of current spot (default: 0%)
        spot_max_pct: Maximum spot price as percentage of current spot (default: 200%)
        num_points: Number of points in the range (default: 250)
        use_comprehensive_range: If True, creates a comprehensive range that includes
            extreme scenarios (spot near $0, very high spot prices) with critical
            points to ensure accurate max loss/profit detection (default: False)

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
    else:
        # Standard range
        spot_min = max(0.01, spot_price * spot_min_pct / 100)
        spot_max = spot_price * spot_max_pct / 100
        return np.linspace(spot_min, spot_max, num_points)


def classify_maturity_bucket(days_to_expiry: int) -> str:
    """
    Convenience function for maturity classification.

    Args:
        days_to_expiry: Days until expiration

    Returns:
        Bucket label string
    """
    return PortfolioAnalyzer.classify_maturity_bucket(days_to_expiry)


def quick_carry_analysis(portfolio) -> Dict:
    """
    Quick carry analysis for a portfolio.

    Args:
        portfolio: OptionPortfolio instance

    Returns:
        Dictionary with carry metrics
    """
    analyzer = PortfolioAnalyzer(portfolio)
    return analyzer.calculate_carry_metrics()


def quick_risk_concentration(
    portfolio, metrics: Optional[List[str]] = None
) -> Dict:
    """
    Quick risk concentration analysis.

    Args:
        portfolio: OptionPortfolio instance
        metrics: Greeks to analyze (default: ['delta', 'gamma', 'vega'])

    Returns:
        Dictionary with concentration analysis
    """
    analyzer = PortfolioAnalyzer(portfolio)
    return analyzer.analyze_risk_concentration(metrics=metrics)


def create_scenario_cache_key(
    spot_scenarios: np.ndarray,
    time_points: List[datetime],
    metric: str,
    portfolio_state_hash: str,
) -> Tuple:
    """
    Create a hashable cache key for scenario grid results.

    Args:
        spot_scenarios: Array of spot prices
        time_points: List of valuation dates
        metric: Metric being calculated
        portfolio_state_hash: Hash representing portfolio state

    Returns:
        Tuple suitable for use as dictionary key
    """
    # Convert numpy array to tuple for hashing
    spot_tuple = tuple(spot_scenarios.tolist())
    time_tuple = tuple(tp.isoformat() for tp in time_points)

    return (spot_tuple, time_tuple, metric, portfolio_state_hash)


def create_spot_vol_cache_key(
    spot_scenarios: np.ndarray,
    vol_scenarios: np.ndarray,
    metric: str,
    portfolio_state_hash: str,
) -> Tuple:
    """
    Create hashable cache key for spot × vol scenario grid results.

    Args:
        spot_scenarios: Array of spot prices
        vol_scenarios: Array of volatilities
        metric: Metric being calculated
        portfolio_state_hash: Hash representing portfolio state

    Returns:
        Tuple suitable for use as dictionary key

    Note:
        Rounds to 6 decimal places for stability. This provides precision
        to 0.000001 for typical spot prices and 0.0001% for volatilities,
        which is more than sufficient for caching purposes.
    """
    # Convert numpy arrays to tuples for hashing (rounded for stability)
    spot_tuple = tuple(np.round(spot_scenarios, 6).tolist())
    vol_tuple = tuple(np.round(vol_scenarios, 6).tolist())

    return ("spot_vol", spot_tuple, vol_tuple, metric, portfolio_state_hash)


def get_portfolio_state_hash(portfolio) -> str:
    """
    Generate a hash representing the current portfolio state.

    This is used for cache invalidation - if the portfolio changes,
    the hash changes and cached scenario grids are invalidated.

    Args:
        portfolio: OptionPortfolio instance

    Returns:
        String hash of portfolio state
    """

    # Collect all relevant state
    state_elements = [
        str(portfolio.spot_price),
        str(portfolio.volatility),
        str(portfolio.risk_free_rate),
        str(portfolio.dividend_yield),
        str(portfolio.valuation_date.isoformat()),
        str(len(portfolio.positions)),
    ]

    # Add position details
    for pos in portfolio.positions:
        state_elements.extend(
            [
                pos.symbol,
                str(pos.quantity),
                str(pos.option.strike_price),
                str(pos.option.maturity_date.isoformat()),
                pos.option.option_type,
                str(pos.option.volatility),
            ]
        )

    # Create hash
    state_str = "|".join(state_elements)
    return hashlib.md5(state_str.encode()).hexdigest()


class ScenarioGridCache:
    """
    Cache for scenario grid calculations with automatic invalidation.

    This class provides caching for expensive scenario grid calculations.
    The cache is automatically invalidated when portfolio state changes.

    Usage:
        cache = ScenarioGridCache()

        # First call calculates and caches
        result1 = cache.get_or_calculate(
            portfolio, analyzer, spot_scenarios, time_points, metric
        )

        # Second call returns cached result (if portfolio unchanged)
        result2 = cache.get_or_calculate(
            portfolio, analyzer, spot_scenarios, time_points, metric
        )
    """

    def __init__(self, max_size: int = 128):
        """
        Initialize cache.

        Args:
            max_size: Maximum number of cached results (LRU eviction)
        """
        self._cache: Dict[Tuple, pd.DataFrame] = {}
        self._max_size = max_size
        self._access_order: List[Tuple] = []

    def get_or_calculate(
        self,
        portfolio,
        analyzer,
        spot_scenarios: np.ndarray,
        time_points: List[datetime],
        metric: str,
        baseline_spot: Optional[float] = None,
        baseline_valuation_date: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Get cached result or calculate if not available.

        Args:
            portfolio: OptionPortfolio instance
            analyzer: PortfolioAnalyzer instance
            spot_scenarios: Array of spot prices
            time_points: List of valuation dates
            metric: Metric to calculate
            baseline_spot: Baseline spot for P&L calculation
            baseline_valuation_date: Baseline date for P&L calculation

        Returns:
            DataFrame with scenario grid results
        """
        # Generate cache key
        portfolio_hash = get_portfolio_state_hash(portfolio)
        cache_key = create_scenario_cache_key(
            spot_scenarios, time_points, metric, portfolio_hash
        )

        # Check cache
        if cache_key in self._cache:
            # Update access order
            if cache_key in self._access_order:
                self._access_order.remove(cache_key)
            self._access_order.append(cache_key)
            return self._cache[cache_key].copy()

        # Calculate result
        result = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric=metric,
            baseline_spot=baseline_spot,
            baseline_valuation_date=baseline_valuation_date,
        )

        # Store in cache
        self._cache[cache_key] = result.copy()
        self._access_order.append(cache_key)

        # Enforce max size (LRU eviction)
        while len(self._cache) > self._max_size:
            oldest_key = self._access_order.pop(0)
            if oldest_key in self._cache:
                del self._cache[oldest_key]

        return result

    def get_or_calculate_spot_vol(
        self,
        portfolio,
        analyzer,
        spot_scenarios: np.ndarray,
        vol_scenarios: np.ndarray,
        metric: str = "pnl",
        baseline_value: Optional[float] = None,
        proportional_vol_scaling: bool = True,
    ) -> pd.DataFrame:
        """
        Get cached spot × vol result or calculate if not available.

        Uses vectorized calculation for P&L at expiry for maximum performance.

        Args:
            portfolio: OptionPortfolio instance
            analyzer: PortfolioAnalyzer instance
            spot_scenarios: Array of spot prices
            vol_scenarios: Array of volatilities
            metric: Metric to calculate
            baseline_value: Portfolio value for P&L baseline
            proportional_vol_scaling: If True, scale position vols proportionally

        Returns:
            DataFrame with scenario grid results (columns: spot_price, volatility, value)
        """
        # Generate cache key
        portfolio_hash = get_portfolio_state_hash(portfolio)
        cache_key = create_spot_vol_cache_key(
            spot_scenarios, vol_scenarios, metric, portfolio_hash
        )

        # Check cache
        if cache_key in self._cache:
            # Update access order (LRU)
            if cache_key in self._access_order:
                self._access_order.remove(cache_key)
            self._access_order.append(cache_key)
            return self._cache[cache_key].copy()

        # Calculate result
        result = analyzer.scenario_grid_spot_vol(
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            metric=metric,
            baseline_value=baseline_value,
            proportional_vol_scaling=proportional_vol_scaling,
        )

        # Store in cache with LRU eviction
        self._cache[cache_key] = result.copy()
        self._access_order.append(cache_key)

        while len(self._cache) > self._max_size:
            oldest_key = self._access_order.pop(0)
            if oldest_key in self._cache:
                del self._cache[oldest_key]

        return result

    def clear(self):
        """Clear all cached results."""
        self._cache.clear()
        self._access_order.clear()

    def size(self) -> int:
        """Return number of cached results."""
        return len(self._cache)
