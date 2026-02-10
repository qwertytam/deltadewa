"""Tests for deltadewa.portfolio.position module."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock
from deltadewa.portfolio.position import OptionPosition


class TestOptionPosition:
    """Test cases for OptionPosition class."""

    @pytest.fixture
    def mock_option(self):
        """Create a mock AmericanOption for testing."""
        option = Mock()
        option.price.return_value = 5.0
        option.delta.return_value = 0.5
        option.gamma.return_value = 0.02
        option.vega.return_value = 0.1
        option.theta.return_value = -0.05
        option.rho.return_value = 0.03
        option.option_type = "call"
        option.strike_price = 100.0
        option.maturity_date = datetime(2024, 12, 31)
        option.volatility = 0.25
        option.greeks.return_value = {
            "price": 5.0,
            "delta": 0.5,
            "gamma": 0.02,
            "vega": 0.1,
            "theta": -0.05,
            "rho": 0.03,
        }
        return option

    @pytest.fixture
    def position(self, mock_option):
        """Create a position for testing."""
        return OptionPosition(
            option=mock_option,
            quantity=10,
            contract_size=100,
            symbol="TEST",
            custom_volatility=False,
        )

    def test_initialization(self, mock_option):
        """Test OptionPosition can be instantiated."""
        position = OptionPosition(
            option=mock_option,
            quantity=10,
            contract_size=100,
            symbol="TEST",
        )
        assert position is not None
        assert position.option == mock_option
        assert position.quantity == 10
        assert position.contract_size == 100
        assert position.symbol == "TEST"
        assert position.custom_volatility is False

    def test_position_value(self, position):
        """Test position_value calculation."""
        # price=5.0, quantity=10, contract_size=100
        expected = 5.0 * 10 * 100
        assert position.position_value() == expected

    def test_position_delta(self, position):
        """Test position_delta calculation."""
        # delta=0.5, quantity=10, contract_size=100
        expected = 0.5 * 10 * 100
        assert position.position_delta() == expected

    def test_position_gamma(self, position):
        """Test position_gamma calculation."""
        # gamma=0.02, quantity=10, contract_size=100
        expected = 0.02 * 10 * 100
        assert position.position_gamma() == expected

    def test_position_vega(self, position):
        """Test position_vega calculation."""
        # vega=0.1, quantity=10, contract_size=100
        expected = 0.1 * 10 * 100
        assert position.position_vega() == expected

    def test_position_theta(self, position):
        """Test position_theta calculation."""
        # theta=-0.05, quantity=10, contract_size=100
        expected = -0.05 * 10 * 100
        assert position.position_theta() == expected

    def test_position_rho(self, position):
        """Test position_rho calculation."""
        # rho=0.03, quantity=10, contract_size=100
        expected = 0.03 * 10 * 100
        assert position.position_rho() == expected

    def test_to_dict(self, position):
        """Test to_dict method."""
        result = position.to_dict()
        assert isinstance(result, dict)
        assert result["symbol"] == "TEST"
        assert result["type"] == "call"
        assert result["strike"] == 100.0
        assert result["quantity"] == 10
        assert result["price"] == 5.0
        assert result["position_value"] == 5000.0
        assert result["delta"] == 0.5
        assert result["position_delta"] == 500.0
        assert result["contract_size"] == 100
        assert result["volatility"] == 0.25
        assert result["custom_volatility"] is False

    def test_negative_quantity(self, mock_option):
        """Test position with negative quantity (short position)."""
        position = OptionPosition(
            option=mock_option, quantity=-5, contract_size=100, symbol="TEST"
        )
        # Short position should have negative values
        assert position.position_value() == -2500.0  # 5.0 * -5 * 100
        assert position.position_delta() == -250.0  # 0.5 * -5 * 100
