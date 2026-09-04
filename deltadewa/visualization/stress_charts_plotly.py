"""Plotly heatmap charts for the Dash /design EXPLORATION zone.

Separate from :mod:`deltadewa.visualization.crash_charts_plotly` only in
subject matter -- both are Dash/Plotly modules, chart builders over
already-computed numbers (a ``pandas.DataFrame`` from
:class:`~deltadewa.analysis.cache.ScenarioGridCache`), no portfolio or
engine access here, matplotlib never imported.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import plotly.graph_objects as go

if TYPE_CHECKING:
    from datetime import datetime

    import numpy as np
    import pandas as pd

# CVD-safe (ColorBrewer) diverging scale -- replaces the matplotlib
# RdYlGn scale `dashboard/stress.py` uses, which is invisible to
# red-green colour blindness. Every heatmap in this module uses this one
# scale, so the choice is made in exactly one place.
_DIVERGING_COLORSCALE = "RdBu"

_EMPTY_TEXT = "No scenario data"

# #331: bottom margin for a 90 deg x-axis so the rotated tick labels
# aren't clipped by the plot area's edge. Time/price's labels are two
# lines (`_time_col_label`'s "Today"/"T+n" plus a date, joined with
# `<br>`), so they need roughly double spot/vol's single-line headroom.
_ROTATED_TICK_BOTTOM_MARGIN = 80
_ROTATED_TWO_LINE_TICK_BOTTOM_MARGIN = 140


@dataclass(frozen=True)
class StressMetricSpec:
    """Presentation metadata for one scenario-grid metric.

    Attributes:
        label: Human-readable axis/colorbar label.
        value_format: A ``str.format`` spec for one cell's value, e.g.
            ``"${:,.0f}"``.

    """

    label: str
    value_format: str


# One shared table for both heatmap builders below and the /design
# metric dropdowns -- a straight port of dashboard/stress.py's
# _METRIC_CONFIG / _METRIC_LABELS, merged into one dataclass per metric
# so the two never drift apart.
STRESS_METRICS: dict[str, StressMetricSpec] = {
    # #329: "pnl"/"value" used to say nothing about composition, unlike
    # the delta pair below -- a reader who'd just learned "options only"
    # vs "incl. underlying" from the delta options had every reason to
    # wonder which convention P&L followed. Both are combined
    # hedge-and-underlying (see _calculate_portfolio_value_at), so both
    # now say so explicitly, in the delta entries' own wording.
    "pnl": StressMetricSpec(
        "Total P&L vs current, incl. underlying ($)",
        "${:,.0f}",
    ),
    "value": StressMetricSpec(
        "Total portfolio value, incl. underlying ($)",
        "${:,.0f}",
    ),
    "net_delta": StressMetricSpec(
        "Net delta (shares equiv., incl. underlying)",
        "{:,.1f}",
    ),
    "delta": StressMetricSpec(
        "Delta (shares equiv., options only)",
        "{:,.1f}",
    ),
    "gamma": StressMetricSpec("Gamma (delta per $1 spot move)", "{:,.4f}"),
    "vega": StressMetricSpec("Vega ($ per 1% vol)", "{:,.2f}"),
    "theta": StressMetricSpec("Theta ($ per day)", "${:,.2f}"),
    "rho": StressMetricSpec("Rho ($ per 1% rate)", "{:,.2f}"),
}


def _metric_spec(metric: str) -> StressMetricSpec:
    """Look up a metric's presentation spec, falling back to P&L."""
    return STRESS_METRICS.get(metric, STRESS_METRICS["pnl"])


# #329: one shared string for both heatmap panels' plain-language note, so
# spot_vol.py and time_price.py can't drift apart in how they word the same
# baseline. This module has no Dash import (chart builder only), so the
# panels render it themselves as an html.P -- this is just the sentence.
STRESS_BASELINE_NOTE = (
    "Every cell is the book's value in that scenario minus its value "
    "today, at today's spot and today's valuation date -- hedge and "
    "underlying combined."
)


