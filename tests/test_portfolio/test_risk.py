"""Tests for deltadewa.portfolio.risk module."""

from datetime import datetime, timedelta
import numpy as np
from deltadewa.portfolio import OptionPortfolio


class TestRiskMixin:
    """Test cases for RiskMixin."""

    def test_get_spot_range(self):
        """Test _get_spot_range helper method."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        spot_range = portfolio._get_spot_range(num_points=10)
        
        assert isinstance(spot_range, np.ndarray)
        assert len(spot_range) == 10

    def test_get_spot_range_comprehensive(self):
        """Test _get_spot_range with comprehensive range."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        spot_range = portfolio._get_spot_range(use_comprehensive_range=True)
        
        assert isinstance(spot_range, np.ndarray)
        assert len(spot_range) > 0
        # Should include extreme values
        assert min(spot_range) < 1.0
        assert max(spot_range) > 500.0

    def test_calculate_max_loss_options(self):
        """Test calculate_max_loss_options method."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        # Long call - limited loss
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        result = portfolio.calculate_max_loss_options()
        
        assert "max_loss" in result
        assert "spot_at_max_loss" in result
        assert "is_unlimited" in result
        # Long call has limited loss (premium paid)
        assert result["is_unlimited"] is False
        assert result["max_loss"] < 0

    def test_calculate_max_profit_options(self):
        """Test calculate_max_profit_options method."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        # Long call - unlimited profit
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        result = portfolio.calculate_max_profit_options()
        
        assert "max_profit" in result
        assert "spot_at_max_profit" in result
        assert "is_unlimited" in result
        # Long call has unlimited profit
        assert result["is_unlimited"] is True

    def test_calculate_max_loss_short_call(self):
        """Test calculate_max_loss_options with naked short call."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        # Short call - unlimited loss
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="call",
        )
        
        result = portfolio.calculate_max_loss_options()
        
        assert result["is_unlimited"] is True

    def test_calculate_max_profit_short_call(self):
        """Test calculate_max_profit_options with short call."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        # Short call - limited profit (premium received)
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="call",
        )
        
        result = portfolio.calculate_max_profit_options()
        
        assert result["is_unlimited"] is False
        # Profit limited to premium
        assert result["max_profit"] > 0

    def test_calculate_max_loss_total(self):
        """Test calculate_max_loss_total with underlying."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0, spot_price=100.0
        )
        
        result = portfolio.calculate_max_loss_total()
        
        assert "max_loss" in result
        assert "is_unlimited" in result
        # Long underlying has limited loss (spot to zero)
        assert result["is_unlimited"] is False

    def test_calculate_max_profit_total(self):
        """Test calculate_max_profit_total with underlying."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0, spot_price=100.0
        )
        
        result = portfolio.calculate_max_profit_total()
        
        assert "max_profit" in result
        assert "is_unlimited" in result
        # Long underlying has unlimited profit
        assert result["is_unlimited"] is True

    def test_calculate_breakeven_points(self):
        """Test calculate_breakeven_points method."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        # Long call
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        breakevens = portfolio.calculate_breakeven_points()
        
        assert isinstance(breakevens, list)
        # Long call should have one breakeven point
        assert len(breakevens) > 0

    def test_risk_reward_analysis(self):
        """Test risk_reward_analysis comprehensive method."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        analysis = portfolio.risk_reward_analysis(num_simulations=100)
        
        assert "net_debit" in analysis
        assert "max_loss_options" in analysis
        assert "max_profit_options" in analysis
        assert "breakeven_options" in analysis
        assert "max_loss_total" in analysis
        assert "max_profit_total" in analysis
        assert "breakeven_total" in analysis
        assert "probability_of_profit" in analysis
        assert "expected_value" in analysis

    def test_print_risk_reward_summary(self):
        """Test print_risk_reward_summary method (just ensure no errors)."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        # Should not raise any exceptions
        # We're not capturing output in this test
        try:
            portfolio.print_risk_reward_summary()
        except Exception as e:
            assert False, f"print_risk_reward_summary raised {e}"

    def test_breakeven_empty_portfolio(self):
        """Test calculate_breakeven_points with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        breakevens = portfolio.calculate_breakeven_points()
        
        # Empty portfolio has no breakeven
        assert len(breakevens) == 0

    def test_check_unlimited_trend(self):
        """Test _check_unlimited_trend helper method."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        # Long call
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        spot_range = np.linspace(100, 500, 100)
        
        # Check increasing trend (profit)
        result = portfolio._check_unlimited_trend(
            spot_range, include_underlying=False, check_increasing=True
        )
        
        assert isinstance(result, bool)
