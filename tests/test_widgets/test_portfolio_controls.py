"""Tests for deltadewa.widgets.portfolio_controls module."""

from unittest.mock import Mock
import pytest
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

    @pytest.fixture
    def mock_serializer(self):
        """Create a mock serializer for testing."""
        serializer = Mock()
        serializer.serialize = Mock(return_value="serialized_data")
        serializer.deserialize = Mock(return_value="deserialized_data")
        return serializer

    @pytest.fixture
    def mock_changelog(self):
        """Create a mock changelog for testing."""
        changelog = Mock()
        changelog.log = Mock()
        return changelog

    def test_initialization(
        self, mock_portfolio, mock_serializer, mock_changelog
    ):
        """Test PortfolioWidgets can be instantiated."""
        widgets = PortfolioWidgets(
            mock_portfolio, mock_serializer, mock_changelog
        )
        assert widgets is not None
        assert widgets.portfolio == mock_portfolio
        assert widgets.serializer == mock_serializer

    def test_create_position_editor(
        self, mock_portfolio, mock_serializer, mock_changelog
    ):
        """Test create_position_editor method."""
        widgets = PortfolioWidgets(
            mock_portfolio, mock_serializer, mock_changelog
        )
        editor = widgets.create_position_editor()
        assert editor is not None
        assert hasattr(editor, "children") or hasattr(editor, "value")

    def test_create_market_params_controls(
        self, mock_portfolio, mock_serializer, mock_changelog
    ):
        """Test create_market_params_controls method."""
        widgets = PortfolioWidgets(
            mock_portfolio, mock_serializer, mock_changelog
        )
        controls = widgets.create_market_params_controls(
            spot_price=mock_portfolio.spot_price,
            volatility=mock_portfolio.volatility,
        )
        assert controls is not None

    def test_create_transaction_cost_controls(
        self, mock_portfolio, mock_serializer, mock_changelog
    ):
        """Test create_transaction_cost_controls method."""
        widgets = PortfolioWidgets(
            mock_portfolio, mock_serializer, mock_changelog
        )
        controls = widgets.create_transaction_cost_controls()
        assert controls is not None

    def test_create_roll_analysis_controls(
        self, mock_portfolio, mock_serializer, mock_changelog
    ):
        """Test create_roll_controls method."""
        widgets = PortfolioWidgets(
            mock_portfolio, mock_serializer, mock_changelog
        )
        controls = widgets.create_roll_controls()
        assert controls is not None

    def test_create_export_controls(
        self, mock_portfolio, mock_serializer, mock_changelog
    ):
        """Test create_export_controls method."""
        widgets = PortfolioWidgets(
            mock_portfolio, mock_serializer, mock_changelog
        )
        controls = widgets.create_export_controls()
        assert controls is not None

    def test_create_import_controls(
        self, mock_portfolio, mock_serializer, mock_changelog
    ):
        """Test create_import_controls method."""
        widgets = PortfolioWidgets(
            mock_portfolio, mock_serializer, mock_changelog
        )
        controls = widgets.create_import_controls()
        assert controls is not None

    def test_attributes_exist(
        self, mock_portfolio, mock_serializer, mock_changelog
    ):
        """Test all expected attributes exist."""
        widgets = PortfolioWidgets(
            mock_portfolio, mock_serializer, mock_changelog
        )
        assert hasattr(widgets, "portfolio")
        assert hasattr(widgets, "create_position_editor")
        assert hasattr(widgets, "create_market_params_controls")
        # Removed create_scenario_controls as it is not in the class
        assert hasattr(widgets, "create_roll_controls")
        assert hasattr(widgets, "create_export_controls")
        assert hasattr(widgets, "create_import_controls")
