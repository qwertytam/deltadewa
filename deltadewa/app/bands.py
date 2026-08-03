"""A horizontal "is this in range" band-bar display component.

Presentation-only, same category as ``visualization.crash_charts_plotly``:
maps already-computed numbers to display/layout, no engine calls. The
"band" (``low``/``high``) is never computed here — it's handed in from
values that already exist on ``ScenarioResult``/``RollStatusRecord``.
"""

from __future__ import annotations

from dash import html

_DOMAIN_PAD_FRACTION = 0.25


def band_bar(*, value: float, low: float, high: float) -> html.Div:
    """Build a horizontal "is this in range" bar.

    A shaded good-zone ``[low, high]`` and a marker at *value*,
    colour-coded by whether *value* falls inside the zone.

    Domain is padded 25% beyond ``[low, high]`` on each side, and
    further extended to include *value* itself if *value* falls outside
    that padding — so the marker is always on the track, never clipped,
    and a wildly out-of-range value still reads as "far outside" rather
    than pinned to the edge.

    Args:
        value: The value to mark on the bar.
        low: The lower bound of the good zone.
        high: The upper bound of the good zone.

    Returns:
        An ``html.Div`` (class ``band-bar``) containing a ``.band-track``
        with a ``.band-good-zone`` and a ``.band-marker``.

    Raises:
        ValueError: If ``low >= high``.

    """
    if low >= high:
        msg = f"low ({low}) must be < high ({high})"
        raise ValueError(msg)

    span = high - low
    pad = span * _DOMAIN_PAD_FRACTION
    domain_low = min(low - pad, value)
    domain_high = max(high + pad, value)
    domain_span = domain_high - domain_low

    def _pct(point: float) -> float:
        return (point - domain_low) / domain_span * 100

    within = low <= value <= high
    marker_modifier = "within" if within else "outside"

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        className="band-good-zone",
                        style={
                            "left": f"{_pct(low)}%",
                            "width": f"{_pct(high) - _pct(low)}%",
                        },
                    ),
                    html.Div(
                        className=(
                            f"band-marker band-marker--{marker_modifier}"
                        ),
                        style={"left": f"{_pct(value)}%"},
                    ),
                ],
                className="band-track",
            ),
        ],
        className="band-bar",
    )
