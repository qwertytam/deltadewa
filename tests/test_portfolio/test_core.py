"""Tests for deltadewa.portfolio.core module."""

import unittest
from datetime import UTC, datetime, timedelta

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio, OptionPortfolioBase


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
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].quantity == 1

    def test_add_position_with_custom_volatility(self):
        """Test adding position with custom volatility."""
        portfolio = OptionPortfolioBase(volatility=0.2)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
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
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
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
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        portfolio.update_position(0, quantity=2)

        assert portfolio.positions[0].quantity == 2
        assert portfolio.symbol == "TEST"

    def test_update_position_exercise_style_synced(self):
        """Regression test: updating exercise_style must sync both
        OptionPosition.exercise_style and OptionPosition.option.exercise_style.
        Previously, update_position only updated the OptionValuation attribute,
        leaving the OptionPosition attribute stale. This caused the position
        table (to_dict) to show the old value, and update_market_conditions to
        silently revert the change when it recreated OptionValuation instances.
        """
        portfolio = OptionPortfolioBase(spot_price=100.0, volatility=0.2)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.AMERICAN,
        )

        pos = portfolio.positions[0]
        assert pos.exercise_style == ExerciseStyle.AMERICAN
        assert pos.option.exercise_style == ExerciseStyle.AMERICAN

        # Change exercise style via update_position
        portfolio.update_position(0, exercise_style=ExerciseStyle.EUROPEAN)

        pos = portfolio.positions[0]
        # Both OptionPosition and OptionValuation attributes must reflect the change
        assert (
            pos.option.exercise_style == ExerciseStyle.EUROPEAN
        ), "OptionValuation.exercise_style not updated"
        assert (
            pos.exercise_style == ExerciseStyle.EUROPEAN
        ), "OptionPosition.exercise_style not synced after update"

        # Confirm to_dict (used by the position table) also reflects the change
        assert (
            pos.to_dict()["exercise_style"] == ExerciseStyle.EUROPEAN
        ), "to_dict() still returns stale exercise_style"

        # Confirm update_market_conditions preserves the updated exercise style
        portfolio.update_market_conditions(spot_price=105.0)
        pos = portfolio.positions[0]
        assert (
            pos.exercise_style == ExerciseStyle.EUROPEAN
        ), "exercise_style reverted after update_market_conditions"
        assert (
            pos.option.exercise_style == ExerciseStyle.EUROPEAN
        ), "OptionValuation.exercise_style reverted after update_market_conditions"

    def test_clear_positions(self):
        """Test clearing all positions."""
        portfolio = OptionPortfolioBase(symbol="TEST")

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
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
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        total_value = portfolio.total_value()
        assert total_value > 0

    def test_total_underlying_value(self):
        """Test total_underlying_value calculation."""
        portfolio = OptionPortfolioBase(
            underlying_quantity=100, spot_price=50.0,
        )

        assert portfolio.total_underlying_value() == 5000.0

    def test_total_portfolio_value(self):
        """Test total_portfolio_value calculation."""
        portfolio = OptionPortfolioBase(
            underlying_quantity=100, spot_price=100.0,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
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
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        positions = portfolio.get_positions()
        assert len(positions) == 1
        assert positions[0]["type"] == OptionType.CALL
        assert positions[0]["strike"] == 100.0

    def test_to_dataframe(self):
        """Test to_dataframe conversion."""
        portfolio = OptionPortfolioBase()

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
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
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
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
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
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
            spot_price=100.0, volatility=0.2, symbol="TEST",
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
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
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
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
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
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
        assert hasattr(portfolio, "run_monte_carlo_simulation")

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


class TestPortfolioCore(unittest.TestCase):
    """Test cases for core portfolio functionality."""

    def setUp(self):
        # Initialize with explicit Symbol
        self.portfolio = OptionPortfolio(symbol="TSLA", spot_price=200.0)

    def test_portfolio_symbol_storage(self):
        """Test that symbol is stored at portfolio level"""
        pf = OptionPortfolio(symbol="TSLA")
        self.assertEqual(pf.get_symbol(), "TSLA")

    def test_add_position_defaults(self):
        """Test adding position uses defaults and works without position-level symbol"""
        self.portfolio.add_position(
            strike_price=210,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            option_type=OptionType.CALL,
            quantity=1,
        )

        # Verify position was added
        self.assertEqual(len(self.portfolio.positions), 1)
        pos = self.portfolio.positions[0]

        # Verify defaults
        self.assertEqual(pos.exercise_style, ExerciseStyle.AMERICAN)

    def test_european_position_pricing(self):
        """Test that a portfolio can hold and price European options"""
        self.portfolio.add_position(
            strike_price=210,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            option_type=OptionType.CALL,
            quantity=1,
            exercise_style=ExerciseStyle.EUROPEAN,  # Explicitly European
        )

        # pylint: disable=assignment-from-no-return
        value = self.portfolio.total_value()
        self.assertGreater(value, 0)
        self.assertEqual(
            self.portfolio.positions[0].exercise_style, ExerciseStyle.EUROPEAN,
        )

    def test_mixed_styles(self):
        """Portfolio should handle both styles simultaneously"""
        # Long American Call
        self.portfolio.add_position(
            strike_price=200,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            option_type=OptionType.CALL,
            quantity=1,
            exercise_style=ExerciseStyle.AMERICAN,
        )
        # Short European Call
        self.portfolio.add_position(
            strike_price=200,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            option_type=OptionType.CALL,
            quantity=-1,
            exercise_style=ExerciseStyle.EUROPEAN,
        )

        # Since American >= European, Net Value should be >= 0
        # pylint: disable=assignment-from-no-return
        net_value = self.portfolio.total_value()
        self.assertGreaterEqual(net_value, -0.01)  # Allow for float precision
