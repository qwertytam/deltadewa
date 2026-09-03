"""PLANNING zone: the Delta Drift panel (Part X §13 Delta Drift).

Reprices at the handbook's own fixed -5% spot shock, not the IPS crash
anchor — a distinct basis from every other PLANNING panel, so it prices
``_BASIS_MINUS_5PCT`` rather than the zone's usual crash-skew chip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import Input, Output, html

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import safe_render as _safe_render

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.scenarios import DeltaDrift, DeltaDriftLeg
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.portfolio.core import OptionPortfolio

# Nor does the delta drift panel: it reprices at the handbook's own fixed
# -5% spot shock (Part X #13 --
# https://qwertytam.github.io/deltadewa-handbook/0.1/part-10/tier-4-tactical-optional-trading-metrics/#13-delta-drift),
# not the IPS crash anchor -- a distinct basis from every other PLANNING
# panel. Pinned to handbook version 0.1 because the -5% in the label below is
# the handbook's figure rather than a choice made here; drop the /0.1/ segment
# for the current page.
_BASIS_MINUS_5PCT = "basis: spot -5%, flat vol (not the IPS crash)"


def _delta_drift_leg_row(leg: DeltaDriftLeg) -> html.Tr:
    """One option leg's delta today, at -5%, and the drift between them."""
    label = (
        f"{leg.position.option.option_type.value} "
        f"{leg.position.option.strike_price:,.0f}"
    )
    return html.Tr(
        [
            html.Td(label),
            html.Td(f"{leg.delta_now:,.1f}"),
            html.Td(f"{leg.delta_shocked:,.1f}"),
            html.Td(f"{leg.drift:,.1f}"),
        ],
    )


def _delta_drift_panel_view(drift: DeltaDrift) -> Component:
    """Render Part X §13: hedge delta today vs. at the handbook's -5% shock.

    Sits beside the hedge triggers panel — same "does the book need
    rebalancing" question, asked a different way: not whether a threshold
    has been crossed, but how quickly the hedge itself would start
    offsetting losses in an early-stage decline.
    """
    header = html.Tr(
        [
            html.Th("Leg"),
            html.Th("Delta now"),
            html.Th(f"Delta at {drift.shock_pct:.0f}%"),
            html.Th("Drift"),
        ],
    )
    return html.Div(
        [
            html.P(
                "Hedge-only delta (options, no underlying) today vs. "
                f"spot {drift.shock_pct:.0f}% — the handbook's own "
                "worked example, not the IPS crash scenario. This "
                "answers how fast the hedge starts biting in an "
                'early-stage decline — it is not the "Delta ratio '
                'deviation" trigger in the Hedge triggers panel above, '
                "which instead measures how far net delta has wandered "
                "from the book's target hedge ratio at today's market, "
                "with no shock applied at all.",
                className="plain-language",
            ),
            html.P(
                f"Delta now {drift.delta_now:,.1f}, at "
                f"{drift.shock_pct:.0f}% {drift.delta_shocked:,.1f} — "
                f"drift {drift.drift:,.1f}.",
                className="env-verdict",
            ),
            html.Table(
                [
                    html.Thead(header),
                    html.Tbody(
                        [_delta_drift_leg_row(leg) for leg in drift.legs],
                    ),
                ],
                className="planning-table",
            ),
        ],
    )


def _render_delta_drift_panel_logic(
    *,
    portfolio: OptionPortfolio,
) -> Component:
    """Render the delta drift panel for the current book."""
    return _safe_render(
        lambda: _delta_drift_panel_view(
            PortfolioAnalyzer(portfolio).calculate_delta_drift(),
        ),
    )


def layout(*, portfolio: OptionPortfolio) -> html.Div:
    """Build the Delta Drift panel."""
    return html.Div(
        [
            html.H3(
                ["Delta drift", basis_chip(_BASIS_MINUS_5PCT)],
            ),
            html.Div(
                _render_delta_drift_panel_logic(portfolio=portfolio),
                id="plan-delta-drift-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp) -> None:
    """Wire the Delta Drift panel's re-render callback."""

    @app.callback(
        Output("plan-delta-drift-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_delta_drift_panel(_version: int) -> Component:
        return _render_delta_drift_panel_logic(
            portfolio=app.program_state.portfolio,
        )
