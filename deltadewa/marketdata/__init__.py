"""Vendor-neutral market data providers.

Exposes:
    MarketDataProvider: Structural protocol any provider must satisfy.
    StaticProvider: No-network provider for tests/offline use.
    CboeFredProvider: Live provider sourced from CBOE CSVs and FRED.
    MarketDataError: Raised when no live or cached data is available.
    MarketDataUnavailableError: Raised for an unregistered symbol/value.
"""

from deltadewa.marketdata._errors import (
    MarketDataError,
    MarketDataUnavailableError,
)
from deltadewa.marketdata._protocols import MarketDataProvider
from deltadewa.marketdata.cboe_fred_provider import CboeFredProvider
from deltadewa.marketdata.static_provider import StaticProvider

__all__ = [
    "CboeFredProvider",
    "MarketDataError",
    "MarketDataProvider",
    "MarketDataUnavailableError",
    "StaticProvider",
]
