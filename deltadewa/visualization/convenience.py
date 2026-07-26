"""Convenience functions for options portfolio visualization.

This module provides module-level convenience functions that wrap
OptionCharts methods for easier use.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, overload

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.container import BarContainer
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.formatters.values import format_currency_for_axis
from deltadewa.visualization.base import OptionCharts

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio, OptionPortfolioBase


def _annotate_no_data(ax: Axes) -> None:
    """Show a centred 'No data' label and turn the axis off."""
    ax.text(
        0.5,
        0.5,
        "No data",
        ha="center",
        va="center",
        transform=ax.transAxes,
    )
    ax.axis("off")


@overload
def plot_pnl_diagram(
    portfolio: OptionPortfolio,
    **kwargs: Any,  # ruff: ignore[any-type]  # matplotlib **kwargs passthrough
) -> Figure: ...


@overload
def plot_pnl_diagram(
    portfolio: OptionPortfolioBase,
    **kwargs: Any,  # ruff: ignore[any-type]  # matplotlib **kwargs passthrough
) -> Figure: ...


def plot_pnl_diagram(
    portfolio: OptionPortfolio | OptionPortfolioBase,
    **kwargs: Any,
) -> Figure:
    """Plot P&L diagram - convenience function.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_pnl_diagram()

    Returns:
        Matplotlib Figure

    """
    charts = OptionCharts(portfolio)
    return charts.plot_pnl_diagram(**kwargs)


@overload
def plot_pnl_distribution_with_metrics(
    portfolio: OptionPortfolio,
    **kwargs: Any,  # ruff: ignore[any-type]  # matplotlib **kwargs passthrough
) -> Figure: ...


@overload
def plot_pnl_distribution_with_metrics(
    portfolio: OptionPortfolioBase,
    **kwargs: Any,  # ruff: ignore[any-type]  # matplotlib **kwargs passthrough
) -> Figure: ...


def plot_pnl_distribution_with_metrics(
    portfolio: OptionPortfolio | OptionPortfolioBase,
    **kwargs: Any,
) -> Figure:
    """Plot P&L distribution with key metrics - convenience function.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_pnl_distribution_with_metrics()

    Returns:
        Matplotlib Figure

    """
    charts = OptionCharts(portfolio)
    return charts.plot_pnl_distribution_with_metrics(**kwargs)


def plot_greeks_by_strike(
    portfolio: OptionPortfolio | OptionPortfolioBase,
    **kwargs: Any,  # ruff: ignore[any-type]  # matplotlib **kwargs passthrough
) -> Figure:
    """Plot Greeks by strike - convenience function.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_greeks_by_strike()

    Returns:
        Matplotlib Figure

    """
    charts = OptionCharts(portfolio)
    return charts.plot_greeks_by_strike(**kwargs)


def plot_theta_analysis(
    portfolio: OptionPortfolio | OptionPortfolioBase,
    **kwargs: Any,  # ruff: ignore[any-type]  # matplotlib **kwargs passthrough
) -> Figure:
    """Plot theta analysis - convenience function.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_theta_analysis()

    Returns:
        Matplotlib Figure

    """
    charts = OptionCharts(portfolio)
    return charts.plot_theta_analysis(**kwargs)


def _set_axis_formatting(
    ax: Axes,
    title: str = "",
    xaxis: bool = True,
    yaxis: bool = True,
    xint: float = 0,
    yint: float = 0,
) -> None:
    """Draw the shared zero-line/title chrome used by consolidated panels."""
    ax.grid(False)
    if xaxis:
        ax.axhline(y=yint, color=DEFAULT_PALETTE.axis, linewidth=1)
    if yaxis:
        ax.axvline(x=xint, color=DEFAULT_PALETTE.axis, linewidth=1)
    ax.set_title(
        title,
        fontsize=11,
        fontweight="bold",
    )


def _add_bar_value_labels(
    ax: Axes,
    bars: BarContainer,
    values: list[float],
) -> None:
    """Add a numeric label beside each non-zero horizontal bar."""
    for b, value in zip(bars, values, strict=False):
        if value != 0:
            label_x = value + (
                0.05 * max(abs(v) for v in values) * (1 if value > 0 else -1)
            )
            ax.text(
                label_x,
                b.get_y() + b.get_height() / 2,
                f"{value:.2f}",
                ha="left" if value > 0 else "right",
                va="center",
                fontsize=8,
            )


@dataclass(frozen=True)
class _GreekPanelStyle:
    """Per-panel display options for a Greek contributors bar chart."""

    xlabel: str | None = None
    add_value_labels: bool = False
    currency_format: bool = False
    annotate_empty: bool = True


def _draw_greek_contributors_panel(
    ax: Axes,
    df: pd.DataFrame,
    column: str,
    greek_name: str,
    top_n: int,
    style: _GreekPanelStyle,
) -> None:
    """Draw a top-N contributors bar panel for a single Greek column.

    Called once per Greek (Delta, Gamma, Vega, Theta) from
    ``plot_greeks_consolidated``; the per-panel differences (whether bars
    get value labels, currency-formatted axis ticks, an explicit x-axis
    label, and a "No data" placeholder when empty) are supplied by the
    caller's ``style`` so this stays a single parameterised routine.
    """
    ax.patch.set_alpha(0.0)
    df_sorted = df.copy()
    df_sorted["abs_value"] = df_sorted[column].abs()
    df_sorted = df_sorted.nlargest(top_n, "abs_value")

    if len(df_sorted) == 0:
        if style.annotate_empty:
            _annotate_no_data(ax)
        return

    labels = [
        f"{row['option_type'].upper()[:1]}{row['strike']:.0f}"
        for _, row in df_sorted.iterrows()
    ]
    values = df_sorted[column].tolist()
    colors_contrib = [
        DEFAULT_PALETTE.positive if v > 0 else DEFAULT_PALETTE.negative
        for v in values
    ]

    bars = ax.barh(labels, values, color=colors_contrib)
    ax.set_xlabel(style.xlabel if style.xlabel is not None else greek_name)
    yint, _ = ax.get_ylim()
    _set_axis_formatting(
        ax,
        f"Top {top_n} {greek_name} Contributors",
        yint=yint,
    )
    if style.currency_format:
        ax.xaxis.set_major_formatter(FuncFormatter(format_currency_for_axis))

    if style.add_value_labels:
        _add_bar_value_labels(ax, bars, values)


def _draw_value_by_dimension_panel(
    ax: Axes,
    df: pd.DataFrame,
    groupby_column: str,
    top_n: int,
    title: str,
    label_formatter: Callable[[Any], str],
) -> None:
    """Draw a top-N bar panel of summed position value by a dimension.

    Called once per dimension (strike, maturity) from
    ``plot_greeks_consolidated``.
    """
    ax.patch.set_alpha(0.0)
    grouped = df.groupby(groupby_column)["position_value"].sum()
    grouped = grouped.reindex(grouped.abs().nlargest(top_n).index)

    if len(grouped) == 0:
        _annotate_no_data(ax)
        return

    labels = [label_formatter(v) for v in grouped.index]
    values = grouped.tolist()
    colors_contrib = [
        DEFAULT_PALETTE.positive if v > 0 else DEFAULT_PALETTE.negative
        for v in values
    ]

    ax.barh(labels, values, color=colors_contrib)
    ax.set_xlabel("Position Value")
    yint, _ = ax.get_ylim()
    _set_axis_formatting(ax, title, yint=yint)
    ax.xaxis.set_major_formatter(FuncFormatter(format_currency_for_axis))


def _draw_greeks_by_dimension_panel(
    ax: Axes,
    df: pd.DataFrame,
    groupby_column: str,
    title: str,
    xlabel: str,
) -> None:
    """Draw a stacked Delta/Gamma bar panel grouped by a dimension.

    Called once per dimension (strike, maturity) from
    ``plot_greeks_consolidated``.
    """
    ax.patch.set_alpha(0.0)
    greek_by_dimension = df.groupby(groupby_column).agg(
        {"position_delta": "sum", "position_gamma": "sum"},
    )

    if len(greek_by_dimension) == 0:
        _annotate_no_data(ax)
        return

    greek_by_dimension.plot(kind="bar", ax=ax, width=0.7)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Greek Value")
    ax.legend(["Delta", "Gamma"], loc="best")
    ax.tick_params(axis="x", rotation=0)
    xint, _ = ax.get_xlim()
    _set_axis_formatting(ax, title, xint=xint)


def plot_greeks_consolidated(
    portfolio: OptionPortfolio | OptionPortfolioBase,
    top_n: int = 5,
    figsize: tuple[int, int] = (16, 10),
) -> Figure:
    """Create consolidated Greeks view optimized for the EXPLAIN mode.

    This function provides the default 80% use case view: a compact summary
    showing net portfolio Greeks and top contributors. Detailed breakdowns
    are available via the show_detailed parameter.

    Args:
        portfolio: OptionPortfolio instance
        top_n: Number of top contributors to show (default: 5)
        figsize: Figure size tuple
        show_detailed: Whether to include detailed breakdown panels

    Returns:
        Matplotlib Figure with consolidated Greeks visualization

    Panels (default view):
        1. Net portfolio Greeks (single row table display)
        2. Top N contributors bar chart for each Greek
        3. Greeks sensitivity heatmap (how net Greeks change with spot)

    Panels (detailed view):
        4. Strike-by-strike breakdown
        5. Maturity-by-maturity breakdown

    """
    df = portfolio.to_dataframe()

    if df.empty:
        # Return empty figure if no positions
        fig, ax = plt.subplots(1, 1, figsize=(10, 6))
        ax.text(
            0.5,
            0.5,
            "No positions in portfolio",
            ha="center",
            va="center",
            fontsize=16,
        )
        ax.axis("off")
        return fig

    # Set number of panels
    nrows = 4
    fig, axes = plt.subplots(nrows, 2, figsize=figsize)
    fig.patch.set_alpha(0.0)

    # Panel 1 & 2: Top Contributors for Delta and Gamma
    for idx, (greek_name, column_name) in enumerate(
        [("Delta", "position_delta"), ("Gamma", "position_gamma")],
    ):
        _draw_greek_contributors_panel(
            axes[0, idx],
            df,
            column_name,
            greek_name,
            top_n,
            _GreekPanelStyle(add_value_labels=True),
        )

    # Detailed panels (if requested)
    # Panel 3: Top Vega Contributors
    _draw_greek_contributors_panel(
        axes[1, 0],
        df,
        "position_vega",
        "Vega",
        top_n,
        _GreekPanelStyle(),
    )

    # Panel 4: Top Theta Contributors
    _draw_greek_contributors_panel(
        axes[1, 1],
        df,
        "position_theta",
        "Theta",
        top_n,
        _GreekPanelStyle(
            xlabel="Theta ($/day)",
            currency_format=True,
            annotate_empty=False,
        ),
    )

    # Panel 5: Value by Strike
    _draw_value_by_dimension_panel(
        axes[2, 0],
        df,
        "strike",
        top_n,
        f"Top {top_n} Position Values by Strike",
        lambda strike: f"{strike:.2f}",
    )

    # Panel 6: Value by Maturity
    df_maturity = df.copy()
    df_maturity["maturity_label"] = pd.to_datetime(
        df_maturity["maturity"],
    ).dt.strftime("%Y-%m-%d")
    _draw_value_by_dimension_panel(
        axes[2, 1],
        df_maturity,
        "maturity_label",
        top_n,
        f"Top {top_n} Position Values by Maturity",
        str,
    )

    # Panel 7: Greeks by Strike
    _draw_greeks_by_dimension_panel(
        axes[3, 0],
        df,
        "strike",
        "Greeks by Strike",
        "Strike Price",
    )

    # Panel 8: Greeks by Maturity
    df["maturity_label"] = pd.to_datetime(df["maturity"]).dt.strftime(
        "%Y-%m-%d",
    )
    _draw_greeks_by_dimension_panel(
        axes[3, 1],
        df,
        "maturity_label",
        "Greeks by Maturity",
        "Maturity Date",
    )

    return fig
