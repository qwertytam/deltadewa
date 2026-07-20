"""Tests for deltadewa.analysis.risk_reward module."""

from datetime import UTC, datetime, timedelta

import numpy as np

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio


class TestRiskRewardMixin:
    """Test cases for RiskRewardMixin."""

    def test_risk_reward_analysis_basic(self) -> None:
        """Test basic risk_reward_analysis method."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            default_exercise_style=ExerciseStyle.AMERICAN,
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

    def test_risk_reward_analysis_long_call(self) -> None:
        """Test risk_reward_analysis with long call strategy."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
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

    def test_risk_reward_analysis_short_call(self) -> None:
        """Test risk_reward_analysis with short call strategy."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
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

    def test_risk_reward_analysis_iron_condor(self) -> None:
        """Test risk_reward_analysis with iron condor strategy."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
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

    def test_risk_reward_analysis_empty_portfolio(self) -> None:
        """Test risk_reward_analysis with empty portfolio."""
        portfolio = OptionPortfolio(
            spot_price=100.0, default_exercise_style=ExerciseStyle.AMERICAN
        )
        analyzer = PortfolioAnalyzer(portfolio)

        analysis = analyzer.risk_reward_analysis(num_simulations=100)

        # Empty portfolio should still return valid structure
        assert "net_debit" in analysis
        assert "max_loss_options" in analysis
        assert "prob_profit" in analysis

    def test_format_risk_reward_summary_basic(self) -> None:
        """Test format_risk_reward_summary returns string."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
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

    def test_format_risk_reward_summary_sections(self) -> None:
        """Test format_risk_reward_summary contains expected sections."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            underlying_quantity=100.0,  # Add underlying for total section
            default_exercise_style=ExerciseStyle.AMERICAN,
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

    def test_format_risk_reward_summary_empty_portfolio(self) -> None:
        """Test format_risk_reward_summary with empty portfolio."""
        portfolio = OptionPortfolio(
            spot_price=100.0, default_exercise_style=ExerciseStyle.AMERICAN
        )
        analyzer = PortfolioAnalyzer(portfolio)

        summary = analyzer.format_risk_reward_summary()

        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "PORTFOLIO RISK/REWARD ANALYSIS" in summary

    def test_print_risk_reward_summary_no_error(self) -> None:
        """Test print_risk_reward_summary doesn't raise exceptions."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
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
            raise AssertionError(
                False,
                f"print_risk_reward_summary raised {e}",
            ) from e

    def test_risk_reward_analysis_with_spot_range(self) -> None:
        """Test risk_reward_analysis with custom spot_range."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
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


