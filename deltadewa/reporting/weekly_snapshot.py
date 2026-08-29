"""Weekly comparison baseline for the M2.6 digest — persisted, diffable.

A tail hedge moves slowly: 52 near-identical program reports would train an
operator to stop reading them. ``WeeklySnapshot`` is the small, JSON-
serializable subset of a ``ProgramReport`` (plus the verdicts a report
doesn't carry — decision and roll) that this week's run compares against
last week's, so the digest can lead with what changed rather than repeat
the whole report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltadewa.reporting.program_report import ProgramReport

# Mirrors program_report._STALE_OR_WORSE locally rather than importing a
# private name across modules — same convention that module itself uses to
# avoid reaching into deltadewa.marketdata.Source (which has no UNAVAILABLE
# member; a provider never returns that source itself).
_STALE_OR_WORSE: Final[frozenset[str]] = frozenset(
    {"STALE", "STATIC", "UNAVAILABLE"},
)

# Noise floors: a move smaller than these is real but not worth a line in
# a digest an operator is meant to actually read every week.
_CONVEXITY_MATERIAL_MOVE_PP: Final[float] = 0.5
_VIX_MATERIAL_MOVE_PTS: Final[float] = 3.0
_CARRY_MATERIAL_MOVE_REL: Final[float] = 0.05
_SKEW_MATERIAL_MOVE_FRACTION: Final[float] = 0.10


@dataclass(frozen=True)
class WeeklySnapshot:
    """One week's comparison baseline.

    Attributes:
        as_of: The report date this snapshot was taken for.
        first_as_of: The ``as_of`` of the very first snapshot ever taken —
            carried forward unchanged on every subsequent run. The origin
            date for "since inception" framing.
        data_quality: ``MarketContextSection.data_quality`` — already the
            worst ``Source`` across every live market-data observation
            used (``Observation.combine`` inside
            ``assess_market_environment``); nothing else in this assembly
            carries a ``Source`` to combine.
        carry_pct_of_notional: ``CostSection.carry_pct_of_notional``.
        within_budget: ``CostSection.within_budget``.
        convexity_pct: ``ProtectionSection.convexity_pct``.
        payoff_vs_premium: ``ProtectionSection.payoff_vs_premium``. Renamed
            from ``payoff_ratio`` (4.2, #303) — see
            ``analysis.crash_payoff``'s module docstring for why. The
            on-disk JSON key stays ``"payoff_ratio"`` (see
            :meth:`to_json_dict`) so already-persisted snapshot history
            keeps loading.
        meets_target: ``ProtectionSection.meets_target``.
        vix: ``MarketContextSection.vix``.
        skew_percentile: ``MarketContextSection.skew_percentile`` (0-1
            fraction).
        regime_label: ``MarketContextSection.regime_label``.
        hedge_cost_verdict: ``MarketContextSection.hedge_cost_verdict``.
        decision_verdict: ``DecisionResult.verdict`` — not part of
            ``ProgramReport``, computed separately by the caller.
        worst_roll_verdict: The worst ``RollVerdict`` across every
            position's ``RollStatusRecord`` (HOLD < MONITOR < REVIEW <
            ROLL), or ``"N/A"`` when the book holds no *gradable* leg —
            no positions at all, or every one already expired (#373).
            The **only** roll field that is diffed week over week.
        worst_roll_leg: Which leg earned ``worst_roll_verdict``, e.g.
            ``"PUT 4200"`` — ``None`` when there is none (#374).
        worst_roll_reason: That leg's plain-language trigger reason.
            ``None`` when there is no worst leg (#374).

            Both are carried for *rendering* and deliberately **not**
            diffed. ``worst_roll_reason`` embeds a live day count, so
            diffing it would fire a threshold crossing every single week as
            the clock ticks — a phantom change on a book that had not
            moved. The verdict word is the thing that genuinely crosses;
            these two explain it.
        expired_leg_count: How many legs are already past maturity
            (#373). Diffed as a **crossing**, not a material move: an
            expired leg is excluded from ``worst_roll_verdict``, so
            without this a book whose only live leg expires would report
            ``ROLL -> N/A`` and read as though the problem resolved
            itself. The two lines together tell the truth.
        ips_compliance_all_pass: ``IpsComplianceSection.all_pass``.
        ips_compliance_rows: ``(metric, passes)`` per compliance row, in
            report order.
        premium_paid_point_in_time: ``ProtectionSection.premium_paid`` —
            the *current* book's cost basis, a stock, not a flow. Shown for
            context only; never summed across snapshots (a roll would show
            as a jump, not an accumulation — see ``cumulative_carry_cost``
            for the genuine flow this digest tracks instead).
        cumulative_carry_cost: Running dollar total of carry (theta) cost
            consumed since ``first_as_of`` — a genuine flow, integrated
            week over week from ``CostSection.total_theta_annual``.

    """

    as_of: date
    first_as_of: date
    data_quality: str
    carry_pct_of_notional: float
    within_budget: bool
    convexity_pct: float | None
    payoff_vs_premium: float | None
    meets_target: bool | None
    vix: float | None
    skew_percentile: float | None
    regime_label: str | None
    hedge_cost_verdict: str | None
    decision_verdict: str
    worst_roll_verdict: str
    worst_roll_leg: str | None
    worst_roll_reason: str | None
    expired_leg_count: int
    ips_compliance_all_pass: bool
    ips_compliance_rows: tuple[tuple[str, bool], ...]
    premium_paid_point_in_time: float
    cumulative_carry_cost: float

    def to_json_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict (dates as ISO strings).

        The ``"payoff_ratio"`` key is a deliberate exception to
        field-name-equals-json-key: the Python field was renamed to
        ``payoff_vs_premium`` in 4.2 (#303), but the on-disk key stays
        ``"payoff_ratio"`` so a snapshot history file persisted before
        this rename keeps loading via :meth:`from_json_dict` without a
        migration step.
        """
        return {
            "as_of": self.as_of.isoformat(),
            "first_as_of": self.first_as_of.isoformat(),
            "data_quality": self.data_quality,
            "carry_pct_of_notional": self.carry_pct_of_notional,
            "within_budget": self.within_budget,
            "convexity_pct": self.convexity_pct,
            "payoff_ratio": self.payoff_vs_premium,
            "meets_target": self.meets_target,
            "vix": self.vix,
            "skew_percentile": self.skew_percentile,
            "regime_label": self.regime_label,
            "hedge_cost_verdict": self.hedge_cost_verdict,
            "decision_verdict": self.decision_verdict,
            "worst_roll_verdict": self.worst_roll_verdict,
            "worst_roll_leg": self.worst_roll_leg,
            "worst_roll_reason": self.worst_roll_reason,
            "expired_leg_count": self.expired_leg_count,
            "ips_compliance_all_pass": self.ips_compliance_all_pass,
            "ips_compliance_rows": [
                list(row) for row in self.ips_compliance_rows
            ],
            "premium_paid_point_in_time": self.premium_paid_point_in_time,
            "cumulative_carry_cost": self.cumulative_carry_cost,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> WeeklySnapshot:
        """Deserialize from ``to_json_dict``'s output."""
        return cls(
            as_of=date.fromisoformat(data["as_of"]),
            first_as_of=date.fromisoformat(data["first_as_of"]),
            data_quality=data["data_quality"],
            carry_pct_of_notional=data["carry_pct_of_notional"],
            within_budget=data["within_budget"],
            convexity_pct=data["convexity_pct"],
            payoff_vs_premium=data["payoff_ratio"],
            meets_target=data["meets_target"],
            vix=data["vix"],
            skew_percentile=data["skew_percentile"],
            regime_label=data["regime_label"],
            hedge_cost_verdict=data["hedge_cost_verdict"],
            decision_verdict=data["decision_verdict"],
            worst_roll_verdict=data["worst_roll_verdict"],
            # .get(): #374/#373 added these three after snapshots were
            # already being persisted, and a history file is read back for
            # standing-breach detection weeks later. Same discipline as the
            # "payoff_ratio" key above — an older file must keep loading.
            worst_roll_leg=data.get("worst_roll_leg"),
            worst_roll_reason=data.get("worst_roll_reason"),
            expired_leg_count=data.get("expired_leg_count", 0),
            ips_compliance_all_pass=data["ips_compliance_all_pass"],
            ips_compliance_rows=tuple(
                (row[0], row[1]) for row in data["ips_compliance_rows"]
            ),
            premium_paid_point_in_time=data["premium_paid_point_in_time"],
            cumulative_carry_cost=data["cumulative_carry_cost"],
        )


def snapshot_from_report(
    report: ProgramReport,
    *,
    decision_verdict: str,
    worst_roll_verdict: str,
    worst_roll_leg: str | None,
    worst_roll_reason: str | None,
    expired_leg_count: int,
    first_as_of: date,
    cumulative_carry_cost: float,
) -> WeeklySnapshot:
    """Build a ``WeeklySnapshot`` from a ``ProgramReport`` plus verdicts.

    ``decision_verdict`` and ``worst_roll_verdict`` aren't part of
    ``ProgramReport`` — they come from ``decision_matrix`` and
    ``evaluate_roll_status``, computed alongside the report by the caller.

    Bool fields are coerced with ``bool(...)`` here rather than trusted
    as-is: pandas/numpy-derived values upstream (e.g. ``carry_vs_budget``'s
    ``within_budget``) can arrive as ``numpy.bool_``, which duck-types as a
    bool everywhere *except* ``json.dumps`` — where it raises. Normalizing
    at construction, not just at serialization, keeps every consumer of a
    ``WeeklySnapshot`` (comparisons, rendering, not just JSON) on native
    types.
    """
    c = report.cost
    p = report.protection
    mc = report.market_context
    ic = report.ips_compliance
    return WeeklySnapshot(
        as_of=report.header.as_of,
        first_as_of=first_as_of,
        data_quality=mc.data_quality,
        carry_pct_of_notional=c.carry_pct_of_notional,
        within_budget=bool(c.within_budget),
        convexity_pct=p.convexity_pct,
        payoff_vs_premium=p.payoff_vs_premium,
        meets_target=(
            bool(p.meets_target) if p.meets_target is not None else None
        ),
        vix=mc.vix,
        skew_percentile=mc.skew_percentile,
        regime_label=mc.regime_label,
        hedge_cost_verdict=mc.hedge_cost_verdict,
        decision_verdict=decision_verdict,
        worst_roll_verdict=worst_roll_verdict,
        worst_roll_leg=worst_roll_leg,
        worst_roll_reason=worst_roll_reason,
        expired_leg_count=expired_leg_count,
        ips_compliance_all_pass=bool(ic.all_pass),
        ips_compliance_rows=tuple(
            (row.metric, bool(row.passes)) for row in ic.rows
        ),
        premium_paid_point_in_time=p.premium_paid,
        cumulative_carry_cost=cumulative_carry_cost,
    )


@dataclass(frozen=True)
class SnapshotChange:
    """One reported change — a threshold crossing or a material move."""

    label: str
    detail: str


@dataclass(frozen=True)
class SnapshotDiff:
    """The result of comparing this week's snapshot against last week's.

    Attributes:
        is_first_run: True when there was no prior snapshot to compare
            against — the digest must say so explicitly rather than
            fabricate a delta.
        prior_as_of: The prior snapshot's ``as_of``, or ``None`` on a
            first run.
        crossings: Verdict flips, band exits, and compliance-row
            pass/fail flips — always listed, first, in the digest.
        material_moves: Numeric moves past a noise floor that didn't
            cross a threshold — listed, but not as loudly as a crossing.

    """

    is_first_run: bool
    prior_as_of: date | None
    crossings: tuple[SnapshotChange, ...]
    material_moves: tuple[SnapshotChange, ...]


def _bool_crossing(
    label: str,
    prior: bool,
    current: bool,
    *,
    true_word: str,
    false_word: str,
) -> SnapshotChange | None:
    if prior == current:
        return None
    return SnapshotChange(
        label=label,
        detail=f"{true_word if prior else false_word} "
        f"→ {true_word if current else false_word}",
    )


def _optional_bool_crossing(
    label: str,
    prior: bool | None,
    current: bool | None,
    *,
    true_word: str,
    false_word: str,
) -> SnapshotChange | None:
    if prior is None or current is None or prior == current:
        return None
    return _bool_crossing(
        label,
        prior,
        current,
        true_word=true_word,
        false_word=false_word,
    )


def _str_crossing(
    label: str,
    prior: str,
    current: str,
) -> SnapshotChange | None:
    if prior == current:
        return None
    return SnapshotChange(label=label, detail=f"{prior} → {current}")


def _material_move(
    label: str,
    prior: float | None,
    current: float | None,
    *,
    floor: float,
    unit: str = "",
) -> SnapshotChange | None:
    if prior is None or current is None:
        return None
    delta = current - prior
    if abs(delta) < floor:
        return None
    sign = "+" if delta >= 0 else ""
    return SnapshotChange(
        label=label,
        detail=f"{prior:.2f}{unit} → {current:.2f}{unit} "
        f"({sign}{delta:.2f}{unit})",
    )


def _relative_material_move(
    label: str,
    prior: float,
    current: float,
    *,
    rel_floor: float,
) -> SnapshotChange | None:
    if prior == 0:
        return None
    if abs((current - prior) / prior) < rel_floor:
        return None
    sign = "+" if current >= prior else ""
    return SnapshotChange(
        label=label,
        detail=f"{prior:.2f}% → {current:.2f}% ({sign}{current - prior:.2f}pp)",
    )


def _worst_roll_crossing(
    prior: WeeklySnapshot,
    current: WeeklySnapshot,
) -> SnapshotChange | None:
    """Build the worst-roll crossing, leg and reason attached (#374).

    Before this, a crossing rendered as a bare ``"HOLD → ROLL"`` and
    nothing anywhere in the digest's output path said *which* leg or
    *why* — the digest is the surface a non-technical partner reads, and
    per-leg detail existed only on ``/monitor``.

    Only the verdict word is compared. The attribution is appended to the
    already-decided change: ``worst_roll_reason`` carries a live day
    count, so comparing it would fire a crossing every week on a book that
    had not moved.
    """
    change = _str_crossing(
        "Worst roll verdict",
        prior.worst_roll_verdict,
        current.worst_roll_verdict,
    )
    if change is None:
        return None
    if current.worst_roll_leg is None:
        return change
    attribution = current.worst_roll_leg
    if current.worst_roll_reason:
        attribution = f"{attribution}, {current.worst_roll_reason}"
    return SnapshotChange(
        label=change.label,
        detail=f"{change.detail} ({attribution})",
    )


def _expired_leg_crossing(
    prior: WeeklySnapshot,
    current: WeeklySnapshot,
) -> SnapshotChange | None:
    """Report any change in the expired-leg count, as a crossing (#373).

    A crossing rather than a material move, and deliberately with no noise
    floor: one leg going from live to expired is exactly the event that
    makes ``worst_roll_verdict`` fall (an expired leg is excluded from
    that reduction), so it must be reported as loudly as the fall itself
    or the digest reads as though a roll trigger resolved on its own.
    """
    if prior.expired_leg_count == current.expired_leg_count:
        return None
    noun = "leg" if current.expired_leg_count == 1 else "legs"
    return SnapshotChange(
        label="Expired legs",
        detail=(
            f"{prior.expired_leg_count} → {current.expired_leg_count} "
            f"{noun} past maturity"
        ),
    )


def diff_snapshots(
    prior: WeeklySnapshot | None,
    current: WeeklySnapshot,
) -> SnapshotDiff:
    """Compare *current* against *prior*, never fabricating a delta.

    ``prior=None`` (no baseline exists yet — the first run) returns a
    ``SnapshotDiff`` with ``is_first_run=True`` and empty crossings/moves;
    the caller states that explicitly rather than inventing a comparison.
    """
    if prior is None:
        return SnapshotDiff(
            is_first_run=True,
            prior_as_of=None,
            crossings=(),
            material_moves=(),
        )

    verdict_and_band_candidates = (
        _str_crossing(
            "Decision verdict",
            prior.decision_verdict,
            current.decision_verdict,
        ),
        _worst_roll_crossing(prior, current),
        _expired_leg_crossing(prior, current),
        _optional_bool_crossing(
            "Convexity band",
            prior.meets_target,
            current.meets_target,
            true_word="in band",
            false_word="out of band",
        ),
        _bool_crossing(
            "Carry budget",
            prior.within_budget,
            current.within_budget,
            true_word="within budget",
            false_word="over budget",
        ),
        _bool_crossing(
            "IPS compliance (overall)",
            prior.ips_compliance_all_pass,
            current.ips_compliance_all_pass,
            true_word="all pass",
            false_word="a metric failing",
        ),
    )
    crossings: list[SnapshotChange] = [
        change for change in verdict_and_band_candidates if change is not None
    ]

    prior_rows = dict(prior.ips_compliance_rows)
    for metric, passes in current.ips_compliance_rows:
        prior_passes = prior_rows.get(metric)
        # A metric absent from the prior snapshot (a newly-added compliance
        # row) has nothing to compare against — not a crossing.
        if prior_passes is None or prior_passes == passes:
            continue
        crossings.append(
            SnapshotChange(
                label=f"IPS compliance: {metric}",
                detail=f"{'pass' if prior_passes else 'fail'} → "
                f"{'pass' if passes else 'fail'}",
            ),
        )

    data_quality_change = _str_crossing(
        "Data quality",
        prior.data_quality,
        current.data_quality,
    )
    if data_quality_change is not None and (
        (prior.data_quality in _STALE_OR_WORSE)
        != (current.data_quality in _STALE_OR_WORSE)
    ):
        crossings.append(data_quality_change)

    material_move_candidates = (
        _material_move(
            "Convexity",
            prior.convexity_pct,
            current.convexity_pct,
            floor=_CONVEXITY_MATERIAL_MOVE_PP,
            unit="%",
        ),
        _material_move(
            "VIX",
            prior.vix,
            current.vix,
            floor=_VIX_MATERIAL_MOVE_PTS,
        ),
        _material_move(
            "SKEW percentile",
            (
                prior.skew_percentile * 100
                if prior.skew_percentile is not None
                else None
            ),
            (
                current.skew_percentile * 100
                if current.skew_percentile is not None
                else None
            ),
            floor=_SKEW_MATERIAL_MOVE_FRACTION * 100,
            unit="%",
        ),
        _relative_material_move(
            "Carry as % of notional",
            prior.carry_pct_of_notional,
            current.carry_pct_of_notional,
            rel_floor=_CARRY_MATERIAL_MOVE_REL,
        ),
    )
    material_moves: list[SnapshotChange] = [
        move for move in material_move_candidates if move is not None
    ]

    return SnapshotDiff(
        is_first_run=False,
        prior_as_of=prior.as_of,
        crossings=tuple(crossings),
        material_moves=tuple(material_moves),
    )


@dataclass(frozen=True)
class StandingBreach:
    """A metric that has failed IPS compliance for N straight snapshots.

    Attributes:
        metric: The compliance row's ``metric`` string, matching
            ``WeeklySnapshot.ips_compliance_rows``.
        weeks: Consecutive *snapshots* failing this metric, including the
            current one — not calendar weeks, so a skipped cron week
            undercounts.
        since: ``as_of`` of the run's first failing snapshot in this
            streak — what disambiguates a skipped week from a shorter
            true run.

    """

    metric: str
    weeks: int
    since: date


def standing_breaches(
    history: Sequence[WeeklySnapshot],
    current: WeeklySnapshot,
) -> tuple[StandingBreach, ...]:
    """Consecutive-snapshot failing runs for each metric failing now.

    For every metric currently failing in ``current.ips_compliance_rows``,
    walks ``history`` backwards from its most recent entry, stopping at the
    first snapshot where that metric passes or is absent (a metric only
    tracked partway through the history). ``history`` may be given in any
    order and may include entries at or after ``current.as_of``; only
    entries strictly older than ``current.as_of`` are considered.

    Returns:
        One ``StandingBreach`` per currently-failing metric, in
        ``current.ips_compliance_rows`` order; ``()`` when ``current``
        passes.

    """
    failing_metrics = [
        metric for metric, passed in current.ips_compliance_rows if not passed
    ]
    if not failing_metrics:
        return ()

    ordered = sorted(
        (snap for snap in history if snap.as_of < current.as_of),
        key=lambda snap: snap.as_of,
        reverse=True,
    )

    breaches: list[StandingBreach] = []
    for metric in failing_metrics:
        weeks = 1
        since = current.as_of
        for snap in ordered:
            row = dict(snap.ips_compliance_rows).get(metric)
            if row is None or row:
                break
            weeks += 1
            since = snap.as_of
        breaches.append(StandingBreach(metric=metric, weeks=weeks, since=since))
    return tuple(breaches)
