"""Tests for deltadewa.reporting.weekly_report."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deltadewa.app.import_portfolio import main as import_portfolio_main
from deltadewa.reporting import weekly_report as weekly_report_module
from deltadewa.reporting.email_smtp import EmailDeliveryError
from deltadewa.reporting.program_report import (
    CostSection,
    DecisionSection,
    IpsComplianceRow,
    IpsComplianceSection,
    MarketContextSection,
    MonetizationSection,
    ProgramReport,
    ProtectionSection,
    ReportHeader,
    ReturnFramingSection,
)
from deltadewa.reporting.weekly_report import (
    _headline,
    _read_backup_heartbeat_warning,
    _worst_roll_verdict,
    build_weekly_digest,
    load_snapshot_history,
    main,
    render_weekly_digest_html,
    render_weekly_digest_markdown,
)
from deltadewa.reporting.weekly_snapshot import (
    SnapshotChange,
    SnapshotDiff,
    WeeklySnapshot,
)

_GOLDEN_PATH = Path(__file__).parent / "goldens" / "weekly_digest.md"
_EXAMPLE_IPS_YAML = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)  # #245: real config/ips.yaml is gitignored; use the tracked example.
# Relative maturity_days (not an absolute maturity_date), so this fixture
# stays valid at any valuation date — including under make test-clockshift's
# forward-shifted clock. spx_protective_put.yaml's absolute 2027-06-17
# maturity would be expired under a large-enough forward shift, breaking
# the crash-skew wing solve on a position with no time value left; that's
# a real trap, not a hypothetical one — it's what this fixture avoids.
_EXAMPLE_PORTFOLIO = Path("examples/portfolios/spx_tail_20m.yaml")

_AS_OF = date(2026, 8, 5)
_PRIOR_AS_OF = date(2026, 7, 29)
_FIRST_AS_OF = date(2026, 7, 1)


def _make_decision(verdict: str = "MAINTAIN") -> DecisionSection:
    return DecisionSection(
        verdict=verdict,
        rationale="test rationale",
        entry_recommendation="test entry recommendation",
        should_enter=True,
        data_quality_note=None,
    )


def _make_report(
    *,
    data_quality: str = "CACHED",
    within_budget: bool = False,
    decision: DecisionSection | None = None,
) -> ProgramReport:
    return ProgramReport(
        header=ReportHeader(
            program_name="SPX Tail Hedge",
            instrument="SPX",
            period_label="Week of 2026-08-05",
            as_of=_AS_OF,
        ),
        cost=CostSection(
            total_theta_annual=-73_000.0,
            book_notional=20_000_000.0,
            carry_pct_of_notional=1.15,
            budget_annual_pct=1.0,
            within_budget=within_budget,
        ),
        protection=ProtectionSection(
            payoff_vs_premium=8.5,
            ips_crash_pct=-25.0,
            convexity_pct=19.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
            meets_target=True,
            premium_paid=300_000.0,
            premium_basis="paid",
        ),
        market_context=MarketContextSection(
            vix=22.0,
            regime_label="NORMAL",
            skew_percentile=0.45,
            hedge_cost_verdict="FAIR",
            data_quality=data_quality,
        ),
        return_framing=ReturnFramingSection(carry_drag_annual_pct=1.15),
        monetization=MonetizationSection(
            realized_label="n/a — planned (C4)",
            schedule_steps=2,
        ),
        ips_compliance=IpsComplianceSection(
            rows=(
                IpsComplianceRow(
                    metric="Annual carry cost",
                    target="≤ 1.00% of notional",
                    actual="1.15%",
                    passes=within_budget,
                    action=(
                        None
                        if within_budget
                        else "Carry is above the IPS budget — trim size."
                    ),
                ),
                IpsComplianceRow(
                    metric="Crash convexity (-25% shock)",
                    target="15.0%\u201325.0% of book",
                    actual="19.0%",
                    passes=True,
                ),
            ),
            all_pass=within_budget,
        ),
        decision=decision if decision is not None else _make_decision(),
    )


def _prior_snapshot() -> WeeklySnapshot:
    return WeeklySnapshot(
        as_of=_PRIOR_AS_OF,
        first_as_of=_FIRST_AS_OF,
        data_quality="LIVE",
        carry_pct_of_notional=1.0,
        within_budget=True,
        convexity_pct=18.0,
        payoff_vs_premium=8.3,
        meets_target=True,
        vix=18.0,
        skew_percentile=0.40,
        regime_label="NORMAL",
        hedge_cost_verdict="FAIR",
        decision_verdict="MAINTAIN",
        worst_roll_verdict="MONITOR",
        ips_compliance_all_pass=True,
        ips_compliance_rows=(
            ("Annual carry cost", True),
            ("Crash convexity (-25% shock)", True),
        ),
        premium_paid_point_in_time=290_000.0,
        cumulative_carry_cost=1_400.0,
    )


class TestWorstRollVerdict:
    """_worst_roll_verdict() — the local severity mirror of RollVerdict."""

    def test_no_records_is_not_applicable(self) -> None:
        assert _worst_roll_verdict(()) == "N/A"

    def test_picks_the_most_severe_verdict(self) -> None:
        records = [
            SimpleNamespace(verdict=SimpleNamespace(value="HOLD")),
            SimpleNamespace(verdict=SimpleNamespace(value="ROLL")),
            SimpleNamespace(verdict=SimpleNamespace(value="MONITOR")),
        ]

        assert _worst_roll_verdict(records) == "ROLL"


class TestBuildWeeklyDigest:
    """build_weekly_digest() — pure assembly."""

    def test_first_run_uses_nominal_week_and_zero_prior_cumulative(
        self,
    ) -> None:
        report = _make_report()

        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        assert digest.elapsed_days == 7
        assert digest.snapshot.first_as_of == _AS_OF
        assert digest.weekly_carry_cost == pytest.approx(
            digest.snapshot.cumulative_carry_cost,
        )
        assert digest.diff.is_first_run is True

    def test_subsequent_run_integrates_over_actual_elapsed_days(self) -> None:
        report = _make_report()
        prior = _prior_snapshot()

        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            history=(prior,),
            as_of=_AS_OF,
        )

        assert digest.elapsed_days == (_AS_OF - _PRIOR_AS_OF).days
        expected_weekly_cost = 73_000.0 / 365.0 * digest.elapsed_days
        assert digest.weekly_carry_cost == pytest.approx(expected_weekly_cost)
        assert digest.snapshot.cumulative_carry_cost == pytest.approx(
            prior.cumulative_carry_cost + expected_weekly_cost,
        )
        assert digest.snapshot.first_as_of == _FIRST_AS_OF

    def test_headline_no_action_when_no_crossings(self) -> None:
        report = _make_report(within_budget=True)
        prior = _prior_snapshot()

        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            history=(replace(prior, worst_roll_verdict="N/A"),),
            as_of=_AS_OF,
        )

        assert digest.headline == "NO ACTION"

    def test_headline_action_names_first_crossing(self) -> None:
        # Compliant on both sides (a BREACH would otherwise outrank this,
        # #296) — the crossing here is the decision verdict changing,
        # which prior's "MAINTAIN" doesn't match.
        report = _make_report(
            within_budget=True,
            decision=_make_decision("MONETIZE"),
        )

        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            history=(_prior_snapshot(),),
            as_of=_AS_OF,
        )

        assert digest.headline.startswith("ACTION: ")

    def test_headline_stale_prefix_when_data_quality_worse_than_cached(
        self,
    ) -> None:
        report = _make_report(data_quality="STALE", within_budget=True)

        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        assert digest.headline.startswith("STALE DATA — ")


def _snapshot_with_carry_failing(
    as_of: date, *, passes: bool
) -> WeeklySnapshot:
    """A hand-built WeeklySnapshot varying only the carry-cost row's pass."""
    return replace(
        _prior_snapshot(),
        as_of=as_of,
        within_budget=passes,
        ips_compliance_all_pass=passes,
        ips_compliance_rows=(
            ("Annual carry cost", passes),
            ("Crash convexity (-25% shock)", True),
        ),
    )


