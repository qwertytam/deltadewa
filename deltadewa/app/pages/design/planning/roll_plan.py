"""PLANNING zone: the Roll Plan panel.

Deliberately a separate panel from the Roll Status by Tranche table
(``roll_status.py``), and deliberately not a second opinion on the same
question. The table grades each tranche's three triggers; this turns
those grades into one action per long put, applying the handbook's
gamma/theta nuance the table's verdicts have no vocabulary for — and
says what to roll *to* and what that would cost.

``basis_crash_skew`` is a parameter, not a module constant: every
PLANNING panel that prices the IPS crash shares this basis chip text,
so the string lives in ``page.py`` and is passed down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, html

from deltadewa.analysis.roll_planner import build_roll_plan
from deltadewa.app import format as fmt
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.roll_planner import RollPlanRecord
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-roll-plan",
    title="Roll plan",
)


def _roll_plan_row(record: RollPlanRecord, *, grouped: bool = False) -> html.Tr:
    """One long put's recommended action, proposal, and reasoning.

    The reasoning cell is not decoration. ``DELAY`` is a recommendation
    to *not* act on a trigger that has fired, so it has to arrive with
    its justification attached or it reads as the tool losing the
    signal.

    Args:
        record: The leg to render.
        grouped: Whether this row sits under a
            :func:`_plan_group_header_row` — when it does, the header
            already names the structure, so the leg text drops the
            redundant ``(structure_id)`` suffix (#333).

    """
    strike_text = (
        f"{record.target_strike:,.0f}"
        if record.target_strike is not None
        else "n/a"
    )
    cost_text = (
        fmt.signed_currency(record.roll_up_cost)
        if record.roll_up_cost is not None
        else "n/a"
    )
    excluded = record.action is None
    action_text = (
        "—" if record.action is None else record.action.value.replace("_", " ")
    )
    action_class = (
        "verdict-badge verdict-badge--excluded"
        if record.action is None
        else f"verdict-badge verdict-badge--{record.action.value.lower()}"
    )
    row_classes = " ".join(
        cls
        for cls in (
            "plan-row--excluded" if excluded else None,
            "plan-row--grouped" if grouped else None,
        )
        if cls is not None
    )
    return html.Tr(
        [
            html.Td(html.Span(action_text, className=action_class)),
            html.Td(_plan_leg_text(record, show_structure_suffix=not grouped)),
            html.Td(strike_text),
            html.Td(cost_text),
            html.Td(f"{record.gamma:,.4f} / {record.theta:,.2f}"),
            html.Td(record.rationale, className="plan-rationale"),
        ],
        className=row_classes or None,
    )


def _plan_leg_text(
    record: RollPlanRecord,
    *,
    show_structure_suffix: bool = True,
) -> str:
    """Name the leg, and the structure it rolls with when it has one.

    ``show_structure_suffix=False`` drops the ``(structure_id)`` suffix for
    a row already sitting under that structure's group header (#333) — the
    tag would otherwise be said twice.
    """
    position = record.position
    leg = (
        f"{position.option.option_type.value} "
        f"{position.option.strike_price:,.0f}"
    )
    if record.structure_id is None or not show_structure_suffix:
        return leg
    return f"{leg} ({record.structure_id})"


def _group_plan_records(
    records: list[RollPlanRecord],
) -> list[tuple[str | None, list[RollPlanRecord]]]:
    """Cluster *records* by ``structure_id`` for display only (#333).

    Pure rendering grouping — the underlying records are unchanged, one
    per leg, in whatever order ``build_roll_plan`` returned them. This
    only decides how they're clustered on screen: legs sharing a tag move
    together, in the order their tag was first seen; a leg with no tag is
    always its own singleton group. Mirrors
    :func:`~deltadewa.analysis.roll_planner.group_into_structures`'s own
    tag-or-singleton grouping, but over :class:`RollPlanRecord` rather
    than ``OptionPosition``.
    """
    grouped: dict[object, list[RollPlanRecord]] = {}
    for record in records:
        tag = record.structure_id
        key: object = tag if tag is not None else object()
        grouped.setdefault(key, []).append(record)
    return [(legs[0].structure_id, legs) for legs in grouped.values()]


def _plan_group_header_row(
    structure_id: str,
    legs: list[RollPlanRecord],
) -> html.Tr:
    """One header row naming a multi-leg structure's grouped rows (#333).

    Target strike and roll-up cost are already identical across every leg
    in the group — netted once in ``roll_planner`` — so they are stated
    here rather than repeated silently on each leg row below.
    """
    priced = next((r for r in legs if r.target_strike is not None), None)
    strike_text = (
        f"target {priced.target_strike:,.0f}" if priced is not None else "n/a"
    )
    cost_text = (
        fmt.signed_currency(priced.roll_up_cost)
        if priced is not None and priced.roll_up_cost is not None
        else "n/a"
    )
    return html.Tr(
        html.Td(
            f"{structure_id} — {len(legs)} legs, rolled as one structure "
            f"({strike_text}, net cost {cost_text})",
            colSpan=6,
            className="plan-group-header",
        ),
    )


def _roll_plan_panel_view(records: list[RollPlanRecord]) -> Component:
    """Render the per-put roll plan: action, proposal, and reasoning.

    Deliberately a separate panel from the roll status table below it,
    and deliberately not a second opinion on the same question. The
    table grades each tranche's three triggers; this turns those grades
    into one action per long put, applying the handbook's gamma/theta
    nuance that the table's verdicts have no vocabulary for — and says
    what to roll *to* and what that would cost.
    """
    intro = html.P(
        "One recommended action per leg — what to roll it to, and what "
        "that roll would cost. Built on the same trigger grades as the "
        "roll status table below, so the two never disagree: this panel "
        "adds the handbook's gamma/theta judgement, which is the only "
        "thing that can turn a fired trigger into DELAY. Legs that get no "
        "recommendation of their own — short legs of a spread, non-puts, "
        "expired legs — are still listed, greyed, with the reason: a leg "
        "the planner skipped must never just be absent.",
        className="plain-language",
    )
    if not records:
        return html.Div(
            [
                intro,
                html.P(
                    "No positions in the book yet.",
                    className="plain-language",
                ),
            ],
        )

    header = html.Tr(
        [
            html.Th("Action"),
            html.Th("Position"),
            html.Th("Target strike"),
            html.Th("Roll-up cost"),
            html.Th("Gamma / theta"),
            html.Th("Reasoning"),
        ],
    )
    rows: list[html.Tr] = []
    for structure_id, legs in _group_plan_records(records):
        if structure_id is not None and len(legs) > 1:
            rows.append(_plan_group_header_row(structure_id, legs))
            rows.extend(_roll_plan_row(r, grouped=True) for r in legs)
        else:
            rows.extend(_roll_plan_row(r) for r in legs)
    return html.Div(
        [
            intro,
            html.Table(
                [
                    html.Thead(header),
                    html.Tbody(rows),
                ],
                className="planning-table",
            ),
        ],
    )


def _render_roll_plan_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the roll plan for every long put in the book."""
    return _safe_render(
        lambda: _roll_plan_panel_view(build_roll_plan(portfolio, ips_config)),
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    basis_crash_skew: str,
) -> html.Div:
    """Build the Roll Plan panel."""
    return html.Div(
        [
            html.H3(
                [SECTION.title, basis_chip(basis_crash_skew)],
                id=SECTION.anchor_id,
            ),
            html.Div(
                _render_roll_plan_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                ),
                id="plan-roll-plan-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Roll Plan panel's re-render callback."""

    @app.callback(
        Output("plan-roll-plan-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_roll_plan_panel(_version: int) -> Component:
        return _render_roll_plan_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )
