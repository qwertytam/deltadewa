"""Tests for deltadewa.reporting.weekly_snapshot."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from deltadewa.analysis.convexity_band import (
    ConvexityGrade,
    ConvexityGrading,
)
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
    VegaSection,
)
from deltadewa.reporting.weekly_snapshot import (
    WeeklySnapshot,
    diff_snapshots,
    snapshot_from_report,
    standing_breaches,
)

_AS_OF = date(2026, 8, 5)

# Test-local only: lets _make_report's needs_alarm default from
# data_quality the way the old (pre-#398) combined-quality check did,
# so every existing data_quality= call site below keeps exercising the
# same scenario without having to also pass needs_alarm explicitly. Real
# needs_alarm is computed by analysis.provenance.assess_freshness — see
# TestDiffSnapshotsCrossings' explicit-needs_alarm tests for the case
# this default can't represent (data_quality and needs_alarm diverging).
_DEFAULT_STALE_OR_WORSE = frozenset({"STALE", "STATIC", "UNAVAILABLE"})

_GRADE_FOR_MEETS = {
    True: ConvexityGrade.WITHIN,
    False: ConvexityGrade.BELOW,
    None: ConvexityGrade.UNMEASURED,
}


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
    needs_alarm: bool | None = None,
    compliance_rows: tuple[tuple[str, bool | None], ...] = (
        ("Annual carry cost", True),
        ("Crash convexity (-25% shock)", True),
    ),
) -> ProgramReport:
    if needs_alarm is None:
        needs_alarm = data_quality in _DEFAULT_STALE_OR_WORSE
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
            # The snapshot tests drive the grade directly: they are about
            # diffing two snapshots, not about grading a reading.
            convexity=ConvexityGrading(
                value_pct=convexity_pct,
                min_pct=15.0,
                max_pct=25.0,
                shock_pct=-25.0,
                grade=_GRADE_FOR_MEETS[meets_target],
            ),
            premium_paid=300_000.0,
            premium_basis="paid",
        ),
        vega=VegaSection(
            sufficiency_pct=2.5,
            floor_pct=1.5,
            ceiling_pct=4.0,
            meets_target=True,
        ),
        market_context=MarketContextSection(
            vix=vix,
            regime_label=regime_label,
            skew_percentile=skew_percentile,
            hedge_cost_verdict=hedge_cost_verdict,
            data_quality=data_quality,
            needs_alarm=needs_alarm,
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
        rally_status="OK",
        worst_rally_pct=3.0,
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
            rally_status="OK",
            worst_rally_pct=3.0,
            first_as_of=date(2026, 7, 1),
            cumulative_carry_cost=5_000.0,
        )

        assert snap.as_of == report.header.as_of
        assert snap.first_as_of == date(2026, 7, 1)
        assert snap.data_quality == report.market_context.data_quality
        assert snap.data_quality_alarm == report.market_context.needs_alarm
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

    def test_missing_data_quality_alarm_key_reconstructs_from_the_string(
        self,
    ) -> None:
        """#398: a pre-#398 snapshot file has no real field to read back.

        ``from_json_dict`` falls back to the file's own old
        combined_quality-membership check rather than raising or
        silently defaulting to a fixed value.
        """
        stale_before_398 = _snapshot(data_quality="STALE").to_json_dict()
        del stale_before_398["data_quality_alarm"]
        healthy_before_398 = _snapshot(data_quality="LIVE").to_json_dict()
        del healthy_before_398["data_quality_alarm"]

        assert WeeklySnapshot.from_json_dict(
            stale_before_398,
        ).data_quality_alarm
        assert not WeeklySnapshot.from_json_dict(
            healthy_before_398,
        ).data_quality_alarm


class TestTheWorstLegsActionIsCarriedNotDiffed:
    """#461: the plan's action rides with the worst leg, for rendering only.

    ``worst_roll_action`` is the roll plan's own words for the worst leg
    (``ROLL BY 2026-12-22``). Like ``worst_roll_reason`` it explains a
    crossing and is never one: the verdict word is what crosses, and an
    action that carries a date would otherwise fire every time the date text
    changed.
    """

    def test_a_file_written_before_the_field_existed_still_loads(self) -> None:
        import json

        on_disk = json.loads(json.dumps(_snapshot().to_json_dict()))
        del on_disk["worst_roll_action"]

        restored = WeeklySnapshot.from_json_dict(on_disk)

        assert restored.worst_roll_action is None
        assert restored.worst_roll_verdict == "HOLD"

    def test_the_action_survives_the_json_file(self) -> None:
        import json

        snap = replace(_snapshot(), worst_roll_action="ROLL BY 2026-12-22")

        restored = WeeklySnapshot.from_json_dict(
            json.loads(json.dumps(snap.to_json_dict())),
        )

        assert restored.worst_roll_action == "ROLL BY 2026-12-22"
        assert restored == snap

    def test_snapshot_from_report_carries_it(self) -> None:
        snap = snapshot_from_report(
            _make_report(),
            decision_verdict="MAINTAIN",
            worst_roll_verdict="REVIEW",
            worst_roll_leg="PUT 5,600",
            worst_roll_reason="219d to maturity",
            worst_roll_action="ROLL BY 2026-12-22",
            expired_leg_count=0,
            rally_status="OK",
            worst_rally_pct=3.0,
            first_as_of=_AS_OF,
            cumulative_carry_cost=1_000.0,
        )

        assert snap.worst_roll_action == "ROLL BY 2026-12-22"

    def test_a_crossing_names_the_action_beside_the_leg(self) -> None:
        prior = _snapshot()
        current = replace(
            prior,
            worst_roll_verdict="REVIEW",
            worst_roll_leg="PUT 5,600",
            worst_roll_reason="219d to maturity",
            worst_roll_action="ROLL BY 2026-12-22",
        )

        (change,) = [
            c
            for c in diff_snapshots(prior, current).crossings
            if c.label == "Worst roll verdict"
        ]

        assert change.detail == (
            "HOLD \u2192 REVIEW "
            "(PUT 5,600, ROLL BY 2026-12-22, 219d to maturity)"
        )

    def test_a_changed_action_on_an_unchanged_verdict_is_not_a_crossing(
        self,
    ) -> None:
        prior = replace(_snapshot(), worst_roll_action="ROLL BY 2026-12-22")
        current = replace(prior, worst_roll_action="ROLL BY 2027-01-05")

        diff = diff_snapshots(prior, current)

        assert all(c.label != "Worst roll verdict" for c in diff.crossings)


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

    def test_hand_entered_aging_does_not_cross_despite_stale_string(
        self,
    ) -> None:
        """#398: the alarm flag drives this, not the STALE_OR_WORSE string.

        Both weeks display ``data_quality == "STALE"`` (as a merely-
        ``AGING`` hand-entered input maps through ``combined_quality``),
        but neither actually crosses the #393/#398 alarm threshold — no
        crossing line should fire on an unchanged, quiet condition.
        """
        prior = _snapshot(data_quality="STALE", needs_alarm=False)
        current = _snapshot(data_quality="STALE", needs_alarm=False)

        diff = diff_snapshots(prior, current)

        assert not any(c.label == "Data quality" for c in diff.crossings)

    def test_alarm_state_flip_crosses_even_if_the_string_does_not(
        self,
    ) -> None:
        """The reverse of the case above: the flag is what actually moved."""
        prior = _snapshot(data_quality="STALE", needs_alarm=False)
        current = _snapshot(data_quality="STALE", needs_alarm=True)

        diff = diff_snapshots(prior, current)

        assert any(c.label == "Data quality" for c in diff.crossings)


class TestTheDataQualityCrossingNamesTheAlarm:
    """#462: the line says what crossed, which is the alarm, not the string.

    ``data_quality`` is the worst-of merged grade. It can sit at ``STALE``
    for weeks while the alarm flips, and the line used to print it on both
    sides: ``STALE -> STALE``, a change that describes nothing.
    """

    @staticmethod
    def _detail(prior: WeeklySnapshot, current: WeeklySnapshot) -> str:
        (change,) = [
            c
            for c in diff_snapshots(prior, current).crossings
            if c.label == "Data quality"
        ]
        return change.detail

    def test_alarm_raised_while_the_string_stays_stale(self) -> None:
        prior = _snapshot(data_quality="STALE", needs_alarm=False)
        current = _snapshot(data_quality="STALE", needs_alarm=True)

        detail = self._detail(prior, current)

        assert detail == "alarm raised (data quality STALE)"
        assert "STALE \u2192 STALE" not in detail

    def test_alarm_cleared_while_the_string_stays_stale(self) -> None:
        prior = _snapshot(data_quality="STALE", needs_alarm=True)
        current = _snapshot(data_quality="STALE", needs_alarm=False)

        assert self._detail(prior, current) == (
            "alarm cleared (data quality STALE)"
        )

    def test_the_string_is_an_arrow_when_it_actually_moved(self) -> None:
        raised = self._detail(
            _snapshot(data_quality="CACHED", needs_alarm=False),
            _snapshot(data_quality="STALE", needs_alarm=True),
        )
        cleared = self._detail(
            _snapshot(data_quality="STALE", needs_alarm=True),
            _snapshot(data_quality="LIVE", needs_alarm=False),
        )

        assert raised == "alarm raised (data quality CACHED \u2192 STALE)"
        assert cleared == "alarm cleared (data quality STALE \u2192 LIVE)"

    @pytest.mark.parametrize(
        "quality",
        ["LIVE", "CACHED", "STALE", "STATIC", "UNAVAILABLE"],
    )
    @pytest.mark.parametrize("raised", [True, False])
    def test_no_line_ever_repeats_one_grade_on_both_sides(
        self,
        quality: str,
        raised: bool,
    ) -> None:
        import re

        prior = _snapshot(data_quality=quality, needs_alarm=not raised)
        current = _snapshot(data_quality=quality, needs_alarm=raised)

        detail = self._detail(prior, current)

        assert re.search(r"(\w+) \u2192 \1", detail) is None


class TestSkewWindow:
    """The skew percentile's window travels with it (8c, #317)."""

    def test_pre_8c_file_reads_back_as_252_sessions(self) -> None:
        """A snapshot with no window key was ranked over 252 — a fact.

        Every skew percentile before 8c was ranked over the unsourced 252
        default no caller ever overrode, so this is not a guess.
        """
        before_8c = _snapshot().to_json_dict()
        del before_8c["skew_lookback_days"]

        restored = WeeklySnapshot.from_json_dict(before_8c)

        assert restored.skew_lookback_days == 252

    def test_window_round_trips(self) -> None:
        snap = replace(_snapshot(), skew_lookback_days=1260)

        restored = WeeklySnapshot.from_json_dict(snap.to_json_dict())

        assert restored.skew_lookback_days == 1260

    def test_window_change_reports_the_window_not_a_move(self) -> None:
        """252 -> 1260 is a different number, not a moved one.

        The 2026-11-06 reading was 90.5 on 252 sessions and 87.6 on 1260;
        a diff across the switch must not report a market move.
        """
        prior = replace(
            _snapshot(skew_percentile=0.905),
            skew_lookback_days=252,
        )
        current = replace(
            _snapshot(skew_percentile=0.20),  # would be a huge "move"
            skew_lookback_days=1260,
        )

        diff = diff_snapshots(prior, current)

        skew = [m for m in diff.material_moves if m.label == "SKEW percentile"]
        assert len(skew) == 1
        assert "trailing 1y → trailing 5y" in skew[0].detail
        assert "not comparable" in skew[0].detail
        assert "→ 20.00%" not in skew[0].detail

    def test_same_window_move_is_still_reported(self) -> None:
        prior = replace(_snapshot(skew_percentile=0.30), skew_lookback_days=252)
        current = replace(
            _snapshot(skew_percentile=0.80),
            skew_lookback_days=252,
        )

        diff = diff_snapshots(prior, current)

        skew = [m for m in diff.material_moves if m.label == "SKEW percentile"]
        assert len(skew) == 1
        assert "30.00% → 80.00%" in skew[0].detail


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
    compliance_rows: tuple[tuple[str, bool | None], ...],
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


