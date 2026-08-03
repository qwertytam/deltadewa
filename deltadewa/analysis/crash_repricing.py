"""Shared crash-state repricing per ``docs/repricing-methodology.md`` §1-3.

Single source of the crash basis for every panel: the health convexity gauge
(:meth:`HealthMixin.calculate_crash_convexity_pct`), the ``crash_payoff``
payoff ratios, and the ``NetHedgeSummary`` crash-convexity ladder all reprice
the option legs *hedge-only* at the crash spot plus a per-leg additive vol shock
through these helpers, so every surface shares one basis (fixes C1/C4/Mo1).

The crash state (§2):

* crash spot ``S_crash = S0 * (1 + crash_move)`` — ``crash_move`` is a signed
  decimal (e.g. ``-0.25`` for a 25% decline);
* per-leg vol ``sigma_i + vol_shock + steepening_i`` — ``vol_shock`` is a flat
  additive decimal (e.g. ``+0.15``) from ``IpsConvexity.crash_vol_shock`` on
  every leg, and ``steepening_i`` is the deep-OTM skew add-on for that leg,
  capped at ``IpsConvexity.skew_steepening`` at the leg's own ~10-delta wing
  (M1.7; ``0.0`` keeps the flat bump);
* rates, dividends, and time-to-maturity held at today's values — the crash is
  an instantaneous jump at the current valuation date;
* the underlying / equity leg is **excluded** — convexity is a hedge-only
  metric.

Those four pricing inputs travel together as a :class:`CrashShock`, built from
policy with :meth:`CrashShock.from_ips`. The band (``target_min_pct`` /
``target_max_pct``) is deliberately *not* on it — policy and pricing stay
separable, so omitting the band can never quietly change what is priced.

Legs are repriced with the existing
:class:`~deltadewa.valuation.OptionValuation` engine (European exercise uses the
analytic Black-Scholes engine); no new pricer is introduced.

As of M2.1, the actual per-leg repricing and the crash-skew vol-shock mapping
live in :mod:`deltadewa.analysis.repricing` and :func:`crash_skew_vol` — the
same primitive and pluggable-mapping vocabulary the general 2D scenario grid
(``scenarios.py::scenario_grid_spot_vol``) now shares, so a shared shock
config (:meth:`CrashShock.to_shock` / :meth:`CrashShock.vol_mapping`)
reprices identically through either path. This module now supplies the
crash-conditional *mapping* and the policy-facing :class:`CrashShock`
adapter; it is no longer a second repricing engine.
"""

from __future__ import annotations

import dataclasses
import functools
import math
from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import brentq

