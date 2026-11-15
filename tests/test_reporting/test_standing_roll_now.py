"""A leg that stands at ROLL NOW sets the digest headline (#472).

The headline was ``NO ACTION`` unless something *changed*: a breach, an
unmeasured metric, or a crossing since last week. A leg that had stood at ROLL
NOW for weeks never crosses anything, so the subject line read ``NO ACTION``
above a table that said ROLL NOW. #296 fixed the same shape for IPS breaches by
branching on the standing state; this does it for the roll plan's action.

The rule, as decided: the **action** triggers it, never the verdict, and only
ROLL NOW. ROLL BY is due, not overdue; DELAY is a deliberate deferral; CHECKED
is a cleared review. The week count is consecutive snapshots with a leg at
ROLL NOW, counted the way ``standing_breaches`` counts.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from deltadewa.analysis.roll_planner import ROLL_NOW_LABEL
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.reporting import weekly_report as weekly_report_module
from deltadewa.reporting.program_report import (
    IpsComplianceSection,
)
from deltadewa.reporting.weekly_report import (
    WeeklyDigest,
    _send_digest_email,
    build_weekly_digest,
    render_weekly_digest_html,
    render_weekly_digest_markdown,
)
from deltadewa.reporting.weekly_snapshot import (
    WeeklySnapshot,
    standing_roll_now,
)

from ..test_analysis.test_roll_by import _book, _convexity, _ips, _put
from .test_weekly_report import _AS_OF, _make_report, _prior_snapshot

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltadewa.portfolio.position import OptionPosition
    from deltadewa.reporting.program_report import ProgramReport

_IN_BAND = 15.0


def _roll_now_leg(strike: float = 5_600.0) -> OptionPosition:
    """Inside the 180d window: the time trigger reads ROLL."""
    return _put(days=150, strike=strike)


def _roll_by_leg() -> OptionPosition:
    """In the review buffer at today's strike: ROLL BY the window date."""
    return _put(days=219)


def _delay_leg() -> OptionPosition:
    """In the buffer, nearer the money since entry, convexity in band."""
    return _put(days=219, spot=5_900.0, entry_spot=7_000.0, strike=5_000.0)


def _checked_leg() -> OptionPosition:
    """Outside the buffer; a rally REVIEW whose condition holds."""
    return _put(days=400)


def _hold_leg() -> OptionPosition:
    """Outside the buffer, no rally."""
    return _put(days=400, spot=6_300.0)


def _digest(
    monkeypatch: pytest.MonkeyPatch,
    *positions: OptionPosition,
    history: Sequence[WeeklySnapshot] = (),
    report: ProgramReport | None = None,
    convexity: float = _IN_BAND,
) -> WeeklyDigest:
    """A digest over a real book, with the plan's actions threaded in."""
    _convexity(monkeypatch, convexity)
    ips = _ips()
    return build_weekly_digest(
        report=report
        if report is not None
        else _make_report(within_budget=True),
        roll_records=evaluate_roll_status(_book(*positions), ips),
        history=history,
        as_of=_AS_OF,
        ips_triggers=ips.triggers,
    )


def _last_week(digest: WeeklyDigest, *, weeks_ago: int = 1) -> WeeklySnapshot:
    """The snapshot an identical earlier week would have left behind."""
    return replace(
        digest.snapshot,
        as_of=_AS_OF - timedelta(days=7 * weeks_ago),
    )


def _unchanged(
    monkeypatch: pytest.MonkeyPatch,
    *positions: OptionPosition,
    weeks: int = 1,
    report: ProgramReport | None = None,
) -> WeeklyDigest:
    """This week's digest, after *weeks* weeks of exactly the same book.

    Nothing differs from the prior snapshot, so no crossing fires: what the
    headline says is down to the standing state alone, which is the case #472
    reproduced.
    """
    first = _digest(monkeypatch, *positions, report=report)
    history = tuple(
        _last_week(first, weeks_ago=weeks - i) for i in range(weeks)
    )
    return _digest(monkeypatch, *positions, history=history, report=report)


