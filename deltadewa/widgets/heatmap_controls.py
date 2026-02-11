"""Heatmap control widgets for portfolio analysis.

This module provides mixin classes for heatmap functionality
in the deltadewa dashboard.
"""

from typing import (
    TYPE_CHECKING,
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

    if TYPE_CHECKING:

        # pylint: disable=missing-function-docstring, unused-argument
        def create_metric_selector(
            self,
            metrics: Optional[List[Tuple[str, str]]] = None,
            description: str = "Metric:",
            default: str = "pnl",
        ) -> widgets.Dropdown: ...

        # pylint: disable=missing-function-docstring, unused-argument
        def create_price_range_slider(
            self,
            description: str = "Price Range (%):",
            default: float = 20.0,
            min_val: float = 5.0,
            max_val: float = 50.0,
            step: float = 5.0,
        ) -> widgets.FloatSlider: ...

        # pylint: disable=missing-function-docstring, unused-argument
        def create_date_selector(
            self,
            max_days: Optional[int] = None,
            description: str = "Valuation Date:",
            num_steps: int = 10,
        ) -> widgets.SelectionSlider: ...

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

        # pylint: disable=assignment-from-no-return
        price_range_slider = self.create_price_range_slider()

        display_format = widgets.Dropdown(
            options=[("Dollar ($)", "dollar"), ("Percentage (%)", "percent")],
            value="dollar",
            description="Display Format:",
            style={"description_width": "150px"},
        )

        # pylint: disable=assignment-from-no-return
        metric_selector = self.create_metric_selector(
            metrics=metrics, default="pnl"
        )

        # pylint: disable=assignment-from-no-return
        date_selector = self.create_date_selector()

        return {
            "price_range": price_range_slider,
            "display_format": display_format,
            "metric_selector": metric_selector,
            "date_selector": date_selector,
        }
