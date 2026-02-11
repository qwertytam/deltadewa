"""
Utility functions for the deltadewa package.

This module provides common utilities for formatting, printing,
and displaying data in notebooks and scripts.
"""

from typing import TYPE_CHECKING, Optional, Union
import numpy as np
import pandas as pd
from IPython.display import clear_output

# Import formatting functions from centralized module
from deltadewa.formatters import (
    format_currency as _format_currency,
    format_percentage as _format_percentage,
    format_number as _format_number,
    format_currency_for_axis as _format_currency_for_axis,
)

if TYPE_CHECKING:
    from pandas.io.formats.style import Styler

__all__ = [
    # Print formatting utilities
    "print_header",
    "print_subheader",
    "print_divider",
    "print_section",
    "print_key_value",
    "print_metric_summary",
    # DataFrame display utilities
    "display_styled_dataframe",
    "format_currency",
    "format_percentage",
    "format_number",
    "format_currency_compact",
    # Status/alert utilities
    "print_success",
    "print_warning",
    "print_error",
    "print_info",
    # Table utilities
    "print_table_row",
    "print_table",
    # Convenience functions
    "clear_output_and_print",
    "print_progress",
    # Volatility analysis utilities
    "calculate_portfolio_avg_volatility",
    "apply_proportional_volatility_shift",
    "restore_volatilities",
    "get_volatility_stats",
]

# ========== Print Formatting Utilities ==========


def print_header(title: str, width: int = 80, char: str = "=") -> None:
    """
    Print a formatted section header.

    Args:
        title: Header text to display
        width: Total width of the header (default: 80)
        char: Character to use for borders (default: '=')

    Example:
        >>> print_header("PORTFOLIO SUMMARY")
        ================================================================================
        PORTFOLIO SUMMARY
        ================================================================================
    """
    print(char * width)
    print(title)
    print(char * width)


def print_subheader(title: str, width: int = 80) -> None:
    """
    Print a formatted subsection header (using dashes).

    Args:
        title: Subheader text to display
        width: Total width of the header (default: 80)

    Example:
        >>> print_subheader("Position Details")
        --------------------------------------------------------------------------------
        Position Details
        --------------------------------------------------------------------------------
    """
    print_header(title, width, char="-")


def print_divider(width: int = 80, char: str = "-") -> None:
    """
    Print a simple divider line.

    Args:
        width: Width of the divider (default: 80)
        char: Character to use (default: '-')

    Example:
        >>> print_divider()
        --------------------------------------------------------------------------------
    """
    print(char * width)


def print_section(
    title: str, content: Optional[str] = None, width: int = 80
) -> None:
    """
    Print a complete section with header and optional content.

    Args:
        title: Section title
        content: Optional content to print below header
        width: Width of the section (default: 80)

    Example:
        >>> print_section("RESULTS", "Total: $1,234.56")
        ================================================================================
        RESULTS
        ================================================================================
        Total: $1,234.56
    """
    print_header(title, width)
    if content:
        print(content)


def print_key_value(
    key: str, value, width: int = 40, align: str = "left"
) -> None:
    """
    Print a key-value pair with aligned formatting.

    Args:
        key: The key/label
        value: The value to display
        width: Total width for key-value pair (default: 40)
        align: Alignment for value ('left' or 'right', default: 'left')

    Example:
        >>> print_key_value("Spot Price", "$100.00", align='right')
        Spot Price:                         $100.00
    """
    if align == "right":
        print(f"{key}:{value:>{width - len(key) - 1}}")
    else:
        print(f"{key}: {value}")


def print_metric_summary(
    metrics: dict, title: Optional[str] = None, width: int = 80
) -> None:
    """
    Print a formatted summary of metrics.

    Args:
        metrics: Dictionary of metric names to values
        title: Optional section title
        width: Width of the output (default: 80)

    Example:
        >>> metrics = {'Total Delta': 125.50, 'Gamma': 0.0045, 'Theta': -15.25}
        >>> print_metric_summary(metrics, "RISK METRICS")
        ================================================================================
        RISK METRICS
        ================================================================================
        Total Delta: 125.50
        Gamma: 0.0045
        Theta: -15.25
        ================================================================================
    """
    if title:
        print_header(title, width)

    for key, value in metrics.items():
        if isinstance(value, float):
            if abs(value) >= 10**6:
                print(f"{key}: {value:,.0f}")
            elif abs(value) >= 10000:
                print(f"{key}: {value:.0f}")
            elif abs(value) >= 100:
                print(f"{key}: {value:.2f}")
            elif abs(value) >= 10:
                print(f"{key}: {value:.3f}")
            elif abs(value) >= 0.1:
                print(f"{key}: {value:.4f}")
            else:
                print(f"{key}: {value:.6f}")
        else:
            print(f"{key}: {value}")

    if title:
        print_divider(width, char="=")


