"""Tests for deltadewa.analysis.base module."""

import pytest

from deltadewa.analysis.base import PortfolioAnalyzer, PortfolioAnalyzerBase
from deltadewa.portfolio.core import OptionPortfolio


class TestPortfolioAnalyzerBase:
    """Test cases for PortfolioAnalyzerBase class."""

    def test_initialization(self) -> None:
        """Test PortfolioAnalyzerBase can be instantiated."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )

        analyzer = PortfolioAnalyzerBase(portfolio)

        assert analyzer is not None
        assert analyzer.portfolio is portfolio
        assert analyzer.portfolio.spot_price == pytest.approx(100.0, rel=1e-5)

    def test_portfolio_analyzer_composition(self) -> None:
        """Test PortfolioAnalyzer includes all mixins."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.2,
            risk_free_rate=0.05,
            dividend_yield=0.0,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        # Check base functionality
        assert hasattr(analyzer, "portfolio")
        assert analyzer.portfolio is portfolio

        # Check mixin methods are available
        assert hasattr(analyzer, "classify_maturity_bucket")
        assert hasattr(analyzer, "add_maturity_buckets")
        assert hasattr(analyzer, "calculate_carry_metrics")
        assert hasattr(analyzer, "analyze_risk_concentration")
        assert hasattr(analyzer, "calculate_hedge_actions")
        assert hasattr(analyzer, "scenario_grid")
        assert hasattr(analyzer, "scenario_grid_spot_vol")
        assert hasattr(analyzer, "format_risk_summary")
        assert hasattr(analyzer, "generate_insights")

    def test_empty_portfolio(self) -> None:
        """Test analyzer with empty portfolio."""
        portfolio = OptionPortfolio()
        analyzer = PortfolioAnalyzer(portfolio)

        # Should not raise errors on empty portfolio
        carry_metrics = analyzer.calculate_carry_metrics()
        assert carry_metrics["total_theta_daily"] == pytest.approx(
            0.0, rel=1e-8
        )

        concentration = analyzer.analyze_risk_concentration()
        assert len(concentration["by_strike"]) == 0
