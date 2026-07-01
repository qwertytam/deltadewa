"""Live MarketDataProvider pulling SPX/VIX/SKEW from CBOE CSVs and FRED."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from deltadewa.marketdata._errors import MarketDataError

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

    def get(self, key: str) -> Any | None:  # noqa: ANN401  # cache stores heterogeneous values (float, dict, str)
        """Return the cached value for *key* if present and within TTL."""
        entry = self._read(key)
        if entry is None:
            return None
        fetched_at = datetime.fromisoformat(entry["fetched_at"])
        if datetime.now(tz=UTC) - fetched_at > self.ttl:
            return None
        return entry["value"]

    def get_stale(self, key: str) -> Any | None:  # noqa: ANN401  # cache stores heterogeneous values (float, dict, str)
        """Return the cached value for *key* regardless of TTL."""
        entry = self._read(key)
        return None if entry is None else entry["value"]

    def set(self, key: str, value: Any) -> None:  # noqa: ANN401  # cache stores heterogeneous values (float, dict, str)
        """Write *value* for *key*, stamped with the current time."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "value": value,
            "fetched_at": datetime.now(tz=UTC).isoformat(),
        }
        self._path(key).write_text(json.dumps(entry))


class CboeFredProvider:
    """Live ``MarketDataProvider`` sourced from CBOE CSVs and FRED.

    Caches each successful response to disk with a short TTL. On request
    failure, falls back to the last cached value (regardless of TTL); if no
    cached value exists, raises ``MarketDataError``.
    """

    is_live: bool = True

    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl: timedelta = timedelta(minutes=15),
        session: requests.Session | None = None,
        fred_api_key: str | None = None,
    ) -> None:
        """Initialize the provider.

        Args:
            cache_dir: Directory for the disk cache. Defaults to
                ``~/.cache/deltadewa/marketdata/``.
            ttl: How long a cached value is considered fresh.
            session: Optional ``requests.Session`` to use (for testing or
                custom transport config). Defaults to a new ``Session``.
            fred_api_key: Reserved for future use of FRED's JSON API; the
                CSV endpoint used here does not require a key.

        """
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "deltadewa" / "marketdata"
        self._cache = _DiskCache(cache_dir=cache_dir, ttl=ttl)
        self._session = session or requests.Session()
        self._fred_api_key = fred_api_key

    def get_spot(self, symbol: str) -> float:
        """Return the latest spot price for *symbol* from CBOE."""
        return self._get_cboe_spot(symbol)

    def get_vix(self) -> float:
        """Return the latest VIX level from FRED's VIXCLS series."""
        series = self._request_with_fallback(
            "vix_fred",
            lambda: self._fetch_fred_history("VIXCLS"),
        )
        return float(series[-1][1])

    def get_vix_term_structure(self) -> dict[str, float]:
        """Return VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels keyed by index name."""
        return {
            name: self._get_cboe_spot(symbol)
            for name, symbol in _VIX_TERM_STRUCTURE_SYMBOLS.items()
        }

    def _get_cboe_spot(self, symbol: str) -> float:
        series = self._request_with_fallback(
            f"spot_{symbol}",
            lambda: self._fetch_cboe_history(symbol),
        )
        return float(series[-1][1])

    def get_skew_index(self) -> float:
        """Return the current CBOE SKEW index level."""
        return self._get_cboe_spot("SKEW")

    def get_skew_percentile(self, lookback_days: int = 252) -> float:
        """Return the SKEW index's percentile rank over *lookback_days*."""
        series = self._request_with_fallback(
            "spot_SKEW",
            lambda: self._fetch_cboe_history("SKEW"),
        )
        values = [value for _, value in series[-lookback_days:]]
        latest = values[-1]
        rank = sum(1 for value in values if value <= latest)
        return rank / len(values)

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
        fetch: Callable[[], Any],
    ) -> Any:  # noqa: ANN401  # strategy result dispatched at runtime; type not statically known
        """Try a live fetch, then cache, then fall back to a stale value."""
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            value = fetch()
        except requests.RequestException as exc:
            stale = self._cache.get_stale(cache_key)
            if stale is not None:
                return stale
            raise MarketDataError(
                f"Could not fetch '{cache_key}' and no cached value exists",
            ) from exc

        self._cache.set(cache_key, value)
        return value
