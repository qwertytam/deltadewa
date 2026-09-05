"""PLANNING zone: the Convexity Cliff panel (Part X "Time to Convexity Cliff").

Touches no market input whatsoever — it compares each long put's maturity
date against the valuation date. Nothing is priced and no Greek is read,
so it is the one PLANNING panel that cannot honestly carry even the
book-Greeks chip; it prices ``_BASIS_MATURITY_CALENDAR`` instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, html

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.health import NO_LONG_PUTS_CLIFF_DAYS
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig, IpsConvexity
    from deltadewa.portfolio.core import OptionPortfolio

# Nor does the convexity cliff panel, which is the only PLANNING panel that
# touches no market input whatsoever: it compares each long put's maturity
# date against the valuation date. Nothing is priced and no Greek is read,
# so it cannot honestly carry even the book-Greeks chip.
_BASIS_MATURITY_CALENDAR = "basis: position maturities (nothing priced)"

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-convexity-cliff",
    title="Convexity cliff",
)


def _cliff_verdict(days: int, conv: IpsConvexity) -> str:
    """Grade the cliff runway against the IPS review/urgent lines.

    One-sided by construction: more runway is better without limit, so there
    is no "too far from the cliff" verdict and deliberately no band bar. The
    vocabulary matches the hedge-trigger panel's so the two read consistently
    when a reader scans down the zone.
    """
    if days <= conv.cliff_urgent_days:
        return "URGENT"
    if days <= conv.cliff_review_days:
        return "REVIEW"
    return "OK"


def _convexity_cliff_panel_view(days: int, conv: IpsConvexity) -> Component:
    """Render Part X's "Time to Convexity Cliff" for the current book.

    Sits after delta drift because it answers the same rebalancing question on
    the calendar axis: not how the hedge behaves if spot moves now, but how
    long the book keeps the convexity it was bought for. A tail hedge that is
    still nominally in place can already have stopped paying off in a crash.

    The no-long-puts case is reported as unavailable rather than as the
    sentinel's numeric value — see
    :data:`~deltadewa.analysis.health.NO_LONG_PUTS_CLIFF_DAYS`.
    """
    if days == NO_LONG_PUTS_CLIFF_DAYS:
        return html.P(
            "The book holds no long puts, so there is no hedge convexity to "
            "decay and this metric does not apply.",
            className="plain-language",
        )
    lead = (
        "A long put loses convexity quickly once its remaining maturity gets "
        f"short. Counting from {conv.cliff_threshold_days} days to expiry as "
        "the start of that high-gamma region, "
    )
    if days == 0:
        # The engine floors the runway at zero, so it cannot say how far past
        # the boundary a leg already is: a put at 120 DTE and one at 30 DTE
        # both read 0 against a 180-day region. Saying "already inside"
        # rather than "0 days" keeps the panel from implying the two are the
        # same decision, without claiming a number it doesn't have.
        return html.Div(
            [
                html.P(
                    lead
                    + "the nearest long put in the book is already inside it.",
                    className="plain-language",
                ),
                html.P(
                    "Past the cliff — URGENT. Convexity is already decaying; "
                    "the roll trigger should have fired first "
                    f"({conv.cliff_review_days}d review, "
                    f"{conv.cliff_urgent_days}d urgent).",
                    className="env-verdict",
                ),
            ],
        )
    verdict = _cliff_verdict(days, conv)
    return html.Div(
        [
            html.P(
                lead + "the nearest long put in the book has "
                f"{days:,} days of runway before it gets there.",
                className="plain-language",
            ),
            html.P(
                f"{days:,} days to the cliff — {verdict} against the IPS "
                f"lines ({conv.cliff_review_days}d review, "
                f"{conv.cliff_urgent_days}d urgent).",
                className="env-verdict",
            ),
        ],
    )


def _render_convexity_cliff_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the convexity cliff panel for the current book."""
    return _safe_render(
        lambda: _convexity_cliff_panel_view(
            PortfolioAnalyzer(portfolio).calculate_convexity_cliff_days(
                cliff_threshold_days=ips_config.convexity.cliff_threshold_days,
            ),
            ips_config.convexity,
        ),
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> html.Div:
    """Build the Convexity Cliff panel."""
    return html.Div(
        [
            html.H3(
                [
                    SECTION.title,
                    basis_chip(_BASIS_MATURITY_CALENDAR),
                ],
                id=SECTION.anchor_id,
            ),
            html.Div(
                _render_convexity_cliff_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                ),
                id="plan-convexity-cliff-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Convexity Cliff panel's re-render callback."""

    @app.callback(
        Output("plan-convexity-cliff-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_convexity_cliff_panel(_version: int) -> Component:
        return _render_convexity_cliff_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )
