"""Convenience functions for options portfolio visualization.

This module provides module-level convenience functions that wrap
OptionCharts methods for easier use.
"""

from typing import Tuple

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.formatters.values import format_currency_for_axis
from deltadewa.visualization.base import OptionCharts


def plot_pnl_diagram(portfolio, **kwargs):
    """
    Convenience function to plot P&L diagram.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_pnl_diagram()

    Returns:
        Matplotlib Figure
    """
    charts = OptionCharts(portfolio)
    return charts.plot_pnl_diagram(**kwargs)


def plot_pnl_distribution_with_metrics(portfolio, **kwargs):
    """
    Convenience function to plot P&L distribution with key metrics.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_pnl_distribution_with_metrics()

    Returns:
        Matplotlib Figure
    """
    charts = OptionCharts(portfolio)
    return charts.plot_pnl_distribution_with_metrics(**kwargs)


def plot_greeks_by_strike(portfolio, **kwargs):
    """
    Convenience function to plot Greeks by strike.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_greeks_by_strike()

    Returns:
        Matplotlib Figure
    """
    charts = OptionCharts(portfolio)
    return charts.plot_greeks_by_strike(**kwargs)


def plot_theta_analysis(portfolio, **kwargs):
    """
    Convenience function to plot theta analysis.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_theta_analysis()

    Returns:
        Matplotlib Figure
    """
    charts = OptionCharts(portfolio)
    return charts.plot_theta_analysis(**kwargs)