class TestAStandingRollNowSetsTheHeadline:
    def test_the_reproduction_no_longer_reads_no_action(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Last week already ROLL NOW, nothing else changed: not NO ACTION."""
        digest = _unchanged(monkeypatch, _roll_now_leg())

        assert digest.diff.crossings == ()
        assert digest.headline == "ACTION: PUT 5,600 ROLL NOW (2nd week)"

    def test_it_names_the_leg_when_there_is_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        digest = _digest(monkeypatch, _roll_now_leg(strike=4_200.0))

        assert digest.headline == "ACTION: PUT 4,200 ROLL NOW (1st week)"

    def test_it_names_the_count_when_there_are_several(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        digest = _digest(
            monkeypatch,
            _roll_now_leg(strike=5_600.0),
            _roll_now_leg(strike=5_400.0),
            _hold_leg(),
        )

        assert digest.headline == "ACTION: 2 legs at ROLL NOW (1st week)"
        # The legs are named in the table, not the subject.
        assert [r.action for r in digest.roll_legs].count(ROLL_NOW_LABEL) == 2

    def test_a_rally_review_that_resolved_to_roll_now_counts(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Convexity above the band: the rally REVIEW fails its condition.

        The leg's verdict is REVIEW, not ROLL, and its action is ROLL NOW. The
        rule is on the action, so it sets the headline (#468's case).
        """
        digest = _digest(monkeypatch, _checked_leg(), convexity=25.0)

        assert digest.roll_legs[0].verdict == "REVIEW"
        assert digest.roll_legs[0].action == ROLL_NOW_LABEL
        assert digest.headline == "ACTION: PUT 5,600 ROLL NOW (1st week)"

    def test_it_sits_above_a_crossing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A leg newly at ROLL NOW also crosses; the standing state leads."""
        quiet = _digest(monkeypatch, _hold_leg())
        digest = _digest(
            monkeypatch,
            _roll_now_leg(),
            history=(_last_week(quiet),),
        )

        assert digest.diff.crossings
        assert digest.headline == "ACTION: PUT 5,600 ROLL NOW (1st week)"


class TestOnlyRollNowTriggersIt:
    """ROLL BY, DELAY and CHECKED never set the headline (#472)."""

    @pytest.mark.parametrize(
        ("leg", "action"),
        [
            (_roll_by_leg, "ROLL BY"),
            (_delay_leg, "DELAY"),
            (_checked_leg, "CHECKED"),
            (_hold_leg, None),
        ],
        ids=["roll by", "delay", "checked", "hold"],
    )
    def test_the_headline_stays_quiet(
        self,
        monkeypatch: pytest.MonkeyPatch,
        leg,
        action: str | None,
    ) -> None:
        digest = _unchanged(monkeypatch, leg(), weeks=3)

        shown = digest.roll_legs[0].action
        assert (shown or "").startswith(action or "")
        assert ROLL_NOW_LABEL not in (shown or "")
        assert digest.headline == "NO ACTION"
        assert digest.standing_roll is None


class TestPrecedence:
    """BREACH > INCOMPLETE > standing ROLL NOW > crossing > NO ACTION."""

    def test_a_breach_outranks_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        digest = _digest(
            monkeypatch,
            _roll_now_leg(),
            report=_make_report(within_budget=False),
        )

        assert digest.headline.startswith("BREACH")

    def test_an_unmeasured_metric_outranks_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        base = _make_report(within_budget=True)
        rows = (
            replace(base.ips_compliance.rows[0], passes=True),
            replace(base.ips_compliance.rows[1], passes=None, actual="—"),
        )
        report = replace(
            base,
            ips_compliance=IpsComplianceSection(rows=rows, all_pass=False),
        )

        digest = _digest(monkeypatch, _roll_now_leg(), report=report)

        assert digest.headline.startswith("INCOMPLETE")

    def test_the_stale_data_prefix_composes_with_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        digest = _digest(
            monkeypatch,
            _roll_now_leg(),
            report=_make_report(data_quality="STALE", within_budget=True),
        )

        assert digest.headline == (
            "STALE DATA — ACTION: PUT 5,600 ROLL NOW (1st week)"
        )

    def test_the_subject_line_carries_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The email subject (``_send_digest_email``) is the headline."""
        digest = _unchanged(monkeypatch, _roll_now_leg(), weeks=2)
        for key, value in {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USERNAME": "program@example.com",
            "SMTP_PASSWORD": "fake-smtp-password",
            "REPORT_EMAIL_TO": "ic@example.com",
            "REPORT_EMAIL_FROM": "program@example.com",
        }.items():
            monkeypatch.setenv(key, value)

        with (
            patch.object(weekly_report_module, "send_email") as sent,
            patch.object(weekly_report_module, "ping"),
        ):
            failure = _send_digest_email(digest, "<p>body</p>", _AS_OF)

        assert failure is None
        subject = sent.call_args.args[0].subject
        assert subject == (
            "Weekly Hedge Digest — ACTION: PUT 5,600 ROLL NOW (3rd week)"
            f" ({_AS_OF})"
        )
        assert "NO ACTION" not in subject


class TestTheWeekCount:
    """Consecutive snapshots with a leg at ROLL NOW, the way breaches count."""

    def test_the_count_tracks_the_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        digest = _unchanged(monkeypatch, _roll_now_leg(), weeks=4)

        assert digest.headline == "ACTION: PUT 5,600 ROLL NOW (5th week)"
        assert digest.standing_roll is not None
        assert digest.standing_roll.weeks == 5
        assert digest.standing_roll.since == _AS_OF - timedelta(days=28)

    def test_a_week_without_a_roll_now_resets_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        now = _digest(monkeypatch, _roll_now_leg())
        quiet = _digest(monkeypatch, _hold_leg())
        history = (
            _last_week(now, weeks_ago=3),
            _last_week(quiet, weeks_ago=2),
            _last_week(now, weeks_ago=1),
        )

        digest = _digest(monkeypatch, _roll_now_leg(), history=history)

        assert digest.headline == "ACTION: PUT 5,600 ROLL NOW (2nd week)"

    @pytest.mark.parametrize(
        "leg",
        [_roll_by_leg, _delay_leg, _checked_leg],
        ids=["roll by", "delay", "checked"],
    )
    def test_a_roll_by_delay_or_checked_week_ends_the_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        leg,
    ) -> None:
        now = _digest(monkeypatch, _roll_now_leg())
        other = _digest(monkeypatch, leg())
        history = (
            _last_week(now, weeks_ago=2),
            _last_week(other, weeks_ago=1),
        )

        digest = _digest(monkeypatch, _roll_now_leg(), history=history)

        assert "(1st week)" in digest.headline

    def test_only_snapshots_before_this_one_are_counted(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        now = _digest(monkeypatch, _roll_now_leg())
        # A snapshot at or after this run's date is not part of its history.
        future = replace(now.snapshot, as_of=_AS_OF + timedelta(days=7))
        same_day = replace(now.snapshot, as_of=_AS_OF)

        run = standing_roll_now((future, same_day), now.snapshot)

        assert run is not None
        assert run.weeks == 1


class TestSnapshotsWrittenBeforeActionsWereRecorded:
    """Snapshots from before 0.10.0 have no action and must still load."""

    def _old(
        self,
        *,
        weeks_ago: int,
        verdict: str,
    ) -> WeeklySnapshot:
        """A snapshot as 0.9.x wrote it, round-tripped through its JSON."""
        data = replace(
            _prior_snapshot(),
            as_of=_AS_OF - timedelta(days=7 * weeks_ago),
            worst_roll_verdict=verdict,
            worst_roll_action=None,
        ).to_json_dict()
        data.pop("worst_roll_action")
        return WeeklySnapshot.from_json_dict(json.loads(json.dumps(data)))

    def test_a_file_without_the_field_loads_with_no_action(self) -> None:
        old = self._old(weeks_ago=1, verdict="ROLL")

        assert old.worst_roll_action is None

    def test_a_roll_verdict_counts_across_the_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verdict ROLL is always ROLL NOW, so the fallback counts it."""
        history = (
            self._old(weeks_ago=2, verdict="ROLL"),
            self._old(weeks_ago=1, verdict="ROLL"),
        )

        digest = _digest(monkeypatch, _roll_now_leg(), history=history)

        assert digest.headline == "ACTION: PUT 5,600 ROLL NOW (3rd week)"

    def test_a_review_week_with_no_action_may_hide_a_roll_now(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A REVIEW-driven ROLL NOW is invisible in old history: say so."""
        history = (self._old(weeks_ago=1, verdict="REVIEW"),)

        digest = _digest(monkeypatch, _roll_now_leg(), history=history)

        assert digest.standing_roll is not None
        assert digest.standing_roll.weeks == 1
        assert digest.standing_roll.may_be_longer is True
        markdown = render_weekly_digest_markdown(digest)
        html = render_weekly_digest_html(digest)
        assert "may be longer than shown" in markdown
        assert "may be longer than shown" in html

    @pytest.mark.parametrize("verdict", ["HOLD", "MONITOR"])
    def test_a_quiet_old_week_is_a_real_end_to_the_run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        verdict: str,
    ) -> None:
        """Below REVIEW a leg cannot have been at ROLL NOW: nothing to say."""
        history = (self._old(weeks_ago=1, verdict=verdict),)

        digest = _digest(monkeypatch, _roll_now_leg(), history=history)

        assert digest.standing_roll is not None
        assert digest.standing_roll.may_be_longer is False
        assert "may be longer than shown" not in (
            render_weekly_digest_markdown(digest)
        )

    def test_a_recorded_action_is_never_flagged(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A CHECKED week is a recorded end to the run, not a gap in it."""
        checked = _digest(monkeypatch, _checked_leg())
        history = (_last_week(checked),)

        digest = _digest(monkeypatch, _roll_now_leg(), history=history)

        assert digest.standing_roll is not None
        assert digest.standing_roll.may_be_longer is False


class TestTheWorstLegCarriesRollNowWheneverAnyLegDoes:
    """The snapshot keeps one leg; the run is only sound if that holds.

    ``standing_roll_now`` reads the snapshot's worst leg. That equals "some leg
    is at ROLL NOW" because the worst leg is chosen by verdict, then by action
    urgency, and every verdict-ROLL leg is ROLL NOW. Pinned over the mixes that
    could break it, rather than left to the argument.
    """

    @pytest.mark.parametrize(
        ("legs", "convexity"),
        [
            ((_roll_now_leg,), _IN_BAND),
            ((_roll_by_leg, _roll_now_leg), _IN_BAND),
            ((_roll_now_leg, _roll_by_leg), _IN_BAND),
            ((_delay_leg, _roll_now_leg), _IN_BAND),
            ((_checked_leg, _roll_now_leg), _IN_BAND),
            ((_hold_leg, _roll_by_leg, _checked_leg), _IN_BAND),
            ((_roll_by_leg, _checked_leg), 25.0),
            ((_roll_by_leg, _hold_leg), 25.0),
            ((_checked_leg, _roll_by_leg), 25.0),
            ((_hold_leg, _roll_by_leg), 5.0),
        ],
        ids=[
            "one leg",
            "roll by then roll now",
            "roll now then roll by",
            "delay then roll now",
            "checked then roll now",
            "no roll now anywhere",
            "rally review fails, roll by beside it",
            "rally review fails on a hold's neighbour",
            "checked leg fails its review beside a roll by",
            "convexity below the band rolls every leg",
        ],
    )
    def test_the_snapshot_says_roll_now_exactly_when_a_leg_does(
        self,
        monkeypatch: pytest.MonkeyPatch,
        legs,
        convexity: float,
    ) -> None:
        digest = _digest(
            monkeypatch,
            *(leg() for leg in legs),
            convexity=convexity,
        )

        any_leg = any(r.action == ROLL_NOW_LABEL for r in digest.roll_legs)
        assert (digest.snapshot.worst_roll_action == ROLL_NOW_LABEL) is any_leg
        assert (digest.standing_roll is not None) is any_leg
        # A first run: no crossing can fire, so the standing state alone
        # decides between the two headlines.
        if any_leg:
            assert "ROLL NOW" in digest.headline
        else:
            assert digest.headline == "NO ACTION"


def test_a_digest_without_the_ips_has_no_actions_and_no_standing_run() -> None:
    """Without ``ips_triggers`` no action is decided, so none can stand."""
    digest = build_weekly_digest(
        report=_make_report(within_budget=True),
        roll_records=(),
        history=(),
        as_of=_AS_OF,
    )

    assert digest.standing_roll is None
    assert digest.headline == "NO ACTION"


def test_the_label_the_run_compares_is_the_one_the_plan_prints() -> None:
    assert ROLL_NOW_LABEL == "ROLL NOW"
