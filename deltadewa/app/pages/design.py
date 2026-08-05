"""The `/design` page: the operator's editor (BOOK) and planners (PLANNING).

BOOK: add/remove positions, the underlying quantity, and guarded
import/export. PLANNING: the four read-only planners — sizing, strike
ladder, roll, monetization — each a thin wrapper over its `analysis/`
function, all pricing the same IPS crash basis `/monitor`'s gauge uses
(the exploration zone's stress-grid surfaces, a different, proportional-
vol basis, land in a later milestone). Gates at the page level: without
``ips_config`` there is no source for the exercise-style default and no
policy to plan against, so the whole page becomes a single "no IPS policy
loaded" state, the same discipline ``monitor.py`` uses.

Every mutating callback routes through a module-level ``_..._logic``
function that is directly callable from tests (the ``@app.callback``-
decorated function is a thin wrapper reading Dash-specific context, e.g.
``dash.ctx``, and handing plain values to it). Failures are contained by
:func:`_guarded_mutation` — except :func:`_import_logic`, which needs to
tell a policy refusal apart from any other failure and so handles its
own try/except — so nothing here ever leaks a traceback to the browser,
and a failed mutation never bumps ``book-version``: the single
``dcc.Store`` every read-only panel in this page (BOOK's position table,
and every PLANNING panel) watches for "the book changed, re-read it."
PLANNING's own reads have no mutator to guard, so they use
:func:`_safe_render` instead — the same no-leaked-traceback discipline,
applied to an engine ``ValueError`` (a structurally missing input) rather
than a failed mutation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dash import ALL, Input, Output, State, ctx, dcc, html, no_update
from dash.development.base_component import Component

from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.analysis.monetization import build_monetization_plan
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.analysis.sizing import size_hedge
from deltadewa.analysis.strike_ladder import build_strike_ladder
from deltadewa.app import format as fmt
from deltadewa.app.bands import band_bar
from deltadewa.app.basis_chip import basis_chip
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.state import ConfirmationRequiredError

if TYPE_CHECKING:
    from collections.abc import Callable

    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.analysis.monetization import (
        MonetizationPlan,
        MonetizationStepStatus,
    )
    from deltadewa.analysis.roll_status import MoneynessDrift, RollStatusRecord
    from deltadewa.analysis.sizing import HedgeSizingResult
    from deltadewa.analysis.strike_ladder import (
        LadderRung,
        StrikeLadderResult,
        UnsolvableRung,
    )
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition
    from deltadewa.state import ProgramState

_logger = logging.getLogger(__name__)

_REQUIRED_ADD_FIELDS_MSG = "Strike, maturity, and quantity are required."

# PLANNING zone: dial defaults, matching hedge_design.ipynb's own notebook-
# cell literals — the same starting point the notebook's sizing/ladder
# cells used, now dial defaults instead of hardcoded cell values.
_DEFAULT_SIZING_PCT_OTM = 20.0
_DEFAULT_SIZING_MATURITY_YEARS = 0.5
_DEFAULT_LADDER_TARGET_DELTAS = "0.05, 0.10, 0.15"
_DEFAULT_LADDER_MATURITIES_YEARS = "0.25, 0.5, 1.0"

# Every PLANNING panel prices this basis — size_hedge, build_strike_ladder,
# and evaluate_roll_status each build CrashShock.from_ips(...) internally,
# the same construction /monitor's build_scenario uses at the IPS crash
# point. One literal, so the zone header and every panel's chip say the
# same thing.
_BASIS_CRASH_SKEW = "basis: crash-skew (IPS anchor)"


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


def _incomplete(message: str) -> html.P:
    """Build an "incomplete inputs" notice.

    Never render zeros for a missing or malformed dial — an unfinished
    input says so in words. Distinct from :func:`_status`: this isn't a
    failed action, there is no action to fail.
    """
    return html.P(message, className="plain-language")


def _safe_render(build: Callable[[], Component]) -> Component:
    """Render a PLANNING panel, turning a structural ``ValueError`` into text.

    Read-only counterpart to :func:`_guarded_mutation`. ``size_hedge`` and
    ``build_strike_ladder`` raise ``ValueError`` when the book has no
    underlying position rather than fabricating a zero result — this turns
    that into the panel's own "incomplete" message instead of a failed
    callback. Anything else (an unexpected engine failure) is logged and
    shown generically, the same no-leaked-traceback discipline the BOOK
    zone's mutators use.
    """
    try:
        return build()
    except ValueError as exc:
        return _incomplete(str(exc))
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception(
            "Unexpected error rendering a /design planning panel",
        )
        return _status(
            "Something went wrong — see the server log.",
            error=True,
        )


def _parse_float_list(raw: str | None) -> list[float] | None:
    """Parse a comma-separated list of floats.

    Returns ``None`` on a blank or malformed string — a dial-parsing
    failure, not an engine error, so it's handled before :func:`_safe_render`
    ever runs.
    """
    if raw is None or not raw.strip():
        return None
    try:
        values = [
            float(part.strip()) for part in raw.split(",") if part.strip()
        ]
    except ValueError:
        return None
    return values or None


def _sizing_panel_view(
    result: HedgeSizingResult,
    ips_config: IpsConfig,
) -> Component:
    """Render one sized candidate: the rationale first, then the answer."""
    conv = ips_config.convexity
    carry_verdict = "within" if result.within_budget else "over"
    convexity_verdict = "within" if result.meets_convexity_target else "over"
    intrinsic_floor_text = fmt.currency(
        result.per_contract_intrinsic_floor,
        decimals=2,
    )
    return html.Div(
        [
            html.H4("Rationale"),
            html.P(
                f"Book notional {fmt.currency(result.book_notional)} x "
                f"beta {result.portfolio_beta:.2f} = beta-adjusted "
                f"notional {fmt.currency(result.beta_adjusted_notional)}. "
                "The hedge must recover "
                f"{fmt.currency(result.required_crash_offset)} beyond the "
                "drawdown tolerance at the IPS crash.",
                className="plain-language",
            ),
            html.H4("Candidate economics"),
            html.P(
                f"{result.candidate_pct_otm:.1f}% OTM, "
                f"{result.candidate_maturity_years:.2f}y to expiry — "
                "crash payoff "
                f"{fmt.currency(result.per_contract_payoff, decimals=2)}"
                f"/contract (intrinsic floor {intrinsic_floor_text}), "
                f"carry {fmt.currency(result.per_contract_carry, decimals=2)}"
                "/contract/year.",
                className="plain-language",
            ),
            html.H4("Sizing"),
            html.P(
                f"{result.contracts_needed:,} contracts needed — implied "
                f"annual carry {fmt.currency(result.implied_annual_carry)} "
                f"vs {fmt.currency(result.carry_budget)} budget "
                f"({carry_verdict} budget, headroom "
                f"{fmt.signed_currency(result.carry_headroom)}; max "
                f"affordable {result.max_affordable_contracts:,} contracts).",
            ),
            band_bar(
                value=result.implied_annual_carry,
                low=0.0,
                high=result.carry_budget,
            ),
            html.P(
                "Achieved convexity "
                f"{fmt.percent(result.achieved_convexity_pct)} vs "
                f"{fmt.percent(conv.target_min_pct)}-"
                f"{fmt.percent(conv.target_max_pct)} target "
                f"({convexity_verdict} target).",
            ),
            band_bar(
                value=result.achieved_convexity_pct,
                low=conv.target_min_pct,
                high=conv.target_max_pct,
            ),
        ],
    )


def _render_sizing_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    pct_otm: float | None,
    maturity_years: float | None,
    vol_override: float | None,
) -> Component:
    """Render the sizing panel for one candidate put."""
    if pct_otm is None or maturity_years is None:
        return _incomplete(
            "Enter a strike (% OTM) and a maturity (years) to size a "
            "candidate hedge.",
        )

    def _build() -> Component:
        result = size_hedge(
            portfolio,
            ips_config,
            candidate_pct_otm=pct_otm,
            candidate_maturity_years=maturity_years,
            vol=vol_override,
        )
        return _sizing_panel_view(result, ips_config)

    return _safe_render(_build)


def _unsolvable_rung_line(rung: UnsolvableRung) -> html.P:
    """One unsolvable ladder cell, surfaced explicitly (Mi5 — never dropped)."""
    return html.P(
        f"{rung.target_delta:.2f}Δ @ {rung.maturity_years:.2f}y — "
        f"{rung.reason}",
        className="unsolvable-note",
    )


def _ladder_rung_row(rung: LadderRung) -> html.Tr:
    """One solved ladder rung."""
    verdict = "within" if rung.meets_target_within_budget else "over"
    return html.Tr(
        [
            html.Td(f"{rung.target_delta:.2f}Δ"),
            html.Td(f"{rung.maturity_years:.2f}y"),
            html.Td(f"{rung.metrics.strike:,.0f}"),
            html.Td(f"{rung.metrics.pct_otm:.1f}%"),
            html.Td(f"{rung.metrics.put_delta:.3f}"),
            html.Td(fmt.currency(rung.metrics.premium, decimals=2)),
            html.Td(
                fmt.currency(rung.metrics.per_contract_payoff, decimals=2),
            ),
            html.Td(f"{rung.contracts_needed:,}"),
            html.Td(fmt.percent(rung.achieved_convexity_pct)),
            html.Td(verdict),
        ],
    )


def _ladder_panel_view(result: StrikeLadderResult) -> Component:
    """Render the solved rungs table, then the unsolvable cells (Mi5)."""
    if not result.rungs and not result.unsolvable:
        return _incomplete("No rungs requested.")

    children: list[Component] = []
    if result.rungs:
        header = html.Tr(
            [
                html.Th("Delta"),
                html.Th("Maturity"),
                html.Th("Strike"),
                html.Th("%OTM"),
                html.Th("Put delta"),
                html.Th("Premium"),
                html.Th("Crash payoff"),
                html.Th("Contracts"),
                html.Th("Achieved convexity"),
                html.Th("Budget"),
            ],
        )
        rows = [_ladder_rung_row(rung) for rung in result.rungs]
        children.append(
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="planning-table",
            ),
        )
    if result.unsolvable:
        children.append(html.H4("Unsolvable"))
        children.extend(
            _unsolvable_rung_line(rung) for rung in result.unsolvable
        )
    return html.Div(children)


def _render_ladder_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    target_deltas_raw: str | None,
    maturities_years_raw: str | None,
) -> Component:
    """Render the strike ladder for comma-separated deltas/maturities."""
    target_deltas = _parse_float_list(target_deltas_raw)
    maturities_years = _parse_float_list(maturities_years_raw)
    if target_deltas is None or maturities_years is None:
        return _incomplete(
            "Enter comma-separated deltas and maturities, e.g. "
            "0.05, 0.10, 0.15 and 0.25, 0.5, 1.0.",
        )

    def _build() -> Component:
        result = build_strike_ladder(
            portfolio,
            ips_config,
            target_deltas=target_deltas,
            maturities_years=maturities_years,
        )
        return _ladder_panel_view(result)

    return _safe_render(_build)


def _otm_pair_text(moneyness: MoneynessDrift) -> str:
    """Format "entry OTM% / current OTM%", entry as "n/a" when unrecorded."""
    entry = (
        fmt.signed_percent(moneyness.entry_otm_pct)
        if moneyness.entry_otm_pct is not None
        else "n/a"
    )
    return f"{entry} / {fmt.signed_percent(moneyness.current_otm_pct)}"


def _roll_record_row(record: RollStatusRecord) -> html.Tr:
    """One position's roll status, with all three trigger reasons (G3)."""
    position = record.position
    suppressed_note = (
        " (strike-drift roll suppressed — convexity in-band, no time pressure)"
        if record.suppressed
        else ""
    )
    cost_text = (
        fmt.currency(record.estimated_roll_up_cost, decimals=2)
        if record.estimated_roll_up_cost is not None
        else "n/a"
    )
    return html.Tr(
        [
            html.Td(
                html.Span(
                    record.verdict.value,
                    className=(
                        "verdict-badge verdict-badge--"
                        f"{record.verdict.value.lower()}"
                    ),
                ),
            ),
            html.Td(
                f"{position.option.option_type.value} "
                f"{position.option.strike_price:,.0f}",
            ),
            html.Td(_otm_pair_text(record.moneyness)),
            html.Td(f"{record.days_to_maturity}d / {record.roll_window_days}d"),
            html.Td(cost_text),
            html.Td(
                f"Time: {record.time_trigger.verdict.value} — "
                f"{record.time_trigger.reason}"
            ),
            html.Td(
                f"Convexity: {record.convexity_trigger.verdict.value} — "
                f"{record.convexity_trigger.reason}",
            ),
            html.Td(
                f"Drift: {record.drift_trigger.verdict.value} — "
                f"{record.drift_trigger.reason}{suppressed_note}",
            ),
        ],
    )


