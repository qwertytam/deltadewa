"""Shared chrome: the as-of stamp and provenance banner.

Rendered once, above the page content, so it appears identically on every
page regardless of route — a reader who lands on either page sees the same
honest answer to "how fresh is this."

Batch 3d / #367: the banner used to grade only ``MarketEnvironment`` — the
six *fetched* market readings — and said nothing about the four inputs a
book is actually **priced** on when they are hand-entered (spot, the
risk-free rate, the dividend yield, and per-leg implied volatility). It
now takes a ``ProvenanceLedger`` (``analysis.provenance``), which grades
both kinds of input side by side, so a stale hand-entered rate can turn
the banner the same way a stale VIX reading already does.

Two tiers, deliberately:

- The **stamp** is always present and never alarming — it names the
  fetched market data's own as-of/quality plus how many hand-entered
  inputs are within policy, so a healthy program shows a quiet line and
  no banner, indefinitely.
- The **banner** mounts only when ``ledger.needs_banner`` — the worst
  input across *both* channels is not ``Freshness.FRESH``. It never
  mounts for a merely ``CACHED`` fetched reading (the normal steady
  state), because #367 adding four more graded inputs must not make an
  already-conservative banner (#368) permanently on: every addition
  making the banner louder is the same false-green failure arriving by
  the opposite route — operators stop reading a banner that never turns
  off. One line, the single worst channel, naming the remedy — not one
  line per input.

Pure functions of an already-built ``ProvenanceLedger``; no market-data,
policy, or grading logic lives here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import html

from deltadewa.analysis.market_environment import DataQuality
from deltadewa.analysis.provenance import Freshness, InputKind
from deltadewa.clock import program_now

if TYPE_CHECKING:
    from deltadewa.analysis.provenance import ProvenanceLedger

_FETCHED_BANNER_TEXT: Final[dict[DataQuality, str]] = {
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

_FALLBACK_BANNER_TEXT: Final[str] = "MARKET DATA DEGRADED"


def _stamp_text(ledger: ProvenanceLedger) -> str:
    """Return the quiet, always-present as-of/quality/review-count line."""
    if ledger.market_data_as_of is None:
        market_part = f"No as-of date ({ledger.market_data_quality.value})"
    else:
        # Shown in the program's timezone, with the zone named rather than
        # assumed. A US desk reading "14:30 UTC" has to do the conversion
        # in their head to judge whether a feed is stale (#182); the
        # abbreviation comes from the zone itself, so it tracks DST.
        local = ledger.market_data_as_of.astimezone(program_now().tzinfo)
        market_part = (
            f"Data as of {local:%Y-%m-%d %H:%M %Z} "
            f"({ledger.market_data_quality.value}"
        )
        # #368: as_of is the *oldest* series' observation date — a fine
        # thing for VIX to lag behind on its own routine FRED schedule.
        # Naming when the pipeline itself last ran, and which series is
        # the laggard, is what let a 2026-08-25 field test tell that
        # apart from "the pipeline stopped": /health read 08-21, the
        # banner 08-20, /monitor's spot 08-23, and nothing said which of
        # those was merely a normal lag.
        if (
            ledger.market_data_fetched_at is not None
            and ledger.oldest_series is not None
        ):
            fetched_local = ledger.market_data_fetched_at.astimezone(
                program_now().tzinfo,
            )
            market_part += (
                f" · refreshed {fetched_local:%Y-%m-%d %H:%M %Z} "
                f"· oldest series: {ledger.oldest_series}"
            )
        market_part += ")"

    hand_entered = ledger.by_kind(InputKind.HAND_ENTERED)
    fresh_count = sum(
        1 for entry in hand_entered if entry.freshness is Freshness.FRESH
    )
    pricing_part = (
        f"Pricing inputs: {fresh_count}/{len(hand_entered)} reviewed "
        "within policy"
    )
    return f"{market_part} · {pricing_part}"


def _banner_text(ledger: ProvenanceLedger) -> str:
    """Return the banner text for the ledger's single worst channel."""
    worst = ledger.worst
    if worst is None:
        # Unreachable given needs_banner's own check, but build_chrome is
        # unguarded chrome shared by every page and /health — degrade to
        # a plain statement rather than ever raising here.
        return _FALLBACK_BANNER_TEXT
    if worst.kind is InputKind.FETCHED and worst.quality is not None:
        return _FETCHED_BANNER_TEXT.get(worst.quality, _FALLBACK_BANNER_TEXT)
    if worst.freshness is Freshness.AGING:
        return (
            f"STALE PRICING INPUT — {worst.label} was last confirmed "
            f"{worst.age_days}d ago (policy: {worst.max_age_days}d). "
            "Review and re-confirm it."
        )
    # HAND_ENTERED entries are never MISSING (see Freshness.MISSING's
    # docstring), so the only remaining case is UNKNOWN.
    return (
        f"UNCONFIRMED PRICING INPUT — {worst.label} has never been "
        "confirmed. Review and confirm it."
    )


def build_chrome(ledger: ProvenanceLedger) -> html.Div:
    """Build the shared header: an as-of stamp plus an unmissable banner.

    The stamp is always present. The banner mounts in addition, with a
    CSS class keyed to ``ledger.combined_quality`` (so an aging
    hand-entered input reads visually the same as a stale fetched one,
    and an unconfirmed one the same as a synthetic one), only when
    ``ledger.needs_banner`` is true.

    Args:
        ledger: The provenance ledger for this request — see
            ``analysis.provenance.build_provenance_ledger``.

    Returns:
        The chrome ``html.Div``, meant to be placed above page content.

    """
    children: list[html.Div] = [
        html.Div(_stamp_text(ledger), className="chrome-stamp"),
    ]
    if ledger.needs_banner:
        suffix = ledger.combined_quality.value.lower()
        banner_class = f"chrome-banner chrome-banner--{suffix}"
        children.append(html.Div(_banner_text(ledger), className=banner_class))
    return html.Div(children, className="chrome")
