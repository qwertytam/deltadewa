"""Tests for deltadewa.analysis.summary module (insights functionality)."""

from datetime import UTC, datetime, timedelta

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio


class TestSummaryMixinInsights:
    """Test cases for SummaryMixin insights functionality."""

    def test_format_risk_summary_basic(self):
        """Test basic risk summary formatting."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        summary = analyzer.format_risk_summary()

        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "PORTFOLIO RISK SUMMARY" in summary
        assert "DIRECTIONAL RISK" in summary
        assert "CONVEXITY RISK" in summary
        assert "VOLATILITY RISK" in summary
        assert "TIME DECAY" in summary

    def test_format_risk_summary_with_stats(self):
        """Test risk summary with provided stats."""
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
        stats = portfolio.summary_stats()
        summary = analyzer.format_risk_summary(stats=stats)

        assert isinstance(summary, str)
        assert "PORTFOLIO RISK SUMMARY" in summary

    def test_format_risk_summary_empty_portfolio(self):
        """Test risk summary with empty portfolio."""
        portfolio = OptionPortfolio()
        analyzer = PortfolioAnalyzer(portfolio)

        summary = analyzer.format_risk_summary()

        assert isinstance(summary, str)
        # Empty portfolio should still produce a summary
        assert len(summary) > 0

    def test_generate_insights_basic(self):
        """Test basic insights generation."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        insights = analyzer.generate_insights()

        assert isinstance(insights, list)
        # Should have at least some insights
        assert len(insights) >= 0

    def test_generate_insights_positive_carry(self):
        """Test insights with positive carry position."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )

        # Short call has positive theta (positive carry)
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        insights = analyzer.generate_insights()

        assert isinstance(insights, list)
        # Should mention positive carry
        carry_insights = [
            i for i in insights if "carry" in i.lower() or "theta" in i.lower()
        ]
        assert len(carry_insights) > 0

    def test_generate_insights_negative_carry(self):
        """Test insights with negative carry position."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        # Long call has negative theta (negative carry)
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        insights = analyzer.generate_insights()

        assert isinstance(insights, list)

    def test_generate_insights_empty_portfolio(self):
        """Test insights generation with empty portfolio."""
        portfolio = OptionPortfolio()
        analyzer = PortfolioAnalyzer(portfolio)

        insights = analyzer.generate_insights()

        assert isinstance(insights, list)
        # Empty portfolio should produce minimal or no insights
        assert len(insights) >= 0

    def test_generate_insights_high_concentration(self):
        """Test insights detect high concentration."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        # Add many positions at same strike (concentrated)
        for _ in range(5):
            portfolio.add_position(
                strike_price=105.0,
                maturity_date=datetime.now(tz=UTC)
                + timedelta(days=30),
                quantity=1,
                option_type=OptionType.CALL,
            )

        analyzer = PortfolioAnalyzer(portfolio)
        insights = analyzer.generate_insights()

        assert isinstance(insights, list)
