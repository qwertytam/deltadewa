"""Tests for deltadewa.analysis.functions module."""

from datetime import datetime, timedelta
import numpy as np
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.functions import (
    classify_maturity_bucket,
    quick_carry_analysis,
    quick_risk_concentration,
)
from deltadewa.spot_utils import generate_spot_range
from deltadewa.analysis.cache import (
    ScenarioGridCache,
    create_scenario_cache_key,
    create_spot_vol_cache_key,
    get_portfolio_state_hash,
)
from deltadewa.constants import OptionType


class TestGenerateSpotRange:
    """Test cases for generate_spot_range function."""

    def test_passthrough_existing_spot_range(self):
        """Test that existing spot_range is returned as-is."""
        existing_range = np.array([90.0, 100.0, 110.0])
        result = generate_spot_range(100.0, spot_range=existing_range)

        # Should be the exact same array
        np.testing.assert_array_equal(result, existing_range)

    def test_standard_range_with_defaults(self):
        """Test standard range generation with default parameters."""
        spot_price = 100.0
        result = generate_spot_range(spot_price)

        # Check it's a numpy array
        assert isinstance(result, np.ndarray)

        # Check number of points
        assert len(result) == 250  # default num_points

        # Check bounds (default is 0% to 200%)
        # Lower bound should be max(0.01, 100 * 0.0 / 100) = 0.01
        assert result[0] == 0.01
        # Upper bound should be 100 * 200 / 100 = 200
        assert result[-1] == 200.0

        # Check it's sorted
        assert np.all(result[:-1] <= result[1:])

    def test_standard_range_with_custom_bounds(self):
        """Test standard range with custom min/max percentages."""
        spot_price = 100.0
        result = generate_spot_range(
            spot_price,
            spot_min_pct=80.0,
            spot_max_pct=120.0,
            num_points=100,
        )

        # Check number of points
        assert len(result) == 100

        # Check bounds
        # Lower bound should be max(0.01, 100 * 80 / 100) = 80
        assert result[0] == 80.0
        # Upper bound should be 100 * 120 / 100 = 120
        assert result[-1] == 120.0

        # Check it's sorted
        assert np.all(result[:-1] <= result[1:])

    def test_comprehensive_range_includes_extremes(self):
        """Test comprehensive range includes extreme values."""
        spot_price = 100.0
        result = generate_spot_range(spot_price, use_comprehensive_range=True)

        # Check it's a numpy array
        assert isinstance(result, np.ndarray)

        # Check that it includes near-zero
        # Near-zero should be max(0.01, 100 * 0.0001) = 0.01
        assert result[0] == 0.01

        # Check that it includes high multiples
        # Maximum should be 10x spot = 1000
        assert result[-1] == 1000.0

        # Check it's sorted
        assert np.all(result[:-1] <= result[1:])

    def test_comprehensive_range_includes_critical_points(self):
        """Test comprehensive range includes critical points."""
        spot_price = 100.0
        result = generate_spot_range(spot_price, use_comprehensive_range=True)

        # Check that critical points are included
        critical_points = [
            0.01,  # near-zero
            10.0,  # 90% down
            25.0,  # 75% down
            50.0,  # 50% down
            75.0,  # 25% down
            100.0,  # current spot
            125.0,  # 25% up
            150.0,  # 50% up
            200.0,  # 100% up
            300.0,  # 200% up
            500.0,  # 400% up
            1000.0,  # 900% up
        ]

        for cp in critical_points:
            assert np.any(
                np.isclose(result, cp)
            ), f"Critical point {cp} not found"

    def test_results_are_sorted(self):
        """Test that results are always sorted."""
        spot_price = 100.0

        # Test standard range
        result_standard = generate_spot_range(spot_price)
        assert np.all(result_standard[:-1] <= result_standard[1:])

        # Test comprehensive range
        result_comprehensive = generate_spot_range(
            spot_price, use_comprehensive_range=True
        )
        assert np.all(result_comprehensive[:-1] <= result_comprehensive[1:])

    def test_near_zero_floor_logic(self):
        """Test that near-zero floor logic correctly handles edge cases.

        The near-zero floor (0.01) is used as the minimum for the linspace calculation,
        but critical points derived from spot_price may be smaller than 0.01.
        The final range includes both linspace values and critical points.
        """
        # Test with very small spot price
        spot_price = 0.001
        result = generate_spot_range(spot_price, use_comprehensive_range=True)

        # The near-zero used for linspace should be max(0.01, 0.001 * 0.0001) = 0.01
        # But critical points based on spot_price can be smaller
        # So result[0] will be min(critical_points) = spot_price * 0.1 = 0.0001
        assert result[0] == 0.0001

        # The near_zero value (0.01) should be in the range
        assert np.any(np.isclose(result, 0.01))

        # Test with larger spot price where near_zero > 0.01
        spot_price = 10000.0
        result = generate_spot_range(spot_price, use_comprehensive_range=True)

        # Near-zero should be max(0.01, 10000 * 0.0001) = 1.0
        # But critical points like 10000 * 0.1 = 1000 are larger
        # So result[0] will be the near_zero value = 1.0
        assert result[0] == 1.0

    def test_standalone_produces_same_results_as_riskmixin(self):
        """Test standalone function produces identical results to RiskMixin._get_spot_range()."""
        # Create a portfolio with RiskMixin
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        # Test standard range
        result_standalone = generate_spot_range(
            spot_price=100.0,
            spot_min_pct=0.0,
            spot_max_pct=200.0,
            num_points=250,
            use_comprehensive_range=False,
        )
        # pylint: disable=protected-access
        result_riskmixin = portfolio._get_spot_range(
            spot_min_pct=0.0,
            spot_max_pct=200.0,
            num_points=250,
            use_comprehensive_range=False,
        )
        np.testing.assert_array_equal(result_standalone, result_riskmixin)

        # Test comprehensive range
        result_standalone_comp = generate_spot_range(
            spot_price=100.0,
            use_comprehensive_range=True,
        )
        # pylint: disable=protected-access
        result_riskmixin_comp = portfolio._get_spot_range(
            use_comprehensive_range=True,
        )
        np.testing.assert_array_equal(
            result_standalone_comp, result_riskmixin_comp
        )


