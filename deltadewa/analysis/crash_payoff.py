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

from deltadewa import constants as const
from deltadewa.analysis.base import PortfolioAnalyzer

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltadewa.ips_config import IpsConvexity
    from deltadewa.portfolio.core import OptionPortfolio


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
        rows: Full payoff ladder, mild to severe (same shape as
            ``crash_scenario_table`` returns).
        headline_row: The row at ``ips_convexity.crash_scenario_pct``,
            or ``None`` when no *ips_convexity* was supplied.
        premium: Total put premium used as the payoff-ratio denominator
            (dollars).
        premium_basis: Whether *premium* came from ``entry_premium``
            fields or the current mark.
        ips_convexity: The ``IpsConvexity`` target used, or ``None``.

    """

    rows: list[CrashScenarioRow]
    headline_row: CrashScenarioRow | None
    premium: float
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
        if pos.option.option_type == const.OptionType.PUT
        and pos.quantity > 0
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


def crash_scenario_table(
    portfolio: OptionPortfolio,
    *,
    shocks: Sequence[float],
    ips_convexity: IpsConvexity | None = None,
) -> list[CrashScenarioRow]:
    """Build a crash-scenario payoff ladder, mild to severe.

    Args:
        portfolio: Portfolio to evaluate.
        shocks: Signed shock percents (e.g. [-10.0, -25.0]).
        ips_convexity: If supplied, ``crash_scenario_pct`` is added to
            the ladder if not already present, and ``meets_target`` is
            set from ``target_min_pct <= convexity_pct <= target_max_pct``
            (inclusive, matching ``roll_status.py``'s HOLD-band
            convention). Without it, every row's ``meets_target`` is
            False — there's no target to evaluate against.

    Returns:
        One ``CrashScenarioRow`` per shock, sorted from mild to severe.

    """
    all_shocks = set(shocks)
    if ips_convexity is not None:
        all_shocks.add(ips_convexity.crash_scenario_pct)

    premium, _ = _premium_with_basis(portfolio)
    analyzer = PortfolioAnalyzer(portfolio)

    rows = []
    for shock_pct in sorted(all_shocks, reverse=True):
        hedge_pnl = _gross_long_put_payoff(portfolio, shock_pct)
        ratio = hedge_pnl / premium if premium > 0 else 0.0
        convexity_pct = analyzer.calculate_crash_convexity_pct(
            crash_pct=_shock_to_multiplier(shock_pct),
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
                payoff_ratio=ratio,
                convexity_pct=convexity_pct,
                meets_target=meets_target,
            ),
        )
    return rows


def compute_crash_convexity(
    portfolio: OptionPortfolio,
    *,
    shocks: Sequence[float],
    ips_convexity: IpsConvexity | None = None,
) -> CrashConvexityResult:
    """Single-pass crash payoff and convexity computation.

    Prices each shock once and returns a shared value object consumed
    by both the table widget and the crash convexity chart.  The
    premium basis (entry cost or current mark) is determined once and
    recorded on the result.

    Prefer this over calling ``crash_scenario_table`` and
    ``crash_payoff_ratio`` separately — both trigger the pricing engine
    for every shock, so combining them saves a full pass per shock.

    Args:
        portfolio: Portfolio to evaluate.
        shocks: Signed shock percents (e.g. [-10.0, -25.0]).
        ips_convexity: IPS convexity target.  When supplied,
            ``crash_scenario_pct`` is added to the ladder if absent and
            ``headline_row`` is populated.

    Returns:
        ``CrashConvexityResult`` with rows, headline, premium, and basis.

    """
    all_shocks = set(shocks)
    if ips_convexity is not None:
        all_shocks.add(ips_convexity.crash_scenario_pct)

    premium, premium_basis = _premium_with_basis(portfolio)
    analyzer = PortfolioAnalyzer(portfolio)

    rows: list[CrashScenarioRow] = []
    for shock_pct in sorted(all_shocks, reverse=True):
        hedge_pnl = _gross_long_put_payoff(portfolio, shock_pct)
        ratio = hedge_pnl / premium if premium > 0 else 0.0
        convexity_pct = analyzer.calculate_crash_convexity_pct(
            crash_pct=_shock_to_multiplier(shock_pct),
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
                payoff_ratio=ratio,
                convexity_pct=convexity_pct,
                meets_target=meets_target,
            ),
        )

    headline_row: CrashScenarioRow | None = None
    if ips_convexity is not None:
        headline_row = next(
            row
            for row in rows
            if row.shock_pct == ips_convexity.crash_scenario_pct
        )

    return CrashConvexityResult(
        rows=rows,
        headline_row=headline_row,
        premium=premium,
        premium_basis=premium_basis,
        ips_convexity=ips_convexity,
    )
