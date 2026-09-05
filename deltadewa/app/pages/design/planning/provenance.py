"""PLANNING zone: the Pricing Input Provenance panel (Batch 3d, #367/#368).

The one cross-module id straddler #308's plan called out: the "mark
inputs reviewed" control sits in this panel's markup, but it is a BOOK
mutation — its callback writes ``book.BOOK_VERSION_STORE`` and
``book.MUTATION_STATUS``, the same two ids every BOOK edit writes. The
import from ``..book`` below is what makes that coupling a real,
grep-able Python dependency instead of two id strings that happen to
match.

``_mark_inputs_reviewed_logic`` itself is a BOOK mutator and stays
defined in ``book.py`` alongside the rest of them (add/remove/import/
export) — only the callback that wires it moves here, because the
control it responds to is this panel's, not BOOK's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from dash import Input, Output, State, dcc, html, no_update

from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.analysis.provenance import build_provenance_ledger
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.provenance_panel import build_provenance_panel
from deltadewa.app.section_nav import SectionSpec
from deltadewa.clock import program_trading_date

from ..book import (
    BOOK_VERSION_STORE,
    MUTATION_STATUS,
    _mark_inputs_reviewed_logic,
)

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-provenance",
    title="Pricing input provenance",
)


def _render_provenance_panel_logic(
    *,
    app: ProgramDashApp,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the pricing-input provenance panel (Batch 3d, #367/#368).

    Reassesses market data fresh in this closure rather than sharing
    ``render()``'s own ``market_env`` — ``assess_market_environment``
    never raises, so sharing would be safe, but a fresh call here keeps
    this panel's isolation independent of whatever ``render()`` happens
    to compute elsewhere, matching monitor.py's convention for this
    specific panel.
    """

    def _build() -> Component:
        environment = assess_market_environment(
            app.market_data,
            ips_config.market_environment,
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            ips_config.pricing_inputs,
            as_of=program_trading_date(ips_config.program.timezone).date(),
        )
        return build_provenance_panel(ledger)

    return _safe_render(_build)


def layout(
    *,
    app: ProgramDashApp,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> html.Div:
    """Build the Pricing Input Provenance panel."""
    return html.Div(
        [
            # No basis chip: unlike every other PLANNING panel, this one
            # grades staleness, not a priced quantity — there is no
            # crash-skew or book-greeks basis for it to name (Batch 3d,
            # #367/#368).
            html.H3(SECTION.title, id=SECTION.anchor_id),
            html.Div(
                _render_provenance_panel_logic(
                    app=app,
                    portfolio=portfolio,
                    ips_config=ips_config,
                ),
                id="plan-provenance-panel",
            ),
            dcc.ConfirmDialogProvider(
                id="mark-inputs-reviewed-confirm",
                message=(
                    "Mark every hand-entered pricing input "
                    "(spot, risk-free rate, dividend yield, and "
                    "every leg's volatility) as confirmed "
                    "current, as of now? This clears any "
                    "existing staleness signal — it does not "
                    "change any value, only its confirmed date."
                ),
                children=html.Button(
                    "Mark pricing inputs reviewed",
                    className="btn btn-secondary",
                ),
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Pricing Input Provenance panel's callbacks.

    Two callbacks, not one: the re-render (watches ``book-version``,
    like every read-only panel) and the "mark inputs reviewed" mutation
    this panel's control drives — see the module docstring for why that
    mutation's callback lives here rather than in ``book.py``.
    """

    @app.callback(
        Output("plan-provenance-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_provenance_panel(_version: int) -> Component:
        return _render_provenance_panel_logic(
            app=app,
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    @app.callback(
        Output(BOOK_VERSION_STORE, "data", allow_duplicate=True),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Input("mark-inputs-reviewed-confirm", "submit_n_clicks"),
        State(BOOK_VERSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def _mark_inputs_reviewed(
        submit_n_clicks: int | None,
        version: int,
    ) -> tuple[Any, Any]:
        if not submit_n_clicks:
            return no_update, no_update
        return _mark_inputs_reviewed_logic(
            version=version,
            state=app.program_state,
        )
