"""Tests for deltadewa.portfolio.factory module."""

from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.factory import (
    create_demo_portfolio,
    create_empty_portfolio,
)

# ruff: noqa: S101


class TestFactoryFunctions:
    """Test cases for factory functions."""

    def test_create_empty_portfolio(self) -> None:
        """Test create_empty_portfolio function."""
        portfolio = create_empty_portfolio()

        assert portfolio is not None
        assert isinstance(portfolio, OptionPortfolio)
        assert len(portfolio.positions) == 0

    def test_create_empty_portfolio_with_kwargs(self) -> None:
        """Test create_empty_portfolio with custom parameters."""
        portfolio = create_empty_portfolio(
            spot_price=150.0,
            volatility=0.3,
            underlying_quantity=200.0,
        )

        assert portfolio.spot_price == 150.0
        assert portfolio.volatility == 0.3
        assert portfolio.underlying_quantity == 200.0

    def test_create_demo_portfolio(self) -> None:
        """Test create_demo_portfolio function."""
        portfolio = create_demo_portfolio()

        assert portfolio is not None
        assert isinstance(portfolio, OptionPortfolio)
        assert len(portfolio.positions) == 2

    def test_create_demo_portfolio_positions(self) -> None:
        """Test that demo portfolio has expected positions."""
        portfolio = create_demo_portfolio()

        # Should have 2 positions
        assert len(portfolio.positions) == 2

        # Check first position (call)
        pos1 = portfolio.positions[0]
        assert pos1.option.strike_price == 100.0
        assert pos1.option.option_type == OptionType.CALL
        assert pos1.quantity == 1

        # Check second position (put)
        pos2 = portfolio.positions[1]
        assert pos2.option.strike_price == 95.0
        assert pos2.option.option_type == OptionType.PUT
        assert pos2.quantity == 1

    def test_create_demo_portfolio_market_conditions(self) -> None:
        """Test demo portfolio has expected market conditions."""
        portfolio = create_demo_portfolio()

        assert portfolio.spot_price == 100.0
        assert portfolio.volatility == 0.25
        assert portfolio.underlying_quantity == 0

    def test_create_empty_portfolio_returns_full_portfolio(self) -> None:
        """Test that created portfolio has all mixin methods."""
        portfolio = create_empty_portfolio()

        # Check for mixin methods
        assert hasattr(portfolio, "total_delta")
        assert hasattr(portfolio, "calculate_pnl_at_expiry")
        assert hasattr(portfolio, "calculate_max_loss_options")
        assert hasattr(portfolio, "run_monte_carlo_simulation")
        # ScenariosMixin removed - use PortfolioAnalyzer instead

    def test_create_demo_portfolio_returns_full_portfolio(self) -> None:
        """Test that demo portfolio has all mixin methods."""
        portfolio = create_demo_portfolio()

        # Check for mixin methods
        assert hasattr(portfolio, "total_delta")
        assert hasattr(portfolio, "calculate_pnl_at_expiry")
        assert hasattr(portfolio, "calculate_max_loss_options")
        assert hasattr(portfolio, "run_monte_carlo_simulation")
        # ScenariosMixin removed - use PortfolioAnalyzer instead

    def test_create_empty_portfolio_different_params(self) -> None:
        """Test create_empty_portfolio with different rate parameters."""
        portfolio = create_empty_portfolio(
            risk_free_rate=0.03,
            dividend_yield=0.02,
        )

        assert portfolio.risk_free_rate == 0.03
        assert portfolio.dividend_yield == 0.02