def plot_greeks_consolidated(
    portfolio,
    top_n: int = 5,
    figsize: Tuple[int, int] = (16, 10),
) -> Figure:
    """
    Create consolidated Greeks view optimized for the EXPLAIN mode.

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

    def _set_axis_formatting(
        ax,
        title: str = "",
        xaxis: bool = True,
        yaxis: bool = True,
        xint: float = 0,
        yint: float = 0,
    ):
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

    # Panel 1 & 2: Top Contributors for Delta and Gamma
    for idx, (greek_name, column_name) in enumerate(
        [("Delta", "position_delta"), ("Gamma", "position_gamma")]
    ):
        ax = axes[0, idx]
        ax.patch.set_alpha(0.0)

        # Calculate top contributors
        df_sorted = df.copy()
        df_sorted["abs_value"] = df_sorted[column_name].abs()
        df_sorted = df_sorted.nlargest(top_n, "abs_value")

        if len(df_sorted) > 0:
            # Create labels combining symbol, type, strike
            labels = [
                f"{row['type'].upper()[:1]}{row['strike']:.0f}"
                for _, row in df_sorted.iterrows()
            ]
            values = df_sorted[column_name].tolist()
            colors_contrib = [
                DEFAULT_PALETTE.positive if v > 0 else DEFAULT_PALETTE.negative
                for v in values
            ]

            bars = ax.barh(labels, values, color=colors_contrib)
            ax.set_xlabel(greek_name)
            yint, _ = ax.get_ylim()
            _set_axis_formatting(
                ax, f"Top {top_n} {greek_name} Contributors", yint=yint
            )

            # Add value labels
            for b, value in zip(bars, values):
                if value != 0:
                    label_x = value + (
                        0.05
                        * max(abs(v) for v in values)
                        * (1 if value > 0 else -1)
                    )
                    ax.text(
                        label_x,
                        b.get_y() + b.get_height() / 2,
                        f"{value:.2f}",
                        ha="left" if value > 0 else "right",
                        va="center",
                        fontsize=8,
                    )
        else:
            ax.text(
                0.5,
                0.5,
                "No data",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.axis("off")

    # Detailed panels (if requested)
    # Panel 3: Top Vega Contributors
    ax = axes[1, 0]
    ax.patch.set_alpha(0.0)
    df_sorted = df.copy()
    df_sorted["abs_value"] = df_sorted["position_vega"].abs()
    df_sorted = df_sorted.nlargest(top_n, "abs_value")

    if len(df_sorted) > 0:
        labels = [
            f"{row['type'].upper()[:1]}{row['strike']:.0f}"
            for _, row in df_sorted.iterrows()
        ]
        values = df_sorted["position_vega"].tolist()
        colors_contrib = [
            DEFAULT_PALETTE.positive if v > 0 else DEFAULT_PALETTE.negative
            for v in values
        ]

        bars = ax.barh(labels, values, color=colors_contrib)
        ax.set_xlabel("Vega")
        yint, _ = ax.get_ylim()
        _set_axis_formatting(ax, f"Top {top_n} Vega Contributors", yint=yint)

    else:
        ax.text(
            0.5,
            0.5,
            "No data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.axis("off")

    # Panel 4: Top Theta Contributors
    ax = axes[1, 1]
    ax.patch.set_alpha(0.0)
    df_sorted = df.copy()
    df_sorted["abs_value"] = df_sorted["position_theta"].abs()
    df_sorted = df_sorted.nlargest(top_n, "abs_value")

    if len(df_sorted) > 0:
        labels = [
            f"{row['type'].upper()[:1]}{row['strike']:.0f}"
            for _, row in df_sorted.iterrows()
        ]
        values = df_sorted["position_theta"].tolist()
        colors_contrib = [
            DEFAULT_PALETTE.positive if v > 0 else DEFAULT_PALETTE.negative
            for v in values
        ]

        bars = ax.barh(labels, values, color=colors_contrib)
        ax.set_xlabel("Theta ($/day)")
        yint, _ = ax.get_ylim()
        _set_axis_formatting(ax, f"Top {top_n} Theta Contributors", yint=yint)
        ax.xaxis.set_major_formatter(FuncFormatter(format_currency_for_axis))

    # Panel 5: Value by Strike
    ax = axes[2, 0]
    ax.patch.set_alpha(0.0)
    df_sorted = df.copy()
    df_sorted["abs_value"] = (
        df_sorted.groupby("strike")["position_value"].sum().abs()
    )
    df_sorted = df_sorted.nlargest(top_n, "abs_value")
    if len(df_sorted) > 0:
        labels = [f"{row['strike']:.2f}" for _, row in df_sorted.iterrows()]
        values = df_sorted["position_value"].tolist()
        colors_contrib = [
            DEFAULT_PALETTE.positive if v > 0 else DEFAULT_PALETTE.negative
            for v in values
        ]

        bars = ax.barh(labels, values, color=colors_contrib)
        ax.set_xlabel("Position Value")
        yint, _ = ax.get_ylim()
        _set_axis_formatting(
            ax, f"Top {top_n} Position Values by Strike", yint=yint
        )
        ax.xaxis.set_major_formatter(FuncFormatter(format_currency_for_axis))
    else:
        ax.text(
            0.5,
            0.5,
            "No data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.axis("off")

    # Panel 6: Value by Maturity
    ax = axes[2, 1]
    ax.patch.set_alpha(0.0)
    df_sorted = df.copy()
    df_sorted["maturity_label"] = pd.to_datetime(
        df_sorted["maturity"]
    ).dt.strftime("%Y-%m-%d")
    df_sorted["abs_value"] = (
        df_sorted.groupby("maturity_label")["position_value"].sum().abs()
    )
    df_sorted = df_sorted.nlargest(top_n, "abs_value")
    if len(df_sorted) > 0:
        labels = [f"{row['maturity_label']}" for _, row in df_sorted.iterrows()]
        values = df_sorted.groupby("maturity_label")["position_value"].sum()
        colors_contrib = [
            DEFAULT_PALETTE.positive if v > 0 else DEFAULT_PALETTE.negative
            for v in values
        ]

        bars = ax.barh(labels, values, color=colors_contrib)
        ax.set_xlabel("Position Value")
        yint, _ = ax.get_ylim()
        _set_axis_formatting(
            ax, f"Top {top_n} Position Values by Maturity", yint=yint
        )
        ax.xaxis.set_major_formatter(FuncFormatter(format_currency_for_axis))
    else:
        ax.text(
            0.5,
            0.5,
            "No data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.axis("off")

    # Panel 7: Greeks by Strike
    ax = axes[3, 0]
    ax.patch.set_alpha(0.0)
    greek_by_strike = df.groupby("strike").agg(
        {"position_delta": "sum", "position_gamma": "sum"}
    )

    if len(greek_by_strike) > 0:
        greek_by_strike.plot(kind="bar", ax=ax, width=0.7)
        ax.set_xlabel("Strike Price")
        ax.set_ylabel("Greek Value")
        ax.legend(["Delta", "Gamma"], loc="best")
        ax.tick_params(axis="x", rotation=0)
        xint, _ = ax.get_xlim()
        _set_axis_formatting(ax, "Greeks by Strike", xint=xint)

    else:
        ax.text(
            0.5,
            0.5,
            "No data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.axis("off")

    # Panel 8: Greeks by Maturity
    ax = axes[3, 1]
    ax.patch.set_alpha(0.0)
    df["maturity_label"] = pd.to_datetime(df["maturity"]).dt.strftime(
        "%Y-%m-%d"
    )
    greek_by_maturity = df.groupby("maturity_label").agg(
        {"position_delta": "sum", "position_gamma": "sum"}
    )

    if len(greek_by_maturity) > 0:
        greek_by_maturity.plot(kind="bar", ax=ax, width=0.7)
        ax.set_xlabel("Maturity Date")
        ax.set_ylabel("Greek Value")
        ax.legend(["Delta", "Gamma"], loc="best")
        ax.tick_params(axis="x", rotation=0)
        xint, _ = ax.get_xlim()
        _set_axis_formatting(ax, "Greeks by Maturity", xint=xint)
    else:
        ax.text(
            0.5,
            0.5,
            "No data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.axis("off")

    return fig
