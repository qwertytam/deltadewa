"""Batch 8a.2 / N3 (#409): every IPS band is classified, and none is lost.

``build_ips_compliance`` documents itself as "the program's single
definition of compliant" (#298), and ``/monitor``'s strip and the weekly
digest's §6 both render its verdict rather than grading anything
themselves. Vega sufficiency was nevertheless missing from it for two
milestones: the reading was computed in ``analysis/health.py`` and rendered
on ``/design``'s sizing panel and in ``/monitor``'s efficiency sentence, and
graded against policy in none of them — so a book below the IPS floor read
``PASS``. Nothing failed; the question was simply never asked.

A test that asserted "there are three rows" would not have caught it, and
will not catch the next one. So this module inventories **every threshold
the IPS defines** and requires each to be classified:

``COMPLIANCE``
    A standing constraint on the book's *shape* — a reader can only answer
    it by resizing or restructuring. These are exactly the rows
    ``build_ips_compliance`` must produce, and the test below asserts that
    correspondence in both directions.

``TRIGGER``
    An event threshold: "this has happened, act." Graded per tranche by
    ``analysis/roll_status.py`` or book-level by
    ``analysis/hedge_triggers.py``, and surfaced on its own panel. A fired
    trigger is not a policy breach.

``INTERPRETATION``
    Labels a reading without a pass/fail (the hedge-efficiency band, the
    market-environment regimes). The efficiency band is the clearest case:
    it is *derived* from carry and convexity, both already graded above, so
    a row for it would double-count two rows that are already there.

``NOT_A_BAND``
    A scalar input or a switch, not a threshold at all — the crash scenario
    depth, the portfolio beta, a boolean.

Adding a field to any IPS section fails
:func:`test_every_ips_threshold_is_classified` until someone writes down
which kind it is, which is the whole point: the classification is a
decision, and #409 happened because one was made implicitly.
"""

from __future__ import annotations

import dataclasses
from enum import StrEnum
from typing import Final

import pytest

from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMarketEnvironment,
    IpsMaturityBuckets,
    IpsMaturitySelection,
    IpsMonetization,
    IpsPricing,
    IpsPricingInputs,
    IpsProgram,
    IpsSizing,
    IpsTriggers,
    IpsVega,
)
from deltadewa.reporting.program_report import (
    CostSection,
    IpsComplianceSection,
    ProtectionSection,
    build_ips_compliance,
    build_vega_section,
)


class BandKind(StrEnum):
    """How the program treats one IPS threshold."""

    COMPLIANCE = "COMPLIANCE"
    TRIGGER = "TRIGGER"
    INTERPRETATION = "INTERPRETATION"
    NOT_A_BAND = "NOT_A_BAND"


