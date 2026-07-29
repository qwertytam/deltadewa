"""Caching utilities for portfolio analysis."""

import hashlib
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.portfolio.core import OptionPortfolio


def create_scenario_cache_key(
    spot_scenarios: np.ndarray[Any, np.dtype[Any]],
    time_points: list[datetime],
    metric: str,
    portfolio_state_hash: str,
) -> tuple[Any, ...]:
    """Create a hashable cache key for scenario grid results.

    Args:
        spot_scenarios: Array of spot prices
        time_points: list of valuation dates
        metric: Metric being calculated
        portfolio_state_hash: Hash representing portfolio state

    Returns:
        tuple suitable for use as dictionary key

    """
    # Convert numpy array to tuple for hashing
    spot_tuple = tuple(spot_scenarios.tolist())
    time_tuple = tuple(tp.isoformat() for tp in time_points)

    return (spot_tuple, time_tuple, metric, portfolio_state_hash)


def create_spot_vol_cache_key(
    spot_scenarios: np.ndarray[Any, np.dtype[Any]],
    vol_scenarios: np.ndarray[Any, np.dtype[Any]],
    metric: str,
    portfolio_state_hash: str,
) -> tuple[Any, ...]:
    """Create hashable cache key for spot x vol scenario grid results.

    Args:
        spot_scenarios: Array of spot prices
        vol_scenarios: Array of volatilities
        metric: Metric being calculated
        portfolio_state_hash: Hash representing portfolio state

    Returns:
        tuple suitable for use as dictionary key

    Note:
        Rounds to 6 decimal places for stability. This provides precision
        to 0.000001 for typical spot prices and 0.0001% for volatilities,
        which is more than sufficient for caching purposes.

    """
    # Convert numpy arrays to tuples for hashing (rounded for stability)
    spot_tuple = tuple(np.round(spot_scenarios, 6).tolist())
    vol_tuple = tuple(np.round(vol_scenarios, 6).tolist())

    return ("spot_vol", spot_tuple, vol_tuple, metric, portfolio_state_hash)


def get_portfolio_state_hash(portfolio: OptionPortfolio) -> str:
    """Generate a hash representing the current portfolio state.

    This is used for cache invalidation - if the portfolio changes,
    the hash changes and cached scenario grids are invalidated. Covers
    portfolio-level market state and underlying notional, plus every
    position's quantity, strike, maturity, type, volatility, contract
    size, and exercise style - anything a reprice depends on.

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
        str(portfolio.underlying_quantity),
        str(len(portfolio.positions)),
    ]

    # Add position details
    for pos in portfolio.positions:
        state_elements.extend(
            [
                str(pos.quantity),
                str(pos.option.strike_price),
                str(pos.option.maturity_date.isoformat()),
                pos.option.option_type,
                str(pos.option.volatility),
                str(pos.contract_size),
                str(pos.exercise_style),
            ],
        )

    # Create hash
    state_str = "|".join(state_elements)
    return hashlib.sha256(state_str.encode()).hexdigest()


class ScenarioGridCache:
    """Cache for scenario grid calculations with automatic invalidation.

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

    def __init__(self, max_size: int = 128) -> None:
        """Initialize cache.

        Args:
            max_size: Maximum number of cached results (LRU eviction)

        """
        self._cache: dict[tuple[Any, ...], pd.DataFrame] = {}
        self._max_size = max_size
        self._access_order: list[tuple[Any, ...]] = []

    def get_or_calculate(
        self,
        portfolio: OptionPortfolio,
        analyzer: PortfolioAnalyzer,
        spot_scenarios: np.ndarray[Any, np.dtype[Any]],
        time_points: list[datetime],
        metric: str,
        baseline_spot: float | None = None,
        baseline_valuation_date: datetime | None = None,
    ) -> pd.DataFrame:
        """Get cached result or calculate if not available.

        Args:
            portfolio: OptionPortfolio instance
            analyzer: PortfolioAnalyzer instance
            spot_scenarios: Array of spot prices
            time_points: list of valuation dates
            metric: Metric to calculate
            baseline_spot: Baseline spot for P&L calculation
            baseline_valuation_date: Baseline date for P&L calculation

        Returns:
            DataFrame with scenario grid results

        """
        # Generate cache key
        portfolio_hash = get_portfolio_state_hash(portfolio)
        cache_key = create_scenario_cache_key(
            spot_scenarios,
            time_points,
            metric,
            portfolio_hash,
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
        portfolio: OptionPortfolio,
        analyzer: PortfolioAnalyzer,
        spot_scenarios: np.ndarray[Any, np.dtype[Any]],
        vol_scenarios: np.ndarray[Any, np.dtype[Any]],
        metric: str = "pnl",
        baseline_value: float | None = None,
        proportional_vol_scaling: bool = True,
    ) -> pd.DataFrame:
        """Get cached spot x vol result or calculate if not available.

        Uses vectorized calculation for P&L at expiry for maximum performance.

        Args:
            portfolio: OptionPortfolio instance
            analyzer: PortfolioAnalyzer instance
            spot_scenarios: Array of spot prices
            vol_scenarios: Array of volatilities
            metric: Metric to calculate
            baseline_value: Portfolio value for P&L baseline
            proportional_vol_scaling: If True, scale position vols
            proportionally

        Returns:
            DataFrame with scenario grid results (columns: spot_price,
            volatility, value)

        """
        # Generate cache key
        portfolio_hash = get_portfolio_state_hash(portfolio)
        cache_key = create_spot_vol_cache_key(
            spot_scenarios,
            vol_scenarios,
            metric,
            portfolio_hash,
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

    def clear(self) -> None:
        """Clear all cached results."""
        self._cache.clear()
        self._access_order.clear()

    def size(self) -> int:
        """Return number of cached results."""
        return len(self._cache)
