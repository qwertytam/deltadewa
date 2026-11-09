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

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from deltadewa.marketdata._observation import Observation


@runtime_checkable
class MarketDataProvider(Protocol):
    """Structural type for any source of spot/vol/skew market data."""

    @property
    def is_read_only(self) -> bool:
        """Whether this provider is incapable of a live network fetch.

        ``True`` for providers that only ever read cached/local/static data
        (``StaticProvider``; a ``CboeFredProvider`` constructed with
        ``read_only=True``). A consumer that must never depend on network
        reachability (e.g. ``deltadewa.app.factory.create_app``) checks this
        at construction rather than trusting a docstring.
        """

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
        lookback_days: int,
    ) -> Observation[float]:
        """Return the SKEW index's percentile rank over *lookback_days*.

        Inclusive rank (the fraction of the window at or below the latest
        close), as a 0-1 fraction. *lookback_days* is required, with no
        default: the window is policy
        (``IpsMarketEnvironment.skew_lookback_days``, #317), and the
        handbook permits any window only "provided it states the window
        every time it quotes a percentile" (`Skew Percentile
        <https://qwertytam.github.io/deltadewa-handbook/part-3/volatility-skew/#the-lookback-window>`_)
        — a default here would let a caller rank against a window no
        surface states.

        Raises:
            MarketDataError: If no SKEW history is available, or (for a
                provider that ranks a real series) if the series is
                shorter than *lookback_days* — a percentile ranked over
                fewer sessions than the window it is labelled with would
                be a silent truncation.

        """
