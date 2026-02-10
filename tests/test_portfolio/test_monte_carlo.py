"""Tests for deltadewa.portfolio.monte_carlo module."""

from datetime import datetime, timedelta
from deltadewa.portfolio import OptionPortfolio


class TestMonteCarloMixin:
    """Test cases for MonteCarloMixin."""

    def test_calculate_probability_of_profit(self):
        """Test calculate_probability_of_profit method."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        result = portfolio.calculate_probability_of_profit(num_simulations=100)
        
        assert "probability" in result
        assert "expected_value" in result
        assert "breakeven_points" in result
        
        # Probability should be between 0 and 1
        assert 0.0 <= result["probability"] <= 1.0
        assert isinstance(result["expected_value"], float)
        assert isinstance(result["breakeven_points"], list)

    def test_calculate_probability_with_underlying(self):
        """Test calculate_probability_of_profit including underlying."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0, spot_price=100.0
        )
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="call",
        )
        
        result = portfolio.calculate_probability_of_profit(
            num_simulations=100, include_underlying=True
        )
        
        assert "probability" in result
        assert 0.0 <= result["probability"] <= 1.0

    def test_calculate_probability_custom_days(self):
        """Test calculate_probability_of_profit with custom days_to_expiry."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        result = portfolio.calculate_probability_of_profit(
            num_simulations=100, days_to_expiry=60
        )
        
        assert "probability" in result

    def test_calculate_probability_empty_portfolio(self):
        """Test calculate_probability_of_profit with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        # Should still work with no positions
        result = portfolio.calculate_probability_of_profit(num_simulations=100)
        
        assert "probability" in result
        # No positions means no cost, so any price change is profitable for underlying
        # But we have no underlying either, so probability depends on implementation

    def test_calculate_probability_normal_method(self):
        """Test calculate_probability_of_profit with normal method."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        result = portfolio.calculate_probability_of_profit(
            method="normal", num_simulations=100
        )
        
        assert "probability" in result
        assert 0.0 <= result["probability"] <= 1.0

    def test_monte_carlo_results_storage(self):
        """Test that Monte Carlo results can be stored in portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        result = portfolio.calculate_probability_of_profit(num_simulations=100)
        
        # Store results
        portfolio.monte_carlo_results = result
        
        # Retrieve results
        stored = portfolio.monte_carlo_results
        assert stored == result

    def test_probability_high_simulations(self):
        """Test with higher number of simulations."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        result = portfolio.calculate_probability_of_profit(num_simulations=1000)
        
        assert "probability" in result
        assert 0.0 <= result["probability"] <= 1.0
