"""Per-candidate option metrics shared by sizing and the strike ladder.

A *candidate* is a hypothetical put at a given (strike, maturity) pair.
:func:`evaluate_candidate` prices it once via
:class:`~deltadewa.valuation.OptionValuation` and returns the six metrics
that both :func:`~deltadewa.analysis.sizing.size_hedge` and
:func:`~deltadewa.analysis.strike_ladder.build_strike_ladder` need,
eliminating any duplicated pricing or payoff logic between the two callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from deltadewa import constants as const
from deltadewa.constants import OptionType
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
        per_contract_payoff: Intrinsic put value at the crash spot times the
            portfolio contract size — ``max(0, strike - crash_spot) *
            contract_size`` — in dollars.
        per_contract_carry: Annualised theta cost per contract as a positive
            dollar amount: ``|theta/day| * 365 * contract_size``.

    """

    strike: float
    pct_otm: float
    put_delta: float
    premium: float
    per_contract_payoff: float
    per_contract_carry: float


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _intrinsic_at_crash(strike: float, crash_spot: float) -> float:
    """Intrinsic put value per unit at the crash spot.

    Uses intrinsic-at-expiry under flat vol (conservative; excludes time
    value), consistent with ``crash_payoff._gross_long_put_payoff``.

    """
    return max(0.0, strike - crash_spot)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_candidate(
    portfolio: OptionPortfolio,
    *,
    strike: float,
    maturity_years: float,
    crash_pct: float,
    vol: float | None = None,
) -> CandidateMetrics:
    """Price one candidate put and return per-contract economics.

    Builds a single :class:`~deltadewa.valuation.OptionValuation` for the
    given *strike* / *maturity_years* pair and derives all six fields of
    :class:`CandidateMetrics` from it.

    Args:
        portfolio: Live portfolio supplying spot, vol, rate, div, exercise
            style, and valuation date.
        strike: Absolute strike price of the candidate put.
        maturity_years: Time to expiry in years (e.g. ``0.25`` for ~3 months).
        crash_pct: Signed crash scenario percent (e.g. ``-25.0`` for a 25 %
            decline), from ``IpsConvexity.crash_scenario_pct``.  Used to
            compute ``per_contract_payoff``.
        vol: Implied volatility override (annualised fraction).  Defaults to
            ``portfolio.volatility`` when ``None``.

    Returns:
        :class:`CandidateMetrics` with strike, OTM %, delta, premium,
        per-contract payoff, and per-contract carry.

    """
    spot = portfolio.spot_price
    effective_vol = vol if vol is not None else portfolio.volatility

    pct_otm = (spot - strike) / spot * 100.0
    crash_spot = spot * (1.0 + crash_pct / 100.0)
    per_contract_payoff = (
        _intrinsic_at_crash(strike, crash_spot) * portfolio.contract_size
    )

    maturity_date = portfolio.valuation_date + timedelta(
        days=round(maturity_years * const.DAYS_PER_YEAR),
    )
    valuation = OptionValuation(
        spot_price=spot,
        strike_price=strike,
        maturity_date=maturity_date,
        volatility=effective_vol,
        risk_free_rate=portfolio.risk_free_rate,
        dividend_yield=portfolio.dividend_yield,
        option_type=OptionType.PUT,
        exercise_style=portfolio.default_exercise_style,
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
        per_contract_carry=per_contract_carry,
    )
