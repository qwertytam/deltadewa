"""PLANNING zone: the Book changes panel (#262).

A readable log of what has happened to the book, newest first: every fill
and every edit that moved no cash, from the position history (#313). #262
asked for a view of ``ProgramState``'s change log, but that log was never
written (no mutator called ``log_portfolio_change``) and it reset at every
restart, so this reads the durable record instead and builds no store of
its own.

Read-only: nothing here mutates the book, so unlike the neighbouring
provenance and liquidity panels there is no control and no BOOK write. It
refreshes whenever ``book.BOOK_VERSION_STORE`` changes, which every BOOK
mutation bumps, so a leg added or removed above shows up here.

Nothing is priced, so there is no basis chip. The rows are built in
:mod:`deltadewa.analysis.book_changes`; this module only lays them out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, html

from deltadewa.analysis.book_changes import (
    BookChange,
    BookChangeLog,
    build_book_change_log,
)
from deltadewa.analysis.realized_carry import reconcile_book
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec
from deltadewa.formatters.values import format_currency
from deltadewa.history_store import HistoryCorruptError

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.app.factory import ProgramDashApp

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-book-changes",
    title="Book changes",
)

_PANEL_ID = "plan-book-changes-panel"

#: How many of the most recent changes the panel lists. A display window,
#: not policy: the total is always stated, and the full record is the
#: history file (and ``python -m deltadewa.history_cli status``).
_RECENT_LIMIT: Final = 25

_DISCLAIMER = (
    "Every change made to the book, newest first: trades with their cash, "
    "and edits that moved no cash. A trade entered without its fees shows "
    "them as not captured, not as zero. Edits and deletions are recorded "
    "but carry no proceeds, so realized carry over a period containing one "
    "cannot be reconciled against statements."
)


def _cash_cell(change: BookChange) -> str:
    if not change.is_fill:
        return "—"
    if change.cash is None:
        return "not captured"
    return format_currency(change.cash, show_sign=True)


def _type_cell(change: BookChange) -> str:
    if change.superseded:
        return f"{change.kind} (superseded)"
    if change.correction:
        return f"{change.kind} (correction)"
    return change.kind


def _change_row(change: BookChange, *, show_since: bool) -> html.Tr:
    cells = [
        html.Td(change.recorded_at.strftime("%Y-%m-%d %H:%M")),
        html.Td(str(change.when)),
        html.Td(_type_cell(change)),
        html.Td(change.lot or "whole book"),
        html.Td(change.detail),
        html.Td(_cash_cell(change)),
        html.Td(change.written_by),
    ]
    if show_since:
        cells.append(html.Td("yes" if change.since_last_mark else "—"))
    return html.Tr(
        cells,
        # A superseded fill is excluded from every calculation: dim it the
        # way the roll planner dims a leg it declines to recommend on.
        className="plan-row--excluded" if change.superseded else None,
    )


def _headline(log: BookChangeLog) -> str:
    noun = "change" if log.total == 1 else "changes"
    text = f"{log.total} {noun} recorded"
    if log.since_last_mark is not None:
        text += f", {log.since_last_mark} since the {log.last_mark_date} mark"
    if log.truncated:
        text += f"; showing the latest {len(log.rows)}"
    return text + "."


def _history_note(log: BookChangeLog) -> str:
    if log.history_start is None:
        return (
            "The position history has not started (no opening mark): "
            "changes are recorded, but realized carry is not measured until "
            "it does. Run `python -m deltadewa.history_cli init`."
        )
    return f"No position history before {log.history_start}."


def _reconcile_block(
    findings: tuple[str, ...],
    *,
    has_marks: bool,
) -> list[Component]:
    if findings:
        return [
            html.P(
                "Lots the history does not explain:", className="env-verdict"
            ),
            html.Ul([html.Li(finding) for finding in findings]),
        ]
    if has_marks:
        return [
            html.P(
                "Every lot in the book is explained by the history.",
                className="plain-language",
            ),
        ]
    return []


def _book_changes_view(app: ProgramDashApp) -> Component:
    store = app.program_state.history
    if store is None:
        return html.P(
            "This process has no position-history store, so there is no "
            "change log to show.",
            className="env-verdict",
        )
    try:
        history = store.load()
    except HistoryCorruptError as exc:
        return html.Div(
            [
                html.P(
                    f"The position history could not be read: {exc}",
                    className="env-verdict",
                ),
                html.P(
                    "Nothing was skipped or repaired. Restore the file from "
                    "the offsite backup (RUNBOOK §7) before relying on this "
                    "log.",
                    className="plain-language",
                ),
            ],
        )

    log = build_book_change_log(history, limit=_RECENT_LIMIT)
    body: list[Component] = [html.P(_DISCLAIMER, className="plain-language")]
    if log.total == 0:
        body += [
            html.P("No book changes recorded yet.", className="env-verdict"),
            html.P(_history_note(log), className="plain-language"),
        ]
        return html.Div(body)

    show_since = log.since_last_mark is not None
    header = [
        "Recorded",
        "Effective",
        "Type",
        "Contract",
        "What happened",
        "Cash",
        "By",
    ]
    if show_since:
        header.append("After last mark")
    body += [
        html.P(_headline(log), className="env-verdict"),
        html.P(_history_note(log), className="plain-language"),
        html.Table(
            [
                html.Thead(html.Tr([html.Th(label) for label in header])),
                html.Tbody(
                    [_change_row(c, show_since=show_since) for c in log.rows],
                ),
            ],
            className="planning-table",
        ),
    ]
    findings = reconcile_book(
        history,
        app.program_state.positions_snapshot(),
    )
    body += _reconcile_block(findings, has_marks=bool(history.marks))
    return html.Div(body)


def _render_book_changes_panel_logic(*, app: ProgramDashApp) -> Component:
    """Render the Book changes panel from the position history."""
    return _safe_render(lambda: _book_changes_view(app))


def layout(*, app: ProgramDashApp) -> html.Div:
    """Build the Book changes panel."""
    return html.Div(
        [
            # No basis chip: nothing here is priced (see module docstring).
            html.H3(SECTION.title, id=SECTION.anchor_id),
            html.Div(
                _render_book_changes_panel_logic(app=app),
                id=_PANEL_ID,
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp) -> None:
    """Wire the Book changes panel's one callback.

    It watches ``book-version``, which every BOOK mutation bumps, so the log
    re-reads the history whenever the book changes.
    """

    @app.callback(
        Output(_PANEL_ID, "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_book_changes_panel(_version: int) -> Component:
        return _render_book_changes_panel_logic(app=app)
