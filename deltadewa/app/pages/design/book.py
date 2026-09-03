"""The `/design` page's BOOK zone: add/remove positions, import/export.

Every mutating callback routes through a module-level ``_..._logic``
function that is directly callable from tests (the ``@app.callback``-
decorated function is a thin wrapper reading Dash-specific context, e.g.
``dash.ctx``, and handing plain values to it). Failures are contained by
:func:`_guarded_mutation` — except :func:`_import_logic`, which needs to
tell a policy refusal apart from any other failure and so handles its
own try/except — so nothing here ever leaks a traceback to the browser,
and a failed mutation never bumps ``book-version``: the single
``dcc.Store`` every read-only panel on the page (this zone's own
position table, and every PLANNING/EXPLORATION panel) watches for "the
book changed, re-read it." Those other zones' reads have no mutator to
guard, so they use ``panel_guard.safe_render`` instead — the same
no-leaked-traceback discipline, applied to an engine ``ValueError`` (a
structurally missing input) rather than a failed mutation.

``BOOK_VERSION_STORE`` and ``MUTATION_STATUS`` are exported because
every other panel module watches the former, and the PLANNING zone's
provenance panel writes into both (#308's one cross-zone id straddler:
its "mark inputs reviewed" control is a BOOK mutation, sitting in
PLANNING's markup).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dash import ALL, Input, Output, State, ctx, dcc, html, no_update
from dash.development.base_component import Component

from deltadewa.analysis.crash_repricing import is_expired
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.panel_guard import status_message as _status
from deltadewa.clock import program_now
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.state import ConfirmationRequiredError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition
    from deltadewa.state import ProgramState

_logger = logging.getLogger(__name__)

_REQUIRED_ADD_FIELDS_MSG = "Strike, maturity, and quantity are required."

# The two ids every other zone/panel module needs: every PLANNING and
# EXPLORATION panel watches BOOK_VERSION_STORE as its re-render trigger,
# and the provenance panel's "mark inputs reviewed" control writes both.
BOOK_VERSION_STORE = "book-version"
MUTATION_STATUS = "mutation-status"


def _guarded_mutation(action: Callable[[], None]) -> str | None:
    """Run a ``ProgramState`` mutator; never let it leak a traceback.

    Args:
        action: A zero-argument callable performing exactly one
            ``ProgramState`` mutation. Its return value is ignored — the
            caller supplies its own success message, since this only
            ever reports failure.

    Returns:
        ``None`` on success, or a clean, user-facing message on failure.

    """
    try:
        action()
    except ConfirmationRequiredError as exc:
        return str(exc)
    except (ValueError, IndexError) as exc:
        return str(exc)
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Unexpected error applying a /design mutation")
        return "Something went wrong — see the server log."
    return None


def _position_row(index: int, position: OptionPosition) -> html.Tr:
    """Build one editable <tr>: the position, plus a confirm-gated remove."""
    entry_premium_text = (
        f"{position.entry_premium:,.2f}"
        if position.entry_premium is not None
        else "—"
    )
    confirm_message = (
        f"Remove position {index}: {position.quantity:,.0f}x "
        f"{position.option.option_type.value} "
        f"{position.option.strike_price:,.0f} exp "
        f"{position.option.maturity_date.strftime('%Y-%m-%d')}? This "
        "cannot be undone from this page — re-add it manually if needed."
    )
    return html.Tr(
        [
            html.Td(f"{position.option.strike_price:,.0f}"),
            html.Td(position.option.option_type.value),
            html.Td(position.exercise_style.value),
            html.Td(position.option.maturity_date.strftime("%Y-%m-%d")),
            html.Td(f"{position.quantity:,.0f}"),
            html.Td(entry_premium_text),
            html.Td(
                dcc.ConfirmDialogProvider(
                    id={"type": "remove-confirm", "index": index},
                    message=confirm_message,
                    children=html.Button(
                        "Remove",
                        className="btn btn-remove",
                    ),
                ),
            ),
        ],
    )


def _net_delta_readout(portfolio: OptionPortfolio) -> Component:
    """Render Part X #10's scalar: net delta, right now.

    The grid form survived the Dash rebuild (``net_delta`` is one of the
    EXPLORATION heatmaps' metric options); the scalar the notebooks' Net
    Hedge Summary showed did not. It belongs beside the underlying quantity
    because that input is the other half of the same sentence — how much
    equity is held, and how much of it the options actually offset.
    """
    stats = portfolio.summary_stats()
    net_delta = stats.get("net_delta")
    if net_delta is None:
        return html.P(
            (
                "Net delta is unavailable — "
                "the book's Greeks could not be computed."
            ),
            className="plain-language",
        )
    return html.P(
        f"Net delta {net_delta:,.0f} against "
        f"{portfolio.underlying_quantity:,.0f} shares of underlying — the "
        "book's total directional exposure, options and equity combined.",
        className="plain-language",
    )


def _render_position_table_logic(
    *,
    positions: Sequence[OptionPosition],
) -> Component:
    """Build the position table wholesale from the live portfolio.

    Always a full rebuild, never a ``Patch()`` — removing a position
    shifts every later index, so every remove button's id must be
    recomputed from the current list, not patched in place.

    Takes the positions rather than the portfolio so callers can hand it
    ``ProgramState.positions_snapshot()``: this is the one place page code
    iterates the live list, and iterating it directly races a concurrent
    mutator into ``RuntimeError: list changed size during iteration``
    (#299).
    """
    if not positions:
        return html.P("No positions in the book yet.")

    header = html.Tr(
        [
            html.Th("Strike"),
            html.Th("Type"),
            html.Th("Exercise"),
            html.Th("Expiry"),
            html.Th("Quantity"),
            html.Th("Entry premium"),
            html.Th(""),
        ],
    )
    rows = [
        _position_row(index, position)
        for index, position in enumerate(positions)
    ]
    return html.Table(
        [html.Thead(header), html.Tbody(rows)],
        className="position-table",
    )


def _add_position_logic(  # pylint: disable=too-many-arguments
    *,
    strike: float | None,
    maturity: str | None,
    quantity: float | None,
    option_type: str,
    exercise_style: str,
    entry_premium: float | None,
    structure_id: str | None,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component, Any, Any, Any, Any, Any, Any, Any, bool]:
    """Add a position from the BOOK zone's add-form.

    Returns:
        A tuple matching the callback's Outputs: the new ``book-version``
        (or ``no_update`` on failure), a status message, the seven form
        fields' next values — cleared on success (so the operator isn't
        typing over stale values on the next add) and left as ``no_update``
        on failure (so a typo can be fixed and resubmitted rather than
        retyped from scratch) — and finally ``False`` for the
        ``add-form-fieldset``'s ``disabled``, on every branch: a
        clientside callback (see :func:`register`) sets it ``True`` the
        instant the button is clicked, closing the window #387 reported
        (typing a new entry while a submission is in flight, only to have
        this response's field-clear silently overwrite it) by disabling
        every field in the form, not just the button — nothing can be
        typed into it until the response has landed. This is what
        re-opens the form once the response — success or failure — has
        actually been applied.

    """
    if strike is None or maturity is None or quantity is None:
        return (
            no_update,
            _status(_REQUIRED_ADD_FIELDS_MSG, error=True),
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            False,
        )

    maturity_date = datetime.strptime(maturity, "%Y-%m-%d").replace(
        tzinfo=UTC,
    )

    def _do_add() -> None:
        # A plain def, not a lambda: state.add_position returns the new
        # OptionPosition, and _guarded_mutation's Callable[[], None]
        # discards a def's return value more predictably under mypy
        # than a lambda's inferred return type does.
        state.add_position(
            strike_price=strike,
            maturity_date=maturity_date,
            quantity=int(quantity),
            option_type=OptionType(option_type),
            exercise_style=ExerciseStyle(exercise_style),
            entry_premium=entry_premium,
            # Blank means "standalone leg", not "a structure named ''" —
            # an empty text input yields "" and must not become a tag that
            # silently groups every untagged leg into one structure (#333).
            structure_id=(structure_id or "").strip() or None,
        )

    error = _guarded_mutation(_do_add)
    if error is not None:
        return (
            no_update,
            _status(error, error=True),
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            False,
        )

    # Reset the exercise-style field back to the IPS default rather than
    # whatever was just submitted — ips_config is guaranteed non-None in
    # practice (the page is gated on it), the None branch only exists so
    # this stays type-safe without a runtime assertion.
    reset_style = (
        state.ips_config.pricing.exercise_style.value
        if state.ips_config is not None
        else exercise_style
    )
    return (
        version + 1,
        _status("Added.", error=False),
        None,
        None,
        None,
        OptionType.PUT.value,
        reset_style,
        None,
        None,
        False,
    )


def _remove_position_logic(
    *,
    index: int,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component]:
    """Remove position *index* — the browser's confirm already happened.

    ``ConfirmDialogProvider``'s ``submit_n_clicks`` only increments once
    the native confirm dialog is accepted, so ``confirm=True`` is always
    correct here; the confirm gate lives client-side, not as a second
    Python-level check.
    """
    error = _guarded_mutation(
        lambda: state.remove_position(index, confirm=True),
    )
    if error is not None:
        return no_update, _status(error, error=True)
    return version + 1, _status("Removed.", error=False)


def _mark_inputs_reviewed_logic(
    *,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component]:
    """Confirm every pricing input — the browser's confirm already happened.

    Same ``ConfirmDialogProvider`` idiom as ``_remove_position_logic``:
    ``submit_n_clicks`` only increments once the native confirm dialog is
    accepted, so ``confirm=True`` is always correct here.
    """
    error = _guarded_mutation(
        lambda: state.mark_inputs_reviewed(confirm=True),
    )
    if error is not None:
        return no_update, _status(error, error=True)
    return version + 1, _status(
        "Pricing inputs marked reviewed.",
        error=False,
    )


def _set_underlying_quantity_logic(
    *,
    value: float | None,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component]:
    """Set the underlying notional being hedged."""
    if value is None:
        return no_update, _status(
            "Underlying quantity cannot be blank.",
            error=True,
        )
    error = _guarded_mutation(lambda: state.set_underlying_quantity(value))
    if error is not None:
        return no_update, _status(error, error=True)
    return version + 1, _status("Underlying quantity updated.", error=False)


def _import_logic(
    *,
    confirm: bool,
    target: str | None,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component, Any, Any]:
    """Import a portfolio export, refusing over unsaved changes.

    Doesn't route through :func:`_guarded_mutation` — unlike the other
    mutators, this needs to tell a policy refusal
    (``ConfirmationRequiredError``) apart from any other failure, since
    only a refusal should remember *target* and reveal the confirm row;
    any other failure (a bad path, a malformed file) should not offer
    "confirm and retry," since retrying would just fail again the same
    way.

    Returns:
        ``(book_version, status, pending_path, confirm_row_hidden)``.

    """
    if not target:
        # Unrelated to the confirm flow — leave any existing pending
        # path/reveal state exactly as it was.
        return (
            no_update,
            _status("An import path is required.", error=True),
            no_update,
            no_update,
        )

    try:
        state.import_portfolio(Path(target), confirm=confirm)
    except ConfirmationRequiredError as exc:
        return no_update, _status(str(exc), error=True), target, False
    except (ValueError, OSError) as exc:
        return no_update, _status(str(exc), error=True), no_update, True
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Unexpected error importing a /design portfolio")
        return (
            no_update,
            _status("Something went wrong — see the server log.", error=True),
            no_update,
            True,
        )

    # #365: an imported book may legitimately hold a leg that expired
    # after being added (persistence.py's importers pass
    # reject_expired=False) — the CLI importer prints a leg-by-leg
    # breakdown (app/import_portfolio.py's _warn_if_expired_legs); the
    # status-message plumbing here only carries one line, so a summary
    # count is the equivalent advisory for this surface.
    expired_count = sum(
        1
        for position in state.portfolio.positions
        if is_expired(position, valuation_date=state.portfolio.valuation_date)
    )
    message = "Imported."
    if expired_count:
        leg_word = "leg" if expired_count == 1 else "legs"
        message += (
            f" Imported with {expired_count} already-expired {leg_word}; "
            "see position detail."
        )
    return version + 1, _status(message, error=False), None, True


def _export_logic(*, state: ProgramState) -> tuple[Any, Component]:
    """Snapshot the live book and package it for browser download.

    Read-only — doesn't touch ``book-version``, correctly outside the
    "failed mutation" concern entirely.
    """
    # Stamped in the program's timezone: the file name is what a human
    # sorts and cites, so it should read as the desk's clock, not UTC.
    stamp = program_now(
        state.ips_config.program.timezone
        if state.ips_config is not None
        else None,
    )
    filename = f"design-export-{stamp:%Y%m%dT%H%M%S}.json"
    try:
        path = state.export_snapshot(filename)
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Unexpected error exporting the /design book")
        return no_update, _status(
            "Something went wrong — see the server log.",
            error=True,
        )
    # dash has no stub for dcc.send_file.
    download = dcc.send_file(  # type: ignore[attr-defined,no-untyped-call]
        str(path),
    )
    return download, _status(f"Exported to {filename}.", error=False)


def layout(
    *,
    app: ProgramDashApp,
    portfolio: OptionPortfolio,
    default_style: str,
) -> html.Div:
    """Build the BOOK zone: editor form, position table, import/export."""
    return html.Div(
        [
            html.H2("Book"),
            html.Div(
                [
                    html.Label("Underlying quantity"),
                    dcc.Input(
                        id="underlying-qty",
                        type="number",
                        value=portfolio.underlying_quantity,
                        debounce=True,
                    ),
                ],
                className="editor-field",
            ),
            html.Div(
                _safe_render(lambda: _net_delta_readout(portfolio)),
                id="net-delta-readout",
            ),
            html.H3("Add a position"),
            html.P(
                "Editing a position is remove + add, not in-place edit — "
                "there is no separate 'update' form.",
                className="plain-language",
            ),
            html.Fieldset(
                [
                    html.Div(
                        [
                            html.Label("Strike"),
                            dcc.Input(id="add-strike", type="number"),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Maturity"),
                            dcc.DatePickerSingle(id="add-maturity"),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Quantity"),
                            dcc.Input(id="add-quantity", type="number"),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Type"),
                            dcc.RadioItems(
                                id="add-option-type",
                                options=[
                                    OptionType.PUT.value,
                                    OptionType.CALL.value,
                                ],
                                value=OptionType.PUT.value,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Exercise style"),
                            dcc.RadioItems(
                                id="add-exercise-style",
                                options=[
                                    ExerciseStyle.EUROPEAN.value,
                                    ExerciseStyle.AMERICAN.value,
                                ],
                                value=default_style,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Entry premium (optional)"),
                            dcc.Input(
                                id="add-entry-premium",
                                type="number",
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Structure (optional)"),
                            dcc.Input(
                                id="add-structure-id",
                                type="text",
                                placeholder="e.g. collar-2027",
                            ),
                            html.Small(
                                "Same tag on both legs of a spread — the "
                                "roll planner then moves them together "
                                "and nets their cost. Blank = standalone.",
                                className="field-hint",
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Button(
                        "Add position",
                        id="add-submit",
                        className="btn btn-primary",
                    ),
                ],
                id="add-form-fieldset",
                className="editor-form",
                disabled=False,
            ),
            html.Div(id=MUTATION_STATUS),
            html.H3("Positions"),
            html.Div(
                _render_position_table_logic(
                    positions=app.program_state.positions_snapshot(),
                ),
                id="position-table",
            ),
            html.H3("Import / export"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Import path"),
                            dcc.Input(id="import-path", type="text"),
                        ],
                        className="editor-field",
                    ),
                    html.Button(
                        "Import",
                        id="import-submit",
                        className="btn btn-primary",
                    ),
                    html.Button(
                        "Export",
                        id="export-submit",
                        className="btn btn-primary",
                    ),
                ],
                className="editor-form",
            ),
            html.Div(
                [
                    html.P(
                        "Unsaved changes would be discarded by this import.",
                    ),
                    html.Button(
                        "Confirm & import",
                        id="import-confirm-submit",
                        className="btn btn-primary",
                    ),
                ],
                id="import-confirm-row",
                className="import-confirm-row",
                hidden=True,
            ),
            dcc.Download(id="export-download"),
            dcc.Store(id=BOOK_VERSION_STORE, data=0),
            dcc.Store(id="import-pending-path", data=None),
        ],
        className="zone-book",
    )


def register(app: ProgramDashApp) -> None:
    """Wire the BOOK zone's mutating callbacks and its own read-only reads.

    Called only from :func:`deltadewa.app.pages.design.page.register_callbacks`
    after that function's own ``app.ips_config is None`` guard — none of
    the callbacks below read ``ips_config``, so this needs no guard or
    capture of its own.
    """
    # #387: the add-position form race. A plain (server) callback reads
    # AND clears the form in one round trip, with nothing disabling the
    # fields while a submission is in flight — typing a new entry then
    # gets wiped by the previous submission's response landing on top of
    # it. This clientside callback locks the *whole form* (every field,
    # not just the button) the instant "Add position" is clicked, with no
    # server round trip — a disabled <fieldset> natively disables every
    # descendant control, including dcc.DatePickerSingle's plain <input>,
    # so there is no window at all where a keystroke could land in it
    # while a response is pending. The server callback below re-enables
    # it once the response has actually been applied (every branch of
    # `_add_position_logic` returns `False` for this Output — success and
    # failure alike, so a rejected submission's fields stay editable
    # rather than trapped behind a stuck-disabled form).
    # dash has no stub for clientside_callback.
    app.clientside_callback(  # type: ignore[no-untyped-call]
        "function(n_clicks) { return true; }",
        Output("add-form-fieldset", "disabled", allow_duplicate=True),
        Input("add-submit", "n_clicks"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output(BOOK_VERSION_STORE, "data", allow_duplicate=True),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Output("add-strike", "value"),
        Output("add-maturity", "date"),
        Output("add-quantity", "value"),
        Output("add-option-type", "value"),
        Output("add-exercise-style", "value"),
        Output("add-entry-premium", "value"),
        Output("add-structure-id", "value"),
        Output("add-form-fieldset", "disabled", allow_duplicate=True),
        Input("add-submit", "n_clicks"),
        State("add-strike", "value"),
        State("add-maturity", "date"),
        State("add-quantity", "value"),
        State("add-option-type", "value"),
        State("add-exercise-style", "value"),
        State("add-entry-premium", "value"),
        State("add-structure-id", "value"),
        State(BOOK_VERSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def _add_position(  # pylint: disable=too-many-arguments
        _n_clicks: int,
        strike: float | None,
        maturity: str | None,
        quantity: float | None,
        option_type: str,
        exercise_style: str,
        entry_premium: float | None,
        structure_id: str | None,
        version: int,
    ) -> tuple[Any, Component, Any, Any, Any, Any, Any, Any, Any, bool]:
        return _add_position_logic(
            strike=strike,
            maturity=maturity,
            quantity=quantity,
            option_type=option_type,
            exercise_style=exercise_style,
            entry_premium=entry_premium,
            structure_id=structure_id,
            version=version,
            state=app.program_state,
        )

    @app.callback(
        Output(BOOK_VERSION_STORE, "data", allow_duplicate=True),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Input({"type": "remove-confirm", "index": ALL}, "submit_n_clicks"),
        State(BOOK_VERSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def _remove_position(
        _all_submit_clicks: list[int | None],
        version: int,
    ) -> tuple[Any, Any]:
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            # Defensive only — prevent_initial_call=True already keeps
            # this from firing without a real click.
            return no_update, no_update
        # A pattern-matching ALL input fires once, with submit_n_clicks
        # still None, the moment a *new* matching component first
        # appears in the DOM (e.g. the position table's first render) —
        # not just on an actual confirmed click. prevent_initial_call
        # only suppresses the callback's own initial dispatch, not this;
        # ctx.triggered[0]["value"] is the real click count, so a falsy
        # value here means "just appeared," not "confirmed."
        if not ctx.triggered[0]["value"]:
            return no_update, no_update
        return _remove_position_logic(
            index=triggered["index"],
            version=version,
            state=app.program_state,
        )

    @app.callback(
        Output(BOOK_VERSION_STORE, "data", allow_duplicate=True),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Input("underlying-qty", "value"),
        State(BOOK_VERSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def _set_underlying_quantity(
        value: float | None,
        version: int,
    ) -> tuple[Any, Component]:
        return _set_underlying_quantity_logic(
            value=value,
            version=version,
            state=app.program_state,
        )

    @app.callback(
        Output(BOOK_VERSION_STORE, "data", allow_duplicate=True),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Output("import-pending-path", "data"),
        Output("import-confirm-row", "hidden"),
        Input("import-submit", "n_clicks"),
        Input("import-confirm-submit", "n_clicks"),
        State("import-path", "value"),
        State("import-pending-path", "data"),
        State(BOOK_VERSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def _import(  # pylint: disable=too-many-arguments
        _submit_clicks: int | None,
        _confirm_clicks: int | None,
        path: str | None,
        pending_path: str | None,
        version: int,
    ) -> tuple[Any, Component, Any, Any]:
        if ctx.triggered_id == "import-confirm-submit":
            confirm, target = True, pending_path
        else:
            confirm, target = False, path
        return _import_logic(
            confirm=confirm,
            target=target,
            version=version,
            state=app.program_state,
        )

    @app.callback(
        Output("export-download", "data"),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Input("export-submit", "n_clicks"),
        prevent_initial_call=True,
    )
    def _export(_n_clicks: int) -> tuple[Any, Component]:
        return _export_logic(state=app.program_state)

    @app.callback(
        Output("position-table", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_position_table(_version: int) -> Component:
        return _render_position_table_logic(
            positions=app.program_state.positions_snapshot(),
        )

    @app.callback(
        Output("net-delta-readout", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_net_delta(_version: int) -> Component:
        portfolio = app.program_state.portfolio
        return _safe_render(lambda: _net_delta_readout(portfolio))
