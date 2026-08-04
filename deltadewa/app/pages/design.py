"""The `/design` page: the operator's editor (BOOK zone).

Add/remove positions, the underlying quantity, and guarded import/export
— the sizing/ladder/roll/monetization planners and the stress-exploration
surfaces land in later milestones. Gates at the page level: without
``ips_config`` there is no source for the exercise-style default and no
policy to plan against, so the whole page (editor included) becomes a
single "no IPS policy loaded" state, the same discipline ``monitor.py``
uses.

Every mutating callback routes through a module-level ``_..._logic``
function that is directly callable from tests (the ``@app.callback``-
decorated function is a thin wrapper reading Dash-specific context, e.g.
``dash.ctx``, and handing plain values to it). Failures are contained by
:func:`_guarded_mutation` — except :func:`_import_logic`, which needs to
tell a policy refusal apart from any other failure and so handles its
own try/except — so nothing here ever leaks a traceback to the browser,
and a failed mutation never bumps ``book-version``: the single
``dcc.Store`` every read-only panel in this zone (and, later, the
planning/exploration zones) watches for "the book changed, re-read it."
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dash import ALL, Input, Output, State, ctx, dcc, html, no_update
from dash.development.base_component import Component

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.state import ConfirmationRequiredError

if TYPE_CHECKING:
    from collections.abc import Callable

    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition
    from deltadewa.state import ProgramState

_logger = logging.getLogger(__name__)

_REQUIRED_ADD_FIELDS_MSG = "Strike, maturity, and quantity are required."


def _no_ips_layout() -> html.Div:
    """Build the single "no IPS policy loaded" state for the /design page."""
    return html.Div(
        [
            html.H1("Design"),
            html.P(
                "No IPS policy is loaded, so there is no policy to plan "
                "against — sizing targets, ladder bands, and roll "
                "thresholds are all policy-derived, and the position "
                "editor's exercise-style default has no source either. "
                "Check that config/ips.yaml (or whatever path this "
                "program state was loaded with) exists and parses — see "
                "the server log at startup for the reason it was "
                "skipped.",
                className="no-ips-message",
            ),
        ],
        className="page page-design",
    )


def _status(message: str, *, error: bool) -> html.Div:
    """Build a status line for the BOOK zone's mutation feedback."""
    modifier = "error" if error else "success"
    return html.Div(
        message,
        className=f"status-message status-message--{modifier}",
    )


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


def _render_position_table_logic(
    *,
    portfolio: OptionPortfolio,
) -> Component:
    """Build the position table wholesale from the live portfolio.

    Always a full rebuild, never a ``Patch()`` — removing a position
    shifts every later index, so every remove button's id must be
    recomputed from the current list, not patched in place.
    """
    if not portfolio.positions:
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
        for index, position in enumerate(portfolio.positions)
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
    version: int,
    state: ProgramState,
) -> tuple[Any, Component, Any, Any, Any, Any, Any, Any]:
    """Add a position from the BOOK zone's add-form.

    Returns:
        A tuple matching the callback's Outputs: the new ``book-version``
        (or ``no_update`` on failure), a status message, and the six
        form fields' next values — cleared on success (so the operator
        isn't typing over stale values on the next add) and left as
        ``no_update`` on failure (so a typo can be fixed and resubmitted
        rather than retyped from scratch).

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
    return version + 1, _status("Imported.", error=False), None, True


def _export_logic(*, state: ProgramState) -> tuple[Any, Component]:
    """Snapshot the live book and package it for browser download.

    Read-only — doesn't touch ``book-version``, correctly outside the
    "failed mutation" concern entirely.
    """
    filename = f"design-export-{datetime.now(tz=UTC):%Y%m%dT%H%M%S}.json"
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


def render(app: ProgramDashApp) -> html.Div:
    """Build the /design page: the BOOK zone (editor, table, import/export).

    Built fresh per request from ``app.program_state``/``app.ips_config``
    — no module-level singleton, so this page's content actually differs
    from ``/monitor``'s (``test_pages.py``'s distinctness assertion).
    """
    if app.ips_config is None:
        return _no_ips_layout()

    ips_config = app.ips_config
    portfolio = app.program_state.portfolio
    default_style = ips_config.pricing.exercise_style.value

    book_zone = html.Div(
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
            html.H3("Add a position"),
            html.P(
                "Editing a position is remove + add, not in-place edit — "
                "there is no separate 'update' form.",
                className="plain-language",
            ),
            html.Div(
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
                    html.Button(
                        "Add position",
                        id="add-submit",
                        className="btn btn-primary",
                    ),
                ],
                className="editor-form",
            ),
            html.Div(id="mutation-status"),
            html.H3("Positions"),
            html.Div(
                _render_position_table_logic(portfolio=portfolio),
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
            dcc.Store(id="book-version", data=0),
            dcc.Store(id="import-pending-path", data=None),
        ],
        className="zone-book",
    )

    return html.Div(
        [html.H1("Design"), book_zone],
        className="page page-design",
    )


def register_callbacks(app: ProgramDashApp) -> None:
    """Wire the BOOK zone's six callbacks.

    A no-op when ``app.ips_config is None`` — mirrors ``render()``'s own
    page-level gate, so a gated page has nothing wired to a mutator
    either.
    """
    if app.ips_config is None:
        return

    @app.callback(
        Output("book-version", "data", allow_duplicate=True),
        Output("mutation-status", "children", allow_duplicate=True),
        Output("add-strike", "value"),
        Output("add-maturity", "date"),
        Output("add-quantity", "value"),
        Output("add-option-type", "value"),
        Output("add-exercise-style", "value"),
        Output("add-entry-premium", "value"),
        Input("add-submit", "n_clicks"),
        State("add-strike", "value"),
        State("add-maturity", "date"),
        State("add-quantity", "value"),
        State("add-option-type", "value"),
        State("add-exercise-style", "value"),
        State("add-entry-premium", "value"),
        State("book-version", "data"),
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
        version: int,
    ) -> tuple[Any, Component, Any, Any, Any, Any, Any, Any]:
        return _add_position_logic(
            strike=strike,
            maturity=maturity,
            quantity=quantity,
            option_type=option_type,
            exercise_style=exercise_style,
            entry_premium=entry_premium,
            version=version,
            state=app.program_state,
        )

    @app.callback(
        Output("book-version", "data", allow_duplicate=True),
        Output("mutation-status", "children", allow_duplicate=True),
        Input({"type": "remove-confirm", "index": ALL}, "submit_n_clicks"),
        State("book-version", "data"),
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
        Output("book-version", "data", allow_duplicate=True),
        Output("mutation-status", "children", allow_duplicate=True),
        Input("underlying-qty", "value"),
        State("book-version", "data"),
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
        Output("book-version", "data", allow_duplicate=True),
        Output("mutation-status", "children", allow_duplicate=True),
        Output("import-pending-path", "data"),
        Output("import-confirm-row", "hidden"),
        Input("import-submit", "n_clicks"),
        Input("import-confirm-submit", "n_clicks"),
        State("import-path", "value"),
        State("import-pending-path", "data"),
        State("book-version", "data"),
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
        Output("mutation-status", "children", allow_duplicate=True),
        Input("export-submit", "n_clicks"),
        prevent_initial_call=True,
    )
    def _export(_n_clicks: int) -> tuple[Any, Component]:
        return _export_logic(state=app.program_state)

    @app.callback(
        Output("position-table", "children"),
        Input("book-version", "data"),
    )
    def _render_position_table(_version: int) -> Component:
        return _render_position_table_logic(
            portfolio=app.program_state.portfolio,
        )
