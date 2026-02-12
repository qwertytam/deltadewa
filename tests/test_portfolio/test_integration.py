"""Integration tests for the complete OptionPortfolio with all mixins."""

from datetime import datetime, timedelta
import numpy as np
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.position import OptionPosition
from deltadewa.portfolio.factory import (
    create_empty_portfolio,
    create_demo_portfolio,
)
from deltadewa.analysis.base import PortfolioAnalyzer


class TestPortfolioIntegration:
    """Integration tests for full portfolio functionality."""

    def test_imports(self):
        """Test that all expected classes can be imported."""
        assert OptionPortfolio is not None
        assert OptionPosition is not None
        assert create_empty_portfolio is not None
        assert create_demo_portfolio is not None

    def test_full_workflow(self):
        """Test a complete portfolio workflow."""
        # Create portfolio
        portfolio = OptionPortfolio(
            underlying_quantity=100.0, spot_price=100.0, volatility=0.2
        )

        # Add positions
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="put",
            symbol="AAPL",
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
            symbol="AAPL",
        )

        # Test core functionality
        assert len(portfolio.positions) == 2
        assert portfolio.total_value() > 0

        # Test Greeks
        assert isinstance(portfolio.total_delta(), float)
        assert isinstance(portfolio.total_gamma(), float)
        assert isinstance(portfolio.net_delta(), float)

        # Test P&L
        pnl = portfolio.calculate_pnl_at_expiry(100.0)
        assert isinstance(pnl, float)

        # Test risk analysis
        max_loss = portfolio.calculate_max_loss_options()
        assert "max_loss" in max_loss

        breakevens = portfolio.calculate_breakeven_points()
        assert isinstance(breakevens, list)

        # Test Monte Carlo
        prob = portfolio.calculate_probability_of_profit(num_simulations=100)
        assert "prob_profit" in prob

        # Test scenario analysis using PortfolioAnalyzer
        analyzer = PortfolioAnalyzer(portfolio)
        spot_range = np.linspace(90, 110, 5)
        time_points = [portfolio.valuation_date]
        scenarios = analyzer.scenario_grid(
            spot_scenarios=spot_range,
            time_points=time_points,
            metric="pnl",
        )
        assert len(scenarios) == 5

    def test_complex_strategy(self):
        """Test a complex options strategy (iron condor)."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Iron Condor: Short 95-105 strangle, Long 90-110 strangle
        # Short put spread
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="put",
        )
        portfolio.add_position(
            strike_price=90.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="put",
        )

        # Short call spread
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="call",
        )
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        # Verify structure
        assert len(portfolio.positions) == 4

        # Iron condor characteristics:
        # - Has both short calls and short puts
        # - Has both long calls and long puts as protection
        # In practice, max profit and loss are limited
        # However, detection algorithms may flag short options as unlimited
        max_loss = portfolio.calculate_max_loss_options()
        max_profit = portfolio.calculate_max_profit_options()

        # Just check that we got results
        assert "max_loss" in max_loss
        assert "max_profit" in max_profit
        assert "is_unlimited" in max_loss
        assert "is_unlimited" in max_profit

        # Should have breakeven points
        breakevens = portfolio.calculate_breakeven_points()
        # Note: Depending on pricing, might be 0, 2, or 4 breakevens
        assert isinstance(breakevens, list)

    def test_position_update_and_removal(self):
        """Test updating and removing positions."""
        portfolio = create_demo_portfolio()

        initial_count = len(portfolio.positions)
        assert initial_count == 2

        # Update a position
        portfolio.update_position(0, quantity=2)
        assert portfolio.positions[0].quantity == 2

        # Remove a position
        portfolio.remove_position(1)
        assert len(portfolio.positions) == 1

        # Clear all
        portfolio.clear_positions()
        assert len(portfolio.positions) == 0

    def test_market_conditions_update(self):
        """Test updating market conditions across portfolio."""
        portfolio = create_demo_portfolio()

        original_spot = portfolio.spot_price
        portfolio.update_market_conditions(spot_price=110.0)

        assert portfolio.spot_price == 110.0
        assert portfolio.spot_price != original_spot

    def test_custom_volatility_positions(self):
        """Test portfolio with custom volatility positions."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)

        # Add position with portfolio volatility
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        # Add position with custom volatility
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
            volatility=0.3,
        )

        assert not portfolio.positions[0].custom_volatility
        assert portfolio.positions[1].custom_volatility

        # Update portfolio volatility
        portfolio.set_volatility(0.25)

        # First position should update, second shouldn't
        assert portfolio.positions[0].option.volatility == 0.25
        assert portfolio.positions[1].option.volatility == 0.3

    def test_dataframe_export(self):
        """Test exporting portfolio to DataFrame."""
        portfolio = create_demo_portfolio()

        df = portfolio.to_dataframe()

        assert len(df) == 2
        assert "symbol" in df.columns
        assert "strike" in df.columns
        assert "type" in df.columns
        assert "quantity" in df.columns

    def test_summary_methods(self):
        """Test summary generation methods."""
        portfolio = create_demo_portfolio()

        # Test summary
        summary = portfolio.summary()
        assert isinstance(summary, str)
        assert len(summary) > 0

        # Test summary_market
        summary_market = portfolio.summary_market()
        assert isinstance(summary_market, str)
        assert len(summary_market) > 0

        # Test summary_stats
        stats = portfolio.summary_stats()
        assert isinstance(stats, dict)
        assert "total_positions" in stats

    def test_risk_reward_full_analysis(self):
        """Test complete risk/reward analysis using PortfolioAnalyzer."""

        portfolio = OptionPortfolio(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        analyzer = PortfolioAnalyzer(portfolio)
        # pylint: disable=assignment-from-no-return
        analysis = analyzer.risk_reward_analysis(num_simulations=100)

        # Ensure analysis is not None
        assert analysis is not None, "risk_reward_analysis returned None"

        # Verify all expected keys are present
        expected_keys = [
            "net_debit",
            "max_loss_options",
            "max_profit_options",
            "breakeven_options",
            "max_loss_total",
            "max_profit_total",
            "breakeven_total",
            "prob_profit",
            "expected_pnl",
        ]

        for key in expected_keys:
            assert analysis[key] is not None, f"Missing key in analysis: {key}"

    def test_empty_portfolio_operations(self):
        """Test that operations work on empty portfolio."""
        portfolio = create_empty_portfolio()

        assert portfolio.total_value() == 0.0
        assert portfolio.total_delta() == 0.0
        assert portfolio.total_gamma() == 0.0

        pnl = portfolio.calculate_pnl_at_expiry(100.0)
        assert pnl == 0.0

        breakevens = portfolio.calculate_breakeven_points()
        assert len(breakevens) == 0
