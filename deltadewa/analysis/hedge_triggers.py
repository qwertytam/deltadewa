"""Hedge decision triggers for the deltadewa options dashboard.

Encapsulates the ~80-line "Hedge Decision Triggers" section of
``monitor_dashboard.ipynb`` into a single importable function.

The module is intentionally side-effect-free: ``evaluate_hedge_triggers``
reads from ``portfolio`` and writes formatted output via ``reporter``, but
never mutates any object it receives.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import deltadewa.constants as const
from deltadewa.analysis.health import delta_drift_from_target

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsTriggers
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.reporting import ConsoleReporter


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
    gamma_low:
        Total gamma below which gamma risk is LOW (default 10).
    gamma_moderate:
        Total gamma below which gamma risk is MODERATE (default 30).

    """

    target_delta_ratio_pct: float = 90.0
    delta_drift_warn_pct: float = 5.0
    delta_drift_action_pct: float = 10.0
    expiry_urgent_days: int = 7
    expiry_soon_days: int = 21
    theta_cost_excellent_pct: float = 1.0
    theta_cost_acceptable_pct: float = 2.0
    gamma_low: float = 10.0
    gamma_moderate: float = 30.0

    @classmethod
    def from_ips(cls, triggers: IpsTriggers) -> HedgeTriggerThresholds:
        """Build thresholds from an ``IpsTriggers`` section.

        Fields the IPS schema does not define (``expiry_urgent_days``,
        ``expiry_soon_days``, ``theta_cost_excellent_pct``, ``gamma_low``,
        ``gamma_moderate``) keep this dataclass's literal defaults.
        """
        return cls(
            target_delta_ratio_pct=triggers.target_delta_ratio_pct,
            delta_drift_warn_pct=triggers.delta_drift_warn_pct,
            delta_drift_action_pct=triggers.delta_drift_action_pct,
            theta_cost_acceptable_pct=triggers.theta_cost_acceptable_pct,
        )


# ---------------------------------------------------------------------------
# Result dataclass (returned for programmatic use / testing)
# ---------------------------------------------------------------------------


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
        Annualised theta cost as a percentage of notional value.
    total_gamma:
        Absolute total portfolio gamma.
    actions:
        Ordered list of ``(priority_label, description)`` tuples.
        Empty when the portfolio is well-managed.

    """

    delta_drift_pct: float | None
    days_to_nearest_expiry: int
    near_expiry_count: int
    theta_cost_pct: float
    total_gamma: float
    actions: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
        Pass ``None`` (or omit) to use the same values as the notebook.

    Returns
    -------
    HedgeTriggerResult
        Structured result for programmatic use or testing.
        The function also prints the full formatted report as a side-effect.

    """
    t = thresholds or HedgeTriggerThresholds()
    now = datetime.datetime.now(tz=datetime.UTC)

    # --- compute metrics ---
    stats = portfolio.summary_stats()

    delta_drift_pct = delta_drift_from_target(
        stats["net_delta"],
        stats["underlying_quantity"],
        t.target_delta_ratio_pct,
    )

    days_to_nearest_expiry = (
        min(
            (pos.option.maturity_date - now).days for pos in portfolio.positions
        )
        if portfolio.positions
        else 999
    )

    near_expiry_positions = [
        pos
        for pos in portfolio.positions
        if (pos.option.maturity_date - now).days < t.expiry_urgent_days
    ]

    theta_cost_per_day = abs(stats["total_theta"])
    theta_annual_cost = theta_cost_per_day * const.DAYS_PER_YEAR

    portfolio_value = abs(stats["underlying_quantity"] * portfolio.spot_price)
    theta_cost_pct = (
        (theta_annual_cost / portfolio_value * 100)
        if portfolio_value > 0
        else 0.0
    )

    total_gamma = abs(stats["total_gamma"])

    # --- print report ---
    reporter.header("  HEDGE DECISION TRIGGERS")
    print()

    _print_delta_trigger(stats, delta_drift_pct, reporter, t)
    _print_expiry_trigger(
        portfolio,
        near_expiry_positions,
        days_to_nearest_expiry,
        reporter,
        t,
        now,
    )
    _print_theta_trigger(
        theta_annual_cost,
        theta_cost_per_day,
        theta_cost_pct,
        reporter,
        t,
    )
    _print_gamma_trigger(total_gamma, reporter, t)

    actions = _build_action_list(
        stats,
        delta_drift_pct,
        near_expiry_positions,
        days_to_nearest_expiry,
        theta_cost_pct,
        total_gamma,
        t,
    )
    _print_action_summary(actions, reporter, t)

    return HedgeTriggerResult(
        delta_drift_pct=delta_drift_pct,
        days_to_nearest_expiry=days_to_nearest_expiry,
        near_expiry_count=len(near_expiry_positions),
        theta_cost_pct=theta_cost_pct,
        total_gamma=total_gamma,
        actions=actions,
    )


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


