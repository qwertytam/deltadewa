"""
DataFrame Styling and Formatting Utilities for Options Dashboard

This module provides consistent styling and formatting functions for DataFrames
used throughout the options dashboard. It standardizes:
- DataFrame display formatting (column names, indices)
- Numeric formatting (currency, percentages, decimals)
- Conditional formatting (color gradients, heatmaps)
- Table styling (borders, headers, alignment)

Usage:
    from deltadewa.formatters import (
        format_portfolio_dataframe,
        format_greeks_dataframe,
        format_risk_metrics_dataframe,
        create_heatmap_style,
        apply_traffic_light_colors
    )

    styled_df = format_portfolio_dataframe(df)
    display(styled_df)

Author: DeltaDewa Team
Date: 2026-01-12
"""

from __future__ import annotations

from typing import (
    Any,
    Mapping,
    Dict,
    List,
    Optional,
    Union,
    Callable,
    Literal,
    TYPE_CHECKING,
    cast,
)
import warnings
import pandas as pd
import numpy as np

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
    start_index: Optional[int] = 1,
    sort_by: Optional[List[str]] = None,
    index_name: Optional[str] = None,
) -> pd.DataFrame:
    """
    Prepare a DataFrame for display with consistent formatting.

    Args:
        df: Input DataFrame
        title_case: Convert column names to title case
        start_index: Starting index number (1-based by default) or None to preserve original index
        index_name: Optional name for the index
        sort_by: Optional list of columns to sort by

    Returns:
        Formatted DataFrame (copy)
    """
    df_display = df.copy()

    # Format column names
    if title_case:
        df_display = df_display.rename(
            columns=lambda s: s.replace("_", " ").title()
        )

    # Reset index with custom numbering
    if start_index is not None:
        df_display.index = pd.RangeIndex(
            start=start_index, stop=start_index + len(df_display)
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
    columns: Union[str, List[str]],
    cmap: str = "RdYlGn",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    axis: Optional[Literal["index", "columns", 0, 1]] = None,
) -> Styler:
    """
    Apply color gradient to specified columns.

    Args:
        styler: Pandas Styler object
        columns: Column name(s) to apply gradient to
        cmap: Colormap name (default: 'RdYlGn' for red-yellow-green)
        vmin: Minimum value for color scale
        vmax: Maximum value for color scale
        axis: Axis along which to apply gradient (one of 'index', 'columns', 0, 1, or None)

    Returns:
        Styler with gradient applied
    """
    if isinstance(columns, str):
        columns = [columns]

    return styler.background_gradient(
        subset=columns, cmap=cmap, vmin=vmin, vmax=vmax, axis=axis
    )


def apply_format_dict(
    styler: Styler,
    format_dict: Mapping[Any, Optional[Union[str, Callable[[object], str]]]],
) -> Styler:
    """
    Apply formatting to columns based on format dictionary.

    Args:
        styler: Pandas Styler object
        format_dict: Mapping of column names to format strings or callables compatible with
                     pandas.Styler.format (values: str | Callable[[object], str] | None)

    Returns:
        Styler with formatting applied
    """
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
    sort_by: Optional[list[str]] = None,
) -> Styler:
    """
    Format portfolio positions DataFrame with standard styling.

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
        df=df, title_case=title_case, start_index=start_index, sort_by=sort_by
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
    sort_by: Optional[list[str]] = None,
) -> Styler:
    """
    Format Greeks analysis DataFrame (e.g., delta by strike/maturity).

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
        df, title_case, sort_by=sort_by, start_index=None
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
    currency_columns: Optional[List[str]] = None,
    percentage_columns: Optional[List[str]] = None,
    title_case: bool = True,
    sort_by: Optional[list[str]] = None,
) -> Styler:
    """
    Format risk metrics DataFrame with appropriate numeric formatting.

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
        df, title_case, sort_by=sort_by, start_index=None
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
    sort_by: Optional[list[str]] = None,
) -> Styler:
    """
    Format scenario analysis DataFrame with color gradients.

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
        df, title_case, sort_by=sort_by, start_index=1
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
# Heatmap Styling Functions
# ============================================================================


def create_heatmap_style(
    df: pd.DataFrame,
    cmap: str = "RdYlGn",
    format_str: str = "{:,.2f}",
    center_value: Optional[float] = None,  # pylint: disable=unused-argument
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
) -> Styler:
    """
    Create a heatmap-style DataFrame (for pivot tables, correlation matrices).

    Args:
        df: Input DataFrame
        cmap: Colormap name
        format_str: Format string for values
        center_value: Value to center colormap at (e.g., 0 for diverging colors)
        vmin: Minimum value for color scale
        vmax: Maximum value for color scale

    Returns:
        Styled DataFrame with heatmap coloring
    """
    styled = df.style.background_gradient(
        cmap=cmap, axis=None, vmin=vmin, vmax=vmax
    )

    styled = styled.format(format_str, na_rep="-")

    # Apply borders and alignment for readability using table styles
    styled = styled.set_table_styles(
        [
            {
                "selector": "td",
                "props": [
                    ("border", "1px solid #ddd"),
                    ("text-align", "right"),
                ],
            }
        ],
        overwrite=False,
    )

    return styled


