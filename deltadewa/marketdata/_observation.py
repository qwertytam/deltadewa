"""Provenance-carrying market data values.

Every ``MarketDataProvider`` method returns an ``Observation`` rather than a
bare number, so a caller cannot drop provenance by omission — there is no
parallel accessor yielding the value without its source and as-of date.

Two timestamps are tracked, and they answer different questions:

``as_of``
    The observation date of the datum itself, read from the source series.
    VIXCLS is a daily close, so a successful fetch at 10am Monday returns
    *Friday's* close: zero seconds old as a fetch, three days old as market
    data. This is the timestamp a stale-data banner must show.

``fetched_at``
    When this process retrieved the value. Distinguishes a fresh download
    from a cache hit; says nothing about how old the data itself is.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime


class Source(StrEnum):
    """Where a single market data value actually came from."""

    LIVE = "LIVE"
    """Fetched over the network on this call."""
    CACHED = "CACHED"
    """Served from the disk cache, within its TTL."""
    STALE = "STALE"
    """Served from the disk cache past its TTL, the live fetch having failed."""
    STATIC = "STATIC"
    """Synthetic or user-supplied; no observation date exists."""


_SOURCE_SEVERITY: Final[dict[Source, int]] = {
    Source.LIVE: 0,
    Source.CACHED: 1,
    Source.STALE: 2,
    Source.STATIC: 3,
}


def worst_source(sources: Iterable[Source]) -> Source:
    """Return the least trustworthy source in *sources*.

    Ordering is ``LIVE < CACHED < STALE < STATIC``. Used when one reading is
    assembled from several observations (the VIX term structure, or a whole
    ``MarketEnvironment``) — the combined reading is only as good as its
    weakest input.

    Args:
        sources: The sources to combine. Must be non-empty.

    Returns:
        The source with the highest severity.

    Raises:
        ValueError: If *sources* is empty — there is no honest answer.

    """
    ordered = sorted(sources, key=lambda source: _SOURCE_SEVERITY[source])
    if not ordered:
        raise ValueError("worst_source() requires at least one source")
    return ordered[-1]


T = TypeVar("T")


@dataclass(frozen=True)
class Observation(Generic[T]):
    """A market data value together with where and when it came from.

    Generic over the payload because provenance belongs to the *series*, not
    to each element: a VIX history is one ``Observation[list[float]]``, not a
    list of observations.

    Attributes:
        value: The observed value.
        source: Where this value came from.
        as_of: Observation date of the datum itself. ``None`` if and only if
            ``source`` is ``STATIC``.
        fetched_at: When this process retrieved the value. ``None`` if and
            only if ``source`` is ``STATIC``.

    """

    value: T
    source: Source
    as_of: datetime | None
    fetched_at: datetime | None

    def __post_init__(self) -> None:
        """Enforce ``STATIC`` if and only if the timestamps are absent.

        Without this, a missing ``as_of`` on a live source would read as
        "unknown" and quietly pass for fresh.

        Raises:
            ValueError: If the timestamps disagree with ``source``.

        """
        is_static = self.source is Source.STATIC
        has_stamp = self.as_of is not None or self.fetched_at is not None
        if is_static and has_stamp:
            raise ValueError(
                f"STATIC observation must carry no timestamps, got "
                f"as_of={self.as_of!r}, fetched_at={self.fetched_at!r}",
            )
        if not is_static and (self.as_of is None or self.fetched_at is None):
            raise ValueError(
                f"{self.source} observation requires both timestamps, got "
                f"as_of={self.as_of!r}, fetched_at={self.fetched_at!r}",
            )

    @classmethod
    def static(cls, value: T) -> Observation[T]:
        """Build a ``STATIC`` observation of *value*, with no timestamps."""
        return cls(
            value=value,
            source=Source.STATIC,
            as_of=None,
            fetched_at=None,
        )

    @classmethod
    def combine(
        cls,
        value: T,
        parts: Iterable[Observation[Any]],
    ) -> Observation[T]:
        """Wrap *value* with the weakest provenance among *parts*.

        For readings assembled from several inputs — a VIX term structure, or
        a whole ``MarketEnvironment``. Takes the worst source and the *oldest*
        timestamps, so the combined reading never looks fresher than its
        stalest ingredient. A single ``STATIC`` part makes the whole reading
        ``STATIC``: a number that was made up has no meaningful as-of date.

        Args:
            value: The combined value.
            parts: The observations it was derived from. Must be non-empty.

        Returns:
            *value* stamped with the combined provenance.

        Raises:
            ValueError: If *parts* is empty.

        """
        materialized = list(parts)
        if not materialized:
            raise ValueError("combine() requires at least one observation")
        source = worst_source(part.source for part in materialized)
        if source is Source.STATIC:
            return cls.static(value)
        # Not STATIC means no part was STATIC, so every part has timestamps.
        return cls(
            value=value,
            source=source,
            as_of=min(p.as_of for p in materialized if p.as_of is not None),
            fetched_at=min(
                p.fetched_at for p in materialized if p.fetched_at is not None
            ),
        )
