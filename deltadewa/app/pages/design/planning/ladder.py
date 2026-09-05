"""PLANNING zone: the Strike Ladder panel.

``basis_crash_skew`` is a parameter, not a module constant: every
PLANNING panel that prices the IPS crash shares this basis chip text,
so the string lives in ``page.py`` and is passed down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, dcc, html

from deltadewa.analysis.strike_ladder import build_strike_ladder
from deltadewa.app import format as fmt
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import NoticeKind, panel_notice
from deltadewa.app.panel_guard import incomplete_notice as _incomplete
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.strike_ladder import (
        LadderRung,
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


def _ladder_panel_view(result: StrikeLadderResult) -> Component:
    """Render the solved rungs table, then the unsolvable cells.

    Unsolvable rungs are shown, never dropped — see
    :func:`_unsolvable_rung_line` for the finding-ID note. #326's third
    mode: when nothing at all solved, that is its own dead end (the
    engine ran and answered "nothing"), rendered as a
    :attr:`NoticeKind.EMPTY` notice rather than as a bare "Unsolvable"
    heading — the same table-less shape #326 reported as
    indistinguishable from a panel that had not built yet.
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
    children: list[Component] = [
        html.Table(
            [html.Thead(header), html.Tbody(rows)],
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
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Strike Ladder panel's re-render callback."""

    @app.callback(
        Output("plan-ladder-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
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