def apply_traffic_light_colors(
    styler: Styler,
    column: str,
    thresholds: Dict[str, float],
    reverse: bool = False,
) -> Styler:
    """
    Apply traffic light colors (red/yellow/green) based on thresholds.

    Args:
        styler: Pandas Styler object
        column: Column to apply colors to
        thresholds: Dict with 'red', 'yellow', 'green' threshold values
        reverse: If True, reverse the color logic (red for high values)

    Returns:
        Styler with traffic light colors

    Example:
        thresholds = {'red': -1000, 'yellow': 0, 'green': 1000}
        apply_traffic_light_colors(styler, 'pnl', thresholds)
    """

    def color_traffic_light(val):
        try:
            val = float(val)
        except (ValueError, TypeError):
            return ""

        if reverse:
            if val >= thresholds["green"]:
                return "background-color: #ffcccc"  # light red
            elif val >= thresholds["yellow"]:
                return "background-color: #ffffcc"  # light yellow
            else:
                return "background-color: #ccffcc"  # light green
        else:
            if val <= thresholds["red"]:
                return "background-color: #ffcccc"  # light red
            elif val <= thresholds["yellow"]:
                return "background-color: #ffffcc"  # light yellow
            else:
                return "background-color: #ccffcc"  # light green

    return styler.apply(
        lambda col: col.map(color_traffic_light), subset=[column]
    )


# ============================================================================
# Pivot Table Formatting
# ============================================================================


def create_diverging_style(
    df: pd.DataFrame,
    value_columns: List[str],
    cmap: str = "RdYlGn",
    title_case: bool = True,
    currency_columns: Optional[List[str]] = None,
) -> Styler:
    """
    Create DataFrame style with diverging colormap and consistent formatting.

    This function creates a styled DataFrame with a diverging color scale centered
    at zero (negative=red, zero=white, positive=green) and consistent currency
    formatting across all tables.

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
            [str(c).replace("_", " ").title() for c in df_styled.columns]
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
            subset=[col], cmap=cmap, vmin=-abs_max, vmax=abs_max, axis=0
        )

    # Format currency columns with consistent formatting
    def format_currency_consistent(value: object) -> str:
        """Format currency consistently: -$1,234.56"""
        if pd.isna(cast(Any, value)):
            return "-"
        try:
            num = float(cast(Any, value))
        except (TypeError, ValueError):
            return "-" if value is None else str(value)
        if num < 0:
            return f"-${abs(num):,.2f}"
        return f"${num:,.2f}"

    format_dict: Dict[Any, Optional[Union[str, Callable[[object], str]]]] = {}
    for col in currency_columns:
        if col in df_styled.columns:
            format_dict[col] = format_currency_consistent

    if format_dict:
        styler = styler.format(format_dict, na_rep="-")

    return styler


def format_pivot_table(
    pivot: pd.DataFrame,
    format_str: str = "{:,.2f}",
    cmap: str = "RdYlGn",
    highlight_zeros: bool = True,  # pylint: disable=unused-argument
) -> Styler:
    """
    Format pivot table with consistent styling.

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

    # Add borders for better readability (use set_table_styles to avoid typing issues)
    styled = styled.set_table_styles(
        [
            {
                "selector": "td",
                "props": [
                    ("border", "1px solid #ddd"),
                    ("padding", "5px"),
                    ("text-align", "center"),
                ],
            }
        ],
        overwrite=False,
    )

    # Style the headers
    styled = styled.set_table_styles(
        [
            {
                "selector": "th",
                "props": [
                    ("background-color", "#f0f0f0"),
                    ("font-weight", "bold"),
                    ("text-align", "center"),
                    ("border", "1px solid #ddd"),
                ],
            },
            {"selector": "td", "props": [("text-align", "right")]},
        ]
    )

    return styled


# ============================================================================
# Conditional Formatting Helpers
# ============================================================================


def highlight_negative_values(
    styler: Styler,
    columns: Optional[List[str]] = None,
    color: str = "#ffcccc",
) -> Styler:
    """
    Highlight negative values in specified columns.

    Args:
        styler: Pandas Styler object
        columns: Columns to check (None = all numeric columns)
        color: Background color for negative values

    Returns:
        Styler with highlighted negative values
    """

    def highlight_neg(val):
        try:
            return f"background-color: {color}" if float(val) < 0 else ""
        except (ValueError, TypeError):
            return ""

    if columns:
        return styler.apply(lambda col: col.map(highlight_neg), subset=columns)
    else:
        return styler.apply(lambda col: col.map(highlight_neg))


