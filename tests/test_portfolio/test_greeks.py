"""Tests for deltadewa.portfolio.greeks module."""

import pytest
from unittest.mock import Mock
from deltadewa.portfolio.core import OptionPortfolio


class TestGreeksMixin:
    """Test cases for Greek calculations mixin."""

    @pytest.fixture
    def portfolio_with_positions(self):
        """Create a portfolio with mock positions for testing."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
        )
        
        # Add mock positions
        pos1 = Mock()
        pos1.position_value.return_value = 500.0
        pos1.position_delta.return_value = 50.0
        pos1.position_gamma.return_value = 2.0
        pos1.position_vega.return_value = 10.0
        pos1.position_theta.return_value = -5.0
        pos1.position_rho.return_value = 3.0
        
        pos2 = Mock()
        pos2.position_value.return_value = 300.0
        pos2.position_delta.return_value = -30.0
        pos2.position_gamma.return_value = 1.5
        pos2.position_vega.return_value = 8.0
        pos2.position_theta.return_value = -3.0
        pos2.position_rho.return_value = 2.0
        
        portfolio.positions = [pos1, pos2]
        return portfolio

    def test_total_value(self, portfolio_with_positions):
        """Test total_value aggregation."""
        assert portfolio_with_positions.total_value() == 800.0  # 500 + 300

    def test_total_underlying_value(self, portfolio_with_positions):
        """Test total_underlying_value calculation."""
        # underlying_quantity=100, spot_price=100
        assert portfolio_with_positions.total_underlying_value() == 10000.0

    def test_total_portfolio_value(self, portfolio_with_positions):
        """Test total_portfolio_value includes both options and underlying."""
        # options=800 + underlying=10000
        assert portfolio_with_positions.total_portfolio_value() == 10800.0

    def test_total_delta(self, portfolio_with_positions):
        """Test total_delta aggregation."""
        assert portfolio_with_positions.total_delta() == 20.0  # 50 + (-30)

    def test_total_gamma(self, portfolio_with_positions):
        """Test total_gamma aggregation."""
        assert portfolio_with_positions.total_gamma() == 3.5  # 2.0 + 1.5

    def test_total_vega(self, portfolio_with_positions):
        """Test total_vega aggregation."""
        assert portfolio_with_positions.total_vega() == 18.0  # 10 + 8

    def test_total_theta(self, portfolio_with_positions):
        """Test total_theta aggregation."""
        assert portfolio_with_positions.total_theta() == -8.0  # -5 + (-3)

    def test_total_rho(self, portfolio_with_positions):
        """Test total_rho aggregation."""
        assert portfolio_with_positions.total_rho() == 5.0  # 3 + 2

    def test_net_delta(self, portfolio_with_positions):
        """Test net_delta includes underlying."""
        # total_delta=20 + underlying_quantity=100
        assert portfolio_with_positions.net_delta() == 120.0

    def test_hedge_ratio(self, portfolio_with_positions):
        """Test hedge_ratio calculation."""
        # hedge_ratio = -(total_delta / underlying_quantity) * 100
        # = -(20 / 100) * 100 = -20%
        assert portfolio_with_positions.hedge_ratio() == -20.0

    def test_hedge_ratio_zero_underlying(self):
        """Test hedge_ratio with zero underlying returns 0."""
        portfolio = OptionPortfolio(underlying_quantity=0.0)
        assert portfolio.hedge_ratio() == 0.0

    def test_delta_adjustment_needed(self, portfolio_with_positions):
        """Test delta_adjustment_needed calculation."""
        # Should return negative of net_delta
        assert portfolio_with_positions.delta_adjustment_needed() == -120.0

    def test_empty_portfolio_greeks(self):
        """Test Greek calculations with empty portfolio."""
        portfolio = OptionPortfolio()
        assert portfolio.total_value() == 0.0
        assert portfolio.total_delta() == 0.0
        assert portfolio.total_gamma() == 0.0
        assert portfolio.total_vega() == 0.0
        assert portfolio.total_theta() == 0.0
        assert portfolio.total_rho() == 0.0
        assert portfolio.net_delta() == 0.0
