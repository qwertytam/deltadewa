"""Tests for deltadewa.analysis.carry module."""

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.carry import carry_vs_budget
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio


class TestCarryMixin:
    """Test cases for CarryMixin."""

    def test_calculate_carry_metrics_empty(self) -> None:
        """Test carry metrics on empty portfolio."""
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.AMERICAN
        )
        analyzer = PortfolioAnalyzer(portfolio)

        metrics = analyzer.calculate_carry_metrics()

        assert metrics["total_theta_daily"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["total_theta_weekly"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["total_theta_monthly"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["total_theta_annual"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["is_positive_carry"] is False
        assert len(metrics["theta_by_bucket"]) == 0

    def test_calculate_carry_metrics_with_position(self) -> None:
        """Test carry metrics with a position."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # Add a short call (should have positive theta)
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        metrics = analyzer.calculate_carry_metrics()

        # Check structure
        assert "total_theta_daily" in metrics
        assert "total_theta_weekly" in metrics
        assert "total_theta_monthly" in metrics
        assert "total_theta_annual" in metrics
        assert "theta_by_bucket" in metrics
        assert "theta_by_type" in metrics
        assert "covered_call_theta" in metrics
        assert "is_positive_carry" in metrics

        # Short call should have positive theta
        assert metrics["covered_call_theta"] > 0
        assert metrics["is_positive_carry"]

    def test_empty_carry_metrics(self) -> None:
        """Test _empty_carry_metrics returns correct structure."""
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.AMERICAN
        )
        analyzer = PortfolioAnalyzer(portfolio)

        # pylint: disable=protected-access
        metrics = analyzer._empty_carry_metrics()

        assert metrics["total_theta_daily"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["total_theta_weekly"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["total_theta_monthly"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["total_theta_annual"] == pytest.approx(0.0, abs=1e-9)
        assert not metrics["theta_by_bucket"]
        assert not metrics["theta_by_type"]
        assert metrics["covered_call_theta"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["long_call_theta"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["hedge_put_theta"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["short_put_theta"] == pytest.approx(0.0, abs=1e-9)
        assert metrics["net_carry"] == pytest.approx(0.0, abs=1e-9)
        assert not metrics["carry_efficiency"]
        assert metrics["is_positive_carry"] is False

    def test_create_theta_summary_table(self) -> None:
        """Test theta summary table creation."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # Add positions
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,  # Short call
            option_type=OptionType.CALL,
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,  # Long put
            option_type=OptionType.PUT,
        )

        analyzer = PortfolioAnalyzer(portfolio)
        summary_table = analyzer.create_theta_summary_table()

        # Check it's a DataFrame
        assert hasattr(summary_table, "index")
        assert hasattr(summary_table, "columns")

        # Check columns exist
        assert "daily" in summary_table.columns
        assert "weekly" in summary_table.columns
        assert "monthly" in summary_table.columns
        assert "annual" in summary_table.columns

        # Check we have at least NET row
        assert "NET" in [idx[0] for idx in summary_table.index]

    def test_create_theta_summary_table_empty(self) -> None:
        """Test theta summary table with empty portfolio."""
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.AMERICAN
        )
        analyzer = PortfolioAnalyzer(portfolio)

        summary_table = analyzer.create_theta_summary_table()

        # Should still have NET row even when empty
        assert not summary_table.empty
        assert "NET" in [idx[0] for idx in summary_table.index]


class TestCarryVsBudget:
    """Test cases for carry_vs_budget."""

    def test_zero_or_negative_notional_returns_zero_pct(self) -> None:
        """book_notional <= 0 yields 0.0%, never a division error."""
        status = carry_vs_budget(
            theta_annual=-50_000.0,
            book_notional=0.0,
            budget_annual_pct=2.0,
        )

        assert status.carry_pct_of_notional == pytest.approx(0.0)
        assert status.within_budget is True

    def test_negative_notional_also_returns_zero_pct(self) -> None:
        """A negative book_notional is treated the same as zero."""
        status = carry_vs_budget(
            theta_annual=-50_000.0,
            book_notional=-1.0,
            budget_annual_pct=2.0,
        )

        assert status.carry_pct_of_notional == pytest.approx(0.0)

    def test_boundary_at_exactly_the_budget_is_within_budget(self) -> None:
        """carry_pct_of_notional == budget_annual_pct is within budget (<=)."""
        status = carry_vs_budget(
            theta_annual=-20_000.0,
            book_notional=1_000_000.0,
            budget_annual_pct=2.0,
        )

        assert status.carry_pct_of_notional == pytest.approx(2.0)
        assert status.within_budget is True

    def test_over_budget_is_not_within_budget(self) -> None:
        """A carry cost above the IPS budget reports within_budget=False."""
        status = carry_vs_budget(
            theta_annual=-50_000.0,
            book_notional=1_000_000.0,
            budget_annual_pct=2.0,
        )

        assert status.carry_pct_of_notional == pytest.approx(5.0)
        assert status.within_budget is False

    def test_theta_sign_is_irrelevant(self) -> None:
        """Positive or negative theta_annual yields the same magnitude."""
        negative = carry_vs_budget(
            theta_annual=-20_000.0,
            book_notional=1_000_000.0,
            budget_annual_pct=2.0,
        )
        positive = carry_vs_budget(
            theta_annual=20_000.0,
            book_notional=1_000_000.0,
            budget_annual_pct=2.0,
        )

        assert negative.carry_pct_of_notional == pytest.approx(
            positive.carry_pct_of_notional,
        )