# ========== DataFrame Display Utilities ==========


def display_styled_dataframe(
    df: pd.DataFrame,
    format_dict: Optional[dict] = None,
    gradient_column: Optional[str] = None,
    start_index: int = 1,
    title_case: bool = True,
    cmap: str = "RdYlGn",
) -> "Styler":
    """
    Format and display a DataFrame with consistent styling.

    Args:
        df: DataFrame to display
        format_dict: Dictionary of column names to format strings
        gradient_column: Column to apply background gradient
        start_index: Starting index for display (default: 1)
        title_case: Whether to convert column names to title case (default: True)
        cmap: Colormap for gradient (default: 'RdYlGn')

    Returns:
        Styled DataFrame

    Example:
        >>> df = pd.DataFrame({'price': [100.0, 200.0], 'delta': [0.5, 0.75]})
        >>> styled = display_styled_dataframe(
        ...     df,
        ...     format_dict={'price': '${:.2f}', 'delta': '{:.4f}'},
        ...     gradient_column='delta'
        ... )
    """
    df_display = df.copy()

    # Convert column names to title case if requested
    if title_case:
        df_display = df_display.rename(
            columns=lambda s: s.replace("_", " ").title()
        )

    # Reset index to start at specified value
    df_display.index = pd.RangeIndex(
        start=start_index, stop=len(df_display) + start_index
    )

    # Apply formatting
    styled = df_display.style
    if format_dict:
        # Update format_dict keys if title case was applied
        if title_case:
            format_dict_updated = {
                k.replace("_", " ").title(): v for k, v in format_dict.items()
            }
        else:
            format_dict_updated = format_dict
        styled = styled.format(format_dict_updated)

    # Apply background gradient if specified
    if gradient_column:
        gradient_col = (
            gradient_column.replace("_", " ").title()
            if title_case
            else gradient_column
        )
        if gradient_col in df_display.columns:
            styled = styled.background_gradient(
                subset=[gradient_col], cmap=cmap
            )

    return styled


# ========== Formatting Functions (Re-exported for Backward Compatibility) ==========
# These functions are now defined in deltadewa.formatters and re-exported here
# for backward compatibility with existing code.


def format_currency(value: Union[int, float], compact: bool = False) -> str:
    """
    Format a value as currency.

    Args:
        value: Numeric value to format
        compact: If True, use compact notation (K, M, B) for large values

    Returns:
        Formatted currency string

    Example:
        >>> format_currency(1234.56)
        '$1,234.56'
        >>> format_currency(1234567.89, compact=True)
        '$1.23M'
    
    Note:
        This function is re-exported from deltadewa.formatters for backward compatibility.
    """
    return _format_currency(value, compact=compact, precision=2)


def format_percentage(value: float, decimals: int = 2) -> str:
    """
    Format a decimal value as a percentage.

    Args:
        value: Decimal value (e.g., 0.1523 for 15.23%)
        decimals: Number of decimal places (default: 2)

    Returns:
        Formatted percentage string

    Example:
        >>> format_percentage(0.1523)
        '15.23%'
        >>> format_percentage(0.1523, decimals=1)
        '15.2%'
    
    Note:
        This function is re-exported from deltadewa.formatters for backward compatibility.
    """
    return _format_percentage(value, decimals=decimals, from_decimal=True)


def format_number(
    value: Union[int, float], decimals: int = 2, thousands_sep: bool = True
) -> str:
    """
    Format a number with appropriate precision.

    Args:
        value: Numeric value to format
        decimals: Number of decimal places (default: 2)
        thousands_sep: Whether to use thousands separator (default: True)

    Returns:
        Formatted number string

    Example:
        >>> format_number(1234.5678)
        '1,234.57'
        >>> format_number(1234.5678, decimals=4)
        '1,234.5678'
    
    Note:
        This function is re-exported from deltadewa.formatters for backward compatibility.
    """
    return _format_number(value, decimals=decimals, thousands_sep=thousands_sep)


def format_currency_compact(x, pos) -> str:  # pylint: disable=unused-argument
    """
    Format currency: <$10k as $x,xxx, <$10M as $x,xxxk, else $x,xxxM
    
    Note:
        This function is re-exported from deltadewa.formatters for backward compatibility.
    """
    return _format_currency_for_axis(x, pos)


# ========== Status/Alert Utilities ==========


def print_success(message: str, prefix: str = "✓") -> None:
    """
    Print a success message with checkmark.

    Args:
        message: Success message
        prefix: Prefix symbol (default: '✓')

    Example:
        >>> print_success("Portfolio loaded successfully")
        ✓ Portfolio loaded successfully
    """
    print(f"{prefix} {message}")


def print_warning(message: str, prefix: str = "⚠") -> None:
    """
    Print a warning message.

    Args:
        message: Warning message
        prefix: Prefix symbol (default: '⚠')

    Example:
        >>> print_warning("Low liquidity detected")
        ⚠ Low liquidity detected
    """
    print(f"{prefix} {message}")


def print_error(message: str, prefix: str = "✗") -> None:
    """
    Print an error message.

    Args:
        message: Error message
        prefix: Prefix symbol (default: '✗')

    Example:
        >>> print_error("Failed to load data")
        ✗ Failed to load data
    """
    print(f"{prefix} {message}")


def print_info(message: str, prefix: str = "ℹ️") -> None:
    """
    Print an informational message.

    Args:
        message: Info message
        prefix: Prefix symbol (default: 'ℹ️')

    Example:
        >>> print_info("Using default configuration")
        ℹ️  Using default configuration
    """
    print(f"{prefix}  {message}")


# ========== Table Utilities ==========


def print_table_row(columns: list, widths: list, separator: str = "|") -> None:
    """
    Print a formatted table row.

    Args:
        columns: List of column values
        widths: List of column widths
        separator: Column separator (default: '|')

    Example:
        >>> print_table_row(['Name', 'Value', 'Delta'], [20, 15, 10])
        Name                | Value         | Delta
    """
    row = separator.join(
        f" {str(col):<{w-2}} " for col, w in zip(columns, widths)
    )
    print(row)


def print_table(
    data: list, headers: list, widths: Optional[list] = None
) -> None:
    """
    Print a simple formatted table.

    Args:
        data: List of rows (each row is a list of values)
        headers: List of column headers
        widths: Optional list of column widths (auto-calculated if None)

    Example:
        >>> headers = ['Strike', 'Type', 'Delta']
        >>> data = [[100, 'Call', 0.55], [110, 'Put', -0.45]]
        >>> print_table(data, headers)
    """
    # Auto-calculate widths if not provided
    if widths is None:
        widths = []
        for i, header in enumerate(headers):
            max_width = len(str(header))
            for row in data:
                if i < len(row):
                    max_width = max(max_width, len(str(row[i])))
            widths.append(max_width + 4)  # Add padding

    # Print header
    print_table_row(headers, widths)
    print_divider(sum(widths) + len(widths) - 1)

    # Print data rows
    for row in data:
        print_table_row(row, widths)


# ========== Convenience Functions ==========


def clear_output_and_print(message: str, wait: bool = True) -> None:
    """
    Clear output and print a new message (useful in widgets).

    Args:
        message: Message to print
        wait: Whether to wait before clearing (default: True)

    Note:
        This is a convenience wrapper for Jupyter output clearing
    """

    clear_output(wait=wait)
    print(message)


def print_progress(
    current: int,
    total: int,
    prefix: str = "",
    suffix: str = "",
    length: int = 50,
    fill: str = "█",
) -> None:
    """
    Print a progress bar.

    Args:
        current: Current progress value
        total: Total value
        prefix: Prefix string (default: '')
        suffix: Suffix string (default: '')
        length: Length of progress bar (default: 50)
        fill: Fill character (default: '█')

    Example:
        >>> for i in range(100):
        ...     print_progress(i + 1, 100, prefix='Progress:', suffix='Complete')
    """
    percent = f"{100 * (current / float(total)):.1f}"
    filled_length = int(length * current // total)
    progress_bar = fill * filled_length + "-" * (length - filled_length)
    print(f"\r{prefix} |{progress_bar}| {percent}% {suffix}", end="")
    if current == total:
        print()  # New line on completion


# ========== Volatility Analysis Utilities ==========


def calculate_portfolio_avg_volatility(portfolio) -> float:
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
    portfolio, target_avg_vol: float, preserve_structure: bool = True
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


def restore_volatilities(portfolio, original_vols: dict) -> None:
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


def get_volatility_stats(portfolio) -> dict:
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