class TestAnUnmeasuredMetricIsNotABreach:
    """#433: ``None`` in a compliance row is unmeasured, not failing."""

    _CONVEXITY = "Crash convexity (-25% shock)"

    def test_an_unmeasured_row_starts_no_standing_breach(self) -> None:
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(
                ("Annual carry cost", True),
                (self._CONVEXITY, None),
            ),
        )

        assert standing_breaches((), current) == ()

    def test_an_unmeasured_week_ends_a_run_of_breaches(self) -> None:
        """Only a recorded breach extends a run; unmeasured is a gap."""
        history = (
            _snap_at(
                date(2026, 7, 22),
                compliance_rows=((self._CONVEXITY, False),),
            ),
            _snap_at(
                date(2026, 7, 29),
                compliance_rows=((self._CONVEXITY, None),),
            ),
        )
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=((self._CONVEXITY, False),),
        )

        (breach,) = standing_breaches(history, current)

        assert breach.weeks == 1

    def test_pass_to_unmeasured_is_a_crossing_that_says_so(self) -> None:
        prior = _snap_at(
            date(2026, 7, 29),
            compliance_rows=(
                ("Annual carry cost", True),
                (self._CONVEXITY, True),
            ),
        )
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(
                ("Annual carry cost", True),
                (self._CONVEXITY, None),
            ),
        )

        diff = diff_snapshots(prior, current)
        details = {c.label: c.detail for c in diff.crossings}

        assert details[f"IPS compliance: {self._CONVEXITY}"] == (
            "pass \u2192 not measured"
        )
        assert details["IPS compliance (overall)"] == (
            "all pass \u2192 a metric not measured"
        )

    def test_pass_to_fail_still_says_failing(self) -> None:
        prior = _snap_at(
            date(2026, 7, 29),
            compliance_rows=((self._CONVEXITY, True),),
        )
        current = _snap_at(
            date(2026, 8, 5),
            compliance_rows=((self._CONVEXITY, False),),
        )

        details = {
            c.label: c.detail for c in diff_snapshots(prior, current).crossings
        }

        assert details["IPS compliance (overall)"] == (
            "all pass \u2192 a metric failing"
        )


class TestUnmeasuredRowsSurviveTheJsonFile:
    """#433: an unmeasured row is ``null`` on disk and loads back unchanged."""

    def test_a_none_row_round_trips_through_real_json(self) -> None:
        import json

        snap = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(
                ("Annual carry cost", True),
                ("Crash convexity (-25% shock)", None),
            ),
        )

        restored = WeeklySnapshot.from_json_dict(
            json.loads(json.dumps(snap.to_json_dict())),
        )

        assert restored.ips_compliance_rows == snap.ips_compliance_rows
        assert restored.ips_compliance_rows[1][1] is None

    def test_a_pre_433_file_with_boolean_rows_still_loads(self) -> None:
        import json

        snap = _snap_at(
            date(2026, 8, 5),
            compliance_rows=(("Annual carry cost", False),),
        )
        on_disk = json.loads(json.dumps(snap.to_json_dict()))

        assert WeeklySnapshot.from_json_dict(on_disk).ips_compliance_rows == (
            ("Annual carry cost", False),
        )
