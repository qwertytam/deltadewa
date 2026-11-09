"""Book changes: a readable log of what happened to the book (#262).

#262 asked for a view of ``ProgramState``'s change log. That log was never
written: ``ProgramState`` builds a ``PortfolioLogger`` but no mutator ever
called ``log_portfolio_change``, and it reset at every process start in any
case. The durable record of every change to the book is the position
history (#313): ``exports/history/events.jsonl`` holds each fill and each
book edit, stamped with when it was recorded and by which process. This
module turns that into rows. It reads the history and builds nothing of its
own, so there is no second store to drift from the first.

Two forms of the same list, which the issue asked about separately:

* the **working log**: every recorded change, newest first, windowed to the
  most recent ``limit`` so a long-lived program does not render years of
  rows (the total is always reported);
* the **since-last-look** count: how many changes were recorded after the
  latest boundary mark, which is the closest thing the program has to
  "since the last report".

A correction (a fill that supersedes an earlier one) is shown as a row of its
own and the original is marked superseded, rather than the original being
hidden: a log that quietly drops entries is not a log.

UI-free: the panel decides how to show a row, this module decides what a
row says.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from deltadewa.portfolio.history import (
    BookEdit,
    CloseReason,
    Fill,
    FillKind,
)

if TYPE_CHECKING:
    from datetime import date, datetime

    from deltadewa.portfolio.history import PositionHistory

#: How many rows the working log returns when the caller does not say.
DEFAULT_LIMIT = 25


@dataclass(frozen=True)
class BookChange:  # pylint: disable=too-many-instance-attributes  # one field per rendered column
    """One recorded change to the book, in words.

    Attributes:
        recorded_at: When it was entered (timezone-aware). The sort key.
        when: The date it took effect: a fill's trade date, an edit's
            effective date. Can precede ``recorded_at`` for a back-dated
            entry.
        kind: ``OPEN``, ``CLOSE`` or ``SETTLE`` for a fill; ``AMEND``,
            ``DELETE`` or ``REPLACE`` for an edit.
        is_fill: Whether cash moved. A fill has a cash figure (possibly not
            captured); an edit never does.
        lot: The contract it concerned, e.g. ``PUT 4200 2027-06-18``, or
            ``None`` for a whole-book replace.
        detail: A sentence saying what happened.
        cash: Signed cash into the account (``+`` received, ``-`` paid),
            or ``None``. For a fill, ``None`` means the price or fees were
            not captured, which is not the same as zero; for an edit it
            means no cash moved.
        written_by: The writing process's label (#355).
        superseded: A later fill corrects this one.
        correction: This fill corrects an earlier one.
        since_last_mark: Recorded after the latest boundary mark, so not yet
            inside any reported period. ``False`` when there is no mark.

    """

    recorded_at: datetime
    when: date
    kind: str
    is_fill: bool
    lot: str | None
    detail: str
    cash: float | None
    written_by: str
    superseded: bool
    correction: bool
    since_last_mark: bool


@dataclass(frozen=True)
class BookChangeLog:
    """The windowed log plus the facts a reader needs around it.

    Attributes:
        rows: Newest first, at most ``limit`` of them.
        total: Every change recorded, whether or not it is in ``rows``.
        since_last_mark: How many were recorded after the latest mark, or
            ``None`` when there is no mark to count from.
        last_mark_date: That mark's date.
        history_start: The first mark's date. Nothing before it is known.

    """

    rows: tuple[BookChange, ...]
    total: int
    since_last_mark: int | None
    last_mark_date: date | None
    history_start: date | None

    @property
    def truncated(self) -> bool:
        """Whether older changes exist beyond ``rows``."""
        return self.total > len(self.rows)


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _fill_detail(fill: Fill) -> str:
    """Say what a fill did: buy/sell, size, contract, price, fees, why."""
    size = abs(fill.quantity)
    contracts = f"{size} x {fill.terms.describe()}"
    price = (
        f"{_money(fill.price_per_share)}"
        if fill.price_per_share is not None
        else "price not captured"
    )
    fees = (
        f"fees {_money(fill.fees)}"
        if fill.fees is not None
        else "fees not captured"
    )
    if fill.kind is FillKind.SETTLE:
        text = f"Settled {contracts} at {price}, {fees}"
    else:
        verb = "Bought" if fill.quantity > 0 else "Sold"
        at = f"at {price}" if fill.price_per_share is not None else price
        text = f"{verb} {contracts} {at}, {fees}"
    tags: list[str] = []
    if fill.kind is FillKind.CLOSE and fill.reason is CloseReason.MONETIZATION:
        tags.append("monetization")
    if fill.roll_id is not None:
        tags.append("roll")
    if tags:
        text += f" ({', '.join(tags)})"
    if fill.note:
        text += f" — {fill.note}"
    return text


def _edit_lot(edit: BookEdit) -> str | None:
    terms = edit.after or edit.before
    return terms.describe() if terms is not None else None


def build_book_change_log(
    history: PositionHistory,
    *,
    limit: int = DEFAULT_LIMIT,
) -> BookChangeLog:
    """Build the working log from the position history.

    Args:
        history: Everything recorded.
        limit: The most rows to return. ``0`` returns none (the counts are
            still reported).

    Returns:
        Newest-first rows and the surrounding counts. Empty rows and a
        ``total`` of ``0`` when nothing has been recorded.

    Raises:
        ValueError: If *limit* is negative.

    """
    if limit < 0:
        raise ValueError(f"limit must be >= 0, got {limit}")
    last_mark = history.marks[-1] if history.marks else None
    superseded = {f.supersedes for f in history.recorded_fills if f.supersedes}

    def _since(recorded_at: datetime) -> bool:
        return last_mark is not None and recorded_at > last_mark.marked_at

    changes: list[BookChange] = [
        BookChange(
            recorded_at=fill.recorded_at,
            when=fill.trade_date,
            kind=fill.kind.value,
            is_fill=True,
            lot=fill.terms.describe(),
            detail=_fill_detail(fill),
            cash=fill.cash_flow(),
            written_by=fill.written_by,
            superseded=fill.event_id in superseded,
            correction=fill.supersedes is not None,
            since_last_mark=_since(fill.recorded_at),
        )
        for fill in history.recorded_fills
    ]
    changes.extend(
        BookChange(
            recorded_at=edit.recorded_at,
            when=edit.effective_date,
            kind=edit.kind.value,
            is_fill=False,
            lot=_edit_lot(edit),
            detail=edit.detail,
            cash=None,
            written_by=edit.written_by,
            superseded=False,
            correction=False,
            since_last_mark=_since(edit.recorded_at),
        )
        for edit in history.edits
    )
    # Newest first. Two records can share an instant (a roll journals its
    # close and open back to back), and the history keeps fills and edits
    # apart, so ties break on position in the combined list: the later entry
    # first, which puts a roll's open above its close.
    order = sorted(
        range(len(changes)),
        key=lambda i: (changes[i].recorded_at, i),
        reverse=True,
    )
    changes = [changes[i] for i in order]

    return BookChangeLog(
        rows=tuple(changes[:limit]),
        total=len(changes),
        since_last_mark=(
            sum(change.since_last_mark for change in changes)
            if last_mark is not None
            else None
        ),
        last_mark_date=last_mark.mark_date if last_mark is not None else None,
        history_start=history.history_start,
    )
