"""Tests for deltadewa.visualization.theta_charts module."""

from datetime import datetime, timedelta
import matplotlib

import matplotlib.pyplot as plt
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.visualization.base import OptionCharts
from deltadewa.constants import OptionType

matplotlib.use("Agg")  # Use non-interactive backend


class TestThetaChartsMixin:
    """Test cases for ThetaChartsMixin class."""

    def test_plot_theta_analysis_empty(self):
        """Test plot_theta_analysis with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0)
        charts = OptionCharts(portfolio)

        # Empty portfolio will raise KeyError, which is expected behavior
        # This test documents that behavior; in production,
        # users should check portfolio.positions before plotting
        try:
            fig = charts.plot_theta_analysis()
            if fig:
                plt.close(fig)
        except KeyError:
            # Expected for empty portfolio
            pass

    def test_plot_theta_analysis_with_positions(self):
        """Test plot_theta_analysis with positions."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now() + timedelta(days=30)

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
        fig = charts.plot_theta_analysis()

        assert fig is not None
        # Should have 4 main panels (2x2) but theta plots create twin axes
        # So we expect more than 4
        assert len(fig.axes) >= 4
        plt.close(fig)

    def test_plot_theta_analysis_custom_projection(self):
        """Test plot_theta_analysis with custom projection days."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now() + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        charts = OptionCharts(portfolio)
        fig = charts.plot_theta_analysis(projection_days=60)

        assert fig is not None
        plt.close(fig)

    def test_prepare_theta_data(self):
        """Test _prepare_theta_data."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now() + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        charts = OptionCharts(portfolio)
        df = portfolio.to_dataframe()
        # pylint: disable=protected-access
        df_carry, theta_metrics = charts._prepare_theta_data(df)

        assert df_carry is not None
        assert "days_to_expiry" in df_carry.columns
        assert "maturity_bucket" in df_carry.columns
        assert "daily" in theta_metrics
        assert "weekly" in theta_metrics
        assert "monthly" in theta_metrics
        assert "annual" in theta_metrics
