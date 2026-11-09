"""Append-only storage for the position history (#313).

Two JSON-lines files under ``exports/history/``:

``events.jsonl``
    Fills and book edits (:class:`~deltadewa.portfolio.history.Fill`,
    :class:`~deltadewa.portfolio.history.BookEdit`), in the order they
    were recorded. Written by ``ProgramState`` (the app, or the importer
    CLI's whole-book replace).
``marks.jsonl``
    Boundary marks (:class:`~deltadewa.portfolio.history.BookMark`),
    written by the weekly job and by ``python -m deltadewa.history init``.

Why ``exports/``
    It is the bind-mounted directory, and ``ops/backup-exports.sh``
    already archives all of it, encrypted, every night. Configuration is
    baked into the image and is not backed up, so a history kept anywhere
    else would not survive the droplet.

What bounds it
    Events are written only when a person changes the book: tens a year.
    Marks are capped at one per program date and taken weekly: about
    10 lots x 52 weeks x 400 bytes, or roughly 200 KB a year. Nothing is
    ever pruned: dropping old records would break the property that a
    year's realized carry is the sum of its quarters, and the
    reconciliation against statements with it.

Write discipline
    Each record is one line, appended in one write and ``fsync``-ed.
    Records are never edited in place: a correction is a new fill that
    ``supersedes`` the old one. Every append first validates the whole
    history *including* the new record, so a record that would make the
    history unreadable (a correction of an unknown fill, a second mark for
    a date) never reaches disk.

Reading never skips
    A malformed line, including a torn final line from a crash mid-write,
    raises :class:`HistoryCorruptError` naming the file and line. Skipping
    it would drop a fill silently, and a dropped fill breaks the identity
    with no visible sign.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Final

from deltadewa.portfolio.history import (
    BookEdit,
    BookMark,
    Fill,
    HistorySchemaError,
    PositionHistory,
    record_from_json,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from pathlib import Path

    from deltadewa.portfolio.history import HistoryRecord

EVENTS_FILENAME: Final = "events.jsonl"
MARKS_FILENAME: Final = "marks.jsonl"

#: Where the history lives, relative to a program's export directory.
HISTORY_DIRNAME: Final = "history"


class HistoryCorruptError(ValueError):
    """A history file holds a line that cannot be read back."""


class HistoryStore:
    """The two history files under one directory."""

    def __init__(self, root: Path) -> None:
        """Point the store at *root*; nothing is created until a write.

        Args:
            root: The history directory, normally
                ``<export_dir>/history``.

        """
        self.root = root

    @property
    def events_path(self) -> Path:
        """``events.jsonl``: fills and book edits."""
        return self.root / EVENTS_FILENAME

    @property
    def marks_path(self) -> Path:
        """``marks.jsonl``: boundary marks."""
        return self.root / MARKS_FILENAME

    def exists(self) -> bool:
        """Whether any history has been recorded here."""
        return self.events_path.exists() or self.marks_path.exists()

    def load(self) -> PositionHistory:
        """Read every record back, corrections resolved.

        Returns:
            The history. Empty when nothing has been recorded.

        Raises:
            HistoryCorruptError: If any line is unreadable, a record is in
                the wrong file, or the records contradict each other.

        """
        fills: list[Fill] = []
        edits: list[BookEdit] = []
        for record in _read_records(self.events_path):
            if isinstance(record, Fill):
                fills.append(record)
            elif isinstance(record, BookEdit):
                edits.append(record)
            else:
                raise HistoryCorruptError(
                    f"{self.events_path}: a mark is stored with the events",
                )
        marks: list[BookMark] = []
        for record in _read_records(self.marks_path):
            if not isinstance(record, BookMark):
                raise HistoryCorruptError(
                    f"{self.marks_path}: a non-mark record is stored with "
                    "the marks",
                )
            marks.append(record)
        try:
            return PositionHistory(
                recorded_fills=tuple(fills),
                edits=tuple(edits),
                marks=tuple(marks),
            )
        except ValueError as exc:
            raise HistoryCorruptError(f"{self.root}: {exc}") from exc

    @property
    def history_start(self) -> date | None:
        """The first mark's date, or ``None`` before the history starts."""
        return self.load().history_start

    def append_fill(self, fill: Fill) -> None:
        """Append one fill.

        Raises:
            ValueError: If the history would not read back with it, e.g.
                it corrects an event that was never recorded.
            HistoryCorruptError: If the existing history is unreadable.

        """
        self.append_events([fill])

    def append_edit(self, edit: BookEdit) -> None:
        """Append one book edit.

        Raises:
            HistoryCorruptError: If the existing history is unreadable.

        """
        self.load()
        _append_lines(self.events_path, [edit])

    def append_events(self, records: Sequence[Fill | BookEdit]) -> None:
        """Append several fills and edits as one change, all or none.

        One book change can be several records (a roll is a close and an
        open; clearing the book is a delete per lot). Written one at a time,
        a failure part-way would leave the history holding some records of a
        change that the caller then reverts. Here every record is validated
        against the history as it would stand with all of them, then the
        lines go down in a single write, so a failure leaves none (or, if
        the write itself is cut short, a torn final line that the next read
        reports rather than skips).

        Raises:
            ValueError: If the history would not read back with the records,
                e.g. a correction of an event that was never recorded.
            HistoryCorruptError: If the existing history is unreadable.

        """
        current = self.load()
        fills = [r for r in records if isinstance(r, Fill)]
        PositionHistory(
            recorded_fills=(*current.recorded_fills, *fills),
            edits=current.edits,
            marks=current.marks,
        )
        _append_lines(self.events_path, records)

    def append_mark(self, mark: BookMark) -> bool:
        """Append a mark unless its date is already marked.

        The first mark for a date wins. The handbook requires a boundary
        mark to be computed once and reused, never recomputed, so a
        second run of the weekly job on the same day keeps the mark it
        already took.

        Returns:
            ``True`` if the mark was written, ``False`` if a mark for that
            date already existed and was kept.

        Raises:
            ValueError: If the mark is dated before the latest existing
                mark (that would split a period already reported), or is
                an opening mark when the history has already started.
            HistoryCorruptError: If the existing history is unreadable.

        """
        current = self.load()
        if any(m.mark_date == mark.mark_date for m in current.marks):
            return False
        if mark.is_opening and current.marks:
            raise ValueError(
                f"the history already started on {current.history_start}; "
                "it can have only one opening mark",
            )
        if current.marks and mark.mark_date < current.marks[-1].mark_date:
            raise ValueError(
                f"mark for {mark.mark_date} is earlier than the latest mark "
                f"({current.marks[-1].mark_date}); marks only move forward",
            )
        _append_lines(self.marks_path, [mark])
        return True