def _centered_diverging_kwargs(center: float = 0.0) -> dict[str, Any]:
    """Build shared colour kwargs for a heatmap trace centered at *center*.

    Plotly centers a diverging colourscale around a value natively via
    ``zmid`` -- this replaces the matplotlib
    ``get_matplotlib_norm_and_cmap`` norm/cmap construction with one dict
    literal, on the CVD-safe scale (see :data:`_DIVERGING_COLORSCALE`).

    Args:
        center: The data value the colourscale should be centered on.

    Returns:
        Kwargs to splat into a ``go.Heatmap(...)`` call.

    """
    return {"colorscale": _DIVERGING_COLORSCALE, "zmid": center}


def _empty_stress_figure(title: str) -> go.Figure:
    """Build an informative empty-state figure for a stress heatmap."""
    fig = go.Figure()
    fig.update_layout(
        title=title,
        annotations=[
            {
                "text": _EMPTY_TEXT,
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
            },
        ],
    )
    return fig


def plot_spot_vol_heatmap(
    result_df: pd.DataFrame,
    *,
    spot_scenarios: np.ndarray[Any, np.dtype[Any]],
    vol_scenarios: np.ndarray[Any, np.dtype[Any]],
    original_spot: float,
    avg_vol: float,
    metric: str,
) -> go.Figure:
    """Build the spot x vol stress heatmap.

    Consumes :meth:`~deltadewa.analysis.cache.ScenarioGridCache
    .get_or_calculate_spot_vol`'s output only -- no portfolio or engine
    access here, purely a chart builder over already-computed numbers.

    Three traces: a ``go.Heatmap`` (the CVD-safe diverging fill), a
    ``go.Contour`` line overlay (no fill, matching the matplotlib
    version's ``ax.contour`` + ``ax.clabel``), and a diamond marker at
    the current ``(original_spot, avg_vol)`` position. Dashed reference
    lines mark both axes at that same point.

    The y-axis is titled as an *absolute level*, never a "bump": the
    axis is ``vol_scenarios``, the target average volatility each
    column is scaled to reach (see
    :func:`~deltadewa.analysis.repricing.proportional_vol`), not an
    additive shock. Conflating the two is the exact unit mismatch that
    hid the M2.1 -25.4% gap; ``/monitor``'s vol dial is an additive
    bump and must never share this label.

    Args:
        result_df: Columns ``spot_price``, ``volatility``, ``value``.
            Empty renders an informative empty-state figure rather than
            raising.
        spot_scenarios: The spot axis, ascending.
        vol_scenarios: The vol axis, ascending -- absolute levels.
        original_spot: Today's spot; drawn as a vertical reference line.
        avg_vol: Today's vega-weighted average vol; drawn as a
            horizontal reference line.
        metric: A key into :data:`STRESS_METRICS`; unrecognised metrics
            fall back to ``"pnl"``.

    Returns:
        A Plotly ``Figure``.

    """
    spec = _metric_spec(metric)
    title = f"Stress heatmap: {spec.label} (proportional vol)"
    if result_df.empty:
        return _empty_stress_figure(title)

    matrix = (
        result_df.pivot(
            index="volatility",
            columns="spot_price",
            values="value",
        )
        .sort_index(ascending=True)
        .to_numpy()
    )

    fig = go.Figure()
    fig.add_trace(
        go.Heatmap(
            x=spot_scenarios,
            y=vol_scenarios,
            z=matrix,
            colorbar={"title": spec.label},
            **_centered_diverging_kwargs(),
        ),
    )
    fig.add_trace(
        go.Contour(
            x=spot_scenarios,
            y=vol_scenarios,
            z=matrix,
            showscale=False,
            contours={"coloring": "lines", "showlabels": True},
            line={"width": 0.5, "color": "rgba(0, 0, 0, 0.4)"},
            hoverinfo="skip",
            name="Contours",
        ),
    )
    fig.add_hline(y=avg_vol, line_dash="dash", line_color="grey")
    fig.add_vline(x=original_spot, line_dash="dash", line_color="grey")
    fig.add_trace(
        go.Scatter(
            x=[original_spot],
            y=[avg_vol],
            mode="markers",
            name="Current position",
            marker={
                "symbol": "diamond",
                "size": 12,
                "color": "white",
                "line": {"color": "black", "width": 2},
            },
        ),
    )
    fig.update_layout(
        title=title,
        xaxis_title="Spot price ($)",
        yaxis_title="Average implied vol (absolute level)",
        yaxis_tickformat=".0%",
        # #331: 90 deg rather than Plotly's 45 deg default, matching
        # plot_time_price_heatmap so the EXPLORATION zone's two heatmaps
        # read consistently.
        xaxis_tickangle=90,
        margin={"b": _ROTATED_TICK_BOTTOM_MARGIN},
    )
    return fig


