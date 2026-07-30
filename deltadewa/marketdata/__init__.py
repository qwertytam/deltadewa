"""Vendor-neutral market data providers.

Exposes:
    MarketDataProvider: Structural protocol any provider must satisfy.
    StaticProvider: No-network provider for tests/offline use.
    CboeFredProvider: Live provider sourced from CBOE CSVs and FRED.
    MarketDataError: Raised when no live or cached data is available.
    MarketDataUnavailableError: Raised for an unregistered symbol/value.
    Observation: A value together with its source and as-of date.
    Source: Where a value came from (LIVE/CACHED/STALE/STATIC).
    worst_source: Combine several sources into the least trustworthy one.
"""

from deltadewa.marketdata._errors import (
    MarketDataError,
    MarketDataUnavailableError,
)
from deltadewa.marketdata._observation import (
    Observation,
    Source,
    worst_source,
)
from deltadewa.marketdata._protocols import MarketDataProvider
from deltadewa.marketdata.cboe_fred_provider import CboeFredProvider
from deltadewa.marketdata.static_provider import StaticProvider

__all__ = [
    "CboeFredProvider",
    "MarketDataError",
    "MarketDataProvider",
    "MarketDataUnavailableError",
    "Observation",
    "Source",
    "StaticProvider",
    "worst_source",
]
