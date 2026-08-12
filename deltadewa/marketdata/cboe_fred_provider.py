"""Live MarketDataProvider pulling SPX/VIX/SKEW from CBOE CSVs and FRED."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd
import requests

from deltadewa.marketdata._errors import MarketDataError
from deltadewa.marketdata._observation import Observation, Source
from deltadewa.marketdata._policy import default_cache_dir

_CBOE_HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

_VIX_TERM_STRUCTURE_SYMBOLS = {
    "VIX9D": "VIX9D",
    "VIX": "VIX",
    "VIX3M": "VIX3M",
    "VIX6M": "VIX6M",
    "VIX1Y": "VIX1Y",
}

# VIX-family CSVs are OHLCV and carry a CLOSE column. SPX, SKEW, and other
# CBOE price-only indices use the symbol name as the sole value column.
_CBOE_OHLCV_SYMBOLS: frozenset[str] = frozenset(_VIX_TERM_STRUCTURE_SYMBOLS)

_REQUEST_TIMEOUT_SECONDS = 10

# A fetched series: (observation date as written by the source, value).
_Series = list[tuple[str, float]]

T = TypeVar("T")


def _as_series(cached: Any) -> _Series:  # ruff: ignore[any-type]  # JSON round-trip erases the tuple type
    """Coerce a JSON-round-tripped cache payload back into a ``_Series``.

    ``json`` writes tuples as lists, so a cached series reads back as
    ``list[list[...]]``.
    """
    return [(str(row[0]), float(row[1])) for row in cached]


def _parse_as_of(raw: str) -> datetime:
    """Parse a source-supplied observation date into a UTC datetime.

    CBOE writes MM/DD/YYYY and FRED writes YYYY-MM-DD; both parse here.
    """
    return pd.Timestamp(raw).to_pydatetime().replace(tzinfo=UTC)


@dataclass(frozen=True)
class _CacheHit:
    """A cached value together with when it was written.

    ``value`` is whatever JSON round-tripped out of the cache file; callers
    narrow it (see ``_as_series``).
    """

    value: Any
    fetched_at: datetime


@dataclass(frozen=True)
class _Fetched:
    """A resolved series plus the provenance of how it was obtained."""

    series: _Series
    source: Source
    fetched_at: datetime

    def observe(self, value: T, rows: _Series) -> Observation[T]:
        """Stamp *value* with this fetch's provenance, dated from *rows*.

        ``as_of`` comes from the last row of *rows* — the observation date of
        the datum itself, which for a daily close is routinely older than
        ``fetched_at``.
        """
        return Observation(
            value=value,
            source=self.source,
            as_of=_parse_as_of(rows[-1][0]),
            fetched_at=self.fetched_at,
        )


@dataclass
class _DiskCache:
    """Small JSON-file cache keyed by request name, with a TTL.

    One JSON file per cache key, holding ``{"value": ..., "fetched_at": ...}``.
    """

    cache_dir: Path
    ttl: timedelta = timedelta(minutes=15)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            return None

    def get(self, key: str) -> _CacheHit | None:
        """Return the cached entry for *key* if present and within TTL."""
        hit = self.get_stale(key)
        if hit is None:
            return None
        if datetime.now(tz=UTC) - hit.fetched_at > self.ttl:
            return None
        return hit

    def get_stale(self, key: str) -> _CacheHit | None:
        """Return the cached entry for *key* regardless of TTL."""
        entry = self._read(key)
        if entry is None:
            return None
        return _CacheHit(
            value=entry["value"],
            fetched_at=datetime.fromisoformat(entry["fetched_at"]),
        )

    def set(self, key: str, value: Any) -> datetime:  # ruff: ignore[any-type]  # cache stores heterogeneous values (float, dict, str)
        """Write *value* for *key*, stamped with the current time.

        Returns:
            The timestamp written, so the caller can stamp the same instant
            onto the observation it is about to return.

        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        fetched_at = datetime.now(tz=UTC)
        entry = {
            "value": value,
            "fetched_at": fetched_at.isoformat(),
        }
        self._path(key).write_text(json.dumps(entry))
        return fetched_at


