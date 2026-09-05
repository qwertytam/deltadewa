"""PLANNING zone: the Position Aging panel (expiry buckets and calendar).

``basis_book_greeks`` is a parameter, not a module constant: this panel
shares its basis chip text with ``hedge_triggers`` and (in the
EXPLORATION zone) ``vega_term``, so the string lives in ``page.py`` and
is passed down to whichever panel needs it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, html

from deltadewa.analysis.position_aging import (
    ExpiryBucketLabel,
    evaluate_position_aging,
)
from deltadewa.app import format as fmt
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import incomplete_notice as _incomplete
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.position_aging import (
        ExpiryBoundaries,
        ExpiryBucketTotal,
        ExpiryCalendarEntry,
        PositionAging,
        SignedTotals,
    )
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-position-aging",
    title="Position aging",
)


def _day_range_text(low: int, high: int) -> str:
    """Format an inclusive day range, naming a collapsed one as empty.

    ``expiry_boundaries`` clamps its upper boundaries to keep the ladder
    monotonic rather than raising, so a legal-but-degenerate IPS (a short
    ``roll_at_months_remaining``, or a ``roll_review_buffer`` of 1.0) can
    leave a bucket with no days in it at all. Printing the arithmetic range
    would read as an inverted window; say the bucket is unreachable instead.
    """
    if low > high:
        return "none (IPS windows meet)"
    return f"{low}-{high}d"


def _expiry_window_text(
    label: ExpiryBucketLabel,
    boundaries: ExpiryBoundaries,
) -> str:
    """Spell out the day window *label* covers, from *boundaries*.

    The bucket labels deliberately carry no numbers (see
    :class:`~deltadewa.analysis.position_aging.ExpiryBucketLabel`) — this is
    where the IPS-resolved boundaries become visible, so editing
    ``ips.yaml`` moves both the grading and the printed window. The
    inclusive/exclusive edges here mirror
    :func:`~deltadewa.analysis.position_aging.classify_expiry_bucket`
    exactly.
    """
    windows = {
        ExpiryBucketLabel.EXPIRED: "<= 0d",
        ExpiryBucketLabel.URGENT: f"< {boundaries.urgent_days}d",
        ExpiryBucketLabel.SOON: _day_range_text(
            boundaries.urgent_days,
            boundaries.soon_days - 1,
        ),
        ExpiryBucketLabel.ROLL_DUE: _day_range_text(
            boundaries.soon_days,
            boundaries.roll_due_days,
        ),
        ExpiryBucketLabel.ROLL_REVIEW: _day_range_text(
            boundaries.roll_due_days + 1,
            boundaries.roll_review_days,
        ),
        ExpiryBucketLabel.LONG_TERM: f"> {boundaries.roll_review_days}d",
    }
    return windows[label]


def _nets_near_zero(value: float) -> bool:
    """Whether *value* would render as a whole-dollar/theta zero (#334).

    The columns this guards both format at zero decimals
    (:func:`~deltadewa.app.format.currency`,
    :func:`~deltadewa.app.format.signed_currency`), so anything that
    rounds to ``0`` at that precision is what a reader would actually
    see as "$0" / "+$0".
    """
    return abs(round(value)) == 0


def _net_and_gross_cell(
    *,
    net_text: str,
    long_text: str,
    short_text: str,
    show_gross: bool,
) -> html.Td:
    """Net on the first line; ``L ... - S ...`` muted underneath.

    *show_gross* is ``False`` for a pure-long or pure-short row -- a
    gross breakdown of a single side repeats the net and teaches
    nothing (#334).
    """
    if not show_gross:
        return html.Td(net_text)
    return html.Td(
        [
            html.Div(net_text),
            html.Div(
                f"L {long_text} · S {short_text}",
                className="aging-gross-line",
            ),
        ],
    )


def _aging_row_class(
    totals: SignedTotals,
    *,
    legs: int,
) -> str | None:
    """Pick the row's styling hook: empty, offsetting, or plain.

    ``aging-row--offsetting`` fires only when the net would otherwise
    read as "$0" *and* both a long and a short leg produced it --
    exactly the case #334 reported as indistinguishable from an empty
    bucket. A non-empty net (e.g. a real spread's mark) needs no flag
    even when it mixes long and short legs; that net is a meaningful
    number, not a cancellation to call out.
    """
    if legs == 0:
        return "aging-row--empty"
    if totals.is_offsetting and _nets_near_zero(totals.net_value):
        return "aging-row--offsetting"
    return None


def _aging_bucket_row(
    total: ExpiryBucketTotal,
    boundaries: ExpiryBoundaries,
) -> html.Tr:
    """One bucket's window, leg count and the size rolling off in it."""
    totals = total.totals
    show_gross = totals.is_offsetting
    return html.Tr(
        [
            html.Td(total.label.value),
            html.Td(_expiry_window_text(total.label, boundaries)),
            html.Td(f"{total.legs}"),
            html.Td(f"{total.contracts:+,}" if total.contracts else "0"),
            _net_and_gross_cell(
                net_text=fmt.currency(total.position_value),
                long_text=fmt.signed_currency(totals.long_value),
                short_text=fmt.signed_currency(totals.short_value),
                show_gross=show_gross,
            ),
            _net_and_gross_cell(
                net_text=fmt.signed_currency(total.position_theta),
                long_text=fmt.signed_currency(totals.long_theta),
                short_text=fmt.signed_currency(totals.short_theta),
                show_gross=show_gross,
            ),
        ],
        className=_aging_row_class(totals, legs=total.legs),
    )


def _aging_calendar_row(entry: ExpiryCalendarEntry) -> html.Tr:
    """One dated roll-off: every leg sharing this maturity."""
    totals = entry.totals
    show_gross = totals.is_offsetting
    return html.Tr(
        [
            html.Td(entry.maturity_date.strftime("%Y-%m-%d")),
            html.Td(f"{entry.days_to_expiry}d"),
            html.Td(entry.bucket.value),
            html.Td(f"{entry.legs}"),
            html.Td(f"{entry.contracts:+,}"),
            _net_and_gross_cell(
                net_text=fmt.currency(entry.position_value),
                long_text=fmt.signed_currency(totals.long_value),
                short_text=fmt.signed_currency(totals.short_value),
                show_gross=show_gross,
            ),
            _net_and_gross_cell(
                net_text=fmt.signed_currency(entry.position_theta),
                long_text=fmt.signed_currency(totals.long_theta),
                short_text=fmt.signed_currency(totals.short_theta),
                show_gross=show_gross,
            ),
        ],
        className=_aging_row_class(totals, legs=entry.legs),
    )


def _position_aging_panel_view(aging: PositionAging) -> Component:
    """Render the bucket summary and the expiration calendar."""
    if not aging.positions:
        return _incomplete(
            "Add a position in the BOOK zone to see the roll-off schedule.",
        )

    bucket_table = html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Bucket"),
                        html.Th("Window"),
                        html.Th("Legs"),
                        html.Th("Contracts"),
                        html.Th("Value"),
                        html.Th("Theta/day"),
                    ],
                ),
            ),
            html.Tbody(
                [
                    _aging_bucket_row(total, aging.boundaries)
                    for total in aging.buckets
                ],
            ),
        ],
        className="planning-table",
    )
    calendar_table = html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Expiry"),
                        html.Th("DTE"),
                        html.Th("Bucket"),
                        html.Th("Legs"),
                        html.Th("Contracts"),
                        html.Th("Value"),
                        html.Th("Theta/day"),
                    ],
                ),
            ),
            html.Tbody(
                [_aging_calendar_row(entry) for entry in aging.calendar],
            ),
        ],
        className="planning-table",
    )
    return html.Div(
        [
            html.P(
                "Every window comes from ips.yaml — expiry_urgent_days, "
                "expiry_soon_days, and the roll window "
                "(roll_at_months_remaining x roll_review_buffer). The two roll "
                "buckets are the same window the roll status table "
                "grades against, so the two panels cannot disagree.",
                className="plain-language",
            ),
            html.P(
                "Value and Theta/day are the NET mark and daily bleed of "
                "every leg in the row — what unwinding it realises today. "
                "When a row mixes a long and a short leg, an 'L · S' line "
                "underneath shows the gross sides that produced the net, "
                "so a row highlighted amber is a real offsetting position "
                "netting to $0 — not an empty one (#334).",
                className="plain-language",
            ),
            bucket_table,
            html.H4("Expiration calendar"),
            html.P(
                "One row per expiry date — how much of the book rolls off "
                "at a time.",
                className="plain-language",
            ),
            calendar_table,
        ],
    )


def _render_position_aging_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the per-leg expiry buckets and expiration calendar."""
    return _safe_render(
        lambda: _position_aging_panel_view(
            evaluate_position_aging(portfolio, ips_config),
        ),
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    basis_book_greeks: str,
) -> html.Div:
    """Build the Position Aging panel."""
    return html.Div(
        [
            html.H3(
                [SECTION.title, basis_chip(basis_book_greeks)],
                id=SECTION.anchor_id,
            ),
            html.Div(
                _render_position_aging_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                ),
                id="plan-position-aging-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Position Aging panel's re-render callback."""

    @app.callback(
        Output("plan-position-aging-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_position_aging_panel(_version: int) -> Component:
        return _render_position_aging_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )
