"""Tests for deltadewa.reporting.weekly_snapshot."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

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
from deltadewa.reporting.weekly_snapshot import (
    WeeklySnapshot,
    diff_snapshots,
    snapshot_from_report,
    standing_breaches,
)

_AS_OF = date(2026, 8, 5)


def _make_report(
    *,
    carry_pct_of_notional: float = 1.0,
    within_budget: bool = True,
    convexity_pct: float | None = 18.0,
    payoff_vs_premium: float | None = 8.5,
    meets_target: bool | None = True,
    vix: float | None = 18.0,
    skew_percentile: float | None = 0.45,
    regime_label: str | None = "NORMAL",
    hedge_cost_verdict: str | None = "FAIR",
    data_quality: str = "LIVE",
    compliance_rows: tuple[tuple[str, bool], ...] = (
        ("Annual carry cost", True),
        ("Crash convexity (-25% shock)", True),
    ),
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
            carry_pct_of_notional=carry_pct_of_notional,
            budget_annual_pct=1.0,
            within_budget=within_budget,
        ),
        protection=ProtectionSection(
            payoff_vs_premium=payoff_vs_premium,
            ips_crash_pct=-25.0,
            convexity_pct=convexity_pct,
            target_min_pct=15.0,
            target_max_pct=25.0,
            meets_target=meets_target,
            premium_paid=300_000.0,
            premium_basis="paid",
        ),
        market_context=MarketContextSection(
            vix=vix,
            regime_label=regime_label,
            skew_percentile=skew_percentile,
            hedge_cost_verdict=hedge_cost_verdict,
            data_quality=data_quality,
        ),
        return_framing=ReturnFramingSection(
            carry_drag_annual_pct=carry_pct_of_notional,
        ),
        monetization=MonetizationSection(
            realized_label="n/a — planned (C4)",
            schedule_steps=2,
        ),
        ips_compliance=IpsComplianceSection(
            rows=tuple(
                IpsComplianceRow(
                    metric=metric,
                    target="—",
                    actual="—",
                    passes=passes,
                )
                for metric, passes in compliance_rows
            ),
            all_pass=all(passes for _, passes in compliance_rows),
        ),
    )


def _snapshot(**kwargs: object) -> WeeklySnapshot:
    """Build a WeeklySnapshot straight from a matching report's fields."""
    report = _make_report(**kwargs)  # type: ignore[arg-type]
    return snapshot_from_report(
        report,
        decision_verdict="MAINTAIN",
        worst_roll_verdict="HOLD",
        worst_roll_leg="PUT 4200",
        worst_roll_reason="30d to maturity",
        expired_leg_count=0,
        first_as_of=_AS_OF,
        cumulative_carry_cost=1_000.0,
    )


class TestSnapshotFromReport:
    """snapshot_from_report() pulls the right fields off a ProgramReport."""

    def test_fields_match_report_sections(self) -> None:
        report = _make_report()
        snap = snapshot_from_report(
            report,
            decision_verdict="BUY",
            worst_roll_verdict="MONITOR",
            worst_roll_leg="PUT 4200",
            worst_roll_reason="30d to maturity",
            expired_leg_count=0,
            first_as_of=date(2026, 7, 1),
            cumulative_carry_cost=5_000.0,
        )

        assert snap.as_of == report.header.as_of
        assert snap.first_as_of == date(2026, 7, 1)
        assert snap.data_quality == report.market_context.data_quality
        assert snap.carry_pct_of_notional == report.cost.carry_pct_of_notional
        assert snap.within_budget == report.cost.within_budget
        assert snap.convexity_pct == report.protection.convexity_pct
        assert snap.decision_verdict == "BUY"
        assert snap.worst_roll_verdict == "MONITOR"
        assert snap.cumulative_carry_cost == pytest.approx(5_000.0)
        assert snap.premium_paid_point_in_time == pytest.approx(
            report.protection.premium_paid,
        )
        assert snap.ips_compliance_rows == (
            ("Annual carry cost", True),
            ("Crash convexity (-25% shock)", True),
        )


class TestSnapshotJsonRoundTrip:
    """WeeklySnapshot survives to_json_dict/from_json_dict unchanged."""

    def test_round_trips(self) -> None:
        snap = _snapshot()

        restored = WeeklySnapshot.from_json_dict(snap.to_json_dict())

        assert restored == snap


