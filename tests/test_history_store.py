"""Tests for the append-only position-history store (#313).

The store's promises: what is appended reads back, nothing is ever
skipped (a torn or malformed line raises, naming the line), a record that
would make the history unreadable never reaches disk, and the first mark
for a date is the one kept.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from typing import TYPE_CHECKING

import pytest

from deltadewa.history_store import (
    EVENTS_FILENAME,
    MARKS_FILENAME,
    HistoryCorruptError,
    HistoryStore,
)
from deltadewa.portfolio.history import EditKind, FillKind
from tests.history_builders import edit, fill, leg, mark

if TYPE_CHECKING:
    from pathlib import Path

D1 = date(2026, 11, 7)
D2 = date(2026, 11, 14)
D3 = date(2026, 11, 21)


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    """An empty store under a temporary export directory."""
    return HistoryStore(tmp_path / "history")


def test_empty_store_loads_empty(store: HistoryStore) -> None:
    """No files means no history, and nothing is created by reading."""
    history = store.load()
    assert history.fills == ()
    assert history.marks == ()
    assert store.history_start is None
    assert not store.exists()
    assert not store.root.exists()


def test_round_trip_keeps_record_order(store: HistoryStore) -> None:
    """Fills and edits read back in the order they were appended."""
    first = fill(FillKind.OPEN, "a", 10, 3.0, day=D1)
    amend = edit(
        EditKind.AMEND,
        "a",
        day=D1,
        quantity_before=10,
        quantity_after=12,
    )
    second = fill(FillKind.OPEN, "b", 5, 2.0, day=D2, fees=None)
    store.append_fill(first)
    store.append_edit(amend)
    store.append_fill(second)
    assert store.append_mark(mark(D1, (leg("a", 12, 3.0),), is_opening=True))

    history = store.load()
    assert history.recorded_fills == (first, second)
    assert history.edits == (amend,)
    assert store.history_start == D1
    assert store.events_path.name == EVENTS_FILENAME
    assert store.marks_path.name == MARKS_FILENAME
    # One record per line, each terminated.
    assert store.events_path.read_text().count("\n") == 3


def test_first_mark_for_a_date_is_kept(store: HistoryStore) -> None:
    """A same-day re-run keeps the boundary already taken."""
    original = mark(D1, (leg("a", 10, 3.0),))
    rerun = mark(D1, (leg("a", 10, 9.0),))
    assert store.append_mark(original)
    assert not store.append_mark(rerun)
    assert store.load().marks == (original,)


def test_marks_only_move_forward(store: HistoryStore) -> None:
    """Inserting a mark into the past would split a reported period."""
    store.append_mark(mark(D2))
    with pytest.raises(ValueError, match="only move forward"):
        store.append_mark(mark(D1))


def test_one_opening_mark(store: HistoryStore) -> None:
    """The history starts once."""
    store.append_mark(mark(D1, is_opening=True))
    with pytest.raises(ValueError, match="only one opening mark"):
        store.append_mark(mark(D2, is_opening=True))


def test_bad_correction_never_reaches_disk(store: HistoryStore) -> None:
    """A fill the history could not read back is refused before writing."""
    store.append_fill(fill(FillKind.OPEN, "a", 1, 1.0, day=D1))
    before = store.events_path.read_text()
    stray = fill(FillKind.OPEN, "a", 1, 1.0, day=D1, supersedes="missing")
    with pytest.raises(ValueError, match="never recorded"):
        store.append_fill(stray)
    assert store.events_path.read_text() == before


def test_valid_correction_is_appended(store: HistoryStore) -> None:
    """A correction lands as a new line; the original stays on disk."""
    original = fill(FillKind.OPEN, "a", 1, 10.0, day=D1, fees=None)
    store.append_fill(original)
    fixed = dataclasses.replace(
        original,
        event_id="fix",
        fees=0.65,
        supersedes=original.event_id,
    )
    store.append_fill(fixed)
    history = store.load()
    assert history.fills == (fixed,)
    assert len(history.recorded_fills) == 2


class TestNothingIsSkipped:
    """Unreadable lines raise, naming the file and line."""

    def test_torn_final_line(self, store: HistoryStore) -> None:
        """A write cut off mid-record is reported, not dropped."""
        store.append_fill(fill(FillKind.OPEN, "a", 1, 1.0, day=D1))
        with store.events_path.open("a", encoding="utf-8") as handle:
            handle.write('{"schema": 1, "record": "fi')
        with pytest.raises(HistoryCorruptError, match=r":2: the final line"):
            store.load()

    def test_final_record_without_newline(self, store: HistoryStore) -> None:
        """A record missing only its line end would corrupt the next append."""
        store.append_fill(fill(FillKind.OPEN, "a", 1, 1.0, day=D1))
        text = store.events_path.read_text()
        store.events_path.write_text(text.rstrip("\n"))
        with pytest.raises(HistoryCorruptError, match="no newline"):
            store.load()

    def test_malformed_middle_line(self, store: HistoryStore) -> None:
        """A bad line that is not the last is a corruption, named by line."""
        store.append_fill(fill(FillKind.OPEN, "a", 1, 1.0, day=D1))
        good_line = store.events_path.read_text()
        store.events_path.write_text(good_line + "not json\n" + good_line)
        with pytest.raises(HistoryCorruptError, match=r":2:"):
            store.load()

    def test_unknown_schema_in_file(self, store: HistoryStore) -> None:
        """A record from another schema version is refused on read."""
        store.root.mkdir(parents=True)
        store.marks_path.write_text('{"schema": 99, "record": "mark"}\n')
        with pytest.raises(HistoryCorruptError, match="refusing to guess"):
            store.load()

    def test_record_in_the_wrong_file(self, store: HistoryStore) -> None:
        """A mark among the events means the files were mixed up."""
        store.root.mkdir(parents=True)
        store.events_path.write_text(json.dumps(mark(D1).to_json()) + "\n")
        with pytest.raises(HistoryCorruptError, match="stored with the events"):
            store.load()

    def test_corrupt_history_blocks_appends(self, store: HistoryStore) -> None:
        """Appending onto a corrupt file would bury the corruption."""
        store.root.mkdir(parents=True)
        store.events_path.write_text("{broken\n")
        with pytest.raises(HistoryCorruptError):
            store.append_fill(fill(FillKind.OPEN, "a", 1, 1.0, day=D3))
