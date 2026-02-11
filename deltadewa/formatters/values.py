"""
Scalar Value Formatters for Options Dashboard

This module provides consistent formatting functions for scalar values:
- Currency formatting (format_currency, format_currency_for_axis)
- Percentage formatting (format_percentage, format_percentage_for_axis)
- Number formatting (format_number, format_number_auto_precision)
- Greek value formatting (format_greek_value)
- Spot price with percentage change (format_spot_with_pct)
- Axis formatter factories for matplotlib

All formatters in this module are self-contained with no dependencies
on other formatter submodules.
"""

from __future__ import annotations

from typing import Optional, Union, Any, cast

import pandas as pd

try:
    # pylint: disable=ungrouped-imports
    from matplotlib.ticker import FuncFormatter

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    FuncFormatter = None  # type: ignore
    MATPLOTLIB_AVAILABLE = False


def format_currency(
    value: Union[int, float],
    compact: bool = False,
    precision: int = 2,
    show_sign: bool = False,
) -> str:
    """
    Unified currency formatting - SINGLE SOURCE OF TRUTH.

    Args:
        value: Numeric value to format
        compact: Use K/M/B notation for large values
        precision: Decimal places (ignored if compact and value >= 1000)
        show_sign: Include + for positive values

    Returns:
        Formatted currency string

    Compact thresholds (standardized):
        - < 1,000: $X.XX
        - < 1,000,000: $X.XXK
        - < 1,000,000,000: $X.XXM
        - >= 1,000,000,000: $X.XXB

    Examples:
        >>> format_currency(1234.56)
        '$1,234.56'
        >>> format_currency(1234567.89, compact=True)
        '$1.23M'
        >>> format_currency(1234.56, show_sign=True)
        '+$1,234.56'
    """
    if not compact:
        sign = "+" if show_sign and value > 0 else ""
        return f"{sign}${value:,.{precision}f}"

    abs_val = abs(value)
    sign = "-" if value < 0 else ("+" if show_sign and value > 0 else "")

    if abs_val < 1_000:
        return f"{sign}${abs_val:,.{precision}f}"
    elif abs_val < 1_000_000:
        return f"{sign}${abs_val/1_000:.{precision}f}K"
    elif abs_val < 1_000_000_000:
        return f"{sign}${abs_val/1_000_000:.{precision}f}M"
    else:
        return f"{sign}${abs_val/1_000_000_000:.{precision}f}B"


def format_currency_for_axis(x: float, pos: Optional[int] = None) -> str:
    """
    FuncFormatter-compatible currency formatter for matplotlib axes.

    Args:
        x: Value to format
        pos: Position (for FuncFormatter compatibility, unused)

    Returns:
        Formatted currency string

    Formatting rules:
        - Values < $10k: $X,XXX
        - Values < $10M: $XXXk
        - Values >= $10M: $X.XM
    """
    _ = pos  # Unused parameter
    if abs(x) < 10_000:
        return f"${x:,.0f}"
    elif abs(x) < 10_000_000:
        return f"${x/1_000:,.0f}k"
    else:
        return f"${x/1_000_000:,.1f}M"


def format_percentage(
    value: float,
    decimals: int = 2,
    from_decimal: bool = True,
    show_sign: bool = False,
) -> str:
    """
    Unified percentage formatting.

    Args:
        value: Value to format
        decimals: Number of decimal places (default: 2)
        from_decimal: If True, value is decimal (0.1523 = 15.23%)
                     If False, value is already percentage (15.23 = 15.23%)
        show_sign: Include + for positive values

    Returns:
        Formatted percentage string

    Examples:
        >>> format_percentage(0.1523)
        '15.23%'
        >>> format_percentage(0.1523, decimals=1)
        '15.2%'
        >>> format_percentage(15.23, from_decimal=False)
        '15.23%'
    """
    pct_value = value * 100 if from_decimal else value
    sign = "+" if show_sign and pct_value > 0 else ""
    return f"{sign}{pct_value:.{decimals}f}%"


def format_percentage_for_axis(x: float, pos: Optional[int] = None) -> str:
    """
    FuncFormatter-compatible percentage formatter for matplotlib axes.

    Args:
        x: Value to format (in decimal form, e.g., 0.25 = 25%)
        pos: Position (for FuncFormatter compatibility, unused)

    Returns:
        Formatted percentage string
    """
    _ = pos  # Unused parameter
    return f"{x*100:.0f}%"


def format_number(
    value: Union[int, float],
    decimals: int = 2,
    thousands_sep: bool = True,
    compact: bool = False,
) -> str:
    """
    Unified number formatting.

    Args:
        value: Numeric value to format
        decimals: Number of decimal places (default: 2)
        thousands_sep: Whether to use thousands separator (default: True)
        compact: Use K/M/B notation for large values (default: False)

    Returns:
        Formatted number string

    Examples:
        >>> format_number(1234.5678)
        '1,234.57'
        >>> format_number(1234.5678, decimals=4)
        '1,234.5678'
        >>> format_number(1234567, compact=True)
        '1.23M'
    """
    if compact:
        # Reuse currency formatting logic but remove the $
        return format_currency(value, compact=True, precision=decimals).replace(
            "$", ""
        )

    if thousands_sep:
        return f"{value:,.{decimals}f}"
    else:
        return f"{value:.{decimals}f}"


