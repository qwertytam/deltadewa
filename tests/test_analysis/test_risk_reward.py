"""Tests for deltadewa.analysis.risk_reward module."""

from datetime import UTC, datetime, timedelta

import numpy as np

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio


class TestRiskRewardMixin:
    """Test cases for RiskRewardMixin."""

    def test_risk_reward_analysis_basic(self):
        """Test basic risk_reward_analysis method."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        analysis = analyzer.risk_reward_analysis(num_simulations=100)

        # Verify all expected keys exist
        assert "net_debit" in analysis
        assert "max_loss_options" in analysis
        assert "max_profit_options" in analysis
        assert "breakeven_options" in analysis
        assert "max_loss_total" in analysis
        assert "max_profit_total" in analysis
        assert "breakeven_total" in analysis
        assert "prob_profit" in analysis
        assert "expected_pnl" in analysis

        # Verify structure of nested dicts
        assert "max_loss" in analysis["max_loss_options"]
        assert "spot_at_max_loss" in analysis["max_loss_options"]
        assert "is_unlimited" in analysis["max_loss_options"]

        assert "max_profit" in analysis["max_profit_options"]
        assert "spot_at_max_profit" in analysis["max_profit_options"]
        assert "is_unlimited" in analysis["max_profit_options"]

    def test_risk_reward_analysis_long_call(self):
        """Test risk_reward_analysis with long call strategy."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        analysis = analyzer.risk_reward_analysis(num_simulations=100)

        # Long call should have unlimited profit
        assert analysis["max_profit_options"]["is_unlimited"] is True
        # Long call should have limited loss (premium paid)
        assert analysis["max_loss_options"]["is_unlimited"] is False
        assert analysis["max_loss_options"]["max_loss"] < 0

    def test_risk_reward_analysis_short_call(self):
        """Test risk_reward_analysis with short call strategy."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=110.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        analysis = analyzer.risk_reward_analysis(num_simulations=100)

        # Short call should have unlimited loss
        assert analysis["max_loss_options"]["is_unlimited"] is True
        # Short call should have limited profit (premium received)
        assert analysis["max_profit_options"]["is_unlimited"] is False
        assert analysis["max_profit_options"]["max_profit"] > 0

    def test_risk_reward_analysis_iron_condor(self):
        """Test risk_reward_analysis with iron condor strategy."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
        )

        maturity = datetime.now(tz=UTC) + timedelta(days=30)
        # Iron condor: buy put spread, buy call spread
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.PUT,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=-1,
            option_type=OptionType.PUT,
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=maturity,
            quantity=-1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        analysis = analyzer.risk_reward_analysis(num_simulations=100)

        # Just verify the analysis structure is valid
        assert "max_loss_options" in analysis
        assert "max_profit_options" in analysis
        assert "breakeven_options" in analysis
        assert isinstance(analysis["breakeven_options"], list)

    def test_risk_reward_analysis_empty_portfolio(self):
        """Test risk_reward_analysis with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)
        analyzer = PortfolioAnalyzer(portfolio)

        analysis = analyzer.risk_reward_analysis(num_simulations=100)

        # Empty portfolio should still return valid structure
        assert "net_debit" in analysis
        assert "max_loss_options" in analysis
        assert "prob_profit" in analysis

    def test_format_risk_reward_summary_basic(self):
        """Test format_risk_reward_summary returns string."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        summary = analyzer.format_risk_reward_summary()

        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "PORTFOLIO RISK/REWARD ANALYSIS" in summary
        assert "CAPITAL REQUIREMENTS" in summary
        assert "OPTIONS ONLY RISK/REWARD" in summary
        assert "PROBABILITY ANALYSIS" in summary

    def test_format_risk_reward_summary_sections(self):
        """Test format_risk_reward_summary contains expected sections."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            underlying_quantity=100.0,  # Add underlying for total section
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        summary = analyzer.format_risk_reward_summary()

        assert "Max Loss:" in summary
        assert "Max Profit:" in summary
        assert "Breakeven Points:" in summary
        assert "Chance of Profit:" in summary
        assert "Expected Value:" in summary
        # Should have total portfolio section when underlying exists
        assert "TOTAL PORTFOLIO RISK/REWARD" in summary

    def test_format_risk_reward_summary_empty_portfolio(self):
        """Test format_risk_reward_summary with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)
        analyzer = PortfolioAnalyzer(portfolio)

        summary = analyzer.format_risk_reward_summary()

        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "PORTFOLIO RISK/REWARD ANALYSIS" in summary

    def test_print_risk_reward_summary_no_error(self):
        """Test print_risk_reward_summary doesn't raise exceptions."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        # Should not raise any exceptions
        try:
            analyzer.print_risk_reward_summary()
        except Exception as e:  # pylint: disable=broad-exception-caught
            assert False, f"print_risk_reward_summary raised {e}"

    def test_risk_reward_analysis_with_spot_range(self):
        """Test risk_reward_analysis with custom spot_range."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        spot_range = np.linspace(50, 150, 100)
        analysis = analyzer.risk_reward_analysis(
            spot_range=spot_range,
            num_simulations=100,
        )

        # Should still return valid analysis
        assert "net_debit" in analysis
        assert "max_loss_options" in analysis
        assert "max_profit_options" in analysis
