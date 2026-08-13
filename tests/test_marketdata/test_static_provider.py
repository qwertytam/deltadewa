"""Tests for deltadewa.marketdata.static_provider."""

import pytest

from deltadewa.marketdata import (
    MarketDataUnavailableError,
    Source,
    StaticProvider,
)


class TestStaticProvider:
    """Tests for StaticProvider."""

    def test_get_spot_returns_registered_price(self) -> None:
        """Test that get_spot returns the price registered for a symbol."""
        provider = StaticProvider(spot_prices={"SPX": 5000.0})

        assert provider.get_spot("SPX").value == pytest.approx(5000.0, rel=1e-2)

    def test_get_spot_raises_for_unknown_symbol(self) -> None:
        """Test that get_spot raises for an unregistered symbol."""
        provider = StaticProvider(spot_prices={"SPX": 5000.0})

        with pytest.raises(MarketDataUnavailableError):
            provider.get_spot("AAPL")

    def test_get_vix_returns_configured_value(self) -> None:
        """Test that get_vix returns the configured VIX level."""
        provider = StaticProvider(vix=22.5)

        assert provider.get_vix().value == pytest.approx(22.5, rel=1e-4)

    def test_get_vix_term_structure_returns_all_keys(self) -> None:
        """Test that get_vix_term_structure returns all expected keys."""
        provider = StaticProvider()

        term_structure = provider.get_vix_term_structure().value

        assert set(term_structure) == {
            "VIX9D",
            "VIX",
            "VIX3M",
            "VIX6M",
            "VIX1Y",
        }

    def test_get_vix_term_structure_returns_a_copy(self) -> None:
        """Test that mutating the returned dict does not affect state."""
        provider = StaticProvider()

        term_structure = provider.get_vix_term_structure().value
        term_structure["VIX"] = -1.0

        assert provider.get_vix_term_structure().value["VIX"] != pytest.approx(
            -1.0, rel=1e-4
        )

    def test_get_skew_index_returns_configured_value(self) -> None:
        """Test that get_skew_index returns the configured value."""
        provider = StaticProvider(skew_index=135.0)

        assert provider.get_skew_index().value == pytest.approx(135.0, rel=1e-5)

    def test_get_skew_percentile_ignores_lookback_days(self) -> None:
        """Test that get_skew_percentile returns the fixed value."""
        provider = StaticProvider(skew_percentile=0.75)

        assert provider.get_skew_percentile(
            lookback_days=30
        ).value == pytest.approx(0.75, rel=1e-4)
        assert provider.get_skew_percentile(
            lookback_days=500
        ).value == pytest.approx(0.75, rel=1e-4)

    def test_get_vix_history_raises_when_empty(self) -> None:
        """The default offline provider carries no history -> raises.

        This is the honest fallback signal: vol-regime callers catch it and
        report a labelled normalized figure, never a fabricated percentile.
        """
        with pytest.raises(MarketDataUnavailableError):
            StaticProvider().get_vix_history()

    def test_get_vix_history_returns_injected_window(self) -> None:
        """Injected history is returned, trimmed to the lookback window."""
        provider = StaticProvider(vix_history=[10.0, 20.0, 30.0, 40.0])

        assert provider.get_vix_history(lookback_days=2).value == [30.0, 40.0]
        assert provider.get_vix_history(lookback_days=99).value == [
            10.0,
            20.0,
            30.0,
            40.0,
        ]

    def test_get_vix_history_returns_a_copy(self) -> None:
        """Mutating the returned list does not affect provider state."""
        provider = StaticProvider(vix_history=[10.0, 20.0])

        history = provider.get_vix_history().value
        history.append(-1.0)

        assert provider.get_vix_history().value == [10.0, 20.0]

    def test_is_read_only_is_always_true(self) -> None:
        """StaticProvider performs no I/O, so it is trivially read-only."""
        assert StaticProvider().is_read_only is True


class TestStaticProviderProvenance:
    """Every StaticProvider reading is STATIC and carries no timestamps."""

    def test_every_reading_is_static(self) -> None:
        """No accessor can hand back a value labelled as observed."""
        provider = StaticProvider(
            spot_prices={"SPX": 5000.0},
            vix_history=[10.0, 20.0],
        )

        observations = [
            provider.get_spot("SPX"),
            provider.get_vix(),
            provider.get_vix_history(),
            provider.get_vix_term_structure(),
            provider.get_skew_index(),
            provider.get_skew_percentile(),
        ]

        assert all(obs.source is Source.STATIC for obs in observations)

    def test_static_readings_carry_no_timestamps(self) -> None:
        """A made-up number has no as-of date, and says so."""
        provider = StaticProvider(spot_prices={"SPX": 5000.0})

        spot = provider.get_spot("SPX")

        assert spot.as_of is None
        assert spot.fetched_at is None
