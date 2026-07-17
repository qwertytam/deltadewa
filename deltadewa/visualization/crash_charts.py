"""Crash payoff chart for option portfolio visualization."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from deltadewa.colours import DEFAULT_PALETTE

if TYPE_CHECKING:
    from deltadewa.analysis.crash_payoff import CrashConvexityResult
    from deltadewa.ips_config import IpsConvexity


def plot_crash_convexity(
    result: CrashConvexityResult,
    *,
    ax: Axes | None = None,
) -> Figure:
    """Single-panel repriced hedge payoff chart.

    Plots the repriced hedge value ($) vs shock (%) from ``result.curve``
    (the long puts repriced at each crash spot, hedge-only).  Horizontal
    reference line at ``premium_paid`` makes cost vs. payoff directly
    visible.  A vertical line marks the IPS crash shock and a text
    annotation shows the payoff ratio (e.g. "8.5x").

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
        ax.set_title("Repriced Hedge Payoff vs Shock")
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
    ax.set_ylabel("Repriced Hedge Value ($)")
    ax.set_title("Repriced Hedge Payoff vs Shock")
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{v:+.0f}%"),
    )
    ax.yaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"${v:,.0f}"),
    )

    return fig


def plot_carry_vs_convexity(
    *,
    carry_cost: float | None,
    convexity_pct: float | None,
    ips_convexity: IpsConvexity | None = None,
    ax: Axes | None = None,
) -> Figure:
    """Carry cost vs crash convexity — cost-vs-protection view.

    Plots the current book as a single point on a cost (Y-axis) vs
    protection (X-axis) plane.  When *ips_convexity* is supplied, the
    target convexity band is shaded on the X axis.

    Consumes pre-computed scalars only; does not reprice the portfolio.

    Args:
        carry_cost: Annual carry cost in dollars (e.g.
            ``calculate_carry_metrics()["total_theta_annual"]``).
            Negative for net-long-premium books.  ``None`` renders a
            labelled empty figure.
        convexity_pct: Hedge-only repriced crash convexity as % of the
            protected book at the IPS scenario
            (``CrashScenarioRow.convexity_pct``).  ``None`` renders a
            labelled empty figure.
        ips_convexity: Optional IPS convexity target; shades the
            ``[target_min_pct, target_max_pct]`` band when supplied.
        ax: Existing Axes to draw on.  Creates a new Figure when
            ``None``.

    Returns:
        Matplotlib ``Figure`` (Agg-safe; no ``plt.show()`` called).

    """
    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 5))
    else:
        maybe_fig = ax.get_figure()
        if maybe_fig is None:
            msg = "Supplied ax is not attached to a Figure"
            raise ValueError(msg)
        fig = cast(Figure, maybe_fig)

    ax.set_xlabel("Crash Convexity (%)")
    ax.set_ylabel("Annual Carry Cost ($)")
    ax.set_title("Carry Cost vs Crash Convexity")

    if carry_cost is None or convexity_pct is None:
        ax.text(
            0.5,
            0.5,
            "No data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        return fig

    if ips_convexity is not None:
        ax.axvspan(
            ips_convexity.target_min_pct,
            ips_convexity.target_max_pct,
            alpha=0.15,
            color=DEFAULT_PALETTE.positive,
            label=(
                f"IPS target"
                f" {ips_convexity.target_min_pct:.0f}-"
                f"{ips_convexity.target_max_pct:.0f}%"
            ),
            zorder=1,
        )
        ax.axvline(
            ips_convexity.target_min_pct,
            color=DEFAULT_PALETTE.positive,
            linewidth=0.8,
            linestyle="--",
            zorder=2,
        )
        ax.axvline(
            ips_convexity.target_max_pct,
            color=DEFAULT_PALETTE.positive,
            linewidth=0.8,
            linestyle="--",
            zorder=2,
        )

    ax.axhline(0.0, color="grey", linewidth=0.8, linestyle="-", zorder=0)
    ax.axvline(0.0, color="grey", linewidth=0.8, linestyle="-", zorder=0)

    ax.scatter(
        [convexity_pct],
        [carry_cost],
        color=DEFAULT_PALETTE.call,
        s=80,
        zorder=3,
        label="Current book",
    )
    ax.annotate(
        f"({convexity_pct:+.1f}%,  ${carry_cost:,.0f}/yr)",
        xy=(convexity_pct, carry_cost),
        xytext=(8, 8),
        textcoords="offset points",
        fontsize=9,
        color=DEFAULT_PALETTE.call,
        zorder=4,
    )

    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{v:+.1f}%"),
    )
    ax.yaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"${v:,.0f}"),
    )
    ax.grid(True, alpha=0.3, zorder=0)
    ax.legend(fontsize=8)

    return fig


class CrashChartsMixin:
    """Mixin providing crash payoff chart methods."""

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

    def plot_carry_vs_convexity(
        self,
        *,
        carry_cost: float | None,
        convexity_pct: float | None,
        ips_convexity: IpsConvexity | None = None,
        ax: Axes | None = None,
    ) -> Figure:
        """Delegate to module-level ``plot_carry_vs_convexity``.

        Args:
            carry_cost: Annual carry cost in dollars.
            convexity_pct: Net crash P&L as % of book notional.
            ips_convexity: Optional IPS convexity target.
            ax: Existing Axes to draw on.

        Returns:
            Matplotlib Figure.

        """
        return plot_carry_vs_convexity(
            carry_cost=carry_cost,
            convexity_pct=convexity_pct,
            ips_convexity=ips_convexity,
            ax=ax,
        )
