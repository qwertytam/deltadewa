"""Tests for deltadewa.portfolio.position module."""

from datetime import UTC, datetime, timedelta

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.position import OptionPosition
from deltadewa.valuation import OptionValuation


class TestOptionPosition:
    """Test cases for OptionPosition class."""

    def test_initialization(self):
        """Test OptionPosition can be instantiated."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            option_type=OptionType.CALL,
        )
        position = OptionPosition(option=option, quantity=1, contract_size=100)

        assert position is not None
        assert position.option == option
        assert position.quantity == 1
        assert position.contract_size == 100
        assert position.custom_volatility is False

    def test_position_value(self):
        """Test position_value calculation."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.AMERICAN,
        )
        position = OptionPosition(option=option, quantity=2, contract_size=100)

        # Position value should be option price * quantity * contract_size
        expected_pnl = option.price() * 2 * 100
        assert position.position_value() == expected_pnl

    def test_position_delta(self):
        """Test position_delta calculation."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.AMERICAN,
        )
        position = OptionPosition(option=option, quantity=2, contract_size=100)

        # Position delta should be option delta * quantity * contract_size
        expected_delta = option.delta() * 2 * 100
        assert position.position_delta() == expected_delta

    def test_position_greeks(self):
        """Test all Greek calculations."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.AMERICAN,
        )
        position = OptionPosition(option=option, quantity=1, contract_size=100)

        # All greeks should be scaled by quantity * contract_size
        assert position.position_gamma() == option.gamma() * 100
        assert position.position_vega() == option.vega() * 100
        assert position.position_theta() == option.theta() * 100
        assert position.position_rho() == option.rho() * 100

    def test_negative_quantity(self):
        """Test position with negative quantity (short position)."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.AMERICAN,
        )
        position = OptionPosition(option=option, quantity=-1, contract_size=100)

        # Negative quantity should result in negative value and delta
        assert position.position_value() < 0
        assert position.position_delta() < 0

    def test_to_dict(self):
        """Test to_dict conversion."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            option_type=OptionType.PUT,
            exercise_style=ExerciseStyle.AMERICAN,
        )
        position = OptionPosition(option=option, quantity=3, contract_size=100)

        pos_dict = position.to_dict()

        assert pos_dict["option_type"] == OptionType.PUT
        assert pos_dict["strike"] == 105.0
        assert pos_dict["quantity"] == 3
        assert pos_dict["contract_size"] == 100
        assert "price" in pos_dict
        assert "position_value" in pos_dict
        assert "delta" in pos_dict
        assert "position_delta" in pos_dict
        assert pos_dict["volatility"] == 0.25
        assert pos_dict["custom_volatility"] is False

    def test_custom_volatility_flag(self):
        """Test custom_volatility flag."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.3,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.AMERICAN,
        )
        position = OptionPosition(
            option=option,
            quantity=1,
            contract_size=100,
            custom_volatility=True,
        )

        assert position.custom_volatility is True
        pos_dict = position.to_dict()
        assert pos_dict["custom_volatility"] is True
        assert pos_dict["exercise_style"] == ExerciseStyle.AMERICAN
