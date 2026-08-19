"""Per-position roll recommendations derived from roll-status verdicts.

Converts the HOLD/MONITOR/REVIEW/ROLL verdict produced by
:func:`~deltadewa.analysis.roll_status.evaluate_roll_status` into a
concrete :class:`RollAction` (ROLL_NOW, DELAY, or HOLD) for each long
protective put, applying the `handbook
<https://github.com/qwertytam/deltadewa-handbook>`_ gamma/theta nuance: defer a
mechanical roll only when the position is outside the mandatory roll
window, has moved nearer the money since entry, and crash convexity is
still within the IPS target band.  See :func:`gamma_theta_delay` for why
the middle condition is load-bearing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from deltadewa import constants as const
from deltadewa.analysis.roll_status import (
    RollStatusRecord,
    RollVerdict,
    estimate_roll_up_cost,
    evaluate_roll_status,
    new_strike_for_entry_otm,
)
from deltadewa.analysis.strike_ladder import strike_for_delta
from deltadewa.constants import OptionType

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsConfig, IpsConvexity, IpsTriggers
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition


class RollAction(StrEnum):
    """Recommended action for a long put position.

    Verdicts in increasing order of urgency are HOLD, DELAY, ROLL_NOW.
    """

    ROLL_NOW = "ROLL_NOW"
    """A trigger has fired and immediate action is warranted."""

    DELAY = "DELAY"
    """A trigger fired but the gamma/theta nuance says defer the roll.

    Only reachable when the put is gaining gamma — never on a rally.
    """

    HOLD = "HOLD"
    """No trigger is active; no action needed."""


@dataclass(frozen=True)
class RollPlanRecord:
    """Roll plan for one long protective put position.

    Attributes:
        position: The OptionPosition being evaluated.
        verdict: Raw HOLD/MONITOR/REVIEW/ROLL from
            :func:`~deltadewa.analysis.roll_status.evaluate_roll_status`.
        action: Recommended action after applying the gamma/theta delay
            nuance.
        target_basis: Strike-selection method used —
            ``"entry_otm"`` or ``"delta"``.
        target_strike: Proposed new strike for the rolled position.
            ``None`` when ``entry_spot`` is unknown (entry_otm basis)
            or when the delta solve falls outside the solvable range.
        roll_up_cost: Cash cost to roll to *target_strike* in dollars
            (positive = debit).  ``None`` when *target_strike* is
            ``None``.
        convexity_now_pct: Portfolio crash-convexity at the IPS crash
            scenario (net P&L as % of book notional).
        meets_convexity_target: ``True`` when *convexity_now_pct* lies
            within the IPS target band.
        gamma: Per-contract gamma of the current position
            (option gamma x contract_size).
        theta: Per-contract theta of the current position in $/day
            (negative for a long put).
        rationale: One-sentence summary of the recommendation.

    """

    position: OptionPosition
    verdict: RollVerdict
    action: RollAction
    target_basis: str
    target_strike: float | None
    roll_up_cost: float | None
    convexity_now_pct: float
    meets_convexity_target: bool
    gamma: float
    theta: float
    rationale: str


def gamma_theta_delay(
    *,
    months_to_maturity: float,
    convexity_now_pct: float,
    drift_pct: float | None,
    ips_triggers: IpsTriggers,
    ips_convexity: IpsConvexity,
) -> bool:
    """Return True when the gamma/theta nuance says to defer the roll.

    The handbook (`"Rule 1 — Time-Based Roll"
    <https://qwertytam.github.io/deltadewa-handbook/part-7/rolling-rules/#rule-1-time-based-roll>`_,
    the gamma/theta trade-off note) sanctions deferring a roll on three
    conditions, all required:

    1. the time trigger is not yet urgent — the position has not
       entered the mandatory roll window
       (``months_to_maturity > roll_time_months``);
    2. **the put has moved meaningfully nearer to the money**
       (``drift_pct < 0``) — this is the whole basis for the deferral,
       because a put drifting toward the strike is accumulating
       favourable gamma that a mechanical roll would throw away;
    3. the key check — crash convexity at current spot still meets the
       IPS target band.

    Condition 2 is not optional garnish. Without it the deferral also
    catches the *opposite* case: a put pushed further OTM by a market
    rally, whose delta has collapsed and which is accumulating no gamma
    at all. That is the handbook's `"Rule 2 — Market Rally Rebalance
    Trigger"
    <https://qwertytam.github.io/deltadewa-handbook/part-7/rolling-rules/#rule-2-market-rally-rebalance-trigger>`_,
    where the sanctioned action is to roll up, not to wait.
    Deferring there would recommend inaction on a live rally trigger
    while citing a gamma position that does not exist.

    This is the same three-part test
    :func:`~deltadewa.analysis.roll_status.evaluate_roll_status` applies
    when it suppresses a drift-only ROLL to MONITOR; the two layers
    state one policy, deliberately.

    Args:
        months_to_maturity: Calendar months remaining to expiry.
        convexity_now_pct: Current portfolio crash-convexity percent.
        drift_pct: Signed change in %OTM since entry (see
            :class:`~deltadewa.analysis.roll_status.MoneynessDrift`) —
            negative means the option has moved nearer the money.
            ``None`` when the position has no recorded ``entry_spot``,
            which cannot support a deferral: the gamma story is
            unverifiable, so the roll stands.
        ips_triggers: IPS trigger thresholds (supplies
            ``roll_time_months``).
        ips_convexity: IPS convexity target band (supplies
            ``target_min_pct`` / ``target_max_pct``).

    Returns:
        ``True`` only when all three conditions hold and the roll should
        be deferred; ``False`` when the roll window has been breached,
        convexity is outside the target band, or the option has not
        moved nearer the money.

    """
    not_in_roll_window = months_to_maturity > ips_triggers.roll_time_months
    in_target_band = (
        ips_convexity.target_min_pct
        <= convexity_now_pct
        <= ips_convexity.target_max_pct
    )
    nearer_the_money = drift_pct is not None and drift_pct < 0
    return not_in_roll_window and in_target_band and nearer_the_money


def _roll_now_rationale(
    record: RollStatusRecord,
    ips_triggers: IpsTriggers,
) -> str:
    """One-sentence rationale identifying the primary ROLL_NOW trigger."""
    if record.days_to_maturity <= record.roll_window_days:
        return (
            f"Time trigger: {record.days_to_maturity}d to expiry"
            f" inside {record.roll_window_days}d roll window."
        )
    if record.crash_convexity_pct < record.convexity_target_min_pct:
        return (
            f"Convexity {record.crash_convexity_pct:.1f}%"
            f" below target minimum"
            f" {record.convexity_target_min_pct:.1f}%."
        )
    drift = record.moneyness.drift_pct
    if drift is not None and abs(drift) > ips_triggers.strike_drift_max_otm_pct:
        direction = "further OTM" if drift > 0 else "nearer the money"
        return (
            f"Strike drift {drift:+.1f}% ({direction}) exceeded the"
            f" {ips_triggers.strike_drift_max_otm_pct:.0f}% threshold."
        )
    return f"Roll recommended ({record.verdict})."


def _delay_rationale(
    record: RollStatusRecord,
    *,
    months_to_maturity: float,
    convexity_now_pct: float,
    ips_triggers: IpsTriggers,
    ips_convexity: IpsConvexity,
) -> str:
    """Spell out all three conditions that earned a DELAY.

    A bare "DELAY" on a fired trigger reads as the tool ignoring a live
    signal, so name each leg of :func:`gamma_theta_delay`'s test against
    the IPS value it was measured on. Every threshold quoted here comes
    from *ips_triggers* / *ips_convexity* — none is a literal.
    """
    drift = record.moneyness.drift_pct
    nearer_pct = abs(drift) if drift is not None else 0.0
    return (
        f"Roll warranted ({record.verdict}) but deferring:"
        f" the put has moved {nearer_pct:.1f}% nearer the money since"
        " entry, so it is gaining gamma;"
        f" {months_to_maturity:.1f} mo to expiry is still outside the"
        f" {ips_triggers.roll_time_months:.0f} mo roll window;"
        f" and crash convexity {convexity_now_pct:.1f}% is inside the"
        f" {ips_convexity.target_min_pct:.0f}-"
        f"{ips_convexity.target_max_pct:.0f}% IPS target band."
        " Revisit when any of the three stops holding."
    )


def build_roll_plan(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    *,
    target_basis: Literal["entry_otm", "delta"] = "entry_otm",
    target_delta: float | None = None,
) -> list[RollPlanRecord]:
    """Build per-position roll recommendations for all long puts.

    Calls
    :func:`~deltadewa.analysis.roll_status.evaluate_roll_status` once
    to obtain verdicts, then for each long protective put:

    1. Selects a target strike via *target_basis*.
    2. Prices the roll via
       :func:`~deltadewa.analysis.roll_status.estimate_roll_up_cost`.
    3. Applies :func:`gamma_theta_delay` to map the verdict to a
       :class:`RollAction`.

    Positions with no ``entry_spot`` recorded yield
    ``target_strike=None`` and ``roll_up_cost=None`` when
    *target_basis* is ``"entry_otm"``; no exception is raised.

    Args:
        portfolio: Live portfolio to evaluate.
        ips_config: Hedge program policy (triggers, convexity targets).
        target_basis: How to select the target strike.
            ``"entry_otm"`` restores entry OTM% at current spot.
            ``"delta"`` uses *target_delta*.
        target_delta: Required when *target_basis* is ``"delta"`` —
            desired put-delta magnitude (e.g. ``0.10`` for a 10-delta
            put).  Ignored for ``"entry_otm"``.

    Returns:
        One :class:`RollPlanRecord` per long put in
        ``portfolio.positions`` order.  Empty when no long puts exist.

    """
    status_records = evaluate_roll_status(portfolio, ips_config)
    spot = portfolio.spot_price
    ips_convexity = ips_config.convexity
    ips_triggers = ips_config.triggers

    result: list[RollPlanRecord] = []
    for record in status_records:
        pos = record.position
        if not (pos.option.option_type == OptionType.PUT and pos.quantity > 0):
            continue

        months_to_maturity = (
            record.days_to_maturity / const.CALENDAR_DAYS_PER_MONTH
        )

        # ── Target strike ─────────────────────────────────────────────
        target_strike: float | None = None
        if target_basis == "entry_otm":
            if record.moneyness.entry_otm_pct is not None:
                target_strike = new_strike_for_entry_otm(
                    pos.option.option_type,
                    spot,
                    record.moneyness.entry_otm_pct,
                )
        elif target_basis == "delta" and target_delta is not None:
            maturity_years = record.days_to_maturity / const.DAYS_PER_YEAR
            target_strike = strike_for_delta(
                portfolio,
                target_delta=target_delta,
                maturity_years=maturity_years,
            )

        # ── Roll cost ─────────────────────────────────────────────────
        roll_up_cost: float | None = None
        if target_strike is not None:
            roll_up_cost = estimate_roll_up_cost(
                pos,
                target_strike,
                pos.option.volatility,
            )

        # ── Convexity ────────────────────────────────────────────────
        convexity_now_pct = record.crash_convexity_pct
        meets_convexity_target = (
            ips_convexity.target_min_pct
            <= convexity_now_pct
            <= ips_convexity.target_max_pct
        )

        # ── Greeks per contract ───────────────────────────────────────
        gamma = pos.option.gamma() * pos.contract_size
        theta = pos.option.theta() * pos.contract_size

        # ── Verdict → Action ─────────────────────────────────────────
        actionable = record.verdict in (
            RollVerdict.ROLL,
            RollVerdict.REVIEW,
        )
        if actionable and gamma_theta_delay(
            months_to_maturity=months_to_maturity,
            convexity_now_pct=convexity_now_pct,
            drift_pct=record.moneyness.drift_pct,
            ips_triggers=ips_triggers,
            ips_convexity=ips_convexity,
        ):
            action = RollAction.DELAY
        elif actionable:
            action = RollAction.ROLL_NOW
        else:
            action = RollAction.HOLD

        # ── Rationale ─────────────────────────────────────────────────
        if action == RollAction.HOLD:
            rationale = "No trigger active; holding."
        elif action == RollAction.DELAY:
            rationale = _delay_rationale(
                record,
                months_to_maturity=months_to_maturity,
                convexity_now_pct=convexity_now_pct,
                ips_triggers=ips_triggers,
                ips_convexity=ips_convexity,
            )
        else:
            rationale = _roll_now_rationale(record, ips_triggers)

        result.append(
            RollPlanRecord(
                position=pos,
                verdict=record.verdict,
                action=action,
                target_basis=target_basis,
                target_strike=target_strike,
                roll_up_cost=roll_up_cost,
                convexity_now_pct=convexity_now_pct,
                meets_convexity_target=meets_convexity_target,
                gamma=gamma,
                theta=theta,
                rationale=rationale,
            ),
        )

    return result
