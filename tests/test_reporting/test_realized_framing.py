"""Digest §4 from the position history (#313).

The section builder chooses what to show; the row builder says it once for
both renderers; and §4 never shows a realized figure the history cannot
support (no figure from one mark, no start date it does not have).
"""

from __future__ import annotations

from datetime import date

import pytest

from deltadewa.portfolio.history import (
    CloseReason,
    FillKind,
    PositionHistory,
)
from deltadewa.reporting.program_report import (
    RealizedCarrySection,
    RealizedStatus,
    ReturnFramingSection,
    build_realized_carry_section,
    realized_framing_rows,
)
from tests.history_builders import fill, leg, mark

D0 = date(2026, 11, 7)
D1 = date(2026, 11, 14)
D2 = date(2026, 11, 21)


def _framing(section: RealizedCarrySection) -> ReturnFramingSection:
    return ReturnFramingSection(
        carry_drag_annual_pct=1.15,
        weekly_carry_cost=1400.0,
        elapsed_days=7,
        cumulative_carry_cost=2800.0,
        cumulative_since=date(2026, 7, 1),
        premium_paid_point_in_time=300_000.0,
        realized=section,
    )


def _three_marks(*, fees: float | None = 0.0) -> PositionHistory:
    return PositionHistory(
        recorded_fills=(
            fill(FillKind.OPEN, "b", 5, 4.0, day=D1, fees=fees),
            fill(
                FillKind.CLOSE,
                "a",
                -10,
                9.0,
                day=D2,
                reason=CloseReason.MONETIZATION,
            ),
        ),
        marks=(
            mark(D0, (leg("a", 10, 10.0),), is_opening=True),
            mark(D1, (leg("a", 10, 9.5), leg("b", 5, 4.0))),
            mark(D2, (leg("b", 5, 3.0),), spot=4500.0),
        ),
    )


class TestSection:
    """Which spans are shown, and when there is nothing to show."""

    def test_not_started(self) -> None:
        """No marks: nothing measured, no start date claimed."""
        section = build_realized_carry_section(PositionHistory())
        assert section.status is RealizedStatus.NOT_STARTED
        assert section.history_start is None

    def test_one_mark(self) -> None:
        """One mark is a start date and an opening value, not a carry."""
        history = PositionHistory(
            marks=(mark(D0, (leg("a", 10, 10.0),), is_opening=True),),
        )
        section = build_realized_carry_section(history)
        assert section.status is RealizedStatus.ONE_MARK
        assert section.history_start == D0
        assert section.opening_value == pytest.approx(10_000.0)
        assert section.inception is None

    def test_two_marks_have_no_separate_latest(self) -> None:
        """When the latest period is the whole history, it is shown once."""
        history = PositionHistory(
            marks=(
                mark(D0, (leg("a", 10, 10.0),), is_opening=True),
                mark(D1, (leg("a", 10, 9.0),)),
            ),
        )
        section = build_realized_carry_section(history)
        assert section.status is RealizedStatus.MEASURED
        assert section.inception is not None
        assert section.latest is None

    def test_three_marks(self) -> None:
        """Since inception, plus the latest period, plus the hedged return."""
        section = build_realized_carry_section(_three_marks())
        assert section.inception is not None
        assert section.latest is not None
        assert (section.latest.start, section.latest.end) == (D1, D2)
        assert section.inception_return is not None
        assert section.inception_return.before_hedge_pct == pytest.approx(
            -10.0,
        )
        # Net carry: 10,500 gross less 9,000 monetized = 1,500 on 5,000,000.
        assert section.inception_return.after_hedge_pct == pytest.approx(
            -10.03,
        )


class TestRows:
    """What §4 says, built once for both formats."""

    def test_measured_rows_and_notes(self) -> None:
        """Theta is relabelled as theta, and the start is stated."""
        rows, notes = realized_framing_rows(
            _framing(build_realized_carry_section(_three_marks())),
        )
        labels = [label for label, _ in rows]
        assert labels[:3] == [
            "Theta carry drag (annual, model)",
            "Theta carry this period (model)",
            "Theta carry since 2026-07-01 (model)",
        ]
        assert "Realized carry since 2026-11-07, gross" in labels
        assert "Realized carry since 2026-11-07, net of monetization" in labels
        assert "Realized carry 2026-11-14 to 2026-11-21, gross" in labels
        assert "After-hedge return since 2026-11-07" in labels
        assert notes[0] == (
            "No position history before 2026-11-07. The book held then is "
            "carried in at its MODEL mark of $10,000."
        )
        assert any("will not agree" in note for note in notes)

    def test_figures(self) -> None:
        """V0 10,000 + P 2,000 - R_routine 0 - V1 1,500 = 10,500 gross."""
        rows = dict(
            realized_framing_rows(
                _framing(build_realized_carry_section(_three_marks())),
            )[0],
        )
        gross = rows["Realized carry since 2026-11-07, gross"]
        assert gross.startswith("$10,500 (")
        assert rows["Before-hedge return since 2026-11-07"] == "-10.00%"

    def test_breaks_are_listed_then_counted(self) -> None:
        """More than five reasons: five named, the rest counted."""
        opens = tuple(
            fill(FillKind.OPEN, f"x{i}", 1, 1.0, day=D1, fees=None)
            for i in range(7)
        )
        history = PositionHistory(
            recorded_fills=opens,
            marks=(
                mark(D0, is_opening=True),
                mark(D1, tuple(leg(f"x{i}", 1, 1.0) for i in range(7))),
            ),
        )
        _, notes = realized_framing_rows(
            _framing(build_realized_carry_section(history)),
        )
        assert any("(7 reason(s))" in note for note in notes)
        assert sum(note.startswith("- OPEN") for note in notes) == 5
        assert any("and 2 more" in note for note in notes)

    def test_one_mark_shows_no_figure(self) -> None:
        """No zero, no dash: it says why there is no figure yet."""
        history = PositionHistory(marks=(mark(D0, is_opening=True),))
        rows = dict(
            realized_framing_rows(
                _framing(build_realized_carry_section(history)),
            )[0],
        )
        assert rows["Realized carry"] == (
            "not yet measurable (one mark, 2026-11-07)"
        )

    def test_mark_note_and_unreadable(self) -> None:
        """A missing mark and an unreadable history are both said aloud."""
        section = RealizedCarrySection(
            status=RealizedStatus.UNREADABLE,
            error="events.jsonl:3: malformed",
            mark_note="no mark taken — the mark step failed: boom",
        )
        rows, notes = realized_framing_rows(_framing(section))
        assert dict(rows)["Realized carry"] == "unavailable"
        assert notes == [
            "The position history could not be read: events.jsonl:3: malformed",
            "This week: no mark taken — the mark step failed: boom.",
        ]