#: ``"<section>.<field>" -> BandKind`` for every field on every IPS section.
#: Sections whose fields are all inputs rather than thresholds
#: (``program``, ``pricing``, ``monetization``) are covered by
#: ``_SECTIONS_WITHOUT_THRESHOLDS`` below rather than enumerated here.
_CLASSIFICATION: Final[dict[str, BandKind]] = {
    # ── The three standing constraints on the book's shape ────────────
    "budget.annual_carry_pct": BandKind.COMPLIANCE,
    "convexity.target_min_pct": BandKind.COMPLIANCE,
    "convexity.target_max_pct": BandKind.COMPLIANCE,
    "vega.sufficiency_min_pct": BandKind.COMPLIANCE,
    "vega.sufficiency_max_pct": BandKind.COMPLIANCE,
    # ── Event thresholds ──────────────────────────────────────────────
    # Handbook Rule 2, graded per tranche by roll_status and book-level
    # by hedge_triggers (#297, #412).
    "triggers.rally_monitor_pct": BandKind.TRIGGER,
    "triggers.rally_review_pct": BandKind.TRIGGER,
    "triggers.rally_action_pct": BandKind.TRIGGER,
    "triggers.rally_urgent_pct": BandKind.TRIGGER,
    # Net delta vs target. The closest thing here to a standing shape
    # constraint, and deliberately still a trigger: it lives under
    # `triggers:`, is surfaced as a rebalance trigger, and is remedied by
    # a hedge adjustment rather than by resizing the programme. Recorded
    # as a decision, not an oversight (Batch 8a.2 / N3).
    "triggers.target_delta_ratio_pct": BandKind.TRIGGER,
    "triggers.delta_ratio_deviation_warn_pct": BandKind.TRIGGER,
    "triggers.delta_ratio_deviation_action_pct": BandKind.TRIGGER,
    # Handbook Rule 1, the time-based roll.
    "triggers.roll_at_months_remaining": BandKind.TRIGGER,
    "triggers.roll_review_buffer": BandKind.TRIGGER,
    "triggers.expiry_urgent_days": BandKind.TRIGGER,
    "triggers.expiry_soon_days": BandKind.TRIGGER,
    # Carry's per-trigger reading. Distinct from budget.annual_carry_pct
    # above, which is the standing ceiling the compliance row grades.
    "triggers.theta_cost_excellent_pct": BandKind.TRIGGER,
    "triggers.theta_cost_acceptable_pct": BandKind.TRIGGER,
    "triggers.gamma_drift_moderate_pct": BandKind.TRIGGER,
    "triggers.gamma_drift_high_pct": BandKind.TRIGGER,
    # The gamma-runway threshold, graded by health.calculate_convexity_
    # cliff_days. Unrelated to roll_at_months_remaining despite the
    # numeric coincidence they were decoupled from in #338.
    "convexity.cliff_threshold_days": BandKind.TRIGGER,
    "convexity.cliff_review_days": BandKind.TRIGGER,
    "convexity.cliff_urgent_days": BandKind.TRIGGER,
    # The IPS's own drawdown tolerance: a stop, not a book-shape gate.
    "drawdown.max_tolerance_pct": BandKind.TRIGGER,
    # Review cadences for the four hand-entered pricing inputs (#367).
    # They grade an input's freshness, never the book's policy standing —
    # the provenance ledger owns them and reports separately.
    "pricing_inputs.spot_max_age_days": BandKind.TRIGGER,
    "pricing_inputs.volatility_max_age_days": BandKind.TRIGGER,
    "pricing_inputs.risk_free_rate_max_age_days": BandKind.TRIGGER,
    "pricing_inputs.dividend_yield_max_age_days": BandKind.TRIGGER,
    # ── Labels, not verdicts ──────────────────────────────────────────
    # Derived from carry and convexity, both graded above — a compliance
    # row here would double-count them (#304's "cheap but too small" is
    # the sentence that carries this reading instead).
    "convexity.efficiency_min_ratio": BandKind.INTERPRETATION,
    "convexity.efficiency_max_ratio": BandKind.INTERPRETATION,
    "market_environment.vol_regime_low": BandKind.INTERPRETATION,
    "market_environment.vol_regime_high": BandKind.INTERPRETATION,
    "market_environment.skew_low_pctile": BandKind.INTERPRETATION,
    "market_environment.skew_high_pctile": BandKind.INTERPRETATION,
    "market_environment.term_contango_tolerance": BandKind.INTERPRETATION,
    "market_environment.vix_very_high": BandKind.INTERPRETATION,
    "market_environment.vix_caution": BandKind.INTERPRETATION,
    "market_environment.vix_low": BandKind.INTERPRETATION,
    "market_environment.spot_divergence_warn_pct": BandKind.INTERPRETATION,
    "maturity_selection.entry_tenor_years": BandKind.INTERPRETATION,
    "maturity_selection.maintain_min_years": BandKind.INTERPRETATION,
    "maturity_selection.maintain_max_years": BandKind.INTERPRETATION,
    # ── Inputs and switches, not thresholds ───────────────────────────
    "convexity.crash_scenario_pct": BandKind.NOT_A_BAND,
    "convexity.crash_vol_shock": BandKind.NOT_A_BAND,
    "convexity.skew_steepening": BandKind.NOT_A_BAND,
    "convexity.skew_reference_delta": BandKind.NOT_A_BAND,
    "convexity.crash_floor_reported": BandKind.NOT_A_BAND,
    "sizing.portfolio_beta": BandKind.NOT_A_BAND,
    "maturity_buckets.edges_days": BandKind.NOT_A_BAND,
    "market_environment.data_ttl_minutes": BandKind.NOT_A_BAND,
}

