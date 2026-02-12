"""Tests for deltadewa.portfolio.monte_carlo module."""

from datetime import datetime, timedelta
import numpy as np
import pytest
from deltadewa.portfolio.core import OptionPortfolio


class TestMonteCarloMixin:
    """Test cases for MonteCarloMixin."""

    def test_calculate_probability_of_profit(self):
        """Test calculate_probability_of_profit method with enriched metrics."""
        portfolio = OptionPortfolio(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        result = portfolio.calculate_probability_of_profit(num_simulations=1000)

        # Test keys
        assert "breakeven_points" in result
        assert "simulated_pnls" in result
        assert "num_simulations" in result
        assert "days_to_expiry" in result
        assert "expected_pnl" in result
        assert "median_pnl" in result
        assert "std_pnl" in result
        assert "min_pnl" in result
        assert "max_pnl" in result
        assert "prob_profit" in result
        assert "prob_loss" in result
        assert "var_95" in result
        assert "var_99" in result
        assert "cvar_95" in result
        assert "cvar_99" in result

        # Probability should be between 0 and 1
        assert 0.0 <= result["prob_profit"] <= 1.0
        assert 0.0 <= result["prob_loss"] <= 1.0

        # Probabilities should sum to 1 (within floating-point precision)
        assert abs(result["prob_profit"] + result["prob_loss"] - 1.0) < 1e-9

        # Check that simulated_pnls is an array
        assert isinstance(result["simulated_pnls"], np.ndarray)
        assert len(result["simulated_pnls"]) > 0

        # Check num_simulations matches array length
        assert result["num_simulations"] == len(result["simulated_pnls"])

        # Check VaR ordering (99% VaR should be worse than 95% VaR)
        assert result["var_99"] <= result["var_95"]

        # Check CVaR ordering (99% CVaR should be worse than 95% CVaR)
        assert result["cvar_99"] <= result["cvar_95"]

        # Check min/max bounds
        assert result["min_pnl"] <= result["var_99"]
        assert result["var_95"] <= result["max_pnl"]

        assert isinstance(result["expected_pnl"], float)
        assert isinstance(result["breakeven_points"], list)

    def test_calculate_probability_with_underlying(self):
        """Test calculate_probability_of_profit including underlying."""
        portfolio = OptionPortfolio(underlying_quantity=100.0, spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="call",
        )

        result = portfolio.calculate_probability_of_profit(
            num_simulations=1000, include_underlying=True
        )

        assert "prob_profit" in result
        assert 0.0 <= result["prob_profit"] <= 1.0
        assert "simulated_pnls" in result
        assert len(result["simulated_pnls"]) > 0

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
            num_simulations=1000, days_to_expiry=60
        )

        assert "prob_profit" in result
        assert result["days_to_expiry"] == 60

    def test_calculate_probability_empty_portfolio(self):
        """Test calculate_probability_of_profit with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Should still work with no positions
        result = portfolio.calculate_probability_of_profit(num_simulations=1000)

        assert "prob_profit" in result
        assert "simulated_pnls" in result
        # Empty portfolio should have zero P&L
        assert abs(result["expected_pnl"]) < 0.01

    def test_calculate_probability_normal_method_raises(self):
        """Test that normal method raises NotImplementedError."""
        portfolio = OptionPortfolio(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        with pytest.raises(NotImplementedError):
            portfolio.calculate_probability_of_profit(
                method="normal", num_simulations=100
            )

    def test_monte_carlo_results_storage(self):
        """Test that Monte Carlo results can be stored in portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        result = portfolio.calculate_probability_of_profit(num_simulations=1000)

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

        result = portfolio.calculate_probability_of_profit(
            num_simulations=10000
        )

        assert "prob_profit" in result
        assert 0.0 <= result["prob_profit"] <= 1.0
        assert result["num_simulations"] == 10000

    def test_vectorized_vs_scalar_consistency(self):
        """Test that vectorized results are consistent with scalar approach."""
        np.random.seed(42)  # For reproducibility

        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        # Run vectorized version
        _ = portfolio.calculate_probability_of_profit(num_simulations=1000)

        # Verify spot prices generate correct P&L
        test_spots = np.array([90.0, 100.0, 110.0])
        pnls = portfolio.vectorized_pnl_at_expiry(
            test_spots, include_underlying=False
        )

        # Manually compute expected P&L
        # pylint: disable=assignment-from-no-return
        initial_cost = portfolio.total_value()
        expected_pnls = []
        for spot in test_spots:
            intrinsic = max(0, spot - 100.0)  # Call with strike 100
            value = intrinsic * 1 * 100  # 1 contract, 100 size
            expected_pnls.append(value - initial_cost)

        # Check they match
        np.testing.assert_allclose(pnls, expected_pnls, rtol=1e-5)

    def test_underlying_only_portfolio(self):
        """Test Monte Carlo with underlying position only (no options)."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0, spot_price=100.0, volatility=0.2
        )

        result = portfolio.calculate_probability_of_profit(
            num_simulations=10000, include_underlying=True
        )

        assert "prob_profit" in result
        assert "simulated_pnls" in result
        # With symmetric GBM and risk-free drift, probability should be around 0.5
        # Using larger sample size (10k) and tighter bounds for better validation
        assert 0.45 <= result["prob_profit"] <= 0.55

    def test_single_position_portfolio(self):
        """Test Monte Carlo with single option position."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="put",
        )

        result = portfolio.calculate_probability_of_profit(num_simulations=1000)

        assert "prob_profit" in result
        assert "var_95" in result
        assert "cvar_95" in result
        assert len(result["simulated_pnls"]) == 1000
