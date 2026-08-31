"""Per-tranche roll status evaluation driven by ips.yaml thresholds.

Combines existing health metrics (crash convexity) with new entry-tracking
data (``OptionPosition.entry_spot``/``entry_date``) to produce a
HOLD/MONITOR/REVIEW/ROLL verdict for every position in a portfolio, or
``EXPIRED`` for a leg that is already gone (#373).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from deltadewa import constants as const
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_hedge_value,
    hedge_value,
    is_expired,
)
from deltadewa.clock import days_between
from deltadewa.constants import OptionType
from deltadewa.valuation import OptionValuation

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsConfig, IpsTriggers
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition


class RollVerdict(StrEnum):
    """Per-tranche roll recommendation.

    ``HOLD < MONITOR < REVIEW < ROLL`` is the urgency scale, and
    :data:`_SEVERITY` is the only place it is written down.

    ``EXPIRED`` (#373) is deliberately **not on that scale**. It is a
    lifecycle fact, not a policy grade -- the same disposition
    :class:`~deltadewa.analysis.position_aging.ExpiryBucketLabel` gives its
    own ``EXPIRED`` member, and read off the same boundary
    (:func:`~deltadewa.analysis.crash_repricing.is_expired`) rather than an
    IPS threshold. An expired leg is not urgent, it is gone: ranking it
    above ``ROLL`` would let it dominate a headline over a real roll, and
    below ``HOLD`` would read as "fine". So it gets no severity at all and
    every reduction over verdicts iterates :data:`GRADABLE_VERDICTS`.
    """

    HOLD = "HOLD"
    MONITOR = "MONITOR"
    REVIEW = "REVIEW"
    ROLL = "ROLL"
    EXPIRED = "EXPIRED"


_SEVERITY: dict[RollVerdict, int] = {
    RollVerdict.HOLD: 0,
    RollVerdict.MONITOR: 1,
    RollVerdict.REVIEW: 2,
    RollVerdict.ROLL: 3,
}

GRADABLE_VERDICTS: Final[frozenset[RollVerdict]] = frozenset(_SEVERITY)
"""The verdicts that sit on the urgency scale -- everything but ``EXPIRED``.

Callers reducing many records to one (the digest's worst-verdict line, a
panel headline) must filter on this rather than assuming every member of
:class:`RollVerdict` has a severity.
"""

_EXPIRED_TRIGGER_REASON: Final[str] = "not evaluated - leg expired"
"""Stand-in reason for an expired leg's three (un-run) roll triggers.

An expired leg short-circuits before any trigger is evaluated, so the
per-trigger cells have nothing real to report. Saying so beats rendering
three readings computed from a negative day count.
"""


@dataclass(frozen=True)
class MoneynessDrift:
    """%OTM at entry vs now, and the drift between them.

    %OTM is signed so positive always means "out of the money": for a
    CALL, ``(strike - spot) / spot * 100``; for a PUT,
    ``(spot - strike) / spot * 100``.
    """

    entry_otm_pct: float | None
    current_otm_pct: float
    drift_pct: float | None


@dataclass(frozen=True)
class TriggerReason:
    """One roll trigger's verdict and the plain-language reason for it."""

    verdict: RollVerdict
    reason: str


@dataclass(frozen=True)
class RollStatusRecord:
    """One row of the roll status table — one option tranche.

    Two convexity numbers, deliberately (#306). ``crash_convexity_pct`` is
    the **book's** crash convexity, which is what
    ``convexity_target_min_pct``/``_max_pct`` band and what
    ``convexity_trigger`` grades — the IPS target is stated against the whole
    book, so the gate cannot be applied per leg. Before #306 that book figure
    was the only one here, repeated down a per-tranche column as though each
    tranche had been tested on its own.

    ``leg_convexity_contribution_pct`` is **this leg's share** of it, in the
    same units (percentage points of the protected book), computed on the same
    :class:`~deltadewa.analysis.crash_repricing.CrashShock`. Contributions are
    exactly additive: they sum to ``crash_convexity_pct``, because both terms
    of the ratio are sums over legs and the denominator is constant. That is
    the number that answers *which* tranche to roll, which the book figure
    never could.

    It is ``None`` — not ``0.0`` — for an expired leg, which
    :func:`~deltadewa.analysis.crash_repricing.crash_hedge_value` excludes
    from pricing entirely (#362). Zero would read as "this leg is worthless";
    ``None`` reads as "this leg was not priced", which is what happened.
    """

    position: OptionPosition
    moneyness: MoneynessDrift
    days_to_maturity: int
    roll_window_days: int
    crash_convexity_pct: float
    leg_convexity_contribution_pct: float | None
    convexity_target_min_pct: float
    convexity_target_max_pct: float
    verdict: RollVerdict
    estimated_roll_up_cost: float | None
    time_trigger: TriggerReason
    convexity_trigger: TriggerReason
    rally_trigger: TriggerReason


def _otm_pct(option_type: OptionType, spot: float, strike: float) -> float:
    if option_type == OptionType.CALL:
        return (strike - spot) / spot * 100
    return (spot - strike) / spot * 100


def compute_moneyness_drift(
    position: OptionPosition,
    current_spot: float,
) -> MoneynessDrift:
    """Compute %OTM at entry vs now for *position*.

    Returns ``entry_otm_pct=None`` and ``drift_pct=None`` when the position
    has no recorded ``entry_spot`` (e.g. imported from a file predating
    entry tracking).
    """
    current_otm_pct = _otm_pct(
        position.option.option_type,
        current_spot,
        position.option.strike_price,
    )

    if position.entry_spot is None:
        return MoneynessDrift(
            entry_otm_pct=None,
            current_otm_pct=current_otm_pct,
            drift_pct=None,
        )

    entry_otm_pct = _otm_pct(
        position.option.option_type,
        position.entry_spot,
        position.option.strike_price,
    )
    return MoneynessDrift(
        entry_otm_pct=entry_otm_pct,
        current_otm_pct=current_otm_pct,
        drift_pct=current_otm_pct - entry_otm_pct,
    )


def estimate_roll_up_cost(
    position: OptionPosition,
    new_strike: float,
    vol: float,
) -> float:
    """Estimate the cash cost of rolling *position* to *new_strike*.

    Prices a same-maturity option at *new_strike* using *vol* and the
    position's current spot/rate/dividend/valuation date (i.e.
    ``position.option``'s current market snapshot), and returns
    ``(new_price - current_price) * quantity * contract_size``. Positive
    means the roll costs money; negative means it's a credit.
    """
    new_option = OptionValuation(
        spot_price=position.option.spot_price,
        strike_price=new_strike,
        maturity_date=position.option.maturity_date,
        volatility=vol,
        risk_free_rate=position.option.risk_free_rate,
        dividend_yield=position.option.dividend_yield,
        option_type=position.option.option_type,
        valuation_date=position.option.valuation_date,
        exercise_style=position.exercise_style,
    )
    multiplier = position.quantity * position.contract_size
    return (new_option.price() - position.option.price()) * multiplier


def _time_trigger_verdict(
    days_to_maturity: int,
    roll_window_days: float,
    review_buffer: float,
) -> TriggerReason:
    reason = (
        f"{days_to_maturity}d to maturity, {roll_window_days:.0f}d roll window"
    )
    if days_to_maturity <= roll_window_days:
        return TriggerReason(RollVerdict.ROLL, reason=reason)
    if days_to_maturity <= roll_window_days * review_buffer:
        return TriggerReason(RollVerdict.REVIEW, reason=reason)
    return TriggerReason(RollVerdict.HOLD, reason=reason)


def _convexity_trigger_verdict(
    crash_convexity_pct: float,
    target_min_pct: float,
    target_max_pct: float,
) -> TriggerReason:
    reason = (
        f"{crash_convexity_pct:.1f}% convexity vs "
        f"{target_min_pct:.0f}-{target_max_pct:.0f}% band"
    )
    if crash_convexity_pct < target_min_pct:
        return TriggerReason(RollVerdict.ROLL, reason=reason)
    if crash_convexity_pct > target_max_pct:
        return TriggerReason(RollVerdict.MONITOR, reason=reason)
    return TriggerReason(RollVerdict.HOLD, reason=reason)


def rally_from_entry_pct(
    position: OptionPosition,
    current_spot: float,
) -> float | None:
    """Percent the underlying has rallied since *position* was entered.

    ``(current_spot - entry_spot) / entry_spot * 100``, signed, so a
    selloff reads negative. This is the reading the handbook's `Rule 2 —
    Market Rally Rebalance Trigger
    <https://qwertytam.github.io/deltadewa-handbook/0.1/part-7/rolling-rules/#rule-2-market-rally-rebalance-trigger>`_
    bands, and it is measured from **the hedge's entry spot** — each
    tranche has its own, which is why this is a per-tranche reading and
    not a book-level one.

    Distinct from :class:`MoneynessDrift`'s ``drift_pct``, an entry-vs-now
    %OTM reading still carried on every record for display. The two are
    deterministically related for a given leg but on very different
    scales: a rally ``r`` on a put entered ``m``% OTM moves its moneyness
    by only ``(1 - m/100) * r/(1+r)`` percentage points, so the handbook's
    most severe rally band (>+20%) produces about 14 pp of drift on a
    16%-OTM put. A former strike-drift trigger banded ``drift_pct``
    directly against a flat 40 pp threshold — a handbook rule that no
    longer exists, and one this scale relationship meant could not fire in
    the direction that mattered; retired in #384, superseded by this
    rally-from-entry reading.

    Args:
        position: The tranche to measure.
        current_spot: Spot to measure against.

    Returns:
        Percent rally since entry, or ``None`` when the position has no
        recorded ``entry_spot`` — the reading is then unavailable, which is
        not the same as zero.

    """
    entry_spot = position.entry_spot
    if entry_spot is None or entry_spot == 0:
        return None
    return (current_spot - entry_spot) / entry_spot * 100.0


def _rally_trigger_verdict(
    rally_pct: float | None,
    triggers: IpsTriggers,
) -> TriggerReason:
    """Band a rally-since-entry reading against the handbook's four bands.

    Five regions onto four gradable verdicts: the handbook's ACTION and
    URGENT bands both map to ``ROLL``, because ``RollVerdict`` has four
    rungs and inventing a fifth would imply an urgency the rest of the
    package has no vocabulary for. The distinction is not lost — the band's
    own name and recommended action are carried in the reason, which is
    this package's standing convention for never letting a verdict arrive
    as a bare word.
    """
    if rally_pct is None:
        return TriggerReason(
            RollVerdict.HOLD,
            reason="no entry spot recorded",
        )

    reading = f"{rally_pct:+.1f}% rally since entry"
    if rally_pct >= triggers.rally_urgent_pct:
        return TriggerReason(
            RollVerdict.ROLL,
            reason=(
                f"{reading} — URGENT band (>{triggers.rally_urgent_pct:.0f}%):"
                " original strikes may provide negligible protection; close"
                " and re-establish"
            ),
        )
    if rally_pct >= triggers.rally_action_pct:
        return TriggerReason(
            RollVerdict.ROLL,
            reason=(
                f"{reading} — ACTION band ({triggers.rally_action_pct:.0f}-"
                f"{triggers.rally_urgent_pct:.0f}%): strikes likely too deep"
                " OTM; roll the ladder closer to spot"
            ),
        )
    if rally_pct >= triggers.rally_review_pct:
        return TriggerReason(
            RollVerdict.REVIEW,
            reason=(
                f"{reading} — REVIEW band ({triggers.rally_review_pct:.0f}-"
                f"{triggers.rally_action_pct:.0f}%): roll strikes up if the"
                " convexity target is no longer met"
            ),
        )
    if rally_pct >= triggers.rally_monitor_pct:
        return TriggerReason(
            RollVerdict.MONITOR,
            reason=(
                f"{reading} — MONITOR band ({triggers.rally_monitor_pct:.0f}-"
                f"{triggers.rally_review_pct:.0f}%): recompute crash convexity"
                " at current spot"
            ),
        )
    return TriggerReason(
        RollVerdict.HOLD,
        reason=(
            f"{reading} — below the {triggers.rally_monitor_pct:.0f}% monitor"
            " band"
        ),
    )


def new_strike_for_entry_otm(
    option_type: OptionType,
    current_spot: float,
    entry_otm_pct: float,
) -> float:
    """Return the strike that restores entry OTM% at *current_spot*.

    Args:
        option_type: PUT or CALL.
        current_spot: Current underlying spot price.
        entry_otm_pct: Percent OTM recorded at position entry (positive).

    Returns:
        Strike price that places the option at *entry_otm_pct* OTM from
        *current_spot*.

    """
    if option_type == OptionType.CALL:
        return current_spot * (1 + entry_otm_pct / 100)
    return current_spot * (1 - entry_otm_pct / 100)


def leg_convexity_contribution_pct(
    portfolio: OptionPortfolio,
    position: OptionPosition,
    *,
    shock: CrashShock,
) -> float | None:
    """Return one leg's share of the book's crash convexity, same units.

    ``(V_crash(leg) - V_today(leg)) / P_today * 100`` against the same
    protected book ``P_today`` that
    :func:`~deltadewa.analysis.crash_repricing.crash_convexity_pct` divides
    by, so contributions across every leg sum **exactly** to the book figure
    — both terms of the ratio are sums over legs and the denominator does not
    depend on which legs are selected. Short legs need no special handling:
    ``position_value`` already carries the quantity sign.

    Do not compare the result against the IPS convexity band. The band is
    stated against the whole book; a leg's contribution is a fraction of it,
    so grading one against the other would fail every row (#306).

    Args:
        portfolio: The book the leg belongs to — supplies the protected-book
            denominator and the market state the leg is repriced in.
        position: The single leg to value.
        shock: The crash basis, built once by the caller with
            :meth:`CrashShock.from_ips` so every leg and the book figure share
            one crash state.

    Returns:
        The leg's contribution in percentage points of the protected book, or
        ``None`` when the book has no underlying (the ratio is undefined) or
        the leg is expired and therefore never priced (#362) — ``None`` rather
        than ``0.0``, which would read as a worthless leg rather than an
        unpriced one.

    """
    book = abs(portfolio.underlying_quantity * portfolio.spot_price)
    if book == 0:
        return None
    if is_expired(position, valuation_date=portfolio.valuation_date):
        return None
    legs = [position]
    v_today = hedge_value(portfolio, positions=legs)
    v_crash = crash_hedge_value(portfolio, shock=shock, positions=legs)
    return (v_crash - v_today) / book * 100.0


def expired_reason(position: OptionPosition, days_to_maturity: int) -> str:
    """Plain-language reason text for an expired leg (#373).

    Says it in words rather than leaving a negative day count as the only
    signal. Matches the wording
    :func:`~deltadewa.analysis.crash_repricing.describe_expired_legs` uses for
    #375's convexity caveat, so one leg reads identically wherever it is
    named.

    Args:
        position: The expired leg.
        days_to_maturity: Its (negative or zero) day count, as
            :func:`~deltadewa.clock.days_between` computed it.

    Returns:
        E.g. ``"expired 2025-06-17 (435d ago) — no roll recommendation"``.

    """
    expiry = position.option.maturity_date.date()
    return (
        f"expired {expiry} ({abs(days_to_maturity)}d ago)"
        " — no roll recommendation"
    )


def verdict_reason(record: RollStatusRecord) -> str:
    """Return the plain-language reason driving ``record.verdict``.

    Lives here rather than in ``app/`` because the digest needs it too and
    ``reporting/`` must not import from ``app/``; ``app.format`` keeps a thin
    delegating alias.

    ``EXPIRED`` is answered first — its three triggers were never evaluated,
    so matching against them would return a stand-in string. Otherwise the
    verdict is matched against the three per-trigger verdicts (time,
    convexity, rally) and that trigger's ``.reason`` is returned — the
    verdict is defined as their max, so one of them always matches; the
    fallback below is defensive only.

    Args:
        record: One position's roll status record.

    Returns:
        A one-sentence, human-readable explanation of the verdict.

    """
    if record.verdict is RollVerdict.EXPIRED:
        return expired_reason(record.position, record.days_to_maturity)

    for trigger in (
        record.time_trigger,
        record.convexity_trigger,
        record.rally_trigger,
    ):
        if trigger.verdict == record.verdict:
            return trigger.reason

    return f"Held at {record.verdict.value}."  # pragma: no cover - defensive


def evaluate_roll_status(  # pylint: disable=too-many-locals  # four triggers, their verdicts, and the crash basis they share
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    current_spot: float | None = None,
) -> list[RollStatusRecord]:
    """Evaluate roll status for every position in *portfolio*.

    Args:
        portfolio: Live OptionPortfolio to evaluate.
        ips_config: Hedge program policy (see deltadewa.ips_config).
        current_spot: Spot price to evaluate against. Defaults to
            portfolio.spot_price.

    Returns:
        One RollStatusRecord per position, in portfolio.positions order.
        An already-expired leg gets a record graded ``EXPIRED`` with its
        three triggers un-run and no roll-up cost (#373) — it is reported,
        never dropped, and never graded on the urgency scale.

    """
    if current_spot is None:
        current_spot = portfolio.spot_price

    triggers = ips_config.triggers
    convexity = ips_config.convexity
    roll_window_days = (
        triggers.roll_at_months_remaining * const.CALENDAR_DAYS_PER_MONTH
    )

    analyzer = PortfolioAnalyzer(portfolio)
    # Source the whole crash basis from the IPS so the roll trigger's convexity
    # matches the health gauge / scenario table exactly; passing spot-only
    # (vol_shock=0) understated convexity and biased the roll toward firing.
    # The band below is read straight off `convexity` — pricing and policy
    # travel separately by design.
    #
    # Built once and reused for every leg's contribution below, so the book
    # figure and its per-leg decomposition can only ever be on one crash
    # state — the property that makes the contributions sum back to it (#306).
    shock = CrashShock.from_ips(convexity)
    crash_convexity_pct = analyzer.calculate_crash_convexity_pct(shock)

    # Measure DTE against the portfolio's (what-if) valuation date, not the
    # wall clock, so moving the valuation date moves every roll verdict.
    as_of = portfolio.valuation_date
    records: list[RollStatusRecord] = []

    for position in portfolio.positions:
        days_to_maturity = days_between(as_of, position.option.maturity_date)
        moneyness = compute_moneyness_drift(position, current_spot)

        # An expired leg short-circuits before any trigger runs (#373). Its
        # day count is a large negative, which trivially satisfies the roll
        # window and used to grade it ROLL — the most urgent possible verdict
        # on a position that is simply gone. Moneyness is still computed: it
        # is a fact about the strike, and the table's entry/now OTM columns
        # stay populated.
        if is_expired(position, valuation_date=as_of):
            expired_trigger = TriggerReason(
                RollVerdict.EXPIRED,
                reason=_EXPIRED_TRIGGER_REASON,
            )
            records.append(
                RollStatusRecord(
                    position=position,
                    moneyness=moneyness,
                    days_to_maturity=days_to_maturity,
                    roll_window_days=int(roll_window_days),
                    crash_convexity_pct=crash_convexity_pct,
                    leg_convexity_contribution_pct=None,
                    convexity_target_min_pct=convexity.target_min_pct,
                    convexity_target_max_pct=convexity.target_max_pct,
                    verdict=RollVerdict.EXPIRED,
                    estimated_roll_up_cost=None,
                    time_trigger=expired_trigger,
                    convexity_trigger=expired_trigger,
                    rally_trigger=expired_trigger,
                ),
            )
            continue

        time_trigger = _time_trigger_verdict(
            days_to_maturity,
            roll_window_days,
            triggers.roll_review_buffer,
        )
        convexity_trigger = _convexity_trigger_verdict(
            crash_convexity_pct,
            convexity.target_min_pct,
            convexity.target_max_pct,
        )
        rally_trigger = _rally_trigger_verdict(
            rally_from_entry_pct(position, current_spot),
            triggers,
        )
        time_verdict = time_trigger.verdict
        convexity_verdict = convexity_trigger.verdict

        verdict = max(
            (
                time_verdict,
                convexity_verdict,
                rally_trigger.verdict,
            ),
            key=lambda v: _SEVERITY[v],
        )

        estimated_roll_up_cost = None
        if (
            verdict in (RollVerdict.REVIEW, RollVerdict.ROLL)
            and moneyness.entry_otm_pct is not None
        ):
            new_strike = new_strike_for_entry_otm(
                position.option.option_type,
                current_spot,
                moneyness.entry_otm_pct,
            )
            estimated_roll_up_cost = estimate_roll_up_cost(
                position,
                new_strike,
                position.option.volatility,
            )

        records.append(
            RollStatusRecord(
                position=position,
                moneyness=moneyness,
                days_to_maturity=days_to_maturity,
                roll_window_days=int(roll_window_days),
                crash_convexity_pct=crash_convexity_pct,
                leg_convexity_contribution_pct=(
                    leg_convexity_contribution_pct(
                        portfolio,
                        position,
                        shock=shock,
                    )
                ),
                convexity_target_min_pct=convexity.target_min_pct,
                convexity_target_max_pct=convexity.target_max_pct,
                verdict=verdict,
                estimated_roll_up_cost=estimated_roll_up_cost,
                time_trigger=time_trigger,
                convexity_trigger=convexity_trigger,
                rally_trigger=rally_trigger,
            ),
        )

    return records
