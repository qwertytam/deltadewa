"""Tests for BatchPricer.portfolio_greeks_at() method."""

import datetime
from datetime import datetime as dt
from datetime import timedelta

import numpy as np
import pytest

from deltadewa import OptionPortfolio, OptionValuation
from deltadewa.batch_pricer import BatchPricer
from deltadewa.constants import ExerciseStyle, FDGridResolution, OptionType


def _make_pricer(portfolio, **kwargs) -> BatchPricer:
    return BatchPricer(
        positions=portfolio.positions,
        risk_free_rate=portfolio.risk_free_rate,
        dividend_yield=portfolio.dividend_yield,
        underlying_quantity=portfolio.underlying_quantity,
        grid_resolution=FDGridResolution.FAST,
        **kwargs,
    )


class TestBatchPricerGreeks:
    """Test cases for BatchPricer.portfolio_greeks_at()."""

    def test_portfolio_greeks_at_matches_direct_valuation(self):
        """Greeks arrays must match direct OptionValuation at each spot."""
        valuation_date = dt.now(tz=datetime.UTC)
        maturity = valuation_date + timedelta(days=45)

        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.25,
            risk_free_rate=0.05,
            dividend_yield=0.01,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = _make_pricer(portfolio)
        spots = np.array([90.0, 100.0, 110.0])
        result = pricer.portfolio_greeks_at(
            spots, valuation_date, greeks=("delta", "gamma", "vega", "theta"),
        )

        for i, spot in enumerate(spots):
            opt = OptionValuation(
                spot_price=spot,
                strike_price=100.0,
                maturity_date=maturity,
                volatility=0.25,
                risk_free_rate=0.05,
                dividend_yield=0.01,
                option_type=OptionType.CALL,
                valuation_date=valuation_date,
                exercise_style=ExerciseStyle.AMERICAN,
                grid_resolution=FDGridResolution.FAST,
            )
            mult = 1 * 100  # quantity=1, contract_size=100
            assert np.isclose(result["delta"][i], opt.delta() * mult, atol=1e-6)
            assert np.isclose(result["gamma"][i], opt.gamma() * mult, atol=1e-6)
            assert np.isclose(result["vega"][i], opt.vega() * mult, atol=1e-6)
            assert np.isclose(result["theta"][i], opt.theta() * mult, atol=1e-6)

    def test_net_delta_includes_underlying(self):
        """Delta array must include underlying_quantity offset at every spot."""
        valuation_date = dt.now(tz=datetime.UTC)
        maturity = valuation_date + timedelta(days=30)

        portfolio = OptionPortfolio(
            underlying_quantity=50.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = _make_pricer(portfolio)
        spots = np.array([90.0, 100.0, 110.0])
        result = pricer.portfolio_greeks_at(spots, valuation_date, greeks=("delta",))

        # Build option-only delta by creating a pricer with underlying_quantity=0
        pricer_no_underlying = BatchPricer(
            positions=portfolio.positions,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            underlying_quantity=0.0,
            grid_resolution=FDGridResolution.FAST,
        )
        result_no_underlying = pricer_no_underlying.portfolio_greeks_at(
            spots, valuation_date, greeks=("delta",),
        )

        expected_delta = result_no_underlying["delta"] + 50.0
        np.testing.assert_allclose(result["delta"], expected_delta, atol=1e-6)

    def test_greeks_and_values_share_cache(self):
        """After both calls, cache has exactly P entries (no duplicate constructions)."""
        valuation_date = dt.now(tz=datetime.UTC)
        maturity = valuation_date + timedelta(days=30)

        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.PUT,
        )

        pricer = _make_pricer(portfolio)
        spots = np.array([95.0, 100.0, 105.0])

        pricer.portfolio_values_at(spots, valuation_date)
        pricer.portfolio_greeks_at(spots, valuation_date, greeks=("delta",))

        # pylint: disable=protected-access
        assert len(pricer._cache) == len(portfolio.positions)

    def test_invalid_greek_raises_value_error(self):
        """Requesting an unknown greek name must raise ValueError."""
        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=dt.now(tz=datetime.UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = _make_pricer(portfolio)
        spots = np.array([100.0])
        with pytest.raises(ValueError):
            pricer.portfolio_greeks_at(
                spots,
                dt.now(tz=datetime.UTC),
                greeks=("zomega",),
            )

    def test_expired_positions_delta(self):
        """Expired positions: delta is +mult ITM call, -mult ITM put, 0 otherwise."""
        now = dt.now(tz=datetime.UTC)
        # Maturity 1 day from now; value at 2 days from now => positions are expired
        maturity = now + timedelta(days=1)
        valuation_date = now + timedelta(days=2)

        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=2,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=3,
            option_type=OptionType.PUT,
        )

        pricer = _make_pricer(portfolio)
        spots = np.array([90.0, 100.0, 110.0])
        result = pricer.portfolio_greeks_at(spots, valuation_date, greeks=("delta",))

        call_mult = 2 * 100
        put_mult = 3 * 100

        # spot=90: call OTM (0), put ITM (-put_mult)
        assert np.isclose(result["delta"][0], 0.0 - put_mult, atol=1e-10)
        # spot=100: call at strike (0), put at strike (0)
        assert np.isclose(result["delta"][1], 0.0, atol=1e-10)
        # spot=110: call ITM (+call_mult), put OTM (0)
        assert np.isclose(result["delta"][2], call_mult, atol=1e-10)

    def test_greeks_at_price_matches_portfolio_values_at(self):
        """portfolio_greeks_at price array must match portfolio_values_at."""
        valuation_date = dt.now(tz=datetime.UTC)
        maturity = valuation_date + timedelta(days=30)

        portfolio = OptionPortfolio(
            underlying_quantity=10.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = _make_pricer(portfolio)
        spots = np.array([90.0, 100.0, 110.0])

        values = pricer.portfolio_values_at(spots, valuation_date)
        greeks_result = pricer.portfolio_greeks_at(spots, valuation_date, greeks=())

        np.testing.assert_allclose(greeks_result["price"], values, atol=1e-6)

    def test_single_spot_greeks(self):
        """Sanity check with a 1-element spots array."""
        valuation_date = dt.now(tz=datetime.UTC)
        maturity = valuation_date + timedelta(days=30)

        portfolio = OptionPortfolio(
            underlying_quantity=0.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        pricer = _make_pricer(portfolio)
        spots = np.array([100.0])
        result = pricer.portfolio_greeks_at(
            spots, valuation_date, greeks=("delta", "gamma"),
        )

        assert "delta" in result
        assert "gamma" in result
        assert "price" in result
        assert result["delta"].shape == (1,)
        assert result["gamma"].shape == (1,)
        assert result["price"].shape == (1,)
        assert result["delta"][0] > 0  # ATM call delta > 0
        assert result["gamma"][0] > 0  # ATM call gamma > 0
        assert result["price"][0] > 0  # ATM call price > 0
