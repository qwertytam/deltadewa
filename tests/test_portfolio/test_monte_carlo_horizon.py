"""Tests for horizon repricing in Monte Carlo (M3 defect 1).

Legs still alive at the simulation horizon must be repriced there, not valued
at intrinsic. On a laddered book at a -30% / 12m horizon the 18m and 24m legs
carry six figures of time value that the old intrinsic basis zeroed out.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from deltadewa.batch_pricer import BatchPricer
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio

_VAL = datetime(2026, 1, 1, tzinfo=UTC)
_SPOT = 6600.0
_HORIZON_DAYS = 365


def _laddered_book() -> OptionPortfolio:
    """Laddered SPX put hedge: near 12m + live 18m + live 24m tenors."""
    pf = OptionPortfolio(
        underlying_quantity=1000.0,
        spot_price=_SPOT,
        volatility=0.20,
        risk_free_rate=0.045,
        dividend_yield=0.015,
        valuation_date=_VAL,
        symbol="SPX",
        default_exercise_style=ExerciseStyle.EUROPEAN,
        contract_size=100,
    )
    # Near leg — 25% OTM, matures exactly at the 12m horizon (settles intrinsic)
    pf.add_position(4950.0, _VAL + timedelta(days=365), 23, OptionType.PUT)
    # 18m leg — 30% OTM, 6m of life left at the horizon
    pf.add_position(4620.0, _VAL + timedelta(days=547), 26, OptionType.PUT)
    # 24m leg — 40% OTM, 12m of life left at the horizon
    pf.add_position(3960.0, _VAL + timedelta(days=730), 16, OptionType.PUT)
    return pf


class TestHorizonRepricing:
    """The horizon P&L reprices live legs instead of intrinsic-valuing them."""

    def test_live_legs_carry_time_value_not_intrinsic(self) -> None:
        """18m/24m legs repriced at -30%/12m are six figures, not $0.

        Pins the ~$457k order-of-magnitude acceptance from the plan (the
        exact figure is book-dependent; this book prices to ~$0.7M).
        """
        pf = _laddered_book()
        horizon = _VAL + timedelta(days=_HORIZON_DAYS)
        crash_spot = 0.70 * _SPOT  # -30%
        live = pf.positions[1:]  # 18m + 24m

        pricer = BatchPricer(
            live,
            pf.risk_free_rate,
            pf.dividend_yield,
            underlying_quantity=0.0,
        )
        repriced = pricer.portfolio_values_at(
            np.array([crash_spot]),
            horizon,
        )[0]
        intrinsic = sum(
            max(0.0, p.option.strike_price - crash_spot)
            * p.quantity
            * p.contract_size
            for p in live
        )

        # Both live strikes sit at/below the crash spot -> $0 intrinsic; the
        # old basis contributed exactly this. Repricing recovers six figures.
        assert intrinsic == pytest.approx(0.0, rel=1e-8)
        assert 4.0e5 < repriced < 1.2e6

    def test_horizon_pnl_beats_intrinsic_pnl_at_crash(self) -> None:
        """MC horizon P&L exceeds the old intrinsic P&L by the live value."""
        pf = _laddered_book()
        crash = np.array([0.70 * _SPOT])

        repriced_pnl = pf._simulate_horizon_pnls(
            crash,
            _HORIZON_DAYS,
            include_underlying=False,
        )[0]
        intrinsic_pnl = pf.vectorized_pnl_at_expiry(
            crash,
            include_underlying=False,
        )[0]

        # Difference is the live 18m/24m time value the old code dropped.
        assert repriced_pnl - intrinsic_pnl > 4.0e5

    def test_grid_interp_matches_direct_repricing(self) -> None:
        """Grid + np.interp agrees with per-path repricing within tolerance."""
        pf = _laddered_book()
        horizon = _VAL + timedelta(days=_HORIZON_DAYS)
        spots = np.linspace(0.5 * _SPOT, 1.5 * _SPOT, 400)

        pricer = BatchPricer(
            pf.positions,
            pf.risk_free_rate,
            pf.dividend_yield,
            underlying_quantity=0.0,
        )
        direct = pricer.portfolio_values_at(spots, horizon)
        grid = pf._horizon_spot_grid(spots)
        grid_values = pricer.portfolio_values_at(grid, horizon)
        interp = np.interp(spots, grid, grid_values)

        np.testing.assert_allclose(interp, direct, rtol=1e-2, atol=1.0e3)

    def test_horizon_spot_grid_spans_range_and_folds_strikes(self) -> None:
        """Grid spans [min, max] and includes only in-range strike kinks."""
        pf = _laddered_book()
        grid = pf._horizon_spot_grid(np.array([4000.0, 8000.0]))

        assert grid[0] == pytest.approx(4000.0, rel=1e-2)
        assert grid[-1] == pytest.approx(8000.0, rel=1e-2)
        assert 4950.0 in grid  # in range
        assert 4620.0 in grid  # in range
        assert 3960.0 not in grid  # below the lower bound -> excluded

    def test_horizon_spot_grid_degenerate_single_spot(self) -> None:
        """Zero-dispersion spots collapse to a single-node grid."""
        pf = _laddered_book()
        grid = pf._horizon_spot_grid(np.array([5000.0, 5000.0]))
        assert grid.tolist() == [5000.0]

    def test_full_simulation_risk_metrics_sane(self) -> None:
        """VaR/CVaR ordering and prob bounds hold on the repriced book."""
        pf = _laddered_book()
        res = pf.run_monte_carlo_simulation(num_simulations=5000, random_seed=3)

        assert res["days_to_expiry"] == _HORIZON_DAYS
        assert 0.0 <= res["prob_profit"] <= 1.0
        assert res["var_99"] <= res["var_95"]
        assert res["cvar_99"] <= res["cvar_95"]
        assert res["min_pnl"] <= res["var_99"]
        assert res["var_95"] <= res["max_pnl"]
