"""Tests for deltadewa.portfolio.core module."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from deltadewa.portfolio.core import OptionPortfolio


class TestOptionPortfolio:
    """Test cases for OptionPortfolio core functionality."""

    @pytest.fixture
    def portfolio(self):
        """Create an empty portfolio for testing."""
        return OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            valuation_date=datetime(2024, 1, 1),
        )

    def test_initialization(self):
        """Test OptionPortfolio can be instantiated with defaults."""
        portfolio = OptionPortfolio()
        assert portfolio is not None
        assert portfolio.underlying_quantity == 0.0
        assert portfolio.spot_price == 100.0
        assert portfolio.volatility == 0.2
        assert portfolio.risk_free_rate == 0.05
        assert portfolio.dividend_yield == 0.0
        assert len(portfolio.positions) == 0

    def test_initialization_with_parameters(self, portfolio):
        """Test OptionPortfolio initialization with custom parameters."""
        assert portfolio.underlying_quantity == 100.0
        assert portfolio.spot_price == 100.0
        assert portfolio.volatility == 0.25
        assert portfolio.risk_free_rate == 0.05
        assert portfolio.dividend_yield == 0.02
        assert portfolio.valuation_date == datetime(2024, 1, 1)

    @patch('deltadewa.portfolio.core.AmericanOption')
    def test_add_position(self, mock_option_class, portfolio):
        """Test adding a position to the portfolio."""
        mock_option = Mock()
        mock_option_class.return_value = mock_option
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime(2024, 12, 31),
            quantity=10,
            option_type="call",
            symbol="TEST",
        )
        
        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].quantity == 10
        assert portfolio.positions[0].symbol == "TEST"
        assert portfolio.positions[0].custom_volatility is False

    @patch('deltadewa.portfolio.core.AmericanOption')
    def test_add_position_with_custom_volatility(self, mock_option_class, portfolio):
        """Test adding a position with custom volatility."""
        mock_option = Mock()
        mock_option_class.return_value = mock_option
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime(2024, 12, 31),
            quantity=10,
            option_type="call",
            symbol="TEST",
            volatility=0.30,  # Custom volatility
        )
        
        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].custom_volatility is True

    def test_set_volatility(self, portfolio):
        """Test setting portfolio volatility."""
        portfolio.volatility = 0.20
        portfolio.set_volatility(0.30)
        assert portfolio.volatility == 0.30

    def test_get_symbol_empty(self, portfolio):
        """Test get_symbol with empty portfolio."""
        assert portfolio.get_symbol() == "N/A"

    @patch('deltadewa.portfolio.core.AmericanOption')
    def test_get_symbol_with_positions(self, mock_option_class, portfolio):
        """Test get_symbol with positions."""
        mock_option = Mock()
        mock_option_class.return_value = mock_option
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime(2024, 12, 31),
            quantity=10,
            option_type="call",
            symbol="AAPL",
        )
        
        assert portfolio.get_symbol() == "AAPL"

    def test_monte_carlo_results_property(self, portfolio):
        """Test monte_carlo_results property getter and setter."""
        assert portfolio.monte_carlo_results is None
        
        results = {"expected_value": 100.0, "probability": 0.65}
        portfolio.monte_carlo_results = results
        
        assert portfolio.monte_carlo_results == results

    def test_clear_positions(self, portfolio):
        """Test clearing all positions."""
        # Add mock positions
        portfolio.positions = [Mock(), Mock(), Mock()]
        assert len(portfolio.positions) == 3
        
        portfolio.clear_positions()
        assert len(portfolio.positions) == 0

    @patch('deltadewa.portfolio.core.AmericanOption')
    def test_remove_position(self, mock_option_class, portfolio):
        """Test removing a position by index."""
        mock_option = Mock()
        mock_option_class.return_value = mock_option
        
        # Add two positions
        portfolio.add_position(100.0, datetime(2024, 12, 31), 10, "call")
        portfolio.add_position(95.0, datetime(2024, 12, 31), 5, "put")
        
        assert len(portfolio.positions) == 2
        portfolio.remove_position(0)
        assert len(portfolio.positions) == 1

    def test_remove_position_invalid_index(self, portfolio):
        """Test removing with invalid index raises error."""
        with pytest.raises(IndexError):
            portfolio.remove_position(0)
        
        with pytest.raises(IndexError):
            portfolio.remove_position(-1)

    def test_get_positions(self, portfolio):
        """Test get_positions returns correct format."""
        positions = portfolio.get_positions()
        assert isinstance(positions, list)
        assert len(positions) == 0

    def test_summary(self, portfolio):
        """Test summary method returns string."""
        summary = portfolio.summary()
        assert isinstance(summary, str)
        assert "Positions:" in summary
        assert "Value:" in summary

    def test_summary_market(self, portfolio):
        """Test summary_market method returns string."""
        summary = portfolio.summary_market()
        assert isinstance(summary, str)
        assert "Spot Price:" in summary
        assert "Volatility:" in summary

    def test_repr(self, portfolio):
        """Test __repr__ method."""
        repr_str = repr(portfolio)
        assert "OptionPortfolio" in repr_str
        assert "positions=" in repr_str

    def test_to_dataframe_empty(self, portfolio):
        """Test to_dataframe with empty portfolio."""
        df = portfolio.to_dataframe()
        assert df.empty

    def test_summary_stats(self, portfolio):
        """Test summary_stats returns correct structure."""
        stats = portfolio.summary_stats()
        assert isinstance(stats, dict)
        assert "total_positions" in stats
        assert "total_value" in stats
        assert "total_delta" in stats
        assert "net_delta" in stats
        assert "hedge_ratio" in stats
        assert "volatility_min" in stats
        assert "volatility_max" in stats
        assert stats["total_positions"] == 0
        assert stats["underlying_quantity"] == 100.0
