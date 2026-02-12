"""
Utility functions for the deltadewa package.

This module provides common utilities for formatting, printing,
and displaying data.

.. note::
    Direct use of print functions here is deprecated.
    Please use `deltadewa.reporting.ConsoleReporter`.
"""

from typing import Optional
from deltadewa.reporting.console import ConsoleReporter

# Create a default instance for backward compatibility
_reporter = ConsoleReporter()

__all__ = [
    "print_header",
    "print_subheader",
    "print_divider",
    "print_section",
    "print_key_value",
    "print_metric_summary",
    "print_success",
    "print_warning",
    "print_error",
    "print_info",
    "print_table_row",
    "print_table",
    "clear_output_and_print",
    "print_progress",
]

# Delegate all existing functions to the reporter instance


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
    # Temporarily override width if provided, otherwise use default
    old_width = _reporter.width
    _reporter.width = width
    _reporter.header(title, char)
    _reporter.width = old_width


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
    old_width = _reporter.width
    _reporter.width = width
    _reporter.subheader(title)
    _reporter.width = old_width


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
    old_width = _reporter.width
    _reporter.width = width
    _reporter.divider(char)
    _reporter.width = old_width


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
    old_width = _reporter.width
    _reporter.width = width
    _reporter.section(title, content)
    _reporter.width = old_width


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
    _reporter.key_value(key, value, width, align)


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
    old_width = _reporter.width
    _reporter.width = width
    _reporter.metric_summary(metrics, title)
    _reporter.width = old_width


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
    _reporter.success(message, prefix)


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
    _reporter.warning(message, prefix)


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
    _reporter.error(message, prefix)


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
    _reporter.info(message, prefix)


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
    _reporter.table_row(columns, widths, separator)


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
    _reporter.table(data, headers, widths)


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
    _reporter.clear_and_print(message, wait)


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
    _reporter.progress(current, total, prefix, suffix, length)
