"""The `/design` BOOK zone's trade forms: close, settle, roll (#446).

``ProgramState`` records a trade as fills with their cash (#313), but until
these forms the page could only *Remove* a lot, which journals a ``DELETE``
with no proceeds and makes the period it falls in unreconcilable. This block
is where a trade is recorded as one.

Each form is two steps, the idiom the import control already uses for its
confirm gate:

1. **Review** validates the fields and states, in words and with the cash,
   exactly what would be recorded. It keeps the raw values in a
   ``dcc.Store``; nothing is written.
2. **Confirm** replays those stored values through
   :mod:`deltadewa.app.trade_entry` into ``ProgramState``, so what is
   recorded is what was shown even if a field was touched in between. The
   button disables the instant it is clicked (as #387's add form does) so a
   double click cannot record a trade twice.

Everything that decides what a form means lives in ``trade_entry`` and is
tested with plain values. This module lays the forms out and wires them.

The layout is a skeleton with no data in it: lots and structures arrive
through callbacks watching ``book.BOOK_VERSION_STORE``, so a raise while
listing them leaves an empty dropdown and a log line rather than a page that
cannot render. A mutation's failure is contained by
``book._guarded_mutation`` like every other BOOK write, and a failed one
never bumps ``book-version``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, TypeVar

from dash import ALL, Input, Output, State, ctx, dcc, html, no_update

from deltadewa.app import trade_entry as te
from deltadewa.app.panel_guard import status_message as _status
from deltadewa.app.section_nav import SectionSpec
from deltadewa.portfolio.history import CloseReason

from .book import BOOK_VERSION_STORE, MUTATION_STATUS, _guarded_mutation

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import date

    from dash.development.base_component import Component

    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.portfolio.position import OptionPosition
    from deltadewa.state import ProgramState

_logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: #357: this block's one TOC entry. The three forms are sub-headings.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-trades",
    title="Record a trade",
)
SECTIONS: Final[tuple[SectionSpec, ...]] = (SECTION,)

#: The Settle form's heading id, which the unsettled-expiry prompt links to.
SETTLE_ANCHOR: Final = "section-settle"

_REASON_HINT = (
    "ROUTINE proceeds (a scheduled roll, an expiry) reduce gross carry. "
    "MONETIZATION proceeds (a gain harvested in stress) are kept out of "
    "gross carry and reported in net carry only. It is recorded now, "
    "never inferred later."
)

_DATE_HINT = "Blank means today (the program's date)."

# ── Form plumbing ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class TradeForm:
    """What a form needs to be reviewed and confirmed.

    Attributes:
        prefix: The form's id prefix (``close``, ``settle``, ``roll``).
        parse: Raw field values to a validated entry.
        review: Say what the entry would record.
        record: Record it. Called only after the operator has confirmed.

    """

    prefix: str
    parse: Callable[[Mapping[str, Any], date], Any]
    review: Callable[
        [Any, Sequence[OptionPosition], date, date | None],
        te.Review,
    ]
    record: Callable[[Any, ProgramState], None]


CLOSE: Final = TradeForm(
    prefix="close",
    parse=lambda raw, today: te.parse_close(raw, today=today),
    review=lambda entry, held, today, mark: te.review_close(
        entry,
        held,
        today=today,
        last_mark=mark,
    ),
    record=te.record_close,
)
SETTLE: Final = TradeForm(
    prefix="settle",
    parse=lambda raw, today: te.parse_settle(raw, today=today),
    review=lambda entry, held, today, mark: te.review_settle(
        entry,
        held,
        today=today,
        last_mark=mark,
    ),
    record=te.record_settle,
)
ROLL: Final = TradeForm(
    prefix="roll",
    parse=lambda raw, today: te.parse_roll(raw, today=today),
    review=lambda entry, held, today, mark: te.review_roll(
        entry,
        held,
        today=today,
        last_mark=mark,
    ),
    record=te.record_roll,
)

_UNEXPECTED = "Something went wrong — see the server log."


def _review_children(review: te.Review) -> Component:
    parts: list[Component] = [html.P(review.summary, className="env-verdict")]
    parts.append(html.Ul([html.Li(line) for line in review.lines]))
    parts.extend(
        html.P(f"⚠ {warning}", className="field-hint trade-warning")
        for warning in review.warnings
    )
    return html.Div(parts)


def review_trade(
    form: TradeForm,
    raw: Mapping[str, Any],
    state: ProgramState,
) -> tuple[Any, bool, Component | list[Any], Component]:
    """Validate a form and say what confirming it would record.

    Nothing is written. Directly callable from tests, like the BOOK zone's
    other ``_..._logic`` functions.

    Returns:
        ``(pending, confirm_row_hidden, review_text, status)``: the raw
        values to replay on confirm (``None`` when refused), whether the
        confirm row stays hidden, the review text, and a status line.

    """
    try:
        today = te.program_today(state)
        entry = form.parse(raw, today)
        review = form.review(
            entry,
            state.positions_snapshot(),
            today,
            te.last_mark_date(state),
        )
    except te.TradeEntryError as exc:
        return None, True, [], _status(str(exc), error=True)
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Unexpected error reviewing a /design trade")
        return None, True, [], _status(_UNEXPECTED, error=True)
    return (
        dict(raw),
        False,
        _review_children(review),
        _status("Review the trade below, then confirm it.", error=False),
    )


def confirm_trade(
    form: TradeForm,
    pending: Mapping[str, Any] | None,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component, bool]:
    """Record the reviewed trade.

    Returns:
        ``(book_version, status, recorded)``. The version is ``no_update``
        unless the trade was recorded: a refused write never bumps it.

    """
    if not pending:
        return (
            no_update,
            _status("Review the trade first, then confirm it.", error=True),
            False,
        )
    said: list[str] = []

    def _record() -> None:
        today = te.program_today(state)
        entry = form.parse(pending, today)
        said.append(
            form.review(
                entry,
                state.positions_snapshot(),
                today,
                te.last_mark_date(state),
            ).summary,
        )
        try:
            form.record(entry, state)
        except KeyError as exc:
            # The lot went between the re-review above and the write.
            raise te.TradeEntryError(
                "That lot is no longer in the book (it was changed or "
                "removed since the review). Review it again.",
            ) from exc

    was_dirty = state.dirty
    error = _guarded_mutation(_record)
    if error is not None:
        if state.dirty and not was_dirty:
            # The write went in and the save did not: the book holds the
            # trade unsaved, and entering it again would record it twice.
            error += (
                " The book now holds changes that were not saved: check "
                "Book changes before entering this trade again."
            )
        return no_update, _status(error, error=True), False
    return version + 1, _status(f"Recorded: {said[0]}", error=False), True


def review_outputs(
    form: TradeForm,
    read_raw: Callable[[tuple[object, ...]], dict[str, Any]],
    values: tuple[object, ...],
    state: ProgramState,
) -> tuple[Any, ...]:
    """Return the review callback's outputs, with the form's read guarded.

    Reading the fields is outside :func:`review_trade`'s own guard, and a
    raise there would leave the Review button doing nothing, with no status
    and no review text. It is reported like any other unexpected failure.
    """
    try:
        raw = read_raw(values)
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Could not read a /design trade form")
        return None, True, [], _status(_UNEXPECTED, error=True)
    return review_trade(form, raw, state)


def confirm_outputs(
    form: TradeForm,
    pending: Mapping[str, Any] | None,
    version: int,
    state: ProgramState,
    rebuild: Callable[[], Component],
) -> tuple[Any, ...]:
    """Return the confirm callback's outputs: record, then rebuild fields.

    The trade is already recorded when the fields are rebuilt, so a rebuild
    that raises must not strand the form with no version bump and no status:
    the fields are simply left as they were.
    """
    new_version, status, recorded = confirm_trade(form, pending, version, state)
    keep: object = no_update
    fields = _guarded(rebuild, keep) if recorded else keep
    return (new_version, status, None, True, False, fields)


@dataclass(frozen=True)
class _Wiring:
    """How a form's fields reach its callbacks."""

    states: Sequence[State]
    read_raw: Callable[[tuple[object, ...]], dict[str, Any]]
    edit_inputs: Sequence[Input]
    rebuild: Callable[[], Component]


