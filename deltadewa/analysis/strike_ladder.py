"""Delta-based strike/maturity ladder for the deltadewa hedge program.

Implements handbook `Strike Selection
<https://qwertytam.github.io/deltadewa-handbook/part-7/strike-selection/>`_,
`Delta-Based Strike Selection
<https://qwertytam.github.io/deltadewa-handbook/part-7/delta-based-strike-selection/>`_,
and `Maturity Selection
<https://qwertytam.github.io/deltadewa-handbook/part-7/maturity-selection/>`_
as three composable pieces:

* :func:`strike_for_delta` — solves for the strike whose put-delta magnitude
  equals a given target, using :func:`scipy.optimize.brentq`.
* :func:`build_candidate_grid` — evaluates every (delta, maturity) combination
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
from deltadewa.analysis.convexity_band import grade_convexity
from deltadewa.analysis.sizing import size_from_unit, sizing_basis

if TYPE_CHECKING:
    from deltadewa.analysis.convexity_band import ConvexityGrading
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GridCell:
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
            (``book_notional * portfolio_beta``); the notional the crash offset
            is measured against (the convexity reading is on the book
            notional, #410). Equals ``book_notional`` at beta
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
        achieved_convexity_pct: ``contracts_needed *
            metrics.per_contract_convexity_pct`` -- crash gain over the
            unadjusted book notional, read through the compliance strip's
            own gauge (#410), **for this cell bought alone**.
        achieved_convexity: The referee's grading of
            ``achieved_convexity_pct`` against the IPS convexity band
            (:func:`~deltadewa.analysis.convexity_band.grade_convexity`).
        meets_convexity: Derived from ``achieved_convexity``: ``True`` when
            the figure lies within the band, inclusive at both ends.
        meets_target_within_budget: Derived: ``True`` when both
            ``within_budget`` and ``meets_convexity`` are ``True``.

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
    achieved_convexity: ConvexityGrading

    @property
    def meets_convexity(self) -> bool | None:
        """Derived from the grading; ``None`` only if it was unmeasured."""
        return self.achieved_convexity.meets

    @property
    def meets_target_within_budget(self) -> bool:
        """Both the carry budget and the convexity band are met."""
        return self.within_budget and self.meets_convexity is True


CandidateGrid = list[GridCell]
"""List of :class:`GridCell`, one per solved (delta, maturity) cell."""


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
class CandidateGridResult:
    """The outcome of :func:`build_candidate_grid`.

    Separates the solved cells from the cells that could not be solved so the
    latter are surfaced explicitly instead of being dropped without a trace.

    Attributes:
        cells: Solved cells, one per (delta, maturity) cell whose strike was
            found, in delta-major order.
        unsolvable: Cells whose strike could not be solved, in the same
            delta-major order. Empty when every requested cell solved.

    """

    cells: CandidateGrid
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


def build_candidate_grid(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    *,
    target_deltas: Sequence[float],
    maturities_years: Sequence[float],
    vol: float | None = None,
) -> CandidateGridResult:
    """Build a full strike/maturity ladder sized against the IPS risk budget.

    For every ``(delta, maturity)`` pair (outer loop: *target_deltas*; inner
    loop: *maturities_years*) the function:

    1. Resolves the strike via :func:`strike_for_delta`.
    2. Prices the candidate put via
       :func:`~deltadewa.analysis.candidate.evaluate_candidate`.
    3. Sizes it via :func:`~deltadewa.analysis.sizing.size_from_unit`, on
       gross payoff (#436: convexity is then the gain over the hedge's value
       today, so a cell sized to the offset can read a little under the band
       floor).
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
        :class:`CandidateGridResult` — ``cells`` is a flat list of
        :class:`GridCell` in delta-major order (all maturities for the first
        delta, then all for the second, etc.) for every cell whose strike
        solved; ``unsolvable`` lists the cells whose strike could not be solved
        (surfaced explicitly, never silently dropped).

    Raises:
        ValueError: When the book notional is 0 (no underlying position);
            the ladder's sizing is undefined and never fabricates a zero result.

    """
    # The same target the sizing workbench sizes to (beta-adjusted offset,
    # carry budget on the true notional, IPS crash basis) -- one builder,
    # so a grid cell and a sized candidate cannot disagree about it.
    basis = sizing_basis(portfolio, ips_config, purpose="strike-ladder sizing")
    # Policy, on its own path: `basis.shock` prices the cells, `conv` only
    # judges them against the band (M1.5 — the two never travel as one object).
    conv = ips_config.convexity

    cells: CandidateGrid = []
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
            shock=basis.shock,
            vol=vol,
        )
        sizing = size_from_unit(
            basis.required_crash_offset,
            metrics.per_contract_payoff,
            metrics.per_contract_carry,
            basis.carry_budget,
        )
        achieved_convexity_pct = (
            sizing.contracts_needed * metrics.per_contract_convexity_pct
        )
        achieved_convexity = grade_convexity(
            achieved_convexity_pct,
            conv,
            at_shock_pct=basis.shock.crash_scenario_pct,
        )
        cells.append(
            GridCell(
                target_delta=delta,
                maturity_years=maturity,
                metrics=metrics,
                portfolio_beta=basis.portfolio_beta,
                beta_adjusted_notional=basis.beta_adjusted_notional,
                required_crash_offset=basis.required_crash_offset,
                contracts_needed=sizing.contracts_needed,
                implied_annual_carry=sizing.implied_annual_carry,
                carry_budget=basis.carry_budget,
                within_budget=sizing.within_budget,
                carry_headroom=sizing.carry_headroom,
                max_affordable_contracts=sizing.max_affordable_contracts,
                achieved_convexity_pct=achieved_convexity_pct,
                achieved_convexity=achieved_convexity,
            ),
        )
    return CandidateGridResult(cells=cells, unsolvable=unsolvable)
