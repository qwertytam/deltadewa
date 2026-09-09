"""The IPS compliance strip (#298) — one definition, shown on two pages.

``/monitor``'s compliance strip and ``/design``'s PLANNING-zone compliance
panel (Batch 8a.4) both need the same thing: the three
``reporting.program_report`` sections — carry, crash convexity, vega
sufficiency (#409) — computed at the IPS crash anchor for the *current*
book, graded by ``build_ips_compliance``, and rendered as one PASS/FAIL
line. Each page used to build its own copy of the section-computation glue
(``monitor.py``'s old ``_compliance_sections``); a second copy is exactly
the class of drift #298/#409's single-compliance rule exists to prevent,
so both pages now call the same three functions here.

``reporting.program_report`` itself stays repricing-free by design (see
its own module docstring) — this module is where the actual
``PortfolioAnalyzer``/``compute_crash_convexity`` calls happen; their
results are handed to program_report's section builders, which do no
further computation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import html
from dash.development.base_component import Component

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_payoff import compute_crash_convexity
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.analysis.market_environment import DataQuality
from deltadewa.analysis.maturity import MaturityBuckets
from deltadewa.reporting.program_report import (
    CostSection,
    ProtectionSection,
    VegaSection,
    build_cost_section,
    build_protection_section,
    build_vega_section,
    expired_legs_caveat,
)

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.reporting.program_report import IpsComplianceSection

# Mirrors chrome._BANNER_QUALITIES and program_report._STALE_OR_WORSE
# locally rather than importing either module-private name — the
# established convention (see weekly_snapshot.py's own copy) for a set
# every module that reads DataQuality needs but none owns.
_STALE_OR_WORSE: frozenset[DataQuality] = frozenset(
    {DataQuality.STALE, DataQuality.STATIC, DataQuality.UNAVAILABLE},
)


def compliance_sections_at_ips_anchor(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> tuple[CostSection, ProtectionSection, VegaSection]:
    """Build the three IPS-compliance sections for *portfolio* right now.

    One per standing IPS band — carry, crash convexity, vega sufficiency
    (#409) — packaged exactly as ``build_ips_compliance`` consumes them,
    so every caller grades the same book off the same three inputs.
    Priced at the IPS crash anchor (``CrashShock.from_ips``), the same
    basis ``/monitor``'s gauge and ``/design``'s PLANNING zone both use.
    """
    convexity = ips_config.convexity
    crash_result = compute_crash_convexity(
        portfolio,
        shock=CrashShock.from_ips(convexity),
        ips_convexity=convexity,
    )
    analyzer = PortfolioAnalyzer(portfolio)
    cost_section = build_cost_section(
        carry_metrics=analyzer.calculate_carry_metrics(
            MaturityBuckets.from_ips(ips_config.maturity_buckets),
        ),
        book_notional=(
            abs(portfolio.underlying_quantity) * portfolio.spot_price
        ),
        budget_annual_pct=ips_config.budget.annual_carry_pct,
    )
    protection_section = build_protection_section(crash_result)
    vega_section = build_vega_section(
        sufficiency_pct=analyzer.calculate_vega_sufficiency_pct(),
        ips_vega=ips_config.vega,
    )
    return cost_section, protection_section, vega_section


def metric_list(compliance: IpsComplianceSection) -> str:
    """Name every metric the compliance section actually graded (#409).

    Lower-cased and comma-joined with a trailing "and", e.g. ``"carry
    cost, crash convexity and vega sufficiency"``. The PASS line is built
    from this rather than from a hand-written list of metric names, so a
    row added to ``build_ips_compliance`` cannot leave the sentence
    describing a narrower question than the verdict answers.

    Metric names are lower-cased only at their first character — "IPS" and
    similar stay as written — because the row labels are title-cased for a
    table header and this sentence is prose.
    """
    names = [row.metric[:1].lower() + row.metric[1:] for row in compliance.rows]
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def compliance_strip(
    compliance: IpsComplianceSection,
    data_quality: DataQuality,
    excluded_expired: tuple[str, ...] = (),
) -> html.Div:
    """Build the one-line IPS compliance strip (#298).

    The program's single definition of "compliant" is
    ``reporting.program_report.build_ips_compliance`` — the same function
    the weekly digest's §6 calls. This renders its result; it never
    re-derives pass/fail from a band comparison of its own, so this line,
    the digest's Overall verdict, and every page that calls it cannot
    silently disagree.

    Callers build ``compliance`` from the *stored* book at the IPS
    anchor via :func:`compliance_sections_at_ips_anchor` — never from a
    scenario explorer's dial-driven numbers — so this line states a fact
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
        ``id="compliance-strip"`` — a FAIL book cannot render a page
        carrying this without this id present
        (``tests/test_app/test_monitor.py``'s structural guard asserts
        exactly that, rather than pinning a string).

    """
    if compliance.all_pass:
        # The metrics are named from the rows themselves, never spelled out
        # here (#409). The old wording enumerated "carry and crash
        # convexity" as a literal, which stayed narrowly true while
        # ``build_ips_compliance`` silently omitted a third banded IPS
        # metric — a reader taking PASS to mean "in policy" had no way to
        # see the sentence was describing a smaller question than they
        # were asking. Deriving it means the line cannot narrow again
        # without the row disappearing too.
        text = (
            f"IPS compliance: PASS — {metric_list(compliance)} all "
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
