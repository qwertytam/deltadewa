"""Tests for deltadewa.portfolio.pnl module."""

import pytest
import numpy as np
from unittest.mock import Mock
from deltadewa.portfolio.core import OptionPortfolio


class TestPnLMixin:
    """Test cases for P&L calculations mixin."""

    @pytest.fixture
    def portfolio(self):
        """Create a portfolio for testing."""
        return OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
        )

    def test_get_spot_range_with_existing_range(self, portfolio):
        """Test _get_spot_range returns existing range if provided."""
        existing_range = np.array([90, 95, 100, 105, 110])
        result = portfolio._get_spot_range(spot_range=existing_range)
        assert np.array_equal(result, existing_range)

    def test_get_spot_range_standard(self, portfolio):
        """Test _get_spot_range creates standard range."""
        result = portfolio._get_spot_range(
            spot_min_pct=50.0, spot_max_pct=150.0, num_points=5
        )
        assert len(result) == 5
        assert result[0] == pytest.approx(50.0, rel=0.01)  # 50% of 100
        assert result[-1] == pytest.approx(150.0, rel=0.01)  # 150% of 100

    def test_get_spot_range_comprehensive(self, portfolio):
        """Test _get_spot_range with comprehensive mode."""
        result = portfolio._get_spot_range(use_comprehensive_range=True)
        assert len(result) > 100  # Should have many points
        assert result[0] > 0  # Should not be exactly zero
        assert result[-1] == pytest.approx(1000.0, rel=0.01)  # 10x spot

    def test_calculate_net_debit(self, portfolio):
        """Test calculate_net_debit returns total_value."""
        # Mock total_value
        portfolio.positions = [Mock()]
        portfolio.positions[0].position_value.return_value = 500.0
        
        assert portfolio.calculate_net_debit() == 500.0

    def test_calculate_pnl_at_expiry_call_itm(self, portfolio):
        """Test calculate_pnl_at_expiry for in-the-money call."""
        # Mock a long call at strike 100
        pos = Mock()
        pos.option.option_type = "call"
        pos.option.strike_price = 100.0
        pos.quantity = 1
        pos.contract_size = 100
        pos.position_value.return_value = 500.0  # Initial cost
        
        portfolio.positions = [pos]
        
        # At expiry spot=110, intrinsic = 10 * 100 = 1000
        # P&L = -500 (cost) + 1000 (intrinsic) = 500
        pnl = portfolio.calculate_pnl_at_expiry(110.0, include_underlying=False)
        assert pnl == 500.0

    def test_calculate_pnl_at_expiry_call_otm(self, portfolio):
        """Test calculate_pnl_at_expiry for out-of-the-money call."""
        pos = Mock()
        pos.option.option_type = "call"
        pos.option.strike_price = 100.0
        pos.quantity = 1
        pos.contract_size = 100
        pos.position_value.return_value = 500.0
        
        portfolio.positions = [pos]
        
        # At expiry spot=90, intrinsic = 0
        # P&L = -500 (cost) + 0 = -500 (max loss)
        pnl = portfolio.calculate_pnl_at_expiry(90.0, include_underlying=False)
        assert pnl == -500.0

    def test_calculate_pnl_at_expiry_put_itm(self, portfolio):
        """Test calculate_pnl_at_expiry for in-the-money put."""
        pos = Mock()
        pos.option.option_type = "put"
        pos.option.strike_price = 100.0
        pos.quantity = 1
        pos.contract_size = 100
        pos.position_value.return_value = 300.0
        
        portfolio.positions = [pos]
        
        # At expiry spot=90, intrinsic = 10 * 100 = 1000
        # P&L = -300 + 1000 = 700
        pnl = portfolio.calculate_pnl_at_expiry(90.0, include_underlying=False)
        assert pnl == 700.0

    def test_calculate_pnl_at_expiry_with_underlying(self, portfolio):
        """Test calculate_pnl_at_expiry includes underlying P&L."""
        # Empty options portfolio, just underlying
        portfolio.positions = []
        portfolio.underlying_quantity = 100
        portfolio.spot_price = 100.0
        
        # Spot moves to 110, underlying P&L = (110 - 100) * 100 = 1000
        pnl = portfolio.calculate_pnl_at_expiry(110.0, include_underlying=True)
        assert pnl == 1000.0

    def test_calculate_pnl_at_expiry_short_position(self, portfolio):
        """Test calculate_pnl_at_expiry with short position."""
        pos = Mock()
        pos.option.option_type = "call"
        pos.option.strike_price = 100.0
        pos.quantity = -1  # Short position
        pos.contract_size = 100
        pos.position_value.return_value = -500.0  # Credit received
        
        portfolio.positions = [pos]
        
        # At expiry spot=110, intrinsic = 10 * -1 * 100 = -1000
        # P&L = 500 (credit) - 1000 (loss) = -500
        pnl = portfolio.calculate_pnl_at_expiry(110.0, include_underlying=False)
        assert pnl == -500.0
