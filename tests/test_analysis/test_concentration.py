"""Tests for deltadewa.analysis.recommendations module.

(concentration functionality).
"""

from datetime import UTC, datetime, timedelta

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio

# ruff: noqa: S101


class TestRecommendationsMixinConcentration:
    """Test cases for RecommendationsMixin concentration functionality."""

    def test_analyze_risk_concentration_empty(self) -> None:
        """Test concentration analysis on empty portfolio."""
        portfolio = OptionPortfolio()
        analyzer = PortfolioAnalyzer(portfolio)

        result = analyzer.analyze_risk_concentration()

        assert "by_strike" in result
        assert "by_maturity" in result
        assert "concentration_scores" in result
        assert len(result["by_strike"]) == 0
        assert len(result["by_maturity"]) == 0
        assert len(result["concentration_scores"]) == 0

    def test_analyze_risk_concentration_with_positions(self) -> None:
        """Test concentration analysis with positions."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        # Add positions at same strike (concentrated)
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=5,
            option_type=OptionType.CALL,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=60),
            quantity=3,
            option_type=OptionType.PUT,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.analyze_risk_concentration(metrics=["delta", "gamma"])

        # Check structure
        assert "by_strike" in result
        assert "by_maturity" in result
        assert "concentration_scores" in result

        # Should have concentration data for delta and gamma
        if "delta" in result["by_strike"]:
            assert isinstance(result["by_strike"]["delta"], list)
            assert len(result["by_strike"]["delta"]) > 0
            assert "strike" in result["by_strike"]["delta"][0]
            assert "value" in result["by_strike"]["delta"][0]
            assert "percentage" in result["by_strike"]["delta"][0]

    def test_analyze_risk_concentration_custom_metrics(self) -> None:
        """Test concentration analysis with custom metrics."""
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
        result = analyzer.analyze_risk_concentration(metrics=["vega", "theta"])

        # Should analyze vega and theta
        assert "by_strike" in result
        assert "by_maturity" in result

    def test_analyze_risk_concentration_top_n(self) -> None:
        """Test top_n parameter limits results."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        # Add positions at different strikes
        for strike in [100, 105, 110, 115, 120]:
            portfolio.add_position(
                strike_price=float(strike),
                maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
                quantity=1,
                option_type=OptionType.CALL,
            )

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.analyze_risk_concentration(metrics=["delta"], top_n=2)

        # Should only return top 2
        if "delta" in result["by_strike"]:
            assert len(result["by_strike"]["delta"]) <= 2

    def test_empty_concentration(self) -> None:
        """Test _empty_concentration returns correct structure."""
        portfolio = OptionPortfolio()
        analyzer = PortfolioAnalyzer(portfolio)

        # pylint: disable=protected-access
        result = analyzer._empty_concentration()

        assert result == {
            "by_strike": {},
            "by_maturity": {},
            "concentration_scores": {},
        }