class TestStandingBreachHeadline:
    """#296: a compliance breach outranks a crossing and carries a count."""

    def test_keeps_announcing_with_no_crossings(self) -> None:
        report = _make_report(within_budget=False)
        history = (
            _snapshot_with_carry_failing(date(2026, 7, 22), passes=False),
            _snapshot_with_carry_failing(_PRIOR_AS_OF, passes=False),
        )

        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            history=history,
            as_of=_AS_OF,
        )

        assert digest.headline.startswith("BREACH")
        assert digest.headline != "NO ACTION"

    def test_count_tracks_the_run(self) -> None:
        report = _make_report(within_budget=False)

        one_week = (_snapshot_with_carry_failing(_PRIOR_AS_OF, passes=False),)
        digest_2nd = build_weekly_digest(
            report=report,
            roll_records=(),
            history=one_week,
            as_of=_AS_OF,
        )
        assert "2nd week" in digest_2nd.headline

        five_weeks = tuple(
            _snapshot_with_carry_failing(
                date(2026, 7, 1) + timedelta(days=7 * i),
                passes=False,
            )
            for i in range(4)
        )
        digest_5th = build_weekly_digest(
            report=report,
            roll_records=(),
            history=five_weeks,
            as_of=_AS_OF,
        )
        assert "5th week" in digest_5th.headline

    def test_a_passing_week_resets_the_count(self) -> None:
        report = _make_report(within_budget=False)
        history = (
            _snapshot_with_carry_failing(date(2026, 7, 15), passes=False),
            _snapshot_with_carry_failing(date(2026, 7, 22), passes=True),
            _snapshot_with_carry_failing(_PRIOR_AS_OF, passes=True),
        )

        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            history=history,
            as_of=_AS_OF,
        )

        assert "1st week" in digest.headline


