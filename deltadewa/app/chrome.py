"""Shared chrome: the as-of stamp and STATIC/STALE provenance banner.

Rendered once, above the page content, so it appears identically on every
page regardless of route — a reader who lands on either page sees the same
honest answer to "how fresh is this."

Pure functions of an already-classified ``MarketEnvironment`` (from
``analysis.market_environment``); no market-data or metric logic lives here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import html

from deltadewa.analysis.market_environment import DataQuality

if TYPE_CHECKING:
    from deltadewa.analysis.market_environment import MarketEnvironment

_BANNER_QUALITIES = {
    DataQuality.STATIC,
    DataQuality.STALE,
    DataQuality.UNAVAILABLE,
}

_BANNER_TEXT = {
    DataQuality.STATIC: (
        "SYNTHETIC DATA — this reading was not observed from any market "
        "data source."
    ),
    DataQuality.STALE: (
        "STALE DATA — the live market feed is unavailable; showing the "
        "last cached reading."
    ),
    DataQuality.UNAVAILABLE: (
        "MARKET DATA UNAVAILABLE — no cached reading exists for this value."
    ),
}


def _stamp_text(environment: MarketEnvironment) -> str:
    """Return the quiet, always-present as-of/quality line."""
    if environment.as_of is None:
        return f"No as-of date ({environment.data_quality.value})"
    as_of = environment.as_of.strftime("%Y-%m-%d %H:%M UTC")
    return f"Data as of {as_of} ({environment.data_quality.value})"


def build_chrome(environment: MarketEnvironment) -> html.Div:
    """Build the shared header: an as-of stamp plus an unmissable banner.

    The stamp is always present. The banner mounts in addition, with a
    distinct CSS class per quality, only when ``environment.data_quality``
    is ``STATIC``, ``STALE``, or ``UNAVAILABLE`` — a made-up number, an old
    number, and no number at all are three different problems and must not
    look alike.

    Args:
        environment: The classified market snapshot for this request.

    Returns:
        The chrome ``html.Div``, meant to be placed above page content.

    """
    quality = environment.data_quality
    children: list[html.Div] = [
        html.Div(_stamp_text(environment), className="chrome-stamp"),
    ]
    if quality in _BANNER_QUALITIES:
        banner_class = f"chrome-banner chrome-banner--{quality.value.lower()}"
        children.append(html.Div(_BANNER_TEXT[quality], className=banner_class))
    return html.Div(children, className="chrome")
