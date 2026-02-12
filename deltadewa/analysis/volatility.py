"""
Volatility analysis utilities for options portfolios.

This module provides functions for analyzing and manipulating portfolio volatility,
including vega-weighted averaging, proportional scaling, and statistical analysis.
"""

from typing import TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio

__all__ = [
    "calculate_portfolio_avg_volatility",
    "apply_proportional_volatility_shift",
    "restore_volatilities",
    "get_volatility_stats",
]


def calculate_portfolio_avg_volatility(portfolio: "OptionPortfolio") -> float:
    """
    Calculate vega-weighted average volatility across all positions.

    This function computes a weighted average of position volatilities,
    where the weights are the absolute vega values of each position.
    This ensures that positions with higher volatility sensitivity
    have more influence on the average.

    Args:
        portfolio: OptionPortfolio instance

    Returns:
        Vega-weighted average volatility as a decimal (e.g., 0.25 for 25%)

    Notes:
        - If total vega is zero or portfolio is empty, returns portfolio.volatility
        - Uses absolute vega values to weight all positions equally regardless of direction
        - Each position uses its current volatility value (position.option.volatility)

    Example:
        >>> # Portfolio with positions at 30%, 20%, 25% volatility
        >>> # With respective vegas of 100, 200, 150
        >>> avg_vol = calculate_portfolio_avg_volatility(portfolio)
        >>> # Returns (30*100 + 20*200 + 25*150) / (100+200+150) = 23.33%
    """
    if not portfolio.positions:
        return portfolio.volatility

    total_weighted_vol = 0.0
    total_vega = 0.0

    for position in portfolio.positions:
        vega = abs(position.position_vega())
        vol = position.option.volatility

        total_weighted_vol += vol * vega
        total_vega += vega

    # Fallback to portfolio volatility if total vega is zero
    if total_vega == 0:
        return portfolio.volatility

    return total_weighted_vol / total_vega


def apply_proportional_volatility_shift(
    portfolio: "OptionPortfolio",
    target_avg_vol: float,
    preserve_structure: bool = True,
) -> dict:
    """
    Scale all position volatilities proportionally to achieve target average.

    This function shifts volatilities while maintaining the relative volatility
    structure (skew/smile) of the portfolio. Each position's volatility is
    scaled by the same factor: (target_avg_vol / current_avg_vol).

    Args:
        portfolio: OptionPortfolio instance to modify
        target_avg_vol: Target vega-weighted average volatility (decimal, e.g., 0.30)
        preserve_structure: If True, scale proportionally; if False, set all to target

    Returns:
        Dictionary mapping position index to original volatility value
        Use with restore_volatilities() to revert changes

    Notes:
        - Modifies portfolio positions in-place
        - Returns original values for restoration
        - If preserve_structure=False, sets all positions to target_avg_vol uniformly
        - If current average is zero, sets all to target_avg_vol

    Example:
        >>> # Positions with [30%, 20%, 25%] volatilities, avg = 25%
        >>> # Shift to 30% average:
        >>> original_vols = apply_proportional_volatility_shift(portfolio, 0.30)
        >>> # Positions become [36%, 24%, 30%] (all scaled by 1.2×)
        >>> restore_volatilities(portfolio, original_vols)  # Restore original
    """
    original_vols = {}

    # Store original volatilities
    for i, position in enumerate(portfolio.positions):
        original_vols[i] = position.option.volatility

    if not preserve_structure:
        # Uniform shift: set all positions to target
        for position in portfolio.positions:
            position.option.update_volatility(target_avg_vol)
        return original_vols

    # Proportional shift: maintain volatility structure
    current_avg = calculate_portfolio_avg_volatility(portfolio)

    # Avoid division by zero
    if current_avg == 0:
        for position in portfolio.positions:
            position.option.update_volatility(target_avg_vol)
        return original_vols

    scaling_factor = target_avg_vol / current_avg

    for position in portfolio.positions:
        new_vol = position.option.volatility * scaling_factor
        position.option.update_volatility(new_vol)

    return original_vols


def restore_volatilities(
    portfolio: "OptionPortfolio", original_vols: dict
) -> None:
    """
    Restore position volatilities to their original values.

    This function reverses changes made by apply_proportional_volatility_shift()
    by restoring each position's volatility to its saved value.

    Args:
        portfolio: OptionPortfolio instance to modify
        original_vols: Dictionary from apply_proportional_volatility_shift()
                      Maps position index to original volatility

    Notes:
        - Modifies portfolio positions in-place
        - Silently skips any missing position indices
        - Safe to call even if portfolio structure has changed

    Example:
        >>> original_vols = apply_proportional_volatility_shift(portfolio, 0.30)
        >>> # ... perform analysis ...
        >>> restore_volatilities(portfolio, original_vols)  # Restore original state
    """
    for i, vol in original_vols.items():
        if i < len(portfolio.positions):
            portfolio.positions[i].option.update_volatility(vol)


def get_volatility_stats(portfolio: "OptionPortfolio") -> dict:
    """
    Get statistical summary of volatility distribution across positions.

    This function analyzes the volatility structure of a portfolio,
    providing insights into volatility skew, custom volatility usage,
    and the overall volatility profile.

    Args:
        portfolio: OptionPortfolio instance

    Returns:
        Dictionary containing:
        - 'avg_volatility': Vega-weighted average (decimal)
        - 'min_volatility': Minimum volatility across positions
        - 'max_volatility': Maximum volatility across positions
        - 'std_volatility': Standard deviation of volatilities
        - 'num_positions': Total number of positions
        - 'num_custom_vol': Number of positions with custom volatility
        - 'portfolio_volatility': Portfolio-level default volatility
        - 'volatility_range': Difference between max and min

    Notes:
        - Returns empty dict if portfolio has no positions
        - All volatility values are in decimal format (e.g., 0.25 for 25%)
        - Custom volatility count helps identify skew complexity

    Example:
        >>> stats = get_volatility_stats(portfolio)
        >>> print(f"Average: {stats['avg_volatility']:.2%}")
        >>> print(f"Range: {stats['min_volatility']:.2%} - {stats['max_volatility']:.2%}")
        >>> print(f"Positions with custom vol: {stats['num_custom_vol']}/{stats['num_positions']}")
    """
    if not portfolio.positions:
        return {}

    volatilities = [pos.option.volatility for pos in portfolio.positions]
    custom_vol_count = sum(
        1 for pos in portfolio.positions if pos.custom_volatility
    )

    return {
        "avg_volatility": calculate_portfolio_avg_volatility(portfolio),
        "min_volatility": min(volatilities),
        "max_volatility": max(volatilities),
        "std_volatility": float(np.std(volatilities)),
        "num_positions": len(portfolio.positions),
        "num_custom_vol": custom_vol_count,
        "portfolio_volatility": portfolio.volatility,
        "volatility_range": max(volatilities) - min(volatilities),
    }
