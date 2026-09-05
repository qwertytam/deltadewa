"""The `/monitor` page: crash-led headline, decisions, position detail.

Read-mostly book review for the non-technical partner (see
``docs/implementation-plan.md`` M2.4). Layout is built once per request
in :func:`render`, at the default dial values; the scenario explorer's
three dials only *update* it afterward, via :func:`register_callbacks`.
No arithmetic happens in this module — every number comes from
``analysis/`` (``monitor_scenario.build_scenario``,
``monitor_scenario.build_scenario_curve``,
``roll_status.evaluate_roll_status``,
``monetization.build_monetization_plan``,
``crash_payoff.compute_crash_convexity``) and ``reporting.program_report``
(``build_cost_section``, ``build_protection_section``,
``build_ips_compliance`` — the IPS compliance strip, #298, reuses the
digest's own section builders and its single compliance definition
rather than writing a second one), and is only formatted here
(``app.format``) or handed to a chart builder
(``visualization.crash_charts_plotly``).

Each panel in :func:`render` is built by its own
:func:`~deltadewa.app.panel_guard.safe_render`-wrapped function (#363): a
raise from any panel's analysis calls degrades that one panel to a
visible notice instead of taking the whole page to HTTP 500, which is
what a single expired leg's crash-skew wing solve did before (#362).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, Patch, dcc, html
from dash.development.base_component import Component

from deltadewa import __version__
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_payoff import compute_crash_convexity
from deltadewa.analysis.crash_repricing import (
    CrashShock,
    gross_quantity,
    hedge_value,
)
from deltadewa.analysis.hedge_efficiency import EfficiencyVerdict
from deltadewa.analysis.market_environment import (
    DataQuality,
    assess_market_environment,
)
from deltadewa.analysis.maturity import MaturityBuckets
from deltadewa.analysis.monetization import build_monetization_plan
from deltadewa.analysis.monitor_scenario import (
    build_scenario,
    build_scenario_curve,
)
from deltadewa.analysis.provenance import build_provenance_ledger
from deltadewa.analysis.roll_status import RollVerdict, evaluate_roll_status
from deltadewa.analysis.spot_reading import observe_spot
from deltadewa.app import format as fmt
from deltadewa.app.bands import band_bar
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.ips_notice import build_no_ips_layout
from deltadewa.app.panel_guard import safe_render
from deltadewa.app.provenance_panel import build_provenance_panel
from deltadewa.app.section_nav import (
    TOP_ANCHOR_ID,
    SectionGroup,
    SectionSpec,
    build_section_nav,
    section_wrapper,
)
from deltadewa.app.shape_notice import shape_notice_text
from deltadewa.clock import program_trading_date
from deltadewa.reporting.program_report import (
    build_cost_section,
    build_ips_compliance,
    build_protection_section,
    expired_legs_caveat,
)
from deltadewa.visualization.crash_charts_plotly import plot_scenario_curve

if TYPE_CHECKING:
    from deltadewa.analysis.monetization import MonetizationPlan
    from deltadewa.analysis.monitor_scenario import ScenarioResult
    from deltadewa.analysis.roll_status import RollStatusRecord
    from deltadewa.analysis.spot_reading import SpotReading
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.reporting.program_report import (
        CostSection,
        IpsComplianceSection,
        ProtectionSection,
    )
    from deltadewa.state import ProgramState

_SPOT_SLIDER_MIN = -50.0
_SPOT_SLIDER_MAX = 10.0
_VOL_SLIDER_MIN = 0.0
_VOL_SLIDER_MAX = 0.30

# #357: this page's TOC entries and each panel's anchor id, in render
# order. /monitor has no zone tier (unlike /design's BOOK/PLANNING/
# EXPLORATION), so build_section_nav gets one flat SectionGroup below —
# same component, no group label. The shape notice is deliberately
# excluded: it renders empty on a conforming book, so a TOC entry to it
# would point at nothing most of the time.
_SECTION_COMPLIANCE: Final = SectionSpec(
    anchor_id="section-compliance",
    title="Compliance",
)
_SECTION_CRASH_SCENARIO: Final = SectionSpec(
    anchor_id="section-crash-scenario",
    title="Crash scenario",
)
_SECTION_DECISIONS: Final = SectionSpec(
    anchor_id="section-decisions",
    title="Decisions",
)
_SECTION_POSITION_DETAIL: Final = SectionSpec(
    anchor_id="section-position-detail",
    title="Position detail",
)
_SECTION_PROVENANCE: Final = SectionSpec(
    anchor_id="section-provenance",
    title="Pricing input provenance",
)
_SECTIONS: Final = (
    _SECTION_COMPLIANCE,
    _SECTION_CRASH_SCENARIO,
    _SECTION_DECISIONS,
    _SECTION_POSITION_DETAIL,
    _SECTION_PROVENANCE,
)

# Labels for the spot cross-check line (#336). STATIC reads "SYNTHETIC" —
# matching chrome.py's own STATIC banner wording — rather than "STATIC",
# since a reader who has never seen the enum should still understand it.
_SPOT_QUALITY_LABEL: dict[DataQuality, str] = {
    DataQuality.LIVE: "LIVE",
    DataQuality.CACHED: "CACHED",
    DataQuality.STALE: "STALE",
    DataQuality.STATIC: "SYNTHETIC",
}

# Mirrors chrome._BANNER_QUALITIES and program_report._STALE_OR_WORSE
# locally rather than importing either module-private name — the
# established convention (see weekly_snapshot.py's own copy) for a set
# every module that reads DataQuality needs but none owns.
_STALE_OR_WORSE: frozenset[DataQuality] = frozenset(
    {DataQuality.STALE, DataQuality.STATIC, DataQuality.UNAVAILABLE},
)


def _no_ips_layout(state: ProgramState) -> html.Div:
    """Build the single "no IPS policy loaded" state for the /monitor page."""
    return build_no_ips_layout(
        state,
        title="Monitor",
        lead=(
            "No IPS policy is loaded, so there is no crash anchor to "
            "render this page around."
        ),
        page_class="page-monitor",
    )


def _spot_headline(
    reading: SpotReading,
    symbol: str,
    warn_pct: float,
) -> html.Div:
    """Build the spot headline: book spot plus the #336 observed cross-check.

    The book-spot sentence is unconditional — every shock below moves from
    ``reading.book_spot`` regardless of the cross-check's quality, since
    that value (never the observed one) is what every number on this page
    is actually computed from (#322). The second line is new: at
    ``UNAVAILABLE`` — today's default state, since nothing has wired this
    reading before #336 — it says so plainly rather than the page's prior
    silence on a distinction it never drew.

    Branches on ``reading.observed_spot`` being ``None``, not on
    ``reading.as_of`` — a ``STATIC`` reading (``StaticProvider``, tests and
    offline use only) carries a real value with no ``as_of`` by the
    ``Observation`` invariant, and must not be mistaken for
    ``UNAVAILABLE``.

    Args:
        reading: The book spot beside the observed market spot, from
            ``analysis.spot_reading.observe_spot``.
        symbol: The book's underlying symbol, for the label.
        warn_pct: ``ips.market_environment.spot_divergence_warn_pct`` — the
            divergence, in percent, past which the cross-check line flags
            rather than merely reports.

    Returns:
        The headline ``html.Div``.

    """
    book_line = html.P(
        f"Book {symbol} spot: "
        f"{fmt.currency(reading.book_spot, decimals=2)} — the shocks "
        "below move from this hand-entered reference point.",
        className="plain-language",
    )
    observed = reading.observed_spot
    if observed is None:
        return html.Div(
            [
                book_line,
                html.P(
                    "No market spot reading is available to cross-check "
                    "against — the value above is hand-entered only.",
                    className="spot-crosscheck spot-crosscheck--unavailable",
                ),
            ],
            className="spot-headline",
        )

    as_of_text = (
        f"as of {fmt.as_of_local(reading.as_of)}"
        if reading.as_of is not None
        else "no as-of date"
    )
    quality_label = _SPOT_QUALITY_LABEL[reading.quality]
    divergence = reading.divergence_pct
    diverged = divergence is not None and abs(divergence) >= warn_pct
    modifier = " spot-crosscheck--diverged" if diverged else ""
    divergence_text = (
        f", {fmt.signed_percent(divergence)} vs book"
        if divergence is not None
        else ""
    )
    return html.Div(
        [
            book_line,
            html.P(
                f"Observed {symbol} spot ({quality_label}, {as_of_text}): "
                f"{fmt.currency(observed, decimals=2)}{divergence_text}.",
                className=(
                    f"spot-crosscheck "
                    f"spot-crosscheck--{reading.quality.value.lower()}"
                    f"{modifier}"
                ),
            ),
        ],
        className="spot-headline",
    )


def _compliance_strip(
    compliance: IpsComplianceSection,
    data_quality: DataQuality,
    excluded_expired: tuple[str, ...] = (),
) -> html.Div:
    """Build the one-line IPS compliance strip (#298).

    The program's single definition of "compliant" is
    ``reporting.program_report.build_ips_compliance`` — the same function
    the weekly digest's §6 calls. This renders its result; it never
    re-derives pass/fail from a band comparison of its own, so this line
    and the digest's Overall verdict cannot silently disagree.

    :func:`render` builds this unconditionally, before the scenario
    explorer, from the *stored* book at the IPS anchor — never from
    ``register_callbacks``' scenario dials, so moving a dial changes the
    numbers below without moving this line. Compliance is a statement
    about the book and the policy, not about a what-if.

    Args:
        compliance: This week's compliance result, computed at the IPS
            anchor via ``build_ips_compliance``.
        data_quality: The page's ``MarketEnvironment.data_quality`` —
            used only to add a caveat line, never to gate the verdict
            itself (carry and crash convexity are QuantLib repricing of
            the book's own hand-entered inputs; market data is not one
            of their inputs, so a stale market-data week must not hide a
            real breach).
        excluded_expired: ``ProtectionSection.excluded_expired_legs``
            (#375) — long-put leg labels dropped from the convexity
            figures for being already expired. Empty ``()`` (the
            default) renders no caveat.

    Returns:
        ``id="compliance-strip"`` — a FAIL book cannot render
        ``/monitor`` without this id present
        (``tests/test_app/test_monitor.py``'s structural guard asserts
        exactly that, rather than pinning a string).

    """
    if compliance.all_pass:
        text = (
            "IPS compliance: PASS — carry and crash convexity both "
            "within policy."
        )
        modifier = "pass"
    else:
        clauses = [
            f"{row.metric} {row.actual} vs. target {row.target}"
            for row in compliance.rows
            if not row.passes
        ]
        text = "IPS compliance: FAIL — " + "; ".join(clauses) + "."
        modifier = "fail"

    children: list[Component] = [
        html.P(
            text,
            className=f"compliance-verdict compliance-verdict--{modifier}",
        ),
    ]
    if data_quality in _STALE_OR_WORSE:
        children.append(
            html.P(
                f"Market data is {data_quality.value} — this verdict is "
                "computed from the book and the IPS policy, not from "
                "market data.",
                className="plain-language",
            ),
        )
    expired_caveat = expired_legs_caveat(excluded_expired)
    if expired_caveat is not None:
        children.append(
            html.P(expired_caveat, className="plain-language"),
        )
    return html.Div(
        children,
        id="compliance-strip",
        className="compliance-strip",
    )


def _scenario_numbers(result: ScenarioResult) -> list[Component]:
    """Build the scenario-numbers children.

    Shows hedge value (shocked), hedge gain, underlying loss, net, and
    the offset ratio.
    """
    offset_text = (
        f"{result.offset_ratio:.2f}x"
        if result.offset_ratio is not None
        else "n/a"
    )
    return [
        html.Div(
            [
                html.Span(
                    "Hedge value (shocked)",
                    className="big-number-label",
                ),
                html.Span(
                    fmt.compact_currency(result.hedge_value_shocked),
                    id="hedge-value-shocked",
                    title=fmt.currency(
                        result.hedge_value_shocked,
                        decimals=2,
                    ),
                    className="big-number",
                ),
            ],
            className="scenario-figure",
        ),
        html.Div(
            [
                html.Span("Hedge gain", className="big-number-label"),
                html.Span(
                    fmt.signed_compact_currency(result.hedge_gain),
                    title=fmt.signed_currency(result.hedge_gain),
                    className="big-number",
                ),
            ],
            className="scenario-figure",
        ),
        html.Div(
            [
                html.Span("Underlying loss", className="big-number-label"),
                html.Span(
                    fmt.signed_compact_currency(result.underlying_loss),
                    title=fmt.signed_currency(result.underlying_loss),
                    className="big-number",
                ),
            ],
            className="scenario-figure",
        ),
        html.Div(
            [
                html.Span("Net", className="big-number-label"),
                html.Span(
                    fmt.signed_compact_currency(result.net),
                    title=fmt.signed_currency(result.net),
                    className="big-number",
                ),
            ],
            className="scenario-figure",
        ),
        html.Div(
            [
                html.Span(
                    "Offset ratio",
                    className="big-number-label",
                    title=(
                        "Hedge dollars gained per dollar of underlying "
                        "loss offset — the handbook's Crash Payoff Ratio "
                        "(offset ratio is a blessed synonym). Distinct "
                        "from the Payoff-vs-Premium Multiple shown "
                        "elsewhere (payoff per dollar of premium paid, "
                        "not per dollar of loss). See the handbook's "
                        "Ratio Disambiguation page, part-6."
                    ),
                ),
                html.Span(offset_text, className="big-number"),
            ],
            className="scenario-figure",
        ),
    ]


def _efficiency_sentence(
    result: ScenarioResult,
    *,
    convexity_pct: float | None,
    convexity_target_min_pct: float | None,
    vega_sufficiency_pct: float | None,
    vega_sufficiency_min_pct: float,
) -> html.P:
    """Build the hedge-efficiency sentence: payoff bought per dollar of carry.

    The bridge between "what does this cost" and "what do we get" — Part X
    #5/#15, the handbook's single "is this hedge worth the money" figure
    (`HER Metric
    <https://qwertytam.github.io/deltadewa-handbook/part-6/hedge-efficiency-ratio/#her-metric>`_
    / `Mathematical Definition of the Ratio
    <https://qwertytam.github.io/deltadewa-handbook/part-6/hedge-efficiency-ratio/#mathematical-definition-of-the-ratio>`_).

    Deliberately one plain-language sentence with no ``big-number`` and no
    ``band_bar``: this page already carries five big numbers and two band
    bars, and M2.4's through-line is that ``/monitor`` reads legibly cold.
    A sixth headline would work against that.

    The wording names *this scenario* because
    :attr:`ScenarioResult.efficiency` is scenario-local — at the IPS default
    dials it is the handbook's ratio, but the spot dial moves it.

    **Wording rule (#304):** the verdict word alone used to read as if the
    ratio sat *inside* the band ("attractive against the IPS 3-6x band" for
    a reading of 20.7 — 3.4x above the ceiling). The sentence now says
    which side of the band the reading is on: below it (``POOR``), inside
    it (``ACCEPTABLE``), or how far above the ceiling (``ATTRACTIVE``).

    **The "cheap but too small" combination (#304):** an ``ATTRACTIVE``
    reading paired with convexity below its target band, or vega
    sufficiency below its floor, is not a good deal — it is a small book
    whose tiny carry makes the ratio look extreme. ``convexity_pct``/
    ``convexity_target_min_pct`` and ``vega_sufficiency_pct``/
    ``vega_sufficiency_min_pct`` are book-level facts (not scenario-local
    like ``result``), passed in by the caller so this function never reads
    ``ips_config``/``portfolio`` itself.

    Args:
        result: This scenario's numbers.
        convexity_pct: Book convexity at the IPS crash anchor, or ``None``
            when no IPS convexity policy is loaded.
        convexity_target_min_pct: IPS convexity band floor, or ``None``
            alongside ``convexity_pct``.
        vega_sufficiency_pct: Book vega sufficiency, portfolio % impact
            per +10 vol points.
        vega_sufficiency_min_pct: IPS vega sufficiency band floor.

    """
    efficiency = result.efficiency
    # ``verdict`` is None exactly when ``ratio`` is (see HedgeEfficiency), but
    # that invariant lives in a docstring, so both are checked here rather
    # than asserted — a renderer should not be the thing that trusts it.
    if efficiency.ratio is None or efficiency.verdict is None:
        return html.P(
            "Hedge efficiency — the payoff bought per dollar of carry — "
            "can't be stated while the book has no carry: the ratio has no "
            "denominator.",
            className="plain-language",
        )

    if efficiency.ratio <= 0:
        # A hedge that loses value in the crash. "Buys $-0.50 of payoff" is
        # not a sentence, and rounding it away would hide the finding.
        return html.P(
            "The hedge *loses* "
            f"{fmt.compact_currency(abs(efficiency.crash_payoff))} at this "
            f"{fmt.signed_percent(result.spot_pct)} scenario, so annual "
            "carry buys no payoff here at all — efficiency is negative, not "
            "merely poor.",
            className="plain-language",
        )

    verdict_word = efficiency.verdict.value.lower()
    band = f"{efficiency.band_min_ratio:g}-{efficiency.band_max_ratio:g}x band"
    if efficiency.verdict is EfficiencyVerdict.POOR:
        position_clause = f"{verdict_word}, below the IPS {band}"
    elif efficiency.verdict is EfficiencyVerdict.ACCEPTABLE:
        position_clause = f"{verdict_word}, within the IPS {band}"
    else:  # ATTRACTIVE
        above_by = efficiency.ratio / efficiency.band_max_ratio
        position_clause = (
            f"{verdict_word}, {above_by:.1f}x above the IPS {band}'s ceiling"
        )

    sentence = (
        f"Every dollar of annual carry buys "
        f"{fmt.currency(efficiency.ratio, decimals=2)} of hedge payoff at "
        f"this {fmt.signed_percent(result.spot_pct)} scenario — "
        f"{position_clause}."
    )

    convexity_short = (
        convexity_pct is not None
        and convexity_target_min_pct is not None
        and convexity_pct < convexity_target_min_pct
    )
    vega_short = (
        vega_sufficiency_pct is not None
        and vega_sufficiency_pct < vega_sufficiency_min_pct
    )
    if efficiency.verdict is EfficiencyVerdict.ATTRACTIVE and (
        convexity_short or vega_short
    ):
        short_reasons = [
            reason
            for reason, is_short in (
                ("crash convexity is below its target band", convexity_short),
                ("vega sufficiency is below its floor", vega_short),
            )
            if is_short
        ]
        sentence += (
            " That is cheap because the book is small, not because it is "
            f"efficient: {' and '.join(short_reasons)}. Cheap, but too "
            "small."
        )

    return html.P(sentence, className="plain-language")


def _cost_panel(
    result: ScenarioResult,
    ips_config: IpsConfig,
    *,
    convexity_pct: float | None,
    vega_sufficiency_pct: float | None,
) -> list[Component]:
    """Build the cost-panel children: carry % of notional vs. IPS budget.

    ``convexity_pct``/``vega_sufficiency_pct`` are book-level facts
    (unaffected by the scenario dials) threaded through to
    :func:`_efficiency_sentence` for the "cheap but too small" combination
    check (#304) — see that function's docstring.
    """
    budget_pct = ips_config.budget.annual_carry_pct
    verdict = "within budget" if result.carry.within_budget else "over budget"
    verdict_class = "within" if result.carry.within_budget else "over"
    return [
        html.Div(
            [
                html.Span(
                    "Annual carry (theta)",
                    className="big-number-label",
                    title=(
                        "Theta: the option book's daily time-decay cost, "
                        "annualized"
                    ),
                ),
                html.Span(
                    fmt.signed_compact_currency(result.carry.theta_annual),
                    id="carry-theta-annual",
                    title=fmt.signed_currency(result.carry.theta_annual),
                    className="big-number",
                ),
            ],
        ),
        html.Div(
            [
                html.Span("Carry", className="big-number-label"),
                html.Span(
                    fmt.percent(result.carry.carry_pct_of_notional),
                    className="big-number",
                ),
                html.Span(
                    f" of notional vs {fmt.percent(budget_pct)} budget "
                    f"({verdict})",
                    className=f"cost-verdict cost-verdict--{verdict_class}",
                ),
                band_bar(
                    value=result.carry.carry_pct_of_notional,
                    low=0.0,
                    high=budget_pct,
                ),
            ],
        ),
        html.P(
            f"This {fmt.compact_currency(abs(result.carry.theta_annual))}"
            "/year carry cost doesn't change with the quantity dial — "
            "only the percentage of book (and the budget verdict) does, "
            "since a smaller book turns the same dollar cost into a "
            "bigger share.",
            className="plain-language",
        ),
        _efficiency_sentence(
            result,
            convexity_pct=convexity_pct,
            convexity_target_min_pct=ips_config.convexity.target_min_pct,
            vega_sufficiency_pct=vega_sufficiency_pct,
            vega_sufficiency_min_pct=ips_config.vega.sufficiency_min_pct,
        ),
    ]


def _headline_sentence(result: ScenarioResult) -> html.P:
    """Build the always-visible headline scenario sentence."""
    return html.P(
        f"A {fmt.signed_percent(result.spot_pct)} spot move with a "
        f"{result.vol_points:+.2f} vol-point shock nets "
        f"{fmt.signed_compact_currency(result.net)}: the hedge gains "
        f"{fmt.signed_compact_currency(result.hedge_gain)} against an "
        "underlying loss of "
        f"{fmt.signed_compact_currency(result.underlying_loss)} "
        f"on {result.quantity:,.0f} shares.",
        className="plain-language plain-language--headline",
    )


def _verdict_badge(record: RollStatusRecord) -> html.Span:
    """Build a colored verdict badge for one roll status record."""
    modifier = record.verdict.value.lower()
    return html.Span(
        record.verdict.value,
        className=f"verdict-badge verdict-badge--{modifier}",
    )


def _decision_row(record: RollStatusRecord) -> html.Div:
    """Build one row of the DECISIONS list: badge, reason, convexity band.

    An expired leg (#373) gets no band bar. It was excluded from the
    convexity figure before pricing (#362), so rendering the book's band
    against it would imply a reading this leg never contributed to — the
    per-row broadcast #306 is about, at its worst. It gets a short note
    saying so instead. The note deliberately does not restate #375's
    caveat on the cost panel: that one explains why a *number* is smaller,
    this one explains why a *leg* has no recommendation.
    """
    expired = record.verdict is RollVerdict.EXPIRED
    trailing: Component = (
        html.Span(
            "excluded from convexity",
            className="decision-note",
        )
        if expired
        else band_bar(
            value=record.crash_convexity_pct,
            low=record.convexity_target_min_pct,
            high=record.convexity_target_max_pct,
        )
    )
    return html.Div(
        [
            _verdict_badge(record),
            html.Span(
                f"{record.position.option.option_type.value} "
                f"{record.position.option.strike_price:,.0f} — "
                f"{fmt.roll_verdict_reason(record)}",
                className="decision-reason",
            ),
            trailing,
        ],
        className="decision-row",
    )


def _decisions_section(
    records: list[RollStatusRecord],
    plan: MonetizationPlan,
) -> html.Div:
    """Build the DECISIONS section: roll verdicts plus monetization."""
    roll_rows = [_decision_row(record) for record in records]

    if plan.gain_basis == "unknown":
        monetization_children: list[Component] = [
            html.P(
                "No entry price is recorded for the protective puts, so "
                "hedge gain — and this monetization schedule — can't be "
                "evaluated.",
            ),
        ]
    else:
        gain_text = (
            fmt.percent(plan.current_gain_pct)
            if plan.current_gain_pct is not None
            else "n/a"
        )
        monetization_children = [
            html.P(
                f"Current hedge gain: {gain_text} — recommended cumulative "
                f"sell: {fmt.percent(plan.recommended_cumulative_sell_pct)} "
                f"({fmt.compact_currency(plan.value_to_harvest)} to "
                "harvest — the dollar amount recommended to sell at this "
                "gain level).",
            ),
        ]
    if plan.vol_spike_context is not None:
        monetization_children.append(
            html.P(plan.vol_spike_context, className="vol-spike-context"),
        )

    return html.Div(
        [
            html.H2("Decisions"),
            html.P(
                "HOLD — no action needed. MONITOR — watching a metric "
                "approach its threshold. REVIEW — a trigger has fired. "
                "ROLL — time to replace this position. EXPIRED — this leg "
                "is past its maturity: it is gone, not urgent, and is "
                "excluded from the book's convexity.",
                className="verdict-legend",
            ),
            html.P(
                "Each position's roll verdict, and any monetization "
                "already recommended by the IPS schedule at the current "
                "mark.",
                className="plain-language",
            ),
            html.Div(roll_rows, className="decision-list"),
            html.Div(
                monetization_children,
                id="monetization-panel",
                className="monetization-panel",
            ),
        ],
        className="decisions-section",
    )


def _position_row(
    record: RollStatusRecord,
    portfolio: OptionPortfolio,
) -> html.Tr:
    """Build one <tr> of the position-detail table.

    The plain per-leg ledger — "what do I actually hold" — not a second
    copy of the DECISIONS section's risk narrative (verdict/reasons
    already live there).
    """
    position = record.position
    current_value = hedge_value(portfolio, positions=[position])
    return html.Tr(
        [
            html.Td(f"{position.option.strike_price:,.0f}"),
            html.Td(position.option.option_type.value),
            html.Td(position.option.maturity_date.strftime("%Y-%m-%d")),
            html.Td(f"{record.days_to_maturity}d"),
            html.Td(f"{position.quantity:,.0f}"),
            html.Td(
                fmt.signed_compact_currency(current_value),
                title=fmt.signed_currency(current_value),
            ),
        ],
    )


def _position_detail_footer(
    records: list[RollStatusRecord],
    portfolio: OptionPortfolio,
) -> html.Tfoot:
    """Build the total row (#337): quantity gross, value from hedge_value().

    Deliberately a ``<tfoot>``, not another leg row in ``<tbody>`` — the
    issue's own acceptance criterion, so the total reads as a total and
    not a phantom extra leg. Quantity is long/short kept apart rather
    than netted (``gross_quantity``, the same #334 shape as
    ``analysis.position_aging.SignedTotals``) — a book that is long 65
    and short 10 should not read as "55," which is indistinguishable
    from an empty book. Current value comes from ``hedge_value(portfolio)``
    with no ``positions=`` filter — the same helper each row already
    calls per-leg, so the total reconciles leg-for-leg (both exclude an
    expired leg from pricing, per ``hedge_value``'s own contract) rather
    than being a second computation that could drift from the rows above
    it.
    """
    long_contracts, short_contracts = gross_quantity(
        [record.position for record in records],
    )
    if long_contracts and short_contracts:
        quantity_text = f"L {long_contracts:,.0f} · S {short_contracts:,.0f}"
    else:
        quantity_text = f"{long_contracts + short_contracts:,.0f}"

    total_value = hedge_value(portfolio)
    return html.Tfoot(
        html.Tr(
            [
                html.Td("Total", colSpan=4),
                html.Td(quantity_text),
                html.Td(
                    fmt.signed_compact_currency(total_value),
                    title=fmt.signed_currency(total_value),
                ),
            ],
            className="position-detail-total",
        ),
    )


def _position_detail_table(
    records: list[RollStatusRecord],
    portfolio: OptionPortfolio,
) -> html.Details:
    """Build the collapsed position-detail table: the plain per-leg ledger."""
    header = html.Tr(
        [
            html.Th("Strike"),
            html.Th("Type"),
            html.Th("Expiry"),
            html.Th("DTE"),
            html.Th("Quantity"),
            html.Th("Current value"),
        ],
    )
    rows = [_position_row(record, portfolio) for record in records]
    return html.Details(
        [
            html.Summary("Position detail"),
            html.Table(
                [
                    html.Thead(header),
                    html.Tbody(rows),
                    _position_detail_footer(records, portfolio),
                ],
                className="position-detail-table",
            ),
        ],
        className="position-detail",
    )


def _page_footer() -> html.Div:
    """Build the page's own last element: a muted build-version stamp.

    #359: this used to be a ``.plain-language`` sentence sandwiched
    inside ``scenario_explorer``, between the cost panel and the crash
    headline — styled identically to every other financial sentence on
    the page, so it read as one more dense sentence and got skimmed
    past. A field test confirmed the text was genuinely rendering (it
    was visible in a copy-paste of the page) but a human looking at the
    live page still missed it. Placed here — the true last child of the
    page, after ``_position_detail_table``, with its own class rather
    than reusing ``.plain-language`` — it stays in the same place
    whether ``Position detail`` is expanded or collapsed, and its
    styling marks it as metadata rather than portfolio commentary.
    """
    return html.Div(
        html.P(f"Running v{__version__}"),
        className="page-footer",
    )


def _cost_and_protection(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> tuple[CostSection, ProtectionSection]:
    """Cost + protection sections at the IPS crash anchor.

    A plain helper, not itself panel-guarded: :func:`_build_compliance_panel`
    and :func:`_build_scenario_explorer_panel` each call this from *inside*
    their own :func:`~deltadewa.app.panel_guard.safe_render` closure rather
    than sharing one precomputed value, so a raise here degrades only
    whichever panel's own call hit it (#363) — see ``panel_guard``'s module
    docstring for why a shared value would make that isolation fake.
    """
    convexity = ips_config.convexity
    crash_result = compute_crash_convexity(
        portfolio,
        shock=CrashShock.from_ips(convexity),
        ips_convexity=convexity,
    )
    cost_section = build_cost_section(
        carry_metrics=PortfolioAnalyzer(portfolio).calculate_carry_metrics(
            MaturityBuckets.from_ips(ips_config.maturity_buckets),
        ),
        book_notional=(
            abs(portfolio.underlying_quantity) * portfolio.spot_price
        ),
        budget_annual_pct=ips_config.budget.annual_carry_pct,
    )
    protection_section = build_protection_section(crash_result)
    return cost_section, protection_section


def _build_shape_notice_panel(portfolio: OptionPortfolio) -> Component:
    """Build the book-shape notice; degrades independently (#363)."""

    def _build() -> Component:
        return html.Div(
            shape_notice_text(portfolio),
            id="shape-notice",
            className="shape-notice",
        )

    return safe_render(_build)


def _build_compliance_panel(
    app: ProgramDashApp,
    ips_config: IpsConfig,
    portfolio: OptionPortfolio,
) -> Component:
    """Build the IPS compliance strip; degrades independently (#298, #363).

    Computed at the *stored* book and the IPS anchor shock — deliberately
    not from the scenario explorer's dial-driven numbers — and via the
    same section builders + ``build_ips_compliance`` the weekly digest's
    §6 calls, so this line and the digest's Overall verdict read off one
    definition of "compliant".
    """

    def _build() -> Component:
        cost_section, protection_section = _cost_and_protection(
            portfolio,
            ips_config,
        )
        compliance = build_ips_compliance(cost_section, protection_section)
        market_env = assess_market_environment(
            app.market_data,
            ips_config.market_environment,
        )
        return _compliance_strip(
            compliance,
            market_env.data_quality,
            protection_section.excluded_expired_legs,
        )

    return safe_render(_build)


def _build_scenario_explorer_panel(
    app: ProgramDashApp,
    ips_config: IpsConfig,
    portfolio: OptionPortfolio,
) -> Component:
    """Build the crash-scenario explorer (dials, curve, numbers, cost panel).

    Degrades independently of every other /monitor panel (#363): if a
    raise (e.g. #362's crash-skew wing solve) reaches here, this whole
    panel — dials included — is replaced by a degraded notice, but the
    compliance strip, decisions, and position table above and below it
    still render, and ``register_callbacks``' dial callbacks simply have
    no matching component to fire against
    (``suppress_callback_exceptions=True``, ``factory.py``).
    """

    def _build() -> Component:
        convexity = ips_config.convexity
        spot_pct = convexity.crash_scenario_pct
        vol_points = convexity.crash_vol_shock
        quantity = portfolio.underlying_quantity

        result = build_scenario(
            portfolio,
            ips_config,
            spot_pct=spot_pct,
            vol_points=vol_points,
            quantity=quantity,
        )
        curve = build_scenario_curve(
            portfolio,
            ips_config,
            vol_points=vol_points,
            quantity=quantity,
        )
        figure = plot_scenario_curve(
            curve,
            marker_pct=result.spot_pct,
            marker_hedge_value=result.hedge_value_shocked,
            ips_crash_pct=convexity.crash_scenario_pct,
        )
        spot_reading = observe_spot(
            app.market_data,
            symbol=portfolio.get_symbol(),
            book_spot=portfolio.spot_price,
        )
        # Book-level facts for the efficiency sentence's "cheap but too
        # small" combination (#304) — this panel's own copy of the same
        # convexity_pct the compliance strip grades, plus vega
        # sufficiency (design.py's own band-membership call).
        _cost_section, protection_section = _cost_and_protection(
            portfolio,
            ips_config,
        )
        vega_sufficiency_pct = PortfolioAnalyzer(
            portfolio,
        ).calculate_vega_sufficiency_pct()

        return html.Div(
            [
                html.H2(
                    [
                        "Crash scenario",
                        basis_chip("basis: crash-skew (IPS anchor)"),
                    ],
                ),
                _spot_headline(
                    spot_reading,
                    portfolio.get_symbol(),
                    ips_config.market_environment.spot_divergence_warn_pct,
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Label(
                                    "Spot shock",
                                    title=(
                                        "How far SPX falls in this scenario"
                                    ),
                                ),
                                dcc.Slider(
                                    id="spot-slider",
                                    min=_SPOT_SLIDER_MIN,
                                    max=_SPOT_SLIDER_MAX,
                                    step=1.0,
                                    value=spot_pct,
                                    marks=None,
                                    tooltip={
                                        "placement": "bottom",
                                        "always_visible": True,
                                    },
                                ),
                            ],
                            className="dial",
                        ),
                        html.Div(
                            [
                                html.Label(
                                    "Vol shock (points)",
                                    title=(
                                        "Implied volatility increase "
                                        "applied in this scenario, in "
                                        "vol points"
                                    ),
                                ),
                                dcc.Slider(
                                    id="vol-slider",
                                    min=_VOL_SLIDER_MIN,
                                    max=_VOL_SLIDER_MAX,
                                    step=0.01,
                                    value=vol_points,
                                    marks=None,
                                    tooltip={
                                        "placement": "bottom",
                                        "always_visible": True,
                                    },
                                ),
                            ],
                            className="dial",
                        ),
                        html.Div(
                            [
                                html.Label("Underlying quantity"),
                                dcc.Input(
                                    id="qty-input",
                                    type="number",
                                    value=quantity,
                                ),
                            ],
                            className="dial",
                        ),
                        html.Button(
                            "Reset",
                            id="reset-button",
                            n_clicks=0,
                        ),
                    ],
                    className="dial-row",
                ),
                dcc.Graph(id="payoff-curve", figure=figure),
                html.Div(
                    _scenario_numbers(result),
                    id="scenario-numbers",
                    className="scenario-numbers",
                ),
                html.Div(
                    _cost_panel(
                        result,
                        ips_config,
                        convexity_pct=protection_section.convexity_pct,
                        vega_sufficiency_pct=vega_sufficiency_pct,
                    ),
                    id="cost-panel",
                    className="cost-panel",
                ),
                _headline_sentence(result),
            ],
            className="scenario-explorer",
        )

    return safe_render(_build)


def _build_decisions_panel(
    app: ProgramDashApp,
    ips_config: IpsConfig,
    portfolio: OptionPortfolio,
) -> Component:
    """Build the DECISIONS section; degrades independently (#363).

    Computes its own roll-status records and market environment rather
    than sharing :func:`_build_position_detail_panel`'s or
    :func:`_build_compliance_panel`'s copies — see ``panel_guard``'s
    module docstring on why that's what makes the isolation real.
    """

    def _build() -> Component:
        records = evaluate_roll_status(portfolio, ips_config)
        market_env = assess_market_environment(
            app.market_data,
            ips_config.market_environment,
        )
        plan = build_monetization_plan(
            portfolio,
            ips_config,
            market_env=market_env,
        )
        return _decisions_section(records, plan)

    return safe_render(_build)


def _build_position_detail_panel(
    ips_config: IpsConfig,
    portfolio: OptionPortfolio,
) -> Component:
    """Build the position-detail table; degrades independently (#363)."""

    def _build() -> Component:
        records = evaluate_roll_status(portfolio, ips_config)
        return _position_detail_table(records, portfolio)

    return safe_render(_build)


def _build_provenance_panel(
    app: ProgramDashApp,
    ips_config: IpsConfig,
    portfolio: OptionPortfolio,
) -> Component:
    """Build the pricing-input provenance panel; degrades independently.

    #367/#368: reassesses market data and rebuilds the ledger fresh in
    this closure — the same isolation rule ``_build_compliance_panel``
    follows — rather than reusing the chrome's ledger, so a failure here
    cannot take chrome or any other panel down with it.
    """

    def _build() -> Component:
        environment = assess_market_environment(
            app.market_data,
            ips_config.market_environment,
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            ips_config.pricing_inputs,
            as_of=program_trading_date(ips_config.program.timezone).date(),
        )
        return build_provenance_panel(ledger)

    return safe_render(_build)


def render(app: ProgramDashApp) -> html.Div:
    """Build the /monitor page: crash-led headline, decisions, position detail.

    Every policy-dependent panel needs ``app.ips_config`` — when it's
    ``None`` there is no crash anchor to render around, so the whole
    page becomes a single "no IPS policy loaded" state rather than
    fabricating one.

    Each panel below is built by its own
    :func:`~deltadewa.app.panel_guard.safe_render`-wrapped function
    (#363): a raise in any one panel's analysis calls degrades that
    panel to a visible notice and leaves the rest of the page intact,
    where before this the whole page returned HTTP 500.
    """
    if app.ips_config is None:
        return _no_ips_layout(app.program_state)

    ips_config = app.ips_config
    portfolio = app.program_state.portfolio

    # #357: each anchor wraps the panel's already-built (safe_render'd)
    # output rather than living inside that closure — see section_nav's
    # module docstring's /monitor case. A raise inside one of these still
    # degrades only that panel; the anchor (and the TOC link to it)
    # survives regardless.
    return html.Div(
        [
            html.H1("Monitor", id=TOP_ANCHOR_ID),
            build_section_nav(
                [SectionGroup(label=None, anchor_id=None, sections=_SECTIONS)],
            ),
            _build_shape_notice_panel(portfolio),
            section_wrapper(
                _SECTION_COMPLIANCE,
                _build_compliance_panel(app, ips_config, portfolio),
            ),
            section_wrapper(
                _SECTION_CRASH_SCENARIO,
                _build_scenario_explorer_panel(app, ips_config, portfolio),
            ),
            section_wrapper(
                _SECTION_DECISIONS,
                _build_decisions_panel(app, ips_config, portfolio),
            ),
            section_wrapper(
                _SECTION_POSITION_DETAIL,
                _build_position_detail_panel(ips_config, portfolio),
            ),
            section_wrapper(
                _SECTION_PROVENANCE,
                _build_provenance_panel(app, ips_config, portfolio),
            ),
            _page_footer(),
        ],
        className="page page-monitor",
    )


def register_callbacks(app: ProgramDashApp) -> None:
    """Wire the scenario explorer's three dials to the curve/numbers/cost panel.

    No ``ProgramState`` mutator is ever called here — every dial value
    is scenario-local. The quantity dial in particular never gets
    written back to ``portfolio.underlying_quantity``.
    """
    ips_config = app.ips_config
    if ips_config is None:
        return

    @app.callback(
        Output("payoff-curve", "figure"),
        Input("vol-slider", "value"),
        Input("qty-input", "value"),
        prevent_initial_call=True,
    )
    def _update_curve(vol_points: float, quantity: float) -> Patch:
        curve = build_scenario_curve(
            app.program_state.portfolio,
            ips_config,
            vol_points=vol_points,
            quantity=quantity,
        )

        patched = Patch()
        patched["data"][0]["y"] = [point.net for point in curve]
        patched["data"][1]["y"] = [point.hedge_value for point in curve]
        patched["data"][2]["y"] = [point.underlying_loss for point in curve]
        patched["data"][3]["y"] = [point.offset_ratio for point in curve]
        return patched

    @app.callback(
        Output("payoff-curve", "figure", allow_duplicate=True),
        Output("scenario-numbers", "children"),
        Output("cost-panel", "children"),
        Input("spot-slider", "value"),
        Input("vol-slider", "value"),
        Input("qty-input", "value"),
        prevent_initial_call=True,
    )
    def _update_scenario(
        spot_pct: float,
        vol_points: float,
        quantity: float,
    ) -> tuple[Patch, list[Component], list[Component]]:
        portfolio = app.program_state.portfolio
        result = build_scenario(
            portfolio,
            ips_config,
            spot_pct=spot_pct,
            vol_points=vol_points,
            quantity=quantity,
        )
        # Book-level facts for the efficiency sentence's "cheap but too
        # small" combination (#304) — read fresh from the live portfolio
        # on every dial move (never cached across callback firings), but
        # via the single-shock convexity call (not #298's full 51-point
        # compute_crash_convexity): unaffected by any of the three dials,
        # so it would be identical work repeated on every keystroke.
        convexity_pct = PortfolioAnalyzer(
            portfolio,
        ).calculate_crash_convexity_pct(
            CrashShock.from_ips(ips_config.convexity)
        )
        vega_sufficiency_pct = PortfolioAnalyzer(
            portfolio,
        ).calculate_vega_sufficiency_pct()

        patched = Patch()
        patched["data"][4]["x"] = [result.spot_pct]
        patched["data"][4]["y"] = [result.hedge_value_shocked]
        return (
            patched,
            _scenario_numbers(result),
            _cost_panel(
                result,
                ips_config,
                convexity_pct=convexity_pct,
                vega_sufficiency_pct=vega_sufficiency_pct,
            ),
        )

    @app.callback(
        Output("spot-slider", "value"),
        Output("vol-slider", "value"),
        Output("qty-input", "value"),
        Input("reset-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def _reset_dials(_n_clicks: int) -> tuple[float, float, float]:
        return (
            ips_config.convexity.crash_scenario_pct,
            ips_config.convexity.crash_vol_shock,
            app.program_state.portfolio.underlying_quantity,
        )