def _register_form(
    app: ProgramDashApp,
    form: TradeForm,
    wiring: _Wiring,
) -> None:
    """Register a form's review, confirm and edit-hides-confirm callbacks."""
    prefix = form.prefix
    # #387's idiom: lock the button the instant it is clicked, with no
    # server round trip, so a double click cannot record twice. The
    # server callback below re-opens it on every branch.
    app.clientside_callback(  # type: ignore[no-untyped-call]
        "function(n_clicks) { return true; }",
        Output(f"{prefix}-confirm", "disabled", allow_duplicate=True),
        Input(f"{prefix}-confirm", "n_clicks"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output(f"{prefix}-pending", "data"),
        Output(f"{prefix}-confirm-row", "hidden"),
        Output(f"{prefix}-review-text", "children"),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Input(f"{prefix}-review", "n_clicks"),
        *wiring.states,
        prevent_initial_call=True,
    )
    def _review(_clicks: int | None, *values: object) -> tuple[Any, ...]:
        return review_outputs(
            form,
            wiring.read_raw,
            values,
            app.program_state,
        )

    @app.callback(
        Output(BOOK_VERSION_STORE, "data", allow_duplicate=True),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Output(f"{prefix}-pending", "data", allow_duplicate=True),
        Output(f"{prefix}-confirm-row", "hidden", allow_duplicate=True),
        Output(f"{prefix}-confirm", "disabled", allow_duplicate=True),
        Output(f"{prefix}-fields", "children", allow_duplicate=True),
        Input(f"{prefix}-confirm", "n_clicks"),
        State(f"{prefix}-pending", "data"),
        State(BOOK_VERSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def _confirm(
        _clicks: int | None,
        pending: dict[str, Any] | None,
        version: int,
    ) -> tuple[Any, ...]:
        return confirm_outputs(
            form,
            pending,
            version,
            app.program_state,
            wiring.rebuild,
        )

    @app.callback(
        Output(f"{prefix}-confirm-row", "hidden", allow_duplicate=True),
        Output(f"{prefix}-pending", "data", allow_duplicate=True),
        Input(f"{prefix}-cancel", "n_clicks"),
        *wiring.edit_inputs,
        prevent_initial_call=True,
    )
    def _hide(*_args: object) -> tuple[bool, None]:
        # Any edit after a review makes the reviewed text stale, so the
        # operator reviews again rather than confirming a sentence that no
        # longer matches the form.
        return True, None


def _guarded(build: Callable[[], _T], fallback: _T) -> _T:
    """Run a callback body; an empty control beats a dead callback.

    The callbacks that list lots and fill small helpers are read-only, so a
    raise has nothing to undo: it is logged and the control stays as it was.
    """
    try:
        return build()
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("A /design trade form's helper callback failed")
        return fallback


def _keep_if_present(
    value: str | None,
    options: Sequence[Mapping[str, str]],
) -> str | None:
    """Keep the chosen value if it is still offered, else clear it."""
    return value if any(o["value"] == value for o in options) else None


# ── Layout ──────────────────────────────────────────────────────────────


def _field(
    label: str, control: Component, hint: str | None = None
) -> Component:
    children: list[Component] = [html.Label(label), control]
    if hint:
        children.append(html.Small(hint, className="field-hint"))
    return html.Div(children, className="editor-field")


def _confirm_row(prefix: str, verb: str) -> Component:
    return html.Div(
        [
            html.Div(id=f"{prefix}-review-text", className="trade-review"),
            html.Button(
                f"Confirm and record {verb}",
                id=f"{prefix}-confirm",
                className="btn btn-primary",
            ),
            html.Button(
                "Cancel",
                id=f"{prefix}-cancel",
                className="btn btn-secondary",
            ),
        ],
        id=f"{prefix}-confirm-row",
        className="import-confirm-row",
        hidden=True,
    )


_REASONS: Final[tuple[str, str]] = (
    CloseReason.ROUTINE.value,
    CloseReason.MONETIZATION.value,
)


# Each form's fields live in a container the confirm callback replaces with
# freshly built ones, rather than blanking them one by one: a ``dcc.Input``
# the server clears by setting ``value`` to ``None`` keeps the last value the
# operator typed and ignores the next entry if it is the same, so a second
# close with the same ``0`` fees would read as blank. A new component has no
# such memory (the same fix as the add-position form's, ``book.py``).


def _close_fields() -> Component:
    return html.Fieldset(
        [
            _field(
                "Lot",
                dcc.Dropdown(
                    id="close-lot",
                    options=[],
                    placeholder="Choose a lot…",
                ),
            ),
            _field(
                "Contracts to close",
                html.Div(
                    [
                        dcc.Input(id="close-contracts", type="number"),
                        html.Button(
                            "Whole lot",
                            id="close-whole-lot",
                            className="btn btn-secondary",
                        ),
                    ],
                    className="trade-input-row",
                ),
            ),
            _field(
                "Price per share",
                dcc.Input(id="close-price", type="number"),
            ),
            _field(
                "Fees (enter 0 if none)",
                dcc.Input(id="close-fees", type="number"),
            ),
            _field(
                "Reason",
                dcc.RadioItems(
                    id="close-reason",
                    options=list(_REASONS),
                    value=None,
                ),
                _REASON_HINT,
            ),
            _field(
                "Trade date",
                dcc.DatePickerSingle(id="close-date"),
                _DATE_HINT,
            ),
            _field(
                "Note (optional)",
                dcc.Input(id="close-note", type="text"),
            ),
            html.Button(
                "Review close",
                id="close-review",
                className="btn btn-primary",
            ),
        ],
        className="editor-form",
    )


def _close_form() -> Component:
    return html.Div(
        [
            html.H4("Close", id="section-close"),
            html.P(
                "Sell some or all of a lot, or buy a short lot back, and "
                "record the price and fees it traded at.",
                className="plain-language",
            ),
            html.Div(_close_fields(), id="close-fields"),
            _confirm_row("close", "close"),
            dcc.Store(id="close-pending", data=None),
        ],
        className="trade-form",
    )


def _settle_fields() -> Component:
    return html.Fieldset(
        [
            _field(
                "Lot (at or past expiry)",
                dcc.Dropdown(
                    id="settle-lot",
                    options=[],
                    placeholder="Choose a lot…",
                ),
            ),
            html.Div(id="settle-expiry-hint", className="field-hint"),
            _field(
                "Settlement value per share (0 if worthless)",
                dcc.Input(id="settle-value", type="number"),
            ),
            _field(
                "Fees (enter 0 if none)",
                dcc.Input(id="settle-fees", type="number"),
            ),
            _field(
                "Settlement date",
                dcc.DatePickerSingle(id="settle-date"),
                "Required: it decides which period the cash lands in.",
            ),
            _field(
                "Note (optional)",
                dcc.Input(id="settle-note", type="text"),
            ),
            html.Button(
                "Review settlement",
                id="settle-review",
                className="btn btn-primary",
            ),
        ],
        className="editor-form",
    )


def _settle_form() -> Component:
    return html.Div(
        [
            html.H4("Settle", id=SETTLE_ANCHOR),
            html.P(
                "SPX options are European and cash-settled, so every expiry "
                "is a settlement, in the money or not. Enter the settlement "
                "value per share, or 0 if it expired worthless.",
                className="plain-language",
            ),
            html.Div(_settle_fields(), id="settle-fields"),
            _confirm_row("settle", "settlement"),
            dcc.Store(id="settle-pending", data=None),
        ],
        className="trade-form",
    )


def _roll_fields() -> Component:
    return html.Div(
        [
            html.Fieldset(
                [
                    _field(
                        "Structure",
                        dcc.Dropdown(
                            id="roll-structure",
                            options=[],
                            placeholder="Choose a structure…",
                        ),
                    ),
                ],
                className="editor-form",
            ),
            html.Div(
                html.P(
                    "Choose a structure to roll.",
                    className="plain-language",
                ),
                id="roll-legs",
            ),
            html.Fieldset(
                [
                    _field(
                        "Reason",
                        dcc.RadioItems(
                            id="roll-reason",
                            options=list(_REASONS),
                            value=None,
                        ),
                        _REASON_HINT,
                    ),
                    _field(
                        "Trade date",
                        dcc.DatePickerSingle(id="roll-date"),
                        _DATE_HINT,
                    ),
                    _field(
                        "New structure tag (optional)",
                        dcc.Input(id="roll-tag", type="text"),
                        "Blank keeps each leg's tag, so a spread stays "
                        "grouped for the roll plan.",
                    ),
                    _field(
                        "Note (optional)",
                        dcc.Input(id="roll-note", type="text"),
                    ),
                    html.Button(
                        "Review roll",
                        id="roll-review",
                        className="btn btn-primary",
                    ),
                ],
                className="editor-form",
            ),
        ],
    )


def _roll_form() -> Component:
    return html.Div(
        [
            html.H4("Roll", id="section-roll"),
            html.P(
                "Roll a structure: each leg is closed and its replacement "
                "opened, every fill at its own price and fees (never one "
                "net figure). A spread is rolled as one action: all its "
                "legs are recorded together, or none are.",
                className="plain-language",
            ),
            html.Div(_roll_fields(), id="roll-fields"),
            _confirm_row("roll", "roll"),
            dcc.Store(id="roll-pending", data=None),
        ],
        className="trade-form",
    )


def layout() -> html.Div:
    """Build the trade block: the prompt, then Close, Settle and Roll."""
    return html.Div(
        [
            html.H3(SECTION.title, id=SECTION.anchor_id),
            html.P(
                "Record a trade here rather than with Remove. A close, a "
                "settlement or a roll is recorded with its cash, so realized "
                "carry can be reconciled against your statements. Remove "
                "records a deletion with no cash: use it for a lot that should "
                "never have been in the book, not to book a trade.",
                className="plain-language",
            ),
            html.Div(id="trade-unsettled-prompt"),
            _close_form(),
            _settle_form(),
            _roll_form(),
        ],
        className="trade-forms",
    )


# ── The unsettled-expiry prompt ─────────────────────────────────────────


def unsettled_prompt(state: ProgramState) -> Component:
    """List the lots past expiry with no settlement, each linked to Settle.

    Empty when there are none. The test is
    :func:`~deltadewa.app.trade_entry.unsettled_lots` on the program's day,
    the expiry boundary ``mark_book`` flags legs with on the weekly job's
    freshly loaded book, so this appears when the next boundary mark would
    carry the break.
    """
    lots = te.unsettled_lots(
        state.positions_snapshot(),
        valuation_date=te.program_day(state),
    )
    if not lots:
        return html.Div()
    rows = [
        html.Li(
            [
                (
                    f"{te.lot_label(lot)}, expired "
                    f"{lot.option.maturity_date.date()}: no settlement "
                    "recorded. "
                ),
                html.A(
                    "Settle…",
                    id={"type": "trade-settle-lot", "lot": lot.position_id},
                    href=f"#{SETTLE_ANCHOR}",
                    n_clicks=0,
                    className="btn btn-secondary",
                ),
            ],
        )
        for lot in lots
    ]
    return html.Div(
        [
            html.P(
                "Expired and still in the book. The model marks an expired "
                "lot at its intrinsic value at the book's spot, which is not "
                "its settlement value, so the period it falls in cannot "
                "reconcile until it is settled:",
                className="panel-notice__headline",
            ),
            html.Ul(rows),
        ],
        className="panel-notice panel-notice--blocked",
    )


# ── The roll form's per-leg blocks ──────────────────────────────────────


def _leg_field(
    lot: OptionPosition,
    field: str,
    label: str,
    *,
    placeholder: str | None = None,
) -> Component:
    return _field(
        label,
        dcc.Input(
            id={"type": "roll-field", "lot": lot.position_id, "field": field},
            type="number",
            placeholder=placeholder,
        ),
    )


def roll_leg_blocks(state: ProgramState, key: str | None) -> Component:
    """Build one block of fields per leg of the chosen structure."""
    if not key:
        return html.P("Choose a structure to roll.", className="plain-language")
    try:
        legs = te.structure_legs(state.positions_snapshot(), key)
    except te.TradeEntryError as exc:
        return _status(str(exc), error=True)
    blocks: list[Component] = []
    for number, lot in enumerate(legs, start=1):
        quantity = int(lot.quantity)
        blocks.append(
            html.Fieldset(
                [
                    html.Legend(f"Leg {number}: {te.lot_label(lot)}"),
                    _leg_field(
                        lot,
                        "close_price",
                        "Close price per share",
                    ),
                    _leg_field(
                        lot,
                        "close_fees",
                        "Close fees (enter 0 if none)",
                    ),
                    _leg_field(
                        lot,
                        "strike",
                        "New strike",
                        placeholder=f"was {lot.option.strike_price:g}",
                    ),
                    _field(
                        "New maturity",
                        dcc.DatePickerSingle(
                            id={
                                "type": "roll-maturity",
                                "lot": lot.position_id,
                            },
                        ),
                    ),
                    _leg_field(
                        lot,
                        "quantity",
                        "New quantity (signed)",
                        placeholder=f"blank = {quantity:+d}",
                    ),
                    _leg_field(
                        lot,
                        "price",
                        "New price per share",
                    ),
                    _leg_field(
                        lot,
                        "fees",
                        "New fees (enter 0 if none)",
                    ),
                ],
                className="editor-form trade-leg",
            ),
        )
    return html.Div(blocks)


def _roll_raw(values: tuple[object, ...]) -> dict[str, Any]:
    """Gather the roll form's raw values, legs in the order they render.

    ``ctx.states_list`` carries each pattern-matched field's id, which is
    what says which leg a value belongs to and which field it is.
    """
    _structure, reason, trade_date, tag, note, *_legs = values
    legs: dict[str, dict[str, Any]] = {}
    fields, maturities = ctx.states_list[5], ctx.states_list[6]
    for item in fields:
        lot = item["id"]["lot"]
        legs.setdefault(lot, {"position_id": lot})[item["id"]["field"]] = (
            item.get("value")
        )
    for item in maturities:
        lot = item["id"]["lot"]
        # ``value`` whichever property the State reads: here, ``date``.
        legs.setdefault(lot, {"position_id": lot})["maturity"] = item.get(
            "value",
        )
    return {
        "legs": list(legs.values()),
        "reason": reason,
        "date": trade_date,
        "tag": tag,
        "note": note,
    }


# ── Callbacks ───────────────────────────────────────────────────────────


def _simple_raw(
    *keys: str,
) -> Callable[[tuple[object, ...]], dict[str, Any]]:
    def _read(values: tuple[object, ...]) -> dict[str, Any]:
        return dict(zip(keys, values, strict=True))

    return _read


def _register_close(app: ProgramDashApp) -> None:
    _register_form(
        app,
        CLOSE,
        _Wiring(
            states=[
                State("close-lot", "value"),
                State("close-contracts", "value"),
                State("close-price", "value"),
                State("close-fees", "value"),
                State("close-reason", "value"),
                State("close-date", "date"),
                State("close-note", "value"),
            ],
            read_raw=_simple_raw(
                "position_id",
                "contracts",
                "price",
                "fees",
                "reason",
                "date",
                "note",
            ),
            edit_inputs=[
                Input("close-lot", "value"),
                Input("close-contracts", "value"),
                Input("close-price", "value"),
                Input("close-fees", "value"),
                Input("close-reason", "value"),
                Input("close-date", "date"),
                Input("close-note", "value"),
            ],
            rebuild=_close_fields,
        ),
    )

    @app.callback(
        Output("close-lot", "options"),
        Output("close-lot", "value"),
        Input(BOOK_VERSION_STORE, "data"),
        State("close-lot", "value"),
    )
    def _close_options(_version: int, value: str | None) -> tuple[Any, ...]:
        def _build() -> tuple[Any, ...]:
            options = [
                {"label": te.lot_label(p), "value": p.position_id}
                for p in app.program_state.positions_snapshot()
            ]
            return options, _keep_if_present(value, options)

        return _guarded(_build, ([], None))

    @app.callback(
        Output("close-contracts", "value", allow_duplicate=True),
        Input("close-whole-lot", "n_clicks"),
        State("close-lot", "value"),
        prevent_initial_call=True,
    )
    def _whole_lot(_clicks: int | None, lot_id: str | None) -> object:
        def _size() -> object:
            for position in app.program_state.positions_snapshot():
                if position.position_id == lot_id:
                    return abs(int(position.quantity))
            return no_update

        keep: object = no_update
        return _guarded(_size, keep)


def _register_settle(app: ProgramDashApp) -> None:
    _register_form(
        app,
        SETTLE,
        _Wiring(
            states=[
                State("settle-lot", "value"),
                State("settle-value", "value"),
                State("settle-fees", "value"),
                State("settle-date", "date"),
                State("settle-note", "value"),
            ],
            read_raw=_simple_raw(
                "position_id",
                "settlement",
                "fees",
                "date",
                "note",
            ),
            edit_inputs=[
                Input("settle-lot", "value"),
                Input("settle-value", "value"),
                Input("settle-fees", "value"),
                Input("settle-date", "date"),
                Input("settle-note", "value"),
            ],
            rebuild=_settle_fields,
        ),
    )

    @app.callback(
        Output("settle-lot", "options"),
        Output("settle-lot", "value"),
        Output("trade-unsettled-prompt", "children"),
        Input(BOOK_VERSION_STORE, "data"),
        State("settle-lot", "value"),
    )
    def _settle_options(_version: int, value: str | None) -> tuple[Any, ...]:
        def _build() -> tuple[Any, ...]:
            state = app.program_state
            lots = te.unsettled_lots(
                state.positions_snapshot(),
                valuation_date=te.program_day(state),
            )
            options = [
                {"label": te.lot_label(p), "value": p.position_id} for p in lots
            ]
            return (
                options,
                _keep_if_present(value, options),
                unsettled_prompt(state),
            )

        return _guarded(
            _build,
            (
                [],
                None,
                _status(
                    "Could not check the book for expired lots: see the "
                    "server log. An expired lot may be waiting to be settled.",
                    error=True,
                ),
            ),
        )

    @app.callback(
        Output("settle-lot", "value", allow_duplicate=True),
        Input({"type": "trade-settle-lot", "lot": ALL}, "n_clicks"),
        prevent_initial_call=True,
    )
    def _preselect(_clicks: list[int | None]) -> object:
        triggered = ctx.triggered_id
        # A pattern-matching ALL input also fires once when a matching
        # component first appears, with n_clicks still 0: only a click
        # counts.
        if not isinstance(triggered, dict) or not ctx.triggered[0]["value"]:
            return no_update
        return triggered["lot"]

    @app.callback(
        Output("settle-expiry-hint", "children"),
        Input("settle-lot", "value"),
    )
    def _expiry_hint(lot_id: str | None) -> str:
        def _hint() -> str:
            for position in app.program_state.positions_snapshot():
                if position.position_id == lot_id:
                    return (
                        f"Expires {position.option.maturity_date.date()}. "
                        "The settlement date cannot be earlier."
                    )
            return ""

        return _guarded(_hint, "")


def _register_roll(app: ProgramDashApp) -> None:
    leg_fields = {"type": "roll-field", "lot": ALL, "field": ALL}
    leg_maturities = {"type": "roll-maturity", "lot": ALL}
    _register_form(
        app,
        ROLL,
        _Wiring(
            states=[
                State("roll-structure", "value"),
                State("roll-reason", "value"),
                State("roll-date", "date"),
                State("roll-tag", "value"),
                State("roll-note", "value"),
                State(leg_fields, "value"),
                State(leg_maturities, "date"),
            ],
            read_raw=_roll_raw,
            edit_inputs=[
                Input("roll-structure", "value"),
                Input("roll-reason", "value"),
                Input("roll-date", "date"),
                Input("roll-tag", "value"),
                Input("roll-note", "value"),
                Input(leg_fields, "value"),
                Input(leg_maturities, "date"),
            ],
            rebuild=_roll_fields,
        ),
    )

    @app.callback(
        Output("roll-structure", "options"),
        Output("roll-structure", "value"),
        Input(BOOK_VERSION_STORE, "data"),
        State("roll-structure", "value"),
    )
    def _roll_options(_version: int, value: str | None) -> tuple[Any, ...]:
        def _build() -> tuple[Any, ...]:
            options = te.structure_options(
                app.program_state.positions_snapshot(),
            )
            return options, _keep_if_present(value, options)

        return _guarded(_build, ([], None))

    @app.callback(
        Output("roll-legs", "children"),
        Input("roll-structure", "value"),
        prevent_initial_call=True,
    )
    def _roll_blocks(key: str | None) -> Component:
        try:
            return roll_leg_blocks(app.program_state, key)
        except Exception:  # pylint: disable=broad-exception-caught
            _logger.exception("Could not build the roll form's leg blocks")
            return _status(_UNEXPECTED, error=True)


def register(app: ProgramDashApp) -> None:
    """Wire the trade forms' callbacks.

    Called from :func:`deltadewa.app.pages.design.page.register_callbacks`
    after the BOOK zone's own, behind that function's no-IPS guard.
    """
    _register_close(app)
    _register_settle(app)
    _register_roll(app)
