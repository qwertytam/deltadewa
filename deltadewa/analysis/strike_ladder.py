"""Delta-based strike/maturity ladder for the deltadewa hedge program.

Implements handbook §2642 (Strike Selection), §2764 (Delta-Based Strike
Selection), and §2801 (Maturity Selection) as three composable pieces:

* :func:`strike_for_delta` — solves for the strike whose put-delta magnitude
  equals a given target, using :func:`scipy.optimize.brentq`.
* :func:`build_strike_ladder` — evaluates every (delta, maturity) combination
  and sizes each rung against the IPS risk budget, reusing
  :func:`~deltadewa.analysis.candidate.evaluate_candidate` and the pure-math
  helpers from :mod:`~deltadewa.analysis.sizing`.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from scipy.optimize import brentq

from deltadewa import constants as const
from deltadewa.analysis.candidate import (
    CandidateMetrics,
    build_put_valuation,
    evaluate_candidate,
)
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.analysis.sizing import (
    beta_adjusted_notional,
    required_crash_offset,
    size_from_unit,
)

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LadderRung:
    """One cell of the strike ladder — a (target_delta, maturity) combination.

    Attributes:
        target_delta: Requested put-delta magnitude (e.g. ``0.10`` for a
            10-delta put).
        maturity_years: Time to expiry in years.
        metrics: Pricing and payoff metrics from
            :func:`~deltadewa.analysis.candidate.evaluate_candidate`.
        portfolio_beta: Book beta versus SPX used to size the hedge
            (``IpsSizing.portfolio_beta``); a user input, not estimated. Same
            for all rungs.
        beta_adjusted_notional: SPX-equivalent exposure
            (``book_notional * portfolio_beta``); the notional the offset and
            convexity are measured against. Equals ``book_notional`` at beta
            1.0. Same for all rungs.
        required_crash_offset: Dollars of crash loss beyond the drawdown
            tolerance that the hedge must offset, measured on the
            ``beta_adjusted_notional`` (same for all rungs given fixed
            portfolio and IPS config).
        contracts_needed: Minimum whole contracts to cover
            ``required_crash_offset`` (ceiling division).
        implied_annual_carry: ``contracts_needed * per_contract_carry``.
        carry_budget: Annual carry budget in dollars for this portfolio (on the
            true book value, not beta-adjusted).
        within_budget: ``True`` when ``implied_annual_carry <= carry_budget``.
        carry_headroom: ``carry_budget - implied_annual_carry``; negative when
            over budget.
        max_affordable_contracts: Most contracts the carry budget supports
            (floor division).
        achieved_convexity_pct: ``(contracts_needed * per_contract_payoff)
            / beta_adjusted_notional * 100``.
        meets_convexity: ``True`` when ``achieved_convexity_pct`` lies within
            the IPS convexity band ``[target_min_pct, target_max_pct]``.
        meets_target_within_budget: ``True`` when both ``within_budget`` and
            ``meets_convexity`` are ``True``.

    """

    target_delta: float
    maturity_years: float
    metrics: CandidateMetrics

    # Sizing outputs
    portfolio_beta: float
    beta_adjusted_notional: float
    required_crash_offset: float
    contracts_needed: int
    implied_annual_carry: float
    carry_budget: float
    within_budget: bool
    carry_headroom: float
    max_affordable_contracts: int
    achieved_convexity_pct: float
    meets_convexity: bool
    meets_target_within_budget: bool


StrikeLadder = list[LadderRung]
"""List of :class:`LadderRung`, one per solved (delta, maturity) cell."""


@dataclass(frozen=True)
class UnsolvableRung:
    """A requested (target_delta, maturity) cell with no solvable strike.

    Surfaced explicitly — never silently dropped — so a rung whose target
    delta falls outside the solvable OTM range (e.g. ``target_delta >= 0.5``,
    which is ATM/ITM and outside the ``[spot * 0.40, spot * 0.9999]`` solver
    bracket) is visible in the ladder output with a reason, rather than just
    missing from the table.

    Attributes:
        target_delta: Requested put-delta magnitude that could not be solved.
        maturity_years: Requested maturity for the cell, in years.
        reason: Human-readable explanation of why no strike was found.

    """

    target_delta: float
    maturity_years: float
    reason: str


@dataclass(frozen=True)
class StrikeLadderResult:
    """The outcome of :func:`build_strike_ladder`.

    Separates the solved rungs from the cells that could not be solved so the
    latter are surfaced explicitly instead of being dropped without a trace.

    Attributes:
        rungs: Solved rungs, one per (delta, maturity) cell whose strike was
            found, in delta-major order.
        unsolvable: Cells whose strike could not be solved, in the same
            delta-major order. Empty when every requested cell solved.

    """

    rungs: StrikeLadder
    unsolvable: list[UnsolvableRung]


# ---------------------------------------------------------------------------
# Delta solver
# ---------------------------------------------------------------------------


def strike_for_delta(
    portfolio: OptionPortfolio,
    *,
    target_delta: float,
    maturity_years: float,
    vol: float | None = None,
) -> float | None:
    """Find the strike whose put-delta magnitude equals *target_delta*.

    Uses :func:`scipy.optimize.brentq` on the bracket
    ``[spot x 0.40, spot x 0.9999]``, which covers OTM put deltas from
    near-zero up to approximately ``-0.50`` (ATM).  For a put, delta is
    negative and its magnitude increases monotonically as strike rises toward
    spot, so the bracket is guaranteed to enclose a unique root when
    *target_delta* ∈ (0, 0.5).

    Args:
        portfolio: Live portfolio supplying spot, vol, rate, div, exercise
            style, and valuation date.
        target_delta: Desired put-delta magnitude as a positive number
            (e.g. ``0.10`` for a 10-delta put).
        maturity_years: Time to expiry in years.
        vol: Implied volatility override (annualised fraction).  Defaults to
            ``portfolio.volatility`` when ``None``.

    Returns:
        Strike price (float) at which ``|put_delta| ≈ target_delta``, or
        ``None`` when the target falls outside the solvable OTM range
        (e.g. *target_delta* ≥ 0.5).

    Raises:
        ValueError: Only when *target_delta* is non-positive (programmer
            error).  Out-of-range or unsolvable targets return ``None``
            instead.

    """
    if target_delta <= 0.0:
        msg = f"target_delta must be positive; got {target_delta!r}"
        raise ValueError(msg)

    spot = portfolio.spot_price
    effective_vol = vol if vol is not None else portfolio.volatility
    maturity_date = portfolio.valuation_date + timedelta(
        days=round(maturity_years * const.DAYS_PER_YEAR),
    )

    def _put_delta_at(strike: float) -> float:
        """Compute put delta for *strike*, all other inputs fixed."""
        v = build_put_valuation(
            spot, strike, maturity_date, effective_vol, portfolio
        )
        return v.delta()

    lo = spot * 0.40
    hi = spot * 0.9999

    # f(strike) = |put_delta(strike)| - target_delta
    # f(lo) should be < 0 (very OTM, |delta| ≈ 0)
    # f(hi) should be > 0 (near ATM, |delta| ≈ 0.5)
    f_lo = abs(_put_delta_at(lo)) - target_delta
    f_hi = abs(_put_delta_at(hi)) - target_delta

    if f_lo >= 0.0 or f_hi <= 0.0:
        return None

    try:
        return float(
            brentq(
                lambda k: abs(_put_delta_at(k)) - target_delta,
                lo,
                hi,
                xtol=0.01,
                maxiter=100,
            ),
        )
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Ladder builder
# ---------------------------------------------------------------------------


def build_strike_ladder(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    *,
    target_deltas: Sequence[float],
    maturities_years: Sequence[float],
    vol: float | None = None,
) -> StrikeLadderResult:
    """Build a full strike/maturity ladder sized against the IPS risk budget.

    For every ``(delta, maturity)`` pair (outer loop: *target_deltas*; inner
    loop: *maturities_years*) the function:

    1. Resolves the strike via :func:`strike_for_delta`.
    2. Prices the candidate put via
       :func:`~deltadewa.analysis.candidate.evaluate_candidate`.
    3. Sizes it via :func:`~deltadewa.analysis.sizing.size_from_unit`.
    4. Checks convexity against the IPS target band.

    No pricing or payoff logic is reimplemented here; every number flows
    through the shared helpers.

    Args:
        portfolio: Live portfolio supplying market data and exercise style.
        ips_config: Policy parameters (carry budget, drawdown tolerance,
            crash scenario, convexity target band).
        target_deltas: Sequence of put-delta magnitudes to include as rows
            (e.g. ``[0.05, 0.10, 0.15]``).
        maturities_years: Sequence of maturities to include as columns
            (e.g. ``[0.25, 0.50, 1.0]``).
        vol: Implied volatility override (annualised fraction).  Defaults to
            ``portfolio.volatility`` when ``None``.

    Returns:
        :class:`StrikeLadderResult` — ``rungs`` is a flat list of
        :class:`LadderRung` in delta-major order (all maturities for the first
        delta, then all for the second, etc.) for every cell whose strike
        solved; ``unsolvable`` lists the cells whose strike could not be solved
        (surfaced explicitly, never silently dropped).

    Raises:
        ValueError: When the book notional is 0 (no underlying position);
            the ladder's sizing is undefined and never fabricates a zero result.

    """
    book_notional = abs(portfolio.underlying_quantity) * portfolio.spot_price
    if book_notional <= 0.0:
        msg = (
            "strike-ladder sizing requires an underlying position; "
            "underlying_quantity is unset (book notional is 0)"
        )
        raise ValueError(msg)
    # Beta-adjusted (SPX-equivalent) notional the hedge is sized against
    # (handbook §2499); equals book_notional at beta 1.0. Carry budget stays on
    # the true book value — the premium budget is a fraction of actual wealth.
    portfolio_beta = ips_config.sizing.portfolio_beta
    beta_adj_notional = beta_adjusted_notional(book_notional, portfolio_beta)
    carry_budget = ips_config.budget.annual_carry_pct / 100.0 * book_notional
    # One crash basis for every rung, built the same way the book surfaces
    # build theirs; the depth is read back off it so the drawdown maths and
    # the repricing cannot drift apart.
    shock = CrashShock.from_ips(ips_config.convexity)
    offset = required_crash_offset(
        beta_adj_notional,
        shock.crash_scenario_pct,
        ips_config.drawdown.max_tolerance_pct,
    )
    # Policy, on its own path: `shock` prices the rungs, `conv` only judges
    # them against the band (M1.5 — the two never travel as one object).
    conv = ips_config.convexity

    rungs: StrikeLadder = []
    unsolvable: list[UnsolvableRung] = []
    for delta, maturity in itertools.product(target_deltas, maturities_years):
        strike = strike_for_delta(
            portfolio,
            target_delta=delta,
            maturity_years=maturity,
            vol=vol,
        )
        if strike is None:
            unsolvable.append(
                UnsolvableRung(
                    target_delta=delta,
                    maturity_years=maturity,
                    reason=(
                        f"no OTM strike solves to |put delta| "
                        f"{delta:.2f} at {maturity:.2f}y — target is "
                        f"outside the solvable (0, 0.5) delta range "
                        f"(>= 0.5 is ATM/ITM, off the solver bracket)"
                    ),
                ),
            )
            continue
        metrics = evaluate_candidate(
            portfolio,
            strike=strike,
            maturity_years=maturity,
            shock=shock,
            vol=vol,
        )
        sizing = size_from_unit(
            offset,
            metrics.per_contract_payoff,
            metrics.per_contract_carry,
            carry_budget,
        )
        achieved_convexity_pct = (
            sizing.contracts_needed
            * metrics.per_contract_payoff
            / beta_adj_notional
            * 100.0
            if beta_adj_notional > 0.0
            else 0.0
        )
        meets_convexity = (
            conv.target_min_pct <= achieved_convexity_pct <= conv.target_max_pct
        )
        rungs.append(
            LadderRung(
                target_delta=delta,
                maturity_years=maturity,
                metrics=metrics,
                portfolio_beta=portfolio_beta,
                beta_adjusted_notional=beta_adj_notional,
                required_crash_offset=offset,
                contracts_needed=sizing.contracts_needed,
                implied_annual_carry=sizing.implied_annual_carry,
                carry_budget=carry_budget,
                within_budget=sizing.within_budget,
                carry_headroom=sizing.carry_headroom,
                max_affordable_contracts=sizing.max_affordable_contracts,
                achieved_convexity_pct=achieved_convexity_pct,
                meets_convexity=meets_convexity,
                meets_target_within_budget=(
                    sizing.within_budget and meets_convexity
                ),
            ),
        )
    return StrikeLadderResult(rungs=rungs, unsolvable=unsolvable)
