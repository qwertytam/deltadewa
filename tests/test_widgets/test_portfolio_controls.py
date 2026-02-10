"""Tests for deltadewa.widgets.portfolio_controls module."""

import pytest
from unittest.mock import Mock
from deltadewa.widgets.portfolio_controls import PortfolioWidgets


class TestPortfolioWidgets:
    """Test cases for PortfolioWidgets class."""

    @pytest.fixture
    def mock_portfolio(self):
        """Create a mock portfolio for testing."""
        portfolio = Mock()
        portfolio.spot_price = 100.0
        portfolio.volatility = 0.25
        portfolio.risk_free_rate = 0.05
        portfolio.dividend_yield = 0.02
        portfolio.positions = []
        portfolio.add_position = Mock()
        portfolio.update_position = Mock()
        portfolio.remove_position = Mock()
        return portfolio

    def test_initialization(self, mock_portfolio):
        """Test PortfolioWidgets can be instantiated."""
        widgets = PortfolioWidgets(mock_portfolio)
        assert widgets is not None
        assert widgets.portfolio == mock_portfolio

    def test_create_position_editor(self, mock_portfolio):
        """Test create_position_editor method."""
        widgets = PortfolioWidgets(mock_portfolio)
        editor = widgets.create_position_editor()
        assert editor is not None
        assert hasattr(editor, "children") or hasattr(editor, "value")

    def test_create_market_params_controls(self, mock_portfolio):
        """Test create_market_params_controls method."""
        widgets = PortfolioWidgets(mock_portfolio)
        controls = widgets.create_market_params_controls()
        assert controls is not None

    def test_create_scenario_controls(self, mock_portfolio):
        """Test create_scenario_controls method."""
        widgets = PortfolioWidgets(mock_portfolio)
        controls = widgets.create_scenario_controls()
        assert controls is not None

    def test_create_transaction_cost_controls(self, mock_portfolio):
        """Test create_transaction_cost_controls method."""
        widgets = PortfolioWidgets(mock_portfolio)
        controls = widgets.create_transaction_cost_controls()
        assert controls is not None

    def test_create_roll_analysis_controls(self, mock_portfolio):
        """Test create_roll_analysis_controls method."""
        widgets = PortfolioWidgets(mock_portfolio)
        controls = widgets.create_roll_analysis_controls()
        assert controls is not None

    def test_create_export_controls(self, mock_portfolio):
        """Test create_export_controls method."""
        widgets = PortfolioWidgets(mock_portfolio)
        controls = widgets.create_export_controls()
        assert controls is not None

    def test_create_import_controls(self, mock_portfolio):
        """Test create_import_controls method."""
        widgets = PortfolioWidgets(mock_portfolio)
        controls = widgets.create_import_controls()
        assert controls is not None

    def test_attributes_exist(self, mock_portfolio):
        """Test all expected attributes exist."""
        widgets = PortfolioWidgets(mock_portfolio)
        assert hasattr(widgets, "portfolio")
        assert hasattr(widgets, "create_position_editor")
        assert hasattr(widgets, "create_market_params_controls")
        assert hasattr(widgets, "create_scenario_controls")