class TestModuleLevelFunctions:
    """Test cases for module-level convenience functions."""

    def test_classify_maturity_bucket_function(self):
        """Test standalone classify_maturity_bucket function."""
        assert classify_maturity_bucket(5) == "0-7 days (Weekly)"
        assert classify_maturity_bucket(15) == "8-30 days (Monthly)"
        assert classify_maturity_bucket(45) == "31-60 days (2M)"
        assert classify_maturity_bucket(75) == "61-90 days (3M)"
        assert classify_maturity_bucket(120) == "90+ days (Long-term)"

    def test_quick_carry_analysis(self):
        """Test quick_carry_analysis function."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        metrics = quick_carry_analysis(portfolio)

        assert isinstance(metrics, dict)
        assert "total_theta_daily" in metrics
        assert "is_positive_carry" in metrics

    def test_quick_risk_concentration(self):
        """Test quick_risk_concentration function."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        result = quick_risk_concentration(portfolio)

        assert isinstance(result, dict)
        assert "by_strike" in result
        assert "by_maturity" in result

    def test_quick_risk_concentration_custom_metrics(self):
        """Test quick_risk_concentration with custom metrics."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        result = quick_risk_concentration(portfolio, metrics=["delta"])

        assert isinstance(result, dict)


class TestCachingFunctions:
    """Test cases for caching utility functions."""

    def test_create_scenario_cache_key(self):
        """Test scenario cache key creation."""
        spot_scenarios = np.array([90, 100, 110])
        time_points = [datetime(2024, 1, 1), datetime(2024, 1, 2)]
        metric = "pnl"
        portfolio_hash = "abc123"

        key = create_scenario_cache_key(
            spot_scenarios, time_points, metric, portfolio_hash
        )

        assert isinstance(key, tuple)
        assert len(key) == 4

    def test_create_spot_vol_cache_key(self):
        """Test spot/vol cache key creation."""
        spot_scenarios = np.array([90, 100, 110])
        vol_scenarios = np.array([0.2, 0.3, 0.4])
        metric = "pnl"
        portfolio_hash = "abc123"

        key = create_spot_vol_cache_key(
            spot_scenarios, vol_scenarios, metric, portfolio_hash
        )

        assert isinstance(key, tuple)
        assert key[0] == "spot_vol"

    def test_get_portfolio_state_hash(self):
        """Test portfolio state hash generation."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        hash1 = get_portfolio_state_hash(portfolio)
        assert isinstance(hash1, str)
        assert len(hash1) > 0

        # Same portfolio should produce same hash
        hash2 = get_portfolio_state_hash(portfolio)
        assert hash1 == hash2

        # Different portfolio should produce different hash
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )
        hash3 = get_portfolio_state_hash(portfolio)
        assert hash3 != hash1


