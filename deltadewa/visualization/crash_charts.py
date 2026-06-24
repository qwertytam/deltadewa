"""Crash payoff and convexity charts for option portfolio visualization."""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from deltadewa.colours import DEFAULT_PALETTE

if TYPE_CHECKING:
    from deltadewa.analysis.crash_payoff import CrashConvexityResult


def _plot_payoff_ratio_panel(
    ax: Axes,
    result: CrashConvexityResult,
) -> None:
    """Plot payoff ratio curve on *ax*.

    X-axis: shock percent (signed, e.g. -10 to -40).
    Y-axis: payoff ratio (x).  IPS crash row highlighted in gold.
    Premium basis annotated in the lower-right corner.

    Args:
        ax: Matplotlib Axes to draw on.
        result: Pre-computed crash convexity result.

    """
    if not result.rows:
        ax.set_title("Payoff Ratio")
        ax.text(
            0.5,
            0.5,
            "No scenario data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        return

    ips_shock = (
        result.ips_convexity.crash_scenario_pct
        if result.ips_convexity is not None
        else None
    )
    xs = [row.shock_pct for row in result.rows]
    ys = [row.payoff_ratio for row in result.rows]

    ax.plot(
        xs,
        ys,
        color=DEFAULT_PALETTE.call,
        linewidth=1.8,
        zorder=2,
    )

    for row in result.rows:
        is_ips = row.shock_pct == ips_shock
        ax.scatter(
            [row.shock_pct],
            [row.payoff_ratio],
            color=DEFAULT_PALETTE.yellow if is_ips else DEFAULT_PALETTE.call,
            edgecolors="black" if is_ips else "none",
            s=100 if is_ips else 50,
            zorder=3,
        )

    ax.axhline(1.0, color="grey", linewidth=0.8, linestyle="--", zorder=1)

    ax.set_xlabel("Shock (%)")
    ax.set_ylabel("Payoff Ratio (x)")
    ax.set_title("Payoff Ratio vs Shock")
    ax.xaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v:+.0f}%"),
    )
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v:.1f}x"),
    )
    ax.text(
        0.98,
        0.04,
        f"Premium basis: {result.premium_basis}",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        color="grey",
    )


def _plot_convexity_panel(
    ax: Axes,
    result: CrashConvexityResult,
) -> None:
    """Plot convexity % bar chart on *ax*.

    Bars coloured green when ``meets_target``, red otherwise.
    IPS target band overlaid as a shaded region when available.

    Args:
        ax: Matplotlib Axes to draw on.
        result: Pre-computed crash convexity result.

    """
    if not result.rows:
        ax.set_title("Convexity %")
        ax.text(
            0.5,
            0.5,
            "No scenario data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        return

    xs = [row.shock_pct for row in result.rows]
    heights = [row.convexity_pct for row in result.rows]
    colors = [
        DEFAULT_PALETTE.positive
        if row.meets_target
        else DEFAULT_PALETTE.negative
        for row in result.rows
    ]

    width = min(abs(xs[0] - xs[1]) * 0.6, 4.0) if len(xs) > 1 else 4.0
    ax.bar(xs, heights, width=width, color=colors, zorder=2)

    if result.ips_convexity is not None:
        ips = result.ips_convexity
        ax.axhspan(
            ips.target_min_pct,
            ips.target_max_pct,
            color=DEFAULT_PALETTE.positive_faded,
            alpha=0.3,
            zorder=1,
            label=(
                f"IPS target "
                f"{ips.target_min_pct:.0f}-{ips.target_max_pct:.0f}%"
            ),
        )
        ax.legend(fontsize=8, loc="upper right")

    ax.axhline(0.0, color="grey", linewidth=0.8, linestyle="-", zorder=1)
    ax.set_xlabel("Shock (%)")
    ax.set_ylabel("Convexity (%)")
    ax.set_title("Net Convexity vs Shock")
    ax.xaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v:+.0f}%"),
    )
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v:+.1f}%"),
    )


def plot_crash_convexity(
    result: CrashConvexityResult,
    figsize: tuple[int, int] = (12, 5),
) -> Figure:
    """Two-panel crash payoff and convexity chart.

    Left panel: payoff ratio (x) vs shock percent, with IPS scenario
    highlighted and premium basis annotated.
    Right panel: net convexity % vs shock percent, with IPS target band.

    Args:
        result: Pre-computed ``CrashConvexityResult`` from
            ``compute_crash_convexity``.
        figsize: Figure dimensions.

    Returns:
        Matplotlib ``Figure`` with two side-by-side panels.

    """
    fig, (ax_ratio, ax_conv) = plt.subplots(1, 2, figsize=figsize)
    _plot_payoff_ratio_panel(ax_ratio, result)
    _plot_convexity_panel(ax_conv, result)
    plt.tight_layout()
    return fig


class CrashChartsMixin:
    """Mixin providing crash payoff and convexity chart methods."""

    def plot_crash_convexity(
        self,
        result: CrashConvexityResult,
        figsize: tuple[int, int] = (12, 5),
    ) -> Figure:
        """Delegate to module-level ``plot_crash_convexity``.

        Args:
            result: Pre-computed crash convexity result.
            figsize: Figure dimensions.

        Returns:
            Matplotlib Figure.

        """
        return plot_crash_convexity(result, figsize=figsize)
