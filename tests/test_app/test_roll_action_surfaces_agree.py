"""Every surface that shows a leg's verdict shows the same action and date.

#461: PUT 5,600 at 219 days read ROLL NOW on the roll plan beside a rally
sentence that said "no roll", while ``/monitor``, the roll status table and
the digest said only REVIEW. The action now reaches every one of them, asked
of one function (``roll_planner.leg_action_label``), and the reason beside it
states Rule 1's rule (#463). This pins that the five places print one
statement for one leg: the action, the window-open date, and the trigger
named.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from deltadewa.analysis.roll_planner import (
    RollAction,
    build_roll_plan,
    leg_action_label,
    leg_reason,
)
from deltadewa.analysis.roll_status import (
    RollStatusRecord,
    evaluate_roll_status,
    roll_window_opens,
    verdict_reason,
)
from deltadewa.app.pages import monitor
from deltadewa.app.pages.design.planning import roll_plan, roll_status
from deltadewa.reporting.weekly_report import (
    build_weekly_digest,
    render_weekly_digest_markdown,
)
from tests.clock_helpers import days_from_today

from ..test_analysis.test_roll_by import _book, _convexity, _ips, _put
from ..test_reporting.test_weekly_report import (
    _AS_OF,
    _make_report,
    _prior_snapshot,
)

_RULE = "approaching the roll window (opens at 180d; review starts at 270d)"


def _all_text(component: Any) -> str:
    """Concatenate every string under a Dash component tree."""
    children = getattr(component, "children", component)
    if isinstance(children, str):
        return children
    if isinstance(children, list | tuple):
        return " ".join(_all_text(c) for c in children)
    return "" if children is None else _all_text(children)


def _leg(
    monkeypatch: pytest.MonkeyPatch,
    days: int,
) -> tuple[RollStatusRecord, list]:
    """One long put's roll status, and the whole book's roll plan."""
    position = _put(days=days)
    _convexity(monkeypatch, 15.0)
    ips = _ips()
    (status,) = evaluate_roll_status(_book(position), ips)
    return status, build_roll_plan(_book(position), ips)


class TestFiveSurfacesOneStatement:
    """PUT 5,600: ROLL BY the window-open date, said the same everywhere."""

    def test_every_surface_prints_the_one_action_and_date(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ips = _ips()
        status, plan = _leg(monkeypatch, 219)
        (planned,) = plan
        opens = days_from_today(219).date() - timedelta(days=180)
        label = f"ROLL BY {opens.isoformat()}"

        # The plan, the source.
        assert planned.action is RollAction.ROLL_BY
        assert planned.action_label == label
        assert roll_window_opens(status) == opens

        # /design: the roll plan's badge, and the status table's verdict cell.
        plan_row = _all_text(roll_plan._roll_plan_row(planned))
        status_row = _all_text(
            roll_status._roll_record_row(status, ips.triggers)
        )
        assert label in plan_row
        assert label in status_row

        # /monitor: the decision row beside the verdict badge.
        monitor_row = _all_text(monitor._decision_row(status, ips.triggers))
        assert label in monitor_row

        # The digest's per-leg row and the snapshot's worst leg.
        digest = build_weekly_digest(
            report=_make_report(),
            roll_records=[status],
            history=(_prior_snapshot(),),
            as_of=_AS_OF,
            ips_triggers=ips.triggers,
        )
        (row,) = digest.roll_legs
        assert row.action == label
        assert digest.snapshot.worst_roll_action == label
        assert f"| REVIEW | {label} |" in render_weekly_digest_markdown(digest)

        # And the function they all ask.
        assert leg_action_label(status, ips_triggers=ips.triggers) == label

    def test_the_verdict_surfaces_state_rule_one_beside_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Action, date and the rule that earned them, in one reading."""
        ips = _ips()
        status, _ = _leg(monkeypatch, 219)

        assert _RULE in verdict_reason(status)
        assert _RULE in _all_text(monitor._decision_row(status, ips.triggers))
        assert _RULE in _all_text(
            roll_status._roll_record_row(status, ips.triggers),
        )
        digest = build_weekly_digest(
            report=_make_report(),
            roll_records=[status],
            as_of=_AS_OF,
            ips_triggers=ips.triggers,
        )
        assert _RULE in digest.roll_legs[0].reason

    def test_the_plan_names_the_time_trigger_not_the_rally(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, (planned,) = _leg(monkeypatch, 219)

        assert planned.driver == "time"
        assert planned.rationale.startswith("Time trigger:")
        assert "no roll" not in planned.rationale.lower()

    @pytest.mark.parametrize(
        ("days", "label_start"),
        [(150, "ROLL NOW"), (400, "CHECKED")],
        ids=["inside the window", "rally review alone"],
    )
    def test_the_unchanged_actions_agree_too(
        self,
        monkeypatch: pytest.MonkeyPatch,
        days: int,
        label_start: str,
    ) -> None:
        """ROLL NOW still means now; CHECKED is still CHECKED. Said once."""
        ips = _ips()
        status, (planned,) = _leg(monkeypatch, days)

        assert planned.action_label == label_start
        assert label_start in _all_text(
            monitor._decision_row(status, ips.triggers),
        )
        assert label_start in _all_text(
            roll_status._roll_record_row(status, ips.triggers),
        )
        assert label_start in _all_text(roll_plan._roll_plan_row(planned))

    def test_a_leg_with_nothing_to_do_shows_no_action(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No "HOLD" repeated beside a HOLD verdict: it would say it twice."""
        ips = _ips()
        _convexity(monkeypatch, 15.0)
        # 400d is outside the buffer and the spot has not moved from entry.
        quiet = _put(days=400, spot=6_300.0)
        (status,) = evaluate_roll_status(_book(quiet), ips)

        assert leg_action_label(status, ips_triggers=ips.triggers) is None
        assert "decision-action" not in repr(
            monitor._decision_row(status, ips.triggers),
        )


class TestTheReasonBesideAnActionIsTheTriggerThatDecidedIt:
    """Time and rally both at REVIEW, convexity above the band.

    The verdict is REVIEW and names the time trigger (first in precedence).
    The rally's own condition fails, so the action is ROLL NOW and the rally
    decided it. A reason about the review buffer beside ROLL NOW would answer
    "why now?" with the wrong trigger, so every surface quotes the rally.
    """

    def test_every_surface_quotes_the_rally_beside_roll_now(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ips = _ips()
        _convexity(monkeypatch, 25.0)  # above the 10-20% band
        (status,) = evaluate_roll_status(_book(_put(days=219)), ips)
        (planned,) = build_roll_plan(_book(_put(days=219)), ips)

        assert status.verdict.value == "REVIEW"
        assert planned.action is RollAction.ROLL_NOW
        assert planned.driver == "rally"
        rally = status.rally_trigger.reason
        time_reason = status.time_trigger.reason

        monitor_row = _all_text(monitor._decision_row(status, ips.triggers))
        assert "ROLL NOW" in monitor_row
        assert rally in monitor_row
        assert time_reason not in monitor_row

        digest = build_weekly_digest(
            report=_make_report(),
            roll_records=[status],
            as_of=_AS_OF,
            ips_triggers=ips.triggers,
        )
        (row,) = digest.roll_legs
        assert row.action == "ROLL NOW"
        assert row.reason == rally
        assert digest.snapshot.worst_roll_reason == rally

        # The status table keeps all three readings, so nothing is hidden.
        table_row = _all_text(
            roll_status._roll_record_row(status, ips.triggers),
        )
        assert rally in table_row
        assert time_reason in table_row

    def test_where_the_triggers_agree_the_verdicts_reason_is_unchanged(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ips = _ips()
        status, _ = _leg(monkeypatch, 219)  # convexity in band: ROLL BY

        monitor_row = _all_text(monitor._decision_row(status, ips.triggers))

        assert verdict_reason(status) in monitor_row


class TestTheNewActionIsExplainedAndFits:
    """What the screenshots found (#461): a new word needs a gloss and room.

    The first render wrapped ``ROLL BY 2026-12-22`` onto three lines, splitting
    the date, and the roll plan's intro explained DELAY and CHECKED but not the
    action that was new. A smoke test saw neither.
    """

    def test_the_roll_plan_intro_says_what_roll_by_is(self) -> None:
        text = _all_text(roll_plan._roll_plan_panel_view([]))

        assert "ROLL BY the date the window opens" in text
        assert "ROLL NOW is kept for a trigger that has reached ROLL" in text

    def test_the_badge_cannot_wrap_its_date(self) -> None:
        from pathlib import Path

        css = (
            Path(monitor.__file__).parent.parent / "assets" / "deltadewa.css"
        ).read_text(encoding="utf-8")
        start = css.index(".verdict-badge--roll_by")
        rule = css[start : css.index("}", start)]

        assert "white-space: nowrap" in rule


class TestARallyReviewAcrossTheConvexityGrid:
    """{rally REVIEW} x {convexity WITHIN, BELOW, ABOVE, UNMEASURED} (#471).

    The REVIEW band says "roll strikes up if the convexity target is no longer
    met". The answer decides the action: met is CHECKED, not met is ROLL NOW,
    and no answer (crash convexity unmeasured) is **no roll action**, with the
    sentence saying the condition could not be checked. It is not CHECKED,
    which asserts the condition was checked and holds, and not ROLL NOW, which
    would repeat the failure #433 removed (an unmeasurable reading producing
    the most urgent action).

    Each cell is asked of the one function every surface calls
    (``leg_action_label`` / ``leg_reason``) and then read off the roll plan,
    the roll status table, ``/monitor`` and the digest, so the four cannot
    word one leg's case differently.
    """

    # 400d is outside the review buffer and the spot is +11.1% since entry,
    # inside Rule 2's REVIEW band: only the rally trigger has fired, apart
    # from what convexity does to the convexity trigger itself.
    _DAYS = 400
    _CHECKED_SENTENCE = "this band's condition could not be checked"

    @pytest.mark.parametrize(
        ("convexity", "verdict", "label"),
        [
            (15.0, "REVIEW", "CHECKED"),
            # Below the band the convexity trigger itself grades ROLL.
            (5.0, "ROLL", "ROLL NOW"),
            (25.0, "REVIEW", "ROLL NOW"),
            (None, "REVIEW", None),
        ],
        ids=["within", "below", "above", "unmeasured"],
    )
    def test_every_surface_prints_the_one_action(
        self,
        monkeypatch: pytest.MonkeyPatch,
        convexity: float | None,
        verdict: str,
        label: str | None,
    ) -> None:
        ips = _ips()
        _convexity(monkeypatch, convexity)
        position = _put(days=self._DAYS)
        (status,) = evaluate_roll_status(_book(position), ips)
        (planned,) = build_roll_plan(_book(position), ips)

        assert status.rally_trigger.verdict.value == "REVIEW"
        assert status.verdict.value == verdict
        # The one function.
        assert leg_action_label(status, ips_triggers=ips.triggers) == label

        # The roll plan.
        assert planned.action_label == (label or "HOLD")
        # The roll status table and /monitor: the action beside the badge.
        table = _all_text(roll_status._roll_record_row(status, ips.triggers))
        monitor_row = _all_text(monitor._decision_row(status, ips.triggers))
        # The digest's row and the snapshot's worst leg.
        digest = build_weekly_digest(
            report=_make_report(),
            roll_records=[status],
            as_of=_AS_OF,
            ips_triggers=ips.triggers,
        )
        (row,) = digest.roll_legs
        markdown = render_weekly_digest_markdown(digest)

        assert row.action == label
        assert digest.snapshot.worst_roll_action == label
        assert row.verdict == verdict
        if label is None:
            # A verdict with no action, and every surface says why.
            assert "| REVIEW | \u2014 |" in markdown
            for text in (
                planned.rationale,
                table,
                monitor_row,
                row.reason,
            ):
                assert self._CHECKED_SENTENCE in text
                assert "gives no roll action" in text
            assert "ROLL NOW" not in table + monitor_row + markdown
            assert "CHECKED" not in table + monitor_row + markdown
        else:
            assert label in table
            assert label in monitor_row
            assert f"| {verdict} | {label} |" in markdown
            for text in (planned.rationale, table, monitor_row, row.reason):
                assert self._CHECKED_SENTENCE not in text

    def test_the_sentence_is_one_sentence_on_every_surface(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The plan quotes the trigger's own reason, as CHECKED does."""
        ips = _ips()
        _convexity(monkeypatch, None)
        position = _put(days=self._DAYS)
        (status,) = evaluate_roll_status(_book(position), ips)
        (planned,) = build_roll_plan(_book(position), ips)
        said = status.rally_trigger.reason

        assert said in planned.rationale
        assert said in _all_text(
            roll_status._roll_record_row(status, ips.triggers),
        )
        assert said in _all_text(monitor._decision_row(status, ips.triggers))
        assert leg_reason(status, ips_triggers=ips.triggers) == said

    def test_a_time_trigger_roll_still_reads_roll_now(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The leg's other triggers still decide: the time trigger wins."""
        ips = _ips()
        _convexity(monkeypatch, None)
        position = _put(days=150)
        (status,) = evaluate_roll_status(_book(position), ips)
        (planned,) = build_roll_plan(_book(position), ips)

        assert status.rally_trigger.verdict.value == "REVIEW"
        assert leg_action_label(status, ips_triggers=ips.triggers) == "ROLL NOW"
        assert planned.action is RollAction.ROLL_NOW
        assert planned.driver == "time"
        # And the reader is still told the rally REVIEW was seen.
        assert "adds no roll action" in planned.rationale

    def test_the_gap_is_a_book_with_no_underlying(self) -> None:
        """No monkeypatch: only a zero-underlying book reaches UNMEASURED.

        Crash convexity is gain divided by the protected book, so it is
        ``None`` exactly when the book has no underlying. A book with one
        grades a number, so the "no action" cell cannot arise on it.
        """
        ips = _ips()
        bare = _book(_put(days=self._DAYS))
        held = _book(_put(days=self._DAYS))
        held.underlying_quantity = 500

        (bare_status,) = evaluate_roll_status(bare, ips)
        (held_status,) = evaluate_roll_status(held, ips)

        assert bare_status.convexity.grade.value == "UNMEASURED"
        assert leg_action_label(bare_status, ips_triggers=ips.triggers) is None
        assert held_status.convexity.grade.value != "UNMEASURED"
        assert (
            leg_action_label(held_status, ips_triggers=ips.triggers) is not None
        )
