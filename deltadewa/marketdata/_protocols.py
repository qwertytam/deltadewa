"""Structural protocol for vendor-neutral market data sources.

Unlike the other ``_protocols.py`` modules in this codebase (which describe
``self`` inside mixin compositions and are never instantiated), this one is
public API: callers depend on ``MarketDataProvider`` rather than a concrete
provider implementation.

Every method returns an ``Observation``. There is deliberately no parallel
accessor returning a bare number: provenance must not be droppable by
omission, and a provider's *type* (the old ``is_live`` flag) never described
what an individual fetch actually did.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from deltadewa.marketdata._observation import Observation


class MarketDataProvider(Protocol):
    """Structural type for any source of spot/vol/skew market data."""

    def get_spot(self, symbol: str) -> Observation[float]:
        """Return the latest spot price for *symbol*."""

    def get_vix(self) -> Observation[float]:
        """Return the current VIX level."""

    def get_vix_history(
        self,
        lookback_days: int = 252,
    ) -> Observation[list[float]]:
        """Return up to the last *lookback_days* VIX closes, oldest first.

        Values are in vol points (e.g. ``20.0``).

        Raises:
            MarketDataError: If no VIX history is available.

        """

    def get_vix_term_structure(self) -> Observation[dict[str, float]]:
        """Return VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels keyed by index name."""

    def get_skew_index(self) -> Observation[float]:
        """Return the current CBOE SKEW index level."""

    def get_skew_percentile(
        self,
        lookback_days: int = 252,
    ) -> Observation[float]:
        """Return the SKEW index's percentile rank over *lookback_days*."""
