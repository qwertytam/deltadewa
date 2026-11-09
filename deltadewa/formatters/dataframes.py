"""DataFrame Styling and Formatting Utilities for Options Dashboard.

This module provides styling and formatting functions for DataFrames:
- Core display preparation and styling helpers
- A risk-metrics formatter
- Conditional formatting (negative values, max/min highlighting)
- Export and display utilities

``create_diverging_style`` and ``apply_table_preset`` were retired with the
Jupyter layer in #279 — both were reached only from that layer.
``apply_gradient_style``, ``format_portfolio_dataframe``,
``format_greeks_dataframe``, ``format_scenario_dataframe`` and
``format_pivot_table`` followed in #312: each coloured a Styler with
``background_gradient``, which imports matplotlib when called. None had a
product caller or a test, and matplotlib is a dev-only dependency that was
never in the production image, so they could not have run there.

All functions work with pandas DataFrames and Styler objects.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Hashable, Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    cast,
)

import pandas as pd

from deltadewa.colours import DEFAULT_PALETTE

if TYPE_CHECKING:
    from pandas.io.formats.style import Styler

# Try to import IPython display for notebook environments
try:
    from IPython.display import display

    IPYTHON_AVAILABLE = True
except ImportError:
    IPYTHON_AVAILABLE = False


# ============================================================================
# Core DataFrame Styling Functions
# ============================================================================


def prepare_dataframe_display(
    df: pd.DataFrame,
    title_case: bool = True,
    start_index: int | None = 1,
    sort_by: list[str] | None = None,
    index_name: str | None = None,
) -> pd.DataFrame:
    """Prepare a DataFrame for display with consistent formatting.

    Args:
        df: Input DataFrame
        title_case: Convert column names to title case
        start_index: Starting index number (1-based by default) or None to
        preserve original index
        index_name: Optional name for the index
        sort_by: Optional list of columns to sort by

    Returns:
        Formatted DataFrame (copy)

    """
    df_display = df.copy()

    # Format column names
    if title_case:
        df_display = df_display.rename(
            columns=lambda s: s.replace("_", " ").title(),
        )

    # Reset index with custom numbering
    if start_index is not None:
        df_display.index = pd.RangeIndex(
            start=start_index,
            stop=start_index + len(df_display),
        )

    if index_name:
        df_display.index.name = index_name

    # Sort by specified columns
    if sort_by:
        sort_by_display = [
            col.replace("_", " ").title() if title_case else col
            for col in sort_by
        ]
        df_display = df_display.sort_values(by=sort_by_display)

    return df_display


def apply_format_dict(
    styler: Styler,
    format_dict: Mapping[Any, str | Callable[[object], str]] | None,
) -> Styler:
    """Apply formatting to columns based on format dictionary.

    Args:
        styler: Pandas Styler object
        format_dict: Mapping of column names to format strings or callables
        compatible with pandas.Styler.format (values: str | Callable[[object],
        str] | None)

    Returns:
        Styler with formatting applied

    """
    # If no format dict provided, call Styler.format with default formatter
    if not format_dict:
        return styler.format(na_rep="-")

    # Ensure we pass a concrete dict to Styler.format to satisfy type checkers
    return styler.format(dict(format_dict), na_rep="-")


# ============================================================================
# High-Level Formatting Functions
# ============================================================================


def format_risk_metrics_dataframe(
    df: pd.DataFrame,
    currency_columns: list[str] | None = None,
    percentage_columns: list[str] | None = None,
    title_case: bool = True,
    sort_by: list[str] | None = None,
) -> Styler:
    """Format risk metrics DataFrame with appropriate numeric formatting.

    Args:
        df: Risk metrics DataFrame
        currency_columns: Columns to format as currency
        percentage_columns: Columns to format as percentages
        title_case: Convert column names to title case
        sort_by: Optional list of columns to sort by

    Returns:
        Styled DataFrame

    """
    df_display = prepare_dataframe_display(
        df,
        title_case,
        sort_by=sort_by,
        start_index=None,
    )

    # Build format dictionary
    fmt = {}

    if currency_columns:
        for col in currency_columns:
            col_display = col.replace("_", " ").title() if title_case else col
            if col_display in df_display.columns:
                fmt[col_display] = "${:,.2f}"

    if percentage_columns:
        for col in percentage_columns:
            col_display = col.replace("_", " ").title() if title_case else col
            if col_display in df_display.columns:
                fmt[col_display] = "{:.2%}"

    styled = apply_format_dict(df_display.style, fmt)
    return styled


# ============================================================================
# Conditional Formatting Helpers
# ============================================================================


def highlight_negative_values(
    styler: Styler,
    columns: list[str] | None = None,
    color: str = DEFAULT_PALETTE.negative_faded,
) -> Styler:
    """Highlight negative values in specified columns.

    Args:
        styler: Pandas Styler object
        columns: Columns to check (None = all numeric columns)
        color: Background color for negative values

    Returns:
        Styler with highlighted negative values

    """

    def highlight_neg(val: object) -> str:
        try:
            return f"background-color: {color}" if float(val) < 0 else ""  # type: ignore[arg-type]
        except (ValueError, TypeError):
            return ""

    if columns:
        return styler.apply(
            lambda col: col.map(highlight_neg),
            subset=cast("list[Hashable]", columns),
        )
    return styler.apply(lambda col: col.map(highlight_neg))


def highlight_max_min(
    styler: Styler,
    column: str,
    max_color: str = DEFAULT_PALETTE.positive_faded,
    min_color: str = DEFAULT_PALETTE.negative_faded,
) -> Styler:
    """Highlight maximum and minimum values in a column.

    Args:
        styler: Pandas Styler object
        column: Column to analyze
        max_color: Color for maximum value
        min_color: Color for minimum value

    Returns:
        Styler with highlighted max/min

    """
    return styler.apply(
        lambda col: [
            (
                f"background-color: {max_color}"
                if v == col.max()
                else f"background-color: {min_color}"
                if v == col.min()
                else ""
            )
            for v in col
        ],
        subset=[column],
    )


# ============================================================================
# Export/Display Utilities
# ============================================================================


def to_excel_styled(
    df: pd.DataFrame,
    filepath: str,
    styler: Styler | None = None,
    sheet_name: str = "Sheet1",
) -> None:
    """Export DataFrame to Excel with styling preserved (when possible).

    Args:
        df: DataFrame to export
        filepath: Output file path
        styler: Optional Styler object (some styles may not transfer to Excel)
        sheet_name: Excel sheet name

    Note:
        Not all Pandas styling is preserved in Excel. Background colors and
        some basic formatting will transfer, but complex styles may not.

    """
    try:
        if styler is not None:
            styler.to_excel(filepath, sheet_name=sheet_name, engine="openpyxl")
        else:
            df.to_excel(filepath, sheet_name=sheet_name, engine="openpyxl")
        print(f"✓ DataFrame exported to {filepath}")
    except Exception as e:  # pylint: disable=broad-except
        warnings.warn(f"Error exporting to Excel: {e}", stacklevel=1)
        # Fallback to CSV
        csv_path = filepath.replace(".xlsx", ".csv")
        df.to_csv(csv_path)
        print(f"ℹ️  Exported to CSV instead: {csv_path}")  # ruff: ignore[ambiguous-unicode-character-string]


def display_dataframe_summary(df: pd.DataFrame, max_rows: int = 10) -> None:
    """Display a summary of a DataFrame (first/last rows, shape, dtypes).

    Args:
        df: DataFrame to summarize
        max_rows: Maximum number of rows to display from each end

    """
    print(f"\nDataFrame Shape: {df.shape[0]} rows x {df.shape[1]} columns")
    print("\nColumn Data Types:")
    print(df.dtypes)

    if len(df) > max_rows * 2:
        print(f"\nFirst {max_rows} rows:")
        if IPYTHON_AVAILABLE:
            display(df.head(max_rows))
        else:
            print(df.head(max_rows))

        print(f"\nLast {max_rows} rows:")
        if IPYTHON_AVAILABLE:
            display(df.tail(max_rows))
        else:
            print(df.tail(max_rows))
    else:
        print("\nFull DataFrame:")
        if IPYTHON_AVAILABLE:
            display(df)
        else:
            print(df)


__all__ = [
    "apply_format_dict",
    "display_dataframe_summary",
    "format_risk_metrics_dataframe",
    "highlight_max_min",
    "highlight_negative_values",
    "prepare_dataframe_display",
    "to_excel_styled",
]
