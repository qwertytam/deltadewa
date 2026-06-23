"""DataFrame Styling and Formatting Utilities for Options Dashboard.

This module provides consistent styling and formatting functions for DataFrames:
- Core display preparation and styling helpers
- High-level formatters for portfolio, Greeks, and scenario analysis
- Pivot table and diverging style creation
- Conditional formatting (negative values, max/min highlighting)
- Table styling presets
- Export and display utilities

All functions work with pandas DataFrames and Styler objects.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    cast,
)

import pandas as pd

from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.formatters.values import format_currency_for_df

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


def apply_gradient_style(
    styler: Styler,
    columns: str | list[str],
    cmap: str = "RdYlGn",
    vmin: float | None = None,
    vmax: float | None = None,
    axis: Literal["index", "columns", 0, 1] | None = None,
) -> Styler:
    """Apply color gradient to specified columns.

    Args:
        styler: Pandas Styler object
        columns: Column name(s) to apply gradient to
        cmap: Colormap name (default: 'RdYlGn' for red-yellow-green)
        vmin: Minimum value for color scale
        vmax: Maximum value for color scale
        axis: Axis along which to apply gradient (one of 'index', 'columns', 0,
        1, or None)

    Returns:
        Styler with gradient applied

    """
    if isinstance(columns, str):
        columns = [columns]

    return styler.background_gradient(
        subset=columns,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        axis=axis,
    )


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


def format_portfolio_dataframe(
    df: pd.DataFrame,
    gradient_column: str = "position_value",
    start_index: int = 1,
    title_case: bool = True,
    cmap: str = "RdYlGn",
    include_greeks: bool = True,
    sort_by: list[str] | None = None,
) -> Styler:
    """Format portfolio positions DataFrame with standard styling.

    Args:
        df: Portfolio DataFrame (from portfolio.to_dataframe())
        gradient_column: Column to apply color gradient to
        start_index: Starting index number
        title_case: Convert column names to title case
        cmap: Colormap for gradient
        include_greeks: Include Greek columns in formatting
        sort_by: Optional list of columns to sort by

    Returns:
        Styled DataFrame ready for display

    """
    # Prepare display DataFrame
    df_display = prepare_dataframe_display(
        df=df,
        title_case=title_case,
        start_index=start_index,
        sort_by=sort_by,
    )

    # Define format dictionary
    fmt = {
        "Strike" if title_case else "strike": "{:,.2f}",
        "Quantity" if title_case else "quantity": "{:.0f}",
        "Price" if title_case else "price": "${:,.2f}",
        "Position Value" if title_case else "position_value": "${:,.2f}",
    }

    if include_greeks:
        greek_fmt = {
            "Delta" if title_case else "delta": "{:,.4f}",
            "Position Delta" if title_case else "position_delta": "{:,.2f}",
            "Gamma" if title_case else "gamma": "{:,.6f}",
            "Position Gamma" if title_case else "position_gamma": "{:,.4f}",
            "Vega" if title_case else "vega": "{:,.4f}",
            "Position Vega" if title_case else "position_vega": "{:,.2f}",
            "Theta" if title_case else "theta": "{:,.4f}",
            "Position Theta" if title_case else "position_theta": "{:,.2f}",
            "Rho" if title_case else "rho": "{:,.4f}",
            "Position Rho" if title_case else "position_rho": "{:,.2f}",
        }
        fmt.update(greek_fmt)

    # Create styled DataFrame (use apply_format_dict to satisfy typing)
    styled = apply_format_dict(df_display.style, fmt)

    # Apply gradient if column exists
    gradient_col_display = (
        gradient_column.replace("_", " ").title()
        if title_case
        else gradient_column
    )
    if gradient_col_display in df_display.columns:
        styled = apply_gradient_style(styled, gradient_col_display, cmap=cmap)

    return styled


def format_greeks_dataframe(
    df: pd.DataFrame,
    metric: str = "delta",
    title_case: bool = True,
    cmap: str = "RdBu_r",
    precision: int = 4,
    sort_by: list[str] | None = None,
) -> Styler:
    """Format Greeks analysis DataFrame (e.g., delta by strike/maturity).

    Args:
        df: Greeks DataFrame
        metric: Which Greek is being displayed (affects color scheme)
        title_case: Convert column names to title case
        cmap: Colormap for gradient
        precision: Decimal precision for display
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

    # Determine format based on metric
    if metric.lower() in ["delta", "gamma", "vega", "theta", "rho"]:
        fmt_str = f"{{:,.{precision}f}}"
    else:
        fmt_str = "{:,.2f}"

    # Apply styling
    styled = df_display.style.background_gradient(cmap=cmap, axis=None)
    styled = styled.format(fmt_str, na_rep="-")

    return styled


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


