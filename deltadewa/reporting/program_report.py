"""Part VII hedge program report — cost, protection, market context, compliance.

Assembles pre-computed crash, carry, and market-environment results into a
single exportable ``ProgramReport`` and renders it as plain Markdown or a
self-contained HTML document.  No repricing or recalculation is performed
here; every figure is drawn from the arguments supplied by the caller.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from enum import StrEnum
from html import escape
from typing import TYPE_CHECKING, Any, Final

from deltadewa.analysis.carry import carry_vs_budget
from deltadewa.analysis.convexity_band import (
    COULD_NOT_BE_MEASURED,
    NOT_MEASURED,
    UNMEASURED_NOT_BREACHING,
    ConvexityGrade,
    format_band_edge,
    format_depth,
    grade_convexity,
    same_crash_depth,
)
from deltadewa.analysis.crash_repricing import describe_expired_legs
from deltadewa.analysis.decision_matrix import (
    DecisionVerdict,
    decision_matrix,
    entry_timing_tree,
)
from deltadewa.analysis.market_environment import describe_skew_percentile
from deltadewa.analysis.provenance import assess_freshness
from deltadewa.analysis.realized_carry import (
    HedgedReturn,
    RealizedCarry,
    hedged_return,
    latest_period,
    since_inception,
)

if TYPE_CHECKING:
    from deltadewa.analysis.convexity_band import ConvexityGrading
    from deltadewa.analysis.crash_payoff import CrashConvexityResult
    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.analysis.monetization import MonetizationPlan
    from deltadewa.analysis.provenance import ProvenanceLedger
    from deltadewa.ips_config import IpsConfig, IpsVega
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.history import PositionHistory

# One unbroken literal, deliberately: the "Handbook links" workflow greps
# the tree for handbook URLs, and a `\` line continuation inside the URL
# made it extract `.../part-6/\` and report a 404 for a link that renders
# fine.
_RATIO_DISAMBIGUATION_URL: Final[str] = (
    "https://qwertytam.github.io/deltadewa-handbook/0.1/part-6/ratio-disambiguation/"
)

# Cites #70 ("Track hedge historical P&L"), the issue realized-gains
# tracking is actually gated on — not the stale "(C4)" label this used to
# carry, which (per docs/implementation-plan.md's current finding index)
# names an unrelated crash-spot-repricing finding.
_MONETIZATION_PLACEHOLDER: str = (
    "not tracked — realized-gains history isn't built (#70)"
)
_PENDING_NOTE: str = (
    "PENDING: start/end book values are not yet tracked; "
    "before/after-hedge returns cannot be computed."
)
# Shown instead of _PENDING_NOTE when ReturnFramingSection's weekly-carry
# fields are populated (Issue #171): the figures above answer "how much
# carry has this cost", a real and already-computed question, but not
# "what did the hedge program return" (start/end book value) — still
# genuinely untracked, so this stays an honest caveat, not a claim the
# rows above it are a return.
_WEEKLY_CARRY_NOTE: str = (
    "Before/after-hedge total return (start/end book value) is not "
    "tracked; the figures above are carry consumption only, not a return."
)

# ── Section dataclasses ───────────────────────────────────────────────────


@dataclass(frozen=True)
class ReportHeader:
    """Identification block for the report."""

    program_name: str
    instrument: str
    period_label: str
    as_of: datetime.date


@dataclass(frozen=True)
class CostSection:
    """Annual carry-cost summary and budget compliance.

    Attributes:
        total_theta_annual: Net annual theta in dollars (negative = cost).
        book_notional: Protected book notional in dollars.
        carry_pct_of_notional: ``abs(total_theta_annual) / book_notional``
            expressed as a percentage.
        budget_annual_pct: IPS carry budget in percent of notional.
        within_budget: True when carry_pct_of_notional <=
            budget_annual_pct.

    """

    total_theta_annual: float
    book_notional: float
    carry_pct_of_notional: float
    budget_annual_pct: float
    within_budget: bool


@dataclass(frozen=True)
class ProtectionSection:
    """Crash payoff and IPS convexity-band compliance.

    Every convexity figure is ``None`` when no ``IpsConvexity`` target was
    supplied to the crash analysis. They are all read off one stored
    :class:`~deltadewa.analysis.convexity_band.ConvexityGrading` (#434), so
    the reading, the band, the depth and the verdict cannot disagree: the
    grade is the referee's, and ``meets_target`` is derived from it.

    Attributes:
        payoff_vs_premium: Gross payoff / premium at the IPS crash point.
            Renamed from ``payoff_ratio`` (4.2, #303) to match the
            handbook's `Ratio Disambiguation
            <https://qwertytam.github.io/deltadewa-handbook/0.1/part-6/ratio-disambiguation/>`_
            name for this figure — "Payoff-vs-Premium Multiple" — which is
            distinct from the handbook's "Crash Payoff Ratio" (this repo's
            ``offset_ratio``).
        convexity: The referee's grading of the crash convexity at the IPS
            shock, from the matching ``CrashScenarioRow``; ``None`` when no
            IPS convexity policy was loaded. Its value is ``None`` when the
            reading could not be taken ("unmeasured, not breaching",
            #433).
        ips_crash_pct: Derived: the signed crash shock used (e.g. -25.0).
        convexity_pct: Derived: crash convexity as % of the protected book
            at the IPS shock (hedge-only; see #432 for the label).
        target_min_pct: Derived: IPS lower bound for convexity_pct.
        target_max_pct: Derived: IPS upper bound for convexity_pct.
        meets_target: Derived from the grade: True/False in band, ``None``
            when unmeasured or when no policy was loaded.
        premium_paid: Total put premium used as the payoff denominator.
        premium_basis: ``"paid"`` or ``"mark (approx)"``.
        excluded_expired_legs: One human-readable label per long-put leg
            excluded from the figures above because it was already
            expired (#375) — see
            ``analysis.crash_payoff.CrashConvexityResult.excluded_expired``
            and ``analysis.crash_repricing.describe_expired_legs``. Empty
            ``()`` when nothing was excluded — the common case, and every
            existing caller's default.

    """

    payoff_vs_premium: float | None
    convexity: ConvexityGrading | None
    premium_paid: float
    premium_basis: str
    excluded_expired_legs: tuple[str, ...] = ()

    @property
    def ips_crash_pct(self) -> float | None:
        """The IPS crash depth the convexity was graded at."""
        return None if self.convexity is None else self.convexity.shock_pct

    @property
    def convexity_pct(self) -> float | None:
        """The raw convexity reading, or ``None`` when unmeasured."""
        return None if self.convexity is None else self.convexity.value_pct

    @property
    def target_min_pct(self) -> float | None:
        """The IPS band floor, or ``None`` when no policy was loaded."""
        return None if self.convexity is None else self.convexity.min_pct

    @property
    def target_max_pct(self) -> float | None:
        """The IPS band ceiling, or ``None`` when no policy was loaded."""
        return None if self.convexity is None else self.convexity.max_pct

    @property
    def meets_target(self) -> bool | None:
        """Derived from the grade; ``None`` when unmeasured or ungraded."""
        return None if self.convexity is None else self.convexity.meets


@dataclass(frozen=True)
class MarketContextSection:
    """Regime, skew, and hedge-cost classification snapshot.

    Attributes:
        vix: Current VIX level in vol points, or ``None``.
        regime_label: ``"LOW"``, ``"NORMAL"``, or ``"HIGH"``; ``None``
            when data quality is UNAVAILABLE.
        skew_percentile: SKEW percentile rank as a 0-1 fraction, or
            ``None``.
        skew_lookback_days: The session window ``skew_percentile`` was
            ranked over (#317) — rendered beside it every time, the
            handbook's condition for quoting a percentile on any window.
            ``None`` when the environment was unavailable.
        hedge_cost_verdict: ``"CHEAP"``, ``"FAIR"``, or ``"EXPENSIVE"``;
            ``None`` when unavailable.
        data_quality: ``provenance_ledger.combined_quality.value`` —
            ``"LIVE"``, ``"CACHED"``, ``"STALE"``, ``"STATIC"``, or
            ``"UNAVAILABLE"`` (#367). Always shown verbatim wherever this
            section renders, regardless of ``needs_alarm`` below — it is
            informative context, not itself an alarm decision.
        needs_alarm: Whether this reading should trip a reader-facing
            alarm (the digest's "STALE DATA —" headline/caveat, and this
            same section's own "⚠ Data quality" caveat) —
            ``analysis.provenance.assess_freshness(provenance_ledger) is
            not None`` (#393/#398). Deliberately **not** derived from
            ``data_quality`` downstream: a hand-entered input that is
            merely ``AGING`` maps onto ``data_quality == "STALE"`` via
            ``combined_quality``'s lossy channel merge, but must not
            alarm — see ``assess_freshness``'s docstring.

    """

    vix: float | None
    regime_label: str | None
    skew_percentile: float | None
    hedge_cost_verdict: str | None
    data_quality: str
    needs_alarm: bool
    skew_lookback_days: int | None = None


class RealizedStatus(StrEnum):
    """How far the position history (#313) has got."""

    NOT_STARTED = "NOT_STARTED"
    ONE_MARK = "ONE_MARK"
    MEASURED = "MEASURED"
    UNREADABLE = "UNREADABLE"


@dataclass(frozen=True)
class RealizedCarrySection:  # pylint: disable=too-many-instance-attributes  # one field per rendered row
    """Realized carry and hedged return, from the position history (#313).

    Attributes:
        status: Whether there is anything to measure yet.
        history_start: The first mark's date. Nothing before it is known.
        opening_value: The hedge book's value at that first mark, the
            value the book held before the history enters at.
        basis: The marks' pricing basis, stated with every figure.
        inception: Realized carry from the first mark to the latest.
        inception_return: Before/after-hedge return over the same span.
        latest: Realized carry between the two most recent marks, when
            that is a shorter span than ``inception``.
        mark_note: Why this week has no new mark, when it has none.
        error: Why the history could not be read, when it could not.

    """

    status: RealizedStatus
    history_start: datetime.date | None = None
    opening_value: float | None = None
    basis: str | None = None
    inception: RealizedCarry | None = None
    inception_return: HedgedReturn | None = None
    latest: RealizedCarry | None = None
    mark_note: str | None = None
    error: str | None = None


def build_realized_carry_section(
    history: PositionHistory,
    *,
    mark_note: str | None = None,
) -> RealizedCarrySection:
    """Assemble §4's realized-carry figures from the position history.

    Pure: every number comes from
    :mod:`deltadewa.analysis.realized_carry`; this only chooses which
    spans to show. Since inception, plus the latest period when the two
    differ.

    Args:
        history: Everything recorded.
        mark_note: The weekly mark step's message when it took no mark.

    Returns:
        The section, with ``status`` saying whether anything is measured.

    """
    if not history.marks:
        return RealizedCarrySection(
            status=RealizedStatus.NOT_STARTED,
            mark_note=mark_note,
        )
    first = history.marks[0]
    inception = since_inception(history)
    latest = latest_period(history)
    return RealizedCarrySection(
        status=(
            RealizedStatus.ONE_MARK
            if inception is None
            else RealizedStatus.MEASURED
        ),
        history_start=first.mark_date,
        opening_value=first.hedge_value,
        basis=first.basis.value,
        inception=inception,
        inception_return=(
            hedged_return(inception, start=first, end=history.marks[-1])
            if inception is not None
            else None
        ),
        latest=latest if latest is not None and latest != inception else None,
        mark_note=mark_note,
    )


@dataclass(frozen=True)
class ReturnFramingSection:
    """Return-attribution framing.

    The carry drag is computed and available; before/after-hedge *return*
    (start/end book value) is not tracked and is therefore PENDING, unless
    the weekly-carry fields below are populated.

    The weekly-carry fields are ``None`` for a standalone report (Jupyter,
    an ad hoc CLI run) — there is no prior-week baseline to integrate
    over. :func:`~deltadewa.reporting.weekly_report.build_weekly_digest`
    populates them from the same
    :class:`~deltadewa.reporting.weekly_snapshot.WeeklySnapshot` figures
    its own digest lede states in prose (Issue #171: the report must not
    silently disagree with the digest it's embedded in). When populated,
    the renderers show carry consumption in place of the ``PENDING``
    before/after-hedge return rows — a real answer to a related but
    different question, not the return itself.

    Attributes:
        carry_drag_annual_pct: Annual carry cost as % of book notional
            (equal to ``CostSection.carry_pct_of_notional``).
        weekly_carry_cost: This period's carry (theta) cost in dollars,
            integrated over ``elapsed_days``. ``None`` outside the weekly
            digest.
        elapsed_days: Days ``weekly_carry_cost`` was integrated over.
            ``None`` outside the weekly digest.
        cumulative_carry_cost: Running carry cost consumed since
            ``cumulative_since``. ``None`` outside the weekly digest.
        cumulative_since: The first snapshot's date — the origin of
            ``cumulative_carry_cost``. ``None`` outside the weekly digest.
        premium_paid_point_in_time: The current book's cost basis (a
            snapshot, not summed across weeks — equal to
            ``ProtectionSection.premium_paid``). ``None`` outside the
            weekly digest.
        realized: Realized carry and before/after-hedge return from the
            position history (#313). ``None`` when the report was built
            without the history (a standalone report); the renderers then
            keep the theta-only framing above. When present it replaces
            ``PENDING``, and the theta rows are relabelled as theta so the
            two carry measures cannot be read as one.

    """

    carry_drag_annual_pct: float
    weekly_carry_cost: float | None = None
    elapsed_days: int | None = None
    cumulative_carry_cost: float | None = None
    cumulative_since: datetime.date | None = None
    premium_paid_point_in_time: float | None = None
    realized: RealizedCarrySection | None = None


@dataclass(frozen=True)
class MonetizationSection:
    """Monetization realized summary and advisory sell programme.

    Reported as a separate line item; never netted against carry cost.

    Attributes:
        realized_label: Human-readable realized-gains status.
        schedule_steps: Number of ``IpsMonetizationStep`` entries
            defined in the IPS.
        current_gain_pct: Current hedge gain as a percentage of cost
            basis, or ``None`` when basis is unavailable or no plan
            was supplied.
        recommended_cumulative_sell_pct: RECOMMENDED cumulative sell
            percentage at the current gain (advisory only — not
            realized); ``None`` when no plan was supplied.
        value_to_harvest: RECOMMENDED dollar amount to harvest now
            (advisory only — not realized); ``None`` when no plan
            was supplied.

    """

    realized_label: str
    schedule_steps: int
    current_gain_pct: float | None = None
    recommended_cumulative_sell_pct: float | None = None
    value_to_harvest: float | None = None


@dataclass(frozen=True)
class VegaSection:
    """Vega sufficiency and its IPS band (#409).

    The third standing constraint on the book's *shape*, alongside
    :class:`CostSection`'s carry budget and :class:`ProtectionSection`'s
    convexity band — and, until #409, the only one of the three that
    :func:`build_ips_compliance` never asked about. The reading was
    computed and rendered in three places (``/design``'s sizing panel,
    ``/monitor``'s efficiency sentence, ``analysis/health.py``) and graded
    for policy in none of them, so a book could sit below the floor while
    the compliance strip said PASS.

    Attributes:
        sufficiency_pct: Book % value change per +10 vol points, from
            ``PortfolioAnalyzer.calculate_vega_sufficiency_pct``. ``None``
            when the reading could not be taken.
        floor_pct: IPS ``vega.sufficiency_min_pct`` — below it the hedge
            barely responds to a volatility spike.
        ceiling_pct: IPS ``vega.sufficiency_max_pct`` — above it the book
            is vega-dominated rather than convexity-driven.
        meets_target: True when *sufficiency_pct* is inside the band,
            inclusive of both edges. ``None`` alongside a ``None``
            reading — never ``False``, which would grade an unmeasured
            book as a breaching one.

    """

    sufficiency_pct: float | None
    floor_pct: float
    ceiling_pct: float
    meets_target: bool | None


class ComplianceStanding(StrEnum):
    """The IPS compliance section's overall verdict (#433)."""

    PASS = "PASS"  # ruff: ignore[hardcoded-password-string]  # a verdict word, not a credential
    FAIL = "FAIL"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class IpsComplianceRow:
    """One row in the IPS compliance summary table.

    Attributes:
        action: Recommended remediation when this row fails — ``None``
            exactly when ``passes`` is not True. Set by ``build_ips_compliance``
            from the same ``CostSection``/``ProtectionSection`` fields that
            already decided ``passes``; it explains an already-decided
            failure, it never re-decides one (#307).

    """

    metric: str
    target: str
    actual: str
    passes: bool | None
    action: str | None = None


@dataclass(frozen=True)
class IpsComplianceSection:
    """IPS compliance summary table.

    A row's ``passes`` is ``True`` (in policy), ``False`` (a breach) or
    ``None`` (**unmeasured**: the reading could not be taken, which is
    neither; #433). The section's verdict has three states for the same
    reason: :attr:`standing` is ``FAIL`` if any row is breached, otherwise
    ``INCOMPLETE`` if any row is unmeasured, otherwise ``PASS``. An
    unmeasured row never turns a PASS into a FAIL, and never lets the
    section read PASS either.

    Attributes:
        rows: One row per compliance metric.
        all_pass: True only when every row passes (so ``False`` for both
            ``FAIL`` and ``INCOMPLETE``; use :attr:`standing` to tell them
            apart).

    """

    rows: tuple[IpsComplianceRow, ...]
    all_pass: bool

    @property
    def failing_metrics(self) -> tuple[str, ...]:
        """The metrics that are breached (not the unmeasured ones)."""
        return tuple(r.metric for r in self.rows if r.passes is False)

    @property
    def unmeasured_metrics(self) -> tuple[str, ...]:
        """The metrics whose reading could not be taken."""
        return tuple(r.metric for r in self.rows if r.passes is None)

    @property
    def standing(self) -> ComplianceStanding:
        """The overall verdict: FAIL on a breach, else INCOMPLETE if unmeasured.

        PASS only when every row is in policy: an unmeasured row never
        reads as a pass.
        """
        if self.failing_metrics:
            return ComplianceStanding.FAIL
        if self.unmeasured_metrics:
            return ComplianceStanding.INCOMPLETE
        return ComplianceStanding.PASS


@dataclass(frozen=True)
class DecisionSection:
    """Part X.2 decision-matrix + entry-timing verdict for this report.

    Attributes:
        verdict: ``DecisionResult.verdict.value`` (BUY/MAINTAIN/AVOID/
            MONETIZE/INSUFFICIENT_DATA).
        rationale: ``DecisionResult.rationale``.
        entry_recommendation: ``EntryTimingResult.recommendation``.
        should_enter: ``EntryTimingResult.should_enter``.
        data_quality_note: Set, verbatim, whenever either
            ``decision_matrix`` or ``entry_timing_tree`` withheld a real
            verdict for data-quality reasons; ``None`` when both returned
            one.

    """

    verdict: str
    rationale: str
    entry_recommendation: str
    should_enter: bool
    data_quality_note: str | None


@dataclass(frozen=True)
class ProgramReport:
    """Assembled Part VII hedge program report.

    All sections are frozen value objects.  Build with
    :func:`build_program_report`; render with :func:`render_markdown` or
    :func:`render_html`.
    """

    header: ReportHeader
    cost: CostSection
    protection: ProtectionSection
    vega: VegaSection
    market_context: MarketContextSection
    return_framing: ReturnFramingSection
    monetization: MonetizationSection
    ips_compliance: IpsComplianceSection
    decision: DecisionSection | None = None


# ── Builder ───────────────────────────────────────────────────────────────


def build_program_report(  # pylint: disable=too-many-arguments
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    crash_result: CrashConvexityResult,
    carry_metrics: dict[str, Any],
    vega_sufficiency_pct: float | None,
    market_env: MarketEnvironment,
    provenance_ledger: ProvenanceLedger,
    period_label: str,
    as_of: datetime.date,
    monetization_plan: MonetizationPlan | None = None,
) -> ProgramReport:
    """Assemble a ProgramReport from already-computed inputs.

    Does not reprice options, recalculate crash payoffs, or re-assess
    the market environment — every figure is consumed as supplied.
    Book notional is derived internally as
    ``abs(portfolio.underlying_quantity) * portfolio.spot_price``.

    Args:
        portfolio: The live hedge portfolio.  Used only to derive
            book notional; no repricing is performed.
        ips_config: Validated IPS policy.
        crash_result: Pre-computed from ``compute_crash_convexity``.
        carry_metrics: Dict from
            ``PortfolioAnalyzer.calculate_carry_metrics``.
        vega_sufficiency_pct: Pre-computed from
            ``PortfolioAnalyzer.calculate_vega_sufficiency_pct`` (#409) —
            passed in rather than read off *portfolio* here, the same way
            *carry_metrics* is, so this builder keeps its standing "does
            not reprice; every figure is consumed as supplied" contract.
            ``None`` when the reading could not be taken; the compliance
            row then reports it as unmeasured rather than as a breach.
        market_env: Pre-assessed from ``assess_market_environment``.
        provenance_ledger: Pre-built from
            ``analysis.provenance.build_provenance_ledger``, over the
            same *market_env* and *portfolio*. ``MarketContextSection.
            data_quality`` reads this ledger's ``combined_quality``
            rather than ``market_env.data_quality`` directly (#367) —
            the same grade the live pages' banner reflects, reused
            rather than re-derived, so a stale hand-entered pricing
            input can turn the digest's caveat too, not only the six
            fetched market readings.
        period_label: Human-readable period (e.g. ``"Q2 2026"``).
        as_of: Report date.
        monetization_plan: Optional pre-computed
            :class:`~deltadewa.analysis.monetization.MonetizationPlan`.
            When supplied, the ``MonetizationSection`` is enriched with
            the current gain and advisory recommended sell amounts.

    Returns:
        Fully assembled ``ProgramReport``.

    """
    book_notional = abs(portfolio.underlying_quantity) * portfolio.spot_price

    header = ReportHeader(
        program_name=ips_config.program.name,
        instrument=ips_config.program.instrument,
        period_label=period_label,
        as_of=as_of,
    )

    cost = build_cost_section(
        carry_metrics=carry_metrics,
        book_notional=book_notional,
        budget_annual_pct=ips_config.budget.annual_carry_pct,
    )
    protection = build_protection_section(crash_result)
    vega = build_vega_section(
        sufficiency_pct=vega_sufficiency_pct,
        ips_vega=ips_config.vega,
    )
    market_context = _build_market_context(market_env, provenance_ledger)
    decision = _build_decision(
        ips_config=ips_config,
        market_env=market_env,
        protection=protection,
        monetization_plan=monetization_plan,
    )

    return ProgramReport(
        header=header,
        cost=cost,
        protection=protection,
        vega=vega,
        market_context=market_context,
        return_framing=ReturnFramingSection(
            carry_drag_annual_pct=cost.carry_pct_of_notional,
        ),
        monetization=MonetizationSection(
            realized_label=_MONETIZATION_PLACEHOLDER,
            schedule_steps=len(ips_config.monetization.schedule),
            current_gain_pct=(
                monetization_plan.current_gain_pct
                if monetization_plan is not None
                else None
            ),
            recommended_cumulative_sell_pct=(
                monetization_plan.recommended_cumulative_sell_pct
                if monetization_plan is not None
                else None
            ),
            value_to_harvest=(
                monetization_plan.value_to_harvest
                if monetization_plan is not None
                else None
            ),
        ),
        ips_compliance=build_ips_compliance(cost, protection, vega),
        decision=decision,
    )


def _build_decision(
    *,
    ips_config: IpsConfig,
    market_env: MarketEnvironment,
    protection: ProtectionSection,
    monetization_plan: MonetizationPlan | None,
) -> DecisionSection:
    """Compute the decision-matrix + entry-timing verdict for this report.

    Reuses ``protection.convexity_pct`` — the row ``build_protection_section``
    already matched to the IPS crash shock — as ``decision_matrix``'s
    ``convexity_now_pct``, rather than re-deriving it with a second,
    differently-rounded search. Before this, ``weekly_report.main()`` ran
    its own bare-``==`` match for that figure, which could select a
    different row than this one, and fell back to what was then called
    ``payoff_ratio`` (a ratio, not a percent — renamed ``payoff_vs_premium``
    in 4.2, #303) when it found none (#307). When no convexity
    reading is available at all, no fabricated number is fed to the
    classifier — a clear note is set instead.
    """
    me = ips_config.market_environment
    entry = entry_timing_tree(
        market_env,
        vix_very_high=me.vix_very_high,
        vix_caution=me.vix_caution,
        vix_low=me.vix_low,
        skew_high=me.skew_high_pctile / 100.0,
        skew_low=me.skew_low_pctile / 100.0,
    )

    if protection.convexity is None:
        return DecisionSection(
            verdict=DecisionVerdict.INSUFFICIENT_DATA.value,
            rationale=(
                "No IPS convexity policy is loaded — hedge adequacy "
                "cannot be assessed."
            ),
            entry_recommendation=entry.recommendation,
            should_enter=entry.should_enter,
            # ProtectionSection.convexity is None: no IPS convexity policy
            # was loaded. (A policy with an *unmeasured* reading goes to
            # ``decision_matrix``, which says so itself, #433.)
            data_quality_note=(
                "No convexity target is loaded from ips.yaml, so the hedge"
                " cannot be graded against one."
            ),
        )

    decision = decision_matrix(
        market_env,
        convexity_now_pct=protection.convexity_pct,
        ips_convexity=ips_config.convexity,
        monetization_plan=monetization_plan,
    )
    return DecisionSection(
        verdict=decision.verdict.value,
        rationale=decision.rationale,
        entry_recommendation=entry.recommendation,
        should_enter=entry.should_enter,
        data_quality_note=decision.data_quality_note or entry.data_quality_note,
    )


def build_cost_section(
    *,
    carry_metrics: dict[str, Any],
    book_notional: float,
    budget_annual_pct: float,
) -> CostSection:
    """Build the CostSection from carry metrics and notional.

    Public (no leading underscore): reused by ``/monitor``'s IPS
    compliance strip (#298) so the page and the report build the exact
    same ``CostSection`` — never a second packaging of the same fields.
    """
    theta_annual: float = carry_metrics.get("total_theta_annual", 0.0)
    status = carry_vs_budget(
        theta_annual=theta_annual,
        book_notional=book_notional,
        budget_annual_pct=budget_annual_pct,
    )
    return CostSection(
        total_theta_annual=theta_annual,
        book_notional=book_notional,
        carry_pct_of_notional=status.carry_pct_of_notional,
        budget_annual_pct=budget_annual_pct,
        within_budget=status.within_budget,
    )


def build_protection_section(
    crash_result: CrashConvexityResult,
) -> ProtectionSection:
    """Build the ProtectionSection from a CrashConvexityResult.

    Public (no leading underscore): reused by ``/monitor``'s IPS
    compliance strip (#298) — see ``build_cost_section``. Names
    ``crash_result.excluded_expired`` (#375) — hedge-only, exactly the
    long-put legs the figures above dropped for being already expired —
    on both return branches.
    """
    excluded_expired_legs = describe_expired_legs(crash_result.excluded_expired)
    if crash_result.ips_convexity is None:
        return ProtectionSection(
            payoff_vs_premium=crash_result.payoff_vs_premium,
            convexity=None,
            premium_paid=crash_result.premium_paid,
            premium_basis=crash_result.premium_basis.value,
            excluded_expired_legs=excluded_expired_legs,
        )

    ips_conv = crash_result.ips_convexity
    ips_shock = ips_conv.crash_scenario_pct
    matching = next(
        (
            r
            for r in crash_result.scenario_rows
            if same_crash_depth(r.shock_pct, ips_shock)
        ),
        None,
    )
    # The matching row was graded at the IPS depth by the referee; reuse that
    # grading rather than grading again. No matching row means no reading.
    grading = (
        matching.convexity
        if matching is not None and matching.convexity is not None
        else grade_convexity(None, ips_conv, at_shock_pct=ips_shock)
    )
    return ProtectionSection(
        payoff_vs_premium=crash_result.payoff_vs_premium,
        convexity=grading,
        premium_paid=crash_result.premium_paid,
        premium_basis=crash_result.premium_basis.value,
        excluded_expired_legs=excluded_expired_legs,
    )


def build_vega_section(
    *,
    sufficiency_pct: float | None,
    ips_vega: IpsVega,
) -> VegaSection:
    """Build the VegaSection from an already-computed reading (#409).

    Public (no leading underscore), and takes the reading rather than a
    portfolio: reused by ``/monitor``'s IPS compliance strip and by
    ``/design``'s sizing panel — see ``build_cost_section`` — so the one
    band comparison lives here instead of being re-typed at each surface.
    Taking a float keeps this module's standing contract that it never
    reprices ("every figure is drawn from the arguments supplied by the
    caller"); both callers get the number from the single
    ``PortfolioAnalyzer.calculate_vega_sufficiency_pct``.

    Args:
        sufficiency_pct: Book % value change per +10 vol points, or
            ``None`` when it could not be measured.
        ips_vega: The IPS ``vega:`` policy section.

    Returns:
        The reading, the band it was measured against, and whether it sits
        inside — ``meets_target=None`` for a ``None`` reading, so an
        unmeasured book is never graded as a breaching one.

    """
    return VegaSection(
        sufficiency_pct=sufficiency_pct,
        floor_pct=ips_vega.sufficiency_min_pct,
        ceiling_pct=ips_vega.sufficiency_max_pct,
        meets_target=(
            None
            if sufficiency_pct is None
            else (
                ips_vega.sufficiency_min_pct
                <= sufficiency_pct
                <= ips_vega.sufficiency_max_pct
            )
        ),
    )


def _build_market_context(
    market_env: MarketEnvironment,
    provenance_ledger: ProvenanceLedger,
) -> MarketContextSection:
    """Build the MarketContextSection from a MarketEnvironment.

    ``data_quality`` reads ``provenance_ledger.combined_quality`` rather
    than ``market_env.data_quality`` directly (#367) — see
    ``build_program_report``'s docstring on why. Every other field still
    comes from *market_env* itself; only the grade's source changes.

    ``needs_alarm`` is computed separately, from ``assess_freshness``
    (#393/#398) — *not* derived from ``data_quality`` above, since that
    would reintroduce the same combined-quality merge bug for a
    hand-entered input that is merely ``AGING``.
    """
    return MarketContextSection(
        vix=market_env.vix,
        regime_label=(
            market_env.regime_label.value
            if market_env.regime_label is not None
            else None
        ),
        skew_percentile=market_env.skew_percentile,
        hedge_cost_verdict=(
            market_env.hedge_cost_verdict.value
            if market_env.hedge_cost_verdict is not None
            else None
        ),
        data_quality=provenance_ledger.combined_quality.value,
        needs_alarm=assess_freshness(provenance_ledger) is not None,
        skew_lookback_days=market_env.skew_lookback_days,
    )


def build_ips_compliance(
    cost: CostSection,
    protection: ProtectionSection,
    vega: VegaSection,
) -> IpsComplianceSection:
    """Build the IPS compliance table from cost, protection and vega.

    Public (no leading underscore): this is the program's single
    definition of "compliant" (Batch 3b). ``/monitor``'s compliance strip
    (#298) calls this directly, on the sections it builds via
    ``build_cost_section``/``build_protection_section``/
    ``build_vega_section`` — never a second pass/fail comparison of its
    own. Two graders that agree today would silently diverge the first
    time an IPS band moves; routing every surface through this one
    function is what keeps that from happening.

    **What belongs here (#409).** A row is a standing constraint on the
    book's *shape* — one a reader can only answer by resizing or
    restructuring. Carry (the budget ceiling), crash convexity (the target
    band) and vega sufficiency (the sufficiency band) are the three the IPS
    states that way. The IPS's other numbers are *triggers* (the four rally
    bands, delta-ratio deviation, expiry days, theta cost, gamma drift, the
    convexity cliff), which say "an event occurred, act" and are surfaced
    by ``analysis/hedge_triggers.py`` and ``analysis/roll_status.py``; or
    *interpretation* bands (the hedge-efficiency ratio, the
    market-environment regimes), which label a reading without a pass/fail
    — and the efficiency ratio in particular is derived from carry and
    convexity, so grading it here would double-count two rows that are
    already present. ``tests/test_reporting/test_ips_band_registry.py``
    pins that classification over every band the IPS defines, so a new one
    cannot be added without someone deciding which kind it is.

    Vega sufficiency was missing until #409, which is exactly the failure
    that classification is meant to prevent: the metric was computed and
    rendered on three surfaces and graded for policy on none of them, so a
    book below the floor read PASS.
    """
    rows: list[IpsComplianceRow] = [
        IpsComplianceRow(
            metric="Annual carry cost",
            target=f"≤ {cost.budget_annual_pct:.2f}% of notional",
            actual=f"{cost.carry_pct_of_notional:.2f}%",
            passes=cost.within_budget,
            action=(
                None
                if cost.within_budget
                else (
                    "Carry is above the IPS budget of "
                    f"{cost.budget_annual_pct:.2f}% — trim position"
                    " size, or roll to a less expensive structure, to"
                    " bring theta back within budget."
                )
            ),
        ),
    ]

    p = protection
    grading = p.convexity
    if grading is not None:
        target_str = f"{_band_text(grading)} of book"
        # The referee's display rule: one decimal, more only when rounding
        # would put the figure on the wrong side of the band from its grade.
        actual_str = grading.display()
        passes = grading.meets
        action: str | None = None
        if passes is not True:
            if grading.grade is ConvexityGrade.UNMEASURED:
                action = (
                    f"Crash convexity {COULD_NOT_BE_MEASURED} at the IPS"
                    " shock — check that the book has an underlying"
                    " position and that the crash scenario has a matching"
                    f" repriced row. {UNMEASURED_NOT_BREACHING}"
                )
            elif grading.grade is ConvexityGrade.BELOW:
                action = (
                    "Convexity is below target — the book is"
                    " under-hedged; increase hedge size, or roll to a"
                    " cheaper/deeper structure, to raise convexity."
                )
            else:
                action = (
                    "Convexity is above target — the book is"
                    " over-hedged; consider monetizing or trimming to"
                    " bring convexity back within band."
                )
        rows.append(
            IpsComplianceRow(
                metric=(
                    "Crash convexity "
                    f"({format_depth(grading.shock_pct)}% shock)"
                ),
                target=target_str,
                actual=actual_str,
                passes=passes,
                action=action,
            ),
        )
    else:
        rows.append(
            IpsComplianceRow(
                metric="Crash convexity",
                target="—",
                actual="—",
                passes=False,
                action=(
                    "No IPS convexity policy is loaded — load one to"
                    " enable crash-convexity compliance monitoring."
                ),
            ),
        )

    rows.append(_vega_compliance_row(vega))

    return IpsComplianceSection(
        rows=tuple(rows),
        all_pass=all(r.passes is True for r in rows),
    )


def _vega_compliance_row(vega: VegaSection) -> IpsComplianceRow:
    """One compliance row for vega sufficiency (#409).

    Same shape as the carry and convexity rows above: target, actual,
    pass/fail, and an ``action`` set exactly when the row fails. The action
    branches on *which side* of the band the reading fell — below the floor
    the hedge barely responds to a vol spike (buy more vega), above the
    ceiling the book is vega-dominated rather than convexity-driven (a
    different problem with the opposite remedy), and an unmeasured reading
    is neither.
    """
    # The en dash matches the convexity row's own target string above,
    # built the same way and read on the same table.
    target = (
        f"{vega.floor_pct:.1f}%\u2013{vega.ceiling_pct:.1f}% per +10 vol pts"
    )
    if vega.sufficiency_pct is None:
        return IpsComplianceRow(
            metric="Vega sufficiency",
            target=target,
            actual="—",
            passes=None,
            action=(
                f"Vega sufficiency {COULD_NOT_BE_MEASURED} — check that the"
                " book has a value to measure the vol shock against."
                f" {UNMEASURED_NOT_BREACHING}"
            ),
        )

    passes = vega.meets_target
    action: str | None = None
    if passes is not True:
        if vega.sufficiency_pct < vega.floor_pct:
            action = (
                "Vega sufficiency is below the IPS floor — the book will"
                " barely respond to a volatility spike; increase hedge"
                " size, or roll to longer-dated or nearer-the-money"
                " strikes, to raise vega."
            )
        else:
            action = (
                "Vega sufficiency is above the IPS ceiling — the book is"
                " vega-dominated rather than convexity-driven; trim vega"
                " or shift toward deeper, more convex strikes."
            )
    return IpsComplianceRow(
        metric="Vega sufficiency",
        target=target,
        actual=f"{vega.sufficiency_pct:.1f}%",
        passes=passes,
        action=action,
    )


# ── Formatting helpers (module-private) ───────────────────────────────────


def _fmt_money(value: float) -> str:
    """Format a dollar amount with sign and comma separators."""
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def _band_text(grading: ConvexityGrading) -> str:
    """Return the band as the reports print it, edges never rounded away."""
    return (
        f"{format_band_edge(grading.min_pct, min_places=1)}%\u2013"
        f"{format_band_edge(grading.max_pct, min_places=1)}%"
    )


def _convexity_text(protection: ProtectionSection) -> str:
    """Return the convexity reading as the referee says to print it (#434).

    Never rounds a figure onto the wrong side of the band from the PASS/FAIL
    beside it; an em dash when there is no reading.
    """
    if protection.convexity is None:
        return "—"
    return protection.convexity.display()


def _fmt_pct(value: float | None, decimals: int = 2) -> str:
    """Format a percentage value, or an em-dash when ``None``."""
    if value is None:
        return "—"
    return f"{value:.{decimals}f}%"


#: How many reasons a period is unreconcilable are listed before the rest
#: are counted. Every reason since inception stays listed in full by
#: ``python -m deltadewa.history_cli status``; the digest names the
#: first few and says how many more there are, rather than growing a page
#: a week.
_MAX_LISTED_BREAKS: Final = 5

_REALIZED_VS_THETA_NOTE: Final = (
    "Realized carry is measured from recorded fills and marks; theta "
    "carry is a forward model estimate of the current book. They answer "
    "different questions and will not agree. A positive realized carry is "
    "a cost; a negative one means the hedge paid."
)


def _signed_pct(value: float) -> str:
    return f"{value:+.2f}%"


def _carry_cell(carry: RealizedCarry, *, net: bool) -> str:
    amount = carry.net if net else carry.gross
    annual = carry.net_annual_pct if net else carry.gross_annual_pct
    if annual is None:
        return _fmt_money(amount)
    return f"{_fmt_money(amount)} ({_signed_pct(annual)} annualised)"


def _return_cell(result: HedgedReturn | None, *, after: bool) -> str:
    if result is None:
        return "—"
    value = result.after_hedge_pct if after else result.before_hedge_pct
    return "unavailable" if value is None else _signed_pct(value)


def _theta_rows(rf: ReturnFramingSection) -> list[tuple[str, str]]:
    rows = [
        (
            "Theta carry drag (annual, model)",
            f"\u2212{_fmt_pct(rf.carry_drag_annual_pct)}",
        ),
    ]
    if (
        rf.weekly_carry_cost is not None
        and rf.elapsed_days is not None
        and rf.cumulative_carry_cost is not None
        and rf.cumulative_since is not None
    ):
        rows += [
            (
                "Theta carry this period (model)",
                (
                    f"{_fmt_money(rf.weekly_carry_cost)} over "
                    f"{rf.elapsed_days} day(s)"
                ),
            ),
            (
                f"Theta carry since {rf.cumulative_since} (model)",
                _fmt_money(rf.cumulative_carry_cost),
            ),
        ]
    if rf.premium_paid_point_in_time is not None:
        rows.append(
            (
                "Point-in-time premium invested",
                _fmt_money(rf.premium_paid_point_in_time),
            ),
        )
    return rows


def _break_notes(carry: RealizedCarry) -> list[str]:
    if carry.reconcilable:
        return []
    listed = carry.breaks[:_MAX_LISTED_BREAKS]
    notes = [
        (
            f"Since {carry.start}, realized carry cannot be reconciled against "
            f"statements ({len(carry.breaks)} reason(s)):"
        ),
        *(f"- {reason}" for reason in listed),
    ]
    hidden = len(carry.breaks) - len(listed)
    if hidden:
        notes.append(
            f"- …and {hidden} more; `python -m deltadewa.history_cli "
            "status` lists them all.",
        )
    return notes


def _measured_rows(
    section: RealizedCarrySection,
) -> tuple[list[tuple[str, str]], list[str]]:
    inception = section.inception
    if inception is None:  # pragma: no cover - MEASURED implies inception
        return [], []
    start = section.history_start
    rows = [
        (
            f"Realized carry since {start}, gross",
            _carry_cell(inception, net=False),
        ),
        (
            f"Realized carry since {start}, net of monetization",
            _carry_cell(inception, net=True),
        ),
    ]
    if section.latest is not None:
        rows.append(
            (
                (
                    f"Realized carry {section.latest.start} to "
                    f"{section.latest.end}, gross"
                ),
                _carry_cell(section.latest, net=False),
            ),
        )
    rows += [
        (
            f"Before-hedge return since {start}",
            _return_cell(section.inception_return, after=False),
        ),
        (
            f"After-hedge return since {start}",
            _return_cell(section.inception_return, after=True),
        ),
    ]
    notes = [_REALIZED_VS_THETA_NOTE, *_break_notes(inception)]
    reason = (
        section.inception_return.unavailable_reason
        if section.inception_return is not None
        else None
    )
    if reason:
        notes.append(f"Before/after-hedge return unavailable: {reason}.")
    return rows, notes


def realized_framing_rows(
    rf: ReturnFramingSection,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Build §4's rows and notes once, for both renderers.

    Only called when ``rf.realized`` is set. One builder rather than one
    per format, so the markdown and HTML digests cannot disagree about
    what §4 says.

    Returns:
        ``(rows, notes)``: label/value pairs for the table, then the
        sentences under it, in order.

    """
    section = rf.realized
    rows = _theta_rows(rf)
    notes: list[str] = []
    if section is None:  # pragma: no cover - callers check first
        return rows, notes
    if section.status is RealizedStatus.UNREADABLE:
        rows.append(("Realized carry", "unavailable"))
        notes.append(f"The position history could not be read: {section.error}")
    elif section.status is RealizedStatus.NOT_STARTED:
        rows.append(("Realized carry", "not started"))
        notes.append(
            "The position history has not started. Run `python -m "
            "deltadewa.history_cli init`, or it starts with the next "
            "weekly mark.",
        )
    else:
        notes.append(
            f"No position history before {section.history_start}. The book "
            f"held then is carried in at its {section.basis} mark of "
            f"{_fmt_money(section.opening_value or 0.0)}.",
        )
        if section.status is RealizedStatus.ONE_MARK:
            rows.append(
                (
                    "Realized carry",
                    f"not yet measurable (one mark, {section.history_start})",
                ),
            )
        else:
            measured_rows, measured_notes = _measured_rows(section)
            rows += measured_rows
            notes += measured_notes
    if section.mark_note:
        notes.append(f"This week: {section.mark_note}.")
    return rows, notes


def _realized_framing_html(rf: ReturnFramingSection) -> str:
    """Render §4's realized-carry table and notes as HTML."""
    rows, notes = realized_framing_rows(rf)
    row_html = "\n".join(
        f"<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>"
        for label, value in rows
    )
    note_html = "\n".join(
        f'<p class="note">{escape(note)}</p>' for note in notes
    )
    return (
        "<table>\n<tr><th></th><th>Value</th></tr>\n"
        f"{row_html}\n</table>\n{note_html}"
    )


def _data_quality_cell(mc: MarketContextSection) -> str:
    """Build the Market Context table's "Data quality" value, qualified.

    ``mc.data_quality`` is shown here unconditionally, whether or not
    ``needs_alarm`` fires the caveat above it (#398) — but ``"STALE"``
    reads as an alarm word on its own, and the only way to reach
    ``data_quality == "STALE"`` with ``needs_alarm`` false is a
    hand-entered input that is merely ``AGING`` (``combined_quality``
    maps ``AGING`` to ``DataQuality.STALE`` — the identical string a
    genuinely dead fetched feed produces). Left unqualified, a reader
    skimming this row alone — the false-green-auditor's finding — could
    reasonably read that as something to act on, exactly the alarm the
    caveat's absence says isn't warranted. Every other reachable
    combination (``needs_alarm`` true; or false with ``LIVE``/``CACHED``)
    needs no qualifier: either the caveat right above already explains
    it, or the grade itself already reads as healthy.
    """
    if not mc.needs_alarm and mc.data_quality not in ("LIVE", "CACHED"):
        return (
            f"{mc.data_quality} (hand-entered input overdue for "
            "review — not a live-feed problem)"
        )
    return mc.data_quality


def _pass_fail_md(value: bool | None) -> str:
    """Markdown pass/fail indicator (✓ PASS / ✗ FAIL / —)."""
    if value is None:
        return "—"
    return "✓ PASS" if value else "✗ FAIL"


def _standing_md(ic: IpsComplianceSection) -> str:
    """Markdown overall verdict: PASS, FAIL, or INCOMPLETE naming the gap."""
    standing = ic.standing
    if standing is ComplianceStanding.INCOMPLETE:
        return (
            f"— INCOMPLETE (not measured: {', '.join(ic.unmeasured_metrics)})"
        )
    return _pass_fail_md(standing is ComplianceStanding.PASS)


def _standing_html(ic: IpsComplianceSection) -> str:
    """HTML overall verdict: PASS, FAIL, or INCOMPLETE naming the gap."""
    standing = ic.standing
    if standing is ComplianceStanding.INCOMPLETE:
        missing = escape(", ".join(ic.unmeasured_metrics))
        return f"<span>&#8212; INCOMPLETE ({NOT_MEASURED}: {missing})</span>"
    return _pass_fail_html(standing is ComplianceStanding.PASS)


def _pass_fail_html(value: bool | None) -> str:
    """HTML pass/fail indicator with colour class."""
    if value is None:
        return "<span>—</span>"
    if value:
        return '<span class="pass">✓ PASS</span>'
    return '<span class="fail">✗ FAIL</span>'


def _html_or_dash(value: str | None) -> str:
    """HTML-escape a string value, or return an em-dash entity."""
    return escape(value) if value is not None else "&mdash;"


_MAX_NAMED_EXPIRED_LEGS: Final[int] = 3


def expired_legs_caveat(legs: tuple[str, ...]) -> str | None:
    """Build the #375 plain-text caveat naming excluded expired legs.

    Public (no leading underscore): reused by ``/monitor``'s compliance
    strip, which renders the same sentence — never a second wording of
    its own — as a ``plain-language`` paragraph.

    Args:
        legs: ``ProtectionSection.excluded_expired_legs``. Each entry is
            one leg label from
            ``analysis.crash_repricing.describe_expired_legs``.

    Returns:
        ``None`` when *legs* is empty (the common case — nothing to
        caveat). Otherwise one sentence, singular/plural as appropriate,
        naming up to :data:`_MAX_NAMED_EXPIRED_LEGS` legs and summarising
        the rest as ``"...and N more."``.

    """
    if not legs:
        return None
    noun = "leg" if len(legs) == 1 else "legs"
    shown = legs[:_MAX_NAMED_EXPIRED_LEGS]
    remainder = len(legs) - len(shown)
    named = ", ".join(shown)
    if remainder > 0:
        named += f", …and {remainder} more"
    return f"Convexity excludes {len(legs)} expired {noun}: {named}."


def _expired_caveat_html(legs: tuple[str, ...]) -> str:
    """HTML ``<div class="caveat">`` for :func:`expired_legs_caveat`.

    ``""`` when *legs* is empty — matching the empty-string convention the
    data-quality caveat already uses in :func:`render_html_body`, so an
    unconditional f-string insertion renders nothing rather than a blank
    ``<div>``.
    """
    caveat = expired_legs_caveat(legs)
    if caveat is None:
        return ""
    return f'<div class="caveat">{escape(caveat)}</div>'


# ── Markdown renderer ─────────────────────────────────────────────────────


def render_markdown(report: ProgramReport) -> str:
    """Render a ProgramReport as a Markdown string.

    Sections follow the `Part VII
    <https://qwertytam.github.io/deltadewa-handbook/part-7/>`_
    handbook format, separated by horizontal rules.  The IPS compliance
    block is a Markdown pipe table, followed by a recommended-action line
    for each failing row.  Pass/fail uses ✓/✗ symbols.  A blockquote
    caveat is injected in the market-context section when data quality is
    STATIC or UNAVAILABLE.  §7 Decision & entry timing renders whenever
    ``report.decision`` is set (#307).

    Args:
        report: Assembled report to render.

    Returns:
        Multi-line Markdown string suitable for display or export.

    """
    lines: list[str] = []

    # ── Header ──────────────────────────────────────────────────────────
    h = report.header
    lines += [
        "# Part VII: Hedge Program Report",
        "",
        f"**Program:** {h.program_name} ({h.instrument})  ",
        f"**Period:** {h.period_label}  ",
        f"**As of:** {h.as_of}",
        "",
        "---",
        "",
    ]

    # ── 1. Cost ─────────────────────────────────────────────────────────
    c = report.cost
    lines += [
        "## 1. Cost",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Annual theta (carry cost) | {_fmt_money(c.total_theta_annual)} |",
        (
            f"| Carry as % of book notional"
            f" | {_fmt_pct(c.carry_pct_of_notional)} |"
        ),
        f"| IPS budget | ≤ {_fmt_pct(c.budget_annual_pct)} |",
        f"| Status | {_pass_fail_md(c.within_budget)} |",
        "",
    ]

    # ── 2. Protection ───────────────────────────────────────────────────
    p = report.protection
    ratio_str = (
        f"{p.payoff_vs_premium:.1f}\u00d7"
        if p.payoff_vs_premium is not None
        else "—"
    )
    crash_label = (
        f"{format_depth(p.ips_crash_pct)}% shock"
        if p.ips_crash_pct is not None
        else "n/a (no IPS scenario)"
    )
    target_band = (
        f"{_band_text(p.convexity)} of book" if p.convexity is not None else "—"
    )
    lines += [
        "## 2. Protection",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        (
            f"| Premium paid"
            f" | {_fmt_money(p.premium_paid)} ({p.premium_basis}) |"
        ),
        f"| IPS crash scenario | {crash_label} |",
        f"| Payoff ratio at crash | {ratio_str} |",
        f"| Convexity (net P&L % of book) | {_convexity_text(p)} |",
        f"| IPS convexity target | {target_band} |",
        f"| Status | {_pass_fail_md(p.meets_target)} |",
        "",
        (
            '> "Payoff ratio at crash" is the handbook\'s '
            "Payoff-vs-Premium Multiple (payoff per dollar of premium "
            "paid) — distinct from the Offset Ratio (payoff per dollar "
            "of underlying loss offset) shown on `/monitor`. See the "
            "handbook's [Ratio Disambiguation]"
            "(https://qwertytam.github.io/deltadewa-handbook/0.1/"
            "part-6/ratio-disambiguation/) page."
        ),
        "",
    ]
    expired_caveat = expired_legs_caveat(p.excluded_expired_legs)
    if expired_caveat is not None:
        lines += [f"> {expired_caveat}", ""]

    # ── 3. Market Context ────────────────────────────────────────────────
    mc = report.market_context
    lines.append("## 3. Market Context")
    lines.append("")
    if mc.needs_alarm:
        lines += [
            (
                f"> ⚠ Data quality: **{mc.data_quality}**"
                " — figures are reference values,"
                " not live market data."
            ),
            "",
        ]
    vix_str = f"{mc.vix:.1f}" if mc.vix is not None else "—"
    skew_str = (
        describe_skew_percentile(mc.skew_percentile, mc.skew_lookback_days)
        if mc.skew_percentile is not None
        else "—"
    )
    lines += [
        "| Metric | Value |",
        "|--------|-------|",
        f"| VIX | {vix_str} |",
        f"| VIX regime | {mc.regime_label or '—'} |",
        f"| SKEW percentile | {skew_str} |",
        f"| Hedge-cost verdict | {mc.hedge_cost_verdict or '—'} |",
        f"| Data quality | {_data_quality_cell(mc)} |",
        "",
    ]

    # ── 4. Return Framing ──────────────────────────────────────
    rf = report.return_framing
    lines += ["## 4. Return Framing", ""]
    if rf.realized is not None:
        rows, notes = realized_framing_rows(rf)
        lines += ["| | Value |", "|---|-------|"]
        lines += [f"| {label} | {value} |" for label, value in rows]
        lines.append("")
        for note in notes:
            lines += [note if note.startswith("- ") else f"> {note}", ""]
    elif (
        rf.weekly_carry_cost is not None
        and rf.elapsed_days is not None
        and rf.cumulative_carry_cost is not None
        and rf.cumulative_since is not None
        and rf.premium_paid_point_in_time is not None
    ):
        lines += [
            "| | Value |",
            "|---|-------|",
            (
                "| Annual carry drag"
                f" | \u2212{_fmt_pct(rf.carry_drag_annual_pct)} |"
            ),
            (
                "| Carry cost this period"
                f" | {_fmt_money(rf.weekly_carry_cost)}"
                f" over {rf.elapsed_days} day(s) |"
            ),
            (
                f"| Cumulative carry cost since {rf.cumulative_since}"
                f" | {_fmt_money(rf.cumulative_carry_cost)} |"
            ),
            (
                "| Point-in-time premium invested"
                f" | {_fmt_money(rf.premium_paid_point_in_time)} |"
            ),
            "",
            f"> {_WEEKLY_CARRY_NOTE}",
            "",
        ]
    else:
        lines += [
            "| | Value |",
            "|---|-------|",
            "| Before-hedge return | PENDING |",
            (
                "| Annual carry drag"
                f" | \u2212{_fmt_pct(rf.carry_drag_annual_pct)} |"
            ),
            "| After-hedge return | PENDING |",
            "",
            f"> {_PENDING_NOTE}",
            "",
        ]

    # ── 5. Monetization Realized ─────────────────────────────────────────
    m = report.monetization
    lines += [
        "## 5. Monetization Realized",
        "",
        f"Realized gains: **{m.realized_label}**",
        "",
    ]
    if m.recommended_cumulative_sell_pct is not None:
        gain_str = (
            f"{m.current_gain_pct:+.1f}%"
            if m.current_gain_pct is not None
            else "unknown (cost basis unavailable)"
        )
        harvest_str = (
            _fmt_money(m.value_to_harvest)
            if m.value_to_harvest is not None
            else "—"
        )
        lines += [
            "Recommended advisory (not realized):",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Current hedge gain | {gain_str} |",
            (
                "| Recommended cumulative sell"
                f" | {_fmt_pct(m.recommended_cumulative_sell_pct, 1)} |"
            ),
            f"| Estimated value to harvest | {harvest_str} |",
            "",
        ]
    lines += [
        (
            "_Monetization is reported separately and never netted"
            " against carry cost._  "
        ),
        f"IPS schedule: {m.schedule_steps} step(s) defined.",
        "",
    ]

    # ── 6. IPS Compliance ────────────────────────────────────────────────
    ic = report.ips_compliance
    lines += [
        "## 6. IPS Compliance",
        "",
        "| Metric | Target | Actual | Status |",
        "|--------|--------|--------|--------|",
    ]
    for row in ic.rows:
        lines.append(
            f"| {row.metric} | {row.target}"
            f" | {row.actual} | {_pass_fail_md(row.passes)} |",
        )
    lines += [
        "",
        f"**Overall: {_standing_md(ic)}**",
        "",
    ]
    action_rows = [row for row in ic.rows if row.action is not None]
    if action_rows:
        lines += [
            f"**Recommended action — {row.metric}:** {row.action}"
            for row in action_rows
        ]
        lines.append("")

    # ── 7. Decision & entry timing ─────────────────────────────────────
    d = report.decision
    if d is not None:
        lines += [
            "## 7. Decision & entry timing",
            "",
            f"**Verdict:** {d.verdict}  ",
            f"**Rationale:** {d.rationale}",
            "",
            f"**Entry-timing recommendation:** {d.entry_recommendation}",
            "",
        ]
        if d.data_quality_note is not None:
            lines += [
                f"> withheld: data quality — {d.data_quality_note}",
                "",
            ]

    return "\n".join(lines)


# ── HTML renderer ─────────────────────────────────────────────────────────

# Public (no leading underscore): the M2.6 weekly digest reuses this verbatim
# so its own document shell matches this one visually, rather than embedding
# a second, drifting copy of the same CSS.
HTML_STYLE = """\
body {
  font-family: system-ui, -apple-system, sans-serif;
  max-width: 820px; margin: 2rem auto; padding: 0 1rem;
  color: #1a1a1a; line-height: 1.5;
}
h1 {
  font-size: 1.4rem; border-bottom: 2px solid #333;
  padding-bottom: .4rem; margin-bottom: .5rem;
}
h2 {
  font-size: 1.05rem; border-bottom: 1px solid #ccc;
  margin-top: 2rem; margin-bottom: .5rem;
}
table {
  border-collapse: collapse; width: 100%;
  margin: .5rem 0; font-size: .9rem;
}
th, td { border: 1px solid #ccc; padding: .35rem .7rem; text-align: left; }
th { background: #f5f5f5; font-weight: 600; }
.pass { color: #2a7a2a; font-weight: 600; }
.fail { color: #cc2222; font-weight: 600; }
.caveat {
  background: #fff8e1; border-left: 4px solid #f9a825;
  padding: .5rem 1rem; margin: .5rem 0; font-size: .9rem;
}
.pending { color: #888; font-style: italic; }
p.note { font-size: .85rem; color: #555; margin-top: .3rem; }"""


def render_html(report: ProgramReport) -> str:
    """Render a ProgramReport as a self-contained HTML document.

    The returned string is a complete ``<!DOCTYPE html>`` page with an
    inline ``<style>`` block — no external dependencies.  Suitable for
    saving to a file or displaying in a Jupyter ``IFrame``.

    All user-controlled string values (program name, period label, etc.)
    are HTML-escaped before insertion.

    Args:
        report: Assembled report to render.

    Returns:
        Self-contained HTML string.

    """
    h = report.header
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Hedge Program Report &mdash; {escape(h.program_name)}</title>
<style>
{HTML_STYLE}
</style>
</head>
<body>

{render_html_body(report)}

</body>
</html>"""


def render_html_body(report: ProgramReport) -> str:
    """Render a ProgramReport's HTML markup, without the document shell.

    Everything ``render_html`` puts inside ``<body>`` — no ``<!DOCTYPE>``,
    ``<html>``, ``<head>``, or ``<style>``. Exists so a caller embedding the
    report inside a larger page (the M2.6 weekly digest, which prepends its
    own lede ahead of this content) can reuse the section markup without a
    second, nested HTML document. ``render_html`` is unchanged behaviour —
    it now just wraps this function's output in the same shell as before.

    Args:
        report: Assembled report to render.

    Returns:
        HTML markup for the report body only.

    """
    h = report.header
    c = report.cost
    p = report.protection
    mc = report.market_context
    rf = report.return_framing
    m = report.monetization
    ic = report.ips_compliance

    # ── Pre-compute per-section fragments ──────────────────────────────
    caveat_html = ""
    if mc.needs_alarm:
        caveat_html = (
            '<div class="caveat">&#9888;&#160;Data quality:'
            f" <strong>{escape(mc.data_quality)}</strong>"
            " &#8212; figures are reference values,"
            " not live market data.</div>"
        )

    expired_caveat_html = _expired_caveat_html(p.excluded_expired_legs)

    ratio_str = (
        f"{p.payoff_vs_premium:.1f}&times;"
        if p.payoff_vs_premium is not None
        else "&mdash;"
    )
    crash_label_html = (
        f"{format_depth(p.ips_crash_pct)}% shock"
        if p.ips_crash_pct is not None
        else "n/a (no IPS scenario)"
    )
    target_band_html = (
        f"{_band_text(p.convexity).replace(chr(0x2013), '&ndash;')} of book"
        if p.convexity is not None
        else "&mdash;"
    )
    vix_str = f"{mc.vix:.1f}" if mc.vix is not None else "&mdash;"
    skew_str = (
        escape(
            describe_skew_percentile(
                mc.skew_percentile,
                mc.skew_lookback_days,
            ),
        )
        if mc.skew_percentile is not None
        else "&mdash;"
    )

    compliance_rows_html = "\n".join(
        f"<tr>"
        f"<td>{escape(r.metric)}</td>"
        f"<td>{escape(r.target)}</td>"
        f"<td>{escape(r.actual)}</td>"
        f"<td>{_pass_fail_html(r.passes)}</td>"
        f"</tr>"
        for r in ic.rows
    )
    action_html = "".join(
        f"<p><strong>Recommended action &mdash; {escape(r.metric)}:</strong>"
        f" {escape(r.action)}</p>"
        for r in ic.rows
        if r.action is not None
    )

    decision_html = ""
    if report.decision is not None:
        d = report.decision
        note_html = (
            f'<p class="note">withheld: data quality &mdash; '
            f"{escape(d.data_quality_note)}</p>"
            if d.data_quality_note is not None
            else ""
        )
        decision_html = f"""<h2>7. Decision &amp; entry timing</h2>
<p><strong>Verdict:</strong> {escape(d.verdict)}</p>
<p><strong>Rationale:</strong> {escape(d.rationale)}</p>
<p><strong>Entry-timing recommendation:</strong> \
{escape(d.entry_recommendation)}</p>
{note_html}"""

    if rf.realized is not None:
        return_framing_html = _realized_framing_html(rf)
    elif (
        rf.weekly_carry_cost is not None
        and rf.elapsed_days is not None
        and rf.cumulative_carry_cost is not None
        and rf.cumulative_since is not None
        and rf.premium_paid_point_in_time is not None
    ):
        return_framing_html = f"""<table>
<tr><th></th><th>Value</th></tr>
<tr><td>Annual carry drag</td>\
<td>&minus;{escape(_fmt_pct(rf.carry_drag_annual_pct))}</td></tr>
<tr><td>Carry cost this period</td>\
<td>{escape(_fmt_money(rf.weekly_carry_cost))} \
over {rf.elapsed_days} day(s)</td></tr>
<tr><td>Cumulative carry cost since {rf.cumulative_since}</td>\
<td>{escape(_fmt_money(rf.cumulative_carry_cost))}</td></tr>
<tr><td>Point-in-time premium invested</td>\
<td>{escape(_fmt_money(rf.premium_paid_point_in_time))}</td></tr>
</table>
<p class="note">{escape(_WEEKLY_CARRY_NOTE)}</p>"""
    else:
        return_framing_html = f"""<table>
<tr><th></th><th>Value</th></tr>
<tr><td>Before-hedge return</td>\
<td class="pending">PENDING</td></tr>
<tr><td>Annual carry drag</td>\
<td>&minus;{escape(_fmt_pct(rf.carry_drag_annual_pct))}</td></tr>
<tr><td>After-hedge return</td>\
<td class="pending">PENDING</td></tr>
</table>
<p class="note">{escape(_PENDING_NOTE)}</p>"""

    mon_advisory_html = ""
    if m.recommended_cumulative_sell_pct is not None:
        gain_str_h = (
            escape(f"{m.current_gain_pct:+.1f}%")
            if m.current_gain_pct is not None
            else "unknown (cost basis unavailable)"
        )
        harvest_str_h = (
            escape(_fmt_money(m.value_to_harvest))
            if m.value_to_harvest is not None
            else "&mdash;"
        )
        sell_pct_h = escape(
            _fmt_pct(m.recommended_cumulative_sell_pct, 1),
        )
        mon_advisory_html = (
            "<p>Recommended advisory (not realized):</p>\n"
            "<table>\n"
            "<tr><th>Metric</th><th>Value</th></tr>\n"
            f"<tr><td>Current hedge gain</td>"
            f"<td>{gain_str_h}</td></tr>\n"
            f"<tr><td>Recommended cumulative sell</td>"
            f"<td>{sell_pct_h}</td></tr>\n"
            f"<tr><td>Estimated value to harvest</td>"
            f"<td>{harvest_str_h}</td></tr>\n"
            "</table>"
        )

    return f"""<h1>Part VII: Hedge Program Report</h1>
<p>
  <strong>Program:</strong> {escape(h.program_name)}\
 ({escape(h.instrument)})<br>
  <strong>Period:</strong> {escape(h.period_label)}<br>
  <strong>As of:</strong> {h.as_of}
</p>

<h2>1. Cost</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Annual theta (carry cost)</td>\
<td>{escape(_fmt_money(c.total_theta_annual))}</td></tr>
<tr><td>Carry as % of book notional</td>\
<td>{escape(_fmt_pct(c.carry_pct_of_notional))}</td></tr>
<tr><td>IPS budget</td>\
<td>&le;&#160;{escape(_fmt_pct(c.budget_annual_pct))}</td></tr>
<tr><td>Status</td><td>{_pass_fail_html(c.within_budget)}</td></tr>
</table>

<h2>2. Protection</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>Premium paid</td>\
<td>{escape(_fmt_money(p.premium_paid))} ({escape(p.premium_basis)})</td></tr>
<tr><td>IPS crash scenario</td><td>{escape(crash_label_html)}</td></tr>
<tr><td>Payoff ratio at crash</td><td>{ratio_str}</td></tr>
<tr><td>Convexity (net P&amp;L % of book)</td>\
<td>{escape(_convexity_text(p))}</td></tr>
<tr><td>IPS convexity target</td><td>{target_band_html}</td></tr>
<tr><td>Status</td><td>{_pass_fail_html(p.meets_target)}</td></tr>
</table>
<p class="note">&#8220;Payoff ratio at crash&#8221; is the handbook's \
Payoff-vs-Premium Multiple (payoff per dollar of premium paid) &#8212; \
distinct from the Offset Ratio (payoff per dollar of underlying loss \
offset) shown on <code>/monitor</code>. See the handbook's \
<a href="{_RATIO_DISAMBIGUATION_URL}">Ratio Disambiguation</a> page.</p>
{expired_caveat_html}

<h2>3. Market Context</h2>
{caveat_html}
<table>
<tr><th>Metric</th><th>Value</th></tr>
<tr><td>VIX</td><td>{vix_str}</td></tr>
<tr><td>VIX regime</td><td>{_html_or_dash(mc.regime_label)}</td></tr>
<tr><td>SKEW percentile</td><td>{skew_str}</td></tr>
<tr><td>Hedge-cost verdict</td>\
<td>{_html_or_dash(mc.hedge_cost_verdict)}</td></tr>
<tr><td>Data quality</td><td>{escape(_data_quality_cell(mc))}</td></tr>
</table>

<h2>4. Return Framing</h2>
{return_framing_html}

<h2>5. Monetization Realized</h2>
<p>Realized gains: <strong>{escape(m.realized_label)}</strong></p>
{mon_advisory_html}
<p class="note">
  Monetization is reported separately and never netted against carry\
 cost.<br>
  IPS schedule: {m.schedule_steps} step(s) defined.
</p>

<h2>6. IPS Compliance</h2>
<table>
<tr><th>Metric</th><th>Target</th><th>Actual</th><th>Status</th></tr>
{compliance_rows_html}
</table>
<p><strong>Overall: {_standing_html(ic)}</strong></p>
{action_html}
{decision_html}"""
