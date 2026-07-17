"""Crash-scenario payoff-ratio analysis for the hedge book.

Answers "for every dollar of put premium paid, how many dollars does the
hedge pay out if the underlying drops X%?" — distinct from
``HealthMixin.calculate_crash_convexity_pct``, which expresses crash P&L as
a % of the protected book's notional rather than as a multiple of premium
paid.

A payoff ratio of 8.5x means the hedge returns 8.5x its cost in the defined
crash; net-profit ratio = payoff_ratio - 1.  Gross payoff is computed from
the intrinsic value of long put legs at the shocked spot under flat vol — a
conservative, time-value-excluding estimate.  Full crash-mark repricing with
a vol shock is a later refinement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np

from deltadewa import constants as const
from deltadewa.analysis.base import PortfolioAnalyzer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltadewa.ips_config import IpsConvexity
    from deltadewa.portfolio.core import OptionPortfolio


_DEFAULT_SCENARIO_SHOCKS: tuple[float, ...] = (-10.0, -20.0, -30.0, -40.0)


class PremiumBasis(StrEnum):
    """Which premium figure was used to compute payoff ratios."""

    PAID = "paid"
    """entry_premium is populated on every long put — uses cost basis."""
    MARK = "mark (approx)"
    """Fallback: current mark price (some/all positions lack entry_premium)."""


@dataclass(frozen=True)
class CrashConvexityResult:
    """Compute-once crash payoff and convexity analysis result.

    Shared value object consumed by the scenario table widget and the
    crash convexity chart — prices each shock exactly once.

    Attributes:
        curve: Fine-grid payoff curve, ``n_points`` evenly-spaced
            ``(shock_pct, gross_payoff)`` pairs sorted ascending by
            shock_pct (severe to mild).  Used for the smooth left-panel
            line in the chart.
        scenario_rows: Discrete payoff ladder at standard shocks plus the
            IPS crash point, sorted mild to severe.  Used for the table
            widget and the right-panel bar chart.
        payoff_ratio: Gross payoff at ``ips_convexity.crash_scenario_pct``
            divided by ``premium_paid``.  ``None`` when no *ips_convexity*
            was supplied or when premium is zero.
        premium_paid: Total put premium used as the denominator (dollars).
        premium_basis: Whether *premium_paid* came from ``entry_premium``
            fields or the current mark.
        ips_convexity: The ``IpsConvexity`` target used, or ``None``.

    """

    curve: list[tuple[float, float]]
    scenario_rows: list[CrashScenarioRow]
    payoff_ratio: float | None
    premium_paid: float
    premium_basis: PremiumBasis
    ips_convexity: IpsConvexity | None


@dataclass(frozen=True)
class CrashScenarioRow:
    """One row of a crash-scenario payoff ladder for the hedge book.

    Attributes:
        shock_pct: Signed shock percent for this row (e.g. -25.0).
        hedge_pnl: Gross intrinsic payoff of long put legs at the shocked
            spot (no cost basis subtracted).
        payoff_ratio: hedge_pnl as a multiple of premium paid.
        convexity_pct: Net-of-underlying crash P&L as % of book notional
            (``HealthMixin.calculate_crash_convexity_pct``).
        meets_target: Whether convexity_pct falls within the IPS
            convexity target band, if one was supplied.

    """

    shock_pct: float
    hedge_pnl: float
    payoff_ratio: float
    convexity_pct: float
    meets_target: bool


def _shock_to_multiplier(shock_pct: float) -> float:
    """Convert a signed shock percent (e.g. -25.0) to a spot multiplier."""
    return 1 + shock_pct / 100


def _gross_long_put_payoff(
    portfolio: OptionPortfolio,
    shock_pct: float,
) -> float:
    """Gross intrinsic payoff of long put legs at a shocked spot.

    Returns ``sum(max(0, strike - crash_spot) * qty * contract_size)``
    over positions where ``option_type == PUT`` and ``quantity > 0``.
    No cost basis is subtracted — this is the gross (numerator) figure
    used in the payoff ratio.

    Note: uses intrinsic-at-expiry under flat vol — a conservative,
    time-value-excluding estimate; full crash-mark repricing with a vol
    shock is a later refinement.

    Args:
        portfolio: Portfolio to evaluate.
        shock_pct: Signed shock percent (e.g. -25.0).

    Returns:
        Gross intrinsic payoff in dollars.

    """
    crash_spot = portfolio.spot_price * _shock_to_multiplier(shock_pct)
    return sum(
        max(0.0, pos.option.strike_price - crash_spot)
        * pos.quantity
        * pos.contract_size
        for pos in portfolio.positions
        if pos.option.option_type == const.OptionType.PUT and pos.quantity > 0
    )


def _premium_with_basis(
    portfolio: OptionPortfolio,
) -> tuple[float, PremiumBasis]:
    """Return (total_premium, basis) for the long puts in *portfolio*.

    Returns ``PremiumBasis.ENTRY`` and a cost-basis total only when
    *every* long put carries a non-``None`` ``entry_premium``.  Falls
    back to current mark via ``_net_protective_premium`` otherwise.

    Args:
        portfolio: Portfolio to evaluate.

    Returns:
        Tuple of (total_premium_dollars, PremiumBasis).

    """
    long_puts = [
        pos
        for pos in portfolio.positions
        if pos.option.option_type == const.OptionType.PUT and pos.quantity > 0
    ]
    if not long_puts:
        return _net_protective_premium(portfolio), PremiumBasis.MARK
    entry_premiums: list[float] = []
    for pos in long_puts:
        if pos.entry_premium is None:
            return _net_protective_premium(portfolio), PremiumBasis.MARK
        entry_premiums.append(pos.entry_premium)
    total = sum(
        ep * abs(pos.quantity) * pos.contract_size
        for ep, pos in zip(entry_premiums, long_puts, strict=True)
    )
    return total, PremiumBasis.PAID


def _net_protective_premium(portfolio: OptionPortfolio) -> float:
    """Net premium paid for long puts (the crash-protection legs).

    Args:
        portfolio: Portfolio to evaluate.

    Returns:
        Sum of ``position_value()`` over long put positions. Zero if
        there are none.

    """
    return sum(
        pos.position_value()
        for pos in portfolio.positions
        if pos.option.option_type == const.OptionType.PUT and pos.quantity > 0
    )


def crash_payoff_ratio(
    portfolio: OptionPortfolio,
    *,
    crash_pct: float,
    premium: float | None = None,
) -> float:
    """Gross hedge payoff at a crash shock, as a multiple of premium paid.

    Args:
        portfolio: Portfolio to evaluate.
        crash_pct: Signed shock percent (e.g. -25.0 for a 25% decline).
            Converted internally to a spot multiplier (-25.0 -> 0.75).
        premium: Premium paid for the hedge in dollars.  Defaults to
            ``_premium_with_basis(portfolio)`` (entry cost when available,
            current mark otherwise) when not supplied.

    Returns:
        gross_payoff / premium, or 0.0 if premium is zero or negative —
        there's no meaningful ratio to a non-positive premium.

    """
    if premium is None:
        premium, _ = _premium_with_basis(portfolio)
    if premium <= 0:
        return 0.0
    return _gross_long_put_payoff(portfolio, crash_pct) / premium


def compute_crash_convexity(
    portfolio: OptionPortfolio,
    *,
    shock_range: tuple[float, float] = (-40.0, 10.0),
    n_points: int = 51,
    ips_convexity: IpsConvexity | None = None,
    scenario_shocks: Sequence[float] | None = None,
) -> CrashConvexityResult:
    """Build a gross-payoff curve once and sample scenario rows from it.

    Prices each grid point exactly once via ``_gross_long_put_payoff``,
    then:

    - exposes the full fine grid as ``result.curve`` for smooth chart
      rendering;
    - samples ``result.scenario_rows`` at the standard shock points
      (by default ``_DEFAULT_SCENARIO_SHOCKS``) plus the IPS crash
      scenario, without re-calling the payoff helper.

    Args:
        portfolio: Portfolio to evaluate.
        shock_range: (min_shock_pct, max_shock_pct) bounding the grid.
        n_points: Number of evenly-spaced points in the fine grid.
        ips_convexity: IPS convexity target.  When supplied the IPS
            crash scenario is guaranteed to appear in both the grid and
            ``scenario_rows``, and ``payoff_ratio`` is populated.
        scenario_shocks: Explicit shocks to include in
            ``scenario_rows``.  ``None`` uses
            ``_DEFAULT_SCENARIO_SHOCKS`` filtered to ``shock_range``.

    Returns:
        ``CrashConvexityResult`` with curve, scenario_rows,
        payoff_ratio, premium_paid, premium_basis, and ips_convexity.

    """
    premium_paid, premium_basis = _premium_with_basis(portfolio)

    # Fine grid (rounded to avoid float-key mismatches).
    lo, hi = shock_range
    fine_grid: set[float] = {
        round(float(s), 6) for s in np.linspace(lo, hi, n_points)
    }

    # Resolved scenario shocks (within range or explicit overrides).
    if scenario_shocks is None:
        s_shocks: set[float] = {
            s for s in _DEFAULT_SCENARIO_SHOCKS if lo <= s <= hi
        }
    else:
        s_shocks = {round(float(s), 6) for s in scenario_shocks}

    # IPS crash point is always present in both sets when supplied.
    ips_shock: float | None = None
    if ips_convexity is not None:
        ips_shock = round(ips_convexity.crash_scenario_pct, 6)
        s_shocks.add(ips_shock)
        fine_grid.add(ips_shock)

    # Single pass: price every unique shock point once.
    all_shocks = fine_grid | s_shocks
    payoff_dict: dict[float, float] = {
        s: _gross_long_put_payoff(portfolio, s) for s in all_shocks
    }

    # Curve — fine grid only, sorted ascending (severe left to mild right).
    curve: list[tuple[float, float]] = [
        (s, payoff_dict[s]) for s in sorted(fine_grid)
    ]

    # Scenario rows — sampled from payoff_dict, sorted mild to severe.
    analyzer = PortfolioAnalyzer(portfolio)
    scenario_rows: list[CrashScenarioRow] = []
    for shock_pct in sorted(s_shocks, reverse=True):
        hedge_pnl = payoff_dict[shock_pct]
        ratio = hedge_pnl / premium_paid if premium_paid > 0 else 0.0
        convexity_pct = analyzer.calculate_crash_convexity_pct(
            crash_scenario_pct=shock_pct,
        )
        meets_target = (
            ips_convexity.target_min_pct
            <= convexity_pct
            <= ips_convexity.target_max_pct
            if ips_convexity is not None
            else False
        )
        scenario_rows.append(
            CrashScenarioRow(
                shock_pct=shock_pct,
                hedge_pnl=hedge_pnl,
                payoff_ratio=ratio,
                convexity_pct=convexity_pct,
                meets_target=meets_target,
            ),
        )

    # Headline payoff ratio at the IPS crash shock.
    payoff_ratio: float | None = None
    if ips_shock is not None and premium_paid > 0:
        payoff_ratio = payoff_dict[ips_shock] / premium_paid

    return CrashConvexityResult(
        curve=curve,
        scenario_rows=scenario_rows,
        payoff_ratio=payoff_ratio,
        premium_paid=premium_paid,
        premium_basis=premium_basis,
        ips_convexity=ips_convexity,
    )


def crash_scenario_table(
    portfolio: OptionPortfolio,
    *,
    shocks: Sequence[float],
    ips_convexity: IpsConvexity | None = None,
) -> list[CrashScenarioRow]:
    """Return discrete scenario rows; thin wrapper over compute_crash_convexity.

    Args:
        portfolio: Portfolio to evaluate.
        shocks: Signed shock percents (e.g. [-10.0, -25.0]).
            ``ips_convexity.crash_scenario_pct`` is added automatically
            when not already present.
        ips_convexity: IPS convexity target; sets ``meets_target`` flags.

    Returns:
        One ``CrashScenarioRow`` per shock, sorted mild to severe.

    """
    return compute_crash_convexity(
        portfolio,
        ips_convexity=ips_convexity,
        scenario_shocks=shocks,
    ).scenario_rows