class TestFormatRiskRewardSummaryCharacterization:
    """Golden-string tests pinning format_risk_reward_summary's exact
    output, so its case-dispatch refactor can be verified as
    output-identical. `risk_reward_analysis` is deterministic (Monte
    Carlo uses `random_seed=42` by default), so these compare full
    strings rather than substrings.
    """

    def test_long_call_options_only(self) -> None:
        """Bounded loss (with % of net debit), unlimited profit, no
        total section: net_debit > 0 so the loss line gets a pct
        suffix; profit is unlimited so no risk/reward ratio line.
        """
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )
        analyzer = PortfolioAnalyzer(portfolio)

        summary = analyzer.format_risk_reward_summary()

        expected = "\n".join(
            [
                "=" * 80,
                "PORTFOLIO RISK/REWARD ANALYSIS",
                "=" * 80,
                "",
                "CAPITAL REQUIREMENTS:",
                "  Net Debit: $363.32 (capital required to implement)",
                "",
                "OPTIONS ONLY RISK/REWARD:",
                "  Max Loss: $363.32 (100.0% of net debit)",
                "    └─ Occurs at spot price: $0.01",
                "  Max Profit: UNLIMITED",
                "  Breakeven Points: $103.69",
                "",
                "PROBABILITY ANALYSIS:",
                "  Chance of Profit: 33.7% (risk-neutral drift)",
                "  Expected Value: $-2.73 (probabilistic weighted average)",
                "",
                "=" * 80,
            ],
        )
        assert summary == expected

    def test_naked_short_call_net_credit(self) -> None:
        """Unlimited loss ('naked short positions'), bounded profit
        with no pct suffix since net_debit < 0 (net credit).
        """
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )
        analyzer = PortfolioAnalyzer(portfolio)

        summary = analyzer.format_risk_reward_summary()

        expected = "\n".join(
            [
                "=" * 80,
                "PORTFOLIO RISK/REWARD ANALYSIS",
                "=" * 80,
                "",
                "CAPITAL REQUIREMENTS:",
                "  Net Credit: $66.74 (capital received)",
                "",
                "OPTIONS ONLY RISK/REWARD:",
                "  Max Loss: UNLIMITED (naked short positions)",
                "  Max Profit: $66.74",
                "    └─ Occurs at spot price: $0.01",
                "  Breakeven Points: $113.72",
                "",
                "PROBABILITY ANALYSIS:",
                "  Chance of Profit: 88.0% (risk-neutral drift)",
                "  Expected Value: $-0.88 (probabilistic weighted average)",
                "",
                "=" * 80,
            ],
        )
        assert summary == expected

    def test_covered_call_with_long_underlying(self) -> None:
        """Underlying present: exercises both total-section unlimited
        labels together. The short call makes max_loss_total unlimited
        via the naked-short-call check (not the underlying sign) yet
        the printed label is still 'short underlying position' —
        that's an existing quirk of the current code, pinned as-is.
        max_profit_total is unlimited via the long underlying position.
        """
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            underlying_quantity=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        maturity = datetime.now(tz=UTC) + timedelta(days=30)
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.PUT,
        )
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=maturity,
            quantity=-1,
            option_type=OptionType.CALL,
        )
        analyzer = PortfolioAnalyzer(portfolio)

        summary = analyzer.format_risk_reward_summary()

        expected = "\n".join(
            [
                "=" * 80,
                "PORTFOLIO RISK/REWARD ANALYSIS",
                "=" * 80,
                "",
                "CAPITAL REQUIREMENTS:",
                "  Net Debit: $65.27 (capital required to implement)",
                "",
                "OPTIONS ONLY RISK/REWARD:",
                "  Max Loss: UNLIMITED (naked short positions)",
                "  Max Profit: $9,433.73 (14452.8% return on net debit)",
                "    └─ Occurs at spot price: $0.01",
                "  Breakeven Points: $97.00",
                "",
                "TOTAL PORTFOLIO RISK/REWARD (Options + Underlying):",
                "  Max Loss: UNLIMITED (short underlying position)",
                "  Max Profit: UNLIMITED (long underlying position)",
                "    └─ Profit increases with spot price",
                "  Breakeven Points: $103.69",
                "",
                "PROBABILITY ANALYSIS:",
                "  Chance of Profit: 46.5% (risk-neutral drift)",
                "  Expected Value: $35.49 (probabilistic weighted average)",
                "",
                "=" * 80,
            ],
        )
        assert summary == expected

    def test_short_underlying_only_quirk_case(self) -> None:
        """Short underlying alone: max_loss_total is unlimited, so
        `portfolio_value` (used for the total section's '% of
        portfolio value' suffixes) is never assigned — max_profit_total
        is bounded but its line has no pct suffix as a result. This is
        an existing quirk of the current code, pinned as-is.
        """
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            underlying_quantity=-50.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        analyzer = PortfolioAnalyzer(portfolio)

        summary = analyzer.format_risk_reward_summary()

        expected = "\n".join(
            [
                "=" * 80,
                "PORTFOLIO RISK/REWARD ANALYSIS",
                "=" * 80,
                "",
                "CAPITAL REQUIREMENTS:",
                "  Net Credit: $0.00 (capital received)",
                "",
                "OPTIONS ONLY RISK/REWARD:",
                "  Max Loss: $-0.00",
                "    └─ Occurs at spot price: $0.01",
                "  Max Profit: $0.00",
                "    └─ Occurs at spot price: $0.01",
                "  Breakeven Points: None identified",
                "",
                "TOTAL PORTFOLIO RISK/REWARD (Options + Underlying):",
                "  Max Loss: UNLIMITED (short underlying position)",
                "  Max Profit: $4,999.50",
                "    └─ Occurs at spot price: $0.01",
                "  Breakeven Points: $100.00, $100.34",
                "",
                "PROBABILITY ANALYSIS:",
                "  Chance of Profit: 50.3% (risk-neutral drift)",
                "  Expected Value: $-16.40 (probabilistic weighted average)",
                "",
                "=" * 80,
            ],
        )
        assert summary == expected

    def test_protective_put_with_long_underlying_and_ratio(self) -> None:
        """Long underlying with a protective put: max_loss_total is
        bounded (so the '% of portfolio value' suffix *does* show on
        the loss line here), max_profit_total is unlimited via the
        long underlying. Options loss/profit are both bounded, which
        also exercises the risk/reward ratio section.
        """
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            underlying_quantity=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
        )
        analyzer = PortfolioAnalyzer(portfolio)

        summary = analyzer.format_risk_reward_summary()

        expected = "\n".join(
            [
                "=" * 80,
                "PORTFOLIO RISK/REWARD ANALYSIS",
                "=" * 80,
                "",
                "CAPITAL REQUIREMENTS:",
                "  Net Debit: $132.01 (capital required to implement)",
                "",
                "OPTIONS ONLY RISK/REWARD:",
                "  Max Loss: $132.01 (100.0% of net debit)",
                "    └─ Occurs at spot price: $97.00",
                "  Max Profit: $9,366.99 (7095.7% return on net debit)",
                "    └─ Occurs at spot price: $0.01",
                "  Breakeven Points: $97.00",
                "",
                "TOTAL PORTFOLIO RISK/REWARD (Options + Underlying):",
                "  Max Loss: $632.01 (6.2% of portfolio value)",
                "    └─ Occurs at spot price: $0.01",
                "  Max Profit: UNLIMITED (long underlying position)",
                "    └─ Profit increases with spot price",
                "  Breakeven Points: $103.69",
                "",
                "PROBABILITY ANALYSIS:",
                "  Chance of Profit: 43.6% (risk-neutral drift)",
                "  Expected Value: $36.37 (probabilistic weighted average)",
                "",
                "RISK/REWARD RATIO: 70.96:1 (max profit to max loss)",
                "=" * 80,
            ],
        )
        assert summary == expected

    def test_call_spread_net_credit_both_unlimited(self) -> None:
        """Short-strike-lower / long-strike-higher call spread: the
        naked short leg makes both loss and profit read as unlimited
        (profit unlimited comes from the long call leg), net_debit < 0.
        """
        maturity = datetime.now(tz=UTC) + timedelta(days=30)
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=maturity,
            quantity=-1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=120.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )
        analyzer = PortfolioAnalyzer(portfolio)

        summary = analyzer.format_risk_reward_summary()

        expected = "\n".join(
            [
                "=" * 80,
                "PORTFOLIO RISK/REWARD ANALYSIS",
                "=" * 80,
                "",
                "CAPITAL REQUIREMENTS:",
                "  Net Credit: $60.16 (capital received)",
                "",
                "OPTIONS ONLY RISK/REWARD:",
                "  Max Loss: UNLIMITED (naked short positions)",
                "  Max Profit: UNLIMITED",
                "  Breakeven Points: $113.72",
                "",
                "PROBABILITY ANALYSIS:",
                "  Chance of Profit: 88.2% (risk-neutral drift)",
                "  Expected Value: $2.49 (probabilistic weighted average)",
                "",
                "=" * 80,
            ],
        )
        assert summary == expected

    def test_empty_portfolio(self) -> None:
        """Empty portfolio: net_debit is 0 (credit branch), no
        breakevens, no total section, no ratio section.
        """
        portfolio = OptionPortfolio(
            spot_price=100.0, default_exercise_style=ExerciseStyle.AMERICAN
        )
        analyzer = PortfolioAnalyzer(portfolio)

        summary = analyzer.format_risk_reward_summary()

        expected = "\n".join(
            [
                "=" * 80,
                "PORTFOLIO RISK/REWARD ANALYSIS",
                "=" * 80,
                "",
                "CAPITAL REQUIREMENTS:",
                "  Net Credit: $0.00 (capital received)",
                "",
                "OPTIONS ONLY RISK/REWARD:",
                "  Max Loss: $-0.00",
                "    └─ Occurs at spot price: $0.01",
                "  Max Profit: $0.00",
                "    └─ Occurs at spot price: $0.01",
                "  Breakeven Points: None identified",
                "",
                "PROBABILITY ANALYSIS:",
                "  Chance of Profit: 100.0% (risk-neutral drift)",
                "  Expected Value: $0.00 (probabilistic weighted average)",
                "",
                "=" * 80,
            ],
        )
        assert summary == expected
