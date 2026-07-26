"""Tests for deltadewa.portfolio.position module."""

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.position import OptionPosition
from deltadewa.valuation import OptionValuation


class TestOptionPosition:
    """Test cases for OptionPosition class."""

    def test_initialization(self) -> None:
        """Test OptionPosition can be instantiated."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        position = OptionPosition(
            option=option,
            quantity=1,
            exercise_style=ExerciseStyle.AMERICAN,
            contract_size=100,
        )

        assert position is not None
        assert position.option == option
        assert position.quantity == 1
        assert position.contract_size == 100
        assert position.custom_volatility is False
        assert position.entry_spot is None
        assert position.entry_date is None

    def test_entry_spot_and_date_stored_when_given(self) -> None:
        """Test entry_spot/entry_date are stored verbatim when provided."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        entry_date = datetime.now(tz=UTC)
        position = OptionPosition(
            option=option,
            quantity=1,
            exercise_style=ExerciseStyle.AMERICAN,
            entry_spot=95.0,
            entry_date=entry_date,
        )

        assert position.entry_spot == pytest.approx(95.0, rel=1e-4)
        assert position.entry_date == entry_date

    def test_position_value(self) -> None:
        """Test position_value calculation."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        position = OptionPosition(
            option=option,
            quantity=2,
            exercise_style=ExerciseStyle.AMERICAN,
            contract_size=100,
        )

        # Position value should be option price * quantity * contract_size
        expected_pnl = option.price() * 2 * 100
        assert position.position_value() == expected_pnl

    def test_position_delta(self) -> None:
        """Test position_delta calculation."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        position = OptionPosition(
            option=option,
            quantity=2,
            exercise_style=ExerciseStyle.AMERICAN,
            contract_size=100,
        )

        # Position delta should be option delta * quantity * contract_size
        expected_delta = option.delta() * 2 * 100
        assert position.position_delta() == expected_delta

    def test_position_greeks(self) -> None:
        """Test all Greek calculations."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        position = OptionPosition(
            option=option,
            quantity=1,
            exercise_style=ExerciseStyle.AMERICAN,
            contract_size=100,
        )

        # All greeks should be scaled by quantity * contract_size
        assert position.position_gamma() == option.gamma() * 100
        assert position.position_vega() == option.vega() * 100
        assert position.position_theta() == option.theta() * 100
        assert position.position_rho() == option.rho() * 100

    def test_negative_quantity(self) -> None:
        """Test position with negative quantity (short position)."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        position = OptionPosition(
            option=option,
            quantity=-1,
            exercise_style=ExerciseStyle.AMERICAN,
            contract_size=100,
        )

        # Negative quantity should result in negative value and delta
        assert position.position_value() < 0
        assert position.position_delta() < 0

    def test_to_dict(self) -> None:
        """Test to_dict conversion."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.PUT,
        )
        position = OptionPosition(
            option=option,
            quantity=3,
            exercise_style=ExerciseStyle.AMERICAN,
            contract_size=100,
        )

        pos_dict = position.to_dict()

        assert pos_dict["option_type"] == OptionType.PUT
        assert pos_dict["strike"] == pytest.approx(105.0, rel=1e-5)
        assert pos_dict["quantity"] == 3
        assert pos_dict["contract_size"] == 100
        assert "price" in pos_dict
        assert "position_value" in pos_dict
        assert "delta" in pos_dict
        assert "position_delta" in pos_dict
        assert pos_dict["volatility"] == pytest.approx(0.25, rel=1e-4)
        assert pos_dict["custom_volatility"] is False
        assert pos_dict["entry_spot"] is None
        assert pos_dict["entry_date"] is None

    def test_entry_premium_none_by_default(self) -> None:
        """entry_premium defaults to None when not provided."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.PUT,
        )
        position = OptionPosition(
            option=option, quantity=5, exercise_style=ExerciseStyle.AMERICAN
        )
        assert position.entry_premium is None

    def test_entry_premium_stored_when_given(self) -> None:
        """entry_premium is stored verbatim and appears in to_dict."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.PUT,
        )
        position = OptionPosition(
            option=option,
            quantity=5,
            exercise_style=ExerciseStyle.AMERICAN,
            entry_premium=2.50,
        )
        assert position.entry_premium == pytest.approx(2.50, rel=1e-7)
        assert position.to_dict()["entry_premium"] == pytest.approx(
            2.50, rel=1e-7
        )

    def test_entry_premium_none_in_to_dict_for_legacy(self) -> None:
        """to_dict includes entry_premium key with None for legacy positions."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.PUT,
        )
        position = OptionPosition(
            option=option, quantity=1, exercise_style=ExerciseStyle.AMERICAN
        )
        d = position.to_dict()
        assert "entry_premium" in d
        assert d["entry_premium"] is None

    def test_position_id_auto_generated(self) -> None:
        """position_id is a non-empty string when not supplied."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        position = OptionPosition(
            option=option, quantity=1, exercise_style=ExerciseStyle.AMERICAN
        )
        assert isinstance(position.position_id, str)
        assert position.position_id != ""

    def test_position_id_unique_per_instance(self) -> None:
        """Two independently created positions get different IDs."""
        maturity = datetime.now(tz=UTC) + timedelta(days=30)
        option_a = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=maturity,
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        option_b = OptionValuation(
            spot_price=100.0,
            strike_price=105.0,
            maturity_date=maturity,
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.PUT,
        )
        pos_a = OptionPosition(
            option=option_a, quantity=1, exercise_style=ExerciseStyle.AMERICAN
        )
        pos_b = OptionPosition(
            option=option_b, quantity=1, exercise_style=ExerciseStyle.AMERICAN
        )
        assert pos_a.position_id != pos_b.position_id

    def test_position_id_explicit_restored(self) -> None:
        """An explicit position_id is stored verbatim (serializer restore)."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        pid = "fixed-id-for-test"
        position = OptionPosition(
            option=option,
            quantity=1,
            exercise_style=ExerciseStyle.AMERICAN,
            position_id=pid,
        )
        assert position.position_id == pid

    def test_to_dict_includes_position_id(self) -> None:
        """to_dict() includes position_id key."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        position = OptionPosition(
            option=option, quantity=1, exercise_style=ExerciseStyle.AMERICAN
        )
        d = position.to_dict()
        assert "position_id" in d
        assert d["position_id"] == position.position_id

    def test_custom_volatility_flag(self) -> None:
        """Test custom_volatility flag."""
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.3,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.CALL,
        )
        position = OptionPosition(
            option=option,
            quantity=1,
            exercise_style=ExerciseStyle.AMERICAN,
            contract_size=100,
            custom_volatility=True,
        )

        assert position.custom_volatility is True
        pos_dict = position.to_dict()
        assert pos_dict["custom_volatility"] is True
        assert pos_dict["exercise_style"] == ExerciseStyle.AMERICAN
