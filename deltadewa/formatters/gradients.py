"""Financial Color Gradients and Heatmap Styling.

This module provides color gradient functions for financial data visualization:
- Heatmap styling for DataFrames
- Traffic light coloring based on thresholds
- Diverging color parameter calculation
- Unified financial gradient application
- Matplotlib norm and colormap generation

These functions are self-contained with no dependencies on other formatter submodules.
"""

# TODO: Linter
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm

from deltadewa.colours import DEFAULT_PALETTE

if TYPE_CHECKING:
    from pandas.io.formats.style import Styler


def create_heatmap_style(
    df: pd.DataFrame,
    cmap: str = "RdYlGn",
    format_str: str = "{:,.2f}",
    center_value: float | None = None,  # pylint: disable=unused-argument
    vmin: float | None = None,
    vmax: float | None = None,
) -> Styler:
    """Create a heatmap-style DataFrame (for pivot tables, correlation matrices).

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
        cmap=cmap,
        axis=None,
        vmin=vmin,
        vmax=vmax,
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
            },
        ],
        overwrite=False,
    )

    return styled


def apply_traffic_light_colors(
    styler: Styler,
    column: str,
    thresholds: dict[str, float],
    reverse: bool = False,
) -> Styler:
    """Apply traffic light colors (red/yellow/green) based on thresholds.

    Args:
        styler: Pandas Styler object
        column: Column to apply colors to
        thresholds: dict with 'red', 'yellow', 'green' threshold values
        reverse: If True, reverse the color logic (red for high values)

    Returns:
        Styler with traffic light colors

    Example:
        thresholds = {'red': -1000, 'yellow': 0, 'green': 1000}
        apply_traffic_light_colors(styler, 'pnl', thresholds)

    """

    def color_traffic_light(val) -> float | str:  # noqa: ANN001
        try:
            val = float(val)
        except (ValueError, TypeError):
            return ""

        if reverse:
            if val >= thresholds["green"]:
                return f"background-color: {DEFAULT_PALETTE.negative_faded}"  # light red
            elif val >= thresholds["yellow"]:
                return f"background-color: {DEFAULT_PALETTE.yellow_faded}"  # light yellow
            else:
                return f"background-color: {DEFAULT_PALETTE.positive_faded}"  # light green
        else:
            if val <= thresholds["red"]:
                return f"background-color: {DEFAULT_PALETTE.negative_faded}"  # light red
            elif val <= thresholds["yellow"]:
                return f"background-color: {DEFAULT_PALETTE.yellow_faded}"  # light yellow
            else:
                return f"background-color: {DEFAULT_PALETTE.positive_faded}"  # light green

    return styler.apply(
        lambda col: col.map(color_traffic_light),
        subset=[column],
    )


def get_diverging_color_params(
    values: np.ndarray,
    center: float = 0.0,
) -> tuple[float, float]:
    """Calculate vmin and vmax for a diverging colormap centered at a value.

    This ensures the colormap is symmetric around the center value,
    so that the center color (white) appears exactly at the center value.

    Args:
        values: Array of numeric values
        center: Value to center the colormap at (default: 0.0)

    Returns:
        tuple of (vmin, vmax) for use with colormaps

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
    """Apply consistent financial diverging gradient to entire 2D DataFrame.

    Args:
        styler: Pandas Styler object
        center: Value to center the colormap at (default: 0.0)
        cmap: Colormap name (default: 'RdYlGn')

    Returns:
        Styled DataFrame with consistent diverging gradient

    """
    df = cast(Any, styler).data
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
    """Get matplotlib Normalize and colormap for consistent financial visualization.

    Args:
        values: Array of values to display
        center: Value to center the colormap at (default: 0.0)
        cmap_name: Colormap name (default: 'RdYlGn')

    Returns:
        tuple of (norm, cmap) for use with matplotlib

    """
    vmin, vmax = get_diverging_color_params(values, center)

    # Use TwoSlopeNorm to ensure center is exactly at the middle color
    norm = TwoSlopeNorm(vmin=vmin, vcenter=center, vmax=vmax)
    cmap = plt.get_cmap(cmap_name)

    return norm, cmap


__all__ = [
    "apply_financial_gradient_2d",
    "apply_traffic_light_colors",
    "create_heatmap_style",
    "get_diverging_color_params",
    "get_matplotlib_norm_and_cmap",
]
