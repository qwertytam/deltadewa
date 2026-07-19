"""Structural protocol for vendor-neutral market data sources.

Unlike the other ``_protocols.py`` modules in this codebase (which describe
``self`` inside mixin compositions and are never instantiated), this one is
public API: callers depend on ``MarketDataProvider`` rather than a concrete
provider implementation.
"""

from __future__ import annotations

from typing import Protocol


class MarketDataProvider(Protocol):
    """Structural type for any source of spot/vol/skew market data."""

    is_live: bool
    """True when the provider fetches real-time / near-real-time data."""

    def get_spot(self, symbol: str) -> float:
        """Return the latest spot price for *symbol*."""

    def get_vix(self) -> float:
        """Return the current VIX level."""

    def get_vix_history(self, lookback_days: int = 252) -> list[float]:
        """Return up to the last *lookback_days* VIX closes, oldest first.

        Values are in vol points (e.g. ``20.0``).

        Raises:
            MarketDataError: If no VIX history is available.

        """

    def get_vix_term_structure(self) -> dict[str, float]:
        """Return VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels keyed by index name."""

    def get_skew_index(self) -> float:
        """Return the current CBOE SKEW index level."""

    def get_skew_percentile(self, lookback_days: int = 252) -> float:
        """Return the SKEW index's percentile rank over *lookback_days*."""
