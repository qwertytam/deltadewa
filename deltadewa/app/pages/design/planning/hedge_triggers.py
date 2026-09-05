"""PLANNING zone: the Hedge Rebalance Triggers panel.

Deliberately **not** merged into the roll panels: the roll plan and its
status table ask "should this tranche be replaced" per position, while
these four ask "is the book still hedged the way policy says" for the
book as a whole. They are different questions with different
thresholds, and a combined table would imply one verdict where there
are two.

``basis_book_greeks`` is a parameter, not a module constant: this panel
shares its basis chip text with ``position_aging`` and (in the
EXPLORATION zone) ``vega_term``, so the string lives in ``page.py`` and
is passed down to whichever panel needs it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, html

from deltadewa.analysis.hedge_triggers import (
    HedgeTriggerThresholds,
    evaluate_hedge_trigger_set,
)
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.hedge_triggers import (
        HedgeTriggerReason,
        HedgeTriggerSet,
    )
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-hedge-triggers",
    title="Hedge rebalance triggers",
)


def _hedge_trigger_row(trigger: HedgeTriggerReason) -> html.Tr:
    """One rebalance trigger: status badge, name, and the reason for it.

    Reuses the ``verdict-badge`` styling the roll table already uses, so
    the two tables read alike — but see :func:`_hedge_triggers_panel_view`
    for why they are not the same set.
    """
    return html.Tr(
        [
            html.Td(
                html.Span(
                    trigger.status.value,
                    className=(
                        "verdict-badge verdict-badge--"
                        f"{trigger.status.value.lower()}"
                    ),
                ),
            ),
            html.Td(trigger.label),
            html.Td(trigger.reason),
        ],
    )


def _hedge_triggers_panel_view(triggers: HedgeTriggerSet) -> Component:
    """Render the book-level rebalance triggers, each with its reasoning.

    Deliberately **not** merged into the roll panels above, despite the
    shared vocabulary: the roll plan and its status table ask "should
    this tranche be replaced" per position, while these four ask "is the
    book still hedged the way policy says" for the book as a whole. They
    are different questions with different thresholds, and a combined
    table would imply one verdict where there are two.
    """
    header = html.Tr(
        [html.Th("Status"), html.Th("Trigger"), html.Th("Reading vs policy")],
    )
    children: list[Component] = [
        html.P(
            "Book-level rebalance triggers — distinct from the roll panels "
            "above, which judge each tranche separately. These ask whether "
            "the book as a whole is still hedged the way the IPS says.",
            className="plain-language",
        ),
        html.Table(
            [
                html.Thead(header),
                html.Tbody([_hedge_trigger_row(t) for t in triggers]),
            ],
            className="planning-table",
        ),
    ]
    if triggers.actions:
        children.append(
            html.Ul(
                [
                    html.Li(f"{priority}: {description}")
                    for priority, description in triggers.actions
                ],
                className="trigger-actions",
            ),
        )
    else:
        children.append(
            html.P(
                "No action required — every trigger is inside its band.",
                className="plain-language",
            ),
        )
    return html.Div(children)


def _render_hedge_triggers_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the hedge rebalance triggers for the current book."""
    return _safe_render(
        lambda: _hedge_triggers_panel_view(
            evaluate_hedge_trigger_set(
                portfolio,
                HedgeTriggerThresholds.from_ips(ips_config.triggers),
            ),
        ),
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    basis_book_greeks: str,
) -> html.Div:
    """Build the Hedge Rebalance Triggers panel."""
    return html.Div(
        [
            html.H3(
                [
                    SECTION.title,
                    basis_chip(basis_book_greeks),
                ],
                id=SECTION.anchor_id,
            ),
            html.Div(
                _render_hedge_triggers_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                ),
                id="plan-hedge-triggers-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Hedge Rebalance Triggers panel's re-render callback."""

    @app.callback(
        Output("plan-hedge-triggers-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_hedge_triggers_panel(_version: int) -> Component:
        return _render_hedge_triggers_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )
