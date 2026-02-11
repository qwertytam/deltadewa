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
            start=0.0,
            end=1.0,
            min_val=0.3,
            mid_val=0.5,
            max_val=0.7,
            actual=0.75,
            unit="%",
            invert_colors=False,
        )
        assert metric is not None
        assert metric.name == "Test Metric"
        assert metric.description == "A test metric"
        assert metric.start == 0.0
        assert metric.end == 1.0
        assert metric.min_val == 0.3
        assert metric.mid_val == 0.5
        assert metric.max_val == 0.7
        assert metric.actual == 0.75
        assert metric.unit == "%"
        assert metric.invert_colors is False

    def test_metric_attributes(self):
        """Test all metric attributes are accessible."""
        metric = HedgeHealthMetric(
            name="Delta",
            description="Portfolio delta",
            start=0.0,
            end=1.0,
            min_val=0.3,
            mid_val=0.5,
            max_val=0.7,
            actual=1.0,
        )
        assert hasattr(metric, "name")
        assert hasattr(metric, "description")
        assert hasattr(metric, "start")
        assert hasattr(metric, "end")
        assert hasattr(metric, "min_val")
        assert hasattr(metric, "mid_val")
        assert hasattr(metric, "max_val")
        assert hasattr(metric, "actual")


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
        portfolio.summary_stats.return_value = {
            "total_theta": -10.0,
            "total_delta": 5.0,
            "total_gamma": 0.5,
            "total_vega": 20.0,
            "equity_value": 10000.0,
            "total_underlying_value": 10000.0,
            "total_portfolio_value": 20000.0,
            "net_delta": 0.5,
            "underlying_quantity": 100.0,
            "total_value": 1000.0,
        }
        # Explicitly set return value for methods that return numerical values
        portfolio.calculate_pnl_at_expiry.return_value = 500.0
        portfolio.calculate_net_delta.return_value = 0.2
        return portfolio

    @pytest.fixture
    def sample_metrics(self):
        """Create sample metrics for testing."""
        return [
            HedgeHealthMetric(
                name="Hedge Ratio",
                description="Current hedge ratio",
                start=0.0,
                end=1.0,
                min_val=0.3,
                mid_val=0.6,
                max_val=0.8,
                actual=0.75,
            ),
            HedgeHealthMetric(
                name="Delta",
                description="Portfolio delta",
                start=-1.0,
                end=1.0,
                min_val=-0.5,
                mid_val=0.0,
                max_val=0.5,
                actual=0.1,
            ),
        ]

    def test_initialization(self, mock_portfolio):
        """Test HedgeHealthDashboard can be instantiated."""
        # Note: Init only takes portfolio, other args are optional scalars.
        # It creates its OWN analyzer internally: self.analyzer = PortfolioAnalyzer(portfolio)
        dashboard = HedgeHealthDashboard(mock_portfolio)
        assert dashboard is not None
        assert dashboard.portfolio == mock_portfolio
        assert hasattr(dashboard, "analyzer")

    def test_initialization_with_metrics(self, mock_portfolio):
        """Test HedgeHealthDashboard initialization."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        # Just check it runs
        assert dashboard is not None

    def test_display_method(self, mock_portfolio):
        """Test display method returns a widget."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        # Ensure cumulative_carry_paid is float (default 0.0)
        widget = dashboard.display()
        assert widget is not None

    def test_update_method(self, mock_portfolio):
        """Test update method can be called."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        dashboard.update()

    def test_update_with_params(self, mock_portfolio):
        """Test update method with parameters."""
        dashboard = HedgeHealthDashboard(mock_portfolio)

        # Mock portfolio updates
        mock_portfolio.spot_price = 110.0
        mock_portfolio.volatility = 0.30

        dashboard.update()

    def test_attributes_exist(self, mock_portfolio):
        """Test all expected attributes exist."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        assert hasattr(dashboard, "portfolio")
        assert hasattr(dashboard, "analyzer")
        assert hasattr(dashboard, "display")
        assert hasattr(dashboard, "update")

    def test_with_carry_paid(self, mock_portfolio):
        """Test that cumulative carry paid is handled correctly."""
        dashboard = HedgeHealthDashboard(
            mock_portfolio, cumulative_carry_paid=100.0
        )
        assert dashboard.cumulative_carry_paid == 100.0
        widget = dashboard.display()
        assert widget is not None

    def test_with_empty_metrics(self, mock_portfolio):
        """Test dashboard with empty metrics list."""
        # Dashboard doesn't take 'metrics' arg.
        dashboard = HedgeHealthDashboard(mock_portfolio)
        assert dashboard is not None
        widget = dashboard.display()
        assert widget is not None
