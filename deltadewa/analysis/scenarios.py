"""Scenario grid generation mixin for portfolio analysis."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from deltadewa.analysis.repricing import (
    MarketShock,
    MarketState,
    VolMapping,
    shocked_leg_option,
)
from deltadewa.batch_pricer import BatchPricer
from deltadewa.constants import FDGridResolution

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio

# Maps scenario_grid() metric names to BatchPricer greek names.
# "net_delta" maps to "delta" because BatchPricer.portfolio_greeks_at()
# already includes the underlying position in the "delta" array.
_METRIC_TO_GREEK: dict[str, str] = {
    "delta": "delta",
    "net_delta": "delta",
    "gamma": "gamma",
    "vega": "vega",
    "theta": "theta",
    "rho": "rho",
}

# Maps scenario_grid_spot_vol() metric names to the OptionValuation method
# each leg is repriced through. "pnl" and "value" both price the leg
# ("pnl" post-processes the summed value below); "net_delta" reads the same
# per-leg delta as "delta" and adds underlying_quantity afterwards.
_SPOT_VOL_METRIC_TO_ATTR: dict[str, str] = {
    "pnl": "price",
    "value": "price",
    "delta": "delta",
    "net_delta": "delta",
    "gamma": "gamma",
    "vega": "vega",
    "theta": "theta",
    "rho": "rho",
}


class ScenariosMixin:
    """Mixin for scenario grid generation.

    Provides methods for calculating portfolio metrics across 2D grids
    of spot prices and time, or spot prices and volatilities.
    """

    if TYPE_CHECKING:
        portfolio: "OptionPortfolio"

    def _create_batch_pricer(
        self,
        use_closed_form: bool = False,
    ) -> BatchPricer:
        """Create a BatchPricer instance from the current portfolio state.

        This serves as a 'shadow' copy of the pricing engines that we can
        manipulate safely during calculations without affecting the main
        portfolio state.
        """
        return BatchPricer(
            positions=self.portfolio.positions,
            risk_free_rate=self.portfolio.risk_free_rate,
            dividend_yield=self.portfolio.dividend_yield,
            underlying_quantity=self.portfolio.underlying_quantity,
            # Use FAST for scenario sweeps to balance speed and accuracy
            grid_resolution=FDGridResolution.FAST,
            use_closed_form=use_closed_form,
        )

    def _calculate_portfolio_value_at(
        self,
        spot: float,
        valuation_date: datetime,
        pricer: BatchPricer | None = None,
    ) -> float:
        """Calculate total portfolio value at given spot and date.

        Optimized to use an existing BatchPricer if provided, avoiding
        expensive QuantLib engine reconstruction.

        Args:
            spot: Spot price to use for valuation
            valuation_date: Date to use for valuation
            pricer: Optional existing BatchPricer instance for performance

        Returns:
            Total portfolio value (options + underlying)

        """
        # If a pricer is provided, use its optimized single-point lookup
        # This reuses the pre-built QuantLib engines
        if pricer:
            # We treat the single spot as a 1-item array
            values = pricer.portfolio_values_at(
                np.array([spot]),
                valuation_date,
            )
            return float(values[0])

        # Fallback to creating a temporary pricer if none provided
        # This is still cleaner than the old loop as it delegates to the
        # optimized class
        temp_pricer = self._create_batch_pricer()
        return float(
            temp_pricer.portfolio_values_at(
                np.array([spot]),
                valuation_date,
            )[0],
        )

    def _calculate_pnl_at_expiry_vectorized(
        self,
        spot_scenarios: np.ndarray[Any, np.dtype[Any]],
        include_underlying: bool = True,
    ) -> np.ndarray[Any, np.dtype[Any]]:
        """Calculate P&L at expiry using vectorized NumPy operations.

        This method should only be used for at-expiry calculations where all
        positions have expired (days_to_maturity <= 0). At expiry, options have
        only intrinsic value and no time value, so volatility doesn't affect
        the results.

        This is much faster than iterating for large grids because:
        - Intrinsic value is element-wise max operation
        - All positions computed simultaneously across all spots
        - NumPy broadcasting handles grid expansion

        Delegates to portfolio implementation for consistency.

        Args:
            spot_scenarios: Array of spot prices to evaluate
            include_underlying: Whether to include underlying position P&L

        Returns:
            np.ndarray of P&L values for each spot scenario

        """
        return self.portfolio.vectorized_pnl_at_expiry(
            spot_scenarios,
            include_underlying=include_underlying,
        )

    def scenario_grid(
        self,
        spot_scenarios: np.ndarray[Any, np.dtype[Any]],
        time_points: list[datetime],
        metric: str = "pnl",
        baseline_spot: float | None = None,
        baseline_valuation_date: datetime | None = None,
    ) -> pd.DataFrame:
        """Calculate portfolio metrics across 2D grid of spot prices and time.

        Useful for heatmap generation showing how portfolio evolves across
        different price levels and time horizons.

        Args:
            spot_scenarios: Array of spot prices to test
            time_points: list of valuation dates to test
            metric: Metric to calculate ('pnl', 'value', 'delta', 'net_delta',
            'gamma', 'vega', 'theta')
            baseline_spot: Spot price for P&L baseline (default: current
            portfolio spot)
            baseline_valuation_date: Valuation date for P&L baseline (default:
            current portfolio date)

        Returns:
            DataFrame with columns: spot_price, valuation_date, metric_value

        """
        results: list[dict[str, Any]] = []
        original_spot = self.portfolio.spot_price
        original_date = self.portfolio.valuation_date

        # Setup defaults and validate
        if baseline_spot is None:
            baseline_spot = original_spot
        if baseline_spot is None:
            raise ValueError(
                "Portfolio spot price is not set for baseline calculation.",
            )

        if baseline_valuation_date is None:
            baseline_valuation_date = original_date
        if baseline_valuation_date is None:
            raise ValueError(
                "Portfolio valuation date is not set for baseline calculation.",
            )

        # Create the BatchPricer ONCE.
        # This builds the QuantLib engines for all positions one time.
        pricer = self._create_batch_pricer()

        # Calculate baseline value efficiently using the pricer
        baseline_value = 0.0
        if metric == "pnl":
            baseline_value = self._calculate_portfolio_value_at(
                baseline_spot,
                baseline_valuation_date,
                pricer=pricer,
            )

        # Main Grid Loop
        for time_point in time_points:
            days_forward = (time_point - original_date).days

            # STRATEGY 1: Efficient Value/PnL (No Greeks)
            if metric in ("pnl", "value"):
                # BatchPricer is optimized for this exact operation
                portfolio_values = pricer.portfolio_values_at(
                    spot_scenarios,
                    time_point,
                )

                # Vectorized construction of result rows
                results.extend(
                    {
                        "spot_price": spot,
                        "valuation_date": time_point,
                        "days_forward": days_forward,
                        "metric": metric,
                        "value": (
                            (portfolio_values[j] - baseline_value)
                            if metric == "pnl"
                            else portfolio_values[j]
                        ),
                    }
                    for j, spot in enumerate(spot_scenarios)
                )

            # STRATEGY 2: Greeks via BatchPricer (no portfolio state mutations)
            else:
                greek_name = _METRIC_TO_GREEK.get(metric)
                if greek_name is None:
                    raise ValueError(
                        f"Unsupported metric: {metric}. "
                        f"Supported: pnl, value, delta, net_delta, "
                        f"gamma, vega, theta, rho",
                    )

                greek_arrays = pricer.portfolio_greeks_at(
                    spot_scenarios,
                    time_point,
                    greeks=(greek_name,),
                )
                results.extend(
                    {
                        "spot_price": spot,
                        "valuation_date": time_point,
                        "days_forward": days_forward,
                        "metric": metric,
                        "value": greek_arrays[greek_name][j],
                    }
                    for j, spot in enumerate(spot_scenarios)
                )

        # Not dead code: this is restore-only (it never sets a shocked
        # value, so there is no window where a mid-loop read observes a
        # wrong portfolio state, unlike the M1.5 stress.py:897 bug). It is
        # still required, though — BatchPricer prices via scratch
        # OptionValuation objects (analysis/scenarios.py never mutates
        # self.portfolio during the loop above), but constructing one of
        # those writes the *global* QuantLib Settings.instance()
        # .evaluationDate singleton (valuation.py:214). Without this call
        # that global is left dirty at the last time_point swept, even
        # though every position object this analyzer owns still reports
        # its own correct, untouched valuation_date.
        self.portfolio.update_market_conditions(
            spot_price=original_spot,
            valuation_date=original_date,
        )

        return pd.DataFrame(results)

    def scenario_grid_spot_vol(
        self,
        spot_scenarios: np.ndarray[Any, np.dtype[Any]],
        vol_scenarios: np.ndarray[Any, np.dtype[Any]],
        *,
        vol_mapping: VolMapping,
        metric: str = "pnl",
        baseline_value: float | None = None,
        days_forward: int = 0,
    ) -> pd.DataFrame:
        """Calculate metrics across 2D grid of spot prices and volatilities.

        Pure — never mutates the portfolio (M2.1). Every cell reprices
        through fresh, scratch ``OptionValuation`` objects
        (:func:`~deltadewa.analysis.repricing.shocked_leg_option`) against
        one base :class:`~deltadewa.analysis.repricing.MarketState`
        snapshotted once at the top of this call, so there is no
        mutate-then-restore window in which a concurrent read of the
        portfolio (or an exception mid-sweep) could observe a shocked value.

        For P&L at expiry (intrinsic value), uses a vectorized calculation
        for maximum performance — volatility doesn't affect intrinsic value,
        so this shortcut is valid under any ``vol_mapping``.

        Args:
            spot_scenarios: Array of spot prices to test.
            vol_scenarios: Array of *absolute target average volatility
                levels* to test — not a bump. Each level is converted to a
                per-mapping ``vol_shock`` (``level - state.avg_volatility``,
                the base vega-weighted average) once per vol slice; that
                level-to-bump conversion is what previously hid a 25% gap
                against the crash-conditional mapping on a skewed book.
            vol_mapping: **Required.** The per-leg vol-shock -> sigma' rule
                — e.g.
                :func:`~deltadewa.analysis.repricing.proportional_vol` for
                the general grid, or
                :func:`~deltadewa.analysis.crash_repricing.crash_skew_vol`
                to match the crash gauge exactly. Never defaulted: a caller
                that forgets it would silently render a different pricing
                model than intended, and disagree with whatever surface it
                was meant to match.
            metric: Metric to calculate ('pnl', 'value', 'delta', 'net_delta',
                'gamma', 'vega', 'theta', 'rho').
            baseline_value: Portfolio value for P&L baseline (default:
                current options-only value).
            days_forward: Calendar days forward from the portfolio's
                valuation date. Defaults to ``0`` (today) — genuinely
                neutral, unlike the vol/spot dials.

        Returns:
            DataFrame with columns: spot_price, volatility, value.

        Raises:
            ValueError: *metric* is not one of the supported names.

        """
        if metric not in _SPOT_VOL_METRIC_TO_ATTR:
            raise ValueError(
                f"Unsupported metric: {metric}. "
                f"Supported: pnl, value, delta, net_delta, "
                f"gamma, vega, theta, rho",
            )

        state = MarketState.from_portfolio(self.portfolio)
        positions = self.portfolio.positions
        underlying_quantity = self.portfolio.underlying_quantity

        if baseline_value is None:
            baseline_value = self.portfolio.total_value()

        # days_forward alone determines the shocked date; it does not vary
        # per cell, so resolve it once via a throwaway shock rather than
        # duplicating MarketShock.shocked_valuation_date's arithmetic here.
        shocked_date = MarketShock(
            spot_shock=0.0,
            vol_shock=0.0,
            days_forward=days_forward,
        ).shocked_valuation_date(state)

        results: list[dict[str, Any]] = []

        # Optimization: vectorized PnL at expiry, valid under any mapping.
        if metric == "pnl":
            # Check if all positions are at expiry (days_to_maturity == 0)
            # at the SHOCKED date, not today's — a days_forward grid that
            # lands on expiry gets the same shortcut a today grid would.
            all_at_expiry = all(
                (pos.option.maturity_date - shocked_date).days == 0
                for pos in positions
            )
            if all_at_expiry:
                pnl_values = self._calculate_pnl_at_expiry_vectorized(
                    spot_scenarios,
                    include_underlying=True,
                )
                for vol in vol_scenarios:
                    for j, spot in enumerate(spot_scenarios):
                        results.append(
                            {
                                "spot_price": spot,
                                "volatility": vol,
                                "value": pnl_values[j],
                            },
                        )
                return pd.DataFrame(results)

        attr = _SPOT_VOL_METRIC_TO_ATTR[metric]

        for vol in vol_scenarios:
            vol_shock = float(vol) - state.avg_volatility

            for spot in spot_scenarios:
                # spot_shock is carried on the shock for mappings that may
                # want it (introspection, future dials); pricing below uses
                # *spot* directly rather than re-deriving it via
                # shock.shocked_spot(state) — one division-then-
                # multiplication round trip per cell is a needless source of
                # floating-point noise when the exact value is already in
                # hand.
                shock = MarketShock(
                    spot_shock=float(spot) / state.spot_price - 1.0,
                    vol_shock=vol_shock,
                    days_forward=days_forward,
                )

                total = 0.0
                for position in positions:
                    volatility = vol_mapping(position, state, shock)
                    option = shocked_leg_option(
                        position,
                        state,
                        spot=float(spot),
                        volatility=volatility,
                        valuation_date=shocked_date,
                    )
                    total += (
                        getattr(option, attr)()
                        * position.quantity
                        * position.contract_size
                    )

                if metric == "net_delta":
                    total += underlying_quantity
                elif metric == "pnl":
                    underlying_pnl = (
                        spot - state.spot_price
                    ) * underlying_quantity
                    total = (total - baseline_value) + underlying_pnl

                results.append(
                    {
                        "spot_price": spot,
                        "volatility": vol,
                        "value": total,
                    },
                )

        return pd.DataFrame(results)
