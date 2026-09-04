"""Scenario grid generation mixin for portfolio analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

import numpy as np
import pandas as pd

from deltadewa.analysis.repricing import (
    MarketShock,
    MarketState,
    VolMapping,
    flat_bump_vol,
    shocked_leg_option,
)
from deltadewa.batch_pricer import BatchPricer
from deltadewa.clock import days_between
from deltadewa.constants import FDGridResolution

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition

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

# Handbook Part X §13, Delta Drift Metric
# (https://qwertytam.github.io/deltadewa-handbook/0.1/part-10/tier-4-tactical-optional-trading-metrics/#delta-drift-metric):
# the shock is fixed at exactly -5% -- the handbook's own worked example, not
# a dial and not the IPS crash_scenario_pct (a much larger,
# separately-configured move). A different percentage would be a different
# metric, so this is a constant, not a parameter.
#
# Pinned to handbook version 0.1 rather than tracking the root, for the reason
# stated on the line above: the constant *is* the handbook's figure. If the
# worked example were rewritten around a different shock, this would need to
# become a different metric rather than quietly cite a page that no longer says
# -5%. Drop the /0.1/ segment for the current page.
DELTA_DRIFT_SHOCK_PCT: Final[float] = -5.0


@dataclass(frozen=True)
class DeltaDriftLeg:
    """One option leg's contribution to the book's delta drift.

    Attributes:
        position: The leg itself, for labelling (strike, type, maturity) --
            the same "carry the position, not just its id" convention
            :class:`~deltadewa.analysis.roll_status.RollStatusRecord` uses.
        delta_now: The leg's position delta (shares) at today's spot.
        delta_shocked: The leg's position delta at spot
            ``DELTA_DRIFT_SHOCK_PCT``.
        drift: ``delta_shocked - delta_now``.

    """

    position: OptionPosition
    delta_now: float
    delta_shocked: float
    drift: float


@dataclass(frozen=True)
class DeltaDrift:
    """Handbook Part X §13: shocked-minus-current hedge delta.

    Handbook `Delta Drift Metric
    <https://qwertytam.github.io/deltadewa-handbook/0.1/part-10/tier-4-tactical-optional-trading-metrics/#delta-drift-metric>`_::

        Δ0 = hedge delta today
        Δ5 = hedge delta if market falls 5%
        Delta Drift = Δ5 - Δ0

    That link is pinned to handbook version 0.1: the three lines above are
    transcribed from it, including the 5% that ``DELTA_DRIFT_SHOCK_PCT``
    hardcodes, so the citation has to keep naming the statement they came from.
    Drop the ``/0.1/`` segment for the current page.

    "Hedge delta" is the **option legs' delta only** -- the underlying
    equity leg is excluded, the same hedge-only convention
    :mod:`~deltadewa.analysis.crash_repricing` uses for crash convexity.
    This answers "how fast does the *hedge* respond to an early-stage
    decline", a different question from Part X #10's net-delta scalar
    (options plus underlying), which the ``/design`` net-delta readout
    already covers -- do not conflate the two.

    Attributes:
        delta_now: Net hedge delta today (options only).
        delta_shocked: Net hedge delta at spot ``DELTA_DRIFT_SHOCK_PCT``.
        drift: ``delta_shocked - delta_now``, signed. A tail-put book's
            drift is expected to be negative -- delta becomes more negative
            as the market falls, which is the hedge doing its job.
        shock_pct: The shock applied, verbatim (``DELTA_DRIFT_SHOCK_PCT``),
            echoed back so a renderer never has to re-import the constant.
        legs: Per-leg breakdown, in portfolio position order.
            ``sum(leg.drift for leg in legs) == drift`` by construction.

    """

    delta_now: float
    delta_shocked: float
    drift: float
    shock_pct: float
    legs: tuple[DeltaDriftLeg, ...]


def _leg_delta_at(
    position: OptionPosition,
    state: MarketState,
    shock: MarketShock,
) -> float:
    """One leg's position delta (shares) at *shock*, volatility held flat.

    Uses :func:`~deltadewa.analysis.repricing.flat_bump_vol` with
    ``shock.vol_shock == 0.0`` so the reading isolates delta's own
    path-dependence on spot, with no vol-regime change riding along.
    """
    option = shocked_leg_option(
        position,
        state,
        spot=shock.shocked_spot(state),
        volatility=flat_bump_vol(position, state, shock),
        valuation_date=shock.shocked_valuation_date(state),
    )
    return option.delta() * position.quantity * position.contract_size


class ScenariosMixin:
    """Mixin for scenario grid generation.

    Provides methods for calculating portfolio metrics across 2D grids
    of spot prices and time, or spot prices and volatilities.
    """

    if TYPE_CHECKING:
        portfolio: OptionPortfolio

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

    def calculate_delta_drift(self) -> DeltaDrift:
        """Handbook Part X §13: hedge delta at spot -5% minus hedge delta now.

        Reprices through the shared shock primitives in ``repricing.py``
        (M2.1) -- the same ones the crash gauge and the 2D scenario grid
        use -- rather than a third repricing path. See :class:`DeltaDrift`
        for the exact handbook definition and the hedge-only convention.

        Returns:
            The book's hedge delta today and at ``DELTA_DRIFT_SHOCK_PCT``,
            their signed difference, and each option leg's own contribution.

        Raises:
            ValueError: The book has no option positions -- there is no
                hedge delta to shock.

        """
        if not self.portfolio.positions:
            msg = "delta drift requires at least one option position to shock"
            raise ValueError(msg)

        state = MarketState.from_portfolio(self.portfolio)
        shock = MarketShock(
            spot_shock=DELTA_DRIFT_SHOCK_PCT / 100.0,
            vol_shock=0.0,
        )

        legs: list[DeltaDriftLeg] = []
        delta_now = 0.0
        delta_shocked = 0.0
        for position in self.portfolio.positions:
            now = position.position_delta()
            shocked = _leg_delta_at(position, state, shock)
            delta_now += now
            delta_shocked += shocked
            legs.append(
                DeltaDriftLeg(
                    position=position,
                    delta_now=now,
                    delta_shocked=shocked,
                    drift=shocked - now,
                ),
            )

        return DeltaDrift(
            delta_now=delta_now,
            delta_shocked=delta_shocked,
            drift=delta_shocked - delta_now,
            shock_pct=DELTA_DRIFT_SHOCK_PCT,
            legs=tuple(legs),
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
                days_between(shocked_date, pos.option.maturity_date) == 0
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
                elif metric == "value":
                    # #329: STRESS_METRICS["value"]'s label says "incl.
                    # underlying" -- without this, this heatmap's "value"
                    # metric silently dropped the underlying leg (unlike
                    # this same loop's "pnl" branch above, and unlike
                    # scenario_grid's BatchPricer-backed "value", which
                    # both already include it), making that label false
                    # for this heatmap specifically.
                    total += underlying_quantity * spot

                results.append(
                    {
                        "spot_price": spot,
                        "volatility": vol,
                        "value": total,
                    },
                )

        return pd.DataFrame(results)