def format_scenario_dataframe(
    df: pd.DataFrame,
    metric_column: str = "portfolio_value",
    title_case: bool = True,
    cmap: str = "RdYlGn",
    sort_by: list[str] | None = None,
) -> Styler:
    """Format scenario analysis DataFrame with color gradients.

    Args:
        df: Scenario analysis DataFrame
        metric_column: Column to highlight with gradient
        title_case: Convert column names to title case
        cmap: Colormap for gradient
        sort_by: Optional list of columns to sort by

    Returns:
        Styled DataFrame

    """
    df_display = prepare_dataframe_display(
        df,
        title_case,
        sort_by=sort_by,
        start_index=1,
    )

    # Format dictionary
    fmt = {
        "Spot Price" if title_case else "spot_price": "${:,.2f}",
        "Volatility" if title_case else "volatility": "{:.2%}",
        "Portfolio Value" if title_case else "portfolio_value": "${:,.2f}",
        "Portfolio Pnl" if title_case else "portfolio_pnl": "${:,.2f}",
        "Net Delta" if title_case else "net_delta": "{:,.2f}",
        "Total Gamma" if title_case else "total_gamma": "{:,.4f}",
        "Total Vega" if title_case else "total_vega": "{:,.2f}",
    }

    # Use typed helper to apply format mappings to avoid mypy typing issues
    styled = apply_format_dict(df_display.style, fmt)

    # Apply gradient to metric column
    metric_col_display = (
        metric_column.replace("_", " ").title() if title_case else metric_column
    )
    if metric_col_display in df_display.columns:
        styled = apply_gradient_style(styled, metric_col_display, cmap=cmap)

    return styled


# ============================================================================
# Pivot Table Formatting
# ============================================================================


def create_diverging_style(
    df: pd.DataFrame,
    value_columns: list[str],
    cmap: str = "RdYlGn",
    title_case: bool = True,
    currency_columns: list[str] | None = None,
) -> Styler:
    """Create DataFrame style with diverging colormap and consistent formatting.

    This function creates a styled DataFrame with a diverging color scale
    centered at zero (negative=red, zero=white, positive=green) and consistent
    currency formatting across all tables.

    Args:
        df: DataFrame to style
        value_columns: Columns to apply diverging color scale
        cmap: Colormap (default: 'RdYlGn' for red-yellow-green diverging)
        title_case: Convert columns to title case
        currency_columns: Columns to format as currency (default: value_columns)

    Returns:
        Styled DataFrame with diverging colors and currency formatting

    """
    df_styled = df.copy()

    # Title case columns if requested
    if title_case:
        # Ensure assignment uses an Index[str] to satisfy type checkers (avoid
        # assigning list[str] to Index)
        df_styled.columns = pd.Index(
            [str(c).replace("_", " ").title() for c in df_styled.columns],
        )
        value_columns = [c.replace("_", " ").title() for c in value_columns]
        if currency_columns:
            currency_columns = [
                c.replace("_", " ").title() for c in currency_columns
            ]

    if currency_columns is None:
        currency_columns = value_columns

    # Create styler
    styler = df_styled.style

    # Apply diverging colormap to each value column
    for col in value_columns:
        if col not in df_styled.columns:
            continue

        col_data = df_styled[col]
        vmin = col_data.min()
        vmax = col_data.max()

        # Skip if all same value
        if vmin == vmax:
            continue

        # Create diverging norm with zero at center
        # This ensures: negative=red, zero=white, positive=green
        abs_max = max(abs(vmin), abs(vmax))
        styler = styler.background_gradient(
            subset=[col],
            cmap=cmap,
            vmin=-abs_max,
            vmax=abs_max,
            axis=0,
        )

    # Format currency columns with consistent formatting
    format_dict: dict[Any, str | Callable[[object], str]] = {}
    for col in currency_columns:
        if col in df_styled.columns:
            format_dict[col] = format_currency_for_df

    if format_dict:
        styler = styler.format(
            cast(
                "dict[Any, str | Callable[[object], str] | None]",
                format_dict,
            ),
            na_rep="-",
        )

    return styler


