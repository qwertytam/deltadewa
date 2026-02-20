"""Tests for deltadewa.portfolio.core module."""

from datetime import datetime, timedelta
from deltadewa.portfolio.core import OptionPortfolioBase, OptionPortfolio


class TestOptionPortfolioBase:
    """Test cases for OptionPortfolioBase class."""

    def test_initialization(self):
        """Test OptionPortfolioBase can be instantiated."""
        portfolio = OptionPortfolioBase(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            symbol="TEST",
        )

        assert portfolio is not None
        assert portfolio.underlying_quantity == 100.0
        assert portfolio.spot_price == 100.0
        assert portfolio.volatility == 0.2
        assert portfolio.risk_free_rate == 0.05
        assert portfolio.dividend_yield == 0.0
        assert portfolio.symbol == "TEST"
        assert len(portfolio.positions) == 0

    def test_add_position(self):
        """Test adding a position to the portfolio."""
        portfolio = OptionPortfolioBase()

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].quantity == 1

    def test_add_position_with_custom_volatility(self):
        """Test adding position with custom volatility."""
        portfolio = OptionPortfolioBase(volatility=0.2)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
            volatility=0.3,
        )

        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].custom_volatility is True
        assert portfolio.positions[0].option.volatility == 0.3

    def test_remove_position(self):
        """Test removing a position."""
        portfolio = OptionPortfolioBase(symbol="TEST")

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="put",
        )

        assert len(portfolio.positions) == 2
        portfolio.remove_position(0)
        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].option.strike_price == 105.0
        assert portfolio.symbol == "TEST"

    def test_remove_position_invalid_index(self):
        """Test removing position with invalid index."""
        portfolio = OptionPortfolioBase()

        try:
            portfolio.remove_position(0)
            assert False, "Should raise IndexError"
        except IndexError:
            pass

    def test_update_position(self):
        """Test updating a position."""
        portfolio = OptionPortfolioBase(symbol="TEST")

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        portfolio.update_position(0, quantity=2)

        assert portfolio.positions[0].quantity == 2
        assert portfolio.symbol == "TEST"

    def test_clear_positions(self):
        """Test clearing all positions."""
        portfolio = OptionPortfolioBase(symbol="TEST")

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="put",
        )

        assert len(portfolio.positions) == 2
        assert portfolio.symbol == "TEST"
        portfolio.clear_positions()
        assert len(portfolio.positions) == 0
        assert portfolio.symbol == "TEST"

    def test_total_value(self):
        """Test total_value calculation."""
        portfolio = OptionPortfolioBase(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        total_value = portfolio.total_value()
        assert total_value > 0

    def test_total_underlying_value(self):
        """Test total_underlying_value calculation."""
        portfolio = OptionPortfolioBase(
            underlying_quantity=100, spot_price=50.0
        )

        assert portfolio.total_underlying_value() == 5000.0

    def test_total_portfolio_value(self):
        """Test total_portfolio_value calculation."""
        portfolio = OptionPortfolioBase(
            underlying_quantity=100, spot_price=100.0
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        total_portfolio = portfolio.total_portfolio_value()
        total_options = portfolio.total_value()
        total_underlying = portfolio.total_underlying_value()

        assert total_portfolio == total_options + total_underlying

    def test_get_positions(self):
        """Test get_positions returns proper format."""
        portfolio = OptionPortfolioBase()

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        positions = portfolio.get_positions()
        assert len(positions) == 1
        assert positions[0]["type"] == "Call"
        assert positions[0]["strike"] == 100.0

    def test_to_dataframe(self):
        """Test to_dataframe conversion."""
        portfolio = OptionPortfolioBase()

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        df = portfolio.to_dataframe()
        assert len(df) == 1
        assert "strike" in df.columns
        assert "quantity" in df.columns

    def test_to_dataframe_empty(self):
        """Test to_dataframe with empty portfolio."""
        portfolio = OptionPortfolioBase()

        df = portfolio.to_dataframe()
        assert len(df) == 0

    def test_summary_stats(self):
        """Test summary_stats returns all required fields."""
        portfolio = OptionPortfolioBase()

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        stats = portfolio.summary_stats()

        # Base fields should always be present
        assert "total_positions" in stats
        assert "total_value" in stats
        assert "total_underlying_value" in stats
        assert "total_portfolio_value" in stats
        assert "underlying_quantity" in stats
        assert stats["total_positions"] == 1

        # Greek fields might not be present in base class
        # They would be present in the composed OptionPortfolio
        # but not in OptionPortfolioBase

    def test_summary(self):
        """Test summary string generation."""
        portfolio = OptionPortfolioBase(symbol="TEST")

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        summary = portfolio.summary()
        assert isinstance(summary, str)
        assert "Positions" in summary
        assert "Value" in summary

    def test_summary_market(self):
        """Test summary_market string generation."""
        portfolio = OptionPortfolioBase(symbol="TEST")

        summary = portfolio.summary_market()
        assert isinstance(summary, str)
        assert "Spot Price" in summary
        assert "Volatility" in summary
        assert "TEST" in summary

    def test_update_market_conditions(self):
        """Test updating market conditions."""
        portfolio = OptionPortfolioBase(
            spot_price=100.0, volatility=0.2, symbol="TEST"
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        assert portfolio.symbol == "TEST"

        portfolio.update_market_conditions(spot_price=110.0, volatility=0.3)

        assert portfolio.spot_price == 110.0
        assert portfolio.volatility == 0.3
        assert portfolio.symbol == "TEST"

    def test_set_volatility(self):
        """Test set_volatility method."""
        portfolio = OptionPortfolioBase(volatility=0.2)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )

        portfolio.set_volatility(0.3)

        assert portfolio.volatility == 0.3
        assert portfolio.positions[0].option.volatility == 0.3

    def test_get_symbol(self):
        """Test get_symbol method."""
        portfolio = OptionPortfolioBase()

        # Empty portfolio
        assert portfolio.get_symbol() == "UNKNOWN"

        # With position
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        assert portfolio.get_symbol() == "UNKNOWN"

        # With symbol set
        portfolio.symbol = "TEST"
        assert portfolio.get_symbol() == "TEST"

    def test_monte_carlo_results_property(self):
        """Test monte_carlo_results property."""
        portfolio = OptionPortfolioBase()

        assert portfolio.monte_carlo_results is None

        results = {"prob_profit": 0.6, "expected_pnl": 100.0}
        portfolio.monte_carlo_results = results

        assert portfolio.monte_carlo_results == results

    def test_repr(self):
        """Test __repr__ method."""
        portfolio = OptionPortfolioBase()

        repr_str = repr(portfolio)
        assert isinstance(repr_str, str)
        assert "OptionPortfolio" in repr_str


class TestOptionPortfolio:
    """Test cases for composed OptionPortfolio class."""

    def test_has_all_mixins(self):
        """Test that OptionPortfolio has methods from all mixins."""
        portfolio = OptionPortfolio()

        # Check methods from GreeksMixin
        assert hasattr(portfolio, "total_delta")
        assert hasattr(portfolio, "total_gamma")
        assert hasattr(portfolio, "net_delta")

        # Check methods from PnLMixin
        assert hasattr(portfolio, "calculate_pnl_at_expiry")
        assert hasattr(portfolio, "calculate_net_debit")

        # Check methods from RiskMixin
        assert hasattr(portfolio, "calculate_max_loss_options")
        assert hasattr(portfolio, "calculate_breakeven_points")

        # Check methods from MonteCarloMixin
        assert hasattr(portfolio, "calculate_probability_of_profit")

        # ScenariosMixin has been removed - use PortfolioAnalyzer instead

    def test_instantiation(self):
        """Test OptionPortfolio can be instantiated."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.2,
        )

        assert portfolio is not None
        assert portfolio.spot_price == 100.0
