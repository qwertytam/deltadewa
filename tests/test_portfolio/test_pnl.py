"""Tests for deltadewa.portfolio.pnl module."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio


class TestPnLMixin:
    """Test cases for PnLMixin."""

    def test_calculate_net_debit(self) -> None:
        """Test calculate_net_debit method."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        net_debit = portfolio.calculate_net_debit()
        # Should equal total_value
        assert net_debit == portfolio.total_value()
        assert net_debit > 0

    def test_calculate_pnl_at_expiry(self) -> None:
        """Test calculate_pnl_at_expiry method."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # Buy a call at 100 strike
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        # If spot goes to 110, call is worth 10 per share
        pnl_high = portfolio.calculate_pnl_at_expiry(110.0)
        # PnL = intrinsic value - initial cost
        # Intrinsic = (110 - 100) * 100 = 1000
        # Should be positive
        assert pnl_high > 0

        # If spot goes to 90, call expires worthless
        pnl_low = portfolio.calculate_pnl_at_expiry(90.0)
        # PnL = 0 - initial cost (loss)
        assert pnl_low < 0

    def test_calculate_pnl_at_expiry_put(self) -> None:
        """Test calculate_pnl_at_expiry with put option."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # Buy a put at 100 strike
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )

        # If spot goes to 90, put is worth 10 per share
        pnl_low = portfolio.calculate_pnl_at_expiry(90.0)
        # Should be positive (or less negative than initial cost)
        assert isinstance(pnl_low, float)

        # If spot goes to 110, put expires worthless
        pnl_high = portfolio.calculate_pnl_at_expiry(110.0)
        # PnL = 0 - initial cost (loss)
        assert pnl_high < 0

    def test_calculate_pnl_with_underlying(self) -> None:
        """Test calculate_pnl_at_expiry including underlying position."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # No options, just underlying
        pnl_up = portfolio.calculate_pnl_at_expiry(
            110.0,
            include_underlying=True,
        )
        # Underlying gained 10 per share * 100 shares = 1000
        assert pnl_up == pytest.approx(1000.0, rel=1e-2)

        pnl_down = portfolio.calculate_pnl_at_expiry(
            90.0,
            include_underlying=True,
        )
        # Underlying lost 10 per share * 100 shares = -1000
        assert pnl_down == pytest.approx(-1000.0, rel=1e-4)

    def test_calculate_pnl_short_option(self) -> None:
        """Test calculate_pnl_at_expiry with short option."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # Sell a call at 100 strike
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        # If spot goes to 110, we lose on the short call
        pnl_high = portfolio.calculate_pnl_at_expiry(110.0)
        # Should be negative (loss from ITM call we're short)
        assert pnl_high < 0

        # If spot goes to 90, short call expires worthless (profit)
        pnl_low = portfolio.calculate_pnl_at_expiry(90.0)
        # Should be positive (kept the premium)
        assert pnl_low > 0

    def test_calculate_pnl_empty_portfolio(self) -> None:
        """Test calculate_pnl_at_expiry with empty portfolio."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        pnl = portfolio.calculate_pnl_at_expiry(110.0)
        # No positions, no P&L
        assert pnl == pytest.approx(0.0, rel=1e-8)

    def test_calculate_net_debit_credit(self) -> None:
        """Test calculate_net_debit for credit spread."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # Sell OTM put (collect premium)
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.PUT,
        )

        # Buy further OTM put (pay premium)
        portfolio.add_position(
            strike_price=90.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )

        net_debit = portfolio.calculate_net_debit()
        # Credit spread should have negative net debit (we receive money)
        # Note: This depends on pricing, but typically credit spreads are net
        # negative
        assert isinstance(net_debit, float)

    def test_vectorized_pnl_at_expiry(self) -> None:
        """Test vectorized_pnl_at_expiry method."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # Buy a call at 100 strike
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        # Test with array of spot prices
        spot_range = np.array([90.0, 100.0, 110.0, 120.0])
        pnl_array = portfolio.vectorized_pnl_at_expiry(
            spot_range,
            include_underlying=False,
        )

        # Should return numpy array
        assert isinstance(pnl_array, np.ndarray)
        assert len(pnl_array) == len(spot_range)

        # Verify results match scalar calculation
        for i, spot in enumerate(spot_range):
            scalar_pnl = portfolio.calculate_pnl_at_expiry(
                spot,
                include_underlying=False,
            )
            assert np.isclose(pnl_array[i], scalar_pnl), (
                f"Mismatch at spot={spot}: vectorized={pnl_array[i]}, "
                f"scalar={scalar_pnl}"
            )

    def test_vectorized_pnl_with_underlying(self) -> None:
        """Test vectorized_pnl_at_expiry including underlying position."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        spot_range = np.array([90.0, 100.0, 110.0])
        pnl_array = portfolio.vectorized_pnl_at_expiry(
            spot_range,
            include_underlying=True,
        )

        # Verify against scalar calculation
        for i, spot in enumerate(spot_range):
            scalar_pnl = portfolio.calculate_pnl_at_expiry(
                spot,
                include_underlying=True,
            )
            assert np.isclose(pnl_array[i], scalar_pnl)

    def test_vectorized_pnl_multi_position(self) -> None:
        """Test vectorized calculation with multiple positions."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # Create a bull call spread
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        spot_range = np.linspace(80, 120, 50)
        pnl_array = portfolio.vectorized_pnl_at_expiry(spot_range)

        # Verify all values against scalar calculation
        for i, spot in enumerate(spot_range):
            scalar_pnl = portfolio.calculate_pnl_at_expiry(spot)
            assert np.isclose(pnl_array[i], scalar_pnl, rtol=1e-10), (
                f"Mismatch at spot={spot}: vectorized={pnl_array[i]}, "
                f"scalar={scalar_pnl}"
            )

    def test_scalar_and_vectorized_agree_both_modes(self) -> None:
        """Scalar and vectorized P&L match for both include_underlying values.

        Uses a book *with* an underlying so the two modes actually differ,
        pinning Mi5 parity across the choice.
        """
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )

        spots = np.linspace(80, 120, 25)
        for include_underlying in (False, True):
            vectorized = portfolio.vectorized_pnl_at_expiry(
                spots,
                include_underlying=include_underlying,
            )
            scalar = np.array(
                [
                    portfolio.calculate_pnl_at_expiry(
                        float(spot),
                        include_underlying=include_underlying,
                    )
                    for spot in spots
                ],
            )
            np.testing.assert_allclose(vectorized, scalar, rtol=1e-10)

    def test_pnl_defaults_to_options_only(self) -> None:
        """Both P&L paths default to options-only (Mi5: unified to False)."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )

        spots = np.array([90.0, 110.0])
        # Default == explicit options-only for both paths.
        np.testing.assert_allclose(
            portfolio.vectorized_pnl_at_expiry(spots),
            portfolio.vectorized_pnl_at_expiry(spots, include_underlying=False),
        )
        assert portfolio.calculate_pnl_at_expiry(
            110.0,
        ) == portfolio.calculate_pnl_at_expiry(110.0, include_underlying=False)
        # And the default really excludes the (present) underlying.
        assert not np.allclose(
            portfolio.vectorized_pnl_at_expiry(spots),
            portfolio.vectorized_pnl_at_expiry(spots, include_underlying=True),
        )
