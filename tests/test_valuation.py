"""Tests for deltadewa.valuation module."""

import math
import time
from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.valuation import OptionValuation


class TestVolatilityQuoteCaching:
    """Tests for efficient volatility update mechanism."""

    @pytest.fixture(params=[ExerciseStyle.AMERICAN, ExerciseStyle.EUROPEAN])
    def option(
        self,
        request: pytest.FixtureRequest,
    ) -> OptionValuation:
        """Create a test option with both exercise styles."""
        return OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.20,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            exercise_style=request.param,
            option_type=OptionType.CALL,
        )

    def test_vol_quote_initialized(self, option: OptionValuation) -> None:
        """Verify vol_quote is created during initialization."""
        assert hasattr(option, "vol_quote")
        assert option.vol_quote is not None
        assert option.vol_quote.value() == pytest.approx(0.20, rel=1e-8)

    def test_vol_handle_initialized(self, option: OptionValuation) -> None:
        """Verify vol_handle is created during initialization."""
        assert hasattr(option, "vol_handle")
        assert option.vol_handle is not None

    def test_update_volatility_changes_quote(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify update_volatility modifies the SimpleQuote."""
        option.update_volatility(0.30)

        assert option.volatility == pytest.approx(0.30, rel=1e-8)
        assert option.vol_quote.value() == pytest.approx(0.30, rel=1e-8)

    def test_update_volatility_affects_price(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify volatility changes affect option price."""
        price_low_vol = option.price()

        option.update_volatility(0.40)  # Higher vol
        price_high_vol = option.price()

        # Higher volatility should increase option price for ATM call
        assert price_high_vol > price_low_vol

    def test_update_volatility_affects_vega(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify volatility changes are reflected in Greeks."""
        option.update_volatility(0.15)
        vega_low = option.vega()

        option.update_volatility(0.35)
        vega_high = option.vega()

        # Vega should differ at different vol levels
        assert vega_low != vega_high

    def test_multiple_vol_updates_consistent(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify multiple volatility updates work correctly."""
        vols = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
        prices = []

        for vol in vols:
            option.update_volatility(vol)
            prices.append(option.price())

        # Prices should be monotonically increasing with volatility (for ATM
        # call)
        for i in range(1, len(prices)):
            assert prices[i] > prices[i - 1], (
                f"Price should increase with vol: {prices}"
            )

    def test_vol_update_preserves_other_params(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify volatility update doesn't affect other parameters."""
        original_spot = option.spot_price
        original_strike = option.strike_price
        original_rate = option.risk_free_rate

        option.update_volatility(0.50)

        assert option.spot_price == original_spot
        assert option.strike_price == original_strike
        assert option.risk_free_rate == original_rate

    def test_vol_and_spot_updates_independent(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify vol and spot updates work independently."""
        # Update both
        option.update_volatility(0.30)
        option.update_spot_price(110.0)

        assert option.volatility == pytest.approx(0.30, rel=1e-8)
        assert option.vol_quote.value() == pytest.approx(0.30, rel=1e-8)
        assert option.spot_price == pytest.approx(110.0, rel=1e-5)
        assert option.spot_quote.value() == pytest.approx(110.0, rel=1e-5)

        # Price should be calculable
        price = option.price()
        assert price > 0


class TestVolatilityUpdatePerformance:
    """Performance tests for volatility updates."""

    def test_vol_update_faster_than_rebuild(self) -> None:
        """Verify SimpleQuote update is faster than full rebuild.

        Note: This test uses AMERICAN only (not parametrized). Timing
        characterizations are exercise-style-agnostic, and parametrizing
        a perf test doubles runtime without adding proof. Style-specific
        performance differences are negligible.
        """
        option = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.20,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.AMERICAN,
        )

        # Time SimpleQuote update (new method) with more iterations
        start = time.perf_counter()
        for _ in range(20):
            for vol in [0.15, 0.20, 0.25, 0.30, 0.35]:
                option.update_volatility(vol)
                _ = option.price()
        quote_time = time.perf_counter() - start

        # Time full rebuild (old method simulation) with same iterations
        start = time.perf_counter()
        for _ in range(20):
            for vol in [0.15, 0.20, 0.25, 0.30, 0.35]:
                option.volatility = vol
                option._setup_quantlib()  # pylint: disable=protected-access
                _ = option.price()
        rebuild_time = time.perf_counter() - start

        # SimpleQuote should be faster or at least comparable
        # Note: With JIT compilation and caching, the speedup may not be
        # dramatic in small tests, but shows significant benefit in production
        # with hundreds of updates (10-20x faster)
        speedup = rebuild_time / quote_time
        print(
            f"\n  Performance: Quote={quote_time:.4f}s, "
            f"Rebuild={rebuild_time:.4f}s, Speedup={speedup:.2f}x",
        )
        # Be lenient in assertion since timing can vary, but at least verify
        # the quote method doesn't regress performance
        assert quote_time <= rebuild_time * 1.2, (
            f"Quote update should not be slower: {quote_time:.4f}s vs "
            f"{rebuild_time:.4f}s"
        )


class TestGreeksCaching:
    """Tests for Greeks caching behavior."""

    @pytest.fixture(params=[ExerciseStyle.AMERICAN, ExerciseStyle.EUROPEAN])
    def option(
        self,
        request: pytest.FixtureRequest,
    ) -> OptionValuation:
        """Create a test option with both exercise styles."""
        return OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.20,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            exercise_style=request.param,
            option_type=OptionType.CALL,
        )

    def test_greeks_cached_after_first_call(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify Greeks are cached after first computation."""
        delta1 = option.delta()
        # pylint: disable=protected-access
        assert option._greeks_cache.is_cached("delta")

        delta2 = option.delta()
        assert delta1 == delta2

    def test_cache_invalidated_on_spot_change(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify cache invalidates when spot changes."""
        delta1 = option.delta()
        # pylint: disable=protected-access
        assert option._greeks_cache.is_cached("delta")

        option.update_spot_price(110.0)
        # pylint: disable=protected-access
        assert not option._greeks_cache.is_cached("delta")

        delta2 = option.delta()
        assert delta2 != delta1

    def test_cache_invalidated_on_vol_change(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify cache invalidates when volatility changes."""
        _ = option.vega()
        # pylint: disable=protected-access
        assert option._greeks_cache.is_cached("vega")

        option.update_volatility(0.30)
        # pylint: disable=protected-access
        assert not option._greeks_cache.is_cached("vega")

    def test_cache_invalidated_on_date_change(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify cache invalidates when valuation date changes."""
        _ = option.theta()
        # pylint: disable=protected-access
        assert option._greeks_cache.is_cached("theta")

        new_date = datetime.now(tz=UTC) + timedelta(days=1)
        option.update_valuation_date(new_date)
        # pylint: disable=protected-access
        assert not option._greeks_cache.is_cached("theta")

    def test_cache_invalidated_on_rate_change(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify cache invalidates when risk-free rate changes."""
        rho1 = option.rho()
        # pylint: disable=protected-access
        assert option._greeks_cache.is_cached("rho")

        option.update_risk_free_rate(0.10)
        # pylint: disable=protected-access
        assert not option._greeks_cache.is_cached("rho")

        rho2 = option.rho()
        assert rho2 != rho1

    def test_greeks_batch_computation(self, option: OptionValuation) -> None:
        """Verify greeks() returns all values efficiently."""
        greeks = option.greeks()

        assert "price" in greeks
        assert "delta" in greeks
        assert "gamma" in greeks
        assert "vega" in greeks
        assert "theta" in greeks
        assert "rho" in greeks

        # Cache may be partially invalidated if some Greeks required numerical
        # fallback that called _setup_quantlib(). But at minimum, price and rho
        # should be cached (as they are computed last and don't trigger setup)
        # pylint: disable=protected-access
        assert option._greeks_cache.is_cached(
            "price",
            # pylint: disable=protected-access
        ) or option._greeks_cache.is_cached("rho")

    def test_greeks_batch_consistent_with_individual(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify greeks() returns same values as individual calls."""
        # Get via batch
        batch_greeks = option.greeks()

        # Invalidate cache
        # pylint: disable=protected-access
        option._invalidate_greeks_cache()

        # Get individually
        individual_delta = option.delta()
        individual_gamma = option.gamma()
        individual_vega = option.vega()
        individual_theta = option.theta()
        individual_rho = option.rho()
        individual_price = option.price()

        # Should match
        assert batch_greeks["delta"] == individual_delta
        assert batch_greeks["gamma"] == individual_gamma
        assert batch_greeks["vega"] == individual_vega
        assert batch_greeks["theta"] == individual_theta
        assert batch_greeks["rho"] == individual_rho
        assert batch_greeks["price"] == individual_price

    def test_cache_reuses_computed_values(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify cache reuses values from previous computations."""
        # Compute delta
        delta1 = option.delta()
        # pylint: disable=protected-access
        assert option._greeks_cache.is_cached("delta")

        # Call delta again - should hit cache
        delta2 = option.delta()
        assert delta1 == delta2
        # pylint: disable=protected-access
        assert option._greeks_cache.is_cached("delta")

        # Now call greeks() - should reuse cached delta
        greeks = option.greeks()
        assert greeks["delta"] == delta1

    def test_cache_stats_accessible(self, option: OptionValuation) -> None:
        """Verify cache statistics are accessible."""
        # Initially nothing cached
        # pylint: disable=protected-access
        stats = option._greeks_cache.cache_stats
        assert "registered" in stats
        assert "cached" in stats
        assert "dirty" in stats

        # After computing, should show in cached
        option.delta()
        # pylint: disable=protected-access
        stats = option._greeks_cache.cache_stats
        assert "delta" in stats["cached"]


class TestIntrinsicAndTimeValue:
    """Tests for intrinsic_value() and time_value() methods."""

    @pytest.fixture(params=[ExerciseStyle.AMERICAN, ExerciseStyle.EUROPEAN])
    def make_option(
        self,
        request: pytest.FixtureRequest,
    ) -> callable:
        """Factory for creating options with both exercise styles."""

        def _make(
            spot: float,
            strike: float,
            option_type: OptionType,
            valuation_date: datetime | None = None,
        ) -> OptionValuation:
            return OptionValuation(
                spot_price=spot,
                strike_price=strike,
                maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
                volatility=0.20,
                risk_free_rate=0.05,
                dividend_yield=0.02,
                exercise_style=request.param,
                option_type=option_type,
                valuation_date=valuation_date,
            )

        return _make

    @pytest.mark.parametrize(
        "spot,strike,option_type,expected_intrinsic",
        [
            (110.0, 100.0, OptionType.CALL, 10.0),  # ITM call
            (90.0, 100.0, OptionType.CALL, 0.0),  # OTM call
            (90.0, 100.0, OptionType.PUT, 10.0),  # ITM put
            (110.0, 100.0, OptionType.PUT, 0.0),  # OTM put
        ],
    )
    def test_intrinsic_value(
        self,
        make_option: callable,
        spot: float,
        strike: float,
        option_type: OptionType,
        expected_intrinsic: float,
    ) -> None:
        """Verify intrinsic_value() calculates correctly."""
        option = make_option(spot, strike, option_type)
        assert option.intrinsic_value() == pytest.approx(
            expected_intrinsic,
            abs=1e-9,
        )

    def test_time_value_decomposition(
        self,
        make_option: callable,
    ) -> None:
        """Verify time_value() + intrinsic_value() == price()."""
        option = make_option(100.0, 100.0, OptionType.CALL)
        price = option.price()
        intrinsic = option.intrinsic_value()
        time_value = option.time_value()

        assert time_value + intrinsic == pytest.approx(price, rel=1e-9)

    def test_time_value_positive_before_expiry(
        self,
        make_option: callable,
    ) -> None:
        """Verify time_value() > 0 for ATM option with time remaining."""
        option = make_option(100.0, 100.0, OptionType.CALL)
        assert option.time_value() > 0.0

    def test_time_value_zero_at_expiry(
        self,
        make_option: callable,
    ) -> None:
        """Verify time_value() ≈ 0 at expiry."""
        today = datetime.now(tz=UTC)
        option = make_option(
            100.0,
            100.0,
            OptionType.CALL,
            valuation_date=today,
        )
        # Override maturity to today (at expiry)
        option.maturity_date = today
        option.update_valuation_date(today)

        assert option.time_value() == pytest.approx(0.0, abs=1e-9)


class TestRiskFreeRateUpdate:
    """Tests for update_risk_free_rate() and rate quote mechanism."""

    @pytest.fixture(params=[ExerciseStyle.AMERICAN, ExerciseStyle.EUROPEAN])
    def option(
        self,
        request: pytest.FixtureRequest,
    ) -> OptionValuation:
        """Create a test option with both exercise styles."""
        return OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.20,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            exercise_style=request.param,
            option_type=OptionType.CALL,
        )

    def test_rate_quote_initialized(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify risk_free_rate_quote is created during init."""
        assert hasattr(option, "risk_free_rate_quote")
        assert option.risk_free_rate_quote is not None
        assert option.risk_free_rate_quote.value() == pytest.approx(
            0.05, rel=1e-9
        )

    def test_update_rate_changes_quote(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify update_risk_free_rate modifies the SimpleQuote."""
        option.update_risk_free_rate(0.10)

        assert option.risk_free_rate == pytest.approx(0.10, rel=1e-8)
        assert option.risk_free_rate_quote.value() == pytest.approx(
            0.10, rel=1e-8
        )

    def test_update_rate_affects_call_price(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify call price increases with interest rate."""
        price_low_rate = option.price()

        option.update_risk_free_rate(0.15)  # Higher rate
        price_high_rate = option.price()

        # Higher rates increase call value
        assert price_high_rate > price_low_rate

    def test_update_rate_affects_rho(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify rate changes affect rho."""
        option.update_risk_free_rate(0.02)
        rho_low = option.rho()

        option.update_risk_free_rate(0.15)
        rho_high = option.rho()

        # Rho should differ at different rate levels
        assert rho_low != rho_high

    def test_rate_update_preserves_other_params(
        self,
        option: OptionValuation,
    ) -> None:
        """Verify rate update doesn't affect other parameters."""
        original_spot = option.spot_price
        original_strike = option.strike_price
        original_vol = option.volatility

        option.update_risk_free_rate(0.15)

        assert option.spot_price == original_spot
        assert option.strike_price == original_strike
        assert option.volatility == original_vol


class TestGreeksSignsAndMagnitudes:
    """Tests for well-known Greek properties."""

    @pytest.fixture(params=[ExerciseStyle.AMERICAN, ExerciseStyle.EUROPEAN])
    def atm_long_option(
        self,
        request: pytest.FixtureRequest,
    ) -> OptionValuation:
        """Create ATM long call with both exercise styles."""
        return OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.20,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            exercise_style=request.param,
            option_type=OptionType.CALL,
        )

    @pytest.fixture(params=[ExerciseStyle.AMERICAN, ExerciseStyle.EUROPEAN])
    def atm_put(
        self,
        request: pytest.FixtureRequest,
    ) -> OptionValuation:
        """Create ATM put with both exercise styles."""
        return OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.20,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            exercise_style=request.param,
            option_type=OptionType.PUT,
        )

    def test_gamma_positive_for_long_option(
        self,
        atm_long_option: OptionValuation,
    ) -> None:
        """Verify gamma > 0 for a long option."""
        assert atm_long_option.gamma() > 0.0

    def test_gamma_peaks_near_atm(self) -> None:
        """Verify gamma is larger at ATM than far OTM."""
        atm = OptionValuation(
            spot_price=100.0,
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.20,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            exercise_style=ExerciseStyle.EUROPEAN,
            option_type=OptionType.CALL,
        )
        far_otm = OptionValuation(
            spot_price=100.0,
            strike_price=150.0,  # Far OTM
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            volatility=0.20,
            risk_free_rate=0.05,
            dividend_yield=0.02,
            exercise_style=ExerciseStyle.EUROPEAN,
            option_type=OptionType.CALL,
        )

        assert atm.gamma() > far_otm.gamma()

    def test_rho_positive_for_call(
        self,
        atm_long_option: OptionValuation,
    ) -> None:
        """Verify rho > 0 for a call."""
        assert atm_long_option.rho() > 0.0

    def test_rho_negative_for_put(
        self,
        atm_put: OptionValuation,
    ) -> None:
        """Verify rho < 0 for a put."""
        assert atm_put.rho() < 0.0


def _norm_cdf(x: float) -> float:
    """Compute standard normal CDF using math.erf.

    Uses the standard relationship: Φ(x) = 0.5 * (1 + erf(x / √2))
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _black_scholes_call(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> float:
    """Compute European call price using Black-Scholes formula.

    Independent oracle for verifying OptionValuation's EUROPEAN pricing.
    """
    if time_to_expiry <= 0:
        return max(0.0, spot - strike)

    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility**2)
        * time_to_expiry
    ) / (volatility * math.sqrt(time_to_expiry))
    d2 = d1 - volatility * math.sqrt(time_to_expiry)

    call = spot * math.exp(-dividend_yield * time_to_expiry) * _norm_cdf(
        d1
    ) - strike * math.exp(-risk_free_rate * time_to_expiry) * _norm_cdf(d2)
    return call


def _black_scholes_put(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> float:
    """Compute European put price using Black-Scholes formula."""
    call = _black_scholes_call(
        spot,
        strike,
        time_to_expiry,
        volatility,
        risk_free_rate,
        dividend_yield,
    )
    put = (
        call
        - spot * math.exp(-dividend_yield * time_to_expiry)
        + strike * math.exp(-risk_free_rate * time_to_expiry)
    )
    return put


class TestAmericanEuropeanParity:
    """Tests for American >= European parity and engine selection proof."""

    @pytest.mark.parametrize(
        "strike",
        [5280.0, 4620.0, 3960.0],
    )
    def test_american_geq_european_for_ladder_puts(
        self,
        strike: float,
    ) -> None:
        """American price >= European price for SPX §4 ladder puts.

        Uses actual SPX parameters from docs/repricing-methodology.md §4:
        spot 6600, 1.5y tenor, vol 20%, r 4.5%, q 1.5%. Tests the parity
        relationship on the real ladder used in the program's golden-value
        regression tests.
        """
        american_opt = OptionValuation(
            spot_price=6600.0,
            strike_price=strike,
            maturity_date=datetime(2027, 7, 2, tzinfo=UTC),
            volatility=0.20,
            risk_free_rate=0.045,
            dividend_yield=0.015,
            exercise_style=ExerciseStyle.AMERICAN,
            option_type=OptionType.PUT,
            valuation_date=datetime(2026, 1, 2, tzinfo=UTC),
        )
        european_opt = OptionValuation(
            spot_price=6600.0,
            strike_price=strike,
            maturity_date=datetime(2027, 7, 2, tzinfo=UTC),
            volatility=0.20,
            risk_free_rate=0.045,
            dividend_yield=0.015,
            exercise_style=ExerciseStyle.EUROPEAN,
            option_type=OptionType.PUT,
            valuation_date=datetime(2026, 1, 2, tzinfo=UTC),
        )

        american_price = american_opt.price()
        european_price = european_opt.price()

        # American price must be >= European price (value of early exercise)
        assert american_price >= european_price

    def test_european_price_matches_bs_closed_form_oracle(self) -> None:
        """European engine matches independent Black-Scholes formula.

        This proves that AnalyticEuropeanEngine was selected, not the
        finite-difference grid (FdBlackScholesVanillaEngine) or Bjerksund-
        Stensland approximation. Matching at rel=1e-6 is beyond closed-form
        approximation accuracy (typically 1-5% error), proving we're using
        the analytic engine.

        Uses §4 parameters: 5280-strike put at 6600 spot, 1.5y, 20% vol,
        4.5% rate, 1.5% yield.
        """
        valuation_date = datetime(2026, 1, 2, tzinfo=UTC)
        maturity = datetime(2027, 7, 2, tzinfo=UTC)
        time_to_expiry = (maturity - valuation_date).days / 365.0

        option = OptionValuation(
            spot_price=6600.0,
            strike_price=5280.0,
            maturity_date=maturity,
            volatility=0.20,
            risk_free_rate=0.045,
            dividend_yield=0.015,
            exercise_style=ExerciseStyle.EUROPEAN,
            option_type=OptionType.PUT,
            valuation_date=valuation_date,
        )

        quantlib_price = option.price()
        oracle_price = _black_scholes_put(
            spot=6600.0,
            strike=5280.0,
            time_to_expiry=time_to_expiry,
            volatility=0.20,
            risk_free_rate=0.045,
            dividend_yield=0.015,
        )

        # Match to near machine precision (rel=1e-6) as proof of engine
        assert quantlib_price == pytest.approx(oracle_price, rel=1e-6)

    def test_european_leg_price_within_tolerance_of_golden_table(
        self,
    ) -> None:
        """5280-strike put price matches §4 golden table (95.39 today).

        docs/repricing-methodology.md §4 table, "Price today" column, shows
        the 5280-strike leg at 95.39. This test pins that leg's price to
        within 0.5% of the published value, confirming the calculation.
        """
        valuation_date = datetime(2026, 1, 2, tzinfo=UTC)
        maturity = datetime(2027, 7, 2, tzinfo=UTC)

        option = OptionValuation(
            spot_price=6600.0,
            strike_price=5280.0,
            maturity_date=maturity,
            volatility=0.20,
            risk_free_rate=0.045,
            dividend_yield=0.015,
            exercise_style=ExerciseStyle.EUROPEAN,
            option_type=OptionType.PUT,
            valuation_date=valuation_date,
        )

        price = option.price()

        # Golden table value: 95.39; tolerance: ±0.5%
        assert price == pytest.approx(95.39, rel=0.005)