from deltadewa.analysis.repricing import (
    MarketShock,
    MarketState,
    VolMapping,
    flat_bump_vol,
    reprice_leg,
    reprice_legs_at,
    reprice_portfolio,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.valuation import OptionValuation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from deltadewa.ips_config import IpsConvexity
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition

# Bracket for the wing-strike root solve: from deep OTM (put-delta magnitude
# ~0) up to just below ATM (magnitude ~0.5). The ~10-delta wing sits well
# inside this range at every supported tenor.
_WING_STRIKE_LO_FRAC = 0.05
_WING_STRIKE_HI_FRAC = 0.9999


@dataclasses.dataclass(frozen=True)
class CrashShock:
    """The four crash-state **pricing** inputs, travelling as one value.

    Bundles the crash basis so it cannot be split up en route to the pricer:
    every surface that reprices at the crash state takes one of these, and
    :meth:`from_ips` is the intended way to build it. Before this object the
    scalars were threaded individually and ``skew_reference_delta`` was quietly
    dropped by the book surfaces, which then priced against the primitive's own
    ``0.10`` default — so tuning the IPS anchor moved the sizing workbench and
    not the gauges.

    **Pricing only — deliberately not the IPS target band.** ``target_min_pct``
    / ``target_max_pct`` stay on :class:`~deltadewa.ips_config.IpsConvexity` and
    travel their own path (M1.5): a caller that omits policy must fail the band
    comparison outright, never silently reprice at a different crash state.

    Every field is required. There is no default anywhere on this object, so no
    surface can reprice against a fabricated crash basis by omission — the
    fail-loud discipline ``crash_vol_shock`` has had since M1.4/M1.5, now
    covering the whole basis.

    Attributes:
        crash_scenario_pct: Signed crash move as a percent of spot (e.g.
            ``-25.0`` for a 25% decline).
        crash_vol_shock: Flat additive vol bump as a decimal (e.g. ``0.15``),
            applied to every leg's own today-vol.
        skew_steepening: Extra vol reached at the deep-OTM wing on top of
            ``crash_vol_shock`` (M1.6/M1.7). ``0.0`` keeps the flat bump.
        skew_reference_delta: Put-delta magnitude of the wing the steepening is
            anchored to (e.g. ``0.10``). Only consulted when
            ``skew_steepening`` is non-zero.

    """

    crash_scenario_pct: float
    crash_vol_shock: float
    skew_steepening: float
    skew_reference_delta: float

    @property
    def crash_move(self) -> float:
        """Signed crash move as a decimal — ``crash_scenario_pct / 100``.

        Returns:
            The multiplier offset the crash spot is built from, e.g. ``-0.25``.

        """
        return self.crash_scenario_pct / 100.0

    @classmethod
    def from_ips(cls, convexity: IpsConvexity) -> CrashShock:
        """Extract the crash pricing basis from IPS policy.

        A pure projection of the four pricing fields — the target band is
        deliberately left behind.

        Args:
            convexity: The program's ``IpsConvexity`` policy block.

        Returns:
            The crash basis every surface should price against.

        """
        return cls(
            crash_scenario_pct=convexity.crash_scenario_pct,
            crash_vol_shock=convexity.crash_vol_shock,
            skew_steepening=convexity.skew_steepening,
            skew_reference_delta=convexity.skew_reference_delta,
        )

    def at_pct(self, crash_scenario_pct: float) -> CrashShock:
        """Re-aim this same vol basis at a different crash depth.

        For shock sweeps and payoff ladders, which price many depths against
        one basis. Carrying the vol knobs along by construction is the point:
        walking the grid cannot silently drop the skew.

        Args:
            crash_scenario_pct: Signed crash move as a percent of spot.

        Returns:
            A copy at the new depth, vol shock and skew unchanged.

        """
        return dataclasses.replace(
            self,
            crash_scenario_pct=crash_scenario_pct,
        )

    def to_shock(self, *, days_forward: int = 0) -> MarketShock:
        """Project this basis onto the general :class:`MarketShock` dials.

        Args:
            days_forward: Calendar days forward from today. Defaults to
                ``0`` — an instantaneous crash, matching this basis's own
                assumption (§2: "rates, dividends, and time-to-maturity held
                at today's values").

        Returns:
            The spot and vol dials this basis implies. Pair with
            :meth:`vol_mapping` to reproduce :func:`crash_hedge_value`
            exactly through the general primitive
            (:func:`~deltadewa.analysis.repricing.reprice_portfolio`).

        """
        return MarketShock(
            spot_shock=self.crash_move,
            vol_shock=self.crash_vol_shock,
            days_forward=days_forward,
        )

    def vol_mapping(self) -> VolMapping:
        """Return the skew-aware vol mapping this basis's calibration implies.

        Returns:
            :func:`crash_skew_vol` built from this basis's skew fields. Pair
            with :meth:`to_shock` — the gauge and any surface reproducing it
            (e.g. the monitor's crash-anchored explorer) construct literally
            the same pair, which is what makes agreement structural rather
            than conventional.

        """
        return crash_skew_vol(
            skew_steepening=self.skew_steepening,
            skew_reference_delta=self.skew_reference_delta,
        )


def _reprice_leg(
    position: OptionPosition,
    portfolio: OptionPortfolio,
    spot: float,
    volatility: float,
) -> float:
    """Total value of one option leg repriced at *spot* and *volatility*.

    Original-signature shim over
    :func:`~deltadewa.analysis.repricing.reprice_leg` (M2.1). The general,
    mapping-agnostic primitive now lives in
    :mod:`deltadewa.analysis.repricing`; :func:`hedge_value` and
    :func:`crash_hedge_value` call it directly. This wrapper exists only so
    ``tests/test_analysis/test_crash_repricing.py``, which calls this
    private helper directly, is unaffected by the extraction. Does not
    mutate portfolio state.

    Args:
        position: Option leg to reprice.
        portfolio: Portfolio supplying rate, dividend, and valuation date.
        spot: Crash spot to price at.
        volatility: Shocked volatility to price at.

    Returns:
        ``price * quantity * contract_size`` in dollars (signed by quantity).

    """
    state = MarketState.from_portfolio(portfolio)
    return reprice_leg(
        position,
        state,
        spot=spot,
        volatility=volatility,
        valuation_date=portfolio.valuation_date,
    )


@functools.cache
def _solve_wing_strike(
    *,
    spot: float,
    maturity_date: datetime,
    volatility: float,
    risk_free_rate: float,
    dividend_yield: float,
    valuation_date: datetime,
    anchor_delta: float,
) -> float:
    """Strike whose European put-delta magnitude equals *anchor_delta*.

    The per-leg skew anchor: the ~10-delta wing computed at *this leg's* own
    tenor and today-vol — a market-skew reference independent of what else the
    book holds. Solved with :func:`scipy.optimize.brentq` on
    ``[spot * 0.05, spot * 0.9999]``; the put-delta magnitude rises
    monotonically from ~0 (deep OTM) to ~0.5 (ATM), so the anchor is bracketed
    for any ``0 < anchor_delta < 0.5``.

    Memoised: the wing depends only on today's state, never on ``crash_move``,
    so a whole shock grid solves each leg's wing once.

    Args:
        spot: Today's underlying spot.
        maturity_date: The leg's expiry.
        volatility: The leg's today implied vol.
        risk_free_rate: Portfolio risk-free rate.
        dividend_yield: Portfolio dividend yield.
        valuation_date: Portfolio valuation date.
        anchor_delta: Target put-delta magnitude (e.g. ``0.10``).

    Returns:
        The wing strike ``K_ref`` (below spot).

    Raises:
        ValueError: When *anchor_delta* is not bracketed on the search
            interval — the wing is unsolvable, so the skew must not silently
            fall back to a flat bump.

    """

    def _abs_put_delta_gap(strike: float) -> float:
        put = OptionValuation(
            spot_price=spot,
            strike_price=strike,
            maturity_date=maturity_date,
            volatility=volatility,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
            option_type=OptionType.PUT,
            valuation_date=valuation_date,
            exercise_style=ExerciseStyle.EUROPEAN,
        )
        return abs(put.delta()) - anchor_delta

    lo = spot * _WING_STRIKE_LO_FRAC
    hi = spot * _WING_STRIKE_HI_FRAC
    if _abs_put_delta_gap(lo) >= 0.0 or _abs_put_delta_gap(hi) <= 0.0:
        raise ValueError(
            f"crash skew anchor delta {anchor_delta} is not bracketed on "
            f"[{lo:.2f}, {hi:.2f}] at this tenor/vol; cannot solve the wing",
        )
    return float(brentq(_abs_put_delta_gap, lo, hi, xtol=0.01, maxiter=100))


@dataclasses.dataclass(frozen=True)
class _CrashSkewVolMapping:
    """:data:`VolMapping` capturing the M1.6/M1.7 skew calibration.

    ``sigma_i + vol_shock`` for calls and ATM/ITM puts. For an OTM put the
    crash vol adds ``min(skew_steepening, slope * ln(S/K))`` where
    ``slope = skew_steepening / ln(S / K_ref)`` and ``K_ref`` is the leg's own
    ~``skew_reference_delta`` wing (:func:`_solve_wing_strike`). The extra vol
    is thus ``skew_steepening`` exactly at the wing and interpolates linearly
    (in log-moneyness) below it — never extrapolated past the calibrated wing
    (the cap). The anchor is per-leg, so a leg's crash vol never depends on what
    else the book holds.

    When ``skew_steepening`` is ``0.0`` this returns exactly
    ``position.option.volatility + shock.vol_shock`` — the flat-bump
    expression (identical to
    :func:`~deltadewa.analysis.repricing.flat_bump_vol`) — and solves no wing,
    so the disabled knob reproduces every prior value bit-for-bit.

    Always anchors the wing at *state*'s spot and valuation date — i.e. at
    today's surface, even when the shock carries a nonzero ``days_forward``.
    The skew calibration is a property of today's market, not of the scenario
    being explored.

    Attributes:
        skew_steepening: Extra vol reached at the deep-OTM wing on top of
            ``vol_shock``. ``0.0`` keeps the flat bump.
        skew_reference_delta: Put-delta magnitude of the wing the steepening
            is anchored to. Only consulted when ``skew_steepening`` is
            non-zero.

    """

    skew_steepening: float
    skew_reference_delta: float

    def __call__(
        self,
        position: OptionPosition,
        state: MarketState,
        shock: MarketShock,
    ) -> float:
        """Shocked crash vol for one leg. See the class docstring.

        Args:
            position: Option leg to shock.
            state: The base (pre-shock) market state — spot and valuation
                date the moneyness and wing solve are measured against.
            shock: The shock being applied; only ``vol_shock`` is read (the
                spot dial moves the spot, not the vol).

        Returns:
            The leg's shocked volatility as a decimal.

        """
        base = position.option.volatility + shock.vol_shock
        if math.isclose(self.skew_steepening, 0.0, abs_tol=1e-9):
            return base
        if position.option.option_type != OptionType.PUT:
            return base
        strike = position.option.strike_price
        if strike >= state.spot_price:
            return base
        k_ref = _solve_wing_strike(
            spot=state.spot_price,
            maturity_date=position.option.maturity_date,
            volatility=position.option.volatility,
            risk_free_rate=state.risk_free_rate,
            dividend_yield=state.dividend_yield,
            valuation_date=state.valuation_date,
            anchor_delta=self.skew_reference_delta,
        )
        slope = self.skew_steepening / math.log(state.spot_price / k_ref)
        extra = min(
            self.skew_steepening,
            slope * math.log(state.spot_price / strike),
        )
        return base + extra


def crash_skew_vol(
    *,
    skew_steepening: float,
    skew_reference_delta: float,
) -> VolMapping:
    """Build the crash-conditional vol mapping (M1.6/M1.7/M2.1).

    A factory, not a ready singleton like
    :func:`~deltadewa.analysis.repricing.flat_bump_vol` /
    :func:`~deltadewa.analysis.repricing.proportional_vol`, because it
    carries runtime configuration — the skew calibration. Returns a frozen
    dataclass rather than a closure so two mappings built from the same
    calibration are equal and equally hashable, which the scenario cache
    relies on for correct cache keys across independent renders.

    Args:
        skew_steepening: Extra vol reached at the deep-OTM wing on top of the
            shock's flat bump. ``0.0`` keeps the flat bump.
        skew_reference_delta: Put-delta magnitude of the wing the steepening
            is anchored to.

    Returns:
        A :data:`~deltadewa.analysis.repricing.VolMapping` implementing the
        skew-aware crash vol.

    """
    return _CrashSkewVolMapping(
        skew_steepening=skew_steepening,
        skew_reference_delta=skew_reference_delta,
    )


def _leg_crash_vol(
    position: OptionPosition,
    *,
    spot: float,
    risk_free_rate: float,
    dividend_yield: float,
    valuation_date: datetime,
    shock: CrashShock,
) -> float:
    """Shocked crash vol for one leg: flat bump plus a capped wing steepening.

    Original-signature shim over the extracted :func:`crash_skew_vol` mapping
    (M2.1); kept so ``tests/test_analysis/test_crash_repricing.py``, which
    calls this private helper directly, is unaffected by the extraction. The
    real implementation is :class:`_CrashSkewVolMapping`.

    Args:
        position: Option leg to shock.
        spot: Today's underlying spot the moneyness is measured against.
        risk_free_rate: Portfolio risk-free rate (for the wing solve).
        dividend_yield: Portfolio dividend yield (for the wing solve).
        valuation_date: Portfolio valuation date (for the wing solve).
        shock: The crash basis. Only its vol fields are read here — the depth
            (``crash_scenario_pct``) moves the spot, not the vol.

    Returns:
        The leg's shocked volatility as a decimal.

    """
    state = MarketState(
        spot_price=spot,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        valuation_date=valuation_date,
        avg_volatility=0.0,  # crash_skew_vol never reads avg_volatility
    )
    mapping = crash_skew_vol(
        skew_steepening=shock.skew_steepening,
        skew_reference_delta=shock.skew_reference_delta,
    )
    return mapping(
        position,
        state,
        MarketShock(spot_shock=0.0, vol_shock=shock.crash_vol_shock),
    )


def crash_hedge_value(
    portfolio: OptionPortfolio,
    *,
    shock: CrashShock,
    positions: Sequence[OptionPosition] | None = None,
) -> float:
    """Hedge-only value of the option legs repriced at the crash state (§2-3).

    Excludes the underlying / equity position. Full repriced option value —
    not intrinsic, not value at expiry.

    Routes through the shared, mapping-agnostic
    :func:`~deltadewa.analysis.repricing.reprice_portfolio` primitive, paired
    with *shock*'s own :meth:`CrashShock.to_shock` /
    :meth:`CrashShock.vol_mapping` — the same pair any surface reproducing
    this value (e.g. the monitor's crash-anchored explorer) must construct
    for the two to agree structurally rather than by convention.

    Args:
        portfolio: Portfolio to evaluate.
        shock: The crash basis — depth, flat vol bump, and wing steepening with
            its anchor. **Required, with no default**: the crash state is never
            inferred, so no surface can reprice against a basis it did not
            state. Build it with :meth:`CrashShock.from_ips`.
        positions: Legs to price. Defaults to every position in the portfolio;
            pass a subset (e.g. the long puts) to value part of the book.

    Returns:
        Summed repriced value of the selected option legs, in dollars.

    """
    return reprice_portfolio(
        portfolio,
        shock=shock.to_shock(),
        vol_mapping=shock.vol_mapping(),
        positions=positions,
    )


def hedge_value(
    portfolio: OptionPortfolio,
    *,
    positions: Sequence[OptionPosition] | None = None,
) -> float:
    """Today's hedge-only option-leg value (no crash move, no vol shock).

    The ``V_today`` term of the convexity ratio: each leg at today's spot and
    its own today-vol. Deliberately does **not** route through
    :func:`crash_hedge_value` — there is no crash state here, and manufacturing
    a zero :class:`CrashShock` would mean inventing a ``skew_reference_delta``
    that is never read. Instead builds an explicit, genuinely-neutral
    :class:`~deltadewa.analysis.repricing.MarketShock` (both dials ``0.0``,
    stated rather than defaulted) under
    :func:`~deltadewa.analysis.repricing.flat_bump_vol`. Numerically identical
    to the old ``crash_move=0, vol_shock=0`` call: a zero move leaves the spot
    alone and a zero bump with no steepening leaves each leg on its own vol.

    Args:
        portfolio: Portfolio to evaluate.
        positions: Legs to price. Defaults to every position.

    Returns:
        Summed repriced value of the selected legs at today's spot and vol.

    """
    return reprice_portfolio(
        portfolio,
        shock=MarketShock(spot_shock=0.0, vol_shock=0.0),
        vol_mapping=flat_bump_vol,
        positions=positions,
    )


def crash_convexity_pct(
    portfolio: OptionPortfolio,
    *,
    shock: CrashShock,
) -> float:
    """Crash convexity: hedge-only value change as % of the protected book (§1).

    ``(V_crash - V_today) / P_today * 100`` where ``V`` is the hedge-only option
    value (§3) and ``P_today`` is the protected book — the equity notional
    ``abs(underlying_quantity * spot)``, the reference the IPS band is stated
    against.

    Args:
        portfolio: Portfolio to evaluate.
        shock: The crash basis (see :func:`crash_hedge_value`). Applies to the
            crash leg only — ``V_today`` is always shock-free, since the
            steepening is a crash-state effect.

    Returns:
        Crash convexity as a percentage of the protected book. ``0.0`` when the
        book is empty (no underlying), since the ratio is then undefined.

    """
    book = abs(portfolio.underlying_quantity * portfolio.spot_price)
    if book == 0:
        return 0.0
    v_today = hedge_value(portfolio)
    v_crash = crash_hedge_value(portfolio, shock=shock)
    return (v_crash - v_today) / book * 100.0


def crash_value_curve(
    portfolio: OptionPortfolio,
    *,
    shock: CrashShock,
    shock_range: tuple[float, float] = (-40.0, 10.0),
    n_points: int = 25,
) -> list[tuple[float, float]]:
    """All-legs hedge value across a shock sweep — the monitor's curve.

    Same repricing basis as :func:`crash_hedge_value` /
    :func:`crash_convexity_pct` (every option leg, none dropped, positions
    never overridden), swept over spot depth at one vol/skew basis, so the
    monitor's headline number (all-legs) and its chart agree with each
    other by construction. Deliberately not
    :func:`~deltadewa.analysis.crash_payoff.compute_crash_convexity`: that
    function's curve is long-puts-only, scoped to the premium-payoff-ratio
    question (dollars back per dollar of premium paid), not this one.

    Builds :class:`~deltadewa.analysis.repricing.MarketState` once and
    reprices every grid point off it, so a whole sweep does one
    vega-weighted-average pass rather than one per point (see
    :func:`~deltadewa.analysis.repricing.reprice_legs_at`).

    Args:
        portfolio: Portfolio to evaluate.
        shock: The crash basis (vol bump, skew steepening/anchor). Its own
            ``crash_scenario_pct`` is unused — each grid point supplies its
            own depth via :meth:`CrashShock.at_pct`.
        shock_range: (min_shock_pct, max_shock_pct) bounding the grid.
        n_points: Number of evenly-spaced points in the grid.

    Returns:
        ``(shock_pct, repriced_value)`` pairs, sorted ascending (most
        severe crash first, matching the sort convention of
        :func:`~deltadewa.analysis.crash_payoff.compute_crash_convexity`'s
        ``curve``).

    """
    lo, hi = shock_range
    grid = sorted(
        {round(float(s), 6) for s in np.linspace(lo, hi, n_points)},
    )

    state = MarketState.from_portfolio(portfolio)
    return [
        (
            pct,
            reprice_legs_at(
                portfolio.positions,
                state,
                shock=shock.at_pct(pct).to_shock(),
                vol_mapping=shock.at_pct(pct).vol_mapping(),
            ),
        )
        for pct in grid
    ]


def crash_intrinsic_floor(
    portfolio: OptionPortfolio,
    *,
    crash_move: float,
    positions: Sequence[OptionPosition] | None = None,
) -> float:
    """Intrinsic floor of the legs at the crash spot (§3).

    A conservative lower bound on ``V_crash`` — the value if every leg were
    worth only its intrinsic payoff at the crash spot, with no time value. Kept
    as a separate, clearly-labelled figure; it must never be the headline (§3
    shows it reads ~2.5x where the repriced value is ~13x).

    Args:
        portfolio: Portfolio to evaluate.
        crash_move: Signed crash move as a decimal (e.g. ``-0.25``).
        positions: Legs to include. Defaults to every position.

    Returns:
        Summed intrinsic value of the selected legs at the crash spot, in
        dollars (signed by quantity).

    """
    legs = portfolio.positions if positions is None else positions
    crash_spot = portfolio.spot_price * (1.0 + crash_move)
    total = 0.0
    for position in legs:
        if position.option.option_type == OptionType.PUT:
            payoff = max(0.0, position.option.strike_price - crash_spot)
        else:
            payoff = max(0.0, crash_spot - position.option.strike_price)
        total += payoff * position.quantity * position.contract_size
    return total


def underlying_pnl(
    *,
    quantity: float,
    spot_price: float,
    spot_shock: float,
) -> float:
    """Scenario-local underlying P&L: ``quantity * spot_price * spot_shock``.

    Deliberately takes a scenario ``quantity`` rather than reading
    ``portfolio.underlying_quantity`` — the monitor's quantity dial (future
    work) is scenario-local and must never require a portfolio mutation to
    preview a hypothetical book size.

    Args:
        quantity: Scenario-local underlying share quantity (may differ from
            the portfolio's stored quantity).
        spot_price: Today's spot price (the shock is applied to this).
        spot_shock: Signed fractional spot move, e.g. ``-0.25`` for -25%
            (matches ``MarketShock.spot_shock`` / ``CrashShock.crash_move``
            units).

    Returns:
        Signed dollar P&L on the underlying position under the shock.

    """
    return quantity * spot_price * spot_shock
