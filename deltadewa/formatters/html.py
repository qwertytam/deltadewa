"""
HTML Badge and Metric Formatters for Dashboard Widgets

This module provides HTML formatting functions for dashboard widgets:
- Badge creation with flexible styling
- Metric formatting with automatic coloring

These formatters are designed for use in Jupyter notebooks with HTML display.
"""

from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.formatters.values import (format_currency, format_number,
                                         format_percentage)


def format_html_badge(
    label: str,
    value: str,
    color: str = "neutral",
    text_color: str = "white",
    size: str = "normal",
) -> str:
    """
    Create an HTML badge for dashboard display.

    Args:
        label: Badge label text
        value: Badge value text
        color: Background color (can be 'neutral', 'positive', 'negative',
               'orange', or a hex color code)
        text_color: Text color (default: 'white')
        size: Badge size ('normal' or 'large')

    Returns:
        HTML string for the badge
    """
    # Map color names to hex codes
    color_map = {
        "neutral": DEFAULT_PALETTE.medium_grey,
        "positive": DEFAULT_PALETTE.positive,
        "negative": DEFAULT_PALETTE.negative,
        "orange": DEFAULT_PALETTE.orange,
    }

    bg_color = color_map.get(color, color)

    # Size settings
    if size == "large":
        padding = "8px 12px"
        label_size = "11px"
        value_size = "16px"
        min_width = "120px"
    else:
        padding = "6px 10px"
        label_size = "10px"
        value_size = "14px"
        min_width = "100px"

    return (
        f'<div style="display:inline-block; background-color:{bg_color}; '
        f"color:{text_color}; padding:{padding}; margin:5px; "
        f'border-radius:5px; font-weight:bold; min-width:{min_width};">'
        f'<div style="font-size:{label_size}; opacity:0.9;">{label}</div>'
        f'<div style="font-size:{value_size};">{value}</div>'
        f"</div>"
    )


def format_html_metric(
    name: str,
    value: float,
    format_type: str = "number",  # "number", "currency", "percentage"
    is_cost: bool = False,
    is_neutral: bool = False,
) -> str:
    """
    Format a metric as colored HTML badge (consolidates _format_greek from widgets).

    Args:
        name: Metric name
        value: Metric value
        format_type: Type of formatting ("number", "currency", "percentage")
        is_cost: Whether this represents a cost (red) vs profit (green)
        is_neutral: Whether to use neutral color regardless of value

    Returns:
        HTML string with formatted badge
    """
    # Handle near-zero values
    # For percentages (in decimal form), use 0.0001 threshold (= 0.01%)
    # For currency and numbers, use 0.01 threshold
    if format_type == "percentage":
        threshold = 0.0001  # 0.01% in decimal form
    else:
        threshold = 0.01

    if abs(value) < threshold:
        if format_type == "percentage":
            value_str = "- %"
        elif format_type == "currency":
            value_str = "$ -"
        else:
            value_str = "-"
    else:
        # Delegate to existing formatters
        if format_type == "currency":
            value_str = format_currency(value, compact=True)
        elif format_type == "percentage":
            value_str = format_percentage(value, from_decimal=True)
        else:  # format_type == "number"
            value_str = format_number(value, compact=True)

    # Determine badge color
    # Logic:
    # - Costs are always shown in negative color (red) regardless of value sign
    #   because costs are semantically negative
    # - is_neutral flag overrides sign-based coloring (but not is_cost)
    # - Otherwise, color by sign (positive=green, negative=red, zero=neutral)
    if is_cost:
        color = "negative"
    elif is_neutral:
        color = "neutral"
    elif value < 0:
        color = "negative"
    elif value > 0:
        color = "positive"
    else:
        color = "neutral"

    return format_html_badge(
        name, value_str, color=color, text_color="white", size="large"
    )


__all__ = [
    "format_html_badge",
    "format_html_metric",
]
