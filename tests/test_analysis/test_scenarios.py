"""Tests for deltadewa.analysis.scenarios module."""

from datetime import UTC, datetime, timedelta

import numpy as np

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio


class TestScenariosMixin:
    """Test cases for ScenariosMixin."""

    def test_calculate_portfolio_value_at(self) -> None:
        """Test _calculate_portfolio_value_at method."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        # Calculate value at current spot and date
        # pylint: disable=protected-access
        value = analyzer._calculate_portfolio_value_at(
            spot=100.0,
            valuation_date=datetime.now(tz=UTC),
        )

        assert isinstance(value, float)
        assert value != 0.0

    def test_calculate_pnl_at_expiry_vectorized(self) -> None:
        """Test _calculate_pnl_at_expiry_vectorized method."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC),  # At expiry
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        # Create spot scenarios
        spot_scenarios = np.array([90, 95, 100, 105, 110, 115])
        # pylint: disable=protected-access
        pnl = analyzer._calculate_pnl_at_expiry_vectorized(
            spot_scenarios=spot_scenarios,
            include_underlying=True,
        )

        assert isinstance(pnl, np.ndarray)
        assert len(pnl) == len(spot_scenarios)

    def test_scenario_grid_pnl(self) -> None:
        """Test scenario_grid with PnL metric."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        # Create scenarios
        spot_scenarios = np.array([95, 100, 105])
        time_points = [
            datetime.now(tz=UTC),
            datetime.now(tz=UTC) + timedelta(days=10),
        ]

        result = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="pnl",
        )

        assert hasattr(result, "columns")
        assert "spot_price" in result.columns
        assert "valuation_date" in result.columns
        assert "value" in result.columns
        assert len(result) == len(spot_scenarios) * len(time_points)

    def test_scenario_grid_delta(self) -> None:
        """Test scenario_grid with delta metric."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([95, 100, 105])
        time_points = [datetime.now(tz=UTC)]

        result = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="delta",
        )

        assert "value" in result.columns
        assert len(result) == len(spot_scenarios) * len(time_points)

    def test_scenario_grid_spot_vol_pnl(self) -> None:
        """Test scenario_grid_spot_vol with PnL metric."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            risk_free_rate=0.05,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([95, 100, 105])
        vol_scenarios = np.array([0.2, 0.3, 0.4])

        result = analyzer.scenario_grid_spot_vol(
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            metric="pnl",
        )

        assert "spot_price" in result.columns
        assert "volatility" in result.columns
        assert "value" in result.columns
        assert len(result) == len(spot_scenarios) * len(vol_scenarios)

    def test_scenario_grid_spot_vol_vega(self) -> None:
        """Test scenario_grid_spot_vol with vega metric."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        spot_scenarios = np.array([95, 100, 105])
        vol_scenarios = np.array([0.2, 0.3, 0.4])

        result = analyzer.scenario_grid_spot_vol(
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            metric="vega",
        )

        assert "value" in result.columns
        assert len(result) == len(spot_scenarios) * len(vol_scenarios)

    def test_scenario_grid_restores_state(self) -> None:
        """Test that scenario_grid restores original portfolio state."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.3,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        analyzer = PortfolioAnalyzer(portfolio)

        original_spot = portfolio.spot_price
        original_date = portfolio.valuation_date

        spot_scenarios = np.array([95, 100, 105])
        time_points = [datetime.now(tz=UTC)]

        analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric="delta",
        )

        # State should be restored
        assert portfolio.spot_price == original_spot
        assert portfolio.valuation_date == original_date
