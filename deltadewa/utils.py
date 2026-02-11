"""
Utility functions for the deltadewa package.

This module provides common utilities for formatting, printing,
and displaying data in notebooks and scripts.
"""

from typing import TYPE_CHECKING, Optional
import pandas as pd
from IPython.display import clear_output
from deltadewa.formatters import (
    prepare_dataframe_display,
    apply_gradient_style,
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

    .. deprecated::
        Use :func:`deltadewa.formatters.prepare_dataframe_display` and
        :func:`deltadewa.formatters.apply_gradient_style` directly instead.

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
    df_display = prepare_dataframe_display(
        df, title_case=title_case, start_index=start_index
    )

    styled = df_display.style
    if format_dict:
        if title_case:
            format_dict = {
                k.replace("_", " ").title(): v for k, v in format_dict.items()
            }
        styled = styled.format(format_dict)

    if gradient_column:
        gradient_col = (
            gradient_column.replace("_", " ").title()
            if title_case
            else gradient_column
        )
        if gradient_col in df_display.columns:
            styled = apply_gradient_style(styled, gradient_col, cmap=cmap)

    return styled


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
