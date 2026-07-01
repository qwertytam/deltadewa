"""Per-position roll recommendations derived from roll-status verdicts.

Converts the HOLD/MONITOR/REVIEW/ROLL verdict produced by
:func:`~deltadewa.analysis.roll_status.evaluate_roll_status` into a
concrete :class:`RollAction` (ROLL_NOW, DELAY, or HOLD) for each long
protective put, applying the handbook gamma/theta nuance: defer a
mechanical roll when the position is outside the mandatory roll window
and crash convexity is still within the IPS target band.
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
    """A trigger fired but the gamma/theta nuance says defer the roll."""

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
    ips_triggers: IpsTriggers,
    ips_convexity: IpsConvexity,
) -> bool:
    """Return True when the gamma/theta nuance says to defer the roll.

    Delay the mechanical roll when the position has NOT yet entered the
    mandatory roll window (``months_to_maturity > roll_time_months``)
    AND crash convexity is still within the IPS target band.  The
    rationale is to keep collecting gamma and convexity before paying
    theta to roll.

    Args:
        months_to_maturity: Calendar months remaining to expiry.
        convexity_now_pct: Current portfolio crash-convexity percent.
        ips_triggers: IPS trigger thresholds (supplies
            ``roll_time_months``).
        ips_convexity: IPS convexity target band (supplies
            ``target_min_pct`` / ``target_max_pct``).

    Returns:
        ``True`` when both conditions hold and the roll should be
        deferred; ``False`` when the roll window has been breached or
        convexity is outside the target band.

    """
    not_in_roll_window = months_to_maturity > ips_triggers.roll_time_months
    in_target_band = (
        ips_convexity.target_min_pct
        <= convexity_now_pct
        <= ips_convexity.target_max_pct
    )
    return not_in_roll_window and in_target_band


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
        return f"Strike drift {drift:+.1f}% OTM exceeded threshold."
    return f"Roll recommended ({record.verdict})."


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
            rationale = (
                f"Roll warranted ({record.verdict}) but deferring"
                f" — {months_to_maturity:.1f} mo to expiry,"
                f" convexity {convexity_now_pct:.1f}%"
                " within target band."
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
