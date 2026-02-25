"""Tests for BatchPricer class."""

from datetime import datetime, timedelta, timezone
import numpy as np

from deltadewa import OptionPortfolio, OptionValuation
from deltadewa.batch_pricer import BatchPricer
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import OptionType, ExerciseStyle, FDGridResolution
import deltadewa.valuation as _valuation_module


class TestBatchPricer:
    """Test cases for BatchPricer class."""

    def test_single_spot_matches_american_option(self):
        """Verify BatchPricer matches OptionValuation for a single spot."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            dividend_yield=0.02,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=2,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spot = 100.0
        valuation_date = datetime.now(tz=timezone.utc)
        spots = np.array([spot])

        # Get BatchPricer result
        batch_result = pricer.portfolio_values_at(spots, valuation_date)[0]

        # Calculate expected using OptionValuation directly
        opt = OptionValuation(
            spot_price=spot,
            strike_price=105.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            volatility=0.3,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            option_type=OptionType.CALL,
            valuation_date=valuation_date,
            exercise_style=ExerciseStyle.AMERICAN,
        )
        expected = opt.price() * 2 * 100 + 100.0 * spot

        assert np.isclose(batch_result, expected, rtol=1e-4)

    def test_multiple_spots_consistency(self):
        """Verify prices are consistent across spot sweep."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,  # No underlying for clearer test
            spot_price=100.0,
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spots = np.array([90.0, 100.0, 110.0])
        valuation_date = datetime.now(tz=timezone.utc)

        portfolio_values = pricer.portfolio_values_at(spots, valuation_date)

        # Verify results are monotonically increasing for call option
        assert portfolio_values[0] < portfolio_values[1] < portfolio_values[2]

        # Verify each matches individual OptionValuation calculation
        for i, spot in enumerate(spots):
            opt = OptionValuation(
                spot_price=spot,
                strike_price=100.0,
                maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
                volatility=0.25,
                risk_free_rate=0.05,
                dividend_yield=0.0,
                option_type=OptionType.CALL,
                valuation_date=valuation_date,
                exercise_style=ExerciseStyle.AMERICAN,
                grid_resolution=FDGridResolution.FAST,
            )
            expected = opt.price() * 100
            assert np.isclose(portfolio_values[i], expected, rtol=1e-4)

    def test_expired_positions_use_intrinsic(self):
        """Verify expired positions fall back to intrinsic value."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )

        # Add call option that will be treated as expired
        # Set maturity to 1 day from now, but value it at 2 days from now
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=1),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spots = np.array([90.0, 100.0, 110.0])
        # Value at a date after expiry
        future_date = datetime.now(tz=timezone.utc) + timedelta(days=2)
        portfolio_values = pricer.portfolio_values_at(spots, future_date)

        # Verify intrinsic values: max(0, spot - 95) * 100
        expected = np.array([0.0, 500.0, 1500.0])
        assert np.allclose(portfolio_values, expected, rtol=1e-10)

    def test_cache_reuses_option_for_same_date(self):
        """Verify QL environment is reused when date unchanged."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spots1 = np.array([95.0, 100.0, 105.0])
        valuation_date = datetime.now(tz=timezone.utc)

        # First call - should create and cache option
        values1 = pricer.portfolio_values_at(spots1, valuation_date)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 1

        # Second call with same date - should reuse cached option
        spots2 = np.array([98.0, 102.0])
        values2 = pricer.portfolio_values_at(spots2, valuation_date)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 1  # Still only 1 cached option

        # Values should be reasonable
        assert values1[1] > 0  # At-the-money call has value
        assert values2[0] > 0

    def test_cache_rebuilds_on_date_change(self):
        """Verify QL environment rebuilds when date changes."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spots = np.array([100.0])
        date1 = datetime.now(tz=timezone.utc)
        date2 = datetime.now(tz=timezone.utc) + timedelta(days=5)

        # First call
        values1 = pricer.portfolio_values_at(spots, date1)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 1

        # Second call with different date
        values2 = pricer.portfolio_values_at(spots, date2)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 2  # Now 2 cached options

        # Value should decrease as time passes (theta decay)
        assert values1[0] > values2[0]

    def test_matches_calculate_portfolio_value_at(self):
        """Verify BatchPricer matches _calculate_portfolio_value_at exactly."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            dividend_yield=0.02,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=2,
            option_type=OptionType.CALL,
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=45),
            quantity=-1,
            option_type=OptionType.PUT,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spots = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
        valuation_date = datetime.now(tz=timezone.utc)

        # Get BatchPricer results
        batch_values = pricer.portfolio_values_at(spots, valuation_date)

        # Get _calculate_portfolio_value_at results
        expected_values = np.array(
            [
                # pylint: disable=protected-access
                analyzer._calculate_portfolio_value_at(spot, valuation_date)
                for spot in spots
            ]
        )

        # Should match closely (within numerical precision)
        assert np.allclose(batch_values, expected_values, rtol=1e-4)

    def test_underlying_position_included(self):
        """Verify underlying shares are included in total."""
        portfolio = OptionPortfolio(
            underlying_quantity=1000.0,
            spot_price=100.0,
            volatility=0.25,
        )

        # No options, just underlying
        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spots = np.array([90.0, 100.0, 110.0])
        portfolio_values = pricer.portfolio_values_at(
            spots, datetime.now(tz=timezone.utc)
        )

        # Should be exactly underlying_quantity * spot
        expected = 1000.0 * spots
        assert np.allclose(portfolio_values, expected, rtol=1e-10)

    def test_mixed_expired_and_alive(self):
        """Verify correct handling when some positions expired, some alive."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )

        # Call that will be expired when valued
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=5),
            quantity=1,
            option_type=OptionType.CALL,
        )

        # Call that will still be alive when valued
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spot = 100.0
        spots = np.array([spot])
        # Value at a date where first option is expired but second is still alive
        valuation_date = datetime.now(tz=timezone.utc) + timedelta(days=10)

        portfolio_value = pricer.portfolio_values_at(spots, valuation_date)[0]

        # Expired call: intrinsic = max(0, 100 - 95) * 100 = 500
        expired_value = 500.0

        # Live call: price it directly
        opt = OptionValuation(
            spot_price=spot,
            strike_price=105.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            volatility=0.25,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            option_type=OptionType.CALL,
            valuation_date=valuation_date,
            exercise_style=ExerciseStyle.AMERICAN,
        )
        live_value = opt.price() * 100

        expected = expired_value + live_value
        assert np.isclose(portfolio_value, expected, rtol=1e-4)

    def test_clear_cache(self):
        """Verify cache clearing works."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        # Build cache
        spots = np.array([100.0])
        pricer.portfolio_values_at(spots, datetime.now(tz=timezone.utc))
        # pylint: disable=protected-access
        assert len(pricer._cache) == 1

        # Clear cache
        pricer.clear_cache()
        # pylint: disable=protected-access
        assert len(pricer._cache) == 0

    def test_multiple_positions_cache(self):
        """Verify cache handles multiple positions correctly."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )

        # Add 3 positions
        for strike in [95.0, 100.0, 105.0]:
            portfolio.add_position(
                strike_price=strike,
                maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
                quantity=1,
                option_type=OptionType.CALL,
            )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spots = np.array([100.0])
        valuation_date = datetime.now(tz=timezone.utc)

        # First call should cache 3 options (one per position)
        pricer.portfolio_values_at(spots, valuation_date)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 3

        # Second call with same date should reuse all 3
        pricer.portfolio_values_at(spots, valuation_date)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 3

        # Call with different date should create 3 more
        new_date = datetime.now(tz=timezone.utc) + timedelta(days=5)
        pricer.portfolio_values_at(spots, new_date)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 6  # 3 positions x 2 dates

    def test_put_option_pricing(self):
        """Test BatchPricer works correctly for put options."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spots = np.array([90.0, 100.0, 110.0])
        valuation_date = datetime.now(tz=timezone.utc)

        portfolio_values = pricer.portfolio_values_at(spots, valuation_date)

        # Put should be worth more at lower spots
        assert portfolio_values[0] > portfolio_values[1] > portfolio_values[2]

        # Verify against OptionValuation
        for i, spot in enumerate(spots):
            opt = OptionValuation(
                spot_price=spot,
                strike_price=100.0,
                maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
                volatility=0.25,
                risk_free_rate=portfolio.risk_free_rate,
                dividend_yield=portfolio.dividend_yield,
                option_type=OptionType.PUT,
                valuation_date=valuation_date,
                exercise_style=ExerciseStyle.AMERICAN,
                grid_resolution=FDGridResolution.FAST,
            )
            expected = opt.price() * 100
            assert np.isclose(portfolio_values[i], expected, rtol=1e-4)

    def test_expired_put_intrinsic(self):
        """Test expired put uses correct intrinsic value."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )

        # Add put option that will be treated as expired
        # Set maturity to 1 day from now, but value it at 2 days from now
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=1),
            quantity=1,
            option_type=OptionType.PUT,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
            grid_resolution=FDGridResolution.FAST,
        )

        spots = np.array([90.0, 100.0, 110.0])
        # Value at a date after expiry
        future_date = datetime.now(tz=timezone.utc) + timedelta(days=2)
        portfolio_values = pricer.portfolio_values_at(spots, future_date)

        # Verify intrinsic values: max(0, 105 - spot) * 100
        expected = np.array([1500.0, 500.0, 0.0])
        assert np.allclose(portfolio_values, expected, rtol=1e-10)


"""Tests for BatchPricer class."""

# --------------------------------------------------------------------------
# (existing imports and TestBatchPricer class unchanged above this point)
# --------------------------------------------------------------------------

import threading
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from deltadewa import OptionPortfolio, OptionValuation
from deltadewa.batch_pricer import BatchPricer
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import ExerciseStyle, FDGridResolution, OptionType
from deltadewa.warnings import ClosedFormAccuracyWarning


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_atm_call_portfolio(
    spot: float = 100.0,
    days: int = 30,
    vol: float = 0.25,
    underlying_qty: float = 0.0,
) -> OptionPortfolio:
    """Return a portfolio with a single ATM call."""
    portfolio = OptionPortfolio(
        underlying_quantity=underlying_qty,
        spot_price=spot,
        volatility=vol,
        risk_free_rate=0.05,
        dividend_yield=0.0,
    )
    portfolio.add_position(
        strike_price=spot,
        maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=days),
        quantity=1,
        option_type=OptionType.CALL,
    )
    return portfolio


def _make_multi_position_portfolio(n: int = 4) -> OptionPortfolio:
    """Return a portfolio with n ATM calls at staggered maturities."""
    portfolio = OptionPortfolio(
        underlying_quantity=0.0,
        spot_price=100.0,
        volatility=0.25,
        risk_free_rate=0.05,
        dividend_yield=0.0,
    )
    for i in range(n):
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30 + i * 10),
            quantity=1,
            option_type=OptionType.CALL,
        )
    return portfolio


def _pricer(
    portfolio: OptionPortfolio,
    use_closed_form: bool = False,
    max_workers: int = 1,
) -> BatchPricer:
    return BatchPricer(
        positions=portfolio.positions,
        risk_free_rate=portfolio.risk_free_rate,
        dividend_yield=portfolio.dividend_yield,
        underlying_quantity=portfolio.underlying_quantity,
        grid_resolution=FDGridResolution.FAST,
        use_closed_form=use_closed_form,
        max_workers=max_workers,
    )


# ---------------------------------------------------------------------------
# Closed-form engine tests
# ---------------------------------------------------------------------------


class TestBatchPricerClosedForm:
    """Tests for use_closed_form=True engine in BatchPricer."""

    def test_closed_form_atm_call_close_to_fd(self):
        """BS2002 price for ATM call should be within 2% of FD price."""
        portfolio = _make_atm_call_portfolio(days=30)
        spots = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
        valuation_date = datetime.now(tz=timezone.utc)

        fd_values = _pricer(portfolio, use_closed_form=False).portfolio_values_at(
            spots, valuation_date
        )
        cf_values = _pricer(portfolio, use_closed_form=True).portfolio_values_at(
            spots, valuation_date
        )

        # Near-ATM options should agree within 2%
        assert np.allclose(fd_values, cf_values, rtol=0.02)

    def test_closed_form_preserves_call_monotonicity(self):
        """Closed-form call prices must increase with spot."""
        portfolio = _make_atm_call_portfolio(days=30)
        spots = np.linspace(80.0, 120.0, 10)
        valuation_date = datetime.now(tz=timezone.utc)

        cf_values = _pricer(portfolio, use_closed_form=True).portfolio_values_at(
            spots, valuation_date
        )
        assert np.all(np.diff(cf_values) > 0)

    def test_closed_form_put_close_to_fd(self):
        """BS2002 price for ATM put should be within 2% of FD price."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )

        spots = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
        valuation_date = datetime.now(tz=timezone.utc)

        fd_values = _pricer(portfolio, use_closed_form=False).portfolio_values_at(
            spots, valuation_date
        )
        cf_values = _pricer(portfolio, use_closed_form=True).portfolio_values_at(
            spots, valuation_date
        )

        assert np.allclose(fd_values, cf_values, rtol=0.02)

    def test_closed_form_european_uses_analytic_engine(self):
        """European options use analytic BS regardless of use_closed_form."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.EUROPEAN,
        )

        spots = np.array([95.0, 100.0, 105.0])
        valuation_date = datetime.now(tz=timezone.utc)

        # Both should produce identical results for European options
        fd_values = _pricer(portfolio, use_closed_form=False).portfolio_values_at(
            spots, valuation_date
        )
        cf_values = _pricer(portfolio, use_closed_form=True).portfolio_values_at(
            spots, valuation_date
        )

        assert np.allclose(fd_values, cf_values, rtol=1e-6)

    def test_closed_form_stores_flag_on_instance(self):
        """use_closed_form is stored as an instance attribute."""
        portfolio = _make_atm_call_portfolio()
        pricer_fd = _pricer(portfolio, use_closed_form=False)
        pricer_cf = _pricer(portfolio, use_closed_form=True)

        assert pricer_fd.use_closed_form is False
        assert pricer_cf.use_closed_form is True

    def test_closed_form_expired_positions_still_use_intrinsic(self):
        """Expired positions must use intrinsic value even with closed_form=True."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=1),
            quantity=1,
            option_type=OptionType.CALL,
        )

        spots = np.array([90.0, 100.0, 110.0])
        future_date = datetime.now(tz=timezone.utc) + timedelta(days=2)

        cf_values = _pricer(portfolio, use_closed_form=True).portfolio_values_at(
            spots, future_date
        )

        expected = np.array([0.0, 500.0, 1500.0])
        assert np.allclose(cf_values, expected, rtol=1e-10)

    def test_closed_form_and_fd_cache_independently(self):
        """Two pricers with different engine flags maintain separate caches."""
        portfolio = _make_atm_call_portfolio()
        spots = np.array([100.0])
        valuation_date = datetime.now(tz=timezone.utc)

        pricer_fd = _pricer(portfolio, use_closed_form=False)
        pricer_cf = _pricer(portfolio, use_closed_form=True)

        pricer_fd.portfolio_values_at(spots, valuation_date)
        pricer_cf.portfolio_values_at(spots, valuation_date)

        # pylint: disable=protected-access
        assert len(pricer_fd._cache) == 1
        assert len(pricer_cf._cache) == 1
        # The cached OptionValuation objects are distinct instances
        fd_opt = list(pricer_fd._cache.values())[0]
        cf_opt = list(pricer_cf._cache.values())[0]
        assert fd_opt is not cf_opt
        assert fd_opt.use_closed_form is False
        assert cf_opt.use_closed_form is True