#: IPS sections that define no thresholds at all — names, an exercise
#: style, the monetization ladder. Listed so the sweep below is provably
#: over *every* section rather than a chosen few.
_SECTIONS_WITHOUT_THRESHOLDS: Final[frozenset[str]] = frozenset(
    {"program", "pricing", "monetization"},
)

#: The compliance rows ``build_ips_compliance`` must produce, in order.
#: The convexity row's label carries the shock depth, so it is matched by
#: prefix rather than pinned to a particular percentage.
_EXPECTED_COMPLIANCE_METRICS: Final[tuple[str, ...]] = (
    "Annual carry cost",
    "Crash convexity",
    "Vega sufficiency",
)


def _ips_section_types() -> dict[str, type]:
    """Every section on ``IpsConfig``, by field name.

    Read off the dataclass rather than listed, so a section added to the
    IPS joins the sweep automatically. ``defaulted_sections`` (#309) is
    bookkeeping about *how the file loaded* rather than policy the book is
    graded on, so it is skipped by name.
    """
    bookkeeping = {"defaulted_sections"}
    sections: dict[str, type] = {}
    known = {
        "program": IpsProgram,
        "pricing": IpsPricing,
        "budget": IpsBudget,
        "convexity": IpsConvexity,
        "drawdown": IpsDrawdown,
        "triggers": IpsTriggers,
        "monetization": IpsMonetization,
        "market_environment": IpsMarketEnvironment,
        "sizing": IpsSizing,
        "vega": IpsVega,
        "maturity_buckets": IpsMaturityBuckets,
        "pricing_inputs": IpsPricingInputs,
        "maturity_selection": IpsMaturitySelection,
    }
    for field in dataclasses.fields(IpsConfig):
        if field.name in bookkeeping:
            continue
        assert field.name in known, (
            f"IpsConfig gained a section {field.name!r} — add it to this"
            " test's `known` map and classify its fields."
        )
        sections[field.name] = known[field.name]
    return sections


def _all_threshold_keys() -> set[str]:
    """``"<section>.<field>"`` for every field on every threshold section."""
    keys: set[str] = set()
    for name, section_type in _ips_section_types().items():
        if name in _SECTIONS_WITHOUT_THRESHOLDS:
            continue
        keys |= {f"{name}.{f.name}" for f in dataclasses.fields(section_type)}
    return keys


def test_every_ips_threshold_is_classified() -> None:
    """No IPS field may exist without a decision about how it is graded.

    This is the guard #409 needed: a banded metric that nobody classified
    is a metric nobody noticed was ungraded.
    """
    actual = _all_threshold_keys()
    classified = set(_CLASSIFICATION)

    unclassified = sorted(actual - classified)
    assert not unclassified, (
        "IPS fields with no BandKind — classify each as COMPLIANCE,"
        f" TRIGGER, INTERPRETATION or NOT_A_BAND: {unclassified}"
    )

    stale = sorted(classified - actual)
    assert not stale, f"classified IPS fields that no longer exist: {stale}"


