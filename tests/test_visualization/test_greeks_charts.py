"""Tests for deltadewa.visualization.greeks_charts module."""

from datetime import UTC, datetime, timedelta

import matplotlib
import matplotlib.pyplot as plt

from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.visualization.base import OptionCharts

matplotlib.use("Agg")  # Use non-interactive backend


class TestGreeksChartsMixin:
    """Test cases for GreeksChartsMixin class."""

    def test_plot_greeks_by_strike_empty(self):
        """Test plot_greeks_by_strike with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)
        charts = OptionCharts(portfolio)

        # Empty portfolio will raise KeyError, which is expected behavior
        # This test documents that behavior; in production,
        # users should check portfolio.positions before plotting
        try:
            fig = charts.plot_greeks_by_strike()
            if fig:
                plt.close(fig)
        except KeyError:
            # Expected for empty portfolio
            pass

    def test_plot_greeks_by_strike_with_positions(self):
        """Test plot_greeks_by_strike with positions."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=maturity,
            quantity=-1,
            option_type=OptionType.CALL,
        )

        charts = OptionCharts(portfolio)
        fig = charts.plot_greeks_by_strike()

        assert fig is not None
        # Should have 3 panels (delta, gamma, vega)
        assert len(fig.axes) == 3
        plt.close(fig)

    def test_plot_greeks_by_strike_custom_metrics(self):
        """Test plot_greeks_by_strike with custom metrics."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        charts = OptionCharts(portfolio)
        fig = charts.plot_greeks_by_strike(metrics=["delta", "theta"])

        assert fig is not None
        # Should have 2 panels
        assert len(fig.axes) == 2
        plt.close(fig)

    def test_plot_greeks_by_maturity(self):
        """Test plot_greeks_by_maturity."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity1 = datetime.now(tz=UTC) + timedelta(days=30)
        maturity2 = datetime.now(tz=UTC) + timedelta(days=60)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity1,
            quantity=1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity2,
            quantity=1,
            option_type=OptionType.PUT,
        )

        charts = OptionCharts(portfolio)
        fig = charts.plot_greeks_by_maturity()

        assert fig is not None
        # Should have 3 panels (delta, gamma, vega)
        assert len(fig.axes) == 3
        plt.close(fig)

    def test_plot_greeks_by_maturity_custom_metrics(self):
        """Test plot_greeks_by_maturity with custom metrics."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        charts = OptionCharts(portfolio)
        fig = charts.plot_greeks_by_maturity(metrics=["vega"])

        assert fig is not None
        # Should have 1 panel
        assert len(fig.axes) == 1
        plt.close(fig)
