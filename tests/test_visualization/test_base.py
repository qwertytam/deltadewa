"""Tests for deltadewa.visualization.base module."""

from datetime import UTC, datetime, timedelta

from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.visualization.base import OptionCharts, OptionChartsBase


class TestOptionChartsBase:
    """Test cases for OptionChartsBase class."""

    def test_initialization(self) -> None:
        """Test OptionChartsBase can be instantiated."""
        portfolio = OptionPortfolio()
        charts = OptionChartsBase(portfolio)

        assert charts is not None
        assert charts.portfolio is portfolio
        assert charts.style == "seaborn-v0_8-darkgrid"

    def test_initialization_custom_style(self) -> None:
        """Test OptionChartsBase with custom style."""
        portfolio = OptionPortfolio()
        charts = OptionChartsBase(portfolio, style="ggplot")

        assert charts.style == "ggplot"

    def test_get_expiry_label_empty(self) -> None:
        """Test _get_expiry_label with empty portfolio."""
        portfolio = OptionPortfolio()
        charts = OptionChartsBase(portfolio)

        # pylint: disable=protected-access
        label = charts._get_expiry_label()
        assert label == "N/A"

    def test_get_expiry_label_single_maturity(self) -> None:
        """Test _get_expiry_label with single maturity."""
        portfolio = OptionPortfolio(spot_price=100.0)
        maturity = datetime.now(tz=UTC) + timedelta(days=30)
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=maturity,
            quantity=1,
            option_type=OptionType.CALL,
        )
        charts = OptionChartsBase(portfolio)

        # pylint: disable=protected-access
        label = charts._get_expiry_label()
        expected = maturity.strftime("%Y-%m-%d")
        assert label == expected

    def test_get_expiry_label_multiple_maturities(self) -> None:
        """Test _get_expiry_label with multiple maturities."""
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
            maturity_date=maturity2,
            quantity=1,
            option_type=OptionType.PUT,
        )

        # pylint: disable=protected-access
        charts = OptionChartsBase(portfolio)
        label = charts._get_expiry_label()

        expected = (
            f"{maturity1.strftime('%Y-%m-%d')} → "
            f"{maturity2.strftime('%Y-%m-%d')}"
        )
        assert label == expected

    def test_create_chart_grid(self) -> None:
        """Test create_chart_grid static method."""
        fig, axes = OptionChartsBase.create_chart_grid(
            rows=2,
            cols=2,
            titles=["A", "B", "C", "D"],
        )

        assert fig is not None
        assert axes.shape == (2, 2)


class TestOptionCharts:
    """Test cases for full OptionCharts composition."""

    def test_initialization(self) -> None:
        """Test OptionCharts can be instantiated."""
        portfolio = OptionPortfolio()
        charts = OptionCharts(portfolio)

        assert charts is not None
        assert hasattr(charts, "portfolio")
        assert hasattr(charts, "plot_pnl_diagram")
        assert hasattr(charts, "plot_greeks_by_strike")
        assert hasattr(charts, "plot_theta_analysis")
        assert hasattr(charts, "plot_scenario_analysis")

    def test_has_pnl_methods(self) -> None:
        """Test OptionCharts has P&L methods."""
        portfolio = OptionPortfolio()
        charts = OptionCharts(portfolio)

        assert hasattr(charts, "plot_pnl_diagram")
        assert hasattr(charts, "plot_pnl_distribution_with_metrics")
        assert hasattr(charts, "_plot_pnl_panel")

    def test_has_greeks_methods(self) -> None:
        """Test OptionCharts has Greek methods."""
        portfolio = OptionPortfolio()
        charts = OptionCharts(portfolio)

        assert hasattr(charts, "plot_greeks_by_strike")
        assert hasattr(charts, "plot_greeks_by_maturity")
        assert hasattr(charts, "_plot_greek_by_dimension")

    def test_has_theta_methods(self) -> None:
        """Test OptionCharts has theta methods."""
        portfolio = OptionPortfolio()
        charts = OptionCharts(portfolio)

        assert hasattr(charts, "plot_theta_analysis")
        assert hasattr(charts, "_prepare_theta_data")
        assert hasattr(charts, "_plot_theta_by_bucket")
        assert hasattr(charts, "_plot_theta_projection")
        assert hasattr(charts, "_plot_carry_efficiency")
        assert hasattr(charts, "_plot_theta_vs_contracts")

    def test_has_scenario_methods(self) -> None:
        """Test OptionCharts has scenario methods."""
        portfolio = OptionPortfolio()
        charts = OptionCharts(portfolio)

        assert hasattr(charts, "plot_scenario_analysis")
