"""Part VII hedge program report — cost, protection, market context, compliance.

Assembles pre-computed crash, carry, and market-environment results into a
single exportable ``ProgramReport`` and renders it as plain Markdown or a
self-contained HTML document.  No repricing or recalculation is performed
here; every figure is drawn from the arguments supplied by the caller.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING, Any, Final

from deltadewa.analysis.carry import carry_vs_budget
from deltadewa.analysis.crash_repricing import describe_expired_legs
from deltadewa.analysis.decision_matrix import (
    DecisionVerdict,
    decision_matrix,
    entry_timing_tree,
)

if TYPE_CHECKING:
    from deltadewa.analysis.crash_payoff import CrashConvexityResult
    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.analysis.monetization import MonetizationPlan
    from deltadewa.analysis.provenance import ProvenanceLedger
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

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

# Qualities worse than a fresh-enough disk-cache hit. CACHED is the healthy
# steady state once a refresh cron exists (M2.6) — a value is only LIVE on
# the call that fetched it — so the caveat must fire on "worse than CACHED",
# not "not LIVE", or it becomes a permanent warning on every scheduled
# report. There is no shared severity ordering to reuse here: ``Source``
# (deltadewa.marketdata) has no UNAVAILABLE member, since a provider never
# returns that source — assess_market_environment substitutes it itself
# when every provider call fails.
_STALE_OR_WORSE: Final[frozenset[str]] = frozenset(
    {"STALE", "STATIC", "UNAVAILABLE"},
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

    All fields except ``premium_paid`` and ``premium_basis`` are ``None``
    when no ``IpsConvexity`` target was supplied to the crash analysis.

    Attributes:
        payoff_vs_premium: Gross payoff / premium at the IPS crash point.
            Renamed from ``payoff_ratio`` (4.2, #303) to match the
            handbook's `Ratio Disambiguation
            <https://qwertytam.github.io/deltadewa-handbook/0.1/part-6/ratio-disambiguation/>`_
            name for this figure — "Payoff-vs-Premium Multiple" — which is
            distinct from the handbook's "Crash Payoff Ratio" (this repo's
            ``offset_ratio``).
        ips_crash_pct: The signed crash shock used (e.g. -25.0).
        convexity_pct: Net-of-underlying crash P&L as % of book notional
            at the IPS shock, from the matching ``CrashScenarioRow``.
        target_min_pct: IPS lower bound for convexity_pct.
        target_max_pct: IPS upper bound for convexity_pct.
        meets_target: True when convexity_pct is within the target band.
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
    ips_crash_pct: float | None
    convexity_pct: float | None
    target_min_pct: float | None
    target_max_pct: float | None
    meets_target: bool | None
    premium_paid: float
    premium_basis: str
    excluded_expired_legs: tuple[str, ...] = ()


@dataclass(frozen=True)
class MarketContextSection:
    """Regime, skew, and hedge-cost classification snapshot.

    Attributes:
        vix: Current VIX level in vol points, or ``None``.
        regime_label: ``"LOW"``, ``"NORMAL"``, or ``"HIGH"``; ``None``
            when data quality is UNAVAILABLE.
        skew_percentile: SKEW percentile rank as a 0-1 fraction, or
            ``None``.
        hedge_cost_verdict: ``"CHEAP"``, ``"FAIR"``, or ``"EXPENSIVE"``;
            ``None`` when unavailable.
        data_quality: ``"LIVE"``, ``"STATIC"``, or ``"UNAVAILABLE"``.

    """

    vix: float | None
    regime_label: str | None
    skew_percentile: float | None
    hedge_cost_verdict: str | None
    data_quality: str


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

    """

    carry_drag_annual_pct: float
    weekly_carry_cost: float | None = None
    elapsed_days: int | None = None
    cumulative_carry_cost: float | None = None
    cumulative_since: datetime.date | None = None
    premium_paid_point_in_time: float | None = None


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
class IpsComplianceRow:
    """One row in the IPS compliance summary table.

    Attributes:
        action: Recommended remediation when this row fails — ``None``
            exactly when ``passes`` is True. Set by ``build_ips_compliance``
            from the same ``CostSection``/``ProtectionSection`` fields that
            already decided ``passes``; it explains an already-decided
            failure, it never re-decides one (#307).

    """

    metric: str
    target: str
    actual: str
    passes: bool
    action: str | None = None


@dataclass(frozen=True)
class IpsComplianceSection:
    """IPS compliance summary table.

    Attributes:
        rows: One row per compliance metric.
        all_pass: True only when every row passes.

    """

    rows: tuple[IpsComplianceRow, ...]
    all_pass: bool


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
        ips_compliance=build_ips_compliance(cost, protection),
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
    )

    if protection.convexity_pct is None:
        return DecisionSection(
            verdict=DecisionVerdict.INSUFFICIENT_DATA.value,
            rationale=(
                "No IPS convexity policy is loaded — hedge adequacy "
                "cannot be assessed."
            ),
            entry_recommendation=entry.recommendation,
            should_enter=entry.should_enter,
            data_quality_note=(
                "ProtectionSection.convexity_pct is None — no IPS "
                "convexity policy loaded"
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
            ips_crash_pct=None,
            convexity_pct=None,
            target_min_pct=None,
            target_max_pct=None,
            meets_target=None,
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
            if round(r.shock_pct, 4) == round(ips_shock, 4)
        ),
        None,
    )
    return ProtectionSection(
        payoff_vs_premium=crash_result.payoff_vs_premium,
        ips_crash_pct=ips_shock,
        convexity_pct=matching.convexity_pct if matching else None,
        target_min_pct=ips_conv.target_min_pct,
        target_max_pct=ips_conv.target_max_pct,
        meets_target=matching.meets_target if matching else None,
        premium_paid=crash_result.premium_paid,
        premium_basis=crash_result.premium_basis.value,
        excluded_expired_legs=excluded_expired_legs,
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
    )


