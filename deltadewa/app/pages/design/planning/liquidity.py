"""PLANNING zone: the Liquidity Check panel (Part X #12, 8c / N10).

Part X #12 needs a per-strike options chain (#156); this is the honest
substitute: a checklist of the operator's own quotes, one per held leg,
graded by ``analysis.liquidity`` against the IPS ``liquidity:`` policy.

Like the provenance panel, its "record a quote" control is a BOOK
mutation: the callback writes ``book.BOOK_VERSION_STORE`` and
``book.MUTATION_STATUS``, imported by name, and the mutator logic
(``_record_liquidity_logic``) lives in ``book.py`` with the others.

No basis chip: nothing here is priced. The disclaimer is rendered every
time, not only when something is wrong — what this panel cannot see is
the same on a quiet day as on a bad one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from dash import Input, Output, State, dcc, html, no_update

from deltadewa.analysis.liquidity import (
    LegLiquidity,
    LiquidityChecklist,
    OpenInterestGrade,
    SpreadGrade,
    assess_liquidity,
    roll_due_position_ids,
)
from deltadewa.analysis.provenance import Freshness
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec
from deltadewa.clock import program_trading_date

from ..book import (
    BOOK_VERSION_STORE,
    MUTATION_STATUS,
    _record_liquidity_logic,
)

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-liquidity",
    title="Liquidity check (hand-entered)",
)

_PANEL_ID = "plan-liquidity-panel"
_LEG_INPUT = "liquidity-leg"
_BID_INPUT = "liquidity-bid"
_ASK_INPUT = "liquidity-ask"
_OI_INPUT = "liquidity-open-interest"
_RECORD_BUTTON = "liquidity-record"

#: Rendered always. Says what this is, and what #156's feed would add
#: that a hand-entered quote cannot — the panel's own "what it does not
#: claim", kept beside the numbers rather than only in docs.
_DISCLAIMER = (
    "Point-in-time quotes you entered — not a liquidity feed. A spread "
    "here describes the moment you looked, not now. A live options chain "
    "(#156) would add what this cannot: quotes for every strike, "
    "including ladder candidates you don't hold; depth behind the quote; "
    "traded volume; intraday and stress-time widening; and automatic "
    "refresh. Record a quote whenever you roll, monetize or add to a "
    "leg — the moments the handbook says liquidity matters."
)


def _spread_text(leg: LegLiquidity) -> str:
    obs = leg.observation
    if obs is None or leg.spread_grade is None:
        return "—"
    grade = (
        ""
        if leg.spread_grade is SpreadGrade.UNGRADED
        else f" {leg.spread_grade.value}"
    )
    return f"{obs.spread_pct:.1f}%{grade}"


def _open_interest_text(leg: LegLiquidity) -> str:
    obs = leg.observation
    if obs is None:
        return "—"
    if obs.open_interest is None:
        return "not recorded"
    grade = (
        " ungraded"
        if leg.open_interest_grade is OpenInterestGrade.UNGRADED
        else f" {leg.open_interest_grade.value}"
        if leg.open_interest_grade is not None
        else ""
    )
    share = (
        f" (you hold {leg.held_share_of_oi_pct:.1f}%)"
        if leg.held_share_of_oi_pct is not None
        else ""
    )
    return f"{obs.open_interest:,}{grade}{share}"


def _checked_text(leg: LegLiquidity) -> str:
    """When the quote was read, and whether that is still recent enough.

    A grade on a quote that is not ``FRESH`` is labelled as "at last
    check" by this column — never presented as the current market.
    """
    obs = leg.observation
    if obs is None:
        return "never checked"
    date_text = f"{obs.observed_at:%Y-%m-%d}"
    freshness = leg.freshness
    if freshness is None:
        return f"{date_text} (no review cadence set)"
    if freshness.freshness is Freshness.FRESH:
        return f"{date_text} ({freshness.age_days}d ago)"
    return (
        f"{date_text} — {freshness.age_days}d ago, overdue "
        f"(policy {freshness.max_age_days}d); grades are as of that day"
    )


def _due_text(leg: LegLiquidity) -> str:
    if leg.roll_due and leg.capture_due:
        return "yes — leg is in its roll window; read today's quote"
    if leg.roll_due:
        return "no — read today, for the roll"
    if leg.observation is None:
        return "yes — never checked"
    if leg.capture_due:
        return "yes — overdue"
    return "no"


def _leg_row(leg: LegLiquidity) -> html.Tr:
    obs = leg.observation
    quote = f"{obs.bid:,.2f} / {obs.ask:,.2f}" if obs is not None else "—"
    return html.Tr(
        [
            html.Td(leg.label),
            html.Td(quote),
            html.Td(_spread_text(leg)),
            html.Td(_open_interest_text(leg)),
            html.Td(_checked_text(leg)),
            html.Td(_due_text(leg)),
        ],
    )


def _headline(checklist: LiquidityChecklist) -> str:
    """Summarise the checklist as counts — quotes cannot support "fine"."""
    n_legs = len(checklist.legs)
    parts = [
        f"{n_legs} leg{'s' if n_legs != 1 else ''}",
        f"{checklist.capture_due} need a fresh quote",
        f"{checklist.never_checked} never checked",
    ]
    if checklist.policy_present:
        parts.extend(
            [
                f"{checklist.overdue} overdue",
                f"{checklist.wide_at_last_check} wide at last check",
            ],
        )
    return " · ".join(parts)


def _policy_text(ips_config: IpsConfig) -> str:
    policy = ips_config.liquidity
    if policy is None:
        return (
            "Ungraded: ips.yaml has no liquidity: section, and the "
            "handbook gives no number for a wide spread or low open "
            "interest — so none is assumed here."
        )
    oi_text = (
        f"open interest below {policy.open_interest_min:,} grades LOW"
        if policy.open_interest_min is not None
        else "open interest is recorded but not graded (no minimum set)"
    )
    return (
        f"IPS policy: a spread wider than {policy.spread_warn_pct:g}% of "
        f"mid grades WIDE; {oi_text}; a quote older than "
        f"{policy.observation_max_age_days}d is overdue."
    )


def _liquidity_panel_view(
    checklist: LiquidityChecklist,
    ips_config: IpsConfig,
) -> Component:
    header = html.Tr(
        [
            html.Th("Leg"),
            html.Th("Bid / ask"),
            html.Th("Spread"),
            html.Th("Open interest"),
            html.Th("Checked"),
            html.Th("Quote due"),
        ],
    )
    body: list[Component] = [
        html.P(_DISCLAIMER, className="plain-language"),
        html.P(_policy_text(ips_config), className="plain-language"),
    ]
    if not checklist.legs:
        body.append(html.P("No legs in the book.", className="env-verdict"))
        return html.Div(body)
    body.extend(
        [
            html.P(_headline(checklist), className="env-verdict"),
            html.Table(
                [
                    html.Thead(header),
                    html.Tbody([_leg_row(leg) for leg in checklist.legs]),
                ],
                className="planning-table",
            ),
        ],
    )
    return html.Div(body)


def _build_checklist(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> LiquidityChecklist:
    return assess_liquidity(
        portfolio,
        ips_config.liquidity,
        as_of=program_trading_date(ips_config.program.timezone).date(),
        roll_due_ids=roll_due_position_ids(
            evaluate_roll_status(portfolio, ips_config),
        ),
    )


def _render_liquidity_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the liquidity checklist for the current book."""
    return _safe_render(
        lambda: _liquidity_panel_view(
            _build_checklist(portfolio, ips_config),
            ips_config,
        ),
    )


