"""Per-candidate option metrics shared by sizing and the strike ladder.

A *candidate* is a hypothetical put at a given (strike, maturity) pair.
:func:`evaluate_candidate` prices it once via
:class:`~deltadewa.valuation.OptionValuation` and returns the metrics that
both :func:`~deltadewa.analysis.sizing.size_hedge` and
:func:`~deltadewa.analysis.strike_ladder.build_strike_ladder` need,
eliminating any duplicated pricing or payoff logic between the two callers.

The crash payoff is the candidate **repriced** at the crash state (crash spot
plus vol shock) through the shared
:func:`~deltadewa.analysis.crash_repricing.crash_hedge_value` helper — the same
basis as the health gauge and the scenario table — with intrinsic value kept
only as a conservative labelled floor (C4; see
``docs/repricing-methodology.md`` §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from deltadewa import constants as const
from deltadewa.analysis.crash_repricing import (
    crash_hedge_value,
    crash_intrinsic_floor,
)
from deltadewa.constants import OptionType
from deltadewa.portfolio.position import OptionPosition
from deltadewa.valuation import OptionValuation

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateMetrics:
    """Pricing and payoff metrics for a single candidate put.

    Attributes:
        strike: Absolute strike price.
        pct_otm: Percent out-of-the-money: ``(spot - strike) / spot * 100``.
        put_delta: Put delta (negative; e.g. ``-0.10`` for a 10-delta put).
        premium: Option price x portfolio contract size in dollars
            (positive cost).
        per_contract_payoff: One contract **repriced** at the crash state
            (crash spot ``S0 * (1 + crash_pct/100)`` plus the flat vol shock),
            in dollars — the full hedge-only option value from
            :func:`~deltadewa.analysis.crash_repricing.crash_hedge_value`,
            including time value.  **Not** intrinsic and **not** value at
            expiry.
        per_contract_intrinsic_floor: One contract's intrinsic value at the
            crash spot — ``max(0, strike - crash_spot) * contract_size`` — in
            dollars.  A conservative labelled lower bound, always
            ``<= per_contract_payoff``; never the headline (§3).
        per_contract_carry: Annualised theta cost per contract as a positive
            dollar amount: ``|theta/day| * 365 * contract_size``.

    """

    strike: float
    pct_otm: float
    put_delta: float
    premium: float
    per_contract_payoff: float
    per_contract_intrinsic_floor: float
    per_contract_carry: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def build_put_valuation(
    spot: float,
    strike: float,
    maturity_date: datetime,
    effective_vol: float,
    portfolio: OptionPortfolio,
) -> OptionValuation:
    """Construct a put :class:`~deltadewa.valuation.OptionValuation`.

    Centralises the nine-kwarg constructor that both
    :func:`evaluate_candidate` and
    :func:`~deltadewa.analysis.strike_ladder.strike_for_delta` need,
    keeping exercise style, rate, and dividend wired from the portfolio
    in one place.

    Args:
        spot: Current underlying spot price.
        strike: Put strike price.
        maturity_date: Option expiry date.
        effective_vol: Implied volatility (annualised fraction); typically
            ``portfolio.volatility`` or an explicit override.
        portfolio: Supplies ``risk_free_rate``, ``dividend_yield``, and
            ``default_exercise_style``.

    Returns:
        Configured :class:`~deltadewa.valuation.OptionValuation` ready
        for ``.price()``, ``.delta()``, or ``.theta()`` calls.

    """
    return OptionValuation(
        spot_price=spot,
        strike_price=strike,
        maturity_date=maturity_date,
        volatility=effective_vol,
        risk_free_rate=portfolio.risk_free_rate,
        dividend_yield=portfolio.dividend_yield,
        option_type=OptionType.PUT,
        exercise_style=portfolio.default_exercise_style,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_candidate(
    portfolio: OptionPortfolio,
    *,
    strike: float,
    maturity_years: float,
    crash_pct: float,
    crash_vol_shock: float,
    vol: float | None = None,
) -> CandidateMetrics:
    """Price one candidate put and return per-contract economics.

    Builds a single :class:`~deltadewa.valuation.OptionValuation` for the
    given *strike* / *maturity_years* pair and derives every field of
    :class:`CandidateMetrics` from it.  The crash payoff and its intrinsic
    floor are obtained by wrapping that valuation in a one-contract
    :class:`~deltadewa.portfolio.position.OptionPosition` and passing it to the
    shared :func:`~deltadewa.analysis.crash_repricing.crash_hedge_value` and
    :func:`~deltadewa.analysis.crash_repricing.crash_intrinsic_floor` helpers —
    no repricing logic is duplicated here.

    Args:
        portfolio: Live portfolio supplying spot, vol, rate, div, exercise
            style, and valuation date.
        strike: Absolute strike price of the candidate put.
        maturity_years: Time to expiry in years (e.g. ``0.25`` for ~3 months).
        crash_pct: Signed crash scenario percent (e.g. ``-25.0`` for a 25 %
            decline), from ``IpsConvexity.crash_scenario_pct``.  Sets the crash
            spot at which the candidate is repriced.
        crash_vol_shock: Flat additive vol bump as a decimal (e.g. ``+0.15``),
            from ``IpsConvexity.crash_vol_shock``.  Applied to the candidate's
            own vol when repricing at the crash spot, so every panel shares one
            crash basis (required — no silent divergence).
        vol: Implied volatility override (annualised fraction).  Defaults to
            ``portfolio.volatility`` when ``None``.

    Returns:
        :class:`CandidateMetrics` with strike, OTM %, delta, premium,
        repriced per-contract payoff, intrinsic floor, and per-contract carry.

    """
    spot = portfolio.spot_price
    effective_vol = vol if vol is not None else portfolio.volatility

    pct_otm = (spot - strike) / spot * 100.0

    maturity_date = portfolio.valuation_date + timedelta(
        days=round(maturity_years * const.DAYS_PER_YEAR),
    )
    valuation = build_put_valuation(
        spot, strike, maturity_date, effective_vol, portfolio
    )

    # Reprice the candidate at the crash state via the shared helper: wrap the
    # today valuation in a one-contract long put and hand it to
    # crash_hedge_value / crash_intrinsic_floor (no duplicated repricing).
    candidate_leg = OptionPosition(
        option=valuation,
        quantity=1,
        contract_size=portfolio.contract_size,
        exercise_style=portfolio.default_exercise_style,
    )
    crash_move = crash_pct / 100.0
    per_contract_payoff = crash_hedge_value(
        portfolio,
        crash_move=crash_move,
        vol_shock=crash_vol_shock,
        positions=[candidate_leg],
    )
    per_contract_intrinsic_floor = crash_intrinsic_floor(
        portfolio,
        crash_move=crash_move,
        positions=[candidate_leg],
    )

    put_delta = valuation.delta()
    premium = valuation.price() * portfolio.contract_size
    # theta() is $/day per unit, negative for a long put; annualise on the
    # 365-calendar-day basis that carry.py uses.
    per_contract_carry = (
        abs(valuation.theta()) * const.DAYS_PER_YEAR * portfolio.contract_size
    )

    return CandidateMetrics(
        strike=strike,
        pct_otm=pct_otm,
        put_delta=put_delta,
        premium=premium,
        per_contract_payoff=per_contract_payoff,
        per_contract_intrinsic_floor=per_contract_intrinsic_floor,
        per_contract_carry=per_contract_carry,
    )