def format_greek_value(
    value: float,
    greek: str = "delta",
    compact: bool = True,
) -> str:
    """
    Greek-specific formatting with appropriate precision.

    Args:
        value: Greek value to format
        greek: Greek name (delta, gamma, vega, theta, rho)
        compact: Use compact notation for large values

    Returns:
        Formatted Greek value string

    Precision by Greek:
        - Delta: 4 decimals
        - Gamma: 6 decimals
        - Vega: 2 decimals
        - Theta: 2 decimals
        - Rho: 4 decimals
    """
    greek_lower = greek.lower()

    # Define precision by Greek
    precision_map = {
        "delta": 4,
        "gamma": 6,
        "vega": 2,
        "theta": 2,
        "rho": 4,
    }

    decimals = precision_map.get(greek_lower, 2)

    if compact and abs(value) >= 1000:
        return format_number(value, decimals=2, compact=True)
    else:
        return format_number(value, decimals=decimals, thousands_sep=True)


def format_number_auto_precision(value: float) -> str:
    """Format a number with precision that adapts to magnitude.

    Automatically selects decimal places based on the absolute value:
    - >= 1,000,000: no decimals, with commas (e.g., "1,234,567")
    - >= 10,000: no decimals, with commas (e.g., "12,345")
    - >= 100: 2 decimals (e.g., "123.45")
    - >= 10: 3 decimals (e.g., "12.345")
    - >= 0.1: 4 decimals (e.g., "0.1234")
    - < 0.1: 6 decimals (e.g., "0.001234")

    Args:
        value: Numeric value to format

    Returns:
        Formatted string with appropriate precision
    """
    abs_val = abs(value)
    if abs_val >= 1_000_000:
        return f"{value:,.0f}"
    elif abs_val >= 10_000:
        return f"{value:,.0f}"
    elif abs_val >= 100:
        return f"{value:,.2f}"
    elif abs_val >= 10:
        return f"{value:.3f}"
    elif abs_val >= 0.1:
        return f"{value:.4f}"
    else:
        return f"{value:.6f}"


def format_spot_with_pct(
    x: float, current_spot: float, pos: Optional[int] = None
) -> str:
    """
    Format spot price with percentage change for axis labels.

    Note: Parameter order (x, current_spot, pos) is intentional for clarity
          when used with lambda/partial. Use get_spot_price_axis_formatter()
          factory function for direct FuncFormatter compatibility.

    Args:
        x: Spot price value
        current_spot: Current spot price to calculate percentage from
        pos: Position (for FuncFormatter compatibility, unused)

    Returns:
        Two-line formatted string with spot price and percentage change

    Example:
        $420
        +10%
    """
    _ = pos  # Unused parameter

    # Handle None edge case
    if x is None:
        return "$0\n0%"

    # Check for zero division and None values
    if current_spot is None or current_spot == 0:
        pct = 0.0
    else:
        pct = (x / current_spot - 1) * 100.0

    curr = format_currency(x, compact=False, precision=0)
    # Note: {pct:+.0f} always includes sign (+/-), even for 0
    return f"{curr}\n{pct:+.0f}%"


def format_currency_for_df(value: object) -> str:
    """NA-safe currency formatter for DataFrame cells.

    Args:
        value: Value to format (may be numeric, NA, or None)

    Returns:
        Formatted string (e.g., "$1,234.56" or "-" for NA values)

    Note:
        Uses format_currency() which produces "$-X" format for negatives
        (e.g., "$-1,234.56"). This differs from the old closure which used
        "-$X" format (e.g., "-$1,234.56"). This change standardizes on the
        canonical format used throughout the codebase.
    """
    if pd.isna(cast(Any, value)):
        return "-"
    try:
        return format_currency(
            float(cast(Any, value)), compact=False, precision=2
        )
    except (TypeError, ValueError):
        return "-" if value is None else str(value)


# ============================================================================
# Axis Formatter Factories
# ============================================================================


def get_currency_axis_formatter(compact: bool = True) -> Any:
    """
    Return a matplotlib FuncFormatter for currency values.

    Args:
        compact: Use compact notation (k, M) for large values

    Returns:
        FuncFormatter instance for matplotlib axes
    """
    if FuncFormatter is None:
        raise ImportError("matplotlib is required for axis formatters")

    if compact:
        return FuncFormatter(format_currency_for_axis)
    else:
        return FuncFormatter(
            lambda x, pos: format_currency(x, compact=False, precision=0)
        )


def get_percentage_axis_formatter(from_decimal: bool = True) -> Any:
    """
    Return a matplotlib FuncFormatter for percentage values.

    Args:
        from_decimal: If True, input values are decimals (0.25 = 25%)

    Returns:
        FuncFormatter instance for matplotlib axes
    """
    if FuncFormatter is None:
        raise ImportError("matplotlib is required for axis formatters")

    if from_decimal:
        return FuncFormatter(format_percentage_for_axis)
    else:
        return FuncFormatter(
            lambda x, pos: format_percentage(x, from_decimal=False, decimals=0)
        )


def get_spot_price_axis_formatter(current_spot: float) -> Any:
    """
    Return a matplotlib FuncFormatter for spot price with % change.

    Args:
        current_spot: Current spot price to calculate percentage from

    Returns:
        FuncFormatter instance for matplotlib axes
    """
    if FuncFormatter is None:
        raise ImportError("matplotlib is required for axis formatters")

    return FuncFormatter(
        lambda x, pos: format_spot_with_pct(x, current_spot, pos)
    )


__all__ = [
    "format_currency",
    "format_currency_for_axis",
    "format_currency_for_df",
    "format_percentage",
    "format_percentage_for_axis",
    "format_number",
    "format_number_auto_precision",
    "format_greek_value",
    "format_spot_with_pct",
    "get_currency_axis_formatter",
    "get_percentage_axis_formatter",
    "get_spot_price_axis_formatter",
]
