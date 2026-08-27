"""Tests for deltadewa.analysis.scenarios module."""

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.repricing import proportional_vol
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
        assert value != pytest.approx(0.0, rel=1e-8)

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
            # #365: this fixture deliberately wants an at-expiry position.
            reject_expired=False,
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
            vol_mapping=proportional_vol,
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
            vol_mapping=proportional_vol,
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


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via ``math.erf`` -- independent of QuantLib."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_put_delta(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> float:
    """European put delta via Black-Scholes -- independent oracle.

    Same role as ``tests/test_valuation.py``'s ``_black_scholes_put``: an
    independent formula to verify the QuantLib-backed engine against, not
    reused across test modules.
    """
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility**2)
        * time_to_expiry
    ) / (volatility * math.sqrt(time_to_expiry))
    return math.exp(-dividend_yield * time_to_expiry) * (_norm_cdf(d1) - 1.0)


class TestDeltaDrift:
    """Tests for ScenariosMixin.calculate_delta_drift (Part X §13)."""

    _VALUATION_DATE = datetime(2026, 1, 1, tzinfo=UTC)
    _MATURITY_DATE = datetime(2027, 1, 1, tzinfo=UTC)  # 365 days -> T=1.0
    _SPOT = 100.0
    _STRIKE = 100.0
    _VOL = 0.20
    _RATE = 0.02
    _DIVIDEND = 0.0

    def _atm_put_portfolio(
        self,
        *,
        underlying_quantity: float = 0.0,
    ) -> OptionPortfolio:
        portfolio = OptionPortfolio(
            underlying_quantity=underlying_quantity,
            spot_price=self._SPOT,
            volatility=self._VOL,
            risk_free_rate=self._RATE,
            dividend_yield=self._DIVIDEND,
            valuation_date=self._VALUATION_DATE,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=self._STRIKE,
            maturity_date=self._MATURITY_DATE,
            quantity=1,
            option_type=OptionType.PUT,
        )
        return portfolio

    def test_matches_hand_checked_black_scholes_delta(self) -> None:
        """delta_now/delta_shocked match an independent BS oracle."""
        portfolio = self._atm_put_portfolio()
        drift = PortfolioAnalyzer(portfolio).calculate_delta_drift()

        expected_now = (
            _bs_put_delta(
                self._SPOT,
                self._STRIKE,
                1.0,
                self._VOL,
                self._RATE,
                self._DIVIDEND,
            )
            * 100  # contract_size
        )
        expected_shocked = (
            _bs_put_delta(
                self._SPOT * 0.95,
                self._STRIKE,
                1.0,
                self._VOL,
                self._RATE,
                self._DIVIDEND,
            )
            * 100
        )

        assert drift.delta_now == pytest.approx(expected_now, rel=1e-6)
        assert drift.delta_shocked == pytest.approx(expected_shocked, rel=1e-6)
        assert drift.drift == pytest.approx(
            expected_shocked - expected_now,
            rel=1e-6,
        )
        assert drift.shock_pct == pytest.approx(-5.0)
        # A long put's delta becomes more negative as spot falls -- the
        # hedge activating, per the handbook's
        # (https://github.com/qwertytam/deltadewa-handbook) own worked
        # example.
        assert drift.drift < 0.0

    def test_per_leg_drift_sums_to_total(self) -> None:
        """Multi-leg book: leg drifts reconcile to the total (no hidden term).

        No underlying-quantity term can break the reconciliation, unlike a
        net-delta metric -- see ``test_underlying_quantity_excluded``.
        """
        portfolio = OptionPortfolio(
            spot_price=100.0,
            volatility=0.25,
            risk_free_rate=0.03,
            valuation_date=self._VALUATION_DATE,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=self._MATURITY_DATE,
            quantity=5,
            option_type=OptionType.PUT,
        )
        portfolio.add_position(
            strike_price=110.0,
            maturity_date=self._MATURITY_DATE,
            quantity=-2,
            option_type=OptionType.CALL,
        )

        drift = PortfolioAnalyzer(portfolio).calculate_delta_drift()

        assert len(drift.legs) == 2
        assert sum(leg.drift for leg in drift.legs) == pytest.approx(
            drift.drift,
            rel=1e-9,
        )
        assert sum(leg.delta_now for leg in drift.legs) == pytest.approx(
            drift.delta_now,
            rel=1e-9,
        )
        assert sum(leg.delta_shocked for leg in drift.legs) == pytest.approx(
            drift.delta_shocked,
            rel=1e-9,
        )

    def test_underlying_quantity_excluded(self) -> None:
        """Hedge delta excludes the equity leg (unlike Part X #10)."""
        portfolio = self._atm_put_portfolio(underlying_quantity=0.0)
        unhedged = PortfolioAnalyzer(portfolio).calculate_delta_drift()

        portfolio.underlying_quantity = 500.0
        hedged = PortfolioAnalyzer(portfolio).calculate_delta_drift()

        assert hedged.delta_now == pytest.approx(unhedged.delta_now)
        assert hedged.delta_shocked == pytest.approx(unhedged.delta_shocked)
        assert hedged.drift == pytest.approx(unhedged.drift)

    def test_empty_book_raises(self) -> None:
        """No option positions means no hedge delta to shock."""
        portfolio = OptionPortfolio(
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        with pytest.raises(ValueError, match="at least one option position"):
            PortfolioAnalyzer(portfolio).calculate_delta_drift()
