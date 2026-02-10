"""
Interactive Widget Components for Options Dashboard

This module provides backward compatibility for the widgets module.
All classes have been refactored into separate module files under
deltadewa.widgets/ package.

⚠️ DEPRECATED: This module re-exports classes from the new structure.
Please update imports to use the new modular structure:
    from deltadewa.widgets import PortfolioWidgets, InteractiveOutput

Classes:
    PortfolioWidgets: Widget creation and management utilities
    InteractiveOutput: Output wrapper with automatic clearing
    GlobalAssumptions: Centralized market parameters and assumptions
    NetHedgeSummary: Always-visible KPI header showing hedge metrics
    GaugeIndicator: Visual gauge indicator with configurable color gradient
    HedgeHealthMetric: Configuration for a single hedge health metric
    HedgeHealthDashboard: Comprehensive hedge health dashboard with visual gauges

Usage:
    from deltadewa.widgets import PortfolioWidgets, InteractiveOutput

    widgets = PortfolioWidgets(portfolio)
    position_editor = widgets.create_position_editor()
    display(position_editor)
"""

# Import all classes from the new modular structure for backward compatibility
from deltadewa.widgets.base import InteractiveOutput
from deltadewa.widgets.assumptions import GlobalAssumptions
from deltadewa.widgets.summary import NetHedgeSummary
from deltadewa.widgets.portfolio_controls import PortfolioWidgets
from deltadewa.widgets.gauges import GaugeIndicator
from deltadewa.widgets.health_dashboard import (
    HedgeHealthMetric,
    HedgeHealthDashboard,
)

__all__ = [
    "InteractiveOutput",
    "GlobalAssumptions",
    "NetHedgeSummary",
    "PortfolioWidgets",
    "GaugeIndicator",
    "HedgeHealthMetric",
    "HedgeHealthDashboard",
]
