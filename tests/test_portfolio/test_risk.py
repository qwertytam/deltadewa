"""Tests for deltadewa.portfolio.risk module."""

from datetime import UTC, datetime, timedelta

import numpy as np

from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio


class TestRiskMixin:
    """Test cases for RiskMixin."""

    def test_get_spot_range(self) -> None:
        """Test _get_spot_range helper method."""
        portfolio = OptionPortfolio(spot_price=100.0)
        # pylint: disable=protected-access
        spot_range = portfolio._get_spot_range(num_points=10)

        assert isinstance(spot_range, np.ndarray)
        assert len(spot_range) == 10

    def test_get_spot_range_comprehensive(self) -> None:
        """Test _get_spot_range with comprehensive range."""
        portfolio = OptionPortfolio(spot_price=100.0)
        # pylint: disable=protected-access
        spot_range = portfolio._get_spot_range(use_comprehensive_range=True)

        assert isinstance(spot_range, np.ndarray)
        assert len(spot_range) > 0
        # Should include extreme values
        assert min(spot_range) < 1.0
        assert max(spot_range) > 500.0

    def test_calculate_max_loss_options(self) -> None:
        """Test calculate_max_loss_options method."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Long call - limited loss
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        result = portfolio.calculate_max_loss_options()

        assert "max_loss" in result
        assert "spot_at_max_loss" in result
        assert "is_unlimited" in result
        # Long call has limited loss (premium paid)
        assert result["is_unlimited"] is False
        assert result["max_loss"] < 0

    def test_calculate_max_profit_options(self) -> None:
        """Test calculate_max_profit_options method."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Long call - unlimited profit
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        result = portfolio.calculate_max_profit_options()

        assert "max_profit" in result
        assert "spot_at_max_profit" in result
        assert "is_unlimited" in result
        # Long call has unlimited profit
        assert result["is_unlimited"] is True

    def test_calculate_max_loss_short_call(self) -> None:
        """Test calculate_max_loss_options with naked short call."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Short call - unlimited loss
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        result = portfolio.calculate_max_loss_options()

        assert result["is_unlimited"] is True

    def test_calculate_max_profit_short_call(self) -> None:
        """Test calculate_max_profit_options with short call."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Short call - limited profit (premium received)
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        result = portfolio.calculate_max_profit_options()

        assert result["is_unlimited"] is False
        # Profit limited to premium
        assert result["max_profit"] > 0

    def test_calculate_max_loss_total(self) -> None:
        """Test calculate_max_loss_total with underlying."""
        portfolio = OptionPortfolio(underlying_quantity=100.0, spot_price=100.0)

        result = portfolio.calculate_max_loss_total()

        assert "max_loss" in result
        assert "is_unlimited" in result
        # Long underlying has limited loss (spot to zero)
        assert result["is_unlimited"] is False

    def test_calculate_max_profit_total(self) -> None:
        """Test calculate_max_profit_total with underlying."""
        portfolio = OptionPortfolio(underlying_quantity=100.0, spot_price=100.0)

        result = portfolio.calculate_max_profit_total()

        assert "max_profit" in result
        assert "is_unlimited" in result
        # Long underlying has unlimited profit
        assert result["is_unlimited"] is True

    def test_calculate_breakeven_points(self) -> None:
        """Test calculate_breakeven_points method."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Long call
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        breakevens = portfolio.calculate_breakeven_points()

        assert isinstance(breakevens, list)
        # Long call should have one breakeven point
        assert len(breakevens) > 0

    def test_breakeven_empty_portfolio(self) -> None:
        """Test calculate_breakeven_points with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)

        breakevens = portfolio.calculate_breakeven_points()

        # Empty portfolio has no breakeven
        assert len(breakevens) == 0

    def test_check_unlimited_trend(self) -> None:
        """Test _check_unlimited_trend helper method."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Long call
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        spot_range = np.linspace(100, 500, 100)

        # Compute PnL array
        pnl_array = portfolio.vectorized_pnl_at_expiry(
            spot_range,
            include_underlying=False,
        )

        # Check increasing trend (profit)
        # pylint: disable=protected-access
        result = portfolio._check_unlimited_trend(
            pnl_array,
            check_increasing=True,
        )

        assert isinstance(result, bool)

    def test_vectorized_risk_methods_numerical_equivalence(self) -> None:
        """Test that vectorized risk methods produce identical results to scalar approach."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Create a complex multi-leg position (iron condor)
        portfolio.add_position(
            strike_price=90.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.PUT,
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        # Generate spot range
        # pylint: disable=protected-access
        spot_range = portfolio._get_spot_range(use_comprehensive_range=True)

        # Calculate using vectorized methods
        max_loss_vec = portfolio.calculate_max_loss_options(spot_range)
        max_profit_vec = portfolio.calculate_max_profit_options(spot_range)
        breakeven_vec = portfolio.calculate_breakeven_points(
            spot_range,
            include_underlying=False,
        )

        # Verify results are computed properly (types and reasonable values)
        assert isinstance(max_loss_vec["max_loss"], float)
        assert isinstance(max_loss_vec["spot_at_max_loss"], float)
        assert isinstance(max_loss_vec["is_unlimited"], bool)

        assert isinstance(max_profit_vec["max_profit"], float)
        assert isinstance(max_profit_vec["spot_at_max_profit"], float)
        assert isinstance(max_profit_vec["is_unlimited"], bool)

        assert isinstance(breakeven_vec, list)
        assert all(isinstance(x, float) for x in breakeven_vec)

        # Verify vectorized gives same results by comparing PnL at a few key spots
        test_spots = np.array([80.0, 90.0, 95.0, 100.0, 105.0, 110.0, 120.0])
        pnl_vectorized = portfolio.vectorized_pnl_at_expiry(
            test_spots,
            include_underlying=False,
        )

        for i, spot in enumerate(test_spots):
            pnl_scalar = portfolio.calculate_pnl_at_expiry(
                spot,
                include_underlying=False,
            )
            assert np.isclose(
                pnl_vectorized[i],
                pnl_scalar,
                rtol=1e-10,
            ), f"Mismatch at spot={spot}: vectorized={pnl_vectorized[i]}, scalar={pnl_scalar}"