def _roll_panel_view(records: list[RollStatusRecord]) -> Component:
    """Render the per-position roll table."""
    if not records:
        return html.P(
            "No positions in the book yet.",
            className="plain-language",
        )

    header = html.Tr(
        [
            html.Th("Verdict"),
            html.Th("Position"),
            html.Th("OTM entry / now"),
            html.Th("DTE / window"),
            html.Th("Est. roll-up cost"),
            html.Th("Time trigger"),
            html.Th("Convexity trigger"),
            html.Th("Drift trigger"),
        ],
    )
    rows = [_roll_record_row(record) for record in records]
    return html.Table(
        [html.Thead(header), html.Tbody(rows)],
        className="planning-table",
    )


def _render_roll_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the roll planner for every position in the book."""
    return _safe_render(
        lambda: _roll_panel_view(evaluate_roll_status(portfolio, ips_config)),
    )


def _monetization_step_row(step: MonetizationStepStatus) -> html.Tr:
    """One row of the IPS monetization schedule."""
    return html.Tr(
        [
            html.Td(fmt.percent(step.gain_pct)),
            html.Td(fmt.percent(step.sell_pct)),
            html.Td("triggered" if step.triggered else "not yet"),
        ],
    )


def _monetization_panel_view(plan: MonetizationPlan) -> Component:
    """Render the full IPS monetization schedule at the current mark.

    Unlike /monitor's one-sentence summary, shows every schedule step —
    now meaningful for a hand-entered book once B0 gave entry_premium a
    write path.
    """
    children: list[Component]
    if plan.gain_basis == "unknown":
        children = [
            html.P(
                "No entry price is recorded for the protective puts, so "
                "hedge gain — and this monetization schedule — can't be "
                "evaluated.",
                className="plain-language",
            ),
        ]
    else:
        gain_text = (
            fmt.percent(plan.current_gain_pct)
            if plan.current_gain_pct is not None
            else "n/a"
        )
        header = html.Tr(
            [html.Th("Gain trigger"), html.Th("Sell %"), html.Th("Status")],
        )
        rows = [_monetization_step_row(step) for step in plan.steps]
        children = [
            html.P(
                f"Current hedge gain: {gain_text}.",
                className="plain-language",
            ),
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="planning-table",
            ),
            html.P(
                "Recommended cumulative sell: "
                f"{fmt.percent(plan.recommended_cumulative_sell_pct)} "
                f"({fmt.compact_currency(plan.value_to_harvest)} to "
                "harvest) — "
                f"{fmt.percent(plan.remaining_sell_capacity)} remaining "
                "sell capacity in the schedule.",
            ),
        ]
    if plan.vol_spike_context is not None:
        children.append(
            html.P(plan.vol_spike_context, className="vol-spike-context"),
        )
    return html.Div(children)


def _render_monetization_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    market_env: MarketEnvironment | None,
) -> Component:
    """Render the monetization panel at the current mark."""
    return _safe_render(
        lambda: _monetization_panel_view(
            build_monetization_plan(
                portfolio,
                ips_config,
                market_env=market_env,
            ),
        ),
    )


def render(app: ProgramDashApp) -> html.Div:
    """Build the /design page: the BOOK zone and the PLANNING zone.

    BOOK is the editor (add/remove, import/export); PLANNING is the four
    read-only planners (sizing, strike ladder, roll, monetization), all
    priced on the same IPS crash basis ``/monitor``'s gauge uses. Built
    fresh per request from ``app.program_state``/``app.ips_config`` — no
    module-level singleton, so this page's content actually differs from
    ``/monitor``'s (``test_pages.py``'s distinctness assertion).
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

    planning_zone = html.Div(
        [
            html.H2(["Planning", basis_chip(_BASIS_CRASH_SKEW)]),
            html.P(
                "Every panel below prices the IPS crash — the same basis "
                "/monitor's gauge uses. These agree with /monitor to the "
                "cent.",
                className="plain-language",
            ),
            html.Div(
                [
                    html.H3(
                        ["Sizing workbench", basis_chip(_BASIS_CRASH_SKEW)]
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Strike (% OTM)"),
                                    dcc.Input(
                                        id="sizing-pct-otm",
                                        type="number",
                                        value=_DEFAULT_SIZING_PCT_OTM,
                                        debounce=True,
                                    ),
                                ],
                                className="editor-field",
                            ),
                            html.Div(
                                [
                                    html.Label("Maturity (years)"),
                                    dcc.Input(
                                        id="sizing-maturity-years",
                                        type="number",
                                        value=_DEFAULT_SIZING_MATURITY_YEARS,
                                        debounce=True,
                                    ),
                                ],
                                className="editor-field",
                            ),
                            html.Div(
                                [
                                    html.Label("Vol override (optional)"),
                                    dcc.Input(
                                        id="sizing-vol-override",
                                        type="number",
                                        debounce=True,
                                    ),
                                ],
                                className="editor-field",
                            ),
                        ],
                        className="editor-form",
                    ),
                    html.Div(
                        _render_sizing_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                            pct_otm=_DEFAULT_SIZING_PCT_OTM,
                            maturity_years=_DEFAULT_SIZING_MATURITY_YEARS,
                            vol_override=None,
                        ),
                        id="plan-sizing-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(["Strike ladder", basis_chip(_BASIS_CRASH_SKEW)]),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Target deltas"),
                                    dcc.Input(
                                        id="ladder-target-deltas",
                                        type="text",
                                        value=_DEFAULT_LADDER_TARGET_DELTAS,
                                        debounce=True,
                                    ),
                                ],
                                className="editor-field",
                            ),
                            html.Div(
                                [
                                    html.Label("Maturities (years)"),
                                    dcc.Input(
                                        id="ladder-maturities-years",
                                        type="text",
                                        value=_DEFAULT_LADDER_MATURITIES_YEARS,
                                        debounce=True,
                                    ),
                                ],
                                className="editor-field",
                            ),
                        ],
                        className="editor-form",
                    ),
                    html.Div(
                        _render_ladder_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                            target_deltas_raw=_DEFAULT_LADDER_TARGET_DELTAS,
                            maturities_years_raw=(
                                _DEFAULT_LADDER_MATURITIES_YEARS
                            ),
                        ),
                        id="plan-ladder-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(["Roll planner", basis_chip(_BASIS_CRASH_SKEW)]),
                    html.Div(
                        _render_roll_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                        ),
                        id="plan-roll-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(["Monetization", basis_chip(_BASIS_CRASH_SKEW)]),
                    html.Div(
                        _render_monetization_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                            market_env=assess_market_environment(
                                app.market_data,
                                ips_config.market_environment,
                            ),
                        ),
                        id="plan-monetization-panel",
                    ),
                ],
                className="panel",
            ),
        ],
        className="zone-planning",
    )

    return html.Div(
        [html.H1("Design"), book_zone, planning_zone],
        className="page page-design",
    )


