"""Tests for deltadewa.analysis.carry module."""

from datetime import datetime, timedelta
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.analysis.base import PortfolioAnalyzer


class TestCarryMixin:
    """Test cases for CarryMixin."""

    def test_calculate_carry_metrics_empty(self):
        """Test carry metrics on empty portfolio."""
        portfolio = OptionPortfolio()
        analyzer = PortfolioAnalyzer(portfolio)

        metrics = analyzer.calculate_carry_metrics()

        assert metrics["total_theta_daily"] == 0.0
        assert metrics["total_theta_weekly"] == 0.0
        assert metrics["total_theta_monthly"] == 0.0
        assert metrics["total_theta_annual"] == 0.0
        assert metrics["is_positive_carry"] is False
        assert len(metrics["theta_by_bucket"]) == 0

    def test_calculate_carry_metrics_with_position(self):
        """Test carry metrics with a position."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
        )

        # Add a short call (should have positive theta)
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="call",
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

    def test_empty_carry_metrics(self):
        """Test _empty_carry_metrics returns correct structure."""
        portfolio = OptionPortfolio()
        analyzer = PortfolioAnalyzer(portfolio)

        # pylint: disable=protected-access
        metrics = analyzer._empty_carry_metrics()

        assert metrics["total_theta_daily"] == 0.0
        assert metrics["total_theta_weekly"] == 0.0
        assert metrics["total_theta_monthly"] == 0.0
        assert metrics["total_theta_annual"] == 0.0
        assert not metrics["theta_by_bucket"]
        assert not metrics["theta_by_type"]
        assert metrics["covered_call_theta"] == 0.0
        assert metrics["long_call_theta"] == 0.0
        assert metrics["hedge_put_theta"] == 0.0
        assert metrics["short_put_theta"] == 0.0
        assert metrics["net_carry"] == 0.0
        assert not metrics["carry_efficiency"]
        assert metrics["is_positive_carry"] is False

    def test_create_theta_summary_table(self):
        """Test theta summary table creation."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
        )

        # Add positions
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,  # Short call
            option_type="call",
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,  # Long put
            option_type="put",
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

    def test_create_theta_summary_table_empty(self):
        """Test theta summary table with empty portfolio."""
        portfolio = OptionPortfolio()
        analyzer = PortfolioAnalyzer(portfolio)

        summary_table = analyzer.create_theta_summary_table()

        # Should still have NET row even when empty
        assert not summary_table.empty
        assert "NET" in [idx[0] for idx in summary_table.index]