def test_compliance_rows_are_exactly_the_compliance_bands() -> None:
    """The COMPLIANCE class and ``build_ips_compliance``'s rows must match.

    Both directions. One row per constraint, and no constraint without a
    row — which is the invariant vega sufficiency broke.
    """
    compliance_sections = {
        key.split(".", 1)[0]
        for key, kind in _CLASSIFICATION.items()
        if kind is BandKind.COMPLIANCE
    }
    assert compliance_sections == {"budget", "convexity", "vega"}

    rows = build_ips_compliance(
        _passing_cost(),
        _passing_protection(),
        build_vega_section(sufficiency_pct=2.5, ips_vega=IpsVega()),
    ).rows

    assert len(rows) == len(_EXPECTED_COMPLIANCE_METRICS)
    for row, expected in zip(rows, _EXPECTED_COMPLIANCE_METRICS, strict=True):
        assert row.metric.startswith(expected)


# ── The vega row's own behaviour ──────────────────────────────────────────


def _passing_cost() -> CostSection:
    return CostSection(
        total_theta_annual=-50_000.0,
        book_notional=20_000_000.0,
        carry_pct_of_notional=0.25,
        budget_annual_pct=1.0,
        within_budget=True,
    )


def _passing_protection() -> ProtectionSection:
    return ProtectionSection(
        payoff_vs_premium=8.5,
        ips_crash_pct=-25.0,
        convexity_pct=15.0,
        target_min_pct=10.0,
        target_max_pct=20.0,
        meets_target=True,
        premium_paid=300_000.0,
        premium_basis="paid",
    )


class TestVegaBreachAlone:
    """A vega breach alone must fail the whole verdict (#409).

    The reported case, inverted into a test: carry and convexity both in
    band, vega below the floor. Before this batch that book read
    ``all_pass=True`` while the efficiency sentence on the same panel said
    "Cheap, but too small."
    """

    @staticmethod
    def _compliance(sufficiency_pct: float | None) -> IpsComplianceSection:
        return build_ips_compliance(
            _passing_cost(),
            _passing_protection(),
            build_vega_section(
                sufficiency_pct=sufficiency_pct,
                ips_vega=IpsVega(
                    sufficiency_min_pct=1.5,
                    sufficiency_max_pct=4.0,
                ),
            ),
        )

    def test_below_the_floor_fails_the_book(self) -> None:
        compliance = self._compliance(0.8)

        assert compliance.all_pass is False
        vega_row = compliance.rows[-1]
        assert vega_row.metric == "Vega sufficiency"
        assert vega_row.passes is False
        assert vega_row.actual == "0.8%"
        assert vega_row.action is not None
        assert "below the IPS floor" in vega_row.action

    def test_above_the_ceiling_fails_with_the_opposite_remedy(self) -> None:
        """Over-hedged on vega is a different problem, not the same one."""
        vega_row = self._compliance(6.0).rows[-1]

        assert vega_row.passes is False
        assert vega_row.action is not None
        assert "above the IPS ceiling" in vega_row.action

    def test_in_band_passes_and_carries_no_action(self) -> None:
        """#307's rule: ``action`` is None exactly when ``passes``."""
        compliance = self._compliance(2.5)

        assert compliance.all_pass is True
        assert compliance.rows[-1].passes is True
        assert compliance.rows[-1].action is None

    @pytest.mark.parametrize("edge", [1.5, 4.0])
    def test_the_band_edges_are_inclusive(self, edge: float) -> None:
        """Matches ``ProtectionSection.meets_target``'s own convention."""
        assert self._compliance(edge).rows[-1].passes is True

    def test_an_unmeasured_reading_is_reported_as_such(self) -> None:
        """Not a breach — an em-dash and a reason, like the convexity row.

        A ``None`` reading grading ``False`` with a "below the floor"
        action would invent a breach out of a missing measurement, which
        is the failure mode ``leg_convexity_contribution_pct`` avoids by
        returning ``None`` rather than ``0.0`` (#362).
        """
        vega_row = self._compliance(None).rows[-1]

        assert vega_row.actual == "—"
        assert vega_row.action is not None
        assert "could not be measured" in vega_row.action
