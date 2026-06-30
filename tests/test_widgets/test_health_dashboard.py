"""Tests for deltadewa.widgets.health_dashboard module."""

from unittest.mock import Mock

import ipywidgets as widgets  # type: ignore[import-untyped]
import pytest

from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.widgets.health_dashboard import (
    HedgeHealthDashboard,
    HedgeHealthMetric,
)


class TestHedgeHealthMetric:
    """Test cases for HedgeHealthMetric class."""

    def test_initialization(self) -> None:
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

    def test_metric_attributes(self) -> None:
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
    def mock_portfolio(self) -> OptionPortfolio:
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
    def sample_metrics(self) -> list:
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

    def test_initialization(self, mock_portfolio: OptionPortfolio) -> None:
        """Test HedgeHealthDashboard can be instantiated."""
        # Note: Init only takes portfolio, other args are optional scalars.
        # It creates its OWN
        # analyzer internally: self.analyzer = PortfolioAnalyzer(portfolio)
        dashboard = HedgeHealthDashboard(mock_portfolio)
        assert dashboard is not None
        assert dashboard.portfolio == mock_portfolio
        assert hasattr(dashboard, "analyzer")

    def test_initialization_with_metrics(
        self,
        mock_portfolio: OptionPortfolio,
    ) -> None:
        """Test HedgeHealthDashboard initialization."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        # Just check it runs
        assert dashboard is not None

    def test_display_method(self, mock_portfolio: OptionPortfolio) -> None:
        """Test display method returns a widget."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        # Ensure cumulative_carry_paid is float (default 0.0)
        widget = dashboard.display()
        assert widget is not None

    def test_update_method(self, mock_portfolio: OptionPortfolio) -> None:
        """Test update method can be called."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        dashboard.update()

    def test_update_with_params(self, mock_portfolio: OptionPortfolio) -> None:
        """Test update method with parameters."""
        dashboard = HedgeHealthDashboard(mock_portfolio)

        # Mock portfolio updates
        mock_portfolio.spot_price = 110.0
        mock_portfolio.volatility = 0.30

        dashboard.update()

    def test_attributes_exist(self, mock_portfolio: OptionPortfolio) -> None:
        """Test all expected attributes exist."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        assert hasattr(dashboard, "portfolio")
        assert hasattr(dashboard, "analyzer")
        assert hasattr(dashboard, "display")
        assert hasattr(dashboard, "update")

    def test_with_carry_paid(self, mock_portfolio: OptionPortfolio) -> None:
        """Test that cumulative carry paid is handled correctly."""
        dashboard = HedgeHealthDashboard(
            mock_portfolio,
            cumulative_carry_paid=100.0,
        )
        assert dashboard.cumulative_carry_paid == 100.0
        widget = dashboard.display()
        assert widget is not None

    def test_with_empty_metrics(self, mock_portfolio: OptionPortfolio) -> None:
        """Test dashboard with empty metrics list."""
        # Dashboard doesn't take 'metrics' arg.
        dashboard = HedgeHealthDashboard(mock_portfolio)
        assert dashboard is not None
        widget = dashboard.display()
        assert widget is not None

    def test_config_initialization(
        self,
        mock_portfolio: OptionPortfolio,
    ) -> None:
        """Test that config is initialized with defaults."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        assert hasattr(dashboard, "config")
        assert "parameters" in dashboard.config
        assert "metrics" in dashboard.config
        assert "historical_vol_low" in dashboard.config["parameters"]
        assert "historical_vol_high" in dashboard.config["parameters"]
        assert "convexity_cliff_days" in dashboard.config["parameters"]

    def test_config_override_with_init_params(
        self,
        mock_portfolio: OptionPortfolio,
    ) -> None:
        """Test that init parameters override default config."""
        dashboard = HedgeHealthDashboard(
            mock_portfolio,
            historical_vol_low=0.20,
            historical_vol_high=0.40,
            convexity_cliff_days=200,
        )
        assert dashboard.config["parameters"]["historical_vol_low"] == 0.20
        assert dashboard.config["parameters"]["historical_vol_high"] == 0.40
        assert dashboard.config["parameters"]["convexity_cliff_days"] == 200

    def test_config_param_applies_on_init(
        self,
        mock_portfolio: OptionPortfolio,
    ) -> None:
        """Test a passed config dict is merged via load_config on init."""
        dashboard = HedgeHealthDashboard(
            mock_portfolio,
            config={
                "parameters": {"historical_vol_low": 0.5},
                "metrics": {"net_carry": {"max_val": 99.0}},
            },
        )

        assert dashboard.config["parameters"]["historical_vol_low"] == 0.5
        assert dashboard.config["metrics"]["net_carry"]["max_val"] == 99.0

    def test_config_none_uses_defaults(
        self,
        mock_portfolio: OptionPortfolio,
    ) -> None:
        """Test omitting config (the default) leaves defaults untouched."""
        dashboard = HedgeHealthDashboard(mock_portfolio)

        defaults = dashboard._get_default_config()  # pylint: disable=W0212
        assert (
            dashboard.config["parameters"]["historical_vol_low"]
            == (defaults["parameters"]["historical_vol_low"])
        )

    def test_get_default_config(self, mock_portfolio: OptionPortfolio) -> None:
        """Test that _get_default_config returns expected structure."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        config = dashboard._get_default_config()  # pylint: disable=W0212

        assert "parameters" in config
        assert "metrics" in config

        # Check parameters
        assert config["parameters"]["historical_vol_low"] == 0.15
        assert config["parameters"]["historical_vol_high"] == 0.35
        assert config["parameters"]["convexity_cliff_days"] == 180

        # Check metrics exist
        expected_metrics = [
            "net_carry",
            "crash_convexity",
            "vega_sufficiency",
            "delta_drift",
            "convexity_cliff",
            "vol_regime",
            "hedge_success",
        ]
        for metric in expected_metrics:
            assert metric in config["metrics"]
            assert "start" in config["metrics"][metric]
            assert "end" in config["metrics"][metric]
            assert "min_val" in config["metrics"][metric]
            assert "mid_val" in config["metrics"][metric]
            assert "max_val" in config["metrics"][metric]
            assert "invert_colors" in config["metrics"][metric]

    def test_load_config_parameters(
        self,
        mock_portfolio: OptionPortfolio,
    ) -> None:
        """Test loading configuration with parameter updates."""
        dashboard = HedgeHealthDashboard(mock_portfolio)

        new_config = {
            "parameters": {
                "historical_vol_low": 0.18,
                "historical_vol_high": 0.38,
            },
        }

        dashboard.load_config(new_config)

        assert dashboard.config["parameters"]["historical_vol_low"] == 0.18
        assert dashboard.config["parameters"]["historical_vol_high"] == 0.38
        # convexity_cliff_days should remain unchanged
        assert dashboard.config["parameters"]["convexity_cliff_days"] == 180

    def test_load_config_metrics(self, mock_portfolio: OptionPortfolio) -> None:
        """Test loading configuration with metric threshold updates."""
        dashboard = HedgeHealthDashboard(mock_portfolio)

        new_config = {
            "metrics": {
                "net_carry": {
                    "start": -15.0,
                    "end": 15.0,
                    "min_val": -8.0,
                    "max_val": 4.0,
                },
            },
        }

        dashboard.load_config(new_config)

        assert dashboard.config["metrics"]["net_carry"]["start"] == -15.0
        assert dashboard.config["metrics"]["net_carry"]["end"] == 15.0
        assert dashboard.config["metrics"]["net_carry"]["min_val"] == -8.0
        assert dashboard.config["metrics"]["net_carry"]["max_val"] == 4.0
        # mid_val should remain unchanged
        assert dashboard.config["metrics"]["net_carry"]["mid_val"] == 0.0

    def test_load_config_full(self, mock_portfolio: OptionPortfolio) -> None:
        """Test loading full configuration with both parameters and metrics."""
        dashboard = HedgeHealthDashboard(mock_portfolio)

        new_config = {
            "parameters": {
                "historical_vol_low": 0.12,
                "convexity_cliff_days": 150,
            },
            "metrics": {
                "crash_convexity": {
                    "start": -40.0,
                    "end": 40.0,
                },
                "vol_regime": {
                    "min_val": 20,
                    "max_val": 80,
                },
            },
        }

        dashboard.load_config(new_config)

        # Check parameters
        assert dashboard.config["parameters"]["historical_vol_low"] == 0.12
        assert dashboard.config["parameters"]["convexity_cliff_days"] == 150

        # Check metrics
        assert dashboard.config["metrics"]["crash_convexity"]["start"] == -40.0
        assert dashboard.config["metrics"]["crash_convexity"]["end"] == 40.0
        assert dashboard.config["metrics"]["vol_regime"]["min_val"] == 20
        assert dashboard.config["metrics"]["vol_regime"]["max_val"] == 80

    def test_display_config_loader(
        self,
        mock_portfolio: OptionPortfolio,
    ) -> None:
        """Test that display_config_loader returns a widget."""
        dashboard = HedgeHealthDashboard(mock_portfolio)
        loader_widget = dashboard.display_config_loader()

        assert loader_widget is not None
        assert hasattr(loader_widget, "children")
        # Check for expected widget types rather than exact count
        children = loader_widget.children
        assert any(isinstance(child, widgets.HTML) for child in children), (
            "Should have HTML label widget"
        )
        assert any(
            isinstance(child, widgets.FileUpload) for child in children
        ), "Should have FileUpload widget"
        assert any(isinstance(child, widgets.Output) for child in children), (
            "Should have Output widget"
        )
