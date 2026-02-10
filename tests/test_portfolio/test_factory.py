"""Tests for deltadewa.portfolio.factory module."""

import pytest
from deltadewa.portfolio.factory import create_empty_portfolio, create_demo_portfolio
from deltadewa.portfolio.core import OptionPortfolio


class TestFactoryFunctions:
    """Test cases for portfolio factory functions."""

    def test_create_empty_portfolio_default(self):
        """Test create_empty_portfolio with default parameters."""
        portfolio = create_empty_portfolio()
        
        assert isinstance(portfolio, OptionPortfolio)
        assert len(portfolio.positions) == 0
        assert portfolio.spot_price == 100.0
        assert portfolio.volatility == 0.2
        assert portfolio.underlying_quantity == 0.0

    def test_create_empty_portfolio_custom_params(self):
        """Test create_empty_portfolio with custom parameters."""
        portfolio = create_empty_portfolio(
            spot_price=150.0,
            volatility=0.30,
            underlying_quantity=500.0,
            risk_free_rate=0.03,
        )
        
        assert isinstance(portfolio, OptionPortfolio)
        assert portfolio.spot_price == 150.0
        assert portfolio.volatility == 0.30
        assert portfolio.underlying_quantity == 500.0
        assert portfolio.risk_free_rate == 0.03

    def test_create_demo_portfolio(self):
        """Test create_demo_portfolio creates portfolio with positions."""
        portfolio = create_demo_portfolio()
        
        assert isinstance(portfolio, OptionPortfolio)
        assert len(portfolio.positions) == 2  # Should have 2 demo positions
        assert portfolio.spot_price == 100.0
        assert portfolio.volatility == 0.25
        assert portfolio.underlying_quantity == 0

    def test_create_demo_portfolio_has_call(self):
        """Test demo portfolio contains a call option."""
        portfolio = create_demo_portfolio()
        
        # Check if there's at least one call
        has_call = any(
            pos.option.option_type.lower() == "call" 
            for pos in portfolio.positions
        )
        assert has_call

    def test_create_demo_portfolio_has_put(self):
        """Test demo portfolio contains a put option."""
        portfolio = create_demo_portfolio()
        
        # Check if there's at least one put
        has_put = any(
            pos.option.option_type.lower() == "put" 
            for pos in portfolio.positions
        )
        assert has_put

    def test_create_demo_portfolio_symbols(self):
        """Test demo portfolio positions have DEMO symbol."""
        portfolio = create_demo_portfolio()
        
        for pos in portfolio.positions:
            assert pos.symbol == "DEMO"

    def test_create_demo_portfolio_quantities(self):
        """Test demo portfolio positions have positive quantities."""
        portfolio = create_demo_portfolio()
        
        for pos in portfolio.positions:
            assert pos.quantity > 0  # All long positions

    def test_factories_return_different_instances(self):
        """Test factory functions return independent instances."""
        portfolio1 = create_empty_portfolio()
        portfolio2 = create_empty_portfolio()
        
        assert portfolio1 is not portfolio2
        
        # Modifying one shouldn't affect the other
        portfolio1.spot_price = 200.0
        assert portfolio2.spot_price == 100.0

    def test_demo_portfolio_is_functional(self):
        """Test demo portfolio can perform basic operations."""
        portfolio = create_demo_portfolio()
        
        # Should be able to call methods
        value = portfolio.total_value()
        assert isinstance(value, (int, float))
        
        delta = portfolio.total_delta()
        assert isinstance(delta, (int, float))
        
        summary = portfolio.summary()
        assert isinstance(summary, str)
