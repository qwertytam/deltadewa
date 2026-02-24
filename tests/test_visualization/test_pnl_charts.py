"""Tests for deltadewa.visualization.pnl_charts module."""

from datetime import datetime, timedelta
import matplotlib
import matplotlib.pyplot as plt
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.visualization.base import OptionCharts
from deltadewa.constants import OptionType

matplotlib.use("Agg")  # Use non-interactive backend


class TestPnLChartsMixin:
    """Test cases for PnLChartsMixin class."""

    def test_plot_pnl_diagram_empty_portfolio(self):
        """Test plot_pnl_diagram with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)
        charts = OptionCharts(portfolio)

        fig = charts.plot_pnl_diagram()
        assert fig is not None
        plt.close(fig)

    def test_plot_pnl_diagram_with_positions(self):
        """Test plot_pnl_diagram with positions."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now() + timedelta(days=30)

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

    def test_plot_pnl_diagram_with_underlying(self):
        """Test plot_pnl_diagram with underlying position."""
        portfolio = OptionPortfolio(spot_price=100.0, underlying_quantity=100.0)
        maturity = datetime.now() + timedelta(days=30)

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

    def test_plot_pnl_distribution_with_metrics(self):
        """Test plot_pnl_distribution_with_metrics."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now() + timedelta(days=30)

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

    def test_plot_pnl_distribution_custom_params(self):
        """Test plot_pnl_distribution_with_metrics with custom parameters."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now() + timedelta(days=30)

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