def _print_delta_trigger(
    stats: dict[str, Any],
    delta_drift_pct: float | None,
    reporter: ConsoleReporter,
    t: HedgeTriggerThresholds,
) -> None:
    print("1️⃣  DELTA HEDGE EFFECTIVENESS:")
    reporter.divider()
    if delta_drift_pct is None:
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
    if abs(delta_drift_pct) < t.delta_drift_warn_pct:
        reporter.success(f"{drift_label} - ON TARGET")
        print("     → Hedge ratio is at target, no action needed")
    elif abs(delta_drift_pct) < t.delta_drift_action_pct:
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


def _print_expiry_trigger(
    portfolio: OptionPortfolio,
    near_expiry_positions: list[Any],
    days_to_nearest_expiry: int,
    reporter: ConsoleReporter,
    t: HedgeTriggerThresholds,
    now: datetime.datetime,
) -> None:
    print("2️⃣  POSITION EXPIRATION STATUS:")
    reporter.divider()
    if days_to_nearest_expiry > t.expiry_soon_days:
        reporter.success(
            f"    Nearest expiry: {days_to_nearest_expiry} days - NO URGENCY",
        )
    elif days_to_nearest_expiry > t.expiry_urgent_days:
        reporter.warning(
            f"    Nearest expiry: {days_to_nearest_expiry} days - "
            f"PLAN ROLLS WITHIN {t.expiry_soon_days} DAYS",
        )

        # Per-position details inside the soon-but-not-urgent window
        df_positions = portfolio.to_dataframe()
        if (
            not df_positions.empty
            and "days_to_expiry" not in df_positions.columns
        ):
            df_positions["days_to_expiry"] = df_positions["maturity"].apply(
                lambda x: (
                    __import__("pandas").to_datetime(x)
                    - __import__("pandas").Timestamp.now()
                ).days,
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
            days_left = (pos.option.maturity_date - now).days
            reporter.warning(
                f"    {pos.option.option_type.upper()} "
                f"${pos.option.strike_price:.0f} expires in {days_left}d",
            )
        print("     → IMMEDIATE ACTION:  Roll or close these positions")
    reporter.divider()
    print()


def _print_theta_trigger(
    theta_annual_cost: float,
    theta_cost_per_day: float,
    theta_cost_pct: float,
    reporter: ConsoleReporter,
    t: HedgeTriggerThresholds,
) -> None:
    print("3️⃣  TIME DECAY COST:")
    reporter.divider()
    if theta_cost_pct < t.theta_cost_excellent_pct:
        reporter.success(
            f"    Annual theta cost: ${theta_annual_cost:,.0f} "
            f"({theta_cost_pct:.2f}% of portfolio) - EXCELLENT",
        )
        print(f"     → Daily bleed:  ${theta_cost_per_day:.2f}/day")
        print("     → Hedge cost is very reasonable")
    elif theta_cost_pct < t.theta_cost_acceptable_pct:
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
    reporter: ConsoleReporter,
    t: HedgeTriggerThresholds,
) -> None:
    print("4️⃣  GAMMA EXPOSURE:")
    reporter.divider()
    if total_gamma < t.gamma_low:
        reporter.success(f"    Total gamma: {total_gamma:.2f} - LOW RISK")
        print("     → Delta will be stable as spot moves")
    elif total_gamma < t.gamma_moderate:
        reporter.warning(f"    Total gamma: {total_gamma:.2f} - MODERATE")
        print("     → Delta will change moderately with spot price moves")
        print("     → May need intraday rebalancing on large moves")
    else:
        reporter.error(f"    Total gamma: {total_gamma:.2f} - HIGH RISK")
        print("     → Delta is highly sensitive to spot price changes")
        print("     → Expect frequent rebalancing needs")
        print("     → Consider spreading strikes to reduce gamma concentration")
    print()


def _build_action_list(
    stats: dict[str, Any],
    delta_drift_pct: float | None,
    near_expiry_positions: list[Any],
    days_to_nearest_expiry: int,
    theta_cost_pct: float,
    total_gamma: float,
    t: HedgeTriggerThresholds,
) -> list[tuple[str, str]]:
    """Build a priority-ordered list of (label, description) action tuples."""
    actions: list[tuple[str, str]] = []

    # Urgent
    if near_expiry_positions:
        actions.append(
            (
                "🔴 URGENT",
                f"Roll {len(near_expiry_positions)} "
                f"expiring position(s) → Use Section 6",
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
                f"Rebalance delta (adjust {abs(shares):.0f} shares) to restore "
                f"the {t.target_delta_ratio_pct:.0f}% target ratio",
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
                "Plan rolls for approaching expiration → Review Section 6",
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
                f"Monitor delta drift ({delta_drift_pct:+.1f}pp from target) "
                f"→ May need adjustment",
            ),
        )
    if theta_cost_pct > t.theta_cost_acceptable_pct:
        actions.append(
            (
                "🟡 REVIEW",
                "Hedge cost is high → Consider structure optimization",
            ),
        )

    # Monitoring
    if total_gamma > t.gamma_moderate:
        actions.append(
            (
                "🟢 MONITOR",
                "High gamma → Watch for delta changes on large moves",
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