def _leg_options(portfolio: OptionPortfolio) -> list[dict[str, str]]:
    return [
        {
            "label": (
                f"{position.option.option_type.value} "
                f"{position.option.strike_price:g} exp "
                f"{position.option.maturity_date:%Y-%m-%d}"
            ),
            "value": position.position_id,
        }
        for position in portfolio.positions
    ]


def _number_field(label: str, input_id: str) -> html.Div:
    return html.Div(
        [
            html.Label(label),
            dcc.Input(id=input_id, type="number", min=0),
        ],
        className="editor-field",
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> html.Div:
    """Build the Liquidity Check panel: checklist, then the record form."""
    return html.Div(
        [
            # No basis chip: nothing here is priced (see module docstring).
            html.H3(SECTION.title, id=SECTION.anchor_id),
            html.Div(
                _render_liquidity_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                ),
                id=_PANEL_ID,
            ),
            html.Fieldset(
                [
                    html.Div(
                        [
                            html.Label("Leg"),
                            dcc.Dropdown(
                                id=_LEG_INPUT,
                                options=_leg_options(portfolio),
                                clearable=False,
                            ),
                        ],
                        className="editor-field",
                    ),
                    _number_field("Bid", _BID_INPUT),
                    _number_field("Ask", _ASK_INPUT),
                    _number_field("Open interest (optional)", _OI_INPUT),
                    html.Button(
                        "Record quote",
                        id=_RECORD_BUTTON,
                        className="btn btn-secondary",
                    ),
                ],
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Liquidity Check panel's callbacks.

    Three: the checklist re-render and the leg dropdown's options (both
    watch ``book-version``, so a leg added or removed elsewhere shows up
    here), and the "record quote" mutation.
    """

    @app.callback(
        Output(_PANEL_ID, "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_liquidity_panel(_version: int) -> Component:
        return _render_liquidity_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    @app.callback(
        Output(_LEG_INPUT, "options"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _refresh_leg_options(_version: int) -> list[dict[str, str]]:
        return _leg_options(app.program_state.portfolio)

    @app.callback(
        Output(BOOK_VERSION_STORE, "data", allow_duplicate=True),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Input(_RECORD_BUTTON, "n_clicks"),
        State(_LEG_INPUT, "value"),
        State(_BID_INPUT, "value"),
        State(_ASK_INPUT, "value"),
        State(_OI_INPUT, "value"),
        State(BOOK_VERSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def _record_liquidity(  # pylint: disable=too-many-arguments
        n_clicks: int | None,
        position_id: str | None,
        bid: float | None,
        ask: float | None,
        open_interest: float | None,
        version: int,
    ) -> tuple[Any, Any]:
        if not n_clicks:
            return no_update, no_update
        return _record_liquidity_logic(
            position_id=position_id,
            bid=bid,
            ask=ask,
            open_interest=open_interest,
            version=version,
            state=app.program_state,
        )
