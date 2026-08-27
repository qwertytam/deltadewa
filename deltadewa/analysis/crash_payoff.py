"""Crash-scenario payoff-vs-premium analysis for the hedge book.

Answers "for every dollar of put premium paid, how many dollars does the
hedge pay out if the underlying drops X%?" — distinct from
``HealthMixin.calculate_crash_convexity_pct``, which expresses crash P&L as
a % of the protected book's notional rather than as a multiple of premium
paid.

Renamed from ``crash_payoff_ratio``/``payoff_ratio`` (4.2, #303): the
handbook's `Ratio Disambiguation
<https://qwertytam.github.io/deltadewa-handbook/0.1/part-6/ratio-disambiguation/>`_
page names this the **Payoff-vs-Premium Multiple** ("no settled synonym")
and reserves **Crash Payoff Ratio** for a different figure — hedge gain
over the *equity loss* it offsets (this repo's ``offset_ratio``, whose name
the handbook lists "offset ratio" as a blessed synonym for, so that one
keeps its name). The two repo names collided with two different handbook
names; this module's rename resolves the collision by adopting the
handbook's term for what this module actually computes.

A payoff-vs-premium multiple of 8.5x means the hedge returns 8.5x its cost
in the defined crash; net-profit ratio = payoff_vs_premium - 1.  The
headline payoff is the long put legs **repriced** at the crash state (crash
spot + flat additive vol shock, full option value including time value) via
``analysis.crash_repricing`` — the same hedge-only basis the health
convexity gauge uses.  The intrinsic value at the crash spot is retained as
a separate, clearly-labelled conservative floor
(``CrashScenarioRow.intrinsic_floor``), never the headline.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np

from deltadewa import constants as const
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_hedge_value,
    crash_intrinsic_floor,
)
from deltadewa.ips_config import (
    _DEFAULT_CRASH_VOL_SHOCK,
    _DEFAULT_SKEW_REFERENCE_DELTA,
    _DEFAULT_SKEW_STEEPENING,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltadewa.ips_config import IpsConvexity
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition


_DEFAULT_SCENARIO_SHOCKS: tuple[float, ...] = (-10.0, -20.0, -30.0, -40.0)


def default_crash_shock() -> CrashShock:
    """Build the crash basis for surfaces reached before any IPS is loaded.

    Not a pricing default in disguise: :class:`CrashShock` itself has none, and
    every configured path builds one with ``CrashShock.from_ips``. This is the
    basis an unconfigured ``IpsConvexity`` would yield, kept in one place so the
    no-IPS panels can't drift apart from each other (they previously each
    inlined their own ``0.15``).

    ``crash_scenario_pct`` is ``0.0`` because callers of this helper supply the
    depth per grid point via :meth:`CrashShock.at_pct`; there is no IPS
    scenario to stand in for it.

    Returns:
        The unconfigured-policy crash basis.

    """
    return CrashShock(
        crash_scenario_pct=0.0,
        crash_vol_shock=_DEFAULT_CRASH_VOL_SHOCK,
        skew_steepening=_DEFAULT_SKEW_STEEPENING,
        skew_reference_delta=_DEFAULT_SKEW_REFERENCE_DELTA,
    )


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
            ``(shock_pct, repriced_hedge_value)`` pairs sorted ascending by
            shock_pct (severe to mild).  Values are the long puts repriced at
            each crash spot (hedge-only, full option value).  Used for the
            smooth left-panel line in the chart.
        scenario_rows: Discrete payoff ladder at standard shocks plus the
            IPS crash point, sorted mild to severe.  Used for the table
            widget and the right-panel bar chart.
        payoff_vs_premium: Repriced hedge value at
            ``ips_convexity.crash_scenario_pct`` divided by ``premium_paid``.
            ``None`` when no *ips_convexity* was supplied or when premium is
            zero.
        premium_paid: Total put premium used as the denominator (dollars).
        premium_basis: Whether *premium_paid* came from ``entry_premium``
            fields or the current mark.
        ips_convexity: The ``IpsConvexity`` target used, or ``None``.

    """

    curve: list[tuple[float, float]]
    scenario_rows: list[CrashScenarioRow]
    payoff_vs_premium: float | None
    premium_paid: float
    premium_basis: PremiumBasis
    ips_convexity: IpsConvexity | None


@dataclass(frozen=True)
class CrashScenarioRow:
    """One row of a crash-scenario payoff ladder for the hedge book.

    Attributes:
        shock_pct: Signed shock percent for this row (e.g. -25.0).
        hedge_pnl: Long put legs **repriced** at the shocked spot and crash
            vol (hedge-only, full option value; no cost basis subtracted).
        payoff_vs_premium: hedge_pnl as a multiple of premium paid.
        convexity_pct: Hedge-only repriced crash convexity as % of the
            protected book (``HealthMixin.calculate_crash_convexity_pct``).
        meets_target: Whether convexity_pct falls within the IPS
            convexity target band, if one was supplied.
        intrinsic_floor: Intrinsic value of the long put legs at the shocked
            spot — a conservative lower bound on ``hedge_pnl``, surfaced as a
            separate labelled floor (never the headline).

    """

    shock_pct: float
    hedge_pnl: float
    payoff_vs_premium: float
    convexity_pct: float
    meets_target: bool
    intrinsic_floor: float


def _long_puts(portfolio: OptionPortfolio) -> list[OptionPosition]:
    """Return the long put legs — the crash-protection positions.

    Args:
        portfolio: Portfolio to evaluate.

    Returns:
        Positions where ``option_type == PUT`` and ``quantity > 0``.

    """
    return [
        pos
        for pos in portfolio.positions
        if pos.option.option_type == const.OptionType.PUT and pos.quantity > 0
    ]


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


def payoff_vs_premium_multiple(
    portfolio: OptionPortfolio,
    *,
    shock: CrashShock,
    premium: float | None = None,
) -> float:
    """Repriced hedge payoff at a crash shock, as a multiple of premium paid.

    The numerator is the long put legs repriced at the crash spot and shocked
    vol (hedge-only, full option value including time value) — not intrinsic.

    Args:
        portfolio: Portfolio to evaluate.
        shock: The crash basis — depth, flat vol bump, and wing steepening with
            its anchor. **Required, with no default**, and built from
            ``IpsConvexity`` via ``CrashShock.from_ips`` so this ratio can never
            diverge from the crash state the gauges price at.
        premium: Premium paid for the hedge in dollars.  Defaults to
            ``_premium_with_basis(portfolio)`` (entry cost when available,
            current mark otherwise) when not supplied.

    Returns:
        repriced_payoff / premium, or 0.0 if premium is zero or negative —
        there's no meaningful ratio to a non-positive premium.

    """
    if premium is None:
        premium, _ = _premium_with_basis(portfolio)
    if premium <= 0:
        return 0.0
    repriced = crash_hedge_value(
        portfolio,
        shock=shock,
        positions=_long_puts(portfolio),
    )
    return repriced / premium


def _reprice_shock_grid(
    portfolio: OptionPortfolio,
    positions: list[OptionPosition],
    shocks: set[float],
    shock: CrashShock,
) -> tuple[dict[float, float], dict[float, float]]:
    """Reprice each shock exactly once: ``(repriced, intrinsic_floor)`` maps.

    Args:
        portfolio: Portfolio to evaluate.
        positions: Legs to price (typically the long puts).
        shocks: Unique signed shock percents to price.
        shock: The crash basis. Its own depth is ignored — each grid point is
            priced at ``shock.at_pct(...)``, which re-aims the same vol shock
            and skew at that depth so walking the grid cannot drop them.

    Returns:
        Two dicts keyed by shock percent: the repriced hedge value and the
        intrinsic floor at each shock.

    """
    repriced: dict[float, float] = {}
    floor: dict[float, float] = {}
    for shock_pct in shocks:
        at_depth = shock.at_pct(shock_pct)
        repriced[shock_pct] = crash_hedge_value(
            portfolio,
            shock=at_depth,
            positions=positions,
        )
        floor[shock_pct] = crash_intrinsic_floor(
            portfolio,
            crash_move=at_depth.crash_move,
            positions=positions,
        )
    return repriced, floor


def _build_scenario_rows(
    portfolio: OptionPortfolio,
    *,
    s_shocks: set[float],
    repriced: dict[float, float],
    floor: dict[float, float],
    premium_paid: float,
    shock: CrashShock,
    ips_convexity: IpsConvexity | None,
) -> list[CrashScenarioRow]:
    """Assemble scenario rows from the pre-priced grid, sorted mild to severe.

    Args:
        portfolio: Portfolio to evaluate (for the convexity gauge).
        s_shocks: Signed shock percents to emit as rows.
        repriced: Repriced hedge value keyed by shock percent.
        floor: Intrinsic floor keyed by shock percent.
        premium_paid: Premium denominator for the payoff ratio (dollars).
        shock: The crash basis, re-aimed per row with ``at_pct`` so each row's
            convexity is gauged at that row's depth on the same vol basis.
        ips_convexity: IPS convexity target, or ``None``. Supplies the band
            only — never the pricing, which comes from *shock*.

    Returns:
        One ``CrashScenarioRow`` per shock, sorted severe to mild.

    """
    analyzer = PortfolioAnalyzer(portfolio)
    rows: list[CrashScenarioRow] = []
    for shock_pct in sorted(s_shocks, reverse=True):
        hedge_pnl = repriced[shock_pct]
        ratio = hedge_pnl / premium_paid if premium_paid > 0 else 0.0
        convexity_pct = analyzer.calculate_crash_convexity_pct(
            shock.at_pct(shock_pct),
        )
        meets_target = (
            ips_convexity.target_min_pct
            <= convexity_pct
            <= ips_convexity.target_max_pct
            if ips_convexity is not None
            else False
        )
        rows.append(
            CrashScenarioRow(
                shock_pct=shock_pct,
                hedge_pnl=hedge_pnl,
                payoff_vs_premium=ratio,
                convexity_pct=convexity_pct,
                meets_target=meets_target,
                intrinsic_floor=floor[shock_pct],
            ),
        )
    return rows


