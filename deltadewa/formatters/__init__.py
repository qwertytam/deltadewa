"""
Formatting utilities for the DeltaDewa options dashboard.

This package provides consistent styling and formatting functions for:
- Scalar value formatting (currency, percentages, numbers, Greeks)
- HTML badge/metric generation for dashboard widgets
- DataFrame display formatting and styling
- Financial color gradients and heatmaps

All functions are re-exported here for backward compatibility.
Import directly from deltadewa.formatters or from specific submodules.
"""

from deltadewa.formatters.values import (
    format_currency,
    format_currency_for_axis,
    format_currency_for_df,
    format_percentage,
    format_percentage_for_axis,
    format_number,
    format_number_auto_precision,
    format_greek_value,
    format_spot_with_pct,
    get_currency_axis_formatter,
    get_percentage_axis_formatter,
    get_spot_price_axis_formatter,
)
from deltadewa.formatters.html import (
    format_html_badge,
    format_html_metric,
)
from deltadewa.formatters.dataframes import (
    prepare_dataframe_display,
    apply_gradient_style,
    apply_format_dict,
    format_portfolio_dataframe,
    format_greeks_dataframe,
    format_risk_metrics_dataframe,
    format_scenario_dataframe,
    create_diverging_style,
    format_pivot_table,
    highlight_negative_values,
    highlight_max_min,
    apply_table_preset,
    to_excel_styled,
    display_dataframe_summary,
)
from deltadewa.formatters.gradients import (
    create_heatmap_style,
    apply_traffic_light_colors,
    get_diverging_color_params,
    apply_financial_gradient_2d,
    get_matplotlib_norm_and_cmap,
)

__all__ = [
    # Scalar value formatters
    "format_currency",
    "format_currency_for_axis",
    "format_currency_for_df",
    "format_percentage",
    "format_percentage_for_axis",
    "format_number",
    "format_number_auto_precision",
    "format_greek_value",
    "format_spot_with_pct",
    # Axis formatter factories
    "get_currency_axis_formatter",
    "get_percentage_axis_formatter",
    "get_spot_price_axis_formatter",
    # HTML formatters for widgets
    "format_html_badge",
    "format_html_metric",
    # Core DataFrame functions
    "prepare_dataframe_display",
    "apply_gradient_style",
    "apply_format_dict",
    # High-level DataFrame formatters
    "format_portfolio_dataframe",
    "format_greeks_dataframe",
    "format_risk_metrics_dataframe",
    "format_scenario_dataframe",
    # Heatmap and pivot styling
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