class TestDiffSnapshotsFirstRun:
    """diff_snapshots(None, current) — no baseline yet."""

    def test_first_run_states_no_prior_rather_than_fabricating(self) -> None:
        current = _snapshot()

        diff = diff_snapshots(None, current)

        assert diff.is_first_run is True
        assert diff.prior_as_of is None
        assert diff.crossings == ()
        assert diff.material_moves == ()


class TestDiffSnapshotsCrossings:
    """Verdict/band/compliance flips are always reported as crossings."""

    def test_decision_verdict_change_is_a_crossing(self) -> None:
        prior = _snapshot()
        current = replace(prior, decision_verdict="MONETIZE")

        diff = diff_snapshots(prior, current)

        assert any(c.label == "Decision verdict" for c in diff.crossings)

    def test_worst_roll_verdict_change_is_a_crossing(self) -> None:
        prior = _snapshot()
        current = replace(prior, worst_roll_verdict="ROLL")

        diff = diff_snapshots(prior, current)

        assert any(c.label == "Worst roll verdict" for c in diff.crossings)

    def test_convexity_band_exit_is_a_crossing(self) -> None:
        prior = _snapshot(meets_target=True)
        current = _snapshot(meets_target=False)

        diff = diff_snapshots(prior, current)

        assert any(c.label == "Convexity band" for c in diff.crossings)

    def test_carry_budget_flip_is_a_crossing(self) -> None:
        prior = _snapshot(within_budget=True)
        current = _snapshot(within_budget=False)

        diff = diff_snapshots(prior, current)

        assert any(c.label == "Carry budget" for c in diff.crossings)

    def test_compliance_row_pass_to_fail_is_a_crossing(self) -> None:
        prior = _snapshot(
            compliance_rows=(
                ("Annual carry cost", True),
                ("Crash convexity (-25% shock)", True),
            ),
        )
        current = _snapshot(
            compliance_rows=(
                ("Annual carry cost", True),
                ("Crash convexity (-25% shock)", False),
            ),
        )

        diff = diff_snapshots(prior, current)

        assert any(
            c.label == "IPS compliance: Crash convexity (-25% shock)"
            for c in diff.crossings
        )

    def test_newly_appeared_compliance_row_is_not_a_crossing(self) -> None:
        """A row absent from the prior snapshot has nothing to diff against."""
        prior = _snapshot(
            compliance_rows=(("Annual carry cost", True),),
        )
        current = _snapshot(
            compliance_rows=(
                ("Annual carry cost", True),
                ("New metric", False),
            ),
        )

        diff = diff_snapshots(prior, current)

        assert not any("New metric" in c.label for c in diff.crossings)

    def test_data_quality_crossing_worse_than_cached_boundary(self) -> None:
        prior = _snapshot(data_quality="CACHED")
        current = _snapshot(data_quality="STALE")

        diff = diff_snapshots(prior, current)

        assert any(c.label == "Data quality" for c in diff.crossings)

    def test_data_quality_change_within_healthy_side_is_not_a_crossing(
        self,
    ) -> None:
        """LIVE -> CACHED is a real change but not a crossing worth flagging."""
        prior = _snapshot(data_quality="LIVE")
        current = _snapshot(data_quality="CACHED")

        diff = diff_snapshots(prior, current)

        assert not any(c.label == "Data quality" for c in diff.crossings)

    def test_recovering_from_stale_is_also_a_crossing(self) -> None:
        prior = _snapshot(data_quality="STALE")
        current = _snapshot(data_quality="LIVE")

        diff = diff_snapshots(prior, current)

        assert any(c.label == "Data quality" for c in diff.crossings)


class TestDiffSnapshotsMaterialMoves:
    """Numeric moves past a noise floor, without a crossing."""

    def test_sub_floor_convexity_move_is_not_reported(self) -> None:
        prior = _snapshot(convexity_pct=18.0)
        current = _snapshot(convexity_pct=18.2)  # 0.2pp < 0.5pp floor

        diff = diff_snapshots(prior, current)

        assert diff.crossings == ()
        assert diff.material_moves == ()

    def test_past_floor_convexity_move_is_reported(self) -> None:
        prior = _snapshot(convexity_pct=18.0)
        current = _snapshot(convexity_pct=19.0)  # 1.0pp >= 0.5pp floor

        diff = diff_snapshots(prior, current)

        assert any(m.label == "Convexity" for m in diff.material_moves)

    def test_past_floor_vix_move_is_reported(self) -> None:
        prior = _snapshot(vix=18.0)
        current = _snapshot(vix=22.0)  # 4 pts >= 3 pt floor

        diff = diff_snapshots(prior, current)

        assert any(m.label == "VIX" for m in diff.material_moves)

    def test_relative_carry_move_past_floor_is_reported(self) -> None:
        prior = _snapshot(carry_pct_of_notional=1.0)
        current = _snapshot(carry_pct_of_notional=1.10)  # 10% relative move

        diff = diff_snapshots(prior, current)

        assert any(
            m.label == "Carry as % of notional" for m in diff.material_moves
        )

    def test_quiet_week_has_neither_crossings_nor_moves(self) -> None:
        prior = _snapshot()
        current = _snapshot()

        diff = diff_snapshots(prior, current)

        assert diff.is_first_run is False
        assert diff.crossings == ()
        assert diff.material_moves == ()
        assert diff.prior_as_of == prior.as_of


