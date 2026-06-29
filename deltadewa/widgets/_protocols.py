"""Structural protocols for mixin composition.

These are never instantiated at runtime. They exist solely to give static
analysers (mypy, pyright, pylint) an accurate picture of what self looks
like inside each mixin at runtime — i.e., the full composed PortfolioAnalyzer.
"""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from typing import Protocol

import ipywidgets as widgets


class WidgetsProtocol(Protocol):
    """Structural type of self inside all Widget mixins."""

    # Mixin methods (defined in their respective mixin classes, but declared
    # here for static type checking)

    # PortfolioWidgets
    def create_price_range_slider(
        self,
        description: str = "Price Range (%):",
        default: float = 20.0,
        min_val: float = 5.0,
        max_val: float = 50.0,
        step: float = 5.0,
    ) -> widgets.FloatSlider: ...
    def create_metric_selector(
        self,
        metrics: list[tuple[str, str]],
        default: str,
    ) -> widgets.Dropdown: ...
    def create_date_selector(
        self,
        description: str = "Valuation Date:",
        default: str | None = None,
    ) -> widgets.DatePicker: ...
