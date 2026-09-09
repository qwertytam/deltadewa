"""Per-position roll recommendations derived from roll-status verdicts.

Converts the HOLD/MONITOR/REVIEW/ROLL verdict produced by
:func:`~deltadewa.analysis.roll_status.evaluate_roll_status` into a
concrete :class:`RollAction` (ROLL_NOW, DELAY, CHECKED, or HOLD) for each
long protective put.

Two things can stop a fired trigger from becoming a roll, and they are
different judgements:

- :func:`gamma_theta_delay` — the `handbook
  <https://github.com/qwertytam/deltadewa-handbook>`_'s gamma/theta nuance.
  Defer a mechanical roll only when the position is outside the mandatory
  roll window, has moved nearer the money since entry, and crash convexity
  is still within the IPS target band. See that function for why the middle
  condition is load-bearing. The roll *is* warranted; it is being deferred.
- :func:`rally_review_cleared` — the handbook's Rule 2 REVIEW band is the
  one band whose action is stated as a conditional ("roll strikes up **if**
  the convexity target is no longer met"). When that condition is false, no
  roll is warranted at all. Before #408 this planner completed the
  conditional in the wrong direction and escalated every rally REVIEW
  straight to ROLL_NOW, on a condition it never evaluated, while the
  roll-status table beside it still read REVIEW.
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
    expired_reason,
    new_strike_for_entry_otm,
)
from deltadewa.analysis.strike_ladder import strike_for_delta
from deltadewa.constants import OptionType

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltadewa.ips_config import IpsConfig, IpsConvexity, IpsTriggers
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition


class RollAction(StrEnum):
    """Recommended action for a long put position.

    Actions in increasing order of urgency are HOLD, CHECKED, DELAY,
    ROLL_NOW.

    Unlike :class:`~deltadewa.analysis.roll_status.RollVerdict`, this scale
    is not reduced anywhere — ``/design``'s roll-plan panel is its only
    consumer, and the digest's worst-verdict line reduces ``RollVerdict``
    instead. So the order below lives in this docstring rather than in a
    ``_SEVERITY`` map, and adding a member here costs a badge rule, not a
    reduction audit (#408).
    """

    ROLL_NOW = "ROLL_NOW"
    """A trigger has fired and immediate action is warranted."""

    DELAY = "DELAY"
    """A trigger fired but the gamma/theta nuance says defer the roll.

    Only reachable when the put is gaining gamma — never on a rally.
    """

    CHECKED = "CHECKED"
    """A trigger fired, its own stated condition was evaluated, and it does
    not call for a roll (#408).

    Distinct from ``HOLD``, which means nothing fired at all, and from
    ``DELAY``, which defers a roll that *is* warranted. Reached only by the
    handbook's `Rule 2 REVIEW band
    <https://qwertytam.github.io/deltadewa-handbook/0.1/part-7/rolling-rules/#rule-2-market-rally-rebalance-trigger>`_,
    the one band whose action is conditional ("roll strikes up **if** the
    convexity target is no longer met") — see :func:`rally_review_cleared`.
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
            nuance, or ``None`` for a leg this planner declines to make a
            recommendation for (#333). ``None`` rather than a fifth
            ``RollAction`` member: inventing one would imply a
            recommendation this function is explicitly not making.
        excluded_reason: Why there is no recommendation, when ``action`` is
            ``None`` — a short leg that rolls with its structure, a
            non-put, an expired leg. Never silent: before #333 these legs
            were dropped from the plan entirely, so an operator reading
            ``/design``'s roll plan saw only the long puts with nothing
            saying the rest had been considered and skipped.
        structure_id: The structure this leg belongs to, or ``None`` for a
            standalone leg. Legs sharing a value roll as one unit and share
            a netted ``roll_up_cost``.
        target_basis: Strike-selection method used —
            ``"entry_otm"`` or ``"delta"``.
        target_strike: Proposed new strike for the rolled position.
            ``None`` when ``entry_spot`` is unknown (entry_otm basis)
            or when the delta solve falls outside the solvable range.
        roll_up_cost: Cash cost to roll in dollars (positive = debit).
            For a multi-leg structure this is the **netted** cost of moving
            every leg, repeated on each of its rows — rolling the long leg
            alone is not a trade anyone would place, and pricing it that
            way understated the cost by omitting the short leg's re-sale
            credit (#333). ``None`` when *target_strike* is ``None``.
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
    action: RollAction | None
    excluded_reason: str | None
    structure_id: str | None
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
    <https://qwertytam.github.io/deltadewa-handbook/0.1/part-7/rolling-rules/#rule-1-time-based-roll>`_,
    the gamma/theta trade-off note) sanctions deferring a roll on three
    conditions, all required:

    1. the time trigger is not yet urgent — the position has not
       entered the mandatory roll window
       (``months_to_maturity > roll_at_months_remaining``);
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
    <https://qwertytam.github.io/deltadewa-handbook/0.1/part-7/rolling-rules/#rule-2-market-rally-rebalance-trigger>`_,
    where the sanctioned action is to roll up, not to wait.
    Deferring there would recommend inaction on a live rally trigger
    while citing a gamma position that does not exist.

    Both rule links above are pinned to handbook version 0.1. The three
    conditions and the deferral they sanction are read off those two rules as
    written — including which action each one calls for — so the citations
    have to keep resolving to the text this logic was derived from rather than
    to whatever the rules say later. Drop the ``/0.1/`` segment for the
    current rules.

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
            ``roll_at_months_remaining``).
        ips_convexity: IPS convexity target band (supplies
            ``target_min_pct`` / ``target_max_pct``).

    Returns:
        ``True`` only when all three conditions hold and the roll should
        be deferred; ``False`` when the roll window has been breached,
        convexity is outside the target band, or the option has not
        moved nearer the money.

    """
    not_in_roll_window = (
        months_to_maturity > ips_triggers.roll_at_months_remaining
    )
    in_target_band = (
        ips_convexity.target_min_pct
        <= convexity_now_pct
        <= ips_convexity.target_max_pct
    )
    nearer_the_money = drift_pct is not None and drift_pct < 0
    return not_in_roll_window and in_target_band and nearer_the_money


def rally_review_cleared(record: RollStatusRecord) -> bool:
    """Return True when a rally REVIEW's own condition says "no roll" (#408).

    The handbook's `Rule 2 — Market Rally Rebalance Trigger
    <https://qwertytam.github.io/deltadewa-handbook/0.1/part-7/rolling-rules/#rule-2-market-rally-rebalance-trigger>`_
    states four bands, and only the REVIEW band's action is *conditional*:
    "Review trigger — roll strikes up **if** the convexity target is no
    longer met." Every other band prescribes outright.

    Until this function existed the planner completed that conditional in
    the wrong direction. ``build_roll_plan`` treated REVIEW and ROLL alike
    as "actionable", and :func:`gamma_theta_delay` — the only
    verdict-softening path — requires the put to have moved *nearer* the
    money, which a rally can never satisfy. So a rally REVIEW had no route
    to anything but ``ROLL_NOW``: the plan said act today, on a condition
    it never evaluated, while the roll-status table beside it still said
    REVIEW.

    All four conditions are required:

    1. ``record.verdict is REVIEW`` — ROLL is unconditional in every band
       that produces it (ACTION and URGENT both grade ROLL), and must keep
       escalating.
    2. the rally trigger is what earned that REVIEW — otherwise this is
       some other rule's REVIEW and Rule 2's condition does not govern it.
    3. the **time** trigger is not also at REVIEW. Rule 1's review buffer
       is a separate rule with no convexity condition attached; a leg
       approaching its roll window is due a look regardless of how the
       book's convexity reads, so a Rule 1 REVIEW still reaches
       ``DELAY``/``ROLL_NOW`` as before.
    4. ``record.convexity_target_met`` — the condition itself, read off the
       one boolean
       :func:`~deltadewa.analysis.roll_status.meets_convexity_target`
       resolved for the whole book, never recomputed here.

    Args:
        record: One leg's roll status, from
            :func:`~deltadewa.analysis.roll_status.evaluate_roll_status`.

    Returns:
        ``True`` when the leg's REVIEW came from Rule 2 alone and the
        convexity target is still met, so no roll is warranted —
        :attr:`RollAction.CHECKED`. ``False`` otherwise, including every
        case where the rally is at or past the ACTION band.

    """
    return (
        record.verdict is RollVerdict.REVIEW
        and record.rally_trigger.verdict is RollVerdict.REVIEW
        and record.time_trigger.verdict is not RollVerdict.REVIEW
        and record.convexity_target_met
    )


def _checked_rationale(record: RollStatusRecord) -> str:
    """State the recomputation that turned a fired trigger into no action.

    ``CHECKED`` is a recommendation to *not* act on a live trigger, so —
    exactly like :func:`_delay_rationale` — it has to arrive with its
    justification attached or it reads as the tool losing the signal. The
    rally trigger's own reason already carries the resolved conditional
    (``roll_status._convexity_recheck``), so this quotes it rather than
    wording the recomputation a second time and risking the two drifting.
    """
    return (
        f"Rally trigger: {record.rally_trigger.reason}"
        " No roll warranted while that holds; revisit if convexity leaves"
        " the band or the rally reaches the action band."
    )


def _roll_now_rationale(record: RollStatusRecord) -> str:
    """One-sentence rationale identifying the primary ROLL_NOW trigger.

    Since #408 a *rally*-sourced ROLL_NOW can only arrive here from the
    ACTION/URGENT bands (which grade ROLL outright) or from a REVIEW band
    whose condition was evaluated and found true — a rally REVIEW with
    convexity still in band is :attr:`RollAction.CHECKED` and never reaches
    this function. Either way the rally trigger's own reason now names the
    band's action or states the recomputation, so quoting it is a complete
    justification rather than a conditional passed through unevaluated.
    """
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
    if record.rally_trigger.verdict == record.verdict:
        reason = record.rally_trigger.reason
        # The REVIEW band's reason already ends in a full stop, having
        # resolved its own conditional; the other three bands do not.
        stop = "" if reason.endswith(".") else "."
        return f"Rally trigger: {reason}{stop}"
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
        f" {ips_triggers.roll_at_months_remaining:.0f} mo roll window;"
        f" and crash convexity {convexity_now_pct:.1f}% is inside the"
        f" {ips_convexity.target_min_pct:.0f}-"
        f"{ips_convexity.target_max_pct:.0f}% IPS target band."
        " Revisit when any of the three stops holding."
    )


@dataclass(frozen=True)
class RollStructure:
    """The legs that roll together, and what moving them costs (#333).

    A spread is one trade. Rolling the long leg while leaving the short leg
    behind is not a trade anyone would actually do, and pricing it that way
    understated the cost — in the *conservative* direction, since the credit
    from re-selling the short leg was simply missing.

    An outright long put is a structure of one, so the single-leg case is
    unchanged by construction rather than by a special case.

    Attributes:
        structure_id: The tag these legs share, or ``None`` for a leg that
            stands alone.
        legs: The member positions, in portfolio order.

    """

    structure_id: str | None
    legs: tuple[OptionPosition, ...]

    @property
    def is_spread(self) -> bool:
        """Whether this structure holds more than one leg."""
        return len(self.legs) > 1

    @property
    def anchor(self) -> OptionPosition | None:
        """The long put the roll is planned around, if there is one.

        The structure's geometry is restated relative to this leg: it is
        the protective leg, the one whose moneyness the roll targets. A
        structure with no long put (a naked short call, say) has no anchor
        and yields no recommendation.
        """
        for leg in self.legs:
            if leg.option.option_type == OptionType.PUT and leg.quantity > 0:
                return leg
        return None


def group_into_structures(
    positions: Sequence[OptionPosition],
) -> tuple[RollStructure, ...]:
    """Group *positions* into the structures they trade as (#333).

    Legs sharing a ``structure_id`` group together; a leg with
    ``structure_id=None`` is its own single-leg structure. Grouping is by
    the explicit tag only — never inferred from maturity/type/sign, which
    mispairs a book that legs in separately or holds overlapping spreads on
    one expiry.

    Args:
        positions: The book's legs, in portfolio order.

    Returns:
        One :class:`RollStructure` per structure, in first-appearance
        order, with each structure's legs in portfolio order.

    """
    # Keyed by the tag for a grouped leg, and by a per-leg sentinel for a
    # standalone one, so insertion order alone gives first-appearance order
    # without a second bookkeeping pass.
    grouped: dict[object, list[OptionPosition]] = {}
    for position in positions:
        tag = position.structure_id
        key: object = tag if tag is not None else object()
        grouped.setdefault(key, []).append(position)

    return tuple(
        RollStructure(
            structure_id=legs[0].structure_id,
            legs=tuple(legs),
        )
        for legs in grouped.values()
    )


def structure_target_strikes(
    structure: RollStructure,
    anchor_target_strike: float,
) -> dict[str, float]:
    """Target strike per leg, preserving the structure's geometry (#333).

    Every leg moves by the same *ratio* the anchor moves by, so a spread
    that was 5% wide stays 5% wide at the new anchor. Constant percentage
    width, not constant points: a points-width spread narrows in relative
    terms as spot rises, which is the opposite of what a re-struck tail
    hedge is for.

    Args:
        structure: The structure being rolled.
        anchor_target_strike: The new strike for
            :attr:`RollStructure.anchor`.

    Returns:
        ``{position_id: target_strike}`` for every leg. Empty when the
        structure has no anchor.

    """
    anchor = structure.anchor
    if anchor is None or anchor.option.strike_price == 0:
        return {}
    ratio = anchor_target_strike / anchor.option.strike_price
    return {
        leg.position_id: leg.option.strike_price * ratio
        for leg in structure.legs
    }


def net_structure_roll_cost(
    structure: RollStructure,
    target_strikes: dict[str, float],
) -> float | None:
    """Net cash cost of rolling every leg of *structure* together (#333).

    A straight sum over the legs, with **no sign special-casing**:
    :func:`~deltadewa.analysis.roll_status.estimate_roll_up_cost` multiplies
    by ``quantity * contract_size``, and quantity is negative on a short
    leg, so the credit from re-selling it arrives with the right sign
    already. A test pins ``structure_cost == long_cost + short_cost`` with
    the short term negative, because "sum the legs" is only obviously
    correct once someone has checked it.

    Args:
        structure: The structure being rolled.
        target_strikes: Per-leg targets from
            :func:`structure_target_strikes`.

    Returns:
        Net dollar cost (positive = debit), or ``None`` when any leg has no
        target — a partially-priced roll is not a number worth showing.

    """
    total = 0.0
    for leg in structure.legs:
        target = target_strikes.get(leg.position_id)
        if target is None:
            return None
        total += estimate_roll_up_cost(leg, target, leg.option.volatility)
    return total


def build_roll_plan(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    *,
    target_basis: Literal["entry_otm", "delta"] = "entry_otm",
    target_delta: float | None = None,
) -> list[RollPlanRecord]:
    """Build a roll recommendation for every position in the book.

    Calls
    :func:`~deltadewa.analysis.roll_status.evaluate_roll_status` once
    to obtain verdicts, groups the book into the structures its legs
    actually trade as (:func:`group_into_structures`), then for each
    structure with a long protective put:

    1. Selects a target strike via *target_basis*.
    2. Prices the roll via
       :func:`~deltadewa.analysis.roll_status.estimate_roll_up_cost`.
    3. Maps the verdict to a :class:`RollAction`, applying
       :func:`rally_review_cleared` (the Rule 2 REVIEW band's own
       condition) and :func:`gamma_theta_delay` (the gamma/theta nuance).

    A spread rolls as a unit: the anchor long put's target sets the
    structure's new geometry, every leg moves by the same ratio so a 5%-wide
    spread stays 5% wide, and ``roll_up_cost`` nets all of them (#333).

    Legs that get no recommendation — short legs, non-puts, expired legs —
    are still **returned**, with ``action=None`` and an ``excluded_reason``.
    Before #333 they were silently dropped, so ``/design``'s roll plan
    showed only long puts with nothing saying the rest had been considered.

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
        One :class:`RollPlanRecord` per position in
        ``portfolio.positions`` order — never a subset. Empty only for an
        empty book.

    """
    status_records = evaluate_roll_status(portfolio, ips_config)
    by_position = {r.position.position_id: r for r in status_records}
    structures = group_into_structures(portfolio.positions)
    spot = portfolio.spot_price
    ips_convexity = ips_config.convexity
    ips_triggers = ips_config.triggers

    plans: dict[str, RollPlanRecord] = {}
    for structure in structures:
        plans.update(
            _plan_structure(
                structure,
                by_position=by_position,
                portfolio=portfolio,
                spot=spot,
                ips_convexity=ips_convexity,
                ips_triggers=ips_triggers,
                target_basis=target_basis,
                target_delta=target_delta,
            ),
        )

    # Portfolio order, not structure order: the plan is read beside the roll
    # status table, which is in portfolio order.
    return [
        plans[position.position_id]
        for position in portfolio.positions
        if position.position_id in plans
    ]


def _excluded(
    record: RollStatusRecord,
    structure: RollStructure,
    reason: str,
) -> RollPlanRecord:
    """Build a record for a leg this planner declines to recommend on.

    ``meets_convexity_target`` is still read off the record rather than
    hardcoded ``False`` (#408). It is a **book**-level fact, like the
    ``convexity_now_pct`` beside it — a leg getting no roll recommendation
    does not make the book's convexity target unmet, and a field saying
    otherwise is a wrong number waiting for its first reader.
    """
    return RollPlanRecord(
        position=record.position,
        verdict=record.verdict,
        action=None,
        excluded_reason=reason,
        structure_id=structure.structure_id,
        target_basis="",
        target_strike=None,
        roll_up_cost=None,
        convexity_now_pct=record.crash_convexity_pct,
        meets_convexity_target=record.convexity_target_met,
        gamma=record.position.option.gamma() * record.position.contract_size,
        theta=record.position.option.theta() * record.position.contract_size,
        rationale=reason,
    )


def _exclusion_reason(
    position: OptionPosition,
    record: RollStatusRecord,
    structure: RollStructure,
) -> str | None:
    """Why *position* gets no recommendation, or ``None`` if it does.

    Ordered most-specific first: an expired short call is reported as
    expired, not as a short leg, because expiry is the fact that actually
    settles what to do with it.
    """
    if record.verdict is RollVerdict.EXPIRED:
        return expired_reason(position, record.days_to_maturity)
    if position.option.option_type != OptionType.PUT:
        return (
            "not a protective put — rolls with its structure"
            if structure.is_spread
            else "not a protective put; no roll recommendation"
        )
    if position.quantity <= 0:
        return (
            "short leg — rolls with its structure, priced in the "
            "structure's netted cost"
            if structure.is_spread
            else "short put — no standalone roll recommendation (#333)"
        )
    return None


def _decide_action(
    record: RollStatusRecord,
    *,
    ips_triggers: IpsTriggers,
    ips_convexity: IpsConvexity,
) -> tuple[RollAction, str]:
    """Map one leg's roll verdict to an action, and say why.

    The whole of #408's decision, in one place: a fired trigger becomes a
    roll unless something says otherwise, and there are exactly two things
    that can — :func:`rally_review_cleared` (the Rule 2 REVIEW band's own
    condition came back false, so no roll is warranted) and
    :func:`gamma_theta_delay` (the roll is warranted but deferred).

    CHECKED is tested before DELAY only for readability — a trigger's own
    condition is resolved before the gamma/theta nuance is applied to it.
    The two are mutually exclusive by construction: a rally moves a put
    *further* OTM, so a rally REVIEW always has ``drift_pct > 0`` and can
    never satisfy ``gamma_theta_delay``'s nearer-the-money condition. A
    test pins that rather than leaving it resting on this ordering.

    Args:
        record: One leg's roll status.
        ips_triggers: IPS trigger policy (the roll window).
        ips_convexity: IPS convexity policy (the target band).

    Returns:
        The action and its rationale. Every rationale states its grounds:
        a recommendation to *not* act on a live trigger reads as the tool
        losing the signal unless it arrives with its justification.

    """
    months_to_maturity = record.days_to_maturity / const.CALENDAR_DAYS_PER_MONTH
    convexity_now_pct = record.crash_convexity_pct

    if record.verdict not in (RollVerdict.ROLL, RollVerdict.REVIEW):
        return RollAction.HOLD, "No trigger active; holding."
    if rally_review_cleared(record):
        return RollAction.CHECKED, _checked_rationale(record)
    if gamma_theta_delay(
        months_to_maturity=months_to_maturity,
        convexity_now_pct=convexity_now_pct,
        drift_pct=record.moneyness.drift_pct,
        ips_triggers=ips_triggers,
        ips_convexity=ips_convexity,
    ):
        return RollAction.DELAY, _delay_rationale(
            record,
            months_to_maturity=months_to_maturity,
            convexity_now_pct=convexity_now_pct,
            ips_triggers=ips_triggers,
            ips_convexity=ips_convexity,
        )
    return RollAction.ROLL_NOW, _roll_now_rationale(record)


def _plan_structure(  # pylint: disable=too-many-arguments,too-many-locals  # one structure's full roll context; every argument is a distinct input
    structure: RollStructure,
    *,
    by_position: dict[str, RollStatusRecord],
    portfolio: OptionPortfolio,
    spot: float,
    ips_convexity: IpsConvexity,
    ips_triggers: IpsTriggers,
    target_basis: Literal["entry_otm", "delta"],
    target_delta: float | None,
) -> dict[str, RollPlanRecord]:
    """Plan one structure, returning a record for every one of its legs."""
    out: dict[str, RollPlanRecord] = {}
    anchor = structure.anchor
    anchor_record = (
        by_position.get(anchor.position_id) if anchor is not None else None
    )

    # ── Anchor target strike ─────────────────────────────────────────────
    anchor_target: float | None = None
    if anchor is not None and anchor_record is not None:
        if target_basis == "entry_otm":
            if anchor_record.moneyness.entry_otm_pct is not None:
                anchor_target = new_strike_for_entry_otm(
                    anchor.option.option_type,
                    spot,
                    anchor_record.moneyness.entry_otm_pct,
                )
        elif target_basis == "delta" and target_delta is not None:
            anchor_target = strike_for_delta(
                portfolio,
                target_delta=target_delta,
                maturity_years=(
                    anchor_record.days_to_maturity / const.DAYS_PER_YEAR
                ),
            )

    # ── Netted cost across every leg ─────────────────────────────────────
    roll_up_cost: float | None = None
    if anchor_target is not None:
        roll_up_cost = net_structure_roll_cost(
            structure,
            structure_target_strikes(structure, anchor_target),
        )

    for leg in structure.legs:
        record = by_position.get(leg.position_id)
        if record is None:  # pragma: no cover - every leg has a record
            continue
        reason = _exclusion_reason(leg, record, structure)
        if reason is not None or anchor is None or anchor_record is None:
            out[leg.position_id] = _excluded(
                record,
                structure,
                reason or "no long put in this structure to roll around",
            )
            continue

        convexity_now_pct = record.crash_convexity_pct
        # Read off the record, not recomputed (#408): the roll-status
        # table's convexity trigger, the rally REVIEW band's condition and
        # this plan now grade on one boolean, so they cannot disagree about
        # whether the target is met for a book they are both describing.
        meets_convexity_target = record.convexity_target_met
        action, rationale = _decide_action(
            record,
            ips_triggers=ips_triggers,
            ips_convexity=ips_convexity,
        )
        if structure.is_spread:
            rationale = (
                f"{rationale} Rolls as one structure with "
                f"{len(structure.legs) - 1} other leg(s); cost is netted."
            )

        out[leg.position_id] = RollPlanRecord(
            position=leg,
            verdict=record.verdict,
            action=action,
            excluded_reason=None,
            structure_id=structure.structure_id,
            target_basis=target_basis,
            target_strike=anchor_target,
            roll_up_cost=roll_up_cost,
            convexity_now_pct=convexity_now_pct,
            meets_convexity_target=meets_convexity_target,
            gamma=leg.option.gamma() * leg.contract_size,
            theta=leg.option.theta() * leg.contract_size,
            rationale=rationale,
        )

    return out
