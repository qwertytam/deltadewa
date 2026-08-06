"""Visualization module for options portfolio analysis.

This module provides comprehensive charting and plotting utilities for options
portfolio analysis, including P&L diagrams, Greek distributions, heatmaps,
theta decay analysis, and interactive scenario visualizations.

Re-exports have been removed — import from submodules directly, for
example:

    from deltadewa.visualization.base import OptionCharts
    from deltadewa.visualization.crash_charts_plotly import plot_scenario_curve

The matplotlib-backed submodules (``base``, ``crash_charts``,
``convenience``, ``pnl_charts``, ``theta_charts``, ``scenarios``,
``greeks_charts``) are notebook-only (matplotlib is a `dev`-group
dependency, not installed in the production/`jobs` image — see the M2.6
close-out). The ``*_plotly`` submodules are the ones ``deltadewa.app``
uses and stay import-safe without matplotlib either way. Confirmed
unused at the package level (every call site already imports a specific
submodule) before removing.

Author: DeltaDewa Team
Date: 2026-01-12
"""