def build_ips_compliance(
    cost: CostSection,
    protection: ProtectionSection,
) -> IpsComplianceSection:
    """Build the IPS compliance table from cost and protection sections.

    Public (no leading underscore): this is the program's single
    definition of "compliant" (Batch 3b). ``/monitor``'s compliance strip
    (#298) calls this directly, on ``CostSection``/``ProtectionSection``
    it builds via ``build_cost_section``/``build_protection_section`` —
    never a second pass/fail comparison of its own. Two graders that
    agree today would silently diverge the first time an IPS band moves;
    routing every surface through this one function is what keeps that
    from happening.
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
    if (
        p.ips_crash_pct is not None
        and p.target_min_pct is not None
        and p.target_max_pct is not None
    ):
        target_str = (
            f"{p.target_min_pct:.1f}%\u2013{p.target_max_pct:.1f}% of book"
        )
        actual_str = (
            f"{p.convexity_pct:.1f}%" if p.convexity_pct is not None else "—"
        )
        passes = bool(p.meets_target)
        action: str | None = None
        if not passes:
            if p.convexity_pct is None:
                action = (
                    "Crash convexity could not be measured at the IPS"
                    " shock — check that the crash scenario has a"
                    " matching repriced row."
                )
            elif p.convexity_pct < p.target_min_pct:
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
                metric=(f"Crash convexity ({p.ips_crash_pct:.0f}% shock)"),
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

    return IpsComplianceSection(
        rows=tuple(rows),
        all_pass=all(r.passes for r in rows),
    )


# ── Formatting helpers (module-private) ───────────────────────────────────


def _fmt_money(value: float) -> str:
    """Format a dollar amount with sign and comma separators."""
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def _fmt_pct(value: float | None, decimals: int = 2) -> str:
    """Format a percentage value, or an em-dash when ``None``."""
    if value is None:
        return "—"
    return f"{value:.{decimals}f}%"


def _pass_fail_md(value: bool | None) -> str:
    """Markdown pass/fail indicator (✓ PASS / ✗ FAIL / —)."""
    if value is None:
        return "—"
    return "✓ PASS" if value else "✗ FAIL"


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
        f"{p.ips_crash_pct:.0f}% shock"
        if p.ips_crash_pct is not None
        else "n/a (no IPS scenario)"
    )
    target_band = (
        f"{_fmt_pct(p.target_min_pct, 1)}"
        f"\u2013{_fmt_pct(p.target_max_pct, 1)} of book"
        if p.target_min_pct is not None
        else "—"
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
        (f"| Convexity (net P&L % of book) | {_fmt_pct(p.convexity_pct, 1)} |"),
        f"| IPS convexity target | {target_band} |",
        f"| Status | {_pass_fail_md(p.meets_target)} |",
        "",
    ]
    expired_caveat = expired_legs_caveat(p.excluded_expired_legs)
    if expired_caveat is not None:
        lines += [f"> {expired_caveat}", ""]

    # ── 3. Market Context ────────────────────────────────────────────────
    mc = report.market_context
    lines.append("## 3. Market Context")
    lines.append("")
    if mc.data_quality in _STALE_OR_WORSE:
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
        f"{mc.skew_percentile * 100:.1f}%"
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
        f"| Data quality | {mc.data_quality} |",
        "",
    ]

    # ── 4. Return Framing ──────────────────────────────────────
    rf = report.return_framing
    lines += ["## 4. Return Framing", ""]
    if (
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
        f"**Overall: {_pass_fail_md(ic.all_pass)}**",
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
    if mc.data_quality in _STALE_OR_WORSE:
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
        f"{p.ips_crash_pct:.0f}% shock"
        if p.ips_crash_pct is not None
        else "n/a (no IPS scenario)"
    )
    target_band_html = (
        f"{_fmt_pct(p.target_min_pct, 1)}"
        f"&ndash;{_fmt_pct(p.target_max_pct, 1)} of book"
        if p.target_min_pct is not None
        else "&mdash;"
    )
    vix_str = f"{mc.vix:.1f}" if mc.vix is not None else "&mdash;"
    skew_str = (
        f"{mc.skew_percentile * 100:.1f}%"
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

    if (
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
<td>{escape(_fmt_pct(p.convexity_pct, 1))}</td></tr>
<tr><td>IPS convexity target</td><td>{target_band_html}</td></tr>
<tr><td>Status</td><td>{_pass_fail_html(p.meets_target)}</td></tr>
</table>
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
<tr><td>Data quality</td><td>{escape(mc.data_quality)}</td></tr>
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
<p><strong>Overall: {_pass_fail_html(ic.all_pass)}</strong></p>
{action_html}
{decision_html}"""
