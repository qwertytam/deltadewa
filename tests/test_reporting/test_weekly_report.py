"""Tests for deltadewa.reporting.weekly_report."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from deltadewa.app.import_portfolio import main as import_portfolio_main
from deltadewa.reporting import weekly_report as weekly_report_module
from deltadewa.reporting.email_smtp import EmailDeliveryError
from deltadewa.reporting.program_report import (
    CostSection,
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
    _worst_roll_verdict,
    build_weekly_digest,
    load_prior_snapshot,
    main,
    render_weekly_digest_html,
    render_weekly_digest_markdown,
)
from deltadewa.reporting.weekly_snapshot import WeeklySnapshot

_GOLDEN_PATH = Path(__file__).parent / "goldens" / "weekly_digest.md"
_EXAMPLE_IPS_YAML = Path(__file__).parent.parent.parent / "config" / "ips.yaml"
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


def _make_report(
    *,
    data_quality: str = "CACHED",
    within_budget: bool = False,
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
            payoff_ratio=8.5,
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
    )


def _prior_snapshot() -> WeeklySnapshot:
    return WeeklySnapshot(
        as_of=_PRIOR_AS_OF,
        first_as_of=_FIRST_AS_OF,
        data_quality="LIVE",
        carry_pct_of_notional=1.0,
        within_budget=True,
        convexity_pct=18.0,
        payoff_ratio=8.3,
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
            decision_verdict="MAINTAIN",
            roll_records=(),
            prior_snapshot=None,
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
            decision_verdict="MONETIZE",
            roll_records=(),
            prior_snapshot=prior,
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
            decision_verdict=prior.decision_verdict,
            roll_records=(),
            prior_snapshot=replace(prior, worst_roll_verdict="N/A"),
            as_of=_AS_OF,
        )

        assert digest.headline == "NO ACTION"

    def test_headline_action_names_first_crossing(self) -> None:
        report = _make_report()  # within_budget=False vs prior's True

        digest = build_weekly_digest(
            report=report,
            decision_verdict="MONETIZE",
            roll_records=(),
            prior_snapshot=_prior_snapshot(),
            as_of=_AS_OF,
        )

        assert digest.headline.startswith("ACTION: ")

    def test_headline_stale_prefix_when_data_quality_worse_than_cached(
        self,
    ) -> None:
        report = _make_report(data_quality="STALE", within_budget=True)

        digest = build_weekly_digest(
            report=report,
            decision_verdict="MAINTAIN",
            roll_records=(),
            prior_snapshot=None,
            as_of=_AS_OF,
        )

        assert digest.headline.startswith("STALE DATA — ")


class TestGoldenMarkdown:
    """Byte-for-byte regression on a pinned, fully-injected digest."""

    def test_matches_golden_file(self) -> None:
        report = _make_report()
        digest = build_weekly_digest(
            report=report,
            decision_verdict="MONETIZE",
            roll_records=(),
            prior_snapshot=_prior_snapshot(),
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
            decision_verdict="MONETIZE",
            roll_records=(),
            prior_snapshot=_prior_snapshot(),
            as_of=_AS_OF,
        )

    def test_is_one_self_contained_document(self) -> None:
        html = render_weekly_digest_html(self._digest())

        assert html.startswith("<!DOCTYPE html>")
        assert html.count("<html") == 1
        assert html.count("</html>") == 1
        assert html.count("<body>") == 1

    def test_contains_headline_and_report_sections(self) -> None:
        html = render_weekly_digest_html(self._digest())

        assert "ACTION: Decision verdict" in html
        assert "<h2>3. Market Context</h2>" in html
        assert "<h2>6. IPS Compliance</h2>" in html


class TestStaleBanner:
    """The staleness banner fires on worse-than-CACHED, in both formats."""

    def test_markdown_caveat_absent_when_cached(self) -> None:
        report = _make_report(data_quality="CACHED", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            decision_verdict="MAINTAIN",
            roll_records=(),
            prior_snapshot=None,
            as_of=_AS_OF,
        )

        md = render_weekly_digest_markdown(digest)

        assert "DATA QUALITY" not in md

    def test_markdown_caveat_present_when_stale(self) -> None:
        report = _make_report(data_quality="STALE", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            decision_verdict="MAINTAIN",
            roll_records=(),
            prior_snapshot=None,
            as_of=_AS_OF,
        )

        md = render_weekly_digest_markdown(digest)

        assert "DATA QUALITY: STALE" in md

    def test_markdown_caveat_present_when_unavailable(self) -> None:
        report = _make_report(data_quality="UNAVAILABLE", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            decision_verdict="MAINTAIN",
            roll_records=(),
            prior_snapshot=None,
            as_of=_AS_OF,
        )

        md = render_weekly_digest_markdown(digest)

        assert "DATA QUALITY: UNAVAILABLE" in md

    def test_html_caveat_present_when_stale(self) -> None:
        report = _make_report(data_quality="STALE", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            decision_verdict="MAINTAIN",
            roll_records=(),
            prior_snapshot=None,
            as_of=_AS_OF,
        )

        html = render_weekly_digest_html(digest)

        assert 'class="caveat"' in html
        assert "STALE" in html

    def test_html_caveat_absent_when_cached(self) -> None:
        report = _make_report(data_quality="CACHED", within_budget=True)
        digest = build_weekly_digest(
            report=report,
            decision_verdict="MAINTAIN",
            roll_records=(),
            prior_snapshot=None,
            as_of=_AS_OF,
        )

        html = render_weekly_digest_html(digest)

        assert 'class="caveat"' not in html


class TestFirstRunRendering:
    """A first run states there's no baseline, in both formats."""

    def test_markdown_states_first_snapshot(self) -> None:
        report = _make_report(within_budget=True)
        digest = build_weekly_digest(
            report=report,
            decision_verdict="MAINTAIN",
            roll_records=(),
            prior_snapshot=None,
            as_of=_AS_OF,
        )

        md = render_weekly_digest_markdown(digest)

        assert "first snapshot" in md
        assert "Threshold crossings" not in md

    def test_html_states_first_snapshot(self) -> None:
        report = _make_report(within_budget=True)
        digest = build_weekly_digest(
            report=report,
            decision_verdict="MAINTAIN",
            roll_records=(),
            prior_snapshot=None,
            as_of=_AS_OF,
        )

        html = render_weekly_digest_html(digest)

        assert "first snapshot" in html