def _snap_at(
    as_of: date,
    *,
    compliance_rows: tuple[tuple[str, bool], ...],
) -> WeeklySnapshot:
    """A snapshot at a given as_of, varying only its compliance rows."""
    return replace(_snapshot(compliance_rows=compliance_rows), as_of=as_of)


class TestStandingBreaches:
    """standing_breaches() — consecutive-snapshot runs per failing metric."""

    def test_no_failing_metric_returns_empty(self) -> None:
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(
                ("Annual carry cost", True),
                ("Crash convexity (-25% shock)", True),
            ),
        )

        assert standing_breaches((), current) == ()

    def test_first_week_of_a_breach_is_weeks_one(self) -> None:
        prior = _snap_at(
            date(2026, 7, 29),
            compliance_rows=(("Annual carry cost", True),),
        )
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(("Annual carry cost", False),),
        )

        breaches = standing_breaches((prior,), current)

        assert len(breaches) == 1
        assert breaches[0].metric == "Annual carry cost"
        assert breaches[0].weeks == 1
        assert breaches[0].since == current.as_of

    def test_run_extends_across_multiple_prior_failing_weeks(self) -> None:
        history = tuple(
            _snap_at(
                date(2026, 7, day),
                compliance_rows=(("Annual carry cost", False),),
            )
            for day in (1, 8, 15, 22, 29)
        )
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(("Annual carry cost", False),),
        )

        breaches = standing_breaches(history, current)

        assert breaches[0].weeks == 6
        assert breaches[0].since == date(2026, 7, 1)

    def test_run_stops_at_the_first_passing_snapshot(self) -> None:
        history = (
            _snap_at(
                date(2026, 7, 15),
                compliance_rows=(("Annual carry cost", False),),
            ),
            _snap_at(
                date(2026, 7, 22),
                compliance_rows=(("Annual carry cost", True),),
            ),
            _snap_at(
                date(2026, 7, 29),
                compliance_rows=(("Annual carry cost", False),),
            ),
        )
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(("Annual carry cost", False),),
        )

        breaches = standing_breaches(history, current)

        assert breaches[0].weeks == 2
        assert breaches[0].since == date(2026, 7, 29)

    def test_metric_absent_from_history_stops_the_run(self) -> None:
        history = (
            _snap_at(
                date(2026, 7, 29),
                compliance_rows=(("Crash convexity (-25% shock)", True),),
            ),
        )
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(("Annual carry cost", False),),
        )

        breaches = standing_breaches(history, current)

        assert breaches[0].weeks == 1

    def test_history_order_does_not_matter(self) -> None:
        history = tuple(
            _snap_at(
                date(2026, 7, day),
                compliance_rows=(("Annual carry cost", False),),
            )
            for day in (22, 8, 15, 1, 29)  # deliberately shuffled
        )
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(("Annual carry cost", False),),
        )

        breaches = standing_breaches(history, current)

        assert breaches[0].weeks == 6

    def test_multiple_failing_metrics_each_get_their_own_breach(self) -> None:
        history = (
            _snap_at(
                date(2026, 7, 29),
                compliance_rows=(
                    ("Annual carry cost", False),
                    ("Crash convexity (-25% shock)", True),
                ),
            ),
        )
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(
                ("Annual carry cost", False),
                ("Crash convexity (-25% shock)", False),
            ),
        )

        breaches = standing_breaches(history, current)

        by_metric = {b.metric: b.weeks for b in breaches}
        assert by_metric == {
            "Annual carry cost": 2,
            "Crash convexity (-25% shock)": 1,
        }
