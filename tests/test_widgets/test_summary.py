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
        portfolio.positions = []
        return portfolio

    @pytest.fixture
    def mock_analyzer(self):
        """Create a mock analyzer for testing."""
        analyzer = Mock()
        analyzer.total_delta = 1000.0
        analyzer.total_gamma = 50.0
        analyzer.total_vega = 200.0
        analyzer.total_theta = -10.0
        analyzer.total_premium = 5000.0
        analyzer.total_quantity = 100
        analyzer.hedge_ratio = 0.75
        return analyzer

    def test_initialization(self, mock_portfolio):
        """Test NetHedgeSummary can be instantiated."""
        summary = NetHedgeSummary(mock_portfolio)
        assert summary is not None
        assert summary.portfolio == mock_portfolio

    def test_initialization_with_analyzer(self, mock_portfolio, mock_analyzer):
        """Test NetHedgeSummary can be instantiated with analyzer."""
        summary = NetHedgeSummary(mock_portfolio, analyzer=mock_analyzer)
        assert summary is not None
        assert summary.portfolio == mock_portfolio

    def test_attributes_exist(self, mock_portfolio):
        """Test all expected attributes are created."""
        summary = NetHedgeSummary(mock_portfolio)
        # Should have widget attributes
        assert hasattr(summary, "container")
        assert summary.container is not None

    def test_update_method_exists(self, mock_portfolio):
        """Test update method can be called."""
        summary = NetHedgeSummary(mock_portfolio)
        # Should not raise exception even with no analyzer
        try:
            summary.update()
        except AttributeError:
            # Expected if no analyzer set
            pass

    def test_update_with_analyzer(self, mock_portfolio, mock_analyzer):
        """Test update method with analyzer."""
        summary = NetHedgeSummary(mock_portfolio, analyzer=mock_analyzer)
        # Should not raise exception
        summary.update()

    def test_update_with_custom_params(self, mock_portfolio, mock_analyzer):
        """Test update method with custom parameters."""
        summary = NetHedgeSummary(mock_portfolio, analyzer=mock_analyzer)
        # Should not raise exception with custom params
        summary.update(
            spot_price=110.0,
            volatility=0.30,
            risk_free_rate=0.04,
            dividend_yield=0.03,
        )

    def test_display_returns_widget(self, mock_portfolio):
        """Test display method returns a widget."""
        summary = NetHedgeSummary(mock_portfolio)
        widget = summary.display()
        assert widget is not None

    def test_container_is_widget(self, mock_portfolio):
        """Test container attribute is a widget."""
        summary = NetHedgeSummary(mock_portfolio)
        assert hasattr(summary.container, "children") or hasattr(
            summary.container, "value"
        )
