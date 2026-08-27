"""Confirmation stamps for hand-entered book-level pricing inputs.

Batch 3d / #367: the provenance banner grades the six market readings the
program *fetches*, but says nothing about the inputs a book is actually
**priced** on when those inputs are hand-entered — spot, the risk-free
rate, and the dividend yield at the book level (per-leg implied
volatility is tracked separately, on ``OptionPosition.volatility_as_of``,
since it varies leg by leg).

What a stamp means
    "When a human last confirmed this value" — not "when the underlying
    datum was observed". There is no feed for a hand-entered rate to
    compare against, so this is the only honest signal available: an
    operator who types a rate on 2026-08-26 from a note written in June
    stamps 2026-08-26. That is still the review-cadence signal #367
    needs, and ``analysis.provenance`` grades it against
    ``ips_config.IpsPricingInputs``'s per-input maximum age.

When a stamp is (and isn't) set
    Setting a stamp is a side effect of a mutator actually **changing**
    the value it stamps — see ``OptionPortfolioBase.update_market_conditions``.
    A save-then-reload or a re-import of an unchanged file must not
    refresh a stamp, or every existing stale input would be laundered
    into looking freshly confirmed the next time the file happens to be
    re-saved.

    The portfolio-import path never stamps at all: it restores whatever
    stamp (or ``None``) was serialized, bypassing the mutators entirely
    — mirroring how ``entry_spot``/``entry_date`` are restored directly
    onto a freshly-added ``OptionPosition`` rather than re-derived. A
    position or book predating this feature has ``None`` stamps, which
    ``analysis.provenance`` reports as ``Freshness.UNKNOWN`` — a
    distinct, worse grade than a stamped-but-old value, never "fresh".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True)
class MarketParameterStamps:
    """When each book-level hand-entered pricing input was last confirmed.

    One stamp per input rather than one for the whole book: the three
    cadences differ (spot every session, dividend yield rarely), so
    ``ips_config.IpsPricingInputs`` grades each independently and a
    single combined timestamp would hide whichever input is actually
    stale behind whichever was confirmed most recently.

    All three default to ``None`` — a book built before this feature
    existed, or one whose inputs have never been explicitly re-confirmed
    since, carries no stamp at all rather than a fabricated one.
    """

    spot_as_of: datetime | None = None
    risk_free_rate_as_of: datetime | None = None
    dividend_yield_as_of: datetime | None = None
