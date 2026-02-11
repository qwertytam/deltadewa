"""Tests for deltadewa.widgets.summary module."""

import pytest
from datetime import datetime
from unittest.mock import Mock
from deltadewa.widgets.summary import NetHedgeSummary


class TestNetHedgeSummary:
    """Test cases for NetHedgeSummary class."""

    @pytest.fixture
    def mock_portfolio(self):
        """Create a mock portfolio for testing."""
        portfolio = Mock()
        portfolio.spot_price = 100.0
        portfolio.valuation_date = datetime(2024, 1, 1)
        portfolio.volatility = 0.25
        portfolio.risk_free_rate = 0.05
        portfolio.dividend_yield = 0.02

        # Setup mock position for volatility stats
        pos = Mock()
        pos.option.volatility = 0.25
        pos.custom_volatility = False
        pos.position_vega.return_value = 10.0
        portfolio.positions = [pos]

        # Setup methods to return values expected by widget
        portfolio.summary_stats.return_value = {
            "total_underlying_value": 10000.0,
            "total_value": 500.0,
            "total_portfolio_value": 10500.0,
            "total_delta": 50.0,
            "net_delta": 10.0,
            "total_theta": -5.0,
            "total_vega": 20.0,
            "total_gamma": 1.5,
            "total_rho": 2.0,
            "hedge_ratio": 0.8,
            "delta_adjustment": 0.0,
            "volatility_min": 0.2,
            "volatility_max": 0.3,
            "custom_volatility_count": 0,
        }

        portfolio.calculate_pnl_at_expiry.return_value = 0.0

        # Setup risk analysis methods that analyzer will call
        portfolio.calculate_net_debit.return_value = 100.0
        portfolio.calculate_max_loss_options.return_value = {
            "max_loss": 100,
            "is_unlimited": False,
            "spot_at_max_loss": 95.0,
        }
        portfolio.calculate_max_profit_options.return_value = {
            "max_profit": 500,
            "is_unlimited": False,
            "spot_at_max_profit": 105.0,
        }
        portfolio.calculate_breakeven_points.return_value = [105.0]
        portfolio.calculate_max_loss_total.return_value = {
            "max_loss": 100,
            "is_unlimited": False,
            "spot_at_max_loss": 95.0,
        }
        portfolio.calculate_max_profit_total.return_value = {
            "max_profit": 500,
            "is_unlimited": False,
            "spot_at_max_profit": 105.0,
        }
        portfolio.calculate_probability_of_profit.return_value = {
            "probability": 0.6,
            "expected_value": 1.5,
        }

        # Setup risk analysis (deprecated wrapper, still works but not used by widgets anymore)
        portfolio.risk_reward_analysis.return_value = {
            "net_debit": 100.0,
            "max_loss_options": {"max_loss": 100, "is_unlimited": False, "spot_at_max_loss": 95.0},
            "max_loss_total": {"max_loss": 100, "is_unlimited": False, "spot_at_max_loss": 95.0},
            "max_profit_options": {"max_profit": 500, "is_unlimited": False, "spot_at_max_profit": 105.0},
            "max_profit_total": {"max_profit": 500, "is_unlimited": False, "spot_at_max_profit": 105.0},
            "breakeven_options": [105.0],
            "breakeven_total": [105.0],
            "probability_of_profit": 0.6,
            "expected_value": 1.5,
        }

        portfolio.monte_carlo_results = {
            "simulated_pnls": [1.0, 2.0],
            "expected_pnl": 1.5,
            "prob_profit": 0.6,
        }

        return portfolio

    def test_initialization(self, mock_portfolio):
        """Test NetHedgeSummary can be instantiated."""
        summary = NetHedgeSummary(mock_portfolio)
        assert summary is not None
        assert summary.portfolio == mock_portfolio

    def test_attributes_exist(self, mock_portfolio):
        """Test all expected attributes are created."""
        summary = NetHedgeSummary(mock_portfolio)
        # Should have widget attributes
        assert hasattr(summary, "widget")
        assert summary.widget is not None

    def test_update_method_exists(self, mock_portfolio):
        """Test update method can be called."""
        summary = NetHedgeSummary(mock_portfolio)
        summary.update()

    def test_display_returns_widget(self, mock_portfolio):
        """Test display method returns a widget."""
        summary = NetHedgeSummary(mock_portfolio)
        widget = summary.display()
        assert widget is not None

    def test_widget_attribute(self, mock_portfolio):
        """Test widget attribute is a widget with children."""
        summary = NetHedgeSummary(mock_portfolio)
        assert hasattr(summary.widget, "children")
