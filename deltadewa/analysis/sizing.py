"""Risk-budget hedge sizing for the deltadewa hedge program.

Implements the 5-step IPS-driven sizing framework:

1. ``required_crash_offset`` — dollars the hedge must recover beyond the
   acceptable drawdown.
2. Per-contract payoff: the candidate **repriced** at the IPS crash state
   (crash spot + vol shock) via
   :func:`~deltadewa.analysis.candidate.evaluate_candidate` — full option
   value, with intrinsic value kept only as a labelled floor.
3. Per-contract carry: annualised theta cost (positive), matching
   ``carry.py``'s 365-day convention.
4. ``size_from_unit`` — pure scalar sizing: contracts needed, carry check,
   max affordable.
5. Achieved convexity vs IPS target band.

``required_crash_offset`` and ``size_from_unit`` work on plain scalars
and are independently unit-testable without any pricing dependency.
``size_hedge`` wraps them via
:func:`~deltadewa.analysis.candidate.evaluate_candidate`.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from deltadewa.analysis.candidate import evaluate_candidate

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HedgeSizingResult:
    """Result of the 5-step risk-budget hedge sizing calculation.

    Attributes:
        candidate_pct_otm: Put strike expressed as percent out-of-the-money
            (e.g. 5.0 → strike = spot * 0.95).
        candidate_maturity_years: Time to expiry of the candidate put in years.
        book_notional: ``abs(underlying_quantity) * spot_price`` in dollars.
        carry_budget: Annual premium budget in dollars
            (``annual_carry_pct / 100 * book_notional``).
        required_crash_offset: Dollars of crash loss beyond the drawdown
            tolerance that the hedge must offset.
        per_contract_payoff: One contract **repriced** at the IPS crash state
            (crash spot + vol shock), in dollars — the full hedge-only option
            value, not intrinsic.
        per_contract_intrinsic_floor: One contract's intrinsic value at the
            crash spot (``max(0, strike - crash_spot) * 100``), in dollars — a
            conservative labelled floor, always ``<= per_contract_payoff``.
        per_contract_carry: Annualised theta cost of one contract as a
            positive dollar amount (``|theta/day| * 365 * 100``).
        contracts_needed: Minimum whole contracts to cover
            ``required_crash_offset`` (ceiling division); 0 when
            ``per_contract_payoff`` is zero.
        implied_annual_carry: ``contracts_needed * per_contract_carry``.
        within_budget: True when ``implied_annual_carry <= carry_budget``.
        carry_headroom: ``carry_budget - implied_annual_carry``; negative
            means over-budget.
        max_affordable_contracts: Most contracts the carry budget can support
            (floor division); ``sys.maxsize`` when ``per_contract_carry`` is
            zero (practically unlimited).
        achieved_convexity_pct: ``(contracts_needed * per_contract_payoff)
            / book_notional * 100``; 0.0 when ``book_notional`` is zero.
        meets_convexity_target: True when ``achieved_convexity_pct`` lies
            within the IPS band ``[target_min_pct, target_max_pct]``.

    """

    # Candidate specification
    candidate_pct_otm: float
    candidate_maturity_years: float

    # Notional & budget
    book_notional: float
    carry_budget: float

    # Step 1 — drawdown offset
    required_crash_offset: float

    # Per-contract economics
    per_contract_payoff: float
    per_contract_intrinsic_floor: float
    per_contract_carry: float

    # Steps 2-3 - sizing & carry check
    contracts_needed: int
    implied_annual_carry: float
    within_budget: bool
    carry_headroom: float
    max_affordable_contracts: int

    # Steps 4-5 - convexity check
    achieved_convexity_pct: float
    meets_convexity_target: bool


@dataclass(frozen=True)
class UnitSizingResult:
    """Return value of :func:`size_from_unit`.

    Attributes:
        contracts_needed: Minimum whole contracts to cover the required offset;
            0 when ``per_contract_payoff`` is zero.
        implied_annual_carry: ``contracts_needed * per_contract_carry``.
        within_budget: ``True`` when ``implied_annual_carry <= carry_budget``.
        carry_headroom: ``carry_budget - implied_annual_carry``; negative
            means over-budget.
        max_affordable_contracts: Most contracts the budget can support
            (floor division); ``sys.maxsize`` when ``per_contract_carry``
            is zero.

    """

    contracts_needed: int
    implied_annual_carry: float
    within_budget: bool
    carry_headroom: float
    max_affordable_contracts: int


# ---------------------------------------------------------------------------
# Pure-math core
# ---------------------------------------------------------------------------


def required_crash_offset(
    book_notional: float,
    crash_pct: float,
    drawdown_tolerance_pct: float,
) -> float:
    """Crash loss beyond the drawdown tolerance the hedge must offset.

    Args:
        book_notional: ``abs(underlying_quantity) * spot_price`` in dollars.
        crash_pct: Signed crash scenario percent (e.g. ``-25.0`` for a 25 %
            decline), as stored in ``IpsConvexity.crash_scenario_pct``.
        drawdown_tolerance_pct: Maximum acceptable portfolio decline in percent
            (non-negative), from ``IpsDrawdown.max_tolerance_pct``.

    Returns:
        Required offset in dollars; 0.0 when the crash is within the
        tolerance or ``book_notional`` is zero.

    """
    if book_notional <= 0.0:
        return 0.0
    excess = abs(crash_pct) / 100.0 - drawdown_tolerance_pct / 100.0
    return max(0.0, book_notional * excess)


def size_from_unit(
    required_offset: float,
    per_contract_payoff: float,
    per_contract_carry: float,
    carry_budget: float,
) -> UnitSizingResult:
    """Pure scalar sizing math — no pricing, no portfolio.

    Args:
        required_offset: Dollar crash loss the hedge must cover.
        per_contract_payoff: Intrinsic payoff of one contract at the crash
            spot in dollars (positive).  If zero or negative,
            ``contracts_needed`` is returned as 0.
        per_contract_carry: Annualised carry cost of one contract in dollars
            (positive).  If zero, ``max_affordable_contracts`` is
            ``sys.maxsize``.
        carry_budget: Total annual carry dollars available.

    Returns:
        ``(contracts_needed, implied_annual_carry, within_budget,
        carry_headroom, max_affordable_contracts)``.

    """
    if per_contract_payoff > 0.0:
        contracts_needed = math.ceil(required_offset / per_contract_payoff)
    else:
        contracts_needed = 0

    implied_annual_carry = contracts_needed * per_contract_carry
    within_budget = implied_annual_carry <= carry_budget
    carry_headroom = carry_budget - implied_annual_carry
    max_affordable = (
        math.floor(carry_budget / per_contract_carry)
        if per_contract_carry > 0.0
        else sys.maxsize
    )

    return UnitSizingResult(
        contracts_needed=contracts_needed,
        implied_annual_carry=implied_annual_carry,
        within_budget=within_budget,
        carry_headroom=carry_headroom,
        max_affordable_contracts=max_affordable,
    )


# ---------------------------------------------------------------------------
# Pricing wrapper
# ---------------------------------------------------------------------------


def size_hedge(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    *,
    candidate_pct_otm: float,
    candidate_maturity_years: float,
    vol: float | None = None,
) -> HedgeSizingResult:
    """Size a candidate put against the IPS risk-budget constraints.

    Derives the strike from *candidate_pct_otm*, delegates per-contract
    pricing to :func:`~deltadewa.analysis.candidate.evaluate_candidate`, then
    calls :func:`size_from_unit` for the scalar arithmetic.

    Args:
        portfolio: Live portfolio; supplies spot, vol, rate, div, exercise
            style, and valuation date.
        ips_config: Policy parameters (carry budget, drawdown tolerance,
            crash scenario, convexity target band).
        candidate_pct_otm: Strike as percent out-of-the-money
            (e.g. 5.0 → ``strike = spot * 0.95``).
        candidate_maturity_years: Time to expiry in years
            (e.g. 0.25 for ~3 months).
        vol: Override for implied volatility (annualised fraction).  Defaults
            to ``portfolio.volatility`` when ``None``.

    Returns:
        ``HedgeSizingResult`` with all sizing and convexity metrics.

    Raises:
        ValueError: When the book notional is 0 (no underlying position);
            sizing is undefined and never returns a fabricated zero result.

    """
    book_notional = abs(portfolio.underlying_quantity) * portfolio.spot_price
    if book_notional <= 0.0:
        msg = (
            "hedge sizing requires an underlying position; "
            "underlying_quantity is unset (book notional is 0)"
        )
        raise ValueError(msg)
    carry_budget = ips_config.budget.annual_carry_pct / 100.0 * book_notional

    crash_pct = ips_config.convexity.crash_scenario_pct  # negative
    offset = required_crash_offset(
        book_notional,
        crash_pct,
        ips_config.drawdown.max_tolerance_pct,
    )

    strike = portfolio.spot_price * (1.0 - candidate_pct_otm / 100.0)
    metrics = evaluate_candidate(
        portfolio,
        strike=strike,
        maturity_years=candidate_maturity_years,
        crash_pct=crash_pct,
        crash_vol_shock=ips_config.convexity.crash_vol_shock,
        vol=vol,
    )

    sizing = size_from_unit(
        offset,
        metrics.per_contract_payoff,
        metrics.per_contract_carry,
        carry_budget,
    )

    achieved_payoff = sizing.contracts_needed * metrics.per_contract_payoff
    achieved_convexity_pct = (
        achieved_payoff / book_notional * 100.0 if book_notional > 0.0 else 0.0
    )
    conv = ips_config.convexity
    meets_convexity_target = (
        conv.target_min_pct <= achieved_convexity_pct <= conv.target_max_pct
    )

    return HedgeSizingResult(
        candidate_pct_otm=candidate_pct_otm,
        candidate_maturity_years=candidate_maturity_years,
        book_notional=book_notional,
        carry_budget=carry_budget,
        required_crash_offset=offset,
        per_contract_payoff=metrics.per_contract_payoff,
        per_contract_intrinsic_floor=metrics.per_contract_intrinsic_floor,
        per_contract_carry=metrics.per_contract_carry,
        contracts_needed=sizing.contracts_needed,
        implied_annual_carry=sizing.implied_annual_carry,
        within_budget=sizing.within_budget,
        carry_headroom=sizing.carry_headroom,
        max_affordable_contracts=sizing.max_affordable_contracts,
        achieved_convexity_pct=achieved_convexity_pct,
        meets_convexity_target=meets_convexity_target,
    )
