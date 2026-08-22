"""Cross-check the book's hand-entered spot against the observed market spot.

The book's ``portfolio.spot_price`` prices every position — crash convexity,
roll OTM%, every drift trigger, hedge value, the monetization gain — and
changes only on portfolio import (see #322). Nothing here feeds that
pricing; this module builds a labelled, independent second opinion for
``/monitor`` to display beside it, so a stale hand-entered spot stops
reading as current. See ``docs/market-data.md`` and #322/#336.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from deltadewa.analysis.market_environment import DataQuality
from deltadewa.marketdata import MarketDataError, Source

if TYPE_CHECKING:
    from datetime import datetime

    from deltadewa.marketdata import MarketDataProvider

_SOURCE_TO_QUALITY: Final[dict[Source, DataQuality]] = {
    Source.LIVE: DataQuality.LIVE,
    Source.CACHED: DataQuality.CACHED,
    Source.STALE: DataQuality.STALE,
    Source.STATIC: DataQuality.STATIC,
}


@dataclass(frozen=True)
class SpotReading:
    """The book's spot beside the last observed market spot, with provenance.

    Attributes:
        book_spot: ``portfolio.spot_price`` — the hand-entered value every
            page number is actually computed from.
        observed_spot: The cached market spot, or ``None`` iff ``quality``
            is ``DataQuality.UNAVAILABLE``.
        quality: ``CACHED``, ``STALE``, or ``UNAVAILABLE`` against a
            read-only provider — never ``LIVE`` (the deployed app never
            fetches) and never ``STATIC`` outside tests.
        as_of: The observed spot's source-series observation date. ``None``
            iff ``quality`` is ``UNAVAILABLE`` or ``STATIC``.
        fetched_at: When this deployment last retrieved ``observed_spot``.
            ``None`` under the same conditions as ``as_of``.

    """

    book_spot: float
    observed_spot: float | None
    quality: DataQuality
    as_of: datetime | None
    fetched_at: datetime | None

    @property
    def divergence_pct(self) -> float | None:
        """Signed ``(observed - book) / book`` as a percent.

        ``None`` when there is no observed spot to compare (``UNAVAILABLE``)
        or the book spot is zero, which would make the ratio meaningless
        rather than merely large.
        """
        if self.observed_spot is None or self.book_spot == 0:
            return None
        return (self.observed_spot - self.book_spot) / self.book_spot * 100


def observe_spot(
    provider: MarketDataProvider,
    *,
    symbol: str,
    book_spot: float,
) -> SpotReading:
    """Read the cached market spot for *symbol* against the book's *book_spot*.

    Never raises: a ``MarketDataError`` (no cache entry, the #293
    drift/missing-key case included) degrades to ``UNAVAILABLE`` rather than
    propagating. Deliberately not folded into ``assess_market_environment``
    — that function's single unbound ``except MarketDataError`` already
    blanks all four of its readings together on any one failure, and a spot
    miss must not additionally blank the vol-regime verdict.

    Args:
        provider: A market data provider — read-only in the deployed app,
            so this can reach ``CACHED``/``STALE``/``UNAVAILABLE`` but never
            ``LIVE``.
        symbol: The underlying to read the observed spot for.
        book_spot: ``portfolio.spot_price`` — the value being cross-checked.

    Returns:
        A ``SpotReading`` carrying both values and the observed one's
        provenance.

    """
    try:
        observation = provider.get_spot(symbol)
    except MarketDataError:
        return SpotReading(
            book_spot=book_spot,
            observed_spot=None,
            quality=DataQuality.UNAVAILABLE,
            as_of=None,
            fetched_at=None,
        )
    return SpotReading(
        book_spot=book_spot,
        observed_spot=observation.value,
        quality=_SOURCE_TO_QUALITY[observation.source],
        as_of=observation.as_of,
        fetched_at=observation.fetched_at,
    )