class CboeFredProvider:
    """Live ``MarketDataProvider`` sourced from CBOE CSVs and FRED.

    Caches each successful response to disk with a short TTL. On request
    failure, falls back to the last cached value (regardless of TTL); if no
    cached value exists, raises ``MarketDataError``.

    Every returned ``Observation`` is labelled with which of those three
    branches produced it (``LIVE``/``CACHED``/``STALE``), and carries the
    source series' own observation date as ``as_of`` — which for a daily
    close is routinely older than the fetch.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl: timedelta = timedelta(minutes=15),
        session: requests.Session | None = None,
        fred_api_key: str | None = None,
        *,
        read_only: bool = False,
        force_fetch: bool = False,
    ) -> None:
        """Initialize the provider.

        Args:
            cache_dir: Directory for the disk cache. Defaults to
                ``default_cache_dir()`` (``DELTADEWA_CACHE_DIR`` if set,
                else ``~/.cache/deltadewa/marketdata/``).
            ttl: How long a cached value is considered fresh. Only
                consulted when *force_fetch* is ``False``.
            session: Optional ``requests.Session`` to use (for testing or
                custom transport config). Defaults to a new ``Session``.
            fred_api_key: Reserved for future use of FRED's JSON API; the
                CSV endpoint used here does not require a key.
            read_only: When ``True``, never issues a live fetch — a fresh
                cache hit is still ``CACHED``, otherwise the last cached
                value is returned as ``STALE`` regardless of age, and
                ``MarketDataError`` is raised only if no cache exists at
                all. For a process (the Dash app) that must never depend
                on network reachability; a separate cron job is what's
                expected to keep the cache warm.
            force_fetch: When ``True``, skip the fresh-cache short-circuit
                on every request and always attempt a live fetch — a
                success still writes through to the cache and returns
                ``LIVE``; a failure still falls back to the last cached
                value as ``STALE`` (or raises ``MarketDataError`` if none
                exists), exactly as when *force_fetch* is ``False``. For
                the writer process that is supposed to keep the cache
                warm (``deltadewa.marketdata.refresh``): *ttl* is a
                read-side staleness policy for consumers like the
                read-only Dash app, not a write-side throttle on the
                process whose entire job is to re-observe. Mutually
                exclusive with *read_only* — there is nothing to force
                when live fetches are structurally disabled.

        Raises:
            ValueError: If both *force_fetch* and *read_only* are
                ``True``.

        """
        if force_fetch and read_only:
            raise ValueError(
                "force_fetch and read_only are mutually exclusive: "
                "read_only forbids the live fetch force_fetch demands",
            )
        if cache_dir is None:
            cache_dir = default_cache_dir()
        self._cache = _DiskCache(cache_dir=cache_dir, ttl=ttl)
        self._session = session or requests.Session()
        self._fred_api_key = fred_api_key
        self._read_only = read_only
        self._force_fetch = force_fetch

    @property
    def is_read_only(self) -> bool:
        """Whether this instance was constructed with ``read_only=True``."""
        return self._read_only

    def get_spot(self, symbol: str) -> Observation[float]:
        """Return the latest spot price for *symbol* from CBOE."""
        return self._get_cboe_spot(symbol)

    def get_vix(self) -> Observation[float]:
        """Return the latest VIX level from FRED's VIXCLS series."""
        fetched = self._request_vix()
        rows = fetched.series
        return fetched.observe(float(rows[-1][1]), rows)

    def get_vix_history(
        self,
        lookback_days: int = 252,
    ) -> Observation[list[float]]:
        """Return the last *lookback_days* VIXCLS closes, oldest first.

        Reuses the same cached FRED series ``get_vix`` reads — no extra
        download, and consistent provenance between the two. Values are in
        vol points.
        """
        fetched = self._request_vix()
        rows = fetched.series[-lookback_days:]
        return fetched.observe([value for _, value in rows], rows)

    def get_vix_term_structure(self) -> Observation[dict[str, float]]:
        """Return VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels keyed by index name.

        Fans out over five separate series, so the combined reading takes the
        weakest source and the oldest as-of among them.
        """
        legs = {
            name: self._get_cboe_spot(symbol)
            for name, symbol in _VIX_TERM_STRUCTURE_SYMBOLS.items()
        }
        return Observation.combine(
            {name: leg.value for name, leg in legs.items()},
            legs.values(),
        )

    def _request_vix(self) -> _Fetched:
        return self._request_with_fallback(
            "vix_fred",
            lambda: self._fetch_fred_history("VIXCLS"),
        )

    def _request_skew(self) -> _Fetched:
        # Distinct cache key from _get_cboe_spot("SKEW")'s "spot_SKEW" (#185
        # item 1): both currently fetch the same CBOE SKEW series, but the
        # spot reading and the percentile-rank reading are different
        # consumers with no reason to be forced onto the same TTL/refresh
        # if one of them ever needs to diverge (e.g. a longer lookback).
        return self._request_with_fallback(
            "skew_percentile_history",
            lambda: self._fetch_cboe_history("SKEW"),
        )

    def _get_cboe_spot(self, symbol: str) -> Observation[float]:
        fetched = self._request_with_fallback(
            f"spot_{symbol}",
            lambda: self._fetch_cboe_history(symbol),
        )
        rows = fetched.series
        return fetched.observe(float(rows[-1][1]), rows)

    def get_skew_index(self) -> Observation[float]:
        """Return the current CBOE SKEW index level."""
        return self._get_cboe_spot("SKEW")

    def get_skew_percentile(
        self,
        lookback_days: int = 252,
    ) -> Observation[float]:
        """Return the SKEW index's percentile rank over *lookback_days*."""
        fetched = self._request_skew()
        rows = fetched.series[-lookback_days:]
        values = [value for _, value in rows]
        latest = values[-1]
        rank = sum(1 for value in values if value <= latest)
        return fetched.observe(rank / len(values), rows)

    def _fetch_cboe_history(self, symbol: str) -> list[tuple[str, float]]:
        url = _CBOE_HISTORY_URL.format(symbol=symbol)
        value_col = "CLOSE" if symbol in _CBOE_OHLCV_SYMBOLS else symbol
        return self._fetch_csv_series(url, date_col="DATE", value_col=value_col)

    def _fetch_fred_history(self, series_id: str) -> list[tuple[str, float]]:
        url = _FRED_CSV_URL.format(series_id=series_id)
        # FRED's CSV export uses "observation_date" as the date column name.
        return self._fetch_csv_series(
            url,
            date_col="observation_date",
            value_col=series_id,
        )

    def _fetch_csv_series(
        self,
        url: str,
        date_col: str,
        value_col: str,
    ) -> list[tuple[str, float]]:
        response = self._session.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        frame = pd.read_csv(StringIO(response.text))
        frame = frame[[date_col, value_col]].dropna()
        frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
        frame = frame.dropna()
        # Sort chronologically regardless of date string format (CBOE uses
        # MM/DD/YYYY; FRED uses YYYY-MM-DD — string sort would mis-order CBOE).
        frame = frame.iloc[pd.to_datetime(frame[date_col]).argsort()]
        return [
            (str(row[date_col]), float(row[value_col]))
            for _, row in frame.iterrows()
        ]

    def _request_with_fallback(
        self,
        cache_key: str,
        fetch: Callable[[], _Series],
    ) -> _Fetched:
        """Try a live fetch, then cache, then fall back to a stale value.

        Each branch is labelled with the ``Source`` it actually represents,
        rather than the provider's type — a stale-cache fallback must not be
        indistinguishable from a fresh download at the return.

        Skips the fresh-cache check below entirely when constructed with
        ``force_fetch=True`` — see the constructor docstring.
        """
        if not self._force_fetch:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _Fetched(
                    series=_as_series(cached.value),
                    source=Source.CACHED,
                    fetched_at=cached.fetched_at,
                )

        if self._read_only:
            stale = self._cache.get_stale(cache_key)
            if stale is not None:
                return _Fetched(
                    series=_as_series(stale.value),
                    source=Source.STALE,
                    fetched_at=stale.fetched_at,
                )
            raise MarketDataError(
                f"No cached value for '{cache_key}' and read_only=True"
                " forbids a live fetch",
            )

        try:
            value = fetch()
        except requests.RequestException as exc:
            stale = self._cache.get_stale(cache_key)
            if stale is not None:
                return _Fetched(
                    series=_as_series(stale.value),
                    source=Source.STALE,
                    fetched_at=stale.fetched_at,
                )
            raise MarketDataError(
                f"Could not fetch '{cache_key}' and no cached value exists",
            ) from exc

        fetched_at = self._cache.set(cache_key, value)
        return _Fetched(
            series=value,
            source=Source.LIVE,
            fetched_at=fetched_at,
        )