def format_pivot_table(
    pivot: pd.DataFrame,
    format_str: str = "{:,.2f}",
    cmap: str = "RdYlGn",
    highlight_zeros: bool = True,  # pylint: disable=unused-argument  # noqa: ARG001
) -> Styler:
    """Format pivot table with consistent styling.

    Args:
        pivot: Pivot table DataFrame
        format_str: Format string for cell values
        cmap: Colormap for background gradient
        highlight_zeros: Whether to highlight zero/near-zero values

    Returns:
        Styled pivot table

    """
    styled = pivot.style.background_gradient(cmap=cmap, axis=None)
    styled = styled.format(format_str, na_rep="-")

    # Add borders for better readability (use set_table_styles to avoid typing
    # issues)
    styled = styled.set_table_styles(
        [
            {
                "selector": "td",
                "props": [
                    ("border", "1px solid #ddd"),
                    ("padding", "5px"),
                    ("text-align", "center"),
                ],
            },
        ],
        overwrite=False,
    )

    # Style the headers
    styled = styled.set_table_styles(
        [
            {
                "selector": "th",
                "props": [
                    ("background-color", DEFAULT_PALETTE.very_light_grey),
                    ("font-weight", "bold"),
                    ("text-align", "center"),
                    ("border", "1px solid #ddd"),
                ],
            },
            {"selector": "td", "props": [("text-align", "right")]},
        ],
    )

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

    def highlight_neg(val) -> str:  # noqa: ANN001
        try:
            return f"background-color: {color}" if float(val) < 0 else ""
        except (ValueError, TypeError):
            return ""

    if columns:
        return styler.apply(lambda col: col.map(highlight_neg), subset=columns)
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
                else f"background-color: {min_color}" if v == col.min() else ""
            )
            for v in col
        ],
        subset=[column],
    )


# ============================================================================
# Table Styling Presets
# ============================================================================


def apply_table_preset(styler: Styler, preset: str = "default") -> Styler:
    """Apply predefined table styling presets.

    Args:
        styler: Pandas Styler object
        preset: Preset name ('default', 'minimal', 'fancy', 'compact')

    Returns:
        Styler with preset applied

    """
    if preset == "minimal":
        styles = [
            {"selector": "table", "props": [("border-collapse", "collapse")]},
            {
                "selector": "th",
                "props": [
                    ("border-bottom", "2px solid #000"),
                    ("text-align", "left"),
                    ("padding", "8px"),
                ],
            },
            {
                "selector": "td",
                "props": [
                    ("border-bottom", "1px solid #ddd"),
                    ("padding", "8px"),
                ],
            },
        ]
    elif preset == "fancy":
        styles = [
            {
                "selector": "table",
                "props": [
                    ("border-collapse", "collapse"),
                    ("box-shadow", "0 2px 4px rgba(0,0,0,0.1)"),
                ],
            },
            {
                "selector": "th",
                "props": [
                    ("background-color", DEFAULT_PALETTE.dark_background),
                    ("color", DEFAULT_PALETTE.white),
                    ("padding", "12px"),
                    ("text-align", "left"),
                    ("font-weight", "bold"),
                ],
            },
            {
                "selector": "tr:nth-child(even)",
                "props": [
                    ("background-color", DEFAULT_PALETTE.very_light_grey),
                ],
            },
            {
                "selector": "td",
                "props": [
                    ("padding", "10px"),
                    ("border-bottom", "1px solid #ddd"),
                ],
            },
        ]
    elif preset == "compact":
        styles = [
            {"selector": "table", "props": [("font-size", "12px")]},
            {"selector": "th, td", "props": [("padding", "4px")]},
        ]
    else:  # default
        styles = [
            {"selector": "table", "props": [("border-collapse", "collapse")]},
            {
                "selector": "th",
                "props": [
                    ("background-color", DEFAULT_PALETTE.very_light_grey),
                    ("padding", "8px"),
                    ("text-align", "left"),
                    ("border", "1px solid #ddd"),
                ],
            },
            {
                "selector": "td",
                "props": [("padding", "8px"), ("border", "1px solid #ddd")],
            },
        ]

    return styler.set_table_styles(styles)  # type: ignore[arg-type]


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
        print(f"ℹ️  Exported to CSV instead: {csv_path}")  # noqa: RUF001


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
    "apply_gradient_style",
    "apply_table_preset",
    "create_diverging_style",
    "display_dataframe_summary",
    "format_greeks_dataframe",
    "format_pivot_table",
    "format_portfolio_dataframe",
    "format_risk_metrics_dataframe",
    "format_scenario_dataframe",
    "highlight_max_min",
    "highlight_negative_values",
    "prepare_dataframe_display",
    "to_excel_styled",
]
