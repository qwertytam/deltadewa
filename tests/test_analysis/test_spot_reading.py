"""Tests for deltadewa.analysis.spot_reading."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from deltadewa.analysis.market_environment import DataQuality
from deltadewa.analysis.spot_reading import SpotReading, observe_spot
from deltadewa.marketdata import MarketDataError, Observation, Source
from deltadewa.marketdata.static_provider import StaticProvider

_AS_OF = datetime(2026, 8, 21, tzinfo=UTC)
_FETCHED = datetime(2026, 8, 22, 6, 0, tzinfo=UTC)


class _StubSpotProvider:
    """MarketDataProvider stand-in returning one canned spot Observation."""

    def __init__(self, observation: Observation[float]) -> None:
        self._observation = observation

    def get_spot(self, symbol: str) -> Observation[float]:
        """Return the canned observation, ignoring *symbol*."""
        _ = symbol
        return self._observation


class _FailingSpotProvider:
    """MarketDataProvider stand-in where get_spot always raises."""

    def get_spot(self, symbol: str) -> Observation[float]:
        """Always raise, as a missing/expired cache key would."""
        raise MarketDataError(symbol)


class TestObserveSpot:
    """Tests for observe_spot."""

    def test_cached_reading_carries_value_and_provenance(self) -> None:
        """A CACHED observation maps straight through with its timestamps."""
        provider = _StubSpotProvider(
            Observation(
                value=5100.0,
                source=Source.CACHED,
                as_of=_AS_OF,
                fetched_at=_FETCHED,
            ),
        )
        reading = observe_spot(provider, symbol="SPX", book_spot=5000.0)
        assert reading == SpotReading(
            book_spot=5000.0,
            observed_spot=5100.0,
            quality=DataQuality.CACHED,
            as_of=_AS_OF,
            fetched_at=_FETCHED,
        )

    def test_stale_reading_maps_to_stale_quality(self) -> None:
        """A STALE observation (cache past TTL) maps to DataQuality.STALE."""
        provider = _StubSpotProvider(
            Observation(
                value=5100.0,
                source=Source.STALE,
                as_of=_AS_OF,
                fetched_at=_FETCHED,
            ),
        )
        reading = observe_spot(provider, symbol="SPX", book_spot=5000.0)
        assert reading.quality is DataQuality.STALE

    def test_market_data_error_degrades_to_unavailable(self) -> None:
        """A missing cache key never raises out of observe_spot."""
        reading = observe_spot(
            _FailingSpotProvider(),
            symbol="SPX",
            book_spot=5000.0,
        )
        assert reading == SpotReading(
            book_spot=5000.0,
            observed_spot=None,
            quality=DataQuality.UNAVAILABLE,
            as_of=None,
            fetched_at=None,
        )

    def test_static_provider_maps_to_static_quality(self) -> None:
        """StaticProvider (tests/offline) reads through as STATIC."""
        provider = StaticProvider(spot_prices={"SPX": 5050.0})
        reading = observe_spot(provider, symbol="SPX", book_spot=5000.0)
        assert reading.quality is DataQuality.STATIC
        assert reading.observed_spot == pytest.approx(5050.0)
        assert reading.as_of is None
        assert reading.fetched_at is None


class TestDivergencePct:
    """Tests for SpotReading.divergence_pct."""

    def test_observed_above_book_is_positive(self) -> None:
        """A higher observed spot than book is a positive divergence."""
        reading = SpotReading(
            book_spot=5000.0,
            observed_spot=5100.0,
            quality=DataQuality.CACHED,
            as_of=_AS_OF,
            fetched_at=_FETCHED,
        )
        assert reading.divergence_pct == pytest.approx(2.0)

    def test_observed_below_book_is_negative(self) -> None:
        """A lower observed spot than book is a negative divergence."""
        reading = SpotReading(
            book_spot=5000.0,
            observed_spot=4900.0,
            quality=DataQuality.CACHED,
            as_of=_AS_OF,
            fetched_at=_FETCHED,
        )
        assert reading.divergence_pct == pytest.approx(-2.0)

    def test_none_when_unavailable(self) -> None:
        """No observed spot means no divergence to report."""
        reading = SpotReading(
            book_spot=5000.0,
            observed_spot=None,
            quality=DataQuality.UNAVAILABLE,
            as_of=None,
            fetched_at=None,
        )
        assert reading.divergence_pct is None

    def test_none_when_book_spot_is_zero(self) -> None:
        """A zero book spot would make the ratio meaningless, not huge."""
        reading = SpotReading(
            book_spot=0.0,
            observed_spot=5100.0,
            quality=DataQuality.CACHED,
            as_of=_AS_OF,
            fetched_at=_FETCHED,
        )
        assert reading.divergence_pct is None
