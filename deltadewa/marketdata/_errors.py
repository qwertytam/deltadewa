"""Typed exceptions for the marketdata subpackage."""

from __future__ import annotations


class MarketDataError(RuntimeError):
    """Raised when market data cannot be retrieved from any source."""


class MarketDataUnavailableError(MarketDataError):
    """Raised when no live or cached value exists for a request."""