# ---------------------------------------------------------------------------
# ClosedFormAccuracyWarning tests
# ---------------------------------------------------------------------------


class TestClosedFormAccuracyWarning:
    """Tests for ClosedFormAccuracyWarning emitted by BatchPricer."""

    @pytest.fixture(autouse=True)
    def _reset_warning_registry(self):
        """Clear the valuation module's __warningregistry__ before each test.

        Python's warning system stores 'already seen' entries in a per-module
        registry dict, checked before the filter stack. Clearing it ensures
        each test starts fresh and simplefilter("always") actually works.
        """
        if hasattr(_valuation_module, "__warningregistry__"):
            _valuation_module.__warningregistry__.clear()
        yield
        # Optionally clear again on teardown so we don't pollute later tests
        if hasattr(_valuation_module, "__warningregistry__"):
            _valuation_module.__warningregistry__.clear()

    def _deep_itm_call_portfolio(self) -> OptionPortfolio:
        """Portfolio with a deep ITM call.

        ITM call: spot well ABOVE strike.
        spot=125, strike=100 → S/K = 1.25, which is 25% ITM.
        deep_itm_ratio = 1/0.85 ≈ 1.176, so 1.25 > 1.176 → warning fires.
        """
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=125.0,  # spot ABOVE strike → call is ITM
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )
        return portfolio

    def _deep_itm_put_portfolio(self) -> OptionPortfolio:
        """Portfolio with a deep ITM put.

        ITM put: spot well BELOW strike.
        spot=75, strike=100 → K/S ≈ 1.333, which is 33% ITM.
        deep_itm_ratio = 1/0.85 ≈ 1.176, so 1.333 > 1.176 → warning fires.
        """
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=75.0,  # spot BELOW strike → put is ITM
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )
        return portfolio

    def _short_dated_put_portfolio(self, days: int = 3) -> OptionPortfolio:
        """Portfolio with a short-dated ATM put."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=days),
            quantity=1,
            option_type=OptionType.PUT,
        )
        return portfolio

    def _high_vol_portfolio(self, vol: float = 0.90) -> OptionPortfolio:
        """Portfolio with very high implied volatility."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=vol,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )
        return portfolio

    def test_no_warning_for_fd_engine(self):
        """No ClosedFormAccuracyWarning when use_closed_form=False."""
        portfolio = self._deep_itm_call_portfolio()
        pricer = _pricer(portfolio, use_closed_form=False)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(np.array([125.0]), datetime.now(tz=timezone.utc))

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        assert len(cf_warnings) == 0

    def test_no_warning_for_near_atm_normal_vol(self):
        """No warning for a near-ATM call with normal vol using closed form."""
        portfolio = _make_atm_call_portfolio(days=30, vol=0.25)
        pricer = _pricer(portfolio, use_closed_form=True)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(np.array([100.0]), datetime.now(tz=timezone.utc))

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        assert len(cf_warnings) == 0

    def test_warning_for_deep_itm_call(self):
        """ClosedFormAccuracyWarning emitted for deep ITM call."""
        portfolio = self._deep_itm_call_portfolio()
        pricer = _pricer(portfolio, use_closed_form=True)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(np.array([125.0]), datetime.now(tz=timezone.utc))

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        assert len(cf_warnings) >= 1
        assert "deep itm call" in str(cf_warnings[0].message).lower()

    def test_warning_for_deep_itm_put(self):
        """ClosedFormAccuracyWarning emitted for deep ITM put."""
        portfolio = self._deep_itm_put_portfolio()
        pricer = _pricer(portfolio, use_closed_form=True)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(np.array([75.0]), datetime.now(tz=timezone.utc))

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        assert len(cf_warnings) >= 1
        assert "deep itm put" in str(cf_warnings[0].message).lower()

    def test_warning_for_short_dated_put(self):
        """ClosedFormAccuracyWarning emitted for short-dated put."""
        portfolio = self._short_dated_put_portfolio(days=3)
        pricer = _pricer(portfolio, use_closed_form=True)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(np.array([100.0]), datetime.now(tz=timezone.utc))

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        assert len(cf_warnings) >= 1
        assert "short-dated put" in str(cf_warnings[0].message).lower()

    def test_no_warning_for_short_dated_call(self):
        """Short-dated calls do not trigger the short-dated-put warning."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=3),
            quantity=1,
            option_type=OptionType.CALL,
        )
        pricer = _pricer(portfolio, use_closed_form=True)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(np.array([100.0]), datetime.now(tz=timezone.utc))

        short_dated_warnings = [
            w
            for w in caught
            if issubclass(w.category, ClosedFormAccuracyWarning)
            and "short-dated" in str(w.message).lower()
        ]
        assert len(short_dated_warnings) == 0

    def test_warning_for_high_vol(self):
        """ClosedFormAccuracyWarning emitted for very high implied volatility."""
        portfolio = self._high_vol_portfolio(vol=0.90)
        pricer = _pricer(portfolio, use_closed_form=True)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(np.array([100.0]), datetime.now(tz=timezone.utc))

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        assert len(cf_warnings) >= 1
        assert "volatility" in str(cf_warnings[0].message).lower()

    def test_warning_emitted_once_per_position_not_per_spot(self):
        """Warning fires exactly once per position across a multi-spot sweep."""
        portfolio = self._deep_itm_call_portfolio()
        pricer = _pricer(portfolio, use_closed_form=True)
        spots = np.linspace(110.0, 130.0, 20)  # 20 spots, all deep ITM

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(spots, datetime.now(tz=timezone.utc))

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        # Must be exactly 1, not 20
        assert len(cf_warnings) == 1

    def test_warning_not_re_emitted_from_cache_hit(self):
        """Second call with same date uses cache — no duplicate warning."""
        portfolio = self._deep_itm_call_portfolio()
        pricer = _pricer(portfolio, use_closed_form=True)
        spots = np.array([125.0])
        valuation_date = datetime.now(tz=timezone.utc)

        # Both calls share the same catch_warnings context.
        # The warning fires on the first call (cache miss → construction).
        # The second call is a cache hit → no construction → no warning.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)

            pricer.portfolio_values_at(spots, valuation_date)  # cache miss
            pricer.portfolio_values_at(spots, valuation_date)  # cache hit

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        # Exactly 1: fired on construction (first call), not on cache hit (second call)
        assert len(cf_warnings) == 1

    def test_warning_can_be_suppressed(self):
        """ClosedFormAccuracyWarning can be silenced with filterwarnings."""
        portfolio = self._deep_itm_call_portfolio()
        pricer = _pricer(portfolio, use_closed_form=True)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("ignore", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(np.array([125.0]), datetime.now(tz=timezone.utc))

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        assert len(cf_warnings) == 0

    def test_warning_can_be_turned_into_error(self):
        """ClosedFormAccuracyWarning can be promoted to an error."""
        portfolio = self._deep_itm_call_portfolio()
        pricer = _pricer(portfolio, use_closed_form=True)

        # First verify the warning is actually emitted
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(np.array([125.0]), datetime.now(tz=timezone.utc))

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        assert len(cf_warnings) >= 1, "Warning should be emitted for deep ITM call"

        # Now test that it can be converted to error
        pricer2 = _pricer(portfolio, use_closed_form=True)
        with warnings.catch_warnings():
            warnings.simplefilter("error", ClosedFormAccuracyWarning)
            with pytest.raises(ClosedFormAccuracyWarning):
                pricer2.portfolio_values_at(
                    np.array([125.0]), datetime.now(tz=timezone.utc)
                )

    def test_warning_message_contains_suppress_hint(self):
        """Warning message includes the filterwarnings suppression hint."""
        portfolio = self._deep_itm_call_portfolio()
        pricer = _pricer(portfolio, use_closed_form=True)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(np.array([125.0]), datetime.now(tz=timezone.utc))

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        assert "filterwarnings" in str(cf_warnings[0].message).lower()


# ---------------------------------------------------------------------------
# Threading tests
# ---------------------------------------------------------------------------


class TestBatchPricerThreading:
    """Tests for max_workers > 1 parallel pricing in BatchPricer."""

    def test_parallel_matches_sequential_single_position(self):
        """Parallel result matches sequential for a single position."""
        portfolio = _make_atm_call_portfolio()
        spots = np.linspace(80.0, 120.0, 15)
        valuation_date = datetime.now(tz=timezone.utc)

        seq_values = _pricer(portfolio, max_workers=1).portfolio_values_at(
            spots, valuation_date
        )
        par_values = _pricer(portfolio, max_workers=4).portfolio_values_at(
            spots, valuation_date
        )

        assert np.allclose(seq_values, par_values, rtol=1e-6)

    def test_parallel_matches_sequential_multi_position(self):
        """Parallel result matches sequential for multiple positions."""
        portfolio = _make_multi_position_portfolio(n=4)
        spots = np.linspace(80.0, 120.0, 20)
        valuation_date = datetime.now(tz=timezone.utc)

        seq_values = _pricer(portfolio, max_workers=1).portfolio_values_at(
            spots, valuation_date
        )
        par_values = _pricer(portfolio, max_workers=4).portfolio_values_at(
            spots, valuation_date
        )

        assert np.allclose(seq_values, par_values, rtol=1e-6)

    def test_parallel_closed_form_matches_sequential_closed_form(self):
        """Parallel + closed-form matches sequential + closed-form."""
        portfolio = _make_multi_position_portfolio(n=4)
        spots = np.linspace(80.0, 120.0, 20)
        valuation_date = datetime.now(tz=timezone.utc)

        seq_values = _pricer(
            portfolio, use_closed_form=True, max_workers=1
        ).portfolio_values_at(spots, valuation_date)
        par_values = _pricer(
            portfolio, use_closed_form=True, max_workers=4
        ).portfolio_values_at(spots, valuation_date)

        assert np.allclose(seq_values, par_values, rtol=1e-6)

    def test_max_workers_one_disables_threading(self):
        """max_workers=1 should not spawn any extra threads."""
        portfolio = _make_atm_call_portfolio()
        pricer = _pricer(portfolio, max_workers=1)

        threads_before = threading.active_count()
        pricer.portfolio_values_at(np.array([100.0]), datetime.now(tz=timezone.utc))
        threads_after = threading.active_count()

        # No new persistent threads should remain after the call
        assert threads_after <= threads_before

    def test_parallel_cache_populated_correctly(self):
        """Cache entries are created exactly once per (position, date) in parallel."""
        portfolio = _make_multi_position_portfolio(n=4)
        pricer = _pricer(portfolio, max_workers=4)
        valuation_date = datetime.now(tz=timezone.utc)

        pricer.portfolio_values_at(np.array([100.0]), valuation_date)

        # pylint: disable=protected-access
        assert len(pricer._cache) == 4

        # Second call with the same date must not grow the cache
        pricer.portfolio_values_at(np.array([95.0, 105.0]), valuation_date)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 4

    def test_parallel_underlying_only_no_options(self):
        """Parallel pricer handles an underlying-only portfolio without errors."""
        portfolio = OptionPortfolio(
            underlying_quantity=1000.0,
            spot_price=100.0,
            volatility=0.25,
        )
        spots = np.array([90.0, 100.0, 110.0])
        par_values = _pricer(portfolio, max_workers=4).portfolio_values_at(
            spots, datetime.now(tz=timezone.utc)
        )

        assert np.allclose(par_values, 1000.0 * spots, rtol=1e-10)

    def test_parallel_expired_positions_handled(self):
        """Parallel pricer handles expired positions correctly."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=1),
            quantity=1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        spots = np.array([90.0, 100.0, 110.0])
        future_date = datetime.now(tz=timezone.utc) + timedelta(days=2)

        seq_values = _pricer(portfolio, max_workers=1).portfolio_values_at(
            spots, future_date
        )
        par_values = _pricer(portfolio, max_workers=4).portfolio_values_at(
            spots, future_date
        )

        assert np.allclose(seq_values, par_values, rtol=1e-6)

    def test_parallel_warning_emitted_once_per_position(self):
        """Accuracy warning fires once per position in parallel mode."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=125.0,
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )
        # Two deep-ITM calls
        for strike in [90.0, 95.0]:
            portfolio.add_position(
                strike_price=strike,
                maturity_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
                quantity=1,
                option_type=OptionType.CALL,
            )

        pricer = _pricer(portfolio, use_closed_form=True, max_workers=2)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ClosedFormAccuracyWarning)
            pricer.portfolio_values_at(
                np.linspace(110.0, 130.0, 10), datetime.now(tz=timezone.utc)
            )

        cf_warnings = [
            w for w in caught if issubclass(w.category, ClosedFormAccuracyWarning)
        ]
        # One warning per position (2 positions), not one per spot (10 spots)
        assert len(cf_warnings) == 2

    def test_negative_max_workers_clamped_to_one(self):
        """max_workers <= 0 is silently clamped to 1."""
        portfolio = _make_atm_call_portfolio()
        pricer = _pricer(portfolio, max_workers=0)
        assert pricer.max_workers == 1

        pricer_neg = _pricer(portfolio, max_workers=-5)
        assert pricer_neg.max_workers == 1
