"""EXPLORATION zone: the Volatility Profile panel (#260).

Frames the panel as what it is -- the assumption every other
EXPLORATION grid is built on, not a standalone statistic. Every grid
scales each leg's volatility by the same factor (``proportional_vol``)
so the vega-weighted average reaches whatever level the axis asks for;
this panel shows that average and the skew (each leg's ratio to it)
being held constant while it moves — a structural read of today's
book, like the vega term exposure panel, not a stress scenario, so it
carries its own ``_BASIS_BOOK_VOLATILITY`` chip rather than the zone's
default proportional-vol basis.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, html

from deltadewa.analysis.volatility import build_volatility_profile
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import incomplete_notice as _incomplete
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec

from ..book import BOOK_VERSION_STORE
from ..dials import _EXPLORATION_EMPTY_BOOK_MSG

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.volatility import (
        PositionVolatilityDetail,
        VolatilityProfile,
    )
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.portfolio.core import OptionPortfolio

# Nor does the volatility profile panel: it reads each leg's own stored
# volatility and vega-weights them, but shocks nothing -- a structural
# read of today's book, like the vega term exposure panel, not a stress
# scenario.
_BASIS_BOOK_VOLATILITY = "basis: each leg's stored volatility (nothing shocked)"

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-volatility-profile",
    title="Volatility profile",
)


def _volatility_profile_row(
    detail: PositionVolatilityDetail,
) -> html.Tr:
    """One position's volatility and its ratio to the book's average."""
    label = f"{detail.option_type.value} {detail.strike_price:,.0f}"
    if detail.is_custom:
        label += " (custom)"
    return html.Tr(
        [
            html.Td(label),
            html.Td(f"{detail.volatility:.2%}"),
            html.Td(f"{detail.relative_to_avg * 100:.0f}% of avg"),
        ],
    )


def _volatility_profile_panel_view(
    profile: VolatilityProfile,
) -> Component:
    """Render #260: the book's volatility profile.

    Frames the panel as what it is -- the assumption every EXPLORATION
    grid below is built on, not a standalone statistic. Every grid scales
    each leg's volatility by the same factor (``proportional_vol``) so the
    vega-weighted average reaches whatever level the axis asks for; this
    panel shows that average and the skew (each leg's ratio to it) being
    held constant while it moves.
    """
    header = html.Tr(
        [html.Th("Leg"), html.Th("Volatility"), html.Th("vs. average")],
    )
    rows = [_volatility_profile_row(detail) for detail in profile.positions]
    return html.Div(
        [
            html.P(
                "Every EXPLORATION grid below scales each leg's "
                "volatility by the same factor so the vega-weighted "
                "average reaches the level on the axis -- this is the "
                "average, and the skew being held constant while it "
                "moves.",
                className="plain-language",
            ),
            html.P(
                f"Vega-weighted average {profile.avg_volatility:.2%}, "
                f"range {profile.min_volatility:.2%}-"
                f"{profile.max_volatility:.2%} "
                f"({profile.volatility_range:.2%} wide).",
                className="env-verdict",
            ),
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="planning-table",
            ),
        ],
    )


def _render_volatility_profile_panel_logic(
    *,
    portfolio: OptionPortfolio,
) -> Component:
    """Render the volatility profile panel for the current book."""
    if not portfolio.positions:
        return _incomplete(_EXPLORATION_EMPTY_BOOK_MSG)

    def _build() -> Component:
        profile = build_volatility_profile(portfolio)
        if profile is None:  # pragma: no cover - guarded above
            return _incomplete(_EXPLORATION_EMPTY_BOOK_MSG)
        return _volatility_profile_panel_view(profile)

    return _safe_render(_build)


def layout(*, portfolio: OptionPortfolio) -> html.Div:
    """Build the Volatility Profile panel."""
    return html.Div(
        [
            html.H3(
                [
                    SECTION.title,
                    basis_chip(_BASIS_BOOK_VOLATILITY),
                ],
                id=SECTION.anchor_id,
            ),
            html.Div(
                _render_volatility_profile_panel_logic(
                    portfolio=portfolio,
                ),
                id="explore-volatility-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp) -> None:
    """Wire the Volatility Profile panel's re-render callback."""

    @app.callback(
        Output("explore-volatility-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_volatility_profile_panel(_version: int) -> Component:
        return _render_volatility_profile_panel_logic(
            portfolio=app.program_state.portfolio,
        )
