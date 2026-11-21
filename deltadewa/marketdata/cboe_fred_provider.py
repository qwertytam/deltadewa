"""Live MarketDataProvider pulling SPX/VIX/SKEW from CBOE CSVs and FRED."""

from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar

import pandas as pd
import requests

from deltadewa.ips_config import ChainSource
from deltadewa.marketdata._errors import MarketDataError
from deltadewa.marketdata._observation import Observation, Source
from deltadewa.marketdata._policy import default_cache_dir, resolve_data_ttl
from deltadewa.marketdata.chain import (
    ChainSnapshot,
    parse_cboe_chain,
    payload_session_date,
)
from deltadewa.marketdata.marketdata_chain import (
    fetch_marketdata_chain,
    marketdata_session_date,
    parse_marketdata_chain,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from deltadewa.ips_config import IpsConfig

_logger = logging.getLogger(__name__)

_CBOE_HISTORY_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{symbol}_History.csv"
_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
_CBOE_CHAIN_URL = (
    "https://cdn.cboe.com/api/global/delayed_quotes/options/_{underlying}.json"
)

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

# The SPX chain is a ~13 MB download (about 1.8 MB gzipped), not a CSV row.
_CHAIN_TIMEOUT_SECONDS = 60

# The only chain the parser understands: its roots are SPX's (chain.py).
_CHAIN_UNDERLYING = "SPX"

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


def _new_session_rule(
    session_of: Callable[[Mapping[str, Any]], date | None],
) -> Callable[[Any, Any], bool]:
    """Build the ``.prev`` rotation rule for one chain source's payloads."""

    def is_new_session(existing: Any, new: Any) -> bool:  # ruff: ignore[any-type]  # raw cached payloads
        """Whether *new* is a different trading session from *existing*.

        An unreadable existing payload has no session, so it is not worth
        keeping; a new payload that cannot be dated (it was parsed before it
        got here, so this is unreachable in the job) rotates, the safe side
        of "keep one more".
        """
        old_session = (
            session_of(existing) if isinstance(existing, dict) else None
        )
        if old_session is None:
            return False
        new_session = session_of(new) if isinstance(new, dict) else None
        return new_session is None or new_session != old_session

    return is_new_session


#: The rotation rule for Cboe's payloads (dated by their ``timestamp``).
_is_new_session = _new_session_rule(payload_session_date)

#: The rotation rule for MarketData payloads (dated by the session asked for).
_is_new_md_session = _new_session_rule(marketdata_session_date)


@dataclass(frozen=True)
class _CacheHit:
    """A cached value together with when it was written.

    ``value`` is whatever JSON round-tripped out of the cache file; callers
    narrow it (see ``_as_series``).
    """

    value: Any
    fetched_at: datetime


@dataclass(frozen=True)
class _Resolved(Generic[T]):
    """A resolved value plus the provenance of how it was obtained."""

    value: T
    source: Source
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

    def signature(self, key: str) -> tuple[int, int] | None:
        """Return ``(mtime_ns, size)`` of *key*'s file, or ``None``.

        Lets a caller holding a parsed copy of a large entry notice that the
        file has not changed without reading and decoding it again.
        """
        try:
            stat = self._path(key).stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def set(
        self,
        key: str,
        value: Any,  # ruff: ignore[any-type]  # cache stores heterogeneous values (float, dict, str)
        *,
        keep_previous: bool | Callable[[Any, Any], bool] = False,
    ) -> datetime:
        """Write *value* for *key*, stamped with the current time.

        The write is atomic: the entry is written to a temporary file in the
        same directory and renamed over the old one, so a reader (the
        read-only app) sees either the whole old entry or the whole new one,
        never a half-written file. That matters for the ~13 MB option chain.

        Args:
            key: The cache key.
            value: A JSON-serialisable value.
            keep_previous: When ``True`` and an entry already exists, first
                copy it to ``<key>.prev.json``, so the last good payload
                survives one further refresh. A callable is asked instead,
                with the existing entry's value and *value*, and rotates
                only when it returns ``True``: the option chain passes
                "the new payload is a different trading session", so
                ``.prev`` is the previous session, not whatever the
                previous fetch happened to be (two runs in one evening
                would otherwise leave ``.prev`` equal to tonight).

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
        path = self._path(key)
        temporary = path.with_name(path.name + ".tmp")
        try:
            temporary.write_text(json.dumps(entry))
            if self._should_rotate(key, value, keep_previous):
                previous = path.with_name(f"{key}.prev.json")
                staged = previous.with_name(previous.name + ".tmp")
                shutil.copyfile(path, staged)
                staged.replace(previous)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return fetched_at

    def _should_rotate(
        self,
        key: str,
        value: Any,  # ruff: ignore[any-type]  # same heterogeneous cache value as set()
        keep_previous: bool | Callable[[Any, Any], bool],
    ) -> bool:
        """Whether the entry *value* replaces should be kept as ``.prev``."""
        if keep_previous is False or not self._path(key).exists():
            return False
        if keep_previous is True:
            return True
        existing = self._read(key)
        return existing is not None and keep_previous(
            existing.get("value"),
            value,
        )


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
        chain_source: ChainSource = ChainSource.CBOE,
        marketdata_token: str | None = None,
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
            chain_source: Where :meth:`get_option_chain` fetches from and
                which cache entry it reads (``pricing_feed.chain_source``;
                :func:`read_only_provider_for` and the refresh job pass the
                policy's value). ``none`` makes it raise.
            marketdata_token: The MarketData.app API token, needed only to
                *fetch* with ``chain_source: marketdata``; a read-only
                provider never needs it.

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
        self._chain_source = chain_source
        self._marketdata_token = marketdata_token
        self._chain_memo: dict[
            str,
            tuple[tuple[int, int] | None, datetime, ChainSnapshot],
        ] = {}

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
        lookback_days: int,
    ) -> Observation[float]:
        """Return the SKEW index's percentile rank over *lookback_days*.

        See ``MarketDataProvider.get_skew_percentile``. Cboe publishes SKEW
        history back to 1990-01-02 and the whole series is cached, so any
        policy window up to decades is servable without another download.

        Raises:
            MarketDataError: If the cached/fetched series holds fewer than
                *lookback_days* sessions (#317) — ranking whatever rows
                happen to exist would label a short-sample percentile with
                a window it was never computed over.

        """
        fetched = self._request_skew()
        if len(fetched.series) < lookback_days:
            raise MarketDataError(
                f"SKEW history holds {len(fetched.series)} sessions, fewer "
                f"than the {lookback_days}-session percentile window; "
                "refusing to rank a truncated sample",
            )
        rows = fetched.series[-lookback_days:]
        values = [value for _, value in rows]
        latest = values[-1]
        rank = sum(1 for value in values if value <= latest)
        return fetched.observe(rank / len(values), rows)

    def get_rate(self, series: str) -> Observation[float]:
        """Return the latest yield of FRED constant-maturity *series*.

        The value is the yield in **percent** as FRED publishes it (``4.60``
        for 4.60%); ``deltadewa.analysis.implied_vol.cmt_to_continuous``
        turns it into the continuously compounded rate the engine takes.
        FRED publishes about a business day behind, so ``as_of`` is
        routinely a day older than ``fetched_at``.
        """
        fetched = self._request_with_fallback(
            f"rate_{series}",
            lambda: self._fetch_fred_history(series),
        )
        rows = fetched.series
        return fetched.observe(float(rows[-1][1]), rows)

    def get_option_chain(self, underlying: str) -> Observation[ChainSnapshot]:
        """Return the option chain for *underlying*, from the chain source.

        ``cboe``: Cboe's delayed-quote payload, cached as ``chain_<UND>``.
        ``marketdata``: MarketData.app's chain for the last fully closed
        session (``deltadewa.marketdata.marketdata_chain``), cached as
        ``mdchain_<UND>``. Each source has its own entry, so a chain one
        source left behind is never read as the other's. The raw payload is
        cached, with the previous session's copy kept as ``.prev``, and
        parsed on read. A payload that fails to parse never replaces a good
        cache entry: the parse runs inside the fetch, before the write. The
        parsed snapshot is memoised on the cache file's identity, so a
        read-only app does not decode megabytes on every page render.

        Raises:
            MarketDataError: If *underlying* is not ``SPX``, the chain source
                is ``none``, or no chain can be fetched or read from cache.

        """
        if underlying != _CHAIN_UNDERLYING:
            raise MarketDataError(
                f"option chains are supported for {_CHAIN_UNDERLYING} only, "
                f"not {underlying!r}",
            )
        if self._chain_source is ChainSource.NONE:
            raise MarketDataError(
                "no option chain source is configured "
                "(pricing_feed.chain_source: none)",
            )
        if self._chain_source is ChainSource.MARKETDATA:
            key = f"mdchain_{underlying}"
            parse = parse_marketdata_chain
            rotate = _is_new_md_session

            def download() -> dict[str, Any]:
                return fetch_marketdata_chain(
                    self._session,
                    token=self._marketdata_token,
                    underlying=underlying,
                    now=datetime.now(tz=UTC),
                )

        else:
            key = f"chain_{underlying}"
            parse = parse_cboe_chain
            rotate = _is_new_session

            def download() -> dict[str, Any]:
                return self._download_chain(underlying)

        memoised = self._memoised_chain(key)
        if memoised is not None:
            return memoised
        parsed: dict[str, ChainSnapshot] = {}

        def fetch() -> dict[str, Any]:
            payload = download()
            parsed["snapshot"] = parse(payload)
            return payload

        resolved = self._resolve(
            key,
            fetch,
            decode=lambda raw: raw,
            keep_previous=rotate,
        )
        snapshot = parsed.get("snapshot")
        if snapshot is None:
            snapshot = parse(resolved.value)
        self._chain_memo[key] = (
            self._cache.signature(key),
            resolved.fetched_at,
            snapshot,
        )
        return Observation(
            value=snapshot,
            source=resolved.source,
            as_of=snapshot.quoted_at,
            fetched_at=resolved.fetched_at,
        )

    def _memoised_chain(self, key: str) -> Observation[ChainSnapshot] | None:
        """Return the parsed chain again if its cache file is unchanged.

        Only where the answer cannot differ from the full ladder's: a read
        that would not fetch (read-only, or within the TTL).
        """
        memo = self._chain_memo.get(key)
        if memo is None:
            return None
        signature, fetched_at, snapshot = memo
        if signature is None or signature != self._cache.signature(key):
            return None
        within_ttl = datetime.now(tz=UTC) - fetched_at <= self._cache.ttl
        if self._force_fetch or not (within_ttl or self._read_only):
            return None
        return Observation(
            value=snapshot,
            source=Source.CACHED if within_ttl else Source.STALE,
            as_of=snapshot.quoted_at,
            fetched_at=fetched_at,
        )

    def _download_chain(self, underlying: str) -> dict[str, Any]:
        url = _CBOE_CHAIN_URL.format(underlying=underlying)
        response = self._session.get(url, timeout=_CHAIN_TIMEOUT_SECONDS)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketDataError(
                "option-chain response is not valid JSON",
            ) from exc
        if not isinstance(payload, dict):
            raise MarketDataError("option-chain response is not an object")
        return payload

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
        try:
            frame = pd.read_csv(StringIO(response.text))
            frame = frame[[date_col, value_col]].dropna()
            frame[value_col] = pd.to_numeric(frame[value_col], errors="coerce")
            frame = frame.dropna()
            # Sort chronologically regardless of date string format (CBOE
            # uses MM/DD/YYYY; FRED uses YYYY-MM-DD: a string sort would
            # mis-order CBOE).
            frame = frame.iloc[pd.to_datetime(frame[date_col]).argsort()]
            series = [
                (str(row[date_col]), float(row[value_col]))
                for _, row in frame.iterrows()
            ]
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            # A page that is not the CSV expected (a renamed column, an HTML
            # error body) is a failed fetch, not a crash: only
            # MarketDataError is contained per series by the refresh job,
            # and it falls back to the last cached value.
            raise MarketDataError(
                f"unreadable series response from {url}: {exc}",
            ) from exc
        if not series:
            raise MarketDataError(f"series response from {url} has no rows")
        return series

    def _request_with_fallback(
        self,
        cache_key: str,
        fetch: Callable[[], _Series],
    ) -> _Fetched:
        """Resolve a CSV series: live, then cache, then a stale value.

        See :meth:`_resolve` for the ladder; this wraps its result in the
        series-shaped ``_Fetched`` the CSV readings use.
        """
        resolved = self._resolve(cache_key, fetch, decode=_as_series)
        return _Fetched(
            series=resolved.value,
            source=resolved.source,
            fetched_at=resolved.fetched_at,
        )

    def _resolve(
        self,
        cache_key: str,
        fetch: Callable[[], T],
        *,
        decode: Callable[[Any], T],
        keep_previous: bool | Callable[[Any, Any], bool] = False,
    ) -> _Resolved[T]:
        """Try a live fetch, then cache, then fall back to a stale value.

        Each branch is labelled with the ``Source`` it actually represents,
        rather than the provider's type — a stale-cache fallback must not be
        indistinguishable from a fresh download at the return.

        Skips the fresh-cache check below entirely when constructed with
        ``force_fetch=True`` — see the constructor docstring.

        Args:
            cache_key: The disk-cache key.
            fetch: Downloads and returns the JSON-serialisable value. It
                may raise ``requests.RequestException`` or
                ``MarketDataError`` (a payload that downloaded but does not
                parse), and either falls back to the last cached value.
            decode: Turns a JSON-round-tripped cache value back into ``T``.
            keep_previous: Keep the entry this write replaces as
                ``<key>.prev.json``; see :meth:`_DiskCache.set` for the
                callable form.

        """
        if not self._force_fetch:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return _Resolved(
                    value=decode(cached.value),
                    source=Source.CACHED,
                    fetched_at=cached.fetched_at,
                )

        if self._read_only:
            stale = self._cache.get_stale(cache_key)
            if stale is not None:
                return _Resolved(
                    value=decode(stale.value),
                    source=Source.STALE,
                    fetched_at=stale.fetched_at,
                )
            raise MarketDataError(
                f"No cached value for '{cache_key}' and read_only=True"
                " forbids a live fetch",
            )

        try:
            value = fetch()
        except (requests.RequestException, MarketDataError) as exc:
            # The cause is kept: "could not fetch" alone left an operator
            # reading the refresh log with no way to tell a vendor block
            # from a missing token (9b). No error raised here carries a
            # credential: the one token is only ever sent in a header.
            stale = self._cache.get_stale(cache_key)
            if stale is not None:
                _logger.warning(
                    "%s: live fetch failed (%s); keeping the last cached value",
                    cache_key,
                    exc,
                )
                return _Resolved(
                    value=decode(stale.value),
                    source=Source.STALE,
                    fetched_at=stale.fetched_at,
                )
            raise MarketDataError(
                f"Could not fetch '{cache_key}' and no cached value "
                f"exists: {exc}",
            ) from exc

        fetched_at = self._cache.set(
            cache_key,
            value,
            keep_previous=keep_previous,
        )
        return _Resolved(
            value=value,
            source=Source.LIVE,
            fetched_at=fetched_at,
        )


def read_only_provider_for(ips_config: IpsConfig | None) -> CboeFredProvider:
    """Build the read-only provider every reader of the cache shares.

    The app, the weekly digest and the history CLI all read what the nightly
    refresh cached and must never fetch: same cache directory
    (``DELTADEWA_CACHE_DIR``), same freshness window (the IPS's
    ``data_ttl_minutes``, or the default without one), same chain source
    (``pricing_feed.chain_source``; ``none`` without the section). One
    construction, so the three cannot disagree about any of them.
    """
    feed = ips_config.pricing_feed if ips_config is not None else None
    return CboeFredProvider(
        cache_dir=default_cache_dir(),
        ttl=resolve_data_ttl(ips_config),
        read_only=True,
        chain_source=(
            feed.chain_source if feed is not None else ChainSource.NONE
        ),
    )
