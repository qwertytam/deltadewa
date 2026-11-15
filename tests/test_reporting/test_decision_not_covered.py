"""A verdict never renders beside a failing metric without saying so (#465).

A digest once read a vega breach in its headline and ``Verdict: MAINTAIN`` in
section 7. Both were true: the decision matrix grades crash convexity against
the IPS band and nothing else, and ``MAINTAIN`` was behaving as documented. But
a reader who goes straight to the decision is told to do nothing, weeks into a
breach whose recommended action is to add hedge.

Decided (option 2, 2026-11-14): the verdict's logic does not change.
``DecisionResult`` carries the failing or unmeasured metrics it did not grade,
read from the one compliance definition (#298), and every surface that
renders the verdict renders them beside it. Feeding compliance into the
verdict (option 3) is the decided target, filed separately.

Every reading, run length and date used as a fixture here is invented to
exercise the rule; none is a figure from a real digest.

The surfaces that render a decision-matrix verdict are the digest's section 7
(markdown and HTML) and ``/design``'s market-environment panel. ``/monitor``'s
Decisions panel renders roll verdicts and monetization, not this verdict; that
is pinned below, so adding the verdict there fails and says to add the caveat.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from deltadewa.analysis.decision_matrix import (
    NOT_COVERED_PREFIX,
    DecisionVerdict,
    UncoveredMetric,
    UncoveredStatus,
    decision_matrix,
    describe_not_covered,
    entry_timing_tree,
)
from deltadewa.analysis.market_environment import DataQuality
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.app import compliance as app_compliance
from deltadewa.app.import_portfolio import main as import_portfolio_main
from deltadewa.app.pages import monitor
from deltadewa.app.pages.design.planning import market_env as design_panel
from deltadewa.ips_config import IpsConfig, IpsVega
from deltadewa.reporting.program_report import (
    IpsComplianceRow,
    IpsComplianceSection,
    build_ips_compliance,
    metrics_outside_the_verdict,
    render_html_body,
    render_markdown,
)
from deltadewa.reporting.weekly_report import (
    build_weekly_digest,
    main,
    render_weekly_digest_html,
    render_weekly_digest_markdown,
)
from deltadewa.reporting.weekly_snapshot import WeeklySnapshot

from ..test_analysis.test_roll_by import _book, _convexity, _ips, _put
from ..test_app.test_convexity_surfaces_agree import _env
from .test_weekly_report import (
    _AS_OF,
    _EXAMPLE_IPS_YAML,
    _EXAMPLE_PORTFOLIO,
    _make_decision,
    _make_report,
    _prior_snapshot,
)

if TYPE_CHECKING:
    from pathlib import Path

_EN_DASH = "\N{EN DASH}"
_VEGA = "Vega sufficiency"
_VEGA_TARGET = f"1.5%{_EN_DASH}4.0% per +10 vol pts"
_VEGA_FAIL = UncoveredMetric(
    metric=_VEGA,
    status=UncoveredStatus.FAIL,
    actual="1.1%",
    target=_VEGA_TARGET,
)
_CARRY = "Annual carry cost"


def _row(
    metric: str,
    passes: bool | None,
    *,
    graded: bool = False,
) -> IpsComplianceRow:
    return IpsComplianceRow(
        metric=metric,
        target="a band",
        actual="a reading" if passes is not None else "—",
        passes=passes,
        graded_by_decision=graded,
    )


def _compliance(*rows: IpsComplianceRow) -> IpsComplianceSection:
    return IpsComplianceSection(
        rows=rows,
        all_pass=all(r.passes is True for r in rows),
    )


class TestWhichRowsTheVerdictDidNotGrade:
    """Read off the compliance rows; nothing here compares a reading."""

    def test_a_failing_row_the_verdict_does_not_read_is_listed(self) -> None:
        compliance = _compliance(
            _row(_CARRY, True),
            _row("Crash convexity (-25% shock)", True, graded=True),
            _row(_VEGA, False),
        )

        (metric,) = metrics_outside_the_verdict(compliance)

        assert metric.metric == _VEGA
        assert metric.status is UncoveredStatus.FAIL

    def test_an_unmeasured_row_is_listed_as_unmeasured_not_failing(
        self,
    ) -> None:
        compliance = _compliance(
            _row(_CARRY, True),
            _row("Crash convexity (-25% shock)", True, graded=True),
            _row(_VEGA, None),
        )

        (metric,) = metrics_outside_the_verdict(compliance)

        assert metric.status is UncoveredStatus.UNMEASURED
        assert metric.weeks is None

    def test_a_failing_carry_row_is_listed_too(self) -> None:
        """Carry over budget beside MAINTAIN is the same contradiction."""
        compliance = _compliance(
            _row(_CARRY, False),
            _row("Crash convexity (-25% shock)", True, graded=True),
            _row(_VEGA, True),
        )

        assert [m.metric for m in metrics_outside_the_verdict(compliance)] == [
            _CARRY,
        ]

    def test_the_row_the_verdict_is_graded_on_is_not_listed(self) -> None:
        """The verdict and its rationale already speak for convexity."""
        compliance = _compliance(
            _row(_CARRY, True),
            _row("Crash convexity (-25% shock)", False, graded=True),
            _row(_VEGA, True),
        )

        assert metrics_outside_the_verdict(compliance) == ()

    def test_a_passing_book_lists_nothing(self) -> None:
        compliance = _compliance(
            _row(_CARRY, True),
            _row("Crash convexity (-25% shock)", True, graded=True),
            _row(_VEGA, True),
        )

        assert metrics_outside_the_verdict(compliance) == ()

    def test_the_real_compliance_builder_marks_convexity_and_only_convexity(
        self,
    ) -> None:
        """A new row is "not covered" by default, not by remembering it."""
        sections = app_compliance.compliance_sections_at_ips_anchor(
            _book(_put(days=400)),
            _ips(),
        )
        compliance = build_ips_compliance(*sections)

        graded = [r.metric for r in compliance.rows if r.graded_by_decision]

        assert len(graded) == 1
        assert graded[0].startswith("Crash convexity")


class TestTheSentence:
    def test_one_failing_metric_with_its_run(self) -> None:
        metric = replace(_VEGA_FAIL, weeks=7)

        sentence = describe_not_covered([metric], see="§6")

        assert sentence == (
            f"Not covered by this verdict: {_VEGA} FAIL "
            f"(1.1% vs {_VEGA_TARGET}, 7th week) — see §6."
        )

    def test_without_a_history_there_is_no_week_count(self) -> None:
        sentence = describe_not_covered([_VEGA_FAIL], see="§6")

        assert sentence is not None
        assert "week" not in sentence
        assert f"{_VEGA} FAIL (1.1% vs {_VEGA_TARGET})" in sentence

    def test_an_unmeasured_metric_says_so_and_is_not_called_a_failure(
        self,
    ) -> None:
        metric = UncoveredMetric(
            metric=_VEGA,
            status=UncoveredStatus.UNMEASURED,
            actual="—",
            target=_VEGA_TARGET,
        )

        sentence = describe_not_covered([metric], see="§6")

        assert sentence == (
            f"{NOT_COVERED_PREFIX} {_VEGA} not measured — see §6."
        )
        assert "FAIL" not in sentence

    def test_several_metrics_are_one_sentence(self) -> None:
        carry = UncoveredMetric(
            metric=_CARRY,
            status=UncoveredStatus.FAIL,
            actual="1.15%",
            target="≤ 1.00% of notional",
        )

        sentence = describe_not_covered([carry, _VEGA_FAIL], see="§6")

        assert sentence is not None
        assert sentence.count(NOT_COVERED_PREFIX) == 1
        assert "; " in sentence
        assert sentence.index(_CARRY) < sentence.index(_VEGA)

    def test_nothing_uncovered_says_nothing(self) -> None:
        assert describe_not_covered([], see="§6") is None


class TestTheDecisionCarriesWhatItDidNotGrade:
    """Built where ``DecisionResult`` is built, and not changed by it."""

    def test_the_metrics_travel_on_the_result(self) -> None:
        result = decision_matrix(
            _env(),
            convexity_now_pct=15.0,
            ips_convexity=_ips().convexity,
            not_covered=[_VEGA_FAIL],
        )

        assert result.verdict is DecisionVerdict.MAINTAIN
        assert result.not_covered == (_VEGA_FAIL,)

    def test_the_verdict_does_not_change(self) -> None:
        """Option 2: the logic is convexity-only, with or without the rest."""
        convexity = _ips().convexity
        for reading in (5.0, 15.0, 25.0, None):
            bare = decision_matrix(
                _env(),
                convexity_now_pct=reading,
                ips_convexity=convexity,
                not_covered=(),
            )
            caveated = decision_matrix(
                _env(),
                convexity_now_pct=reading,
                ips_convexity=convexity,
                not_covered=[_VEGA_FAIL],
            )

            assert caveated.verdict is bare.verdict
            assert caveated.rationale == bare.rationale
            assert caveated.hedge_adequacy is bare.hedge_adequacy

    @pytest.mark.parametrize(
        "reading",
        [5.0, 15.0, 25.0, None],
        ids=["under", "adequate", "over", "unmeasured"],
    )
    def test_every_return_path_carries_it(self, reading: float | None) -> None:
        """INSUFFICIENT_DATA paths too: no early return drops the field."""
        for quality in (DataQuality.LIVE, DataQuality.STALE):
            env = replace(_env(), data_quality=quality)
            result = decision_matrix(
                env,
                convexity_now_pct=reading,
                ips_convexity=_ips().convexity,
                not_covered=[_VEGA_FAIL],
            )
            assert result.not_covered == (_VEGA_FAIL,), (reading, quality)

        no_cost = replace(_env(), hedge_cost_verdict=None)
        result = decision_matrix(
            no_cost,
            convexity_now_pct=reading,
            ips_convexity=_ips().convexity,
            not_covered=[_VEGA_FAIL],
        )
        assert result.not_covered == (_VEGA_FAIL,)


def _example_ips_text(*, vega_floor: float | None = None) -> str:
    """The example IPS, with a carry budget its example book fits inside.

    The example book's carry (1.40%) is over the shipped 1.0% budget, which
    is a real failing row and is rightly listed beside the verdict too. These
    tests are about one metric at a time, so the budget is widened and carry
    passes; ``vega_floor`` raises the vega floor above what the book reads.
    """
    text = _EXAMPLE_IPS_YAML.read_text(encoding="utf-8")
    assert text.count("annual_carry_pct: 1.0") == 1
    text = text.replace("annual_carry_pct: 1.0", "annual_carry_pct: 9.0")
    if vega_floor is not None:
        assert text.count("sufficiency_min_pct: 1.5") == 1
        text = text.replace(
            "sufficiency_min_pct: 1.5",
            f"sufficiency_min_pct: {vega_floor}",
        )
    return text


class TestTheDigestPrintsItBesideTheVerdict:
    """Section 7, in the markdown and in the HTML, end to end."""

    def test_a_run_of_the_real_cli_prints_the_caveat_in_both_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))
        ips_path = tmp_path / "ips.yaml"
        ips_path.write_text(_example_ips_text(vega_floor=3.5), encoding="utf-8")
        assert (
            import_portfolio_main(
                [
                    str(_EXAMPLE_PORTFOLIO),
                    "--export-dir",
                    str(tmp_path),
                    "--ips-path",
                    str(ips_path),
                ],
            )
            == 0
        )

        assert (
            main(
                [
                    "--export-dir",
                    str(tmp_path),
                    "--ips-path",
                    str(ips_path),
                    "--as-of",
                    "2026-08-05",
                ],
            )
            == 0
        )

        weekly = tmp_path / "reports" / "weekly"
        markdown = (weekly / "digest-2026-08-05.md").read_text(encoding="utf-8")
        html = (weekly / "digest-2026-08-05.html").read_text(encoding="utf-8")
        for text in (markdown, html):
            assert "7. Decision" in text
            assert f"{NOT_COVERED_PREFIX} {_VEGA} FAIL" in text
            assert "see §6" in text
            # And it sits in section 7, not somewhere above it.
            assert text.index(NOT_COVERED_PREFIX) > text.index("7. Decision")

    def test_a_quiet_book_prints_no_caveat(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No false caveat: a book whose vega is in band says nothing."""
        monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))
        ips_path = tmp_path / "ips.yaml"
        ips_path.write_text(_example_ips_text(), encoding="utf-8")
        assert (
            import_portfolio_main(
                [
                    str(_EXAMPLE_PORTFOLIO),
                    "--export-dir",
                    str(tmp_path),
                    "--ips-path",
                    str(ips_path),
                ],
            )
            == 0
        )
        main(
            [
                "--export-dir",
                str(tmp_path),
                "--ips-path",
                str(ips_path),
                "--as-of",
                "2026-08-05",
            ],
        )

        markdown = (
            tmp_path / "reports" / "weekly" / "digest-2026-08-05.md"
        ).read_text(encoding="utf-8")

        assert NOT_COVERED_PREFIX not in markdown

    @pytest.mark.parametrize(
        "verdict",
        [v.value for v in DecisionVerdict],
        ids=[v.value for v in DecisionVerdict],
    )
    def test_no_verdict_renders_beside_a_failing_metric_without_it(
        self,
        verdict: str,
    ) -> None:
        """A MAINTAIN, and every other verdict, on the report renderers."""
        decision = replace(
            _make_decision(verdict),
            not_covered=(_VEGA_FAIL,),
        )
        report = _make_report(decision=decision)

        for text in (render_markdown(report), render_html_body(report)):
            assert f"{verdict}" in text
            assert f"{NOT_COVERED_PREFIX} {_VEGA} FAIL" in text

    def test_the_digest_adds_how_long_it_has_been_failing(self) -> None:
        """Only the digest keeps a history, so only it knows the run."""
        base = _make_report(
            within_budget=True,
            decision=replace(_make_decision(), not_covered=(_VEGA_FAIL,)),
        )
        failing_rows = (
            *base.ips_compliance.rows[:2],
            replace(base.ips_compliance.rows[2], passes=False, actual="1.1%"),
        )
        report = replace(
            base,
            ips_compliance=IpsComplianceSection(
                rows=failing_rows,
                all_pass=False,
            ),
        )

        def failing_week(weeks_ago: int) -> WeeklySnapshot:
            return replace(
                _prior_snapshot(),
                as_of=_AS_OF - timedelta(days=7 * weeks_ago),
                ips_compliance_all_pass=False,
                ips_compliance_rows=(
                    (_CARRY, True),
                    ("Crash convexity (-25% shock)", True),
                    (_VEGA, False),
                ),
            )

        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            history=(failing_week(2), failing_week(1)),
            as_of=_AS_OF,
        )

        markdown = render_weekly_digest_markdown(digest)
        html = render_weekly_digest_html(digest)
        assert "3rd week" in markdown
        assert "3rd week" in html
        assert digest.headline.startswith("BREACH: Vega sufficiency")
        assert "(3rd week)" in digest.headline

    def test_an_unmeasured_metric_gets_no_week_count(self) -> None:
        unmeasured = UncoveredMetric(
            metric=_VEGA,
            status=UncoveredStatus.UNMEASURED,
            actual="—",
            target=_VEGA_TARGET,
        )
        report = _make_report(
            decision=replace(_make_decision(), not_covered=(unmeasured,)),
        )

        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            history=(_prior_snapshot(),),
            as_of=_AS_OF,
        )

        assert digest.report.decision is not None
        assert digest.report.decision.not_covered == (unmeasured,)


