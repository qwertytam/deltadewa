"""Tests for drift labelling and local RNG in Monte Carlo (M3 defects 2 & 3).

The GBM drift is risk-neutral by default and must be labelled as such; a
supplied real-world return relabels the results. Seeding uses a local
Generator so it is reproducible without perturbing the global np.random state.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.monte_carlo import drift_measure_label

_VAL = datetime(2026, 1, 1, tzinfo=UTC)
_SPOT = 6600.0


def _book() -> OptionPortfolio:
    """Net-long SPX book (underlying dominates the drift sensitivity)."""
    pf = OptionPortfolio(
        underlying_quantity=1000.0,
        spot_price=_SPOT,
        volatility=0.20,
        risk_free_rate=0.045,
        dividend_yield=0.015,
        valuation_date=_VAL,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    pf.add_position(4950.0, _VAL + timedelta(days=365), 23, OptionType.PUT)
    pf.add_position(4620.0, _VAL + timedelta(days=547), 26, OptionType.PUT)
    return pf


class TestDriftMeasure:
    """Drift measure defaults to risk-neutral and is configurable."""

    def test_default_is_risk_neutral(self) -> None:
        """No expected_return -> risk-neutral drift labelled on the result."""
        res = _book().run_monte_carlo_simulation(num_simulations=500)
        assert res["drift_measure"] == "risk_neutral"
        assert res["expected_return_annual"] == pytest.approx(0.045, rel=1e-4)

    def test_expected_return_makes_it_real_world(self) -> None:
        """A supplied return relabels the result and shifts expected P&L."""
        pf = _book()
        rn = pf.run_monte_carlo_simulation(num_simulations=8000, random_seed=1)
        rw = pf.run_monte_carlo_simulation(
            num_simulations=8000,
            random_seed=1,
            expected_return=0.10,
        )

        assert rw["drift_measure"] == "real_world"
        assert rw["expected_return_annual"] == pytest.approx(0.10, rel=1e-8)
        # Same seed, only the drift differs: a higher drift lifts terminal
        # spots, so a net-long book's expected P&L rises.
        assert rw["expected_pnl"] > rn["expected_pnl"]

    def test_empty_portfolio_still_labels_measure(self) -> None:
        """The empty-result path carries the drift measure too."""
        pf = OptionPortfolio(spot_price=_SPOT, valuation_date=_VAL)
        res = pf.run_monte_carlo_simulation(
            num_simulations=100,
            expected_return=0.08,
        )
        assert res["drift_measure"] == "real_world"
        assert res["expected_return_annual"] == pytest.approx(0.08, rel=1e-9)

    def test_drift_measure_label(self) -> None:
        """Label helper maps measures to display strings; passes rest."""
        assert drift_measure_label("risk_neutral") == "risk-neutral"
        assert drift_measure_label("real_world") == "real-world"
        assert drift_measure_label("unknown") == "unknown"


class TestLocalRng:
    """Seeding is reproducible and confined to a local Generator."""

    def test_seeded_runs_are_reproducible(self) -> None:
        """Two runs with the same seed give identical paths."""
        pf = _book()
        r1 = pf.run_monte_carlo_simulation(num_simulations=2000, random_seed=7)
        r2 = pf.run_monte_carlo_simulation(num_simulations=2000, random_seed=7)
        np.testing.assert_array_equal(
            r1["simulated_pnls"],
            r2["simulated_pnls"],
        )

    def test_seeding_does_not_touch_global_rng(self) -> None:
        """A seeded MC run leaves the global np.random stream untouched."""
        np.random.seed(0)
        expected_next = np.random.random()

        np.random.seed(0)
        _book().run_monte_carlo_simulation(
            num_simulations=1000,
            random_seed=999,
        )
        got_next = np.random.random()

        # If the MC had used the global RNG, this draw would have advanced.
        assert got_next == expected_next

    def test_different_seeds_give_different_draws(self) -> None:
        """Distinct seeds must produce distinct paths (#180).

        The companion to ``test_seeded_runs_are_reproducible``: together
        they pin that ``random_seed`` actually reaches the Generator.
        A local ``default_rng`` that ignored its argument would satisfy
        reproducibility on its own.
        """
        pf = _book()
        r1 = pf.run_monte_carlo_simulation(num_simulations=2000, random_seed=7)
        r2 = pf.run_monte_carlo_simulation(num_simulations=2000, random_seed=8)
        assert not np.array_equal(r1["simulated_pnls"], r2["simulated_pnls"])

    def test_seed_choice_survives_an_interleaved_run(self) -> None:
        """Seed 7 gives the same paths either side of a seed-8 run.

        A ``Generator`` held as shared state, rather than built per call,
        would drift here even though each individual call looked
        reproducible.
        """
        pf = _book()
        first = pf.run_monte_carlo_simulation(
            num_simulations=2000,
            random_seed=7,
        )
        pf.run_monte_carlo_simulation(num_simulations=2000, random_seed=8)
        again = pf.run_monte_carlo_simulation(
            num_simulations=2000,
            random_seed=7,
        )
        np.testing.assert_array_equal(
            first["simulated_pnls"],
            again["simulated_pnls"],
        )

    def test_unseeded_runs_vary(self) -> None:
        """random_seed=None yields different draws across runs."""
        pf = _book()
        r1 = pf.run_monte_carlo_simulation(
            num_simulations=2000,
            random_seed=None,
        )
        r2 = pf.run_monte_carlo_simulation(
            num_simulations=2000,
            random_seed=None,
        )
        assert not np.array_equal(r1["simulated_pnls"], r2["simulated_pnls"])
