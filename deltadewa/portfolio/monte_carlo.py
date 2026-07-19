"""Monte Carlo simulation mixin for option portfolio."""

from collections import Counter
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from deltadewa import constants as const
from deltadewa.batch_pricer import BatchPricer

if TYPE_CHECKING:
    from deltadewa.portfolio._protocols import _PortfolioProtocol

# Base grid points the horizon is repriced on before interpolating the paths.
# Strike kinks are folded in on top of these (see _horizon_spot_grid).
_HORIZON_GRID_POINTS = 201

# Human-readable labels for the GBM drift measure recorded on every result.
_DRIFT_MEASURE_LABELS = {
    "risk_neutral": "risk-neutral",
    "real_world": "real-world",
}


def drift_measure_label(measure: str) -> str:
    """Return the human-readable label for a Monte Carlo drift measure.

    Single source for the wording used wherever a probability derived from
    the simulation is displayed, so the risk-neutral assumption is surfaced
    consistently.

    Args:
        measure: The ``drift_measure`` value from a results dict
            (``"risk_neutral"`` or ``"real_world"``).

    Returns:
        A display label (e.g. ``"risk-neutral"``); the raw value unchanged if
        it is not a recognised measure.

    """
    return _DRIFT_MEASURE_LABELS.get(measure, measure)