def _design_text(component: object) -> str:
    children = getattr(component, "children", component)
    if isinstance(children, str):
        return children
    if isinstance(children, list | tuple):
        return " ".join(_design_text(c) for c in children)
    return "" if children is None else _design_text(children)


class TestDesignPrintsItBesideTheVerdict:
    """/design's market-environment panel, the verdict's second surface."""

    _POLICY = _ips().market_environment

    def _panel(self, decision_inputs: dict[str, object]) -> str:
        decision = decision_matrix(_env(), **decision_inputs)  # type: ignore[arg-type]
        timing = entry_timing_tree(
            _env(),
            vix_very_high=self._POLICY.vix_very_high,
            vix_caution=self._POLICY.vix_caution,
            vix_low=self._POLICY.vix_low,
            skew_high=self._POLICY.skew_high_pctile / 100.0,
            skew_low=self._POLICY.skew_low_pctile / 100.0,
        )
        return _design_text(
            design_panel._market_env_panel_view(
                _env(),
                decision,
                timing,
                self._POLICY,
            ),
        )

    def test_a_maintain_beside_a_failing_metric_carries_the_caveat(
        self,
    ) -> None:
        text = self._panel(
            {
                "convexity_now_pct": 15.0,
                "ips_convexity": _ips().convexity,
                "not_covered": [replace(_VEGA_FAIL, weeks=None)],
            },
        )

        assert "Decision: " in text
        assert "MAINTAIN" in text.upper()
        assert f"{NOT_COVERED_PREFIX} {_VEGA} FAIL" in text
        assert "see the IPS compliance strip on /monitor" in text
        # Beside the verdict: after it, before the entry-timing rows.
        assert text.index("Decision:") < text.index(NOT_COVERED_PREFIX)
        assert text.index(NOT_COVERED_PREFIX) < text.index("Entry timing:")

    @pytest.mark.parametrize("reading", [5.0, 15.0, 25.0, None])
    def test_every_verdict_on_the_panel_carries_it(
        self,
        reading: float | None,
    ) -> None:
        text = self._panel(
            {
                "convexity_now_pct": reading,
                "ips_convexity": _ips().convexity,
                "not_covered": [_VEGA_FAIL],
            },
        )

        assert NOT_COVERED_PREFIX in text

    def test_a_clean_book_prints_no_caveat(self) -> None:
        text = self._panel(
            {
                "convexity_now_pct": 15.0,
                "ips_convexity": _ips().convexity,
                "not_covered": (),
            },
        )

        assert NOT_COVERED_PREFIX not in text

    def test_the_real_panel_reads_the_real_compliance_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Through ``_render_market_env_panel_logic`` on a book that fails vega.

        Nothing is injected: the panel builds the compliance rows itself, from
        the same definition the digest and ``/monitor``'s strip read, and the
        book here has a real vega reading below a floor set above it.
        """
        _convexity(monkeypatch, 15.0)
        book = _book(_put(days=400))
        book.underlying_quantity = 500
        ips = _failing_vega_ips()
        reading = app_compliance.compliance_sections_at_ips_anchor(book, ips)[
            2
        ].sufficiency_pct
        assert reading is not None
        assert reading < ips.vega.sufficiency_min_pct

        text = _design_text(
            design_panel._render_market_env_panel_logic(
                portfolio=book,
                ips_config=ips,
                market_env=_env(),
            ),
        )

        assert f"{NOT_COVERED_PREFIX} {_VEGA} FAIL" in text


def _failing_vega_ips() -> IpsConfig:
    """The test IPS with a vega floor no real book reaches."""
    return dataclasses.replace(
        _ips(),
        vega=IpsVega(sufficiency_min_pct=50.0, sufficiency_max_pct=60.0),
    )


class TestMonitorsDecisionsPanelCarriesNoDecisionVerdict:
    """#465 asked whether /monitor shows the verdict. It does not.

    ``/monitor``'s Decisions panel renders each leg's roll verdict and action
    and the monetization schedule. The decision matrix's verdict (BUY /
    MAINTAIN / AVOID / MONETIZE) is rendered on ``/design`` and in the digest
    only, so there is nothing on ``/monitor`` to caveat. Pinned, so the day it
    is added there this fails and says the caveat has to travel with it.
    """

    def test_the_panel_prints_no_matrix_verdict_beside_a_failing_metric(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from deltadewa.analysis.monetization import build_monetization_plan

        _convexity(monkeypatch, 15.0)
        ips = _failing_vega_ips()
        book = _book(_put(days=400))
        book.underlying_quantity = 500
        records = evaluate_roll_status(book, ips)
        plan = build_monetization_plan(book, ips, market_env=_env())

        text = _design_text(
            monitor._decisions_section(records, plan, ips.triggers),
        )

        for verdict in DecisionVerdict:
            assert verdict.value not in text
        assert NOT_COVERED_PREFIX not in text
