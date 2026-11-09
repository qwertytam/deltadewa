"""Start, mark and inspect the position history (#313).

Run inside the ``jobs`` container, like the other cron entry points::

    python -m deltadewa.history_cli init     # start the history now
    python -m deltadewa.history_cli mark     # take today's mark
    python -m deltadewa.history_cli status   # what is recorded, and breaks

``init`` writes the **opening mark**: the book as it stands, priced once,
which every later period is measured from. Nothing before it is known, and
nothing is reconstructed: legs already held come in at their value in this
mark, never as synthetic opening trades. Run it once, at deploy. If it is
never run, the weekly digest's own mark step starts the history the first
time it runs, so a forgotten step costs a few days of history, not all of
it.

``mark`` is what the weekly digest does every Sunday (see
:func:`take_mark`); running it by hand is for a boundary the operator
wants recorded, e.g. a quarter-end. At most one mark per program date:
a second on the same day keeps the first, because a boundary mark is
computed once and reused, never recomputed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from deltadewa.analysis.realized_carry import latest_period, reconcile_book
from deltadewa.clock import program_now
from deltadewa.portfolio.history import BookMark, mark_book
from deltadewa.state import ProgramState

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

_DEFAULT_EXPORT_DIR: Final = Path("exports")
_DEFAULT_IPS_PATH: Final = Path("config/ips.yaml")
_WRITER_LABEL: Final = "history_cli"

_EXIT_OK: Final = 0
_EXIT_REFUSED: Final = 1


@dataclass(frozen=True)
class MarkOutcome:
    """What a mark attempt did, in words an operator can act on.

    Attributes:
        mark: The mark now standing for the date: the one just written,
            or the one already there. ``None`` when no mark was taken.
        written: Whether this call wrote it.
        message: One sentence for a log line or a digest caveat.

    """

    mark: BookMark | None
    written: bool
    message: str


def take_mark(
    state: ProgramState,
    *,
    written_by: str,
    as_of: date | None = None,
) -> MarkOutcome:
    """Mark the live book once for its program date.

    The first mark ever taken is the opening mark that starts the
    history.

    Args:
        state: The loaded program state.
        written_by: The calling process, stamped on the mark (#355).
        as_of: The date the caller is reporting for. The book is priced
            on its own valuation date, so a caller reporting for any
            other day (a back-dated digest re-run) gets no mark rather
            than a mark carrying the wrong date.

    Returns:
        What happened.

    Raises:
        RuntimeError: If *state* has no history store.

    """
    store = state.history
    if store is None:
        raise RuntimeError("this ProgramState has no history store")
    portfolio = state.portfolio
    book_date = portfolio.valuation_date.date()
    if as_of is not None and as_of != book_date:
        return MarkOutcome(
            mark=None,
            written=False,
            message=(
                f"no mark taken: the book is priced on {book_date}, not the "
                f"report date {as_of}"
            ),
        )
    existing = store.load().marks
    tz = state.ips_config.program.timezone if state.ips_config else None
    mark = mark_book(
        portfolio,
        marked_at=program_now(tz),
        written_by=written_by,
        is_opening=not existing,
    )
    if store.append_mark(mark):
        started = (
            " — the position history starts here" if mark.is_opening else ""
        )
        return MarkOutcome(
            mark=mark,
            written=True,
            message=(
                f"marked {len(mark.legs)} lots on {mark.mark_date} at "
                f"{mark.hedge_value:,.2f}{started}"
            ),
        )
    kept = next(m for m in existing if m.mark_date == mark.mark_date)
    return MarkOutcome(
        mark=kept,
        written=False,
        message=(
            f"kept the {kept.mark_date} mark already taken at "
            f"{kept.marked_at.isoformat()}"
        ),
    )


def _status_lines(state: ProgramState) -> list[str]:
    store = state.history
    if store is None:  # pragma: no cover - load() always attaches one
        return ["no history store"]
    history = store.load()
    if history.history_start is None:
        return [
            (
                "The position history has not started. Run "
                "`python -m deltadewa.history_cli init`."
            ),
        ]
    lines = [
        f"No position history before {history.history_start}.",
        (
            f"{len(history.marks)} marks, {len(history.fills)} fills, "
            f"{len(history.edits)} book edits."
        ),
    ]
    period = latest_period(history)
    if period is None:
        lines.append("Realized carry: not yet measurable (one mark).")
    else:
        lines.append(
            f"Latest period {period.start} to {period.end}: gross "
            f"{period.gross:,.2f}, net {period.net:,.2f}"
            + ("" if period.reconcilable else " — NOT reconcilable:"),
        )
        lines.extend(f"  - {reason}" for reason in period.breaks)
    findings = reconcile_book(history, state.positions_snapshot())
    lines.append(
        "Lots reconcile with the history."
        if not findings
        else "Lots the history does not explain:",
    )
    lines.extend(f"  - {finding}" for finding in findings)
    return lines


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start, mark and inspect the position history.",
    )
    parser.add_argument("command", choices=("init", "mark", "status"))
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=_DEFAULT_EXPORT_DIR,
        help=f"Shared state/export directory (default: {_DEFAULT_EXPORT_DIR}).",
    )
    parser.add_argument(
        "--ips-path",
        type=Path,
        default=_DEFAULT_IPS_PATH,
        help=f"Hedge program policy file (default: {_DEFAULT_IPS_PATH}).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one history command.

    Returns:
        ``0`` on success; ``1`` when ``init`` is refused because the
        history has already started.

    """
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)
    state = ProgramState.load(args.export_dir, ips_path=args.ips_path)
    if args.command == "status":
        print("\n".join(_status_lines(state)))
        return _EXIT_OK
    if args.command == "init":
        store = state.history
        start = store.history_start if store is not None else None
        if start is not None:
            print(
                f"history_cli: the position history already started on "
                f"{start}; it has one opening mark.",
                file=sys.stderr,
            )
            return _EXIT_REFUSED
    outcome = take_mark(state, written_by=_WRITER_LABEL)
    print(f"history_cli: {outcome.message}")
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
