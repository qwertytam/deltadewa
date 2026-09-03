"""EXPLORATION zone: the Vega Term Exposure panel (Part X §14).

Not a stress scenario — a read of today's book, so it carries the
``_BASIS_BOOK_GREEKS`` chip (like the PLANNING zone's hedge triggers
and position aging panels) rather than EXPLORATION's default
proportional-vol basis. ``basis_book_greeks`` is a parameter, not a
module constant, for that reason: three panels across two zones share
this basis chip text, so the string lives in ``page.py`` and is passed
down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import Input, Output, html

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.maturity import MaturityBuckets
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import safe_render as _safe_render

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.maturity import MaturityVegaExposure
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio


def _vega_term_panel_view(exposure: MaturityVegaExposure) -> Component:
    """Render Part X §14: vega bucketed by maturity, a structural view.

    Not a stress scenario — a read of today's book, so it carries the
    ``_BASIS_BOOK_GREEKS`` chip (like the PLANNING zone's hedge triggers
    panel) rather than EXPLORATION's default proportional-vol basis.
    """
    header = html.Tr([html.Th("Maturity bucket"), html.Th("Vega")])
    rows = [
        html.Tr([html.Td(bucket), html.Td(f"{vega:,.1f}")])
        for bucket, vega in exposure.vega_by_bucket.items()
    ]
    return html.Div(
        [
            html.P(
                "Where the book's volatility sensitivity sits across the "
                "term structure — a structural read, not a stress "
                "scenario. Institutional tail hedges typically prefer "
                "long-dated vega exposure.",
                className="plain-language",
            ),
            html.P(
                f"Total vega {exposure.total_vega:,.1f}.",
                className="env-verdict",
            ),
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="planning-table",
            ),
        ],
    )


def _render_vega_term_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the vega term exposure panel for the current book.

    Takes ``ips_config`` for the bucket edges (#305): where the term
    structure is cut is policy, not presentation, and this is the panel the
    old weekly-options edges rendered useless on an 18-month ladder.
    """
    buckets = MaturityBuckets.from_ips(ips_config.maturity_buckets)
    return _safe_render(
        lambda: _vega_term_panel_view(
            PortfolioAnalyzer(portfolio).calculate_vega_by_maturity(buckets),
        ),
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    basis_book_greeks: str,
) -> html.Div:
    """Build the Vega Term Exposure panel."""
    return html.Div(
        [
            html.H3(
                [
                    "Vega term exposure",
                    basis_chip(basis_book_greeks),
                ],
            ),
            html.Div(
                _render_vega_term_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                ),
                id="explore-vega-term-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Vega Term Exposure panel's re-render callback."""

    @app.callback(
        Output("explore-vega-term-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_vega_term_panel(_version: int) -> Component:
        return _render_vega_term_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )
