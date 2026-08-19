"""Hedge decision triggers for the deltadewa options dashboard.

Two entry points over one evaluation:

- :func:`evaluate_hedge_trigger_set` is the pure core — it reads a
  portfolio and returns each trigger's status and the plain-language
  reason for it, with no output of any kind. This is what a UI renders.
- :func:`evaluate_hedge_triggers` is the console report the notebook
  cell this module came from used. It calls the core and prints; its
  return value and its printed output are both unchanged.

The split exists because until M2.7 only the printing form existed, so
the delta, expiry, theta and gamma triggers — which M1.3 and M1.4 did
substantial correctness work on — could not be shown on either Dash page
and were live nowhere in the product.

The module is side-effect-free with respect to its inputs: neither
function mutates any object it receives.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import pandas as pd

import deltadewa.constants as const
from deltadewa.analysis.health import delta_drift_from_target
from deltadewa.clock import days_between

if TYPE_CHECKING:
    from collections.abc import Iterator

    from deltadewa.ips_config import IpsTriggers
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.reporting import ConsoleReporter


def gamma_drift_from_spot(
    total_gamma: float,
    spot_price: float,
    underlying_quantity: float,
) -> float | None:
    """Net-delta drift per 1% spot move, as % of the hedged equity.

    ``|total_gamma| * spot / |underlying_quantity|`` — the net-delta change (in
    index units) for a 1% spot move, divided by the equity units. Unlike raw
    gamma it is independent of book size, so a fixed band means the same thing
    on a $5M and a $50M book. Returns ``None`` when ``underlying_quantity`` is
    unset — the ratio is then undefined and the trigger reports unavailable.

    Args:
        total_gamma: Portfolio total gamma (``summary_stats`` ``total_gamma``).
        spot_price: Current underlying spot.
        underlying_quantity: Equity/underlying quantity being hedged.

    Returns:
        Gamma drift as a percent, or ``None`` when ``underlying_quantity`` is 0.

    """
    if underlying_quantity == 0:
        return None
    return abs(total_gamma) * spot_price / abs(underlying_quantity)


# ---------------------------------------------------------------------------
# Threshold configuration
# ---------------------------------------------------------------------------


@dataclass
class HedgeTriggerThresholds:
    """Configurable thresholds for each hedge decision trigger.

    All values use the same units as the notebook defaults so existing
    callers get identical output without passing any arguments.

    Parameters
    ----------
    target_delta_ratio_pct:
        Intended net-delta-to-equity ratio (%) the book is run at; delta drift
        is measured as deviation from it (default 90 %).
    delta_drift_warn_pct:
        Drift (pp from target) at which a MONITOR warning is raised (default
        5 pp).
    delta_drift_action_pct:
        Drift (pp from target) at which an ACTION REQUIRED alert is raised
        (default 10 pp).
    expiry_urgent_days:
        Days-to-expiry below which a position is classified as URGENT
        (default 7 days).
    expiry_soon_days:
        Days-to-expiry below which a position is classified as SOON
        (default 21 days).
    theta_cost_excellent_pct:
        Annualised theta cost % of portfolio below which the cost is EXCELLENT
        (default 1.0 %).
    theta_cost_acceptable_pct:
        Annualised theta cost % of portfolio below which the cost is ACCEPTABLE
        (default 2.0 %).
    gamma_drift_moderate_pct:
        Gamma drift (% of hedged equity that net delta shifts per 1% spot move)
        below which gamma risk is LOW (default 2 %).
    gamma_drift_high_pct:
        Gamma drift above which gamma risk is HIGH (default 5 %).

    """

    target_delta_ratio_pct: float = 90.0
    delta_drift_warn_pct: float = 5.0
    delta_drift_action_pct: float = 10.0
    expiry_urgent_days: int = 7
    expiry_soon_days: int = 21
    theta_cost_excellent_pct: float = 1.0
    theta_cost_acceptable_pct: float = 2.0
    gamma_drift_moderate_pct: float = 2.0
    gamma_drift_high_pct: float = 5.0

    @classmethod
    def from_ips(cls, triggers: IpsTriggers) -> HedgeTriggerThresholds:
        """Build thresholds from an ``IpsTriggers`` section.

        Every threshold this dataclass carries is mapped here — no policy
        value is left on a dataclass literal.

        Note:
            This is *not* the whole of ``IpsTriggers``. ``roll_time_months``,
            ``strike_drift_max_otm_pct``, ``strike_drift_review_fraction``
            and ``roll_review_buffer`` are roll policy, consumed by
            ``roll_planner``/``roll_status`` rather than here. But
            ``rally_rebalance_pct`` is consumed by **nothing** — the
            handbook's `"Rule 2 — Market Rally Rebalance Trigger"
            <https://qwertytam.github.io/deltadewa-handbook/part-7/rolling-rules/#rule-2-market-rally-rebalance-trigger>`_
            has never been built, and the earlier wording of this docstring
            ("every threshold the IPS defines") is why that went unnoticed.
            See ``docs/part-x-coverage.md``.

        """
        return cls(
            target_delta_ratio_pct=triggers.target_delta_ratio_pct,
            delta_drift_warn_pct=triggers.delta_drift_warn_pct,
            delta_drift_action_pct=triggers.delta_drift_action_pct,
            expiry_urgent_days=triggers.expiry_urgent_days,
            expiry_soon_days=triggers.expiry_soon_days,
            theta_cost_excellent_pct=triggers.theta_cost_excellent_pct,
            theta_cost_acceptable_pct=triggers.theta_cost_acceptable_pct,
            gamma_drift_moderate_pct=triggers.gamma_drift_moderate_pct,
            gamma_drift_high_pct=triggers.gamma_drift_high_pct,
        )


# ---------------------------------------------------------------------------
# Result dataclass (returned for programmatic use / testing)
# ---------------------------------------------------------------------------


class TriggerStatus(StrEnum):
    """One trigger's reading, in increasing order of urgency.

    Deliberately three values rather than mirroring
    :class:`~deltadewa.analysis.roll_status.RollVerdict`'s four: these
    triggers have no ROLL-equivalent, and inventing one to make the two
    enums match would imply an action this evaluation does not recommend.

    ``UNAVAILABLE`` is not "fine" — it means the metric could not be
    measured (almost always a missing ``underlying_quantity``) and must be
    shown as such rather than folded into ``OK``.
    """

    OK = "OK"
    MONITOR = "MONITOR"
    ACTION = "ACTION"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class HedgeTriggerReason:
    """One trigger's status and the plain-language reason for it.

    The counterpart of
    :class:`~deltadewa.analysis.roll_status.TriggerReason`, and rendered
    the same way: the reason states the reading *and* the threshold it was
    read against, so a verdict is never a bare word.
    """

    label: str
    status: TriggerStatus
    reason: str


@dataclass(frozen=True)
class HedgeTriggerSet:
    """Every hedge rebalance trigger, evaluated for one book.

    Distinct from :func:`~deltadewa.analysis.roll_status.evaluate_roll_status`,
    which answers "should *this tranche* be replaced" per position. These
    four answer "is the book still hedged the way policy says" for the book
    as a whole, and the two sets are never merged.

    Attributes:
        delta: Net-delta drift vs the IPS target hedge ratio.
        expiry: Nearest expiry vs the URGENT / SOON windows.
        theta: Annualised carry cost vs the EXCELLENT / ACCEPTABLE bands.
        gamma: Net-delta drift per 1% spot move vs the gamma bands.
        metrics: The raw figures behind the four readings — the same
            values :class:`HedgeTriggerResult` carries.
        actions: Priority-ordered ``(label, description)`` recommendations.

    """

    delta: HedgeTriggerReason
    expiry: HedgeTriggerReason
    theta: HedgeTriggerReason
    gamma: HedgeTriggerReason
    metrics: HedgeTriggerResult
    actions: list[tuple[str, str]]

    def __iter__(self) -> Iterator[HedgeTriggerReason]:
        """Iterate the four triggers in the order the report prints them."""
        return iter((self.delta, self.expiry, self.theta, self.gamma))


@dataclass
class HedgeTriggerResult:
    """Structured result of ``evaluate_hedge_triggers``.

    Attributes
    ----------
    delta_drift_pct:
        Signed deviation from the target hedge ratio, in percentage points
        (0 = at target), or ``None`` when ``underlying_quantity`` is unset and
        the metric is unavailable.
    days_to_nearest_expiry:
        Calendar days to the nearest position's expiry.
    near_expiry_count:
        Number of positions within ``thresholds.expiry_urgent_days``.
    theta_cost_pct:
        Annualised theta cost as a percentage of notional value, or ``None``
        when ``underlying_quantity`` is unset (the metric is unavailable).
    total_gamma:
        Absolute total portfolio gamma (raw, for reference).
    gamma_drift_pct:
        Net-delta drift per 1% spot move as % of the hedged equity — the figure
        the gamma trigger bands on. ``None`` when ``underlying_quantity`` is
        unset (the metric is then unavailable).
    actions:
        Ordered list of ``(priority_label, description)`` tuples.
        Empty when the portfolio is well-managed.

    """

    delta_drift_pct: float | None
    days_to_nearest_expiry: int
    near_expiry_count: int
    theta_cost_pct: float | None
    total_gamma: float
    gamma_drift_pct: float | None
    actions: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Banding: one decision per trigger, rendered two ways
# ---------------------------------------------------------------------------
#
# Each ``_*_reason`` below is the single place its trigger's thresholds are
# compared. The console printers dispatch on the resulting status rather than
# re-deciding, so the report and any UI can never disagree about whether a
# trigger has fired.


def _delta_reason(
    delta_drift_pct: float | None,
    t: HedgeTriggerThresholds,
) -> HedgeTriggerReason:
    """Band net-delta drift against the IPS target hedge ratio."""
    label = "Delta drift"
    if delta_drift_pct is None:
        return HedgeTriggerReason(
            label=label,
            status=TriggerStatus.UNAVAILABLE,
            reason=(
                "no underlying quantity set, so the hedge ratio cannot be "
                "measured"
            ),
        )

    reason = (
        f"{delta_drift_pct:+.1f}pp from the "
        f"{t.target_delta_ratio_pct:.0f}% target; monitor past "
        f"{t.delta_drift_warn_pct:.0f}pp, act past "
        f"{t.delta_drift_action_pct:.0f}pp"
    )
    drift = abs(delta_drift_pct)
    if drift < t.delta_drift_warn_pct:
        return HedgeTriggerReason(label, TriggerStatus.OK, reason)
    if drift < t.delta_drift_action_pct:
        return HedgeTriggerReason(label, TriggerStatus.MONITOR, reason)
    return HedgeTriggerReason(label, TriggerStatus.ACTION, reason)


def _expiry_reason(
    days_to_nearest_expiry: int,
    t: HedgeTriggerThresholds,
) -> HedgeTriggerReason:
    """Band the nearest expiry against the URGENT / SOON windows."""
    label = "Expiry"
    reason = (
        f"{days_to_nearest_expiry}d to the nearest expiry; urgent under "
        f"{t.expiry_urgent_days}d, plan rolls under {t.expiry_soon_days}d"
    )
    if days_to_nearest_expiry > t.expiry_soon_days:
        return HedgeTriggerReason(label, TriggerStatus.OK, reason)
    if days_to_nearest_expiry > t.expiry_urgent_days:
        return HedgeTriggerReason(label, TriggerStatus.MONITOR, reason)
    return HedgeTriggerReason(label, TriggerStatus.ACTION, reason)


def _theta_reason(
    theta_cost_pct: float | None,
    t: HedgeTriggerThresholds,
) -> HedgeTriggerReason:
    """Band annualised carry cost against the EXCELLENT / ACCEPTABLE bands."""
    label = "Theta cost"
    if theta_cost_pct is None:
        return HedgeTriggerReason(
            label=label,
            status=TriggerStatus.UNAVAILABLE,
            reason=(
                "no underlying quantity set, so cost as a share of the book "
                "cannot be measured"
            ),
        )

    reason = (
        f"{theta_cost_pct:.2f}% of the book per year; excellent under "
        f"{t.theta_cost_excellent_pct:.1f}%, acceptable under "
        f"{t.theta_cost_acceptable_pct:.1f}%"
    )
    if theta_cost_pct < t.theta_cost_excellent_pct:
        return HedgeTriggerReason(label, TriggerStatus.OK, reason)
    if theta_cost_pct < t.theta_cost_acceptable_pct:
        return HedgeTriggerReason(label, TriggerStatus.MONITOR, reason)
    return HedgeTriggerReason(label, TriggerStatus.ACTION, reason)


def _gamma_reason(
    gamma_drift_pct: float | None,
    t: HedgeTriggerThresholds,
) -> HedgeTriggerReason:
    """Band net-delta drift per 1% spot move against the gamma bands."""
    label = "Gamma drift"
    if gamma_drift_pct is None:
        return HedgeTriggerReason(
            label=label,
            status=TriggerStatus.UNAVAILABLE,
            reason=(
                "no underlying quantity set, so drift per 1% move cannot be "
                "measured"
            ),
        )

    reason = (
        f"{gamma_drift_pct:.2f}% of equity per 1% spot move; moderate past "
        f"{t.gamma_drift_moderate_pct:.1f}%, high past "
        f"{t.gamma_drift_high_pct:.1f}%"
    )
    if gamma_drift_pct < t.gamma_drift_moderate_pct:
        return HedgeTriggerReason(label, TriggerStatus.OK, reason)
    if gamma_drift_pct < t.gamma_drift_high_pct:
        return HedgeTriggerReason(label, TriggerStatus.MONITOR, reason)
    return HedgeTriggerReason(label, TriggerStatus.ACTION, reason)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_hedge_trigger_set(
    portfolio: OptionPortfolio,
    thresholds: HedgeTriggerThresholds | None = None,
) -> HedgeTriggerSet:
    """Evaluate every hedge rebalance trigger for *portfolio*.

    The pure counterpart of :func:`evaluate_hedge_triggers`: same metrics,
    same thresholds, same firing points — but returned as structured
    statuses and reasons instead of printed. This is what a dashboard
    renders.

    Args:
        portfolio: Live ``OptionPortfolio``. Never mutated.
        thresholds: Optional :class:`HedgeTriggerThresholds`. Pass ``None``
            for the built-in defaults; production callers should pass
            ``HedgeTriggerThresholds.from_ips(ips_config.triggers)`` so no
            threshold comes from a dataclass literal.

    Returns:
        The four triggers, the raw metrics behind them, and the
        priority-ordered action list.

    """
    t = thresholds or HedgeTriggerThresholds()
    # Evaluate DTE/expiry against the portfolio's (what-if) valuation date, not
    # the wall clock, so a moved valuation date moves the trigger logic.
    now = portfolio.valuation_date
    stats = portfolio.summary_stats()

    delta_drift_pct = delta_drift_from_target(
        stats["net_delta"],
        stats["underlying_quantity"],
        t.target_delta_ratio_pct,
    )

    days_to_nearest_expiry = (
        min(
            days_between(now, pos.option.maturity_date)
            for pos in portfolio.positions
        )
        if portfolio.positions
        else 999
    )
    near_expiry_positions = [
        pos
        for pos in portfolio.positions
        if days_between(now, pos.option.maturity_date) < t.expiry_urgent_days
    ]

    theta_cost_per_day = abs(stats["total_theta"])
    theta_annual_cost = theta_cost_per_day * const.DAYS_PER_YEAR

    # Theta cost is a % of the hedged equity; unavailable (not a fabricated 0)
    # when there is no underlying position to measure it against.
    portfolio_value = abs(stats["underlying_quantity"] * portfolio.spot_price)
    theta_cost_pct: float | None = (
        (theta_annual_cost / portfolio_value * 100)
        if portfolio_value > 0
        else None
    )

    total_gamma = abs(stats["total_gamma"])
    gamma_drift = gamma_drift_from_spot(
        stats["total_gamma"],
        portfolio.spot_price,
        stats["underlying_quantity"],
    )

    actions = _build_action_list(
        stats,
        delta_drift_pct,
        near_expiry_positions,
        days_to_nearest_expiry,
        theta_cost_pct,
        gamma_drift,
        t,
    )

    return HedgeTriggerSet(
        delta=_delta_reason(delta_drift_pct, t),
        expiry=_expiry_reason(days_to_nearest_expiry, t),
        theta=_theta_reason(theta_cost_pct, t),
        gamma=_gamma_reason(gamma_drift, t),
        metrics=HedgeTriggerResult(
            delta_drift_pct=delta_drift_pct,
            days_to_nearest_expiry=days_to_nearest_expiry,
            near_expiry_count=len(near_expiry_positions),
            theta_cost_pct=theta_cost_pct,
            total_gamma=total_gamma,
            gamma_drift_pct=gamma_drift,
            actions=actions,
        ),
        actions=actions,
    )


def evaluate_hedge_triggers(
    portfolio: OptionPortfolio,
    reporter: ConsoleReporter,
    thresholds: HedgeTriggerThresholds | None = None,
) -> HedgeTriggerResult:
    """Evaluate hedge decision triggers and print a formatted alert report.

    Reproduces the five-section "Hedge Decision Triggers" notebook cell:

    1. **Delta hedge effectiveness** — drift vs the target hedge ratio
    2. **Position expiration status** — nearest expiry and urgent positions
    3. **Time decay cost** — annualised theta as % of portfolio
    4. **Gamma exposure** — portfolio-level gamma risk
    5. **Recommended actions** — priority-ordered action list

    Parameters
    ----------
    portfolio:
        Live ``OptionPortfolio`` instance.
    reporter:
        ``ConsoleReporter`` for headers, status messages, and dividers.
    thresholds:
        Optional :class:`HedgeTriggerThresholds` to override the defaults.
        Pass ``None`` (or omit) to use the built-in defaults.

    Returns
    -------
    HedgeTriggerResult
        Structured result for programmatic use or testing.
        The function also prints the full formatted report as a side-effect.

    """
    t = thresholds or HedgeTriggerThresholds()
    triggers = evaluate_hedge_trigger_set(portfolio, t)
    metrics = triggers.metrics
    now = portfolio.valuation_date
    stats = portfolio.summary_stats()

    # Only the console form needs the positions themselves (it names each
    # one); the structured form carries the count.
    near_expiry_positions = [
        pos
        for pos in portfolio.positions
        if days_between(now, pos.option.maturity_date) < t.expiry_urgent_days
    ]
    theta_cost_per_day = abs(stats["total_theta"])
    theta_annual_cost = theta_cost_per_day * const.DAYS_PER_YEAR

    reporter.header("  HEDGE DECISION TRIGGERS")
    print()

    _print_delta_trigger(
        stats,
        metrics.delta_drift_pct,
        triggers.delta.status,
        reporter,
        t,
    )
    _print_expiry_trigger(
        portfolio,
        near_expiry_positions,
        metrics.days_to_nearest_expiry,
        triggers.expiry.status,
        reporter,
        t,
        now,
    )
    _print_theta_trigger(
        theta_annual_cost,
        theta_cost_per_day,
        metrics.theta_cost_pct,
        triggers.theta.status,
        reporter,
    )
    _print_gamma_trigger(
        metrics.total_gamma,
        metrics.gamma_drift_pct,
        triggers.gamma.status,
        reporter,
    )
    _print_action_summary(triggers.actions, reporter, t)

    return metrics


# ---------------------------------------------------------------------------
# Private section printers
# ---------------------------------------------------------------------------


def _shares_to_target(
    stats: dict[str, Any],
    t: HedgeTriggerThresholds,
) -> float:
    """Underlying shares needed to restore the target net-delta ratio.

    Positive = buy, negative = sell. Restores ``net_delta`` to
    ``target_delta_ratio_pct`` of the equity position (rather than to full
    neutrality). Equivalent to the option-delta adjustment toward target.
    """
    target_net_delta = (
        t.target_delta_ratio_pct / 100.0 * stats["underlying_quantity"]
    )
    return float(target_net_delta - stats["net_delta"])


def _print_delta_trigger(  # pylint: disable=too-many-arguments  # a printer over one already-banded trigger; every argument is a distinct print input
    stats: dict[str, Any],
    delta_drift_pct: float | None,
    status: TriggerStatus,
    reporter: ConsoleReporter,
    t: HedgeTriggerThresholds,
) -> None:
    print("1️⃣  DELTA HEDGE EFFECTIVENESS:")
    reporter.divider()
    if delta_drift_pct is None or status is TriggerStatus.UNAVAILABLE:
        reporter.warning(
            "    Delta drift: unavailable - no underlying_quantity set",
        )
        print("     → Set the equity position to measure the hedge ratio")
        print()
        return

    drift_label = (
        f"    Delta drift: {delta_drift_pct:+.1f}pp from "
        f"{t.target_delta_ratio_pct:.0f}% target"
    )
    if status is TriggerStatus.OK:
        reporter.success(f"{drift_label} - ON TARGET")
        print("     → Hedge ratio is at target, no action needed")
    elif status is TriggerStatus.MONITOR:
        direction = "under-hedged" if delta_drift_pct > 0 else "over-hedged"
        reporter.warning(f"{drift_label} - MONITOR")
        print(
            f"     → {direction}; rebalance if drift exceeds "
            f"{t.delta_drift_action_pct:.0f}pp",
        )
        print(
            f"     → Current net delta: {stats['net_delta']:.0f} "
            f"vs {stats['underlying_quantity']:.0f} equity",
        )
    else:
        direction = "under-hedged" if delta_drift_pct > 0 else "over-hedged"
        shares = _shares_to_target(stats, t)
        verb = "Buy" if shares > 0 else "Sell"
        reporter.error(f"{drift_label} - ACTION REQUIRED")
        print(f"     → Hedge is {direction} vs target!")
        print(
            f"     → {verb} {abs(shares):.0f} shares to restore the "
            f"{t.target_delta_ratio_pct:.0f}% target ratio",
        )
        print(
            f"     → Or adjust option delta by ~{abs(shares):.0f} to target",
        )
    print()


def _print_expiry_trigger(  # pylint: disable=too-many-arguments  # a printer over one already-banded trigger; every argument is a distinct print input
    portfolio: OptionPortfolio,
    near_expiry_positions: list[Any],
    days_to_nearest_expiry: int,
    status: TriggerStatus,
    reporter: ConsoleReporter,
    t: HedgeTriggerThresholds,
    now: datetime.datetime,
) -> None:
    print("2️⃣  POSITION EXPIRATION STATUS:")
    reporter.divider()
    if status is TriggerStatus.OK:
        reporter.success(
            f"    Nearest expiry: {days_to_nearest_expiry} days - NO URGENCY",
        )
    elif status is TriggerStatus.MONITOR:
        reporter.warning(
            f"    Nearest expiry: {days_to_nearest_expiry} days - "
            f"PLAN ROLLS WITHIN {t.expiry_soon_days} DAYS",
        )

        # Per-position details inside the soon-but-not-urgent window. The
        # maturity column is a date string; `days_between` compares calendar
        # dates, so the tz-stripping dance this used to need is gone and the
        # count matches the scalar triggers above exactly (#182).
        df_positions = portfolio.to_dataframe()
        if (
            not df_positions.empty
            and "days_to_expiry" not in df_positions.columns
        ):
            df_positions["days_to_expiry"] = df_positions["maturity"].apply(
                lambda x: days_between(now, pd.to_datetime(x)),
            )
        urgent_theta = (
            df_positions[df_positions["days_to_expiry"] < t.expiry_urgent_days][
                "position_theta"
            ].sum()
            if not df_positions.empty
            else 0.0
        )
        soon_theta = (
            df_positions[
                (df_positions["days_to_expiry"] >= t.expiry_urgent_days)
                & (df_positions["days_to_expiry"] < t.expiry_soon_days)
            ]["position_theta"].sum()
            if not df_positions.empty
            else 0.0
        )
        print(
            f"  • Urgent positions (<{t.expiry_urgent_days}d): "
            f"Burning ${abs(urgent_theta):.2f}/day",
        )
        print(
            f"  • Near-term positions ({t.expiry_urgent_days}-"
            f"{t.expiry_soon_days}d): "
            f"Burning ${abs(soon_theta):.2f}/day",
        )
        print("  • Recommendation: Focus rolls on urgent positions first")
    else:
        reporter.error(
            f"    {len(near_expiry_positions)} position(s) expiring in "
            f"<{t.expiry_urgent_days} days - IMMEDIATE ACTION REQUIRED",
        )
        for pos in near_expiry_positions:
            days_left = days_between(now, pos.option.maturity_date)
            reporter.warning(
                f"    {pos.option.option_type.upper()} "
                f"${pos.option.strike_price:.0f} expires in {days_left}d",
            )
        print("     → IMMEDIATE ACTION:  Roll or close these positions")
    reporter.divider()
    print()


def _print_theta_trigger(  # pylint: disable=too-many-arguments  # a printer over one already-banded trigger; every argument is a distinct print input
    theta_annual_cost: float,
    theta_cost_per_day: float,
    theta_cost_pct: float | None,
    status: TriggerStatus,
    reporter: ConsoleReporter,
) -> None:
    # As with the gamma printer: the banding moved to _theta_reason, and
    # this output names no threshold, so no thresholds argument survives.
    print("3️⃣  TIME DECAY COST:")
    reporter.divider()
    if theta_cost_pct is None or status is TriggerStatus.UNAVAILABLE:
        reporter.warning(
            "    Theta cost: unavailable - no underlying_quantity set",
        )
        print(f"     → Annual theta: ${theta_annual_cost:,.0f}/yr")
        print("     → Set the equity position to measure cost as % of book")
        print()
        return
    if status is TriggerStatus.OK:
        reporter.success(
            f"    Annual theta cost: ${theta_annual_cost:,.0f} "
            f"({theta_cost_pct:.2f}% of portfolio) - EXCELLENT",
        )
        print(f"     → Daily bleed:  ${theta_cost_per_day:.2f}/day")
        print("     → Hedge cost is very reasonable")
    elif status is TriggerStatus.MONITOR:
        reporter.warning(
            f"    Annual theta cost: ${theta_annual_cost:,.0f} "
            f"({theta_cost_pct:.2f}% of portfolio) - ACCEPTABLE",
        )
        print(f"     → Daily bleed: ${theta_cost_per_day:.2f}/day")
        print("     → Monitor if hedge is providing sufficient protection")
    else:
        reporter.error(
            f"    Annual theta cost: ${theta_annual_cost:,.0f} "
            f"({theta_cost_pct:.2f}% of portfolio) - EXPENSIVE",
        )
        print(f"     → Daily bleed: ${theta_cost_per_day:.2f}/day")
        print(
            "     → Consider:  Moving strikes further OTM, using longer dated"
            " options, or reducing hedge size",
        )
    print()


def _print_gamma_trigger(
    total_gamma: float,
    gamma_drift_pct: float | None,
    status: TriggerStatus,
    reporter: ConsoleReporter,
) -> None:
    # No ``thresholds`` argument, unlike the other three printers: once the
    # banding moved to _gamma_reason this printer stopped naming any
    # threshold in its output, so carrying one would be decoration.
    print("4️⃣  GAMMA EXPOSURE:")
    reporter.divider()
    if gamma_drift_pct is None or status is TriggerStatus.UNAVAILABLE:
        reporter.warning(
            "    Gamma drift: unavailable - no underlying_quantity set",
        )
        print("     → Set the equity position to measure gamma drift")
        print()
        return

    label = (
        f"    Gamma drift: {gamma_drift_pct:.2f}% of equity per 1% move "
        f"(gamma {total_gamma:.2f})"
    )
    if status is TriggerStatus.OK:
        reporter.success(f"{label} - LOW RISK")
        print("     → Delta will be stable as spot moves")
    elif status is TriggerStatus.MONITOR:
        reporter.warning(f"{label} - MODERATE")
        print("     → Delta will change moderately with spot price moves")
        print("     → May need intraday rebalancing on large moves")
    else:
        reporter.error(f"{label} - HIGH RISK")
        print("     → Delta is highly sensitive to spot price changes")
        print("     → Expect frequent rebalancing needs")
        print("     → Consider spreading strikes to reduce gamma concentration")
    print()


def _build_action_list(
    stats: dict[str, Any],
    delta_drift_pct: float | None,
    near_expiry_positions: list[Any],
    days_to_nearest_expiry: int,
    theta_cost_pct: float | None,
    gamma_drift_pct: float | None,
    t: HedgeTriggerThresholds,
) -> list[tuple[str, str]]:
    """Build a priority-ordered list of (label, description) action tuples."""
    actions: list[tuple[str, str]] = []

    # Urgent
    if near_expiry_positions:
        actions.append(
            (
                "🔴 URGENT",
                (
                    f"Roll {len(near_expiry_positions)} "
                    "expiring position(s) → Use the roll planner"
                ),
            ),
        )
    if (
        delta_drift_pct is not None
        and abs(delta_drift_pct) > t.delta_drift_action_pct
    ):
        shares = _shares_to_target(stats, t)
        actions.append(
            (
                "🔴 URGENT",
                (
                    f"Rebalance delta (adjust {abs(shares):.0f} shares) to "
                    f"restore the {t.target_delta_ratio_pct:.0f}% target ratio"
                ),
            ),
        )

    # Important but not urgent
    if (
        days_to_nearest_expiry <= t.expiry_soon_days
        and not near_expiry_positions
    ):
        actions.append(
            (
                "🟡 SOON",
                "Plan rolls for approaching expiration → Use the roll planner",
            ),
        )
    if (
        delta_drift_pct is not None
        and t.delta_drift_warn_pct
        < abs(delta_drift_pct)
        <= t.delta_drift_action_pct
    ):
        actions.append(
            (
                "🟡 SOON",
                (
                    f"Monitor delta drift ({delta_drift_pct:+.1f}pp from "
                    "target) → May need adjustment"
                ),
            ),
        )
    if (
        theta_cost_pct is not None
        and theta_cost_pct > t.theta_cost_acceptable_pct
    ):
        actions.append(
            (
                "🟡 REVIEW",
                "Hedge cost is high → Consider structure optimization",
            ),
        )

    # Monitoring
    if gamma_drift_pct is not None and gamma_drift_pct > t.gamma_drift_high_pct:
        actions.append(
            (
                "🟢 MONITOR",
                "High gamma drift → Watch for delta changes on large moves",
            ),
        )

    return actions


def _print_action_summary(
    actions: list[tuple[str, str]],
    reporter: ConsoleReporter,
    t: HedgeTriggerThresholds,
) -> None:
    reporter.header("📌 RECOMMENDED ACTIONS (Priority Order)")
    if not actions:
        reporter.success(
            " No immediate actions required - portfolio is well-managed",
        )
        print("\n  Continue monitoring:")
        print(
            f"    • Delta drift (rebalance if "
            f">{t.delta_drift_action_pct:.0f}pp from target)",
        )
        print(
            f"    • Approaching expirations (roll before "
            f"<{t.expiry_urgent_days} days)",
        )
        print("    • Theta bleed relative to protection value")
    else:
        for i, (priority, action) in enumerate(actions, 1):
            print(f"\n{i}. {priority}:  {action}")
    print()
    reporter.divider()
