"""Tests for deltadewa.visualization.scenarios module."""

from datetime import UTC, datetime, timedelta

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.visualization.base import OptionCharts

matplotlib.use("Agg")  # Use non-interactive backend


class TestScenarioChartsMixin:
    """Test cases for ScenarioChartsMixin class."""

    def test_plot_scenario_analysis(self) -> None:
        """Test plot_scenario_analysis."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            underlying_quantity=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        # Create sample scenario data
        spot_prices = [90, 95, 100, 105, 110]
        scenario_df = pd.DataFrame(
            {
                "spot_price": spot_prices,
                "portfolio_pnl": [100, 200, 300, 400, 500],
                "underlying_pnl": [-1000, -500, 0, 500, 1000],
                "total_pnl": [-900, -300, 300, 900, 1500],
                "total_delta": [0.5, 0.6, 0.7, 0.8, 0.9],
                "net_delta": [50.5, 50.6, 50.7, 50.8, 50.9],
            },
        )

        charts = OptionCharts(portfolio)
        valuation_date = datetime.now(tz=UTC)
        fig = charts.plot_scenario_analysis(
            scenario_df=scenario_df,
            days_forward=10,
            valuation_date=valuation_date,
            current_spot=100.0,
        )

        assert fig is not None
        # Should have 2 panels
        assert len(fig.axes) == 2
        plt.close(fig)

    def test_plot_scenario_analysis_today(self) -> None:
        """Test plot_scenario_analysis with days_forward=0."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        maturity = datetime.now(tz=UTC) + timedelta(days=30)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )

        scenario_df = pd.DataFrame(
            {
                "spot_price": [90, 100, 110],
                "portfolio_pnl": [0, 100, 200],
                "underlying_pnl": [0, 0, 0],
                "total_pnl": [0, 100, 200],
                "total_delta": [0.5, 0.6, 0.7],
                "net_delta": [0.5, 0.6, 0.7],
            },
        )

        charts = OptionCharts(portfolio)
        valuation_date = datetime.now(tz=UTC)
        fig = charts.plot_scenario_analysis(
            scenario_df=scenario_df,
            days_forward=0,
            valuation_date=valuation_date,
            current_spot=100.0,
        )

        assert fig is not None
        plt.close(fig)
