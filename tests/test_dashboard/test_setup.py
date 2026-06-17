"""Tests for deltadewa.dashboard.setup."""

from unittest.mock import MagicMock

from deltadewa.dashboard.setup import build_global_assumptions, setup_dashboard
from deltadewa.marketdata import StaticProvider
from deltadewa.portfolio.core import OptionPortfolio

# ruff: noqa: S101

# pylint: disable=redefined-outer-name


class TestBuildGlobalAssumptions:
    """Tests for build_global_assumptions."""

    def test_without_market_data_unchanged(
        self,
        empty_portfolio: OptionPortfolio,
    ) -> None:
        """Test that omitting market_data leaves seeding behaviour unchanged."""
        global_assumptions, _ = build_global_assumptions(empty_portfolio)

        assert global_assumptions.spot_price.value == empty_portfolio.spot_price
        assert global_assumptions.volatility.value == empty_portfolio.volatility

    def test_with_static_provider_seeds_values(
        self,
        empty_portfolio: OptionPortfolio,
    ) -> None:
        """Test that a supplied provider seeds spot and VIX-derived vol."""
        provider = StaticProvider(
            spot_prices={empty_portfolio.get_symbol(): 123.0},
            vix=20.0,
        )

        global_assumptions, _ = build_global_assumptions(
            empty_portfolio,
            market_data=provider,
        )

        assert global_assumptions.spot_price.value == 123.0
        assert global_assumptions.volatility.value == 0.20

    def test_falls_back_on_provider_error(
        self,
        empty_portfolio: OptionPortfolio,
    ) -> None:
        """Test fallback to portfolio values when the provider has no spot."""
        provider = StaticProvider()  # no spot price registered
        reporter = MagicMock()

        global_assumptions, _ = build_global_assumptions(
            empty_portfolio,
            market_data=provider,
            reporter=reporter,
        )

        assert global_assumptions.spot_price.value == empty_portfolio.spot_price
        assert global_assumptions.volatility.value == empty_portfolio.volatility
        reporter.warning.assert_called_once()


class TestSetupDashboard:
    """Tests for setup_dashboard."""

    def test_threads_market_data_through(
        self,
        single_position_portfolio: OptionPortfolio,
    ) -> None:
        """Test that setup_dashboard passes market_data to GlobalAssumptions."""
        # Mark as already-imported so initialize_portfolio doesn't overwrite
        # it (and its symbol) with the default portfolio.
        globals_dict = {"portfolio": single_position_portfolio}
        provider = StaticProvider(
            spot_prices={single_position_portfolio.get_symbol(): 250.0},
            vix=18.0,
        )

        context = setup_dashboard(
            single_position_portfolio,
            globals_dict=globals_dict,
            market_data=provider,
        )

        global_assumptions = context["global_assumptions"]
        assert global_assumptions.spot_price.value == 250.0
        assert global_assumptions.volatility.value == 0.18
