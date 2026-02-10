"""Tests for deltadewa.portfolio.monte_carlo module."""

import pytest
import numpy as np
from unittest.mock import Mock, patch
from deltadewa.portfolio.core import OptionPortfolio
from datetime import datetime, timedelta


class TestMonteCarloMixin:
    """Test cases for Monte Carlo simulation mixin."""

    @pytest.fixture
    def portfolio(self):
        """Create a portfolio for testing."""
        return OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            valuation_date=datetime(2024, 1, 1),
        )

    def test_calculate_probability_of_profit_returns_dict(self, portfolio):
        """Test calculate_probability_of_profit returns proper dict structure."""
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=100):
            with patch.object(portfolio, 'calculate_breakeven_points', return_value=[95, 105]):
                result = portfolio.calculate_probability_of_profit(
                    num_simulations=100
                )
                
                assert isinstance(result, dict)
                assert "probability" in result
                assert "expected_value" in result
                assert "breakeven_points" in result
                assert 0 <= result["probability"] <= 1

    def test_calculate_probability_with_positions(self, portfolio):
        """Test probability calculation with positions."""
        # Add mock position with maturity
        pos = Mock()
        pos.option.maturity_date = datetime(2024, 3, 1)
        portfolio.positions = [pos]
        
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=100):
            with patch.object(portfolio, 'calculate_breakeven_points', return_value=[]):
                result = portfolio.calculate_probability_of_profit(
                    num_simulations=100
                )
                # All simulations profitable
                assert result["probability"] == 1.0

    def test_calculate_probability_with_losses(self, portfolio):
        """Test probability calculation when all simulations lose."""
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=-100):
            with patch.object(portfolio, 'calculate_breakeven_points', return_value=[]):
                result = portfolio.calculate_probability_of_profit(
                    num_simulations=100
                )
                # No simulations profitable
                assert result["probability"] == 0.0

    def test_calculate_probability_custom_days_to_expiry(self, portfolio):
        """Test with custom days_to_expiry parameter."""
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=50):
            with patch.object(portfolio, 'calculate_breakeven_points', return_value=[]):
                result = portfolio.calculate_probability_of_profit(
                    num_simulations=50,
                    days_to_expiry=30
                )
                assert isinstance(result["probability"], float)

    def test_calculate_probability_include_underlying(self, portfolio):
        """Test probability calculation including underlying position."""
        portfolio.underlying_quantity = 100
        
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=100):
            with patch.object(portfolio, 'calculate_breakeven_points', return_value=[]):
                result = portfolio.calculate_probability_of_profit(
                    num_simulations=100,
                    include_underlying=True
                )
                assert isinstance(result, dict)

    def test_expected_value_calculation(self, portfolio):
        """Test expected value is properly calculated."""
        # Mock to return constant P&L
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=50):
            with patch.object(portfolio, 'calculate_breakeven_points', return_value=[]):
                result = portfolio.calculate_probability_of_profit(
                    num_simulations=100
                )
                # Expected value should be close to 50
                assert abs(result["expected_value"] - 50) < 1

    def test_monte_carlo_with_empty_portfolio(self, portfolio):
        """Test Monte Carlo with empty portfolio uses default days."""
        # Empty portfolio should default to 30 days
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=0):
            with patch.object(portfolio, 'calculate_breakeven_points', return_value=[]):
                result = portfolio.calculate_probability_of_profit(
                    num_simulations=50
                )
                assert result["expected_value"] == 0.0

    def test_normal_method_fallback(self, portfolio):
        """Test that 'normal' method falls back to Monte Carlo."""
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=100):
            with patch.object(portfolio, 'calculate_breakeven_points', return_value=[]):
                result = portfolio.calculate_probability_of_profit(
                    method="normal",
                    num_simulations=50
                )
                # Should still work with fallback
                assert isinstance(result, dict)
                assert "probability" in result
