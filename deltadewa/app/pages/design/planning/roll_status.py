"""PLANNING zone: the Roll Status by Tranche panel.

The evidence layer under the Roll Plan panel above it: every position
(not just long puts) and every trigger reading behind its verdict. See
``roll_plan.py`` for why the two are deliberately separate panels
rather than a second opinion on the same question.

``basis_crash_skew`` is a parameter, not a module constant: every
PLANNING panel that prices the IPS crash shares this basis chip text,
so the string lives in ``page.py`` and is passed down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import Input, Output, html

from deltadewa.analysis.roll_status import RollVerdict, evaluate_roll_status
from deltadewa.app import format as fmt
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import safe_render as _safe_render

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.roll_status import MoneynessDrift, RollStatusRecord
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio


def _otm_pair_text(moneyness: MoneynessDrift) -> str:
    """Format "entry OTM% / current OTM%", entry as "n/a" when unrecorded."""
    entry = (
        fmt.signed_percent(moneyness.entry_otm_pct)
        if moneyness.entry_otm_pct is not None
        else "n/a"
    )
    return f"{entry} / {fmt.signed_percent(moneyness.current_otm_pct)}"


def _dte_text(record: RollStatusRecord) -> str:
    """Days-to-maturity cell — or the expiry date for a leg already gone.

    ``-435d / 180d`` is technically the day count but reads as an extreme
    roll urgency; the sign is the only signal and it is easy to miss (#373).
    """
    if record.verdict is RollVerdict.EXPIRED:
        return f"expired {record.position.option.maturity_date.date()}"
    return f"{record.days_to_maturity}d / {record.roll_window_days}d"


def _leg_convexity_text(record: RollStatusRecord) -> str:
    """Render this leg's own contribution to book crash convexity (#306).

    The neighbouring Convexity cell is a **book-level** gate — the IPS band
    is stated against the whole book, so it cannot be applied per leg. This
    cell is the per-tranche number that gate never carried: contributions
    sum exactly to the book figure, so this is the column that answers
    *which* tranche to roll.

    ``n/a`` for an expired leg, which was never priced — not ``+0.00``,
    which would read as a worthless leg rather than an unpriced one.
    """
    contribution = record.leg_convexity_contribution_pct
    if contribution is None:
        return "n/a"
    return f"{contribution:+.2f} pp"


def _roll_record_row(record: RollStatusRecord) -> html.Tr:
    """One position's roll status, with all three trigger reasons (G3)."""
    position = record.position
    cost_text = (
        fmt.currency(record.estimated_roll_up_cost, decimals=2)
        if record.estimated_roll_up_cost is not None
        else "n/a"
    )
    return html.Tr(
        [
            html.Td(
                html.Span(
                    record.verdict.value,
                    className=(
                        "verdict-badge verdict-badge--"
                        f"{record.verdict.value.lower()}"
                    ),
                ),
            ),
            html.Td(
                f"{position.option.option_type.value} "
                f"{position.option.strike_price:,.0f}",
            ),
            html.Td(_otm_pair_text(record.moneyness)),
            html.Td(_dte_text(record)),
            html.Td(cost_text),
            html.Td(_leg_convexity_text(record)),
            html.Td(
                f"Time: {record.time_trigger.verdict.value} — "
                f"{record.time_trigger.reason}"
            ),
            html.Td(
                f"Convexity (book): {record.convexity_trigger.verdict.value}"
                f" — {record.convexity_trigger.reason}",
            ),
            html.Td(
                f"Rally: {record.rally_trigger.verdict.value} — "
                f"{record.rally_trigger.reason}",
            ),
        ],
    )


def _roll_panel_view(records: list[RollStatusRecord]) -> Component:
    """Render the per-position roll table.

    The evidence layer under the roll plan above: every position (not
    just long puts) and every trigger reading behind its verdict.
    """
    intro = html.P(
        "The evidence behind the roll plan above — every position in "
        "the book, and how each of its three IPS triggers reads. The "
        "plan turns these grades into an action; this table is where "
        "you check one.",
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
            html.Th("Verdict"),
            html.Th("Position"),
            html.Th("OTM entry / now"),
            html.Th("DTE / window"),
            html.Th("Est. roll-up cost"),
            html.Th("This leg's convexity"),
            html.Th("Time trigger"),
            html.Th("Convexity trigger (book)"),
            html.Th("Rally trigger"),
        ],
    )
    rows = [_roll_record_row(record) for record in records]
    return html.Div(
        [
            intro,
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="planning-table",
            ),
        ],
    )


def _render_roll_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the roll status table for every position in the book."""
    return _safe_render(
        lambda: _roll_panel_view(evaluate_roll_status(portfolio, ips_config)),
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    basis_crash_skew: str,
) -> html.Div:
    """Build the Roll Status by Tranche panel."""
    return html.Div(
        [
            html.H3(
                [
                    "Roll status by tranche",
                    basis_chip(basis_crash_skew),
                ],
            ),
            html.Div(
                _render_roll_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                ),
                id="plan-roll-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Roll Status by Tranche panel's re-render callback."""

    @app.callback(
        Output("plan-roll-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_roll_panel(_version: int) -> Component:
        return _render_roll_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )
