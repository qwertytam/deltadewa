"""Crash payoff chart for option portfolio visualization."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from deltadewa.colours import DEFAULT_PALETTE

if TYPE_CHECKING:
    from deltadewa.analysis.crash_payoff import CrashConvexityResult


def plot_crash_convexity(
    result: CrashConvexityResult,
    *,
    ax: Axes | None = None,
) -> Figure:
    """Single-panel gross hedge payoff chart.

    Plots raw gross payoff ($) vs shock (%) from ``result.curve``.
    Horizontal reference line at ``premium_paid`` makes cost vs. payoff
    directly visible.  A vertical line marks the IPS crash shock and a
    text annotation shows the payoff ratio (e.g. "8.5x").

    Does not recompute anything from the portfolio — consumes the
    pre-computed ``CrashConvexityResult`` value object only.

    Args:
        result: Pre-computed crash convexity result.
        ax: Existing Axes to draw on.  Creates a new Figure when ``None``.

    Returns:
        Matplotlib ``Figure`` (Agg-safe; no ``plt.show()`` called).

    """
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 5))
    else:
        maybe_fig = ax.get_figure()
        if maybe_fig is None:
            msg = "Supplied ax is not attached to a Figure"
            raise ValueError(msg)
        fig = cast(Figure, maybe_fig)

    if not result.curve:
        ax.set_title("Gross Hedge Payoff vs Shock")
        ax.text(
            0.5,
            0.5,
            "No scenario data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        return fig

    xs = [s for s, _ in result.curve]
    ys = [gp for _, gp in result.curve]

    ax.plot(xs, ys, color=DEFAULT_PALETTE.call, linewidth=1.8, zorder=2)

    ax.axhline(0.0, color="grey", linewidth=0.8, linestyle="-", zorder=1)

    if result.premium_paid > 0:
        ax.axhline(
            result.premium_paid,
            color=DEFAULT_PALETTE.yellow,
            linewidth=1.2,
            linestyle="--",
            zorder=1,
            label=f"Premium ({result.premium_basis})",
        )

    if result.ips_convexity is not None:
        ips_shock = result.ips_convexity.crash_scenario_pct
        ax.axvline(
            ips_shock,
            color="grey",
            linewidth=1.0,
            linestyle=":",
            zorder=1,
        )
        if result.payoff_ratio is not None:
            curve_dict = dict(result.curve)
            ips_gp = curve_dict.get(
                round(ips_shock, 6),
                result.payoff_ratio * result.premium_paid,
            )
            ax.annotate(
                f"{result.payoff_ratio:.1f}x",
                xy=(ips_shock, ips_gp),
                xytext=(8, 8),
                textcoords="offset points",
                fontsize=9,
                color=DEFAULT_PALETTE.yellow,
                zorder=4,
            )

    if result.premium_paid > 0:
        ax.legend(fontsize=8, loc="upper right")

    ax.grid(True, alpha=0.3, zorder=0)

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

    ax.set_xlabel("Shock (%)")
    ax.set_ylabel("Gross Payoff ($)")
    ax.set_title("Gross Hedge Payoff vs Shock")
    ax.xaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v:+.0f}%"),
    )
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"${v:,.0f}"),
    )

    return fig


class CrashChartsMixin:
    """Mixin providing crash payoff chart method."""

    def plot_crash_convexity(
        self,
        result: CrashConvexityResult,
        *,
        ax: Axes | None = None,
    ) -> Figure:
        """Delegate to module-level ``plot_crash_convexity``.

        Args:
            result: Pre-computed crash convexity result.
            ax: Existing Axes to draw on.  Creates a new Figure when ``None``.

        Returns:
            Matplotlib Figure.

        """
        return plot_crash_convexity(result, ax=ax)
