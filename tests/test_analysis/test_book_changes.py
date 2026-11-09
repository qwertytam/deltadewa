"""Tests for the book-change log (#262).

Crafted history in, rows out. Every date is a pinned absolute date, so the
rows are exact and stay exact as the calendar moves.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from deltadewa.analysis.book_changes import (
    DEFAULT_LIMIT,
    build_book_change_log,
)
from deltadewa.portfolio.history import (
    CloseReason,
    EditKind,
    FillKind,
    PositionHistory,
)
from tests.history_builders import at, edit, fill, mark

D0 = date(2026, 11, 2)
D1 = date(2026, 11, 3)
D2 = date(2026, 11, 4)
D3 = date(2026, 11, 5)


class TestEmpty:
    """Nothing recorded is an empty log, not an error."""

    def test_empty_history(self) -> None:
        """No rows, no counts, no start date."""
        log = build_book_change_log(PositionHistory())
        assert log.rows == ()
        assert log.total == 0
        assert log.since_last_mark is None
        assert log.last_mark_date is None
        assert log.history_start is None
        assert not log.truncated

    def test_marks_only(self) -> None:
        """A mark is a boundary, not a change: nothing to list."""
        history = PositionHistory(marks=(mark(D0, is_opening=True),))
        log = build_book_change_log(history)
        assert log.total == 0
        assert log.history_start == D0
        assert log.since_last_mark == 0
        assert log.last_mark_date == D0

    def test_negative_limit_refused(self) -> None:
        """A negative window is a bug in the caller."""
        with pytest.raises(ValueError, match="limit must be >= 0"):
            build_book_change_log(PositionHistory(), limit=-1)


class TestRows:
    """What each kind of record says, and in what order."""

    def test_newest_first_across_fills_and_edits(self) -> None:
        """Fills and edits interleave by when they were recorded."""
        history = PositionHistory(
            recorded_fills=(
                fill(FillKind.OPEN, "a", 10, 48.5, day=D0, fees=6.5),
                fill(FillKind.OPEN, "b", 5, 20.0, day=D2, fees=3.0),
            ),
            edits=(
                edit(
                    EditKind.AMEND,
                    "a",
                    day=D1,
                    quantity_before=10,
                    quantity_after=12,
                ),
            ),
        )
        log = build_book_change_log(history)
        assert [(row.when, row.kind) for row in log.rows] == [
            (D2, "OPEN"),
            (D1, "AMEND"),
            (D0, "OPEN"),
        ]

    def test_fill_rows_carry_cash_and_words(self) -> None:
        """Buy 10 @ 48.50 with 6.50 fees pays 48,506.50."""
        history = PositionHistory(
            recorded_fills=(
                fill(FillKind.OPEN, "a", 10, 48.5, day=D0, fees=6.5),
            ),
        )
        (row,) = build_book_change_log(history).rows
        assert row.is_fill
        assert row.cash == pytest.approx(-48_506.5)
        assert row.lot == "PUT 4200 2027-06-18"
        assert row.detail == (
            "Bought 10 x PUT 4200 2027-06-18 at 48.50, fees 6.50"
        )

    def test_close_reason_and_roll_are_tagged(self) -> None:
        """A monetizing close that is half of a roll says both."""
        history = PositionHistory(
            recorded_fills=(
                fill(
                    FillKind.CLOSE,
                    "a",
                    -4,
                    60.0,
                    day=D0,
                    fees=2.0,
                    reason=CloseReason.MONETIZATION,
                    roll_id="r1",
                ),
            ),
        )
        (row,) = build_book_change_log(history).rows
        assert row.detail == (
            "Sold 4 x PUT 4200 2027-06-18 at 60.00, fees 2.00 "
            "(monetization, roll)"
        )
        assert row.cash == pytest.approx(4 * 60.0 * 100 - 2.0)

    def test_settlement_wording(self) -> None:
        """A worthless expiry is a settlement at 0.00, not a sale."""
        history = PositionHistory(
            recorded_fills=(
                fill(FillKind.SETTLE, "a", -10, 0.0, day=D0, fees=0.0),
            ),
        )
        (row,) = build_book_change_log(history).rows
        assert row.detail == (
            "Settled 10 x PUT 4200 2027-06-18 at 0.00, fees 0.00"
        )
        assert row.cash == pytest.approx(0.0)

    def test_uncaptured_figures_are_said_not_zeroed(self) -> None:
        """Unknown fees: the row says so and carries no cash figure."""
        history = PositionHistory(
            recorded_fills=(
                fill(FillKind.OPEN, "a", 10, 48.5, day=D0, fees=None),
                fill(FillKind.OPEN, "b", 1, None, day=D1, fees=None),
            ),
        )
        newest, oldest = build_book_change_log(history).rows
        assert oldest.cash is None
        assert oldest.detail.endswith("at 48.50, fees not captured")
        assert newest.cash is None
        assert newest.detail == (
            "Bought 1 x PUT 4200 2027-06-18 price not captured, "
            "fees not captured"
        )

    def test_edits_carry_no_cash(self) -> None:
        """A book edit moved no cash; its sentence is the recorded detail."""
        history = PositionHistory(
            edits=(
                edit(EditKind.DELETE, "a", day=D0, quantity_before=3),
                edit(EditKind.REPLACE, None, day=D1),
            ),
        )
        replace, delete = build_book_change_log(history).rows
        assert not delete.is_fill
        assert delete.cash is None
        assert delete.detail == "DELETE in a test"
        assert delete.lot == "PUT 4200 2027-06-18"
        assert replace.lot is None


class TestCorrections:
    """Supersession is shown, not hidden."""

    def test_both_the_original_and_its_correction_appear(self) -> None:
        """The wrong fill is marked superseded; the fix, a correction."""
        original = fill(FillKind.OPEN, "a", 1, 10.0, day=D0, fees=None)
        fixed = dataclasses.replace(
            original,
            event_id="fix",
            fees=0.65,
            supersedes=original.event_id,
            recorded_at=at(D1),
        )
        history = PositionHistory(recorded_fills=(original, fixed))
        log = build_book_change_log(history)
        assert log.total == 2
        newest, oldest = log.rows
        assert (newest.correction, newest.superseded) == (True, False)
        assert (oldest.correction, oldest.superseded) == (False, True)
        assert newest.cash == pytest.approx(-1_000.65)
        assert oldest.cash is None


class TestWindow:
    """The window bounds the rows, never the counts."""

    @staticmethod
    def _history(n: int) -> PositionHistory:
        base = date(2026, 1, 1).toordinal()
        return PositionHistory(
            recorded_fills=tuple(
                fill(
                    FillKind.OPEN,
                    f"l{i}",
                    1,
                    1.0,
                    day=date.fromordinal(base + i),
                )
                for i in range(n)
            ),
        )

    def test_default_limit(self) -> None:
        """Past the default window: the newest are kept, the rest counted."""
        log = build_book_change_log(self._history(DEFAULT_LIMIT + 10))
        assert len(log.rows) == DEFAULT_LIMIT
        assert log.total == DEFAULT_LIMIT + 10
        assert log.truncated
        assert log.rows[0].when == date.fromordinal(
            date(2026, 1, 1).toordinal() + DEFAULT_LIMIT + 9,
        )

    def test_limit_zero_still_counts(self) -> None:
        """A zero window returns no rows but the totals are intact."""
        log = build_book_change_log(self._history(3), limit=0)
        assert log.rows == ()
        assert log.total == 3
        assert log.truncated

    def test_exact_fit_is_not_truncated(self) -> None:
        """As many rows as changes: nothing older is hidden."""
        log = build_book_change_log(self._history(4), limit=4)
        assert len(log.rows) == 4
        assert not log.truncated


class TestSinceLastMark:
    """The 'since I last looked' count, bounded by the latest mark."""

    def test_counts_only_what_was_recorded_after_the_latest_mark(self) -> None:
        """Marks at 22:00 UTC: entries at noon the next day are 'since'."""
        history = PositionHistory(
            recorded_fills=(
                fill(FillKind.OPEN, "a", 1, 1.0, day=D0),  # before D0 22:00
                fill(FillKind.OPEN, "b", 1, 1.0, day=D2),  # after D1 22:00
            ),
            edits=(edit(EditKind.DELETE, "a", day=D3, quantity_before=1),),
            marks=(mark(D0, is_opening=True), mark(D1)),
        )
        log = build_book_change_log(history)
        assert log.last_mark_date == D1
        assert log.since_last_mark == 2
        assert [row.since_last_mark for row in log.rows] == [
            True,
            True,
            False,
        ]

    def test_no_mark_means_no_count(self) -> None:
        """Without a mark there is no 'since', and no row claims one."""
        history = PositionHistory(
            recorded_fills=(fill(FillKind.OPEN, "a", 1, 1.0, day=D0),),
        )
        log = build_book_change_log(history)
        assert log.since_last_mark is None
        assert not log.rows[0].since_last_mark