class TestHeadlineMechanism:
    """_headline() directly — the invariant and the STALE-prefix compose."""

    def _snapshot(
        self, *, all_pass: bool, data_quality: str = "CACHED"
    ) -> WeeklySnapshot:
        return replace(
            _prior_snapshot(),
            as_of=_AS_OF,
            data_quality=data_quality,
            ips_compliance_all_pass=all_pass,
            ips_compliance_rows=(
                ("Annual carry cost", all_pass),
                ("Crash convexity (-25% shock)", True),
            ),
        )

    def _compliance(self, *, all_pass: bool) -> IpsComplianceSection:
        return IpsComplianceSection(
            rows=(
                IpsComplianceRow(
                    metric="Annual carry cost",
                    target="≤ 1.00%",
                    actual="1.15%",
                    passes=all_pass,
                ),
                IpsComplianceRow(
                    metric="Crash convexity (-25% shock)",
                    target="15.0%\u201325.0%",
                    actual="19.0%",
                    passes=True,
                ),
            ),
            all_pass=all_pass,
        )

    @pytest.mark.parametrize(
        ("all_pass", "has_crossing"),
        [(True, False), (True, True), (False, False), (False, True)],
    )
    def test_no_action_implies_all_pass(
        self,
        all_pass: bool,
        has_crossing: bool,
    ) -> None:
        crossings = (
            (SnapshotChange(label="Decision verdict", detail="A → B"),)
            if has_crossing
            else ()
        )
        diff = SnapshotDiff(
            is_first_run=False,
            prior_as_of=_PRIOR_AS_OF,
            crossings=crossings,
            material_moves=(),
        )
        snapshot = self._snapshot(all_pass=all_pass)
        compliance = self._compliance(all_pass=all_pass)

        headline = _headline(diff, snapshot, compliance, ())

        if headline == "NO ACTION":
            assert all_pass is True

    @pytest.mark.parametrize(
        ("all_pass", "has_crossing"),
        [(True, False), (True, True), (False, False)],
    )
    def test_stale_prefix_composes_on_every_branch(
        self,
        all_pass: bool,
        has_crossing: bool,
    ) -> None:
        crossings = (
            (SnapshotChange(label="Decision verdict", detail="A → B"),)
            if has_crossing
            else ()
        )
        diff = SnapshotDiff(
            is_first_run=False,
            prior_as_of=_PRIOR_AS_OF,
            crossings=crossings,
            material_moves=(),
        )
        snapshot = self._snapshot(all_pass=all_pass, data_quality="STALE")
        compliance = self._compliance(all_pass=all_pass)

        headline = _headline(diff, snapshot, compliance, ())

        assert headline.startswith("STALE DATA — ")


class TestGoldenMarkdown:
    """Byte-for-byte regression on a pinned, fully-injected digest."""

    def test_matches_golden_file(self) -> None:
        report = _make_report()
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            history=(_prior_snapshot(),),
            as_of=_AS_OF,
        )

        rendered = render_weekly_digest_markdown(digest)

        assert rendered == _GOLDEN_PATH.read_text(encoding="utf-8")


