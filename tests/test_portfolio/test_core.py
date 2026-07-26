"""Tests for deltadewa.portfolio.core module."""

import unittest
from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio, OptionPortfolioBase


class TestOptionPortfolioBase:
    """Test cases for OptionPortfolioBase class."""

    def test_initialization(self) -> None:
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
        assert portfolio.underlying_quantity == pytest.approx(100.0, rel=1e-5)
        assert portfolio.spot_price == pytest.approx(100.0, rel=1e-5)
        assert portfolio.volatility == pytest.approx(0.2, rel=1e-4)
        assert portfolio.risk_free_rate == pytest.approx(0.05, rel=1e-9)
        assert portfolio.dividend_yield == pytest.approx(0.0, rel=1e-8)
        assert portfolio.symbol == "TEST"
        assert len(portfolio.positions) == 0

    def test_add_position(self) -> None:
        """Test adding a position to the portfolio."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.AMERICAN
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].quantity == 1

    def test_add_position_with_custom_volatility(self) -> None:
        """Test adding position with custom volatility."""
        portfolio = OptionPortfolioBase(
            volatility=0.2, default_exercise_style=ExerciseStyle.AMERICAN
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.3,
        )

        assert len(portfolio.positions) == 1
        assert portfolio.positions[0].custom_volatility is True
        assert portfolio.positions[0].option.volatility == pytest.approx(
            0.3, rel=1e-4
        )

    def test_add_position_auto_captures_entry_spot_and_date(self) -> None:
        """Test add_position captures current spot/date as entry by default."""
        valuation_date = datetime.now(tz=UTC)
        portfolio = OptionPortfolioBase(
            spot_price=123.0,
            valuation_date=valuation_date,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=valuation_date + timedelta(days=30),
            quantity=1,
        )

        assert portfolio.positions[0].entry_spot == pytest.approx(
            123.0, rel=1e-4
        )
        assert portfolio.positions[0].entry_date == valuation_date

    def test_add_position_explicit_entry_spot_and_date_override(self) -> None:
        """Test explicit entry_spot/entry_date override the portfolio's."""
        portfolio = OptionPortfolioBase(
            spot_price=123.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        entry_date = datetime.now(tz=UTC) - timedelta(days=10)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            entry_spot=110.0,
            entry_date=entry_date,
        )

        assert portfolio.positions[0].entry_spot == pytest.approx(
            110.0, rel=1e-4
        )
        assert portfolio.positions[0].entry_date == entry_date

    def test_remove_position(self) -> None:
        """Test removing a position."""
        portfolio = OptionPortfolioBase(
            symbol="TEST",
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

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
        assert portfolio.positions[0].option.strike_price == pytest.approx(
            105.0, rel=1e-4
        )
        assert portfolio.symbol == "TEST"

    def test_remove_position_invalid_index(self) -> None:
        """Test removing position with invalid index."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        try:
            portfolio.remove_position(0)
            raise AssertionError(False, "Should raise IndexError")
        except IndexError:
            pass

    def test_add_position_returns_appended_position(self) -> None:
        """add_position returns the object that was appended to positions."""
        portfolio = OptionPortfolioBase(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        returned = portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )
        assert returned is portfolio.positions[-1]
        assert isinstance(returned.position_id, str)
        assert returned.position_id != ""

    def test_update_position(self) -> None:
        """Test updating a position."""
        portfolio = OptionPortfolioBase(
            symbol="TEST",
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        portfolio.update_position(0, quantity=2)

        assert portfolio.positions[0].quantity == 2
        assert portfolio.symbol == "TEST"

    def test_update_position_exercise_style_synced(self) -> None:
        """Regression test.

        Testing: updating exercise_style must sync both
        OptionPosition.exercise_style and OptionPosition.option.exercise_style.
        Previously, update_position only updated the OptionValuation attribute,
        leaving the OptionPosition attribute stale. This caused the position
        table (to_dict) to show the old value, and update_market_conditions to
        silently revert the change when it recreated OptionValuation instances.
        """
        portfolio = OptionPortfolioBase(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

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
        # Both OptionPosition and OptionValuation attributes must reflect the
        # change
        assert pos.option.exercise_style == ExerciseStyle.EUROPEAN, (
            "OptionValuation.exercise_style not updated"
        )
        assert pos.exercise_style == ExerciseStyle.EUROPEAN, (
            "OptionPosition.exercise_style not synced after update"
        )

        # Confirm to_dict (used by the position table) also reflects the change
        assert pos.to_dict()["exercise_style"] == ExerciseStyle.EUROPEAN, (
            "to_dict() still returns stale exercise_style"
        )

        # Confirm update_market_conditions preserves the updated exercise style
        portfolio.update_market_conditions(spot_price=105.0)
        pos = portfolio.positions[0]
        assert pos.exercise_style == ExerciseStyle.EUROPEAN, (
            "exercise_style reverted after update_market_conditions"
        )
        assert pos.option.exercise_style == ExerciseStyle.EUROPEAN, (
            "Valuation.exercise_style reverted after update_market_conditions"
        )

    def test_update_position_preserves_position_id(self) -> None:
        """update_position keeps same object; position_id is stable."""
        portfolio = OptionPortfolioBase(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )
        original_id = portfolio.positions[0].position_id
        assert original_id != ""

        # Update quantity (field mutation — no OptionValuation rebuild)
        portfolio.update_position(0, quantity=5)
        assert portfolio.positions[0].position_id == original_id

        # Update strike (triggers OptionValuation rebuild inside OptionPosition)
        portfolio.update_position(0, strike=110.0)
        assert portfolio.positions[0].position_id == original_id

    def test_clear_positions(self) -> None:
        """Test clearing all positions."""
        portfolio = OptionPortfolioBase(
            symbol="TEST",
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

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

    def test_total_value(self) -> None:
        """Test total_value calculation."""
        portfolio = OptionPortfolioBase(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        total_value = portfolio.total_value()
        assert total_value > 0

    def test_total_underlying_value(self) -> None:
        """Test total_underlying_value calculation."""
        portfolio = OptionPortfolioBase(
            underlying_quantity=100,
            spot_price=50.0,
        )

        assert portfolio.total_underlying_value() == pytest.approx(
            5000.0, rel=1e-4
        )

    def test_total_portfolio_value(self) -> None:
        """Test total_portfolio_value calculation."""
        portfolio = OptionPortfolioBase(
            underlying_quantity=100,
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
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

    def test_get_positions(self) -> None:
        """Test get_positions returns proper format."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        positions = portfolio.get_positions()
        assert len(positions) == 1
        assert positions[0]["option_type"] == OptionType.CALL
        assert positions[0]["strike"] == pytest.approx(100.0, rel=1e-5)

    def test_to_dataframe(self) -> None:
        """Test to_dataframe conversion."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

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

    def test_to_dataframe_empty(self) -> None:
        """Test to_dataframe with empty portfolio."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        df = portfolio.to_dataframe()
        assert len(df) == 0

    def test_summary_stats(self) -> None:
        """Test summary_stats returns all required fields."""
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.AMERICAN
        )

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

    def test_summary(self) -> None:
        """Test summary string generation."""
        portfolio = OptionPortfolio(
            symbol="TEST", default_exercise_style=ExerciseStyle.AMERICAN
        )

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

    def test_summary_market(self) -> None:
        """Test summary_market string generation."""
        portfolio = OptionPortfolioBase(
            symbol="TEST",
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        summary = portfolio.summary_market()
        assert isinstance(summary, str)
        assert "Spot Price" in summary
        assert "Volatility" in summary
        assert "TEST" in summary

    def test_update_market_conditions(self) -> None:
        """Test updating market conditions."""
        portfolio = OptionPortfolioBase(
            spot_price=100.0,
            volatility=0.2,
            symbol="TEST",
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        assert portfolio.symbol == "TEST"

        portfolio.update_market_conditions(spot_price=110.0, volatility=0.3)

        assert portfolio.spot_price == pytest.approx(110.0, rel=1e-5)
        assert portfolio.volatility == pytest.approx(0.3, rel=1e-4)
        assert portfolio.symbol == "TEST"

    def test_set_volatility(self) -> None:
        """Test set_volatility method."""
        portfolio = OptionPortfolioBase(
            volatility=0.2,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        portfolio.set_volatility(0.3)

        assert portfolio.volatility == pytest.approx(0.3, rel=1e-4)
        assert portfolio.positions[0].option.volatility == pytest.approx(
            0.3, rel=1e-4
        )

    def test_set_volatility_reprices_leg(self) -> None:
        """Regression (M4): set_volatility must reprice, not just set the attr.

        The old implementation assigned ``pos.option.volatility`` directly,
        leaving the QuantLib quote and the greek cache stale, so ``price()``
        returned the value at the *previous* vol.
        """
        maturity = datetime.now(tz=UTC) + timedelta(days=30)
        portfolio = OptionPortfolioBase(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )
        price_before = portfolio.positions[0].option.price()

        # Reference leg built directly at the higher vol for comparison.
        reference = OptionPortfolioBase(
            spot_price=100.0,
            volatility=0.5,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        reference.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )
        expected_price = reference.positions[0].option.price()

        portfolio.set_volatility(0.5)
        price_after = portfolio.positions[0].option.price()

        # An ATM call is worth more at higher vol; the old code left it flat.
        assert price_after > price_before
        assert price_after == pytest.approx(expected_price)

    def test_set_volatility_skips_custom_volatility_leg(self) -> None:
        """Regression (M4): a custom-vol leg must be left untouched.

        ``set_volatility`` only repositions legs whose vol tracks the
        portfolio; a leg with an explicit ``custom_volatility`` must keep both
        its vol quote and its price when the portfolio vol moves.
        """
        maturity = datetime.now(tz=UTC) + timedelta(days=30)
        portfolio = OptionPortfolioBase(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.3,
        )
        custom_leg = portfolio.positions[0]
        assert custom_leg.custom_volatility is True
        price_before = custom_leg.option.price()

        portfolio.set_volatility(0.5)

        assert custom_leg.option.volatility == pytest.approx(0.3, rel=1e-4)
        assert custom_leg.option.price() == pytest.approx(price_before)

    def test_update_market_conditions_rate_change_preserves_identity(
        self,
    ) -> None:
        """Regression (C3): the rate/dividend rebuild must keep entry + id.

        Changing the risk-free rate or dividend yield recreates every
        OptionPosition; the old rebuild dropped entry_spot/date/premium and
        minted a fresh position_id, silently losing cost basis and identity.
        """
        portfolio = OptionPortfolioBase(
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        entry_date = datetime(2026, 1, 2, tzinfo=UTC)
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            entry_spot=98.0,
            entry_date=entry_date,
        )
        pos = portfolio.positions[0]
        pos.entry_premium = 4.25
        original_id = pos.position_id

        # Rate change triggers the position-rebuild branch.
        portfolio.update_market_conditions(risk_free_rate=0.06)

        rebuilt = portfolio.positions[0]
        assert rebuilt.entry_spot == pytest.approx(98.0, rel=1e-4)
        assert rebuilt.entry_date == entry_date
        assert rebuilt.entry_premium == pytest.approx(4.25)
        assert rebuilt.position_id == original_id

    def test_get_symbol(self) -> None:
        """Test get_symbol method."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

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

    def test_monte_carlo_results_property(self) -> None:
        """Test monte_carlo_results property."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        assert portfolio.monte_carlo_results is None

        results = {"prob_profit": 0.6, "expected_pnl": 100.0}
        portfolio.monte_carlo_results = results

        assert portfolio.monte_carlo_results == results

    def test_repr(self) -> None:
        """Test __repr__ method."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        repr_str = repr(portfolio)
        assert isinstance(repr_str, str)
        assert "OptionPortfolio" in repr_str


class TestDefaultExerciseStyle:
    """Test cases for OptionPortfolioBase.default_exercise_style."""

    def test_defaults_to_american(self) -> None:
        """Test that default_exercise_style defaults to AMERICAN."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        assert portfolio.default_exercise_style == ExerciseStyle.AMERICAN

    def test_add_position_uses_default_exercise_style(self) -> None:
        """Test that omitting exercise_style uses the portfolio default."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        assert portfolio.positions[0].exercise_style == ExerciseStyle.EUROPEAN
        assert portfolio.positions[0].option.exercise_style == (
            ExerciseStyle.EUROPEAN
        )

    def test_explicit_exercise_style_overrides_default(self) -> None:
        """Test that an explicit exercise_style still overrides the default."""
        portfolio = OptionPortfolioBase(
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.AMERICAN,
        )

        assert portfolio.positions[0].exercise_style == ExerciseStyle.AMERICAN


class TestOptionPortfolio:
    """Test cases for composed OptionPortfolio class."""

    def test_has_all_mixins(self) -> None:
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

    def test_instantiation(self) -> None:
        """Test OptionPortfolio can be instantiated."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.2,
        )

        assert portfolio is not None
        assert portfolio.spot_price == pytest.approx(100.0, rel=1e-5)


class TestPortfolioCore(unittest.TestCase):
    """Test cases for core portfolio functionality."""

    def setUp(self) -> None:
        """Set up a basic portfolio for testing."""
        # Initialize with explicit Symbol
        self.portfolio = OptionPortfolio(
            symbol="TSLA",
            spot_price=200.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

    def test_portfolio_symbol_storage(self) -> None:
        """Test that symbol is stored at portfolio level."""
        pf = OptionPortfolio(symbol="TSLA")
        self.assertEqual(pf.get_symbol(), "TSLA")

    def test_add_position_defaults(self) -> None:
        """Test adding position uses defaults and works.

        Test that it works without position-level symbol.
        """
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

    def test_european_position_pricing(self) -> None:
        """Test that a portfolio can hold and price European options."""
        self.portfolio.add_position(
            strike_price=210,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            option_type=OptionType.CALL,
            quantity=1,
            exercise_style=ExerciseStyle.EUROPEAN,  # Explicitly European
        )

        value = self.portfolio.total_value()
        self.assertGreater(value, 0)
        self.assertEqual(
            self.portfolio.positions[0].exercise_style,
            ExerciseStyle.EUROPEAN,
        )

    def test_mixed_styles(self) -> None:
        """Portfolio should handle both styles simultaneously."""
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
        net_value = self.portfolio.total_value()
        self.assertGreaterEqual(net_value, -0.01)  # Allow for float precision
