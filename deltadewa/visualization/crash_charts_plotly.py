"""Plotly scenario-curve chart for the Dash monitor page.

Separate from :mod:`deltadewa.visualization.crash_charts` (matplotlib,
Jupyter-only) so the Jupyter/Dash split stays obvious — this module never
imports matplotlib, and the matplotlib module never imports plotly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import plotly.graph_objects as go

from deltadewa.colours import DEFAULT_PALETTE

if TYPE_CHECKING:
    from deltadewa.analysis.monitor_scenario import ScenarioCurvePoint

_EMPTY_TEXT = "No scenario data"

# net is an emphasis/ink color, not a categorical identity hue -- its sign
# varies point to point, so tying it to a directional hue (green/red) would
# mislead half the time. The three hued series below were run through the
# dataviz skill's CVD validator (all-pairs, light mode): call/negative/orange
# pass lightness, chroma, and CVD-separation; orange WARNs on raw contrast
# (2.63:1), which is legal here because the mitigation the skill requires --
# a visible legend and Plotly's hover tooltips -- is already present. The
# marker reuses hedge_value's blue rather than a fourth hue: a green marker
# against the red underlying_loss line fails CVD (deuteranopia ΔE 3.7), so
# shape (diamond) + size distinguishes the marker instead of a new color.
_NET_COLOR = "#333333"
_HEDGE_VALUE_COLOR = DEFAULT_PALETTE.call
_UNDERLYING_LOSS_COLOR = DEFAULT_PALETTE.negative
_OFFSET_RATIO_COLOR = DEFAULT_PALETTE.orange

# ~6-7 labeled x-axis ticks regardless of how many points the curve has --
# 25 curve points do not need 25 labels.
_MAX_X_TICKS = 6


def _empty_figure() -> go.Figure:
    """Build the informative empty-state figure (5 empty traces)."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[], y=[], mode="lines", name="Net"))
    fig.add_trace(go.Scatter(x=[], y=[], mode="lines", name="Hedge value"))
    fig.add_trace(go.Scatter(x=[], y=[], mode="lines", name="Underlying loss"))
    fig.add_trace(
        go.Scatter(x=[], y=[], mode="lines", name="Offset ratio", yaxis="y2"),
    )
    fig.add_trace(go.Scatter(x=[], y=[], mode="markers", name="Scenario"))
    fig.update_layout(
        title="Crash Scenario Curve",
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


def _x_ticks(
    curve: list[ScenarioCurvePoint],
) -> tuple[list[float], list[str]]:
    """Pick a readable subset of points for the double-height x-axis labels.

    Subsamples the already-engine-returned ``shock_pct``/``shocked_spot_price``
    pairs — this is presentation subsetting, not a new computed number, so it
    belongs here rather than in the engine or the callback.

    Args:
        curve: The full curve, ascending by ``shock_pct``.

    Returns:
        ``(tickvals, ticktext)`` where each ``ticktext`` entry is
        ``"<+/-pct>%<br><spot>"``.

    """
    step = max(1, len(curve) // _MAX_X_TICKS)
    indices = list(range(0, len(curve), step))
    if indices[-1] != len(curve) - 1:
        indices.append(len(curve) - 1)

    tickvals = [curve[i].shock_pct for i in indices]
    ticktext = [
        f"{curve[i].shock_pct:+.0f}%<br>{curve[i].shocked_spot_price:,.0f}"
        for i in indices
    ]
    return tickvals, ticktext


def plot_scenario_curve(
    curve: list[ScenarioCurvePoint],
    *,
    marker_pct: float,
    marker_hedge_value: float,
    ips_crash_pct: float,
) -> go.Figure:
    """Four-series scenario curve vs. spot shock, with the scenario marker.

    Consumes :func:`~deltadewa.analysis.monitor_scenario.build_scenario_curve`'s
    output only — no portfolio or engine access here, purely a chart builder
    over already-computed numbers.

    Five traces, in this fixed order (load-bearing: the ``/monitor`` page's
    callbacks patch these traces by index):

    - ``data[0]``: net P&L (``hedge_gain + underlying_loss``) -- the most
      prominent series: heaviest weight, solid, ink-colored.
    - ``data[1]``: hedge value (a level, not a change) -- lighter, dashed.
    - ``data[2]``: underlying loss (signed P&L; negative = a loss) --
      lighter, dashed.
    - ``data[3]``: offset ratio, on the secondary right-hand y-axis (a
      ratio, not dollars) -- dotted; breaks at points near a 0% shock where
      the ratio is undefined (see
      :data:`~deltadewa.analysis.monitor_scenario._OFFSET_RATIO_MATERIAL_SHOCK_PCT`).
    - ``data[4]``: a single-point marker at ``(marker_pct,
      marker_hedge_value)`` -- the current scenario position on the hedge
      value line.

    Sign convention: ``underlying_loss`` and ``net`` are negative when the
    scenario loses money, positive when it gains -- labeled explicitly in
    the legend and axis title so a reader can tell direction at a glance.

    Also draws a vertical dotted reference line at *ips_crash_pct* (the
    policy anchor), matching the previous single-series version's style.

    Args:
        curve: Points from ``build_scenario_curve``. An empty list renders
            an informative empty-state figure rather than raising.
        marker_pct: Spot shock % of the current scenario position.
        marker_hedge_value: Repriced hedge value at *marker_pct*.
        ips_crash_pct: The IPS policy's crash scenario %, drawn as a
            vertical reference line.

    Returns:
        A Plotly ``Figure`` with the five traces described above.

    """
    if not curve:
        return _empty_figure()

    shock_pcts = [point.shock_pct for point in curve]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=shock_pcts,
            y=[point.net for point in curve],
            mode="lines",
            name="Net P&L (+ = protected)",
            line={"color": _NET_COLOR, "width": 3},
        ),
    )
    fig.add_trace(
        go.Scatter(
            x=shock_pcts,
            y=[point.hedge_value for point in curve],
            mode="lines",
            name="Hedge value",
            line={"color": _HEDGE_VALUE_COLOR, "width": 1.5, "dash": "dash"},
        ),
    )
    fig.add_trace(
        go.Scatter(
            x=shock_pcts,
            y=[point.underlying_loss for point in curve],
            mode="lines",
            name="Underlying loss (P&L)",
            line={
                "color": _UNDERLYING_LOSS_COLOR,
                "width": 1.5,
                "dash": "dash",
            },
        ),
    )
    fig.add_trace(
        go.Scatter(
            x=shock_pcts,
            y=[point.offset_ratio for point in curve],
            mode="lines",
            name="Offset ratio (hedge $ / loss $)",
            line={"color": _OFFSET_RATIO_COLOR, "width": 1.5, "dash": "dot"},
            yaxis="y2",
            connectgaps=False,
        ),
    )
    fig.add_trace(
        go.Scatter(
            x=[marker_pct],
            y=[marker_hedge_value],
            mode="markers",
            name="Scenario",
            marker={
                "color": _HEDGE_VALUE_COLOR,
                "size": 14,
                "symbol": "diamond",
                "line": {"color": _NET_COLOR, "width": 1.5},
            },
        ),
    )
    fig.add_vline(
        x=ips_crash_pct,
        line_dash="dot",
        line_color="grey",
        annotation_text="IPS anchor",
    )

    tickvals, ticktext = _x_ticks(curve)
    fig.update_layout(
        title="Crash Scenario Curve",
        xaxis_title="Shock (%) / spot price",
        xaxis_tickmode="array",
        xaxis_tickvals=tickvals,
        xaxis_ticktext=ticktext,
        yaxis_title="P&L / value ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=".3s",
        yaxis2={
            "title": "Offset ratio (x)",
            "overlaying": "y",
            "side": "right",
        },
    )
    return fig
