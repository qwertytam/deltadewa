"""Integration tests for deltadewa.visualization module."""

from datetime import UTC, datetime, timedelta

import matplotlib
import matplotlib.pyplot as plt

from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.visualization.base import OptionCharts
from deltadewa.visualization.convenience import (
    plot_greeks_by_strike,
    plot_greeks_consolidated,
    plot_pnl_diagram,
    plot_pnl_distribution_with_metrics,
    plot_theta_analysis,
)

matplotlib.use("Agg")  # Use non-interactive backend


class TestIntegration:
    """Integration tests for the complete visualization module."""

    def test_import_optioncharts(self) -> None:
        """Test importing OptionCharts from visualization."""
        assert OptionCharts is not None

    def test_convenience_functions_exist(self) -> None:
        """Test all convenience functions are accessible."""
        assert plot_pnl_diagram is not None
        assert plot_pnl_distribution_with_metrics is not None
        assert plot_greeks_by_strike is not None
        assert plot_theta_analysis is not None
        assert plot_greeks_consolidated is not None

    def test_convenience_plot_pnl_diagram(self) -> None:
        """Test plot_pnl_diagram convenience function."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        fig = plot_pnl_diagram(portfolio)
        assert fig is not None
        plt.close(fig)

    def test_convenience_plot_pnl_distribution(self) -> None:
        """Test plot_pnl_distribution_with_metrics convenience function."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        fig = plot_pnl_distribution_with_metrics(portfolio)
        assert fig is not None
        plt.close(fig)

    def test_convenience_plot_greeks_by_strike(self) -> None:
        """Test plot_greeks_by_strike convenience function."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        fig = plot_greeks_by_strike(portfolio)
        assert fig is not None
        plt.close(fig)

    def test_convenience_plot_theta_analysis(self) -> None:
        """Test plot_theta_analysis convenience function."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        fig = plot_theta_analysis(portfolio)
        assert fig is not None
        plt.close(fig)

    def test_convenience_plot_greeks_consolidated(self) -> None:
        """Test plot_greeks_consolidated convenience function."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        fig = plot_greeks_consolidated(portfolio)
        assert fig is not None
        plt.close(fig)

    def test_convenience_plot_greeks_consolidated_figure_structure(
        self,
    ) -> None:
        """Test panel structure: 8 axes with the expected titles/xlabels.

        Uses a multi-strike, multi-maturity portfolio so every panel
        (per-Greek contributors, value-by-strike/maturity, Greeks-by-
        strike/maturity) has data to render rather than a "No data"
        placeholder.
        """
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
            strike_price=105.0,
            maturity_date=maturity1,
            quantity=-1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=maturity2,
            quantity=1,
            option_type=OptionType.PUT,
        )

        fig = plot_greeks_consolidated(portfolio, top_n=5)

        assert len(fig.axes) == 8
        titles = {ax.get_title() for ax in fig.axes}
        assert titles == {
            "Top 5 Delta Contributors",
            "Top 5 Gamma Contributors",
            "Top 5 Vega Contributors",
            "Top 5 Theta Contributors",
            "Top 5 Position Values by Strike",
            "Top 5 Position Values by Maturity",
            "Greeks by Strike",
            "Greeks by Maturity",
        }

        by_title = {ax.get_title(): ax for ax in fig.axes}
        assert by_title["Top 5 Delta Contributors"].get_xlabel() == "Delta"
        assert (
            by_title["Top 5 Theta Contributors"].get_xlabel() == "Theta ($/day)"
        )
        assert by_title["Greeks by Strike"].get_xlabel() == "Strike Price"
        assert by_title["Greeks by Maturity"].get_xlabel() == "Maturity Date"

        plt.close(fig)

    def test_full_workflow(self) -> None:
        """Test full workflow with all chart types."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            underlying_quantity=100.0,
            volatility=0.25,
        )

        # Add multiple positions
        maturity1 = datetime.now(tz=UTC) + timedelta(days=30)
        maturity2 = datetime.now(tz=UTC) + timedelta(days=60)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity1,
            quantity=1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=maturity1,
            quantity=-1,
            option_type=OptionType.CALL,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=maturity2,
            quantity=1,
            option_type=OptionType.PUT,
        )

        # Create charts
        charts = OptionCharts(portfolio)

        # Test all chart methods work
        fig1 = charts.plot_pnl_diagram()
        assert fig1 is not None
        plt.close(fig1)

        fig2 = charts.plot_pnl_distribution_with_metrics()
        assert fig2 is not None
        plt.close(fig2)

        fig3 = charts.plot_greeks_by_strike()
        assert fig3 is not None
        plt.close(fig3)

        fig4 = charts.plot_greeks_by_maturity()
        assert fig4 is not None
        plt.close(fig4)

        fig5 = charts.plot_theta_analysis()
        assert fig5 is not None
        plt.close(fig5)
