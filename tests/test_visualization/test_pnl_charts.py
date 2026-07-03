"""Tests for deltadewa.visualization.pnl_charts module."""

from datetime import UTC, datetime, timedelta

import matplotlib
import matplotlib.pyplot as plt

from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.visualization.base import OptionCharts

matplotlib.use("Agg")  # Use non-interactive backend


class TestPnLChartsMixin:
    """Test cases for PnLChartsMixin class."""

    def test_plot_pnl_diagram_empty_portfolio(self) -> None:
        """Test plot_pnl_diagram with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)
        charts = OptionCharts(portfolio)

        fig = charts.plot_pnl_diagram()
        assert fig is not None
        plt.close(fig)

    def test_plot_pnl_diagram_with_positions(self) -> None:
        """Test plot_pnl_diagram with positions."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        charts = OptionCharts(portfolio)
        fig = charts.plot_pnl_diagram()

        assert fig is not None
        plt.close(fig)

    def test_plot_pnl_diagram_with_underlying(self) -> None:
        """Test plot_pnl_diagram with underlying position."""
        portfolio = OptionPortfolio(spot_price=100.0, underlying_quantity=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        charts = OptionCharts(portfolio)
        fig = charts.plot_pnl_diagram(show_underlying=True)

        assert fig is not None
        # Should have 2 panels
        assert len(fig.axes) == 2
        plt.close(fig)

    def test_plot_pnl_distribution_with_metrics(self) -> None:
        """Test plot_pnl_distribution_with_metrics."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        charts = OptionCharts(portfolio)
        fig = charts.plot_pnl_distribution_with_metrics()

        assert fig is not None
        plt.close(fig)

    def test_plot_pnl_distribution_custom_params(self) -> None:
        """Test plot_pnl_distribution_with_metrics with custom parameters."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        charts = OptionCharts(portfolio)
        fig = charts.plot_pnl_distribution_with_metrics(
            spot_range_pct=50.0,
            num_points=500,
            include_underlying=False,
        )

        assert fig is not None
        plt.close(fig)

    def test_plot_pnl_distribution_figure_structure(self) -> None:
        """Test annotation structure: axes, title, and every metric label.

        Uses a put spread (no naked short calls, no long calls) so that
        max loss and max profit are both bounded, exercising every
        annotation branch: percentile levels, current spot, breakeven,
        max loss, max profit, and expected value.
        """
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.PUT,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=maturity,
            quantity=-1,
            option_type=OptionType.PUT,
        )

        charts = OptionCharts(portfolio)
        fig = charts.plot_pnl_distribution_with_metrics(
            num_points=200,
            include_underlying=False,
        )
        ax = fig.axes[0]

        assert len(fig.axes) == 1
        assert ax.get_title() == (
            "P&L Distribution with Key Metrics (Options Only)"
        )
        assert ax.get_xlabel() == "Spot Price at Maturity ($)"
        assert ax.get_ylabel() == "Profit / Loss ($)"

        annotation_texts = {t.get_text() for t in ax.texts}
        assert annotation_texts == {
            "5% @ $91",
            "95% @ $110",
            "Current Spot\n$100",
            "BE $100.34",
            "ML $-491",
            "MP $509",
            "EV $-8",
        }

        plt.close(fig)
