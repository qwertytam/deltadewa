"""Tests for deltadewa.analysis.recommendations module (hedge functionality)."""

from datetime import UTC, datetime, timedelta

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio

# ruff: noqa: S101


class TestRecommendationsMixinHedge:
    """Test cases for RecommendationsMixin hedge functionality."""

    def test_calculate_hedge_actions_basic(self) -> None:
        """Test basic hedge action calculation."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )

        # Add a long call
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_hedge_actions(target_hedge_ratio=50.0)

        # Check structure
        assert "current_state" in result
        assert "target_state" in result
        assert "underlying_trade" in result
        assert "underlying_cost" in result

        # Check current state
        assert "portfolio_delta" in result["current_state"]
        assert "notional_position" in result["current_state"]
        assert "hedge_ratio" in result["current_state"]

        # Check target state
        assert "target_hedge_ratio" in result["target_state"]
        assert "target_portfolio_delta" in result["target_state"]
        assert "delta_change_needed" in result["target_state"]

        # Check underlying trade
        assert "action" in result["underlying_trade"]
        assert "shares" in result["underlying_trade"]
        assert "cost" in result["underlying_trade"]

    def test_calculate_hedge_actions_without_alternatives(self) -> None:
        """Test hedge actions without option alternatives."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_hedge_actions(
            target_hedge_ratio=50.0,
            include_option_alternatives=False,
        )

        assert "option_alternatives" in result
        assert result["option_alternatives"] == []

    def test_calculate_hedge_actions_with_alternatives(self) -> None:
        """Test hedge actions with option alternatives."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        # Add positions
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_hedge_actions(
            target_hedge_ratio=50.0,
            include_option_alternatives=True,
            max_alternatives=5,
        )

        assert "option_alternatives" in result
        # Should have alternatives since we have meaningful delta
        if result["target_state"]["delta_change_needed"] >= 1:
            assert isinstance(result["option_alternatives"], list)

    def test_calculate_option_alternatives(self) -> None:
        """Test _calculate_option_alternatives method."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        # pylint: disable=protected-access
        alternatives = analyzer._calculate_option_alternatives(
            delta_change_needed=-10.0,
            max_alternatives=10,
        )

        assert isinstance(alternatives, list)

        if len(alternatives) > 0:
            alt = alternatives[0]
            assert "action" in alt
            assert "option_type" in alt
            assert "strike" in alt
            assert "maturity" in alt
            assert "delta_per_contract" in alt
            assert "contracts_needed" in alt
            assert "price" in alt
            assert "cost" in alt

    def test_calculate_option_alternatives_max_limit(self) -> None:
        """Test max_alternatives parameter."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        # Add multiple positions
        for strike in [95, 100, 105, 110, 115]:
            portfolio.add_position(
                strike_price=float(strike),
                maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
                quantity=1,
                option_type=OptionType.CALL,
            )

        analyzer = PortfolioAnalyzer(portfolio)
        # pylint: disable=protected-access
        alternatives = analyzer._calculate_option_alternatives(
            delta_change_needed=-10.0,
            max_alternatives=3,
        )

        # Should return at most 3 alternatives
        assert len(alternatives) <= 3
