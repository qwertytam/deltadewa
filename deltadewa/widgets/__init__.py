"""Interactive Widget Components for Options Dashboard.

This module provides reusable ipywidgets components for building interactive
portfolio analysis dashboards.

.. note::

   **This layer has no product consumer.** Stage 4.3 deleted the two
   notebooks that drove it; ``deltadewa/app/`` (the Dash app) is the
   shipping surface and never imports from here. The modules are kept and
   still tested, but nothing reaches them at runtime. See
   ``docs/part-x-coverage.md``, "Stage 4.3 — the notebook retirement".

Classes:
    InteractiveOutput: Output wrapper with automatic clearing
    GlobalAssumptions: Centralized market parameters and assumptions
    NetHedgeSummary: Always-visible KPI header showing hedge metrics
    PortfolioWidgets: Widget creation and management utilities
    GaugeConfig: Configuration dataclass for GaugeIndicator display parameters
    GaugeIndicator: Visual gauge indicator with configurable color gradient
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
from deltadewa.widgets.convenience import link_portfolio_to_assumptions
from deltadewa.widgets.env_gauges import build_env_gauges
from deltadewa.widgets.export_controls import ExportControlsMixin
from deltadewa.widgets.gauges import GaugeConfig, GaugeIndicator
from deltadewa.widgets.heatmap_controls import HeatmapControlsMixin
from deltadewa.widgets.portfolio_controls import PortfolioWidgets
from deltadewa.widgets.summary import NetHedgeSummary

__all__ = [
    "ExportControlsMixin",
    "GaugeConfig",
    "GaugeIndicator",
    "GlobalAssumptions",
    "HeatmapControlsMixin",
    "InteractiveOutput",
    "NetHedgeSummary",
    "PortfolioWidgets",
    "build_env_gauges",
    "link_portfolio_to_assumptions",
]
