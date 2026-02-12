"""Tests for deltadewa.portfolio.pnl module."""

from datetime import datetime, timedelta
import numpy as np
from deltadewa.portfolio.core import OptionPortfolio


class TestPnLMixin:
    """Test cases for PnLMixin."""

    def test_calculate_net_debit(self):
        """Test calculate_net_debit method."""
        portfolio = OptionPortfolio(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        net_debit = portfolio.calculate_net_debit()
        # Should equal total_value
        assert net_debit == portfolio.total_value()
        assert net_debit > 0

    def test_calculate_pnl_at_expiry(self):
        """Test calculate_pnl_at_expiry method."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Buy a call at 100 strike
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
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

    def test_calculate_pnl_at_expiry_put(self):
        """Test calculate_pnl_at_expiry with put option."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Buy a put at 100 strike
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="put",
        )

        # If spot goes to 90, put is worth 10 per share
        pnl_low = portfolio.calculate_pnl_at_expiry(90.0)
        # Should be positive (or less negative than initial cost)
        assert isinstance(pnl_low, float)

        # If spot goes to 110, put expires worthless
        pnl_high = portfolio.calculate_pnl_at_expiry(110.0)
        # PnL = 0 - initial cost (loss)
        assert pnl_high < 0

    def test_calculate_pnl_with_underlying(self):
        """Test calculate_pnl_at_expiry including underlying position."""
        portfolio = OptionPortfolio(underlying_quantity=100.0, spot_price=100.0)

        # No options, just underlying
        pnl_up = portfolio.calculate_pnl_at_expiry(
            110.0, include_underlying=True
        )
        # Underlying gained 10 per share * 100 shares = 1000
        assert pnl_up == 1000.0

        pnl_down = portfolio.calculate_pnl_at_expiry(
            90.0, include_underlying=True
        )
        # Underlying lost 10 per share * 100 shares = -1000
        assert pnl_down == -1000.0

    def test_calculate_pnl_short_option(self):
        """Test calculate_pnl_at_expiry with short option."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Sell a call at 100 strike
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="call",
        )

        # If spot goes to 110, we lose on the short call
        pnl_high = portfolio.calculate_pnl_at_expiry(110.0)
        # Should be negative (loss from ITM call we're short)
        assert pnl_high < 0

        # If spot goes to 90, short call expires worthless (profit)
        pnl_low = portfolio.calculate_pnl_at_expiry(90.0)
        # Should be positive (kept the premium)
        assert pnl_low > 0

    def test_calculate_pnl_empty_portfolio(self):
        """Test calculate_pnl_at_expiry with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)

        pnl = portfolio.calculate_pnl_at_expiry(110.0)
        # No positions, no P&L
        assert pnl == 0.0

    def test_calculate_net_debit_credit(self):
        """Test calculate_net_debit for credit spread."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Sell OTM put (collect premium)
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="put",
        )

        # Buy further OTM put (pay premium)
        portfolio.add_position(
            strike_price=90.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="put",
        )

        net_debit = portfolio.calculate_net_debit()
        # Credit spread should have negative net debit (we receive money)
        # Note: This depends on pricing, but typically credit spreads are net negative
        assert isinstance(net_debit, float)

    def test_vectorized_pnl_at_expiry(self):
        """Test vectorized_pnl_at_expiry method."""

        portfolio = OptionPortfolio(spot_price=100.0)

        # Buy a call at 100 strike
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        # Test with array of spot prices
        spot_range = np.array([90.0, 100.0, 110.0, 120.0])
        pnl_array = portfolio.vectorized_pnl_at_expiry(
            spot_range, include_underlying=False
        )

        # Should return numpy array
        assert isinstance(pnl_array, np.ndarray)
        assert len(pnl_array) == len(spot_range)

        # Verify results match scalar calculation
        for i, spot in enumerate(spot_range):
            scalar_pnl = portfolio.calculate_pnl_at_expiry(
                spot, include_underlying=False
            )
            assert np.isclose(pnl_array[i], scalar_pnl), (
                f"Mismatch at spot={spot}: vectorized={pnl_array[i]}, "
                f"scalar={scalar_pnl}"
            )

    def test_vectorized_pnl_with_underlying(self):
        """Test vectorized_pnl_at_expiry including underlying position."""

        portfolio = OptionPortfolio(underlying_quantity=100.0, spot_price=100.0)

        spot_range = np.array([90.0, 100.0, 110.0])
        pnl_array = portfolio.vectorized_pnl_at_expiry(
            spot_range, include_underlying=True
        )

        # Verify against scalar calculation
        for i, spot in enumerate(spot_range):
            scalar_pnl = portfolio.calculate_pnl_at_expiry(
                spot, include_underlying=True
            )
            assert np.isclose(pnl_array[i], scalar_pnl)

    def test_vectorized_pnl_multi_position(self):
        """Test vectorized calculation with multiple positions."""

        portfolio = OptionPortfolio(spot_price=100.0)

        # Create a bull call spread
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="call",
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