def _time_col_label(days: str | float, original_date: datetime) -> str:
    """Format one time-axis column label: 'Today'/'T+n' plus the date.

    *days* is typed loosely (``str | float``) because a pivoted
    DataFrame's column index is generic — the real values are always the
    ints ``build_time_price_grid_spec`` put there.
    """
    offset = int(float(days))
    future_date = original_date + timedelta(days=offset)
    prefix = "Today" if offset == 0 else f"T+{offset}"
    return f"{prefix}<br>{future_date.strftime('%Y-%m-%d')}"


def _spot_row_label(spot: float, original_spot: float) -> str:
    """Format one spot-axis row label with its % move from today."""
    pct = (spot - original_spot) / original_spot
    if abs(pct) < 0.001:
        return f"${spot:,.0f} (~0%)"
    sign = "+" if pct > 0 else ""
    return f"${spot:,.0f} ({sign}{pct:.0%})"


def plot_time_price_heatmap(
    result_df: pd.DataFrame,
    *,
    original_spot: float,
    original_date: datetime,
    metric: str,
) -> go.Figure:
    """Build the time x price stress heatmap, with cell annotations.

    The notebook rendered this as a styled pandas table; this ports it
    as a ``go.Heatmap`` with per-cell ``text`` annotations
    (``texttemplate="%{text}"``) so both readings survive -- the colour
    gradient and the actual number in each cell.

    Consumes :meth:`~deltadewa.analysis.cache.ScenarioGridCache
    .get_or_calculate`'s output only -- no portfolio or engine access.

    Args:
        result_df: Columns ``spot_price``, ``days_forward``, ``value``.
            Empty renders an informative empty-state figure.
        original_spot: Today's spot; row labels show each row's % move
            from this reference.
        original_date: Valuation date the time axis is offset from;
            each column label shows the resulting calendar date.
        metric: A key into :data:`STRESS_METRICS`.

    Returns:
        A Plotly ``Figure``.

    """
    spec = _metric_spec(metric)
    title = f"Time vs price: {spec.label} (proportional vol)"
    if result_df.empty:
        return _empty_stress_figure(title)

    # Ascending, matching plot_spot_vol_heatmap (#330): Plotly draws
    # categorical y-axis entries bottom-to-top, so an ascending index
    # puts the highest spot at the top. matrix/text/y_labels all derive
    # from this same pivot.index, so the sort carries all three together
    # -- no z<->label mispairing is possible.
    pivot = result_df.pivot(
        index="spot_price",
        columns="days_forward",
        values="value",
    ).sort_index(ascending=True)
    matrix = pivot.to_numpy()
    text = [
        [spec.value_format.format(value) for value in row] for row in matrix
    ]
    x_labels = [_time_col_label(days, original_date) for days in pivot.columns]
    y_labels = [_spot_row_label(spot, original_spot) for spot in pivot.index]

    fig = go.Figure(
        go.Heatmap(
            z=matrix,
            x=x_labels,
            y=y_labels,
            text=text,
            texttemplate="%{text}",
            colorbar={"title": spec.label},
            **_centered_diverging_kwargs(),
        ),
    )
    fig.update_layout(
        title=title,
        xaxis_title="Time forward",
        yaxis_title="Spot price (% from current)",
        # #331: 90 deg rather than Plotly's 45 deg default -- at 45 deg
        # these two-line date labels overlapped and ate a wide diagonal
        # band of the plot area; at 90 deg they stack vertically and take
        # less horizontal room. The taller bottom margin keeps the second
        # line from being clipped.
        xaxis_tickangle=90,
        margin={"b": _ROTATED_TWO_LINE_TICK_BOTTOM_MARGIN},
    )
    return fig