class TestScenarioGridCache:
    """Test cases for ScenarioGridCache class."""

    def test_initialization(self):
        """Test ScenarioGridCache initialization."""
        cache = ScenarioGridCache(max_size=64)

        assert cache is not None
        assert cache.size() == 0

    def test_get_or_calculate_first_call(self):
        """Test first call to get_or_calculate calculates."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        cache = ScenarioGridCache()
        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([95, 100, 105])
        time_points = [datetime.now()]

        result = cache.get_or_calculate(
            portfolio, analyzer, spot_scenarios, time_points, "pnl"
        )

        assert result is not None
        assert cache.size() == 1

    def test_get_or_calculate_second_call_cached(self):
        """Test second call returns cached result."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        cache = ScenarioGridCache()
        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([95, 100, 105])
        time_points = [datetime.now()]

        result1 = cache.get_or_calculate(
            portfolio, analyzer, spot_scenarios, time_points, "pnl"
        )

        result2 = cache.get_or_calculate(
            portfolio, analyzer, spot_scenarios, time_points, "pnl"
        )

        # Should still be cached
        assert cache.size() == 1
        assert len(result1) == len(result2)

    def test_get_or_calculate_spot_vol(self):
        """Test get_or_calculate_spot_vol method."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        cache = ScenarioGridCache()
        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([95, 100, 105])
        vol_scenarios = np.array([0.2, 0.3, 0.4])

        result = cache.get_or_calculate_spot_vol(
            portfolio, analyzer, spot_scenarios, vol_scenarios, "pnl"
        )

        assert result is not None
        assert cache.size() == 1

    def test_clear_cache(self):
        """Test cache clearing."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        cache = ScenarioGridCache()
        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([95, 100, 105])
        time_points = [datetime.now()]

        cache.get_or_calculate(
            portfolio, analyzer, spot_scenarios, time_points, "pnl"
        )

        assert cache.size() == 1

        cache.clear()
        assert cache.size() == 0

    def test_cache_max_size(self):
        """Test cache respects max_size with LRU eviction."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        cache = ScenarioGridCache(max_size=2)
        analyzer = PortfolioAnalyzer(portfolio)

        time_points = [datetime.now()]

        # Add 3 different scenarios
        cache.get_or_calculate(
            portfolio, analyzer, np.array([95, 100]), time_points, "pnl"
        )
        cache.get_or_calculate(
            portfolio, analyzer, np.array([100, 105]), time_points, "pnl"
        )
        cache.get_or_calculate(
            portfolio, analyzer, np.array([105, 110]), time_points, "pnl"
        )

        # Should only keep 2 (most recent)
        assert cache.size() <= 2
