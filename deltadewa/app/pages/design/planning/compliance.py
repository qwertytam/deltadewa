"""PLANNING zone: the IPS compliance strip (#298), now also on /design.

``/monitor``'s compliance strip has always been the program's one-line
PASS/FAIL headline (#298); ``/design`` never carried it, which read as
an oversight rather than a decision once field-tested against the live
book — nothing in the docs or the strip's own history documented leaving
it off this page deliberately. Batch 8a.4 adds it here, reusing
``app.compliance`` end to end (both the section computation and the
rendered strip itself) rather than writing a second grader — the same
#298/#409 discipline this page's other panels already follow for their
own numbers.

Unlike every other PLANNING panel, compliance is not priced on one
basis: carry and vega sufficiency read the book at today's market, crash
convexity reads it at the IPS crash shock — that mix is exactly what
"compliant" means, not a single repriced number, so it carries its own
chip rather than the zone's shared crash-skew one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, html

from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.compliance import (
    compliance_sections_at_ips_anchor,
    compliance_strip,
)
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec
from deltadewa.reporting.program_report import build_ips_compliance

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

_BASIS_IPS_POLICY = "basis: IPS policy verdict"

#: #357: this panel's TOC entry and heading id, from one source. Same
#: anchor id monitor.py's own compliance section uses — the two pages
#: never render at once, so the id is free to repeat (precedent:
#: "shape-notice").
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-compliance",
    title="Compliance",
)


def _render_compliance_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    market_env: MarketEnvironment,
) -> Component:
    """Render the compliance strip for the current book."""

    def _build() -> Component:
        cost_section, protection_section, vega_section = (
            compliance_sections_at_ips_anchor(portfolio, ips_config)
        )
        compliance = build_ips_compliance(
            cost_section,
            protection_section,
            vega_section,
        )
        return compliance_strip(
            compliance,
            market_env.data_quality,
            protection_section.excluded_expired_legs,
        )

    return _safe_render(_build)


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    market_env: MarketEnvironment,
) -> html.Div:
    """Build the Compliance panel.

    Takes the already-assessed ``market_env`` snapshot ``page.py``'s
    ``render()`` shares with the market-environment and monetization
    panels — this panel only reads its ``data_quality`` for a caveat
    line, never a graded input, so a second fetch here would add no
    accuracy and only risk disagreeing with the other panels reading
    the same snapshot.
    """
    return html.Div(
        [
            html.H3(
                [SECTION.title, basis_chip(_BASIS_IPS_POLICY)],
                id=SECTION.anchor_id,
            ),
            html.Div(
                _render_compliance_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                    market_env=market_env,
                ),
                id="plan-compliance-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Compliance panel's re-render callback."""

    @app.callback(
        Output("plan-compliance-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_compliance_panel(_version: int) -> Component:
        # Fresh fetch, like every other PLANNING panel's own callback
        # (market_env.py's docstring explains why: a callback fires
        # later than the render it followed, and there is no snapshot
        # from that render left to share).
        return _render_compliance_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            market_env=assess_market_environment(
                app.market_data,
                ips_config.market_environment,
            ),
        )
