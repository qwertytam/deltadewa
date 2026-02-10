"""Tests for deltadewa.portfolio.risk module."""

import pytest
import numpy as np
from unittest.mock import Mock, patch
from deltadewa.portfolio.core import OptionPortfolio


class TestRiskMixin:
    """Test cases for risk analysis mixin."""

    @pytest.fixture
    def portfolio(self):
        """Create a portfolio for testing."""
        return OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )

    def test_calculate_max_loss_options(self, portfolio):
        """Test calculate_max_loss_options basic functionality."""
        # Mock calculate_pnl_at_expiry to return known values
        with patch.object(portfolio, 'calculate_pnl_at_expiry') as mock_pnl:
            mock_pnl.side_effect = lambda spot, **kwargs: -500.0 if spot < 95 else -100.0
            
            result = portfolio.calculate_max_loss_options(
                spot_range=np.array([90, 95, 100, 105, 110])
            )
            
            assert "max_loss" in result
            assert "spot_at_max_loss" in result
            assert "is_unlimited" in result
            assert result["max_loss"] == -500.0

    def test_calculate_max_profit_options(self, portfolio):
        """Test calculate_max_profit_options basic functionality."""
        with patch.object(portfolio, 'calculate_pnl_at_expiry') as mock_pnl:
            mock_pnl.side_effect = lambda spot, **kwargs: 1000.0 if spot > 105 else 200.0
            
            result = portfolio.calculate_max_profit_options(
                spot_range=np.array([90, 95, 100, 105, 110])
            )
            
            assert result["max_profit"] == 1000.0

    def test_unlimited_loss_detection_short_call(self, portfolio):
        """Test detection of unlimited loss with naked short call."""
        pos = Mock()
        pos.quantity = -1  # Short
        pos.option.option_type = "call"
        portfolio.positions = [pos]
        
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=-100):
            result = portfolio.calculate_max_loss_options()
            assert result["is_unlimited"] is True

    def test_unlimited_profit_detection_long_call(self, portfolio):
        """Test detection of unlimited profit with long call."""
        pos = Mock()
        pos.quantity = 1  # Long
        pos.option.option_type = "call"
        portfolio.positions = [pos]
        
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=100):
            result = portfolio.calculate_max_profit_options()
            assert result["is_unlimited"] is True

    def test_calculate_max_loss_total(self, portfolio):
        """Test calculate_max_loss_total with underlying."""
        portfolio.underlying_quantity = -100  # Short underlying
        
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=-500):
            result = portfolio.calculate_max_loss_total()
            # Short underlying has unlimited loss
            assert result["is_unlimited"] is True

    def test_calculate_max_profit_total(self, portfolio):
        """Test calculate_max_profit_total with underlying."""
        portfolio.underlying_quantity = 100  # Long underlying
        
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=500):
            result = portfolio.calculate_max_profit_total()
            # Long underlying has unlimited profit
            assert result["is_unlimited"] is True

    def test_calculate_breakeven_points(self, portfolio):
        """Test calculate_breakeven_points finds zero crossings."""
        # Mock P&L that crosses zero at spot=100
        def mock_pnl(spot, **kwargs):
            return (spot - 100) * 10  # Linear P&L crossing zero at 100
        
        with patch.object(portfolio, 'calculate_pnl_at_expiry', side_effect=mock_pnl):
            breakevens = portfolio.calculate_breakeven_points(
                spot_range=np.array([95, 98, 100, 102, 105])
            )
            # Should find breakeven near 100
            assert len(breakevens) >= 1

    def test_risk_reward_analysis(self, portfolio):
        """Test risk_reward_analysis returns complete dict."""
        with patch.object(portfolio, 'calculate_pnl_at_expiry', return_value=0):
            with patch.object(portfolio, 'calculate_probability_of_profit', 
                            return_value={"probability": 0.6, "expected_value": 100}):
                result = portfolio.risk_reward_analysis()
                
                assert "net_debit" in result
                assert "max_loss_options" in result
                assert "max_profit_options" in result
                assert "breakeven_options" in result
                assert "max_loss_total" in result
                assert "max_profit_total" in result
                assert "breakeven_total" in result
                assert "probability_of_profit" in result
                assert "expected_value" in result

    def test_print_risk_reward_summary(self, portfolio, capsys):
        """Test print_risk_reward_summary outputs formatted text."""
        with patch.object(portfolio, 'risk_reward_analysis') as mock_analysis:
            mock_analysis.return_value = {
                "net_debit": 1000.0,
                "max_loss_options": {"max_loss": -500, "spot_at_max_loss": 90, "is_unlimited": False},
                "max_profit_options": {"max_profit": 1500, "spot_at_max_profit": 110, "is_unlimited": False},
                "breakeven_options": [95.0, 105.0],
                "max_loss_total": {"max_loss": -500, "spot_at_max_loss": 90, "is_unlimited": False},
                "max_profit_total": {"max_profit": 1500, "spot_at_max_profit": 110, "is_unlimited": False},
                "breakeven_total": [95.0, 105.0],
                "probability_of_profit": 0.65,
                "expected_value": 200.0,
            }
            
            portfolio.print_risk_reward_summary()
            
            captured = capsys.readouterr()
            assert "PORTFOLIO RISK/REWARD ANALYSIS" in captured.out
            assert "CAPITAL REQUIREMENTS" in captured.out
            assert "OPTIONS ONLY RISK/REWARD" in captured.out
            assert "PROBABILITY ANALYSIS" in captured.out

    def test_check_unlimited_trend_increasing(self, portfolio):
        """Test _check_unlimited_trend detects increasing trend."""
        # Mock consistently increasing P&L
        # Need more than 10 points for _check_unlimited_trend to work
        with patch.object(portfolio, 'calculate_pnl_at_expiry') as mock_pnl:
            mock_pnl.side_effect = lambda spot, **kwargs: spot * 10
            
            spot_range = np.array([90, 95, 100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 150])
            result = portfolio._check_unlimited_trend(
                spot_range, include_underlying=False, check_increasing=True
            )
            assert result is True

    def test_check_unlimited_trend_decreasing(self, portfolio):
        """Test _check_unlimited_trend detects decreasing trend."""
        # Need more than 10 points for _check_unlimited_trend to work
        with patch.object(portfolio, 'calculate_pnl_at_expiry') as mock_pnl:
            mock_pnl.side_effect = lambda spot, **kwargs: -spot * 10
            
            spot_range = np.array([90, 95, 100, 105, 110, 115, 120, 125, 130, 135, 140, 145, 150])
            result = portfolio._check_unlimited_trend(
                spot_range, include_underlying=False, check_increasing=False
            )
            assert result is True
