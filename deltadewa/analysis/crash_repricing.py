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

Legs are repriced with the existing
:class:`~deltadewa.valuation.OptionValuation` engine (European exercise uses the
analytic Black-Scholes engine); no new pricer is introduced.
"""

from __future__ import annotations

import functools
import math
from typing import TYPE_CHECKING

from scipy.optimize import brentq

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import _DEFAULT_SKEW_REFERENCE_DELTA
from deltadewa.valuation import OptionValuation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition

# Bracket for the wing-strike root solve: from deep OTM (put-delta magnitude
# ~0) up to just below ATM (magnitude ~0.5). The ~10-delta wing sits well
# inside this range at every supported tenor.
_WING_STRIKE_LO_FRAC = 0.05
_WING_STRIKE_HI_FRAC = 0.9999


def _reprice_leg(
    position: OptionPosition,
    portfolio: OptionPortfolio,
    spot: float,
    volatility: float,
) -> float:
    """Total value of one option leg repriced at *spot* and *volatility*.

    Builds a fresh :class:`OptionValuation` at the given crash state — holding
    the portfolio's rate, dividend, valuation date, and the leg's own strike,
    maturity, type, and exercise style — and scales the per-share price by
    signed contract quantity and contract size. Does not mutate portfolio state.

    Args:
        position: Option leg to reprice.
        portfolio: Portfolio supplying rate, dividend, and valuation date.
        spot: Crash spot to price at.
        volatility: Shocked volatility to price at.

    Returns:
        ``price * quantity * contract_size`` in dollars (signed by quantity).

    """
    option = OptionValuation(
        spot_price=spot,
        strike_price=position.option.strike_price,
        maturity_date=position.option.maturity_date,
        volatility=volatility,
        risk_free_rate=portfolio.risk_free_rate,
        dividend_yield=portfolio.dividend_yield,
        option_type=position.option.option_type,
        valuation_date=portfolio.valuation_date,
        exercise_style=position.exercise_style,
    )
    return option.price() * position.quantity * position.contract_size


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


def _leg_crash_vol(
    position: OptionPosition,
    *,
    spot: float,
    risk_free_rate: float,
    dividend_yield: float,
    valuation_date: datetime,
    vol_shock: float,
    skew_steepening: float,
    skew_reference_delta: float,
) -> float:
    """Shocked crash vol for one leg: flat bump plus a capped wing steepening.

    ``sigma_i + vol_shock`` for calls and ATM/ITM puts. For an OTM put the crash
    vol adds ``min(skew_steepening, slope * ln(S/K))`` where
    ``slope = skew_steepening / ln(S / K_ref)`` and ``K_ref`` is the leg's own
    ~``skew_reference_delta`` wing (:func:`_solve_wing_strike`). The extra vol
    is thus ``skew_steepening`` exactly at the wing and interpolates linearly
    (in log-moneyness) below it — never extrapolated past the calibrated wing
    (the cap). The anchor is per-leg, so a leg's crash vol never depends on what
    else the book holds.

    When ``skew_steepening`` is ``0.0`` this returns exactly
    ``position.option.volatility + vol_shock`` — the flat-bump expression — and
    solves no wing, so the disabled knob reproduces every prior value
    bit-for-bit.

    Args:
        position: Option leg to shock.
        spot: Today's underlying spot the moneyness is measured against.
        risk_free_rate: Portfolio risk-free rate (for the wing solve).
        dividend_yield: Portfolio dividend yield (for the wing solve).
        valuation_date: Portfolio valuation date (for the wing solve).
        vol_shock: Flat additive vol bump applied to every leg.
        skew_steepening: Extra vol added at the leg's own wing (``0.0`` = off).
        skew_reference_delta: Put-delta magnitude of that wing (e.g. ``0.10``).

    Returns:
        The leg's shocked volatility as a decimal.

    """
    base = position.option.volatility + vol_shock
    if math.isclose(skew_steepening, 0.0, abs_tol=1e-9):
        return base
    if position.option.option_type != OptionType.PUT:
        return base
    strike = position.option.strike_price
    if strike >= spot:
        return base
    k_ref = _solve_wing_strike(
        spot=spot,
        maturity_date=position.option.maturity_date,
        volatility=position.option.volatility,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        valuation_date=valuation_date,
        anchor_delta=skew_reference_delta,
    )
    slope = skew_steepening / math.log(spot / k_ref)
    extra = min(skew_steepening, slope * math.log(spot / strike))
    return base + extra


def crash_hedge_value(
    portfolio: OptionPortfolio,
    *,
    crash_move: float,
    vol_shock: float,
    skew_steepening: float = 0.0,
    skew_reference_delta: float = _DEFAULT_SKEW_REFERENCE_DELTA,
    positions: Sequence[OptionPosition] | None = None,
) -> float:
    """Hedge-only value of the option legs repriced at the crash state (§2-3).

    Excludes the underlying / equity position. Full repriced option value —
    not intrinsic, not value at expiry.

    Args:
        portfolio: Portfolio to evaluate.
        crash_move: Signed crash move as a decimal (e.g. ``-0.25``). The crash
            spot is ``portfolio.spot_price * (1 + crash_move)``.
        vol_shock: Flat additive vol bump as a decimal (e.g. ``+0.15``) applied
            to every leg's own today-vol.
        skew_steepening: Optional extra vol added at the deep-OTM tail on top of
            ``vol_shock``, capped at this value at each leg's own
            ``skew_reference_delta`` wing and interpolated (in log-moneyness)
            below it (M1.7). ``0.0`` (the default) keeps the flat bump and
            reproduces prior values exactly.
        skew_reference_delta: Put-delta magnitude of the wing the steepening is
            anchored to (e.g. ``0.10``), sourced from
            ``IpsConvexity.skew_reference_delta``. Only consulted when
            ``skew_steepening`` is non-zero.
        positions: Legs to price. Defaults to every position in the portfolio;
            pass a subset (e.g. the long puts) to value part of the book.

    Returns:
        Summed repriced value of the selected option legs, in dollars.

    """
    legs = portfolio.positions if positions is None else positions
    crash_spot = portfolio.spot_price * (1.0 + crash_move)
    return float(
        sum(
            _reprice_leg(
                position,
                portfolio,
                crash_spot,
                _leg_crash_vol(
                    position,
                    spot=portfolio.spot_price,
                    risk_free_rate=portfolio.risk_free_rate,
                    dividend_yield=portfolio.dividend_yield,
                    valuation_date=portfolio.valuation_date,
                    vol_shock=vol_shock,
                    skew_steepening=skew_steepening,
                    skew_reference_delta=skew_reference_delta,
                ),
            )
            for position in legs
        ),
    )


def hedge_value(
    portfolio: OptionPortfolio,
    *,
    positions: Sequence[OptionPosition] | None = None,
) -> float:
    """Today's hedge-only option-leg value (no crash move, no vol shock).

    Equivalent to :func:`crash_hedge_value` at ``crash_move=0``,
    ``vol_shock=0`` — the ``V_today`` term of the convexity ratio.

    Args:
        portfolio: Portfolio to evaluate.
        positions: Legs to price. Defaults to every position.

    Returns:
        Summed repriced value of the selected legs at today's spot and vol.

    """
    return crash_hedge_value(
        portfolio,
        crash_move=0.0,
        vol_shock=0.0,
        positions=positions,
    )


def crash_convexity_pct(
    portfolio: OptionPortfolio,
    *,
    crash_move: float,
    vol_shock: float,
    skew_steepening: float = 0.0,
    skew_reference_delta: float = _DEFAULT_SKEW_REFERENCE_DELTA,
) -> float:
    """Crash convexity: hedge-only value change as % of the protected book (§1).

    ``(V_crash - V_today) / P_today * 100`` where ``V`` is the hedge-only option
    value (§3) and ``P_today`` is the protected book — the equity notional
    ``abs(underlying_quantity * spot)``, the reference the IPS band is stated
    against.

    Args:
        portfolio: Portfolio to evaluate.
        crash_move: Signed crash move as a decimal (e.g. ``-0.25``).
        vol_shock: Flat additive vol bump as a decimal (e.g. ``+0.15``).
        skew_steepening: Optional deep-OTM skew steepening applied to the crash
            leg only, capped at each leg's own ``skew_reference_delta`` wing
            (M1.7). ``0.0`` (the default) keeps the flat bump. The today-value
            ``V_today`` is always skew-free — steepening is a crash-state
            effect.
        skew_reference_delta: Put-delta magnitude of the wing the steepening is
            anchored to (e.g. ``0.10``). Only consulted when ``skew_steepening``
            is non-zero.

    Returns:
        Crash convexity as a percentage of the protected book. ``0.0`` when the
        book is empty (no underlying), since the ratio is then undefined.

    """
    book = abs(portfolio.underlying_quantity * portfolio.spot_price)
    if book == 0:
        return 0.0
    v_today = hedge_value(portfolio)
    v_crash = crash_hedge_value(
        portfolio,
        crash_move=crash_move,
        vol_shock=vol_shock,
        skew_steepening=skew_steepening,
        skew_reference_delta=skew_reference_delta,
    )
    return (v_crash - v_today) / book * 100.0


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
