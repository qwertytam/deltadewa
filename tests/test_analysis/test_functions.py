"""Tests for deltadewa.analysis.functions module."""

from datetime import datetime, timedelta
import numpy as np
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.analysis import (
    PortfolioAnalyzer,
    classify_maturity_bucket,
    quick_carry_analysis,
    quick_risk_concentration,
    ScenarioGridCache,
)
from deltadewa.analysis.functions import (
    create_scenario_cache_key,
    create_spot_vol_cache_key,
    get_portfolio_state_hash,
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
            option_type="call",
        )
        
        metrics = quick_carry_analysis(portfolio)
        
        assert isinstance(metrics, dict)
        assert 'total_theta_daily' in metrics
        assert 'is_positive_carry' in metrics

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
            option_type="call",
        )
        
        result = quick_risk_concentration(portfolio)
        
        assert isinstance(result, dict)
        assert 'by_strike' in result
        assert 'by_maturity' in result

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
            option_type="call",
        )
        
        result = quick_risk_concentration(portfolio, metrics=['delta'])
        
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
            option_type="call",
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
            option_type="call",
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
            option_type="call",
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
            option_type="call",
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
            option_type="call",
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
            option_type="call",
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