def _append_lines(path: Path, records: Sequence[HistoryRecord]) -> None:
    """Append *records*, one line each, in one write, then ``fsync`` it."""
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        json.dumps(record.to_json(), separators=(",", ":")) + "\n"
        for record in records
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _read_records(path: Path) -> list[HistoryRecord]:
    """Decode every line of *path*; a missing file is an empty history."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # Not "corrupt" in the sense of a bad line, but the same thing to
        # every caller: the history cannot be read, and nothing may be
        # guessed. Raising the one type they already handle keeps a
        # permissions fault or a non-UTF-8 byte from escaping as something
        # nobody catches (the digest would otherwise fail outright over a
        # section-four problem).
        raise HistoryCorruptError(
            f"{path}: cannot be read ({type(exc).__name__}: {exc}). "
            "Nothing was skipped; check the file's permissions and "
            "encoding, or restore it from the offsite backup",
        ) from exc
    lines = text.split("\n")
    # A complete file ends with "\n", leaving one empty trailing element.
    torn_tail = lines[-1] != ""
    records: list[HistoryRecord] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        is_last = number == len(lines)
        try:
            records.append(record_from_json(json.loads(line)))
        except (json.JSONDecodeError, HistorySchemaError) as exc:
            if is_last and torn_tail:
                raise HistoryCorruptError(
                    f"{path}:{number}: the final line is incomplete — a "
                    "write was interrupted. Nothing was skipped; restore "
                    "the file from the offsite backup (RUNBOOK §7) or "
                    "remove the partial line by hand once you have "
                    "confirmed what it was",
                ) from exc
            raise HistoryCorruptError(f"{path}:{number}: {exc}") from exc
    if torn_tail and records:
        # The last line parsed but has no newline: a write cut off at
        # exactly a record boundary. Readable, but the next append would
        # join onto it, so say so now rather than corrupt the file later.
        raise HistoryCorruptError(
            f"{path}:{len(lines)}: the final line has no newline — a write "
            "was interrupted after the record but before its line end",
        )
    return records
