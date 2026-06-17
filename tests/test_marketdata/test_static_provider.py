"""Tests for deltadewa.marketdata.static_provider."""

import pytest

from deltadewa.marketdata import MarketDataUnavailableError, StaticProvider
from deltadewa.widgets.assumptions import GlobalAssumptions

# ruff: noqa: S101


class TestStaticProvider:
    """Tests for StaticProvider."""

    def test_get_spot_returns_registered_price(self) -> None:
        """Test that get_spot returns the price registered for a symbol."""
        provider = StaticProvider(spot_prices={"SPX": 5000.0})

        assert provider.get_spot("SPX") == 5000.0

    def test_get_spot_raises_for_unknown_symbol(self) -> None:
        """Test that get_spot raises for an unregistered symbol."""
        provider = StaticProvider(spot_prices={"SPX": 5000.0})

        with pytest.raises(MarketDataUnavailableError):
            provider.get_spot("AAPL")

    def test_get_vix_returns_configured_value(self) -> None:
        """Test that get_vix returns the configured VIX level."""
        provider = StaticProvider(vix=22.5)

        assert provider.get_vix() == 22.5

    def test_get_vix_term_structure_returns_all_keys(self) -> None:
        """Test that get_vix_term_structure returns all expected keys."""
        provider = StaticProvider()

        term_structure = provider.get_vix_term_structure()

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

        term_structure = provider.get_vix_term_structure()
        term_structure["VIX"] = -1.0

        assert provider.get_vix_term_structure()["VIX"] != -1.0

    def test_get_skew_index_returns_configured_value(self) -> None:
        """Test that get_skew_index returns the configured value."""
        provider = StaticProvider(skew_index=135.0)

        assert provider.get_skew_index() == 135.0

    def test_get_skew_percentile_ignores_lookback_days(self) -> None:
        """Test that get_skew_percentile returns the fixed value."""
        provider = StaticProvider(skew_percentile=0.75)

        assert provider.get_skew_percentile(lookback_days=30) == 0.75
        assert provider.get_skew_percentile(lookback_days=500) == 0.75

    def test_from_assumptions_seeds_spot_price(self) -> None:
        """Test that from_assumptions seeds the spot price from a widget."""
        assumptions = GlobalAssumptions(spot_price=4200.0)

        provider = StaticProvider.from_assumptions(assumptions, symbol="SPX")

        assert provider.get_spot("SPX") == pytest.approx(4200.0)
