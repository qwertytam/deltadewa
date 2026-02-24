"""Tests for BatchPricer class."""

from datetime import datetime, timedelta
import numpy as np

from deltadewa import OptionPortfolio, OptionValuation
from deltadewa.batch_pricer import BatchPricer
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import OptionType, ExerciseStyle


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
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=2,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        spot = 100.0
        valuation_date = datetime.now()
        spots = np.array([spot])

        # Get BatchPricer result
        batch_result = pricer.portfolio_values_at(spots, valuation_date)[0]

        # Calculate expected using OptionValuation directly
        opt = OptionValuation(
            spot_price=spot,
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
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
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        spots = np.array([90.0, 100.0, 110.0])
        valuation_date = datetime.now()

        portfolio_values = pricer.portfolio_values_at(spots, valuation_date)

        # Verify results are monotonically increasing for call option
        assert portfolio_values[0] < portfolio_values[1] < portfolio_values[2]

        # Verify each matches individual OptionValuation calculation
        for i, spot in enumerate(spots):
            opt = OptionValuation(
                spot_price=spot,
                strike_price=100.0,
                maturity_date=datetime.now() + timedelta(days=30),
                volatility=0.25,
                risk_free_rate=0.05,
                dividend_yield=0.0,
                option_type=OptionType.CALL,
                valuation_date=valuation_date,
                exercise_style=ExerciseStyle.AMERICAN,
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
            maturity_date=datetime.now() + timedelta(days=1),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        spots = np.array([90.0, 100.0, 110.0])
        # Value at a date after expiry
        future_date = datetime.now() + timedelta(days=2)
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
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        spots1 = np.array([95.0, 100.0, 105.0])
        valuation_date = datetime.now()

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
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        spots = np.array([100.0])
        date1 = datetime.now()
        date2 = datetime.now() + timedelta(days=5)

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
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=2,
            option_type=OptionType.CALL,
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now() + timedelta(days=45),
            quantity=-1,
            option_type=OptionType.PUT,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        spots = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
        valuation_date = datetime.now()

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
        )

        spots = np.array([90.0, 100.0, 110.0])
        portfolio_values = pricer.portfolio_values_at(spots, datetime.now())

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
            maturity_date=datetime.now() + timedelta(days=5),
            quantity=1,
            option_type=OptionType.CALL,
        )

        # Call that will still be alive when valued
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        spot = 100.0
        spots = np.array([spot])
        # Value at a date where first option is expired but second is still alive
        valuation_date = datetime.now() + timedelta(days=10)

        portfolio_value = pricer.portfolio_values_at(spots, valuation_date)[0]

        # Expired call: intrinsic = max(0, 100 - 95) * 100 = 500
        expired_value = 500.0

        # Live call: price it directly
        opt = OptionValuation(
            spot_price=spot,
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
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
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        # Build cache
        spots = np.array([100.0])
        pricer.portfolio_values_at(spots, datetime.now())
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
                maturity_date=datetime.now() + timedelta(days=30),
                quantity=1,
                option_type=OptionType.CALL,
            )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        spots = np.array([100.0])
        valuation_date = datetime.now()

        # First call should cache 3 options (one per position)
        pricer.portfolio_values_at(spots, valuation_date)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 3

        # Second call with same date should reuse all 3
        pricer.portfolio_values_at(spots, valuation_date)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 3

        # Call with different date should create 3 more
        new_date = datetime.now() + timedelta(days=5)
        pricer.portfolio_values_at(spots, new_date)
        # pylint: disable=protected-access
        assert len(pricer._cache) == 6  # 3 positions × 2 dates

    def test_put_option_pricing(self):
        """Test BatchPricer works correctly for put options."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        spots = np.array([90.0, 100.0, 110.0])
        valuation_date = datetime.now()

        portfolio_values = pricer.portfolio_values_at(spots, valuation_date)

        # Put should be worth more at lower spots
        assert portfolio_values[0] > portfolio_values[1] > portfolio_values[2]

        # Verify against OptionValuation
        for i, spot in enumerate(spots):
            opt = OptionValuation(
                spot_price=spot,
                strike_price=100.0,
                maturity_date=datetime.now() + timedelta(days=30),
                volatility=0.25,
                risk_free_rate=portfolio.risk_free_rate,
                dividend_yield=portfolio.dividend_yield,
                option_type=OptionType.PUT,
                valuation_date=valuation_date,
                exercise_style=ExerciseStyle.AMERICAN,
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
            maturity_date=datetime.now() + timedelta(days=1),
            quantity=1,
            option_type=OptionType.PUT,
        )

        pricer = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=portfolio.underlying_quantity,
        )

        spots = np.array([90.0, 100.0, 110.0])
        # Value at a date after expiry
        future_date = datetime.now() + timedelta(days=2)
        portfolio_values = pricer.portfolio_values_at(spots, future_date)

        # Verify intrinsic values: max(0, 105 - spot) * 100
        expected = np.array([1500.0, 500.0, 0.0])
        assert np.allclose(portfolio_values, expected, rtol=1e-10)
