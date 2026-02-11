"""Heatmap control widgets for portfolio analysis.

This module provides mixin classes for heatmap functionality
in the deltadewa dashboard.
"""

from typing import (
    Optional,
    List,
    Tuple,
    Dict,
    Any,
)

import ipywidgets as widgets  # type: ignore[import-untyped]


class HeatmapControlsMixin:
    """
    Mixin providing heatmap control widgets.

    This mixin expects the host class to have:
    - self.create_metric_selector(): method to create metric selector
    - self.create_price_range_slider(): method to create price range slider
    - self.create_date_selector(): method to create date selector
    """

    # ==========================================================================
    # Heatmap Widgets
    # ==========================================================================

    def create_heatmap_controls(
        self, metrics: Optional[List[Tuple[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Create complete heatmap configuration controls.

        Args:
            metrics: List of (display_name, value) tuples for metric options

        Returns:
            Dictionary with heatmap control widgets
        """
        if metrics is None:
            metrics = [
                ("P&L", "pnl"),
                ("P&L (Options Only)", "pnl_options_only"),
                ("P&L % (Total)", "pnl_pct"),
                ("P&L % (Options Only)", "pnl_options_pct"),
                ("Net Delta", "net_delta"),
                ("Gamma", "gamma"),
                ("Theta (Daily)", "theta"),
                ("Vega", "vega"),
                ("Rho", "rho"),
            ]

        price_range_slider = self.create_price_range_slider()

        display_format = widgets.Dropdown(
            options=[("Dollar ($)", "dollar"), ("Percentage (%)", "percent")],
            value="dollar",
            description="Display Format:",
            style={"description_width": "150px"},
        )

        metric_selector = self.create_metric_selector(
            metrics=metrics, default="pnl"
        )

        date_selector = self.create_date_selector()

        return {
            "price_range": price_range_slider,
            "display_format": display_format,
            "metric_selector": metric_selector,
            "date_selector": date_selector,
        }
