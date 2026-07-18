"""Shared crash-state repricing per ``docs/repricing-methodology.md`` §1-3.

Single source of the crash basis for every panel: the health convexity gauge
(:meth:`HealthMixin.calculate_crash_convexity_pct`), the ``crash_payoff``
payoff ratios, and the ``NetHedgeSummary`` crash-convexity ladder all reprice
the option legs *hedge-only* at the crash spot plus a flat additive vol shock
through these helpers, so every surface shares one basis (fixes C1/C4/Mo1).

The crash state (§2):

* crash spot ``S_crash = S0 * (1 + crash_move)`` — ``crash_move`` is a signed
  decimal (e.g. ``-0.25`` for a 25% decline);
* per-leg vol ``sigma_i + vol_shock`` — ``vol_shock`` is a flat additive decimal
  (e.g. ``+0.15``), sourced from ``IpsConvexity.crash_vol_shock``;
* rates, dividends, and time-to-maturity held at today's values — the crash is
  an instantaneous jump at the current valuation date;
* the underlying / equity leg is **excluded** — convexity is a hedge-only
  metric.

Legs are repriced with the existing
:class:`~deltadewa.valuation.OptionValuation` engine (European exercise uses the
analytic Black-Scholes engine); no new pricer is introduced.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deltadewa.constants import OptionType
from deltadewa.valuation import OptionValuation

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition


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


def crash_hedge_value(
    portfolio: OptionPortfolio,
    *,
    crash_move: float,
    vol_shock: float,
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
                position.option.volatility + vol_shock,
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