class TestLoadPriorSnapshot:
    """load_prior_snapshot() — reads each file's own as_of, not the name."""

    def test_missing_dir_returns_none(self, tmp_path: Path) -> None:
        assert load_prior_snapshot(tmp_path, before=_AS_OF) is None

    def test_returns_the_most_recent_prior(self, tmp_path: Path) -> None:
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

        result = load_prior_snapshot(tmp_path, before=_AS_OF)

        assert result is not None
        assert result.as_of == date(2026, 8, 1)

    def test_ignores_snapshots_on_or_after_before(self, tmp_path: Path) -> None:
        weekly_dir = tmp_path / "reports" / "weekly"
        weekly_dir.mkdir(parents=True)
        same_day = replace(_prior_snapshot(), as_of=_AS_OF)
        (weekly_dir / "snapshot-same.json").write_text(
            json.dumps(same_day.to_json_dict()),
        )

        assert load_prior_snapshot(tmp_path, before=_AS_OF) is None

    def test_skips_unreadable_files(self, tmp_path: Path) -> None:
        weekly_dir = tmp_path / "reports" / "weekly"
        weekly_dir.mkdir(parents=True)
        (weekly_dir / "snapshot-bad.json").write_text("not json")
        good = _prior_snapshot()
        (weekly_dir / "snapshot-good.json").write_text(
            json.dumps(good.to_json_dict()),
        )

        result = load_prior_snapshot(tmp_path, before=_AS_OF)

        assert result is not None
        assert result.as_of == good.as_of


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
