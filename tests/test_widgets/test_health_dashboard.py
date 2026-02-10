"""Tests for deltadewa.widgets.health_dashboard module."""

import pytest
from unittest.mock import Mock
from deltadewa.widgets.health_dashboard import (
    HedgeHealthMetric,
    HedgeHealthDashboard,
)


class TestHedgeHealthMetric:
    """Test cases for HedgeHealthMetric class."""

    def test_initialization(self):
        """Test HedgeHealthMetric can be instantiated."""
        metric = HedgeHealthMetric(
            name="Test Metric",
            description="A test metric",
            value_func=lambda p: 0.75,
            thresholds=[0.3, 0.7],
            colors=["red", "yellow", "green"],
        )
        assert metric is not None
        assert metric.name == "Test Metric"
        assert metric.description == "A test metric"
        assert metric.value_func is not None
        assert metric.thresholds == [0.3, 0.7]
        assert metric.colors == ["red", "yellow", "green"]

    def test_metric_attributes(self):
        """Test all metric attributes are accessible."""
        metric = HedgeHealthMetric(
            name="Delta",
            description="Portfolio delta",
            value_func=lambda p: 1.0,
            thresholds=[0.5],
            colors=["red", "green"],
        )
        assert hasattr(metric, "name")
        assert hasattr(metric, "description")
        assert hasattr(metric, "value_func")
        assert hasattr(metric, "thresholds")
        assert hasattr(metric, "colors")


class TestHedgeHealthDashboard:
    """Test cases for HedgeHealthDashboard class."""

    @pytest.fixture
    def mock_portfolio(self):
        """Create a mock portfolio for testing."""
        portfolio = Mock()
        portfolio.spot_price = 100.0
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
        analyzer.hedge_ratio = 0.75
        analyzer.calculate_scenario_hedge_ratio = Mock(return_value=0.80)
        return analyzer

    @pytest.fixture
    def sample_metrics(self):
        """Create sample metrics for testing."""
        return [
            HedgeHealthMetric(
                name="Hedge Ratio",
                description="Current hedge ratio",
                value_func=lambda p: 0.75,
                thresholds=[0.3, 0.7],
                colors=["red", "yellow", "green"],
            ),
            HedgeHealthMetric(
                name="Delta",
                description="Portfolio delta",
                value_func=lambda p: 0.50,
                thresholds=[0.2, 0.5, 0.8],
                colors=["red", "yellow", "green", "blue"],
            ),
        ]

    def test_initialization(self, mock_portfolio, mock_analyzer):
        """Test HedgeHealthDashboard can be instantiated."""
        dashboard = HedgeHealthDashboard(mock_portfolio, mock_analyzer)
        assert dashboard is not None
        assert dashboard.portfolio == mock_portfolio
        assert dashboard.analyzer == mock_analyzer

    def test_initialization_with_metrics(
        self, mock_portfolio, mock_analyzer, sample_metrics
    ):
        """Test HedgeHealthDashboard with custom metrics."""
        dashboard = HedgeHealthDashboard(
            mock_portfolio, mock_analyzer, metrics=sample_metrics
        )
        assert dashboard is not None

    def test_display_method(self, mock_portfolio, mock_analyzer):
        """Test display method returns a widget."""
        dashboard = HedgeHealthDashboard(mock_portfolio, mock_analyzer)
        widget = dashboard.display()
        assert widget is not None

    def test_update_method(self, mock_portfolio, mock_analyzer):
        """Test update method can be called."""
        dashboard = HedgeHealthDashboard(mock_portfolio, mock_analyzer)
        # Should not raise exception
        dashboard.update()

    def test_update_with_params(self, mock_portfolio, mock_analyzer):
        """Test update method with parameters."""
        dashboard = HedgeHealthDashboard(mock_portfolio, mock_analyzer)
        # Should not raise exception
        dashboard.update(
            spot_price=110.0,
            volatility=0.30,
            risk_free_rate=0.04,
            dividend_yield=0.03,
        )

    def test_attributes_exist(self, mock_portfolio, mock_analyzer):
        """Test all expected attributes exist."""
        dashboard = HedgeHealthDashboard(mock_portfolio, mock_analyzer)
        assert hasattr(dashboard, "portfolio")
        assert hasattr(dashboard, "analyzer")
        assert hasattr(dashboard, "display")
        assert hasattr(dashboard, "update")

    def test_with_empty_metrics(self, mock_portfolio, mock_analyzer):
        """Test dashboard with empty metrics list."""
        dashboard = HedgeHealthDashboard(
            mock_portfolio, mock_analyzer, metrics=[]
        )
        assert dashboard is not None
        widget = dashboard.display()
        assert widget is not None