def highlight_max_min(
    styler: Styler,
    column: str,
    max_color: str = "#ccffcc",
    min_color: str = "#ffcccc",
) -> Styler:
    """
    Highlight maximum and minimum values in a column.

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
    """
    Apply predefined table styling presets.

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
                    ("background-color", "#2c3e50"),
                    ("color", "white"),
                    ("padding", "12px"),
                    ("text-align", "left"),
                    ("font-weight", "bold"),
                ],
            },
            {
                "selector": "tr:nth-child(even)",
                "props": [("background-color", "#f9f9f9")],
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
                    ("background-color", "#f0f0f0"),
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
    styler: Optional[Styler] = None,
    sheet_name: str = "Sheet1",
):
    """
    Export DataFrame to Excel with styling preserved (when possible).

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
        warnings.warn(f"Error exporting to Excel: {e}")
        # Fallback to CSV
        csv_path = filepath.replace(".xlsx", ".csv")
        df.to_csv(csv_path)
        print(f"ℹ️  Exported to CSV instead: {csv_path}")


def display_dataframe_summary(df: pd.DataFrame, max_rows: int = 10):
    """
    Display a summary of a DataFrame (first/last rows, shape, dtypes).

    Args:
        df: DataFrame to summarize
        max_rows: Maximum number of rows to display from each end
    """
    print(f"\nDataFrame Shape: {df.shape[0]} rows × {df.shape[1]} columns")
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


# ============================================================================
# Unified Financial Color Gradient Functions
# ============================================================================


def get_diverging_color_params(
    values: np.ndarray,
    center: float = 0.0,
) -> tuple[float, float]:
    """
    Calculate vmin and vmax for a diverging colormap centered at a value.
    
    This ensures the colormap is symmetric around the center value,
    so that the center color (white) appears exactly at the center value.
    
    Args:
        values: Array of numeric values
        center: Value to center the colormap at (default: 0.0)
    
    Returns:
        Tuple of (vmin, vmax) for use with colormaps
    """
    # Flatten if needed and remove NaN
    flat_values = np.asarray(values).flatten()
    flat_values = flat_values[~np.isnan(flat_values)]
    
    if len(flat_values) == 0:
        return (-1.0, 1.0)
    
    data_min = float(np.min(flat_values))
    data_max = float(np.max(flat_values))
    
    # Calculate the maximum absolute distance from center
    max_abs = max(abs(data_min - center), abs(data_max - center))
    
    # Ensure we have some range
    if max_abs == 0:
        max_abs = 1.0
    
    return (center - max_abs, center + max_abs)


def apply_financial_gradient_2d(
    styler: Styler,
    center: float = 0.0,
    cmap: str = "RdYlGn",
) -> Styler:
    """
    Apply consistent financial diverging gradient to entire 2D DataFrame.
    
    Args:
        styler: Pandas Styler object
        center: Value to center the colormap at (default: 0.0)
        cmap: Colormap name (default: 'RdYlGn')
    
    Returns:
        Styled DataFrame with consistent diverging gradient
    """
    df = styler.data
    all_values = df.values
    vmin, vmax = get_diverging_color_params(all_values, center)
    
    return styler.background_gradient(
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        axis=None,
    )


def get_matplotlib_norm_and_cmap(
    values: np.ndarray,
    center: float = 0.0,
    cmap_name: str = "RdYlGn",
) -> tuple:
    """
    Get matplotlib Normalize and colormap for consistent financial visualization.
    
    Args:
        values: Array of values to display
        center: Value to center the colormap at (default: 0.0)
        cmap_name: Colormap name (default: 'RdYlGn')
    
    Returns:
        Tuple of (norm, cmap) for use with matplotlib
    """
    from matplotlib.colors import TwoSlopeNorm
    import matplotlib.pyplot as plt
    
    vmin, vmax = get_diverging_color_params(values, center)
    
    # Use TwoSlopeNorm to ensure center is exactly at the middle color
    norm = TwoSlopeNorm(vmin=vmin, vcenter=center, vmax=vmax)
    cmap = plt.get_cmap(cmap_name)
    
    return norm, cmap


# ============================================================================
# Module Metadata
# ============================================================================

__all__ = [
    # Core functions
    "prepare_dataframe_display",
    "apply_gradient_style",
    "apply_format_dict",
    # High-level formatters
    "format_portfolio_dataframe",
    "format_greeks_dataframe",
    "format_risk_metrics_dataframe",
    "format_scenario_dataframe",
    # Heatmap styling
    "create_heatmap_style",
    "create_diverging_style",
    "apply_traffic_light_colors",
    "format_pivot_table",
    # Conditional formatting
    "highlight_negative_values",
    "highlight_max_min",
    # Table presets
    "apply_table_preset",
    # Export/display
    "to_excel_styled",
    "display_dataframe_summary",
    # Unified financial gradient
    "get_diverging_color_params",
    "apply_financial_gradient_2d",
    "get_matplotlib_norm_and_cmap",
]