def register_callbacks(app: ProgramDashApp) -> None:
    """Wire the BOOK zone's six mutating callbacks and PLANNING's four reads.

    A no-op when ``app.ips_config is None`` — mirrors ``render()``'s own
    page-level gate, so a gated page has nothing wired to a mutator
    either.
    """
    if app.ips_config is None:
        return
    # Captured once into a local rather than re-read from app.ips_config
    # inside each nested callback below: mypy narrows a local variable's
    # None-ness across a closure, but not a property re-accessed later
    # (the same reason monitor.py's register_callbacks does this).
    ips_config = app.ips_config

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

    @app.callback(
        Output("plan-sizing-panel", "children"),
        Input("book-version", "data"),
        Input("sizing-pct-otm", "value"),
        Input("sizing-maturity-years", "value"),
        Input("sizing-vol-override", "value"),
    )
    def _render_sizing_panel(
        _version: int,
        pct_otm: float | None,
        maturity_years: float | None,
        vol_override: float | None,
    ) -> Component:
        return _render_sizing_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            pct_otm=pct_otm,
            maturity_years=maturity_years,
            vol_override=vol_override,
        )

    @app.callback(
        Output("plan-ladder-panel", "children"),
        Input("book-version", "data"),
        Input("ladder-target-deltas", "value"),
        Input("ladder-maturities-years", "value"),
    )
    def _render_ladder_panel(
        _version: int,
        target_deltas_raw: str | None,
        maturities_years_raw: str | None,
    ) -> Component:
        return _render_ladder_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            target_deltas_raw=target_deltas_raw,
            maturities_years_raw=maturities_years_raw,
        )

    @app.callback(
        Output("plan-roll-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_roll_panel(_version: int) -> Component:
        return _render_roll_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    @app.callback(
        Output("plan-monetization-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_monetization_panel(_version: int) -> Component:
        return _render_monetization_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            market_env=assess_market_environment(
                app.market_data,
                ips_config.market_environment,
            ),
        )
