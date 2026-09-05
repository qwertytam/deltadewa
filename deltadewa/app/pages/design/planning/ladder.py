"""PLANNING zone: the Strike Ladder panel.

``basis_crash_skew`` is a parameter, not a module constant: every
PLANNING panel that prices the IPS crash shares this basis chip text,
so the string lives in ``page.py`` and is passed down.

#358: the results table's columns are click-to-sort. Decided in #390's
triage (recorded there, not re-litigated here): a small server-side sort
over the domain objects, not a ``dash_table.DataTable`` migration — a
DataTable sorts what it *renders* (``"$1,000" < "$900"`` lexicographically),
and this panel's cells (the ``verdict-badge``-style budget column, the
row-level ``Unsolvable`` breakout) aren't data DataTable can hold anyway.
:func:`_sort_rungs` sorts the underlying ``LadderRung``/``CandidateMetrics``
values instead. Sort state lives in its own ``dcc.Store``
(:data:`_SORT_STORE_ID`) rather than as a dial, since it isn't a pricing
input — clicking a header must not reprice anything, only reorder rows
already computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, TypedDict

from dash import ALL, Input, NoUpdate, Output, State, ctx, dcc, html, no_update

from deltadewa.analysis.strike_ladder import build_strike_ladder
from deltadewa.app import format as fmt
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import NoticeKind, panel_notice
from deltadewa.app.panel_guard import incomplete_notice as _incomplete
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from collections.abc import Callable

    from dash.development.base_component import Component

    from deltadewa.analysis.strike_ladder import (
        LadderRung,
        StrikeLadder,
        StrikeLadderResult,
        UnsolvableRung,
    )
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig, IpsMaturitySelection
    from deltadewa.portfolio.core import OptionPortfolio

# PLANNING zone: dial default. Carried over from the ladder cell of
# hedge_design.ipynb, which Stage 4.3 deleted — the starting point that
# notebook hardcoded, kept here as an adjustable dial default. Genuinely
# presentation, not policy: no IPS strike-selection section exists to read
# it from, and inventing one is its own decision, not #316's.
_DEFAULT_LADDER_TARGET_DELTAS = "0.05, 0.10, 0.15"

# #326: safe_render's BLOCKED remediation pointer for this panel, which
# raises ValueError on a book with no underlying position
# (build_strike_ladder). Presentation, on the page that knows where the
# fix lives -- not baked into the analysis-layer exception text.
_LADDER_BLOCKED_HINT = (
    "Set the underlying spot and quantity in the BOOK zone; the ladder "
    "sizes every rung against them."
)

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-strike-ladder",
    title="Strike ladder",
)

# #358: the sort-state Store's id, and the pattern-matching type every
# sortable header button shares (the ALL + ctx.triggered_id idiom
# book.py's remove-confirm buttons already use).
_SORT_STORE_ID: Final[str] = "ladder-sort-state"
_SORT_HEADER_TYPE: Final[str] = "ladder-sort-header"


class _SortState(TypedDict):
    """The table's current sort — a column key and a direction.

    Lives in a ``dcc.Store`` as a plain JSON-serializable dict rather
    than a dataclass; the only two producers are :func:`_toggle_sort_state`
    (a real column key, "asc" or "desc") and the Store's own ``data=None``
    default (unsorted), so nothing downstream needs to validate it further.
    """

    column: str
    direction: str


@dataclass(frozen=True, slots=True)
class _Column:
    """One sortable column: its header label and how to read its value.

    ``sort_key`` always returns ``float`` — ``contracts_needed`` (int) and
    ``meets_target_within_budget`` (bool) are cast up rather than sorted
    as a mixed ``float | int | bool``, so every column's comparator is the
    same type and there's exactly one numeric ordering to reason about.
    """

    key: str
    label: str
    sort_key: Callable[[LadderRung], float]


# Order here is the table's column order — also what a sort_state=None
# (unsorted) header row renders left to right.
_COLUMNS: Final[tuple[_Column, ...]] = (
    _Column("delta", "Delta", lambda rung: rung.target_delta),
    _Column("maturity", "Maturity", lambda rung: rung.maturity_years),
    _Column("strike", "Strike", lambda rung: rung.metrics.strike),
    _Column("pct_otm", "%OTM", lambda rung: rung.metrics.pct_otm),
    _Column("put_delta", "Put delta", lambda rung: rung.metrics.put_delta),
    _Column("premium", "Premium", lambda rung: rung.metrics.premium),
    _Column(
        "crash_payoff",
        "Crash payoff",
        lambda rung: rung.metrics.per_contract_payoff,
    ),
    _Column(
        "contracts",
        "Contracts",
        lambda rung: float(rung.contracts_needed),
    ),
    _Column(
        "achieved_convexity",
        "Achieved convexity",
        lambda rung: rung.achieved_convexity_pct,
    ),
    _Column(
        "budget",
        "Budget",
        lambda rung: float(rung.meets_target_within_budget),
    ),
)
_COLUMNS_BY_KEY: Final[dict[str, _Column]] = {
    column.key: column for column in _COLUMNS
}


def _sort_rungs(
    rungs: StrikeLadder,
    sort_state: _SortState | None,
) -> StrikeLadder:
    """Sort solved rungs by *sort_state*'s column, or leave them as-is.

    Sorts the underlying ``LadderRung``/``CandidateMetrics`` values, never
    the rendered strings (see the module docstring). ``sorted`` is stable,
    so rows tied on the sort column keep their original delta-major
    relative order rather than reshuffling on every re-render.
    """
    if sort_state is None:
        return rungs
    column = _COLUMNS_BY_KEY.get(sort_state["column"])
    if column is None:
        # Defensive only: the Store only ever holds a value
        # _toggle_sort_state produced, which is always a real column key.
        # Degrades to unsorted rather than raising mid-render if that
        # ever stops being true (e.g. a column is renamed later).
        return rungs
    return sorted(
        rungs,
        key=column.sort_key,
        reverse=sort_state["direction"] == "desc",
    )


def _toggle_sort_state(
    current: _SortState | None,
    clicked_column: str,
) -> _SortState:
    """Compute the next sort state after a header click.

    A new column sorts ascending; clicking the *same* column again flips
    the direction. There's no third "unsorted" state once a column has
    been clicked — the Store resets to ``None`` (natural, delta-major
    order) on the next full page load anyway, since it's an in-memory
    Store, not a persisted one.
    """
    if current is not None and current["column"] == clicked_column:
        direction = "desc" if current["direction"] == "asc" else "asc"
    else:
        direction = "asc"
    return {"column": clicked_column, "direction": direction}


def _sort_indicator(column: _Column, sort_state: _SortState | None) -> str:
    """Return " ▲"/" ▼" for the active sort column, else nothing."""
    if sort_state is None or sort_state["column"] != column.key:
        return ""
    return " ▲" if sort_state["direction"] == "asc" else " ▼"


def _sort_header_row(sort_state: _SortState | None) -> html.Tr:
    """Build the header row: every column a clickable sort button."""
    return html.Tr(
        [
            html.Th(
                html.Button(
                    f"{column.label}{_sort_indicator(column, sort_state)}",
                    id={"type": _SORT_HEADER_TYPE, "column": column.key},
                    className="sort-header",
                    n_clicks=0,
                ),
            )
            for column in _COLUMNS
        ],
    )


def _ladder_maturities_text(selection: IpsMaturitySelection) -> str:
    """Format the ladder dial's initial text from IPS policy (#316).

    ``ladder_maturities_years`` is already derived from the three
    ``maturity_selection`` fields, so this is only the text-rendering
    step of that -- not a fourth place the tenor could drift from them.
    """
    return ", ".join(str(years) for years in selection.ladder_maturities_years)


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


def _unsolvable_rung_line(rung: UnsolvableRung) -> html.P:
    """One unsolvable ladder cell, surfaced explicitly — never dropped.

    Not the ``Mi5`` finding (that's the unrelated ``include_underlying``
    scalar/vectorized P&L default, already closed in M1.3/M1.4) — this
    is M1.4's strike-ladder bullet's third clause, which was never given
    its own finding number in ``docs/implementation-plan.md``.
    """
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


def _ladder_panel_view(
    result: StrikeLadderResult,
    sort_state: _SortState | None,
) -> Component:
    """Render the solved rungs table, then the unsolvable cells.

    Unsolvable rungs are shown, never dropped — see
    :func:`_unsolvable_rung_line` for the finding-ID note. #326's third
    mode: when nothing at all solved, that is its own dead end (the
    engine ran and answered "nothing"), rendered as a
    :attr:`NoticeKind.EMPTY` notice rather than as a bare "Unsolvable"
    heading — the same table-less shape #326 reported as
    indistinguishable from a panel that had not built yet. *sort_state*
    (#358) reorders only the solved rungs — the unsolvable list below the
    table is always shown in the engine's own delta-major order, since
    there's no column value to sort those rows by.
    """
    if not result.rungs and not result.unsolvable:
        # Unreachable by construction: _render_ladder_panel_logic only
        # calls build_strike_ladder with two non-empty sequences (a
        # None list already short-circuits to the INPUT notice above
        # it), and itertools.product of two non-empty sequences always
        # yields at least one cell, which lands in rungs or unsolvable.
        # Kept as a real INPUT notice rather than deleted, in case that
        # invariant ever changes.
        return _incomplete("No rungs requested.")

    if not result.rungs:
        return panel_notice(
            "No rung solves at these inputs.",
            kind=NoticeKind.EMPTY,
            body=[_unsolvable_rung_line(rung) for rung in result.unsolvable],
        )

    rows = [
        _ladder_rung_row(rung) for rung in _sort_rungs(result.rungs, sort_state)
    ]
    children: list[Component] = [
        html.Table(
            [
                html.Thead(_sort_header_row(sort_state)),
                html.Tbody(rows),
            ],
            className="planning-table",
        ),
    ]
    if result.unsolvable:
        # A partial answer, not an empty one -- the table above already
        # says the panel worked, so this stays plain markup rather than
        # a second notice.
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
    sort_state: _SortState | None = None,
) -> Component:
    """Render the strike ladder for comma-separated deltas/maturities.

    ``sort_state`` (#358) only reorders the already-solved rungs; it
    plays no part in the solve itself and every existing caller (every
    test predating #358, and the initial ``layout()`` render) omits it
    and gets the engine's own delta-major order, unchanged.
    """
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
        return _ladder_panel_view(result, sort_state)

    return _safe_render(_build, blocked_hint=_LADDER_BLOCKED_HINT)


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    basis_crash_skew: str,
) -> html.Div:
    """Build the Strike Ladder panel.

    #316: the maturities dial's initial value comes from policy (the
    maintain range), not a hardcoded 0.5y.
    """
    ladder_maturities_default = _ladder_maturities_text(
        ips_config.maturity_selection,
    )
    return html.Div(
        [
            html.H3(
                [SECTION.title, basis_chip(basis_crash_skew)],
                id=SECTION.anchor_id,
            ),
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
                                value=ladder_maturities_default,
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
                    maturities_years_raw=ladder_maturities_default,
                ),
                id="plan-ladder-panel",
            ),
            # #358: unsorted (natural, delta-major order) at page load —
            # a plain in-memory Store, so it resets on a full page load
            # rather than persisting a sort across sessions.
            dcc.Store(id=_SORT_STORE_ID, data=None),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Strike Ladder panel's re-render and header-sort callbacks."""

    @app.callback(
        Output("plan-ladder-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
        Input("ladder-target-deltas", "value"),
        Input("ladder-maturities-years", "value"),
        Input(_SORT_STORE_ID, "data"),
    )
    def _render_ladder_panel(
        _version: int,
        target_deltas_raw: str | None,
        maturities_years_raw: str | None,
        sort_state: _SortState | None,
    ) -> Component:
        return _render_ladder_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            target_deltas_raw=target_deltas_raw,
            maturities_years_raw=maturities_years_raw,
            sort_state=sort_state,
        )

    @app.callback(
        Output(_SORT_STORE_ID, "data"),
        Input({"type": _SORT_HEADER_TYPE, "column": ALL}, "n_clicks"),
        State(_SORT_STORE_ID, "data"),
        prevent_initial_call=True,
    )
    def _handle_sort_click(
        _all_n_clicks: list[int | None],
        current_state: _SortState | None,
    ) -> _SortState | NoUpdate:
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            # Defensive only -- prevent_initial_call=True already keeps
            # this from firing without a real trigger.
            return no_update
        # A pattern-matching ALL input fires once, with n_clicks still 0,
        # the moment a *new* matching header button first appears in the
        # DOM (e.g. this panel's first solve) -- not just on an actual
        # click. The same guard book.py's remove-confirm callback uses
        # (see its docstring): ctx.triggered[0]["value"] is the real
        # click count, so a falsy value here means "just appeared," not
        # "clicked."
        if not ctx.triggered[0]["value"]:
            return no_update
        return _toggle_sort_state(current_state, triggered["column"])
