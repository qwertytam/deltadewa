"""Visualization module for options portfolio analysis.

This module provides comprehensive charting and plotting utilities for options
portfolio analysis, including P&L diagrams, Greek distributions, heatmaps,
theta decay analysis, and interactive scenario visualizations.

Usage:
    from deltadewa.visualization import OptionCharts

    charts = OptionCharts(portfolio)
    charts.plot_pnl_diagram()
    charts.plot_greeks_by_strike()
    charts.plot_theta_analysis()

Author: DeltaDewa Team
Date: 2026-01-12
"""

from deltadewa.visualization.base import OptionCharts
from deltadewa.visualization.convenience import (
    plot_pnl_diagram,
    plot_pnl_distribution_with_metrics,
    plot_greeks_by_strike,
    plot_theta_analysis,
    plot_greeks_consolidated,
)

__all__ = [
    "OptionCharts",
    "plot_pnl_diagram",
    "plot_pnl_distribution_with_metrics",
    "plot_greeks_by_strike",
    "plot_theta_analysis",
    "plot_greeks_consolidated",
]
