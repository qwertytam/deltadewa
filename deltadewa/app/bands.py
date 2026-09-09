"""A horizontal "is this in range" band-bar display component.

Presentation-only, same category as ``visualization.crash_charts_plotly``:
maps already-computed numbers to display/layout, no engine calls. The
"band" (``low``/``high``) is never computed here — it's handed in from
values that already exist on ``ScenarioResult``/``RollStatusRecord``.
"""

from __future__ import annotations

from collections.abc import Callable

from dash import html

_DOMAIN_PAD_FRACTION = 0.25


def _default_fmt(value: float) -> str:
    """Format a label when the caller doesn't supply its own units."""
    return f"{value:.1f}"


def band_bar(
    *,
    value: float,
    low: float,
    high: float,
    fmt: Callable[[float], str] = _default_fmt,
) -> html.Div:
    """Build a horizontal "is this in range" bar, labelled at five points.

    A shaded good-zone ``[low, high]`` and a marker at *value*,
    colour-coded by whether *value* falls inside the zone. Five points
    are labelled so a reader isn't left inferring the scale from the
    prose above the bar: the track's own left/right extremes, ``low``,
    ``high``, and *value* itself at the marker.

    Domain is padded 25% beyond ``[low, high]`` on each side, and
    further extended to include *value* itself if *value* falls outside
    that padding — so the marker is always on the track, never clipped,
    and a wildly out-of-range value still reads as "far outside" rather
    than pinned to the edge.

    Args:
        value: The value to mark on the bar.
        low: The lower bound of the good zone.
        high: The upper bound of the good zone.
        fmt: Formats each of the five labels in the caller's own units
            — a percentage panel passes
            :func:`deltadewa.app.format.percent`, a dollar panel
            :func:`deltadewa.app.format.currency`. Defaults to one
            decimal place, unitless.

    Returns:
        An ``html.Div`` (class ``band-bar``) containing a ``.band-track``
        (``.band-good-zone``, ``.band-marker`` and the *value* label) and
        a ``.band-scale-labels`` row naming the track's own extremes,
        ``low`` and ``high``.

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
                    html.Span(
                        fmt(value),
                        className=(
                            "band-value-label "
                            f"band-value-label--{marker_modifier}"
                        ),
                        style={"left": f"{_pct(value)}%"},
                    ),
                ],
                className="band-track",
            ),
            html.Div(
                [
                    html.Span(
                        fmt(domain_low),
                        className="band-label band-label--edge-start",
                    ),
                    html.Span(
                        fmt(low),
                        className="band-label band-label--mid",
                        style={"left": f"{_pct(low)}%"},
                    ),
                    html.Span(
                        fmt(high),
                        className="band-label band-label--mid",
                        style={"left": f"{_pct(high)}%"},
                    ),
                    html.Span(
                        fmt(domain_high),
                        className="band-label band-label--edge-end",
                    ),
                ],
                className="band-scale-labels",
            ),
        ],
        className="band-bar",
    )