class MonteCarloMixin:
    """Mixin providing Monte Carlo simulation for option portfolio."""

    if TYPE_CHECKING:
        _self: "_PortfolioProtocol"

    # Declare attribute for static type checkers. The concrete
    # `OptionPortfolioBase` provides a property for this name at runtime.
    monte_carlo_results: (
        dict[str, float | int | np.ndarray[Any, np.dtype[Any]]] | None
    )

    def _calculate_theoretical_max_loss(
        self: "_PortfolioProtocol",
    ) -> float | None:
        """Calculate theoretical max loss based on position structure."""
        if not hasattr(self, "positions") or not self.positions:
            return None

        max_loss_theoretical = 0.0
        for pos in self.positions:
            if pos.quantity < 0:  # Short position
                if pos.option.option_type == const.OptionType.PUT:
                    # Short put max loss = strike * quantity
                    loss = (
                        pos.option.strike_price
                        * abs(pos.quantity)
                        * pos.contract_size
                    )
                    max_loss_theoretical += loss
                else:
                    # Short call = unlimited loss
                    return float("inf")

        if max_loss_theoretical > 0:
            return -max_loss_theoretical
        return None

    def _analyze_concentration(
        self: "_PortfolioProtocol",
        pnls: np.ndarray[Any, np.dtype[Any]],
    ) -> tuple[bool, float, tuple[float, int] | None]:
        """Analyze P&L distribution concentration."""
        unique_rounded = np.unique(np.round(pnls, 2))
        is_concentrated = len(unique_rounded) < (len(pnls) / 100)

        concentration_pct = 0.0
        most_common_pnl = None

        if is_concentrated:
            most_common = Counter(np.round(pnls, 2)).most_common(1)
            if most_common:
                most_common_pnl = most_common[0]
                concentration_pct = most_common_pnl[1] / len(pnls) * 100

        return is_concentrated, concentration_pct, most_common_pnl

    def _empty_monte_carlo_results(
        self: "_PortfolioProtocol",
        days_to_expiry: int,
    ) -> dict[str, Any]:
        """Return safe empty results structure."""
        return {
            "simulated_pnls": np.array([]),
            "num_simulations": 0,
            "days_to_expiry": days_to_expiry,
            "expected_pnl": 0.0,
            "median_pnl": 0.0,
            "std_pnl": 0.0,
            "min_pnl": 0.0,
            "max_pnl": 0.0,
            "prob_profit": 0.0,
            "prob_loss": 0.0,
            "avg_loss": 0.0,
            "max_loss": 0.0,
            "median_loss": 0.0,
            "var_95": 0.0,
            "var_99": 0.0,
            "cvar_95": 0.0,
            "cvar_99": 0.0,
            "breakeven_points": [],
            "theoretical_max_loss": None,
            "is_concentrated": False,
            "concentration_pct": 0.0,
            "most_common_pnl": None,
            "drift_measure": "risk_neutral",
            "expected_return_annual": 0.0,
        }

    def _horizon_spot_grid(
        self: "_PortfolioProtocol",
        final_spots: np.ndarray[Any, np.dtype[Any]],
        num_points: int = _HORIZON_GRID_POINTS,
    ) -> np.ndarray[Any, np.dtype[Any]]:
        """Build the spot grid the horizon is repriced on.

        Spans the full range of simulated terminal spots (no extrapolation)
        and folds in every strike inside that range, so legs settling at
        intrinsic interpolate exactly across their kink.

        Args:
            final_spots: Simulated terminal spot prices.
            num_points: Evenly-spaced base grid points across the spot range.

        Returns:
            Sorted unique grid of spot prices; a single-element array when
            every simulated spot is identical (zero-dispersion edge case).

        """
        lo = float(np.min(final_spots))
        hi = float(np.max(final_spots))
        if hi <= lo:
            return np.array([lo])
        base = np.linspace(lo, hi, num_points)
        strikes = np.array(
            [pos.option.strike_price for pos in self.positions],
            dtype=float,
        )
        in_range = strikes[(strikes > lo) & (strikes < hi)]
        return np.asarray(np.unique(np.concatenate([base, in_range])))

    def _simulate_horizon_pnls(
        self: "_PortfolioProtocol",
        final_spots: np.ndarray[Any, np.dtype[Any]],
        days_to_expiry: int,
        include_underlying: bool,
    ) -> np.ndarray[Any, np.dtype[Any]]:
        """P&L of every simulated path, repricing live legs at the horizon.

        Legs still alive at the horizon are repriced there (time-decayed, at
        the path spot) via :class:`BatchPricer`; legs expiring at/before the
        horizon settle at intrinsic. The option value is priced once on a spot
        grid (:meth:`_horizon_spot_grid`) and every path is interpolated onto
        it, so the per-path step is a single vectorized NumPy call instead of
        one QuantLib evaluation per path. Measured ~50x faster than repricing
        each path directly (≈2 ms vs ≈100 ms at 2e4 paths); the gap widens
        with path count since the grid cost is fixed.

        Args:
            final_spots: Simulated terminal spot prices at the horizon.
            days_to_expiry: Days from the valuation date to the horizon.
            include_underlying: Add the underlying mark-to-market overlay.

        Returns:
            P&L for each path, in dollars.

        """
        horizon_date = self.valuation_date + timedelta(days=days_to_expiry)
        # Options-only pricer: the underlying is an exactly-linear overlay
        # added below, so it never needs interpolating and P&L stays parity
        # with total_value() (options-only initial cost).
        pricer = BatchPricer(
            positions=self.positions,
            risk_free_rate=self.risk_free_rate,
            dividend_yield=self.dividend_yield,
            underlying_quantity=0.0,
        )
        grid = self._horizon_spot_grid(final_spots)
        grid_values = pricer.portfolio_values_at(grid, horizon_date)

        initial_cost = self.total_value()
        if len(grid) == 1:
            option_value = np.full(len(final_spots), grid_values[0])
        else:
            option_value = np.interp(final_spots, grid, grid_values)
        pnls = option_value - initial_cost

        if include_underlying and self.underlying_quantity != 0:
            pnls = pnls + self.underlying_quantity * (
                final_spots - self.spot_price
            )
        return np.asarray(pnls)

    def run_monte_carlo_simulation(  # pylint: disable=too-many-locals
        self: "_PortfolioProtocol",
        num_simulations: int = 10**5,
        include_underlying: bool = True,
        random_seed: int | None = 42,  # Set to None for true randomness
        days_to_expiry: int | None = None,
        expected_return: float | None = None,
    ) -> dict[str, Any]:
        """Run Monte Carlo simulation and store results on portfolio object.

        Generates Geometric Brownian Motion terminal spots with a local RNG,
        then reprices the book at the horizon: legs still alive are repriced
        through :class:`BatchPricer` (not valued at intrinsic), while legs
        expiring at/before the horizon settle at intrinsic.

        Args:
            num_simulations: Number of simulation paths
            include_underlying: Include underlying position in P&L
            random_seed: Random seed for reproducibility (None for true
            randomness)
            days_to_expiry: Days to expiration (uses nearest maturity if None)
            expected_return: Annualized real-world expected return of the
                underlying for the GBM drift. ``None`` (default) uses the
                risk-neutral drift (``risk_free_rate``); every probability
                output is then a risk-neutral (Q-measure) statement, flagged
                by ``results["drift_measure"] == "risk_neutral"``. Supplying a
                value makes the results real-world (P-measure), flagged
                ``"real_world"``.

        Returns:
            dict: Monte Carlo results dictionary

        """
        # 1. Determine time horizon (days to expiry)
        min_time_horizon = 1
        if days_to_expiry is None:
            if len(self.positions) > 0:
                min_maturity = min(
                    pos.option.maturity_date for pos in self.positions
                )
                days_to_expiry = max(
                    min_time_horizon,
                    (min_maturity - self.valuation_date).days,
                )
            else:
                days_to_expiry = const.CALENDAR_DAYS_PER_MONTH  # Default

        year_frac_to_expiry = days_to_expiry / const.DAYS_PER_YEAR

        # 2. Setup market parameters
        spot_price = self.spot_price
        volatility = self.volatility
        risk_free_rate = self.risk_free_rate
        dividend_yield = self.dividend_yield

        # Drift is risk-neutral (mu = r) unless a real-world expected_return is
        # supplied. The measure is recorded in the results so downstream
        # probabilities are never presented as real-world by omission.
        if expected_return is None:
            mu_annual = risk_free_rate
            drift_measure = "risk_neutral"
        else:
            mu_annual = expected_return
            drift_measure = "real_world"

        # 3. Vectorized GBM terminal spots with a *local* RNG — seeding stays
        # confined here and never perturbs the global np.random state.
        rng = np.random.default_rng(random_seed)
        z = rng.standard_normal(num_simulations)
        drift = (
            mu_annual - dividend_yield - 0.5 * volatility**2
        ) * year_frac_to_expiry
        diffusion = volatility * np.sqrt(year_frac_to_expiry) * z
        final_spots = spot_price * np.exp(drift + diffusion)

        # 4. Horizon P&L — legs still alive at the horizon are repriced there
        # (not valued at intrinsic); the per-path step is vectorized via a
        # spot grid + np.interp, so there is no Python P&L loop and no
        # per-path QuantLib call.
        simulated_pnls = self._simulate_horizon_pnls(
            final_spots,
            days_to_expiry,
            include_underlying,
        )

        # 5. Clean data
        pnls_clean = simulated_pnls[np.isfinite(simulated_pnls)]
        num_valid = len(pnls_clean)

        if num_valid == 0:
            empty = self._empty_monte_carlo_results(days_to_expiry)
            empty["drift_measure"] = drift_measure
            empty["expected_return_annual"] = mu_annual
            return empty

        # 6. Metric calculations
        expected_pnl = np.mean(pnls_clean)
        median_pnl = np.median(pnls_clean)
        std_pnl = np.std(pnls_clean)
        min_pnl = np.min(pnls_clean)
        max_pnl = np.max(pnls_clean)

        # Wing/loss ratios
        profits = pnls_clean[pnls_clean >= 0]
        losses = pnls_clean[pnls_clean < 0]
        prob_profit = len(profits) / num_valid
        prob_loss = len(losses) / num_valid

        # VaR and CVaR risk metrics
        var_95 = np.percentile(pnls_clean, 5)  # 5th percentile = 95% VaR
        var_99 = np.percentile(pnls_clean, 1)  # 1st percentile = 99% VaR
        cvar_95 = np.mean(pnls_clean[pnls_clean <= var_95])
        cvar_99 = np.mean(pnls_clean[pnls_clean <= var_99])

        # Conditional loss analysis
        if len(losses) > 0:
            avg_loss = np.mean(losses)
            max_loss = np.min(losses)  # Most negative = worst loss
            median_loss = np.median(losses)
        else:
            avg_loss = max_loss = median_loss = 0.0

        # 7. Theoretical Maximum Loss (for short options)
        theoretical_max_loss = self._calculate_theoretical_max_loss()

        # 8. Distribution analysis (for short option strategies)
        unique_rounded = np.unique(np.round(pnls_clean, 2))
        is_concentrated, concentration_pct, most_common_pnl = (
            self._analyze_concentration(pnls_clean)
        )

        # 9. Breakeven Analysis (Delegate to existing method)
        breakeven_points = self.calculate_breakeven_points(
            include_underlying=include_underlying,
        )

        results = {
            # Raw data
            "simulated_pnls": pnls_clean,
            "num_simulations": num_valid,
            "days_to_expiry": days_to_expiry,
            # Basic statistics
            "expected_pnl": expected_pnl,
            "median_pnl": median_pnl,
            "std_pnl": std_pnl,
            "min_pnl": min_pnl,
            "max_pnl": max_pnl,
            # Profit/Loss breakdown
            "prob_profit": prob_profit,
            "prob_loss": prob_loss,
            "avg_loss": avg_loss,
            "max_loss": max_loss,
            "median_loss": median_loss,
            # Risk metrics
            "var_95": var_95,
            "var_99": var_99,
            "cvar_95": cvar_95,
            "cvar_99": cvar_99,
            # Distribution characteristics
            "breakeven_points": breakeven_points,
            "is_concentrated": is_concentrated,
            "most_common_pnl": most_common_pnl,
            "concentration_pct": concentration_pct,
            "unique_values": len(unique_rounded),
            # Theoretical bounds
            "theoretical_max_loss": theoretical_max_loss,
            # Drift assumption behind every probability figure above
            "drift_measure": drift_measure,
            "expected_return_annual": mu_annual,
        }

        # Cache results on the object
        self.monte_carlo_results = results

        return results