class TestRenderWeeklyDigestHtml:
    """render_weekly_digest_html() — smoke-tested, not byte-goldened."""

    def _digest(self, **report_kwargs: object):
        report = _make_report(**report_kwargs)  # type: ignore[arg-type]
        return build_weekly_digest(
            report=report,
            roll_records=(),
            history=(_prior_snapshot(),),
            as_of=_AS_OF,
        )

    def test_is_one_self_contained_document(self) -> None:
        html = render_weekly_digest_html(self._digest())

        assert html.startswith("<!DOCTYPE html>")
        assert html.count("<html") == 1
        assert html.count("</html>") == 1
        assert html.count("<body>") == 1

    def test_contains_headline_and_report_sections(self) -> None:
        # Default fixture is within_budget=False vs prior's True — a
        # compliance breach, which outranks a plain crossing (#296).
        html = render_weekly_digest_html(self._digest())

        assert "BREACH: Annual carry cost out of policy" in html
        assert "<h2>3. Market Context</h2>" in html
        assert "<h2>6. IPS Compliance</h2>" in html
        assert "<h2>7. Decision &amp; entry timing</h2>" in html


class TestStaleBanner:
    """The staleness banner fires on worse-than-CACHED, in both formats."""

    def test_markdown_caveat_absent_when_cached(self) -> None:
        report = _make_report(data_quality="CACHED", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        md = render_weekly_digest_markdown(digest)

        assert "DATA QUALITY" not in md

    def test_markdown_caveat_present_when_stale(self) -> None:
        report = _make_report(data_quality="STALE", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        md = render_weekly_digest_markdown(digest)

        assert "DATA QUALITY: STALE" in md

    def test_markdown_caveat_present_when_unavailable(self) -> None:
        report = _make_report(data_quality="UNAVAILABLE", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        md = render_weekly_digest_markdown(digest)

        assert "DATA QUALITY: UNAVAILABLE" in md

    def test_html_caveat_present_when_stale(self) -> None:
        report = _make_report(data_quality="STALE", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        html = render_weekly_digest_html(digest)

        assert 'class="caveat"' in html
        assert "STALE" in html

    def test_html_caveat_absent_when_cached(self) -> None:
        report = _make_report(data_quality="CACHED", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        html = render_weekly_digest_html(digest)

        assert 'class="caveat"' not in html


class TestBackupHeartbeatCaveat:
    """The #252 backup-heartbeat caveat: rendered only when
    ``backup_heartbeat_warning`` is set, in both formats — same pattern
    as ``TestStaleBanner``'s DATA QUALITY banner.
    """

    def test_markdown_caveat_absent_by_default(self) -> None:
        report = _make_report(within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        md = render_weekly_digest_markdown(digest)

        assert "backup" not in md.lower()

    def test_markdown_caveat_present_when_warning_set(self) -> None:
        report = _make_report(within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
            backup_heartbeat_warning="Offsite backup heartbeat ping "
            "failed as of 2026-08-04T03:00:12Z",
        )

        md = render_weekly_digest_markdown(digest)

        assert (
            "Offsite backup heartbeat ping failed as of "
            "2026-08-04T03:00:12Z" in md
        )

    def test_html_caveat_absent_by_default(self) -> None:
        report = _make_report(within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        html = render_weekly_digest_html(digest)

        assert "backup" not in html.lower()

    def test_html_caveat_present_when_warning_set(self) -> None:
        report = _make_report(within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
            backup_heartbeat_warning="Offsite backup heartbeat ping failed",
        )

        html = render_weekly_digest_html(digest)

        assert html.count('class="caveat"') == 1
        assert "Offsite backup heartbeat ping failed" in html

    def test_both_caveats_can_render_together(self) -> None:
        report = _make_report(data_quality="STALE", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
            backup_heartbeat_warning="Offsite backup heartbeat ping failed",
        )

        html = render_weekly_digest_html(digest)

        # program_report's own body also uses class="caveat" elsewhere
        # (unrelated to either banner), so assert both banners' own text
        # is present rather than an exact, brittle site-wide count.
        assert "DATA QUALITY: STALE" in html
        assert "Offsite backup heartbeat ping failed" in html


class TestReadBackupHeartbeatWarning:
    """_read_backup_heartbeat_warning() — the #252 status-file reader."""

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert _read_backup_heartbeat_warning(tmp_path) is None

    def test_present_and_valid_returns_a_warning(
        self,
        tmp_path: Path,
    ) -> None:
        (tmp_path / ".backup-heartbeat-status.json").write_text(
            json.dumps(
                {
                    "failed_at": "2026-08-04T03:00:12Z",
                    "url_var": "BACKUP_HEARTBEAT_URL",
                },
            ),
        )

        warning = _read_backup_heartbeat_warning(tmp_path)

        assert warning is not None
        assert "2026-08-04T03:00:12Z" in warning
        assert "ops/backup-exports.sh" in warning

    def test_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / ".backup-heartbeat-status.json").write_text("not json")

        assert _read_backup_heartbeat_warning(tmp_path) is None

    def test_missing_expected_key_returns_none(self, tmp_path: Path) -> None:
        (tmp_path / ".backup-heartbeat-status.json").write_text(
            json.dumps({"unexpected": "shape"}),
        )

        assert _read_backup_heartbeat_warning(tmp_path) is None


class TestFirstRunRendering:
    """A first run states there's no baseline, in both formats."""

    def test_markdown_states_first_snapshot(self) -> None:
        report = _make_report(within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        md = render_weekly_digest_markdown(digest)

        assert "first snapshot" in md
        assert "Threshold crossings" not in md

    def test_html_states_first_snapshot(self) -> None:
        report = _make_report(within_budget=True)
        digest = build_weekly_digest(
            report=report,
            roll_records=(),
            as_of=_AS_OF,
        )

        html = render_weekly_digest_html(digest)

        assert "first snapshot" in html


class TestLoadSnapshotHistory:
    """load_snapshot_history() — every prior snapshot, oldest first."""

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert load_snapshot_history(tmp_path, before=_AS_OF) == ()

    def test_returns_every_prior_oldest_first(self, tmp_path: Path) -> None:
        weekly_dir = tmp_path / "reports" / "weekly"
        weekly_dir.mkdir(parents=True)
        older = _prior_snapshot()
        newer = replace(older, as_of=date(2026, 8, 1))
        (weekly_dir / "snapshot-a.json").write_text(
            json.dumps(older.to_json_dict()),
        )
        (weekly_dir / "snapshot-b.json").write_text(
            json.dumps(newer.to_json_dict()),
        )

        result = load_snapshot_history(tmp_path, before=_AS_OF)

        assert [snap.as_of for snap in result] == [older.as_of, newer.as_of]

    def test_ignores_snapshots_on_or_after_before(self, tmp_path: Path) -> None:
        weekly_dir = tmp_path / "reports" / "weekly"
        weekly_dir.mkdir(parents=True)
        same_day = replace(_prior_snapshot(), as_of=_AS_OF)
        (weekly_dir / "snapshot-same.json").write_text(
            json.dumps(same_day.to_json_dict()),
        )

        assert load_snapshot_history(tmp_path, before=_AS_OF) == ()

    def test_skips_unreadable_files(self, tmp_path: Path) -> None:
        weekly_dir = tmp_path / "reports" / "weekly"
        weekly_dir.mkdir(parents=True)
        (weekly_dir / "snapshot-bad.json").write_text("not json")
        good = _prior_snapshot()
        (weekly_dir / "snapshot-good.json").write_text(
            json.dumps(good.to_json_dict()),
        )

        result = load_snapshot_history(tmp_path, before=_AS_OF)

        assert [snap.as_of for snap in result] == [good.as_of]


@dataclass
class _MainFixture:
    export_dir: Path


@pytest.fixture
def seeded_export_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> _MainFixture:
    """A tmp export dir with a real portfolio loaded, and an empty cache."""
    monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))
    exit_code = import_portfolio_main(
        [
            str(_EXAMPLE_PORTFOLIO),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(_EXAMPLE_IPS_YAML),
        ],
    )
    assert exit_code == 0
    return _MainFixture(export_dir=tmp_path)


class TestMainCli:
    """main() — refuses without policy/positions; writes + reuses snapshots."""

    def test_refuses_when_ips_missing(self, tmp_path: Path) -> None:
        exit_code = import_portfolio_main(
            [
                str(_EXAMPLE_PORTFOLIO),
                "--export-dir",
                str(tmp_path),
                "--ips-path",
                str(tmp_path / "does-not-exist-ips.yaml"),
            ],
        )
        assert exit_code == 0

        result = main(
            [
                "--export-dir",
                str(tmp_path),
                "--ips-path",
                str(tmp_path / "does-not-exist-ips.yaml"),
                "--as-of",
                "2026-08-05",
            ],
        )

        assert result == 1
        assert not (tmp_path / "reports" / "weekly").exists()

    def test_refuses_when_portfolio_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))

        result = main(
            [
                "--export-dir",
                str(tmp_path),
                "--ips-path",
                str(_EXAMPLE_IPS_YAML),
                "--as-of",
                "2026-08-05",
            ],
        )

        assert result == 1
        assert not (tmp_path / "reports" / "weekly").exists()

    def test_writes_three_files_and_a_second_run_finds_the_prior(
        self,
        seeded_export_dir: _MainFixture,
    ) -> None:
        export_dir = seeded_export_dir.export_dir

        first_exit = main(
            [
                "--export-dir",
                str(export_dir),
                "--ips-path",
                str(_EXAMPLE_IPS_YAML),
                "--as-of",
                "2026-08-05",
            ],
        )
        assert first_exit == 0

        weekly_dir = export_dir / "reports" / "weekly"
        written = sorted(p.name for p in weekly_dir.iterdir())
        assert written == [
            "digest-2026-08-05.html",
            "digest-2026-08-05.md",
            "snapshot-2026-08-05.json",
        ]

        second_exit = main(
            [
                "--export-dir",
                str(export_dir),
                "--ips-path",
                str(_EXAMPLE_IPS_YAML),
                "--as-of",
                "2026-08-12",
            ],
        )
        assert second_exit == 0

        second_digest_md = (weekly_dir / "digest-2026-08-12.md").read_text(
            encoding="utf-8",
        )
        # A real prior was found — not the first-run message.
        assert "first snapshot" not in second_digest_md
        assert "Compared against the snapshot from 2026-08-05" in (
            second_digest_md
        )

    def test_surfaces_a_backup_heartbeat_failure_marker(
        self,
        seeded_export_dir: _MainFixture,
    ) -> None:
        """#252: main() reads ops/backup-exports.sh's status file and
        surfaces it in the written digest — the end-to-end path from a
        root cron failure to something a reader of the digest sees.
        """
        export_dir = seeded_export_dir.export_dir
        (export_dir / ".backup-heartbeat-status.json").write_text(
            json.dumps(
                {
                    "failed_at": "2026-08-04T03:00:12Z",
                    "url_var": "BACKUP_HEARTBEAT_URL",
                },
            ),
        )

        exit_code = main(
            [
                "--export-dir",
                str(export_dir),
                "--ips-path",
                str(_EXAMPLE_IPS_YAML),
                "--as-of",
                "2026-08-05",
            ],
        )
        assert exit_code == 0

        digest_md = (
            export_dir / "reports" / "weekly" / "digest-2026-08-05.md"
        ).read_text(encoding="utf-8")
        assert "Offsite backup heartbeat ping failed" in digest_md
        assert "2026-08-04T03:00:12Z" in digest_md


class TestMainSendEmail:
    """--send-email: opt-in delivery, exit 2 on any failure, ping on send."""

    def test_without_flag_never_sends_or_pings(
        self,
        seeded_export_dir: _MainFixture,
    ) -> None:
        """The existing (no --send-email) tests' behaviour, made explicit."""
        with (
            patch.object(weekly_report_module, "send_email") as mock_send,
            patch.object(weekly_report_module, "ping") as mock_ping,
        ):
            exit_code = main(
                [
                    "--export-dir",
                    str(seeded_export_dir.export_dir),
                    "--ips-path",
                    str(_EXAMPLE_IPS_YAML),
                    "--as-of",
                    "2026-08-05",
                ],
            )

        assert exit_code == 0
        mock_send.assert_not_called()
        mock_ping.assert_not_called()

    def test_missing_env_vars_exits_two_without_sending(
        self,
        seeded_export_dir: _MainFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.delenv("SMTP_PORT", raising=False)
        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        monkeypatch.delenv("SMTP_PASSWORD", raising=False)
        monkeypatch.delenv("REPORT_EMAIL_TO", raising=False)
        monkeypatch.delenv("REPORT_EMAIL_FROM", raising=False)

        with patch.object(weekly_report_module, "send_email") as mock_send:
            exit_code = main(
                [
                    "--export-dir",
                    str(seeded_export_dir.export_dir),
                    "--ips-path",
                    str(_EXAMPLE_IPS_YAML),
                    "--as-of",
                    "2026-08-05",
                    "--send-email",
                ],
            )

        assert exit_code == 2
        mock_send.assert_not_called()
        # The digest itself was still written — only delivery is missing.
        weekly_dir = seeded_export_dir.export_dir / "reports" / "weekly"
        assert (weekly_dir / "digest-2026-08-05.md").exists()

    def test_send_failure_exits_two_without_pinging(
        self,
        seeded_export_dir: _MainFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "hedge-program@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "fake-smtp-password")
        monkeypatch.setenv("REPORT_EMAIL_TO", "ic@example.com")
        monkeypatch.setenv("REPORT_EMAIL_FROM", "hedge-program@example.com")
        monkeypatch.setenv("DIGEST_HEARTBEAT_URL", "https://hc-ping.com/x")

        with (
            patch.object(
                weekly_report_module,
                "send_email",
                side_effect=EmailDeliveryError("SMTP relay rejected the send"),
            ),
            patch.object(weekly_report_module, "ping") as mock_ping,
        ):
            exit_code = main(
                [
                    "--export-dir",
                    str(seeded_export_dir.export_dir),
                    "--ips-path",
                    str(_EXAMPLE_IPS_YAML),
                    "--as-of",
                    "2026-08-05",
                    "--send-email",
                ],
            )

        assert exit_code == 2
        mock_ping.assert_not_called()

    def test_successful_send_pings_the_digest_heartbeat(
        self,
        seeded_export_dir: _MainFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "hedge-program@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "fake-smtp-password")
        monkeypatch.setenv("REPORT_EMAIL_TO", "ic@example.com")
        monkeypatch.setenv("REPORT_EMAIL_FROM", "hedge-program@example.com")
        monkeypatch.setenv("DIGEST_HEARTBEAT_URL", "https://hc-ping.com/x")

        with (
            patch.object(weekly_report_module, "send_email") as mock_send,
            patch.object(weekly_report_module, "ping") as mock_ping,
        ):
            exit_code = main(
                [
                    "--export-dir",
                    str(seeded_export_dir.export_dir),
                    "--ips-path",
                    str(_EXAMPLE_IPS_YAML),
                    "--as-of",
                    "2026-08-05",
                    "--send-email",
                ],
            )

        assert exit_code == 0
        mock_send.assert_called_once()
        message = mock_send.call_args.args[0]
        assert message.to_addr == "ic@example.com"
        assert message.from_addr == "hedge-program@example.com"
        mock_ping.assert_called_once_with(
            "https://hc-ping.com/x",
            label="digest",
        )


class TestMainBuildFailure:
    """#364: build_and_render() raising exits 3, writes nothing, never pings."""

    def test_returns_three_and_writes_no_files(
        self,
        seeded_export_dir: _MainFixture,
    ) -> None:
        export_dir = seeded_export_dir.export_dir

        with (
            patch.object(
                weekly_report_module,
                "build_and_render",
                side_effect=RuntimeError("synthetic build failure"),
            ),
            patch.object(weekly_report_module, "ping") as mock_ping,
        ):
            exit_code = main(
                [
                    "--export-dir",
                    str(export_dir),
                    "--ips-path",
                    str(_EXAMPLE_IPS_YAML),
                    "--as-of",
                    "2026-08-05",
                ],
            )

        assert exit_code == 3
        weekly_dir = export_dir / "reports" / "weekly"
        # No digest md/html, and critically no snapshot — next week's
        # digest must still compare against last week's real snapshot.
        assert not weekly_dir.exists() or not any(weekly_dir.iterdir())
        mock_ping.assert_not_called()

    def test_send_email_sends_a_failure_alert(
        self,
        seeded_export_dir: _MainFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "hedge-program@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "fake-smtp-password")
        monkeypatch.setenv("REPORT_EMAIL_TO", "ic@example.com")
        monkeypatch.setenv("REPORT_EMAIL_FROM", "hedge-program@example.com")
        monkeypatch.setenv("DIGEST_HEARTBEAT_URL", "https://hc-ping.com/x")

        with (
            patch.object(
                weekly_report_module,
                "build_and_render",
                side_effect=RuntimeError("synthetic build failure"),
            ),
            patch.object(weekly_report_module, "send_email") as mock_send,
            patch.object(weekly_report_module, "ping") as mock_ping,
        ):
            exit_code = main(
                [
                    "--export-dir",
                    str(seeded_export_dir.export_dir),
                    "--ips-path",
                    str(_EXAMPLE_IPS_YAML),
                    "--as-of",
                    "2026-08-05",
                    "--send-email",
                ],
            )

        assert exit_code == 3
        mock_send.assert_called_once()
        message = mock_send.call_args.args[0]
        assert "FAILED to build" in message.subject
        mock_ping.assert_not_called()

    def test_without_send_email_sends_no_alert(
        self,
        seeded_export_dir: _MainFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "hedge-program@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "fake-smtp-password")
        monkeypatch.setenv("REPORT_EMAIL_TO", "ic@example.com")
        monkeypatch.setenv("REPORT_EMAIL_FROM", "hedge-program@example.com")

        with (
            patch.object(
                weekly_report_module,
                "build_and_render",
                side_effect=RuntimeError("synthetic build failure"),
            ),
            patch.object(weekly_report_module, "send_email") as mock_send,
            patch.object(weekly_report_module, "ping") as mock_ping,
        ):
            exit_code = main(
                [
                    "--export-dir",
                    str(seeded_export_dir.export_dir),
                    "--ips-path",
                    str(_EXAMPLE_IPS_YAML),
                    "--as-of",
                    "2026-08-05",
                ],
            )

        assert exit_code == 3
        mock_send.assert_not_called()
        mock_ping.assert_not_called()


class TestMainStateLoadFailure:
    """R-a.3: ProgramState.load() raising is guarded the same as #364.

    A blast-radius audit found ``ProgramState.load()`` sitting ahead of
    #364's guard, unwrapped — a raise there exited with Python's bare
    default (1), indistinguishable from ``_EXIT_REFUSED``'s documented
    meaning of a clean, expected refusal. These pin the widened guard:
    same exit code (3), same no-files/no-ping contract, same alert email
    as a ``build_and_render`` failure — not merely "no traceback escapes."
    """

    def test_returns_three_and_writes_no_files(
        self,
        seeded_export_dir: _MainFixture,
    ) -> None:
        export_dir = seeded_export_dir.export_dir

        with (
            patch.object(
                weekly_report_module.ProgramState,
                "load",
                side_effect=RuntimeError("synthetic state-load failure"),
            ),
            patch.object(weekly_report_module, "ping") as mock_ping,
        ):
            exit_code = main(
                [
                    "--export-dir",
                    str(export_dir),
                    "--ips-path",
                    str(_EXAMPLE_IPS_YAML),
                    "--as-of",
                    "2026-08-05",
                ],
            )

        assert exit_code == 3
        weekly_dir = export_dir / "reports" / "weekly"
        assert not weekly_dir.exists() or not any(weekly_dir.iterdir())
        mock_ping.assert_not_called()

    def test_send_email_sends_a_failure_alert(
        self,
        seeded_export_dir: _MainFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USERNAME", "hedge-program@example.com")
        monkeypatch.setenv("SMTP_PASSWORD", "fake-smtp-password")
        monkeypatch.setenv("REPORT_EMAIL_TO", "ic@example.com")
        monkeypatch.setenv("REPORT_EMAIL_FROM", "hedge-program@example.com")
        monkeypatch.setenv("DIGEST_HEARTBEAT_URL", "https://hc-ping.com/x")

        with (
            patch.object(
                weekly_report_module.ProgramState,
                "load",
                side_effect=RuntimeError("synthetic state-load failure"),
            ),
            patch.object(weekly_report_module, "send_email") as mock_send,
            patch.object(weekly_report_module, "ping") as mock_ping,
        ):
            exit_code = main(
                [
                    "--export-dir",
                    str(seeded_export_dir.export_dir),
                    "--ips-path",
                    str(_EXAMPLE_IPS_YAML),
                    # No --as-of: state loading fails before as_of would
                    # normally be computed, so the alert must fall back to
                    # a default-timezone resolution rather than crashing.
                    "--send-email",
                ],
            )

        assert exit_code == 3
        mock_send.assert_called_once()
        message = mock_send.call_args.args[0]
        assert "FAILED to build" in message.subject
        mock_ping.assert_not_called()
