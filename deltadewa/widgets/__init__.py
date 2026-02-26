"""Interactive Widget Components for Options Dashboard

This module provides reusable ipywidgets components for building interactive
portfolio analysis dashboards. It standardizes widget creation patterns and
reduces code duplication across notebooks.

Classes:
    InteractiveOutput: Output wrapper with automatic clearing
    GlobalAssumptions: Centralized market parameters and assumptions
    NetHedgeSummary: Always-visible KPI header showing hedge metrics
    PortfolioWidgets: Widget creation and management utilities
    GaugeIndicator: Visual gauge indicator with configurable color gradient
    HedgeHealthMetric: Configuration for a single hedge health metric
    HedgeHealthDashboard: Comprehensive hedge health dashboard with visual gauges
    ExportControlsMixin: Mixin for export/import controls (advanced usage)
    HeatmapControlsMixin: Mixin for heatmap controls (advanced usage)

Usage:
    from deltadewa.widgets import PortfolioWidgets, InteractiveOutput

    widgets = PortfolioWidgets(portfolio)
    position_editor = widgets.create_position_editor()
    display(position_editor)
"""

from deltadewa.widgets.assumptions import GlobalAssumptions
from deltadewa.widgets.base import InteractiveOutput
from deltadewa.widgets.export_controls import ExportControlsMixin
from deltadewa.widgets.gauges import GaugeIndicator
from deltadewa.widgets.health_dashboard import (
                                                HedgeHealthDashboard,
                                                HedgeHealthMetric,
)
from deltadewa.widgets.heatmap_controls import HeatmapControlsMixin
from deltadewa.widgets.portfolio_controls import PortfolioWidgets
from deltadewa.widgets.summary import NetHedgeSummary

__all__ = [
                                                "ExportControlsMixin",
                                                "GaugeIndicator",
                                                "GlobalAssumptions",
                                                "HeatmapControlsMixin",
                                                "HedgeHealthDashboard",
                                                "HedgeHealthMetric",
                                                "InteractiveOutput",
                                                "NetHedgeSummary",
                                                "PortfolioWidgets",
]