def compute_crash_convexity(
    portfolio: OptionPortfolio,
    *,
    shock: CrashShock,
    shock_range: tuple[float, float] = (-40.0, 10.0),
    n_points: int = 51,
    ips_convexity: IpsConvexity | None = None,
    scenario_shocks: Sequence[float] | None = None,
) -> CrashConvexityResult:
    """Build a repriced-payoff curve once and sample scenario rows from it.

    Reprices the long puts at each grid point exactly once (hedge-only, full
    option value at the crash spot + flat additive vol shock), then:

    - exposes the full fine grid as ``result.curve`` for smooth chart
      rendering;
    - samples ``result.scenario_rows`` at the standard shock points
      (by default ``_DEFAULT_SCENARIO_SHOCKS``) plus the IPS crash
      scenario, without re-pricing.

    Args:
        portfolio: Portfolio to evaluate.
        shock: The crash basis every grid point is priced against — flat vol
            bump plus the wing steepening and its anchor. **Required, with no
            default**, so no path reprices spot-only or flat by omission. Its
            own depth is unused: the grid supplies each point's depth via
            ``at_pct``.
        shock_range: (min_shock_pct, max_shock_pct) bounding the grid.
        n_points: Number of evenly-spaced points in the fine grid.
        ips_convexity: IPS convexity target (policy, not pricing).  When
            supplied the IPS crash scenario is guaranteed to appear in both
            the grid and ``scenario_rows``, and ``payoff_vs_premium`` is
            populated.  Used only for ``meets_target`` band comparison,
            never for repricing — that is *shock*'s job, and the two stay
            separate arguments so policy cannot quietly move the pricing.
        scenario_shocks: Explicit shocks to include in
            ``scenario_rows``.  ``None`` uses
            ``_DEFAULT_SCENARIO_SHOCKS`` filtered to ``shock_range``.

    Returns:
        ``CrashConvexityResult`` with curve, scenario_rows,
        payoff_vs_premium, premium_paid, premium_basis, and ips_convexity.

    """
    premium_paid, premium_basis = _premium_with_basis(portfolio)
    long_puts = _long_puts(portfolio)

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

    # Single pass: reprice every unique shock point once (headline) and take
    # its intrinsic floor (conservative lower bound, never the headline).
    all_shocks = fine_grid | s_shocks
    repriced, floor = _reprice_shock_grid(
        portfolio,
        long_puts,
        all_shocks,
        shock,
    )

    # Curve — fine grid only, sorted ascending (severe left to mild right).
    curve: list[tuple[float, float]] = [
        (s, repriced[s]) for s in sorted(fine_grid)
    ]

    # Scenario rows — sampled from the repriced pass, sorted mild to severe.
    scenario_rows = _build_scenario_rows(
        portfolio,
        s_shocks=s_shocks,
        repriced=repriced,
        floor=floor,
        premium_paid=premium_paid,
        shock=shock,
        ips_convexity=ips_convexity,
    )

    # Headline payoff ratio at the IPS crash shock.
    payoff_vs_premium: float | None = None
    if ips_shock is not None and premium_paid > 0:
        payoff_vs_premium = repriced[ips_shock] / premium_paid

    return CrashConvexityResult(
        curve=curve,
        scenario_rows=scenario_rows,
        payoff_vs_premium=payoff_vs_premium,
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
            when not already present (if ips_convexity is supplied).
        ips_convexity: IPS convexity config (supplies the crash pricing basis
            and, separately, the target band comparison). When None, prices
            against :func:`default_crash_shock`.

    Returns:
        One ``CrashScenarioRow`` per shock, sorted mild to severe.

    """
    shock = (
        CrashShock.from_ips(ips_convexity)
        if ips_convexity is not None
        else default_crash_shock()
    )
    return compute_crash_convexity(
        portfolio,
        shock=shock,
        ips_convexity=ips_convexity,
        scenario_shocks=shocks,
    ).scenario_rows
