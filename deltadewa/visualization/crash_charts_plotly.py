"""Plotly crash-value-curve chart for the Dash monitor page.

Separate from :mod:`deltadewa.visualization.crash_charts` (matplotlib,
Jupyter-only) so the Jupyter/Dash split stays obvious — this module never
imports matplotlib, and the matplotlib module never imports plotly.
"""

from __future__ import annotations

import plotly.graph_objects as go

from deltadewa.colours import DEFAULT_PALETTE

_EMPTY_TEXT = "No scenario data"


def plot_crash_value_curve(
    curve: list[tuple[float, float]],
    *,
    marker_pct: float,
    marker_value: float,
    ips_crash_pct: float,
) -> go.Figure:
    """All-legs hedge value vs. spot shock, with the scenario marker.

    Consumes :func:`~deltadewa.analysis.crash_repricing.crash_value_curve`'s
    output only — no portfolio or engine access here, purely a chart
    builder over already-computed numbers.

    Two traces, in this fixed order (load-bearing: the ``/monitor``
    page's callbacks patch these traces by index):

    - ``data[0]``: the curve line (x=shock_pct, y=value), from *curve*.
    - ``data[1]``: a single-point marker at ``(marker_pct, marker_value)``
      — the current scenario position.

    Also draws a vertical dotted reference line at *ips_crash_pct* (the
    policy anchor), matching :func:`plot_crash_convexity`'s style in
    ``crash_charts.py``. Deliberately no target-band overlay — the
    convexity-%-of-notional band isn't expressible on this chart's axes
    (dollars vs. shock %); the monitor's DECISIONS section covers it in
    text instead.

    Args:
        curve: ``(shock_pct, repriced_value)`` pairs from
            ``crash_value_curve``. An empty list renders an informative
            empty-state figure rather than raising.
        marker_pct: Spot shock % of the current scenario position.
        marker_value: Repriced hedge value at *marker_pct*.
        ips_crash_pct: The IPS policy's crash scenario %, drawn as a
            vertical reference line.

    Returns:
        A Plotly ``Figure`` with the two traces described above.

    """
    fig = go.Figure()

    if not curve:
        fig.add_trace(go.Scatter(x=[], y=[], mode="lines", name="Curve"))
        fig.add_trace(
            go.Scatter(x=[], y=[], mode="markers", name="Scenario"),
        )
        fig.update_layout(
            title="Hedge Value vs Shock",
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

    xs = [shock_pct for shock_pct, _ in curve]
    ys = [value for _, value in curve]

    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines",
            name="Hedge value",
            line={"color": DEFAULT_PALETTE.call, "width": 2},
        ),
    )
    fig.add_trace(
        go.Scatter(
            x=[marker_pct],
            y=[marker_value],
            mode="markers",
            name="Scenario",
            marker={"color": DEFAULT_PALETTE.orange, "size": 12},
        ),
    )
    fig.add_vline(
        x=ips_crash_pct,
        line_dash="dot",
        line_color="grey",
        annotation_text="IPS anchor",
    )
    fig.update_layout(
        title="Hedge Value vs Shock",
        xaxis_title="Shock (%)",
        yaxis_title="Repriced Hedge Value ($)",
        xaxis_ticksuffix="%",
        yaxis_tickprefix="$",
        yaxis_tickformat=",.0f",
    )
    return fig
