"""PLANNING zone: the Pricing inputs panel (9b).

What the book is priced on, and where each number came from. For each of the
four inputs (the index level, the rate, the dividend yield and each option's
IV) it shows the value that prices the book, its origin (fetched, last good,
your override, fallback to your value, or your value), the value you typed,
and what the nightly feed says now.

It is also where you take control of a number:

- **Override** spot or one option's IV: your value is pinned above the feed
  until you clear it, and is listed on `/monitor` and in the digest with its
  age and the feed's figure beside it (D7).
- **Edit the dividend yield**: never fetched (put-call parity cannot
  separate it from funding and timing), so it is typed and confirmed
  quarterly (D5).

Every change is review then confirm: the review says exactly what confirming
will do and warns when your number is far from the feed's; nothing is
written until you confirm.

**The app reads prices once, when it starts.** A page reload re-renders the
same readings, so the panel says so at the top, and says when a newer chain
is cached that only a restart would adopt. The table's "feed now" figures
are what the cache holds today, which can be newer than what prices the book.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final

from dash import Input, Output, State, dcc, html, no_update

from deltadewa.analysis.chain_quotes import (
    ChainReading,
    read_fetched_chain,
    read_positions,
    rung_readings,
)
from deltadewa.analysis.implied_vol import cmt_to_continuous
from deltadewa.analysis.pricing_resolution import (
    InputOrigin,
    newer_cached_session,
)
from deltadewa.app import input_overrides as io
from deltadewa.app.chrome import priced_notice
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.panel_guard import status_message as _status
from deltadewa.app.section_nav import SectionSpec
from deltadewa.clock import program_trading_date
from deltadewa.marketdata import MarketDataError

from ..book import BOOK_VERSION_STORE, MUTATION_STATUS, _guarded_mutation

if TYPE_CHECKING:
    from datetime import datetime

    from dash.development.base_component import Component

    from deltadewa.analysis.pricing_resolution import ResolvedValue
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig, IpsPricingFeed
    from deltadewa.marketdata import MarketDataProvider
    from deltadewa.marketdata.chain import ChainSnapshot
    from deltadewa.state import ProgramState

_logger = logging.getLogger(__name__)

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-pricing-inputs",
    title="Pricing inputs",
)

_PANEL_ID = "plan-pricing-inputs-panel"
_TARGET = "pricing-target"
_ACTION = "pricing-action"
_VALUE = "pricing-value"
_REVIEW_BUTTON = "pricing-review"
_REVIEW_TEXT = "pricing-review-text"
_CONFIRM_ROW = "pricing-confirm-row"
_CONFIRM_BUTTON = "pricing-confirm"
_CANCEL_BUTTON = "pricing-cancel"
_PENDING = "pricing-pending"

_EXPLANATION = (
    "What the book is priced on, and where each number came from. The "
    "feed is the SPX option chain from the source pricing_feed.chain_source "
    'names, and a FRED Treasury rate, fetched daily. "IV at book r, q" is '
    "solved from the close mid with the program's own European engine at "
    "the book's rate and dividend yield, so it reprices the mid exactly; "
    "the vendor's IV, where it gives one, is solved at its own rate and "
    "dividend, and differs from it by roughly half to three quarters of a "
    "vol point per point of rate or yield. An IV and the rate and yield it "
    "was solved with are a pair, never mixed."
)

_DIVIDEND_NOTE = (
    "Never fetched: put-call parity measures the dividend, funding and "
    "timing together and cannot isolate the yield. It is hand-entered and "
    "confirmed quarterly."
)

_NO_FEED = (
    "ips.yaml has no pricing_feed section, so nothing is fetched and every "
    "pricing input is hand-entered. Add the section (see "
    "config/ips.example.yaml) to start the nightly fetch."
)

_UNEXPECTED = "Something went wrong — see the server log."

_EM_DASH = "—"

#: What the panel prints for each origin.
_ORIGIN_CLASS: Final[dict[InputOrigin, str]] = {
    InputOrigin.FETCHED: "origin--fetched",
    InputOrigin.LAST_GOOD: "origin--last-good",
    InputOrigin.OVERRIDE: "origin--override",
    InputOrigin.FALLBACK: "origin--fallback",
    InputOrigin.ENTERED: "origin--entered",
}


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _fraction_pct(value: float | None) -> str:
    return _EM_DASH if value is None else f"{value * 100:.2f}%"


def _adopt_text(feed: IpsPricingFeed) -> str:
    source = (
        f"Option chain source: {feed.chain_source.value}."
        if feed.fetches_chain
        else "Option chain source: none (no chain is fetched)."
    )
    if not feed.adopt:
        return (
            "Policy adopt: nothing. The feed is fetched and shown here, and "
            f"every number is priced on your typed value. {source}"
        )
    named = ", ".join(feed.adopt)
    return (
        f"Policy adopt: {named}. These are priced on the feed's value "
        "unless you override them or the feed has nothing usable; "
        f"dividend_yield is never adopted. {source}"
    )


def _flags_text(reading: ChainReading) -> str:
    if not reading.flags:
        return "clean"
    return ", ".join(sorted(flag.value for flag in reading.flags))


def _contract_text(reading: ChainReading) -> str:
    quote = reading.quote
    if quote is None:
        return "not listed"
    return f"{quote.symbol} ({quote.root})"


def _quote_text(reading: ChainReading) -> str:
    quote = reading.quote
    if quote is None:
        return _EM_DASH
    return f"{_money(quote.bid)} / {_money(quote.ask)} ({_money(quote.mid)})"


def _spread_text(reading: ChainReading) -> str:
    quote = reading.quote
    if quote is None or quote.spread_pct is None:
        return _EM_DASH
    return f"{quote.spread_pct:.1f}%"


def _open_interest_text(reading: ChainReading) -> str:
    quote = reading.quote
    if quote is None or quote.open_interest is None:
        return _EM_DASH
    return f"{quote.open_interest:,}"


def _origin_cell(value: ResolvedValue) -> html.Td:
    return html.Td(
        f"{io.origin_text(value.origin)} — {value.detail}",
        className=f"origin {_ORIGIN_CLASS[value.origin]}",
    )


def _age_text(stamp_age_days: int | None) -> str:
    if stamp_age_days is None:
        return "never confirmed"
    return f"confirmed {stamp_age_days}d ago"


def _stamp_age(state: ProgramState, stamp: datetime | None) -> int | None:
    if stamp is None:
        return None
    today = state.portfolio.valuation_date.date()
    return max((today - stamp.date()).days, 0)


def _reading_row(
    label: str,
    reading: ChainReading,
    *,
    effective: ResolvedValue | None,
    typed_iv: float | None,
    typed_age: int | None,
) -> html.Tr:
    quote = reading.quote
    return html.Tr(
        [
            html.Td(label),
            html.Td(_fraction_pct(effective.value) if effective else _EM_DASH),
            _origin_cell(effective) if effective else html.Td(_EM_DASH),
            html.Td(
                f"{_fraction_pct(typed_iv)} ({_age_text(typed_age)})"
                if typed_iv is not None
                else _EM_DASH,
            ),
            html.Td(_contract_text(reading)),
            html.Td(_quote_text(reading)),
            html.Td(_spread_text(reading)),
            html.Td(_fraction_pct(quote.vendor_iv if quote else None)),
            html.Td(_fraction_pct(reading.solved_iv)),
            html.Td(_open_interest_text(reading)),
            html.Td(_flags_text(reading)),
        ],
    )


_HEADER = html.Tr(
    [
        html.Th("Leg"),
        html.Th("Priced IV"),
        html.Th("Origin"),
        html.Th("Your IV"),
        html.Th("Contract"),
        html.Th("Bid / ask (mid)"),
        html.Th("Spread"),
        html.Th("Vendor IV"),
        html.Th("IV at book r, q"),
        html.Th("Open interest"),
        html.Th("Flags"),
    ],
)

_RUNG_HEADER = html.Tr(
    [
        html.Th("Rung"),
        html.Th("Contract"),
        html.Th("Bid / ask (mid)"),
        html.Th("Spread"),
        html.Th("Vendor IV"),
        html.Th("IV at book r, q"),
        html.Th("Open interest"),
        html.Th("Flags"),
    ],
)


def _rung_row(reading: ChainReading) -> html.Tr:
    quote = reading.quote
    return html.Tr(
        [
            html.Td(reading.label),
            html.Td(_contract_text(reading)),
            html.Td(_quote_text(reading)),
            html.Td(_spread_text(reading)),
            html.Td(_fraction_pct(quote.vendor_iv if quote else None)),
            html.Td(_fraction_pct(reading.solved_iv)),
            html.Td(_open_interest_text(reading)),
            html.Td(_flags_text(reading)),
        ],
    )


def _leg_label(state: ProgramState, index: int) -> str:
    option = state.portfolio.positions[index].option
    return (
        f"{option.option_type.value} {option.strike_price:g} exp "
        f"{option.maturity_date:%Y-%m-%d}"
    )


def _rate_cells(
    provider: MarketDataProvider,
    feed: IpsPricingFeed,
) -> tuple[str, str]:
    """Return the fed rate's text and its provenance line."""
    try:
        observation = provider.get_rate(feed.rate_series)
    except MarketDataError:
        return _EM_DASH, f"no {feed.rate_series} reading cached yet"
    continuous = cmt_to_continuous(observation.value)
    as_of = (
        f"{observation.as_of:%Y-%m-%d}"
        if observation.as_of is not None
        else "undated"
    )
    provenance = (
        f"{feed.rate_series} {observation.value:.2f}% as published, "
        f"{as_of}, {observation.source.value}"
    )
    return f"{continuous * 100:.2f}% continuous", provenance


def _inputs_table(
    state: ProgramState,
    snapshot: ChainSnapshot | None,
    source: str,
    rate: tuple[str, str],
) -> html.Table:
    resolution = state.resolution
    entered = state.entered
    stamps = state.portfolio.stamps
    spot_age = _age_text(_stamp_age(state, stamps.spot_as_of))
    rate_age = _age_text(_stamp_age(state, stamps.risk_free_rate_as_of))
    yield_age = _age_text(_stamp_age(state, stamps.dividend_yield_as_of))
    rate_pct = resolution.risk_free_rate.value * 100
    yield_pct = resolution.dividend_yield.value * 100
    spot_feed = (
        f"{_money(snapshot.spot)} (chain, {snapshot.session_date:%Y-%m-%d} "
        f"close, {source})"
        if snapshot is not None
        else _EM_DASH
    )
    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Input"),
                        html.Th("Priced on"),
                        html.Th("Origin"),
                        html.Th("Your value"),
                        html.Th("Feed now"),
                    ],
                ),
            ),
            html.Tbody(
                [
                    html.Tr(
                        [
                            html.Td("Index level (spot)"),
                            html.Td(_money(resolution.spot.value)),
                            _origin_cell(resolution.spot),
                            html.Td(f"{_money(entered.spot)} ({spot_age})"),
                            html.Td(spot_feed),
                        ],
                    ),
                    html.Tr(
                        [
                            html.Td("Risk-free rate"),
                            html.Td(f"{rate_pct:.2f}%"),
                            _origin_cell(resolution.risk_free_rate),
                            html.Td(
                                f"{entered.risk_free_rate * 100:.2f}% "
                                f"({rate_age})",
                            ),
                            html.Td(f"{rate[0]} — {rate[1]}"),
                        ],
                    ),
                    html.Tr(
                        [
                            html.Td("Dividend yield"),
                            html.Td(f"{yield_pct:.2f}%"),
                            _origin_cell(resolution.dividend_yield),
                            html.Td(
                                f"{entered.dividend_yield * 100:.2f}% "
                                f"({yield_age})",
                            ),
                            html.Td(_DIVIDEND_NOTE),
                        ],
                    ),
                ],
            ),
        ],
        className="planning-table",
    )


def _notes(
    state: ProgramState,
    ips_config: IpsConfig,
    market_data: MarketDataProvider,
) -> list[Component]:
    """Build the restart notice, the newer-chain note, any resolver fault."""
    resolution = state.resolution
    notes: list[Component] = []
    if resolution.adopting:
        notes.append(
            html.P(
                priced_notice(resolution.resolved_at, resolution.session_date),
                className="env-verdict",
            ),
        )
        newer = newer_cached_session(market_data, ips_config, resolution)
        if newer is not None:
            notes.append(
                html.P(
                    f"A newer chain is cached (the {newer} session). The "
                    "book is not priced on it: restart the app to price on "
                    "it. The Feed now figures below are from the cache.",
                    className="env-verdict env-verdict--warn",
                ),
            )
    if resolution.error is not None:
        notes.append(
            html.P(
                "The pricing inputs could not be resolved "
                f"({resolution.error}); the book is priced on your typed "
                "values.",
                className="env-verdict env-verdict--warn",
            ),
        )
    return notes


def _panel_view(
    state: ProgramState,
    ips_config: IpsConfig,
    market_data: MarketDataProvider,
) -> Component:
    feed = ips_config.pricing_feed
    if feed is None:
        return html.Div([html.P(_NO_FEED, className="plain-language")])
    body: list[Component] = [
        html.P(_EXPLANATION, className="plain-language"),
        html.P(_adopt_text(feed), className="plain-language"),
        *_notes(state, ips_config, market_data),
    ]
    chain = read_fetched_chain(market_data, ips_config)
    snapshot = chain.observation.value if chain.observation else None
    source = chain.observation.source.value if chain.observation else ""
    if snapshot is None:
        body.append(html.P(chain.note, className="env-verdict"))
    else:
        body.append(
            html.P(
                f"Chain generated {snapshot.quoted_at:%Y-%m-%d %H:%M} UTC; "
                f"quotes are the {snapshot.session_date:%Y-%m-%d} close "
                f"({source}); a quote older than {feed.max_quote_age_days} "
                f"days is flagged STALE-QUOTE, one wider than "
                f"{feed.max_spread_pct:g}% of mid WIDE.",
                className="env-verdict",
            ),
        )
    body.append(
        _inputs_table(state, snapshot, source, _rate_cells(market_data, feed)),
    )
    if snapshot is None:
        return html.Div(body)
    portfolio = state.portfolio
    program_date = program_trading_date(ips_config.program.timezone).date()
    held = read_positions(snapshot, portfolio, feed, program_date=program_date)
    entered = state.entered
    if held:
        body.append(html.H4("Held options"))
        rows = []
        for index, (position_id, reading) in enumerate(held.items()):
            position = portfolio.positions[index]
            rows.append(
                _reading_row(
                    _leg_label(state, index),
                    reading,
                    effective=state.resolution.legs.get(position_id),
                    typed_iv=entered.leg_vols.get(position_id),
                    typed_age=_stamp_age(state, position.volatility_as_of),
                ),
            )
        body.append(
            html.Table(
                [html.Thead(_HEADER), html.Tbody(rows)],
                className="planning-table",
            ),
        )
    else:
        body.append(html.P("No legs in the book.", className="env-verdict"))
    rungs = rung_readings(
        snapshot,
        ips_config,
        feed,
        risk_free_rate=portfolio.risk_free_rate,
        dividend_yield=portfolio.dividend_yield,
        program_date=program_date,
    )
    if rungs:
        body.append(html.H4("strike_ladder rungs (candidates, not held)"))
        body.append(
            html.Table(
                [
                    html.Thead(_RUNG_HEADER),
                    html.Tbody([_rung_row(reading) for reading in rungs]),
                ],
                className="planning-table",
            ),
        )
    return html.Div(body)


def _render_panel_logic(
    *,
    state: ProgramState,
    ips_config: IpsConfig,
    market_data: MarketDataProvider,
) -> Component:
    """Render the Pricing inputs tables for the current book."""
    return _safe_render(
        lambda: _panel_view(state, ips_config, market_data),
    )


# ── The controls: override, clear, dividend yield — review then confirm ────


def target_options(state: ProgramState) -> list[dict[str, str]]:
    """List what can be overridden or edited: spot, the yield, each IV."""
    options = [
        {"label": "Spot price", "value": io.TARGET_SPOT},
        {"label": "Dividend yield", "value": io.TARGET_DIVIDEND},
    ]
    for index, position in enumerate(state.portfolio.positions):
        options.append(
            {
                "label": f"IV: {_leg_label(state, index)}",
                "value": f"iv:{position.position_id}",
            },
        )
    return options


def _review_children(review: io.Review) -> Component:
    parts: list[Component] = [html.P(review.summary, className="env-verdict")]
    parts.append(html.Ul([html.Li(line) for line in review.lines]))
    parts.extend(
        html.P(f"⚠ {warning}", className="field-hint trade-warning")
        for warning in review.warnings
    )
    return html.Div(parts)


def review_override(
    raw: dict[str, Any],
    state: ProgramState,
) -> tuple[Any, bool, Component | list[Any], Component]:
    """Validate the form and say what confirming would do. Writes nothing.

    Directly callable from tests, like the BOOK zone's other ``_..._logic``
    functions.

    Returns:
        ``(pending, confirm_row_hidden, review_text, status)``: the raw
        values to replay on confirm (``None`` when refused), whether the
        confirm row stays hidden, the review text, and a status line.

    """
    try:
        entry = io.parse_entry(raw, state)
        review = io.review_entry(entry, state)
    except io.InputEntryError as exc:
        return None, True, [], _status(str(exc), error=True)
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Unexpected error reviewing a pricing-input change")
        return None, True, [], _status(_UNEXPECTED, error=True)
    return (
        dict(raw),
        False,
        _review_children(review),
        _status("Review the change below, then confirm it.", error=False),
    )


def confirm_override(
    pending: dict[str, Any] | None,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component, bool]:
    """Record the reviewed change.

    Returns:
        ``(book_version, status, recorded)``. The version is ``no_update``
        unless it was recorded: a refused write never bumps it.

    """
    if not pending:
        return (
            no_update,
            _status("Review the change first, then confirm it.", error=True),
            False,
        )
    said: list[str] = []

    def _record() -> None:
        entry = io.parse_entry(pending, state)
        said.append(io.review_entry(entry, state).summary)
        io.record_entry(entry, state)

    error = _guarded_mutation(_record)
    if error is not None:
        return no_update, _status(error, error=True), False
    return version + 1, _status(f"Done: {said[0]}", error=False), True


def _controls() -> html.Div:
    """Build the override / clear / dividend form: a skeleton, no data."""
    return html.Div(
        [
            html.H4("Override a number, or edit the dividend yield"),
            html.P(
                "An override prices the book on your value until you clear "
                "it, and is listed on /monitor and in the digest so it is "
                "not forgotten. Review shows exactly what confirming will "
                "do; nothing is written until you confirm.",
                className="plain-language",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Input"),
                            dcc.Dropdown(
                                id=_TARGET,
                                options=[],
                                placeholder="Spot, the yield, or an IV",
                                clearable=False,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Action"),
                            dcc.RadioItems(
                                id=_ACTION,
                                options=[
                                    {
                                        "label": "Set my value",
                                        "value": "set",
                                    },
                                    {
                                        "label": "Clear my override",
                                        "value": "clear",
                                    },
                                ],
                                value="set",
                                inline=True,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Value (spot level; IV and yield in %)"),
                            dcc.Input(id=_VALUE, type="text", debounce=False),
                        ],
                        className="editor-field",
                    ),
                    html.Button("Review", id=_REVIEW_BUTTON, n_clicks=0),
                ],
                className="editor-row",
            ),
            html.Div(id=_REVIEW_TEXT),
            html.Div(
                [
                    html.Button("Confirm", id=_CONFIRM_BUTTON, n_clicks=0),
                    html.Button(
                        "Cancel",
                        id=_CANCEL_BUTTON,
                        n_clicks=0,
                    ),
                ],
                id=_CONFIRM_ROW,
                hidden=True,
            ),
            dcc.Store(id=_PENDING, data=None),
        ],
        className="pricing-controls",
    )


def layout(
    *,
    state: ProgramState,
    ips_config: IpsConfig,
    market_data: MarketDataProvider,
) -> html.Div:
    """Build the panel: heading, the guarded tables, then the controls."""
    return html.Div(
        [
            html.H3(SECTION.title, id=SECTION.anchor_id),
            html.Div(
                _render_panel_logic(
                    state=state,
                    ips_config=ips_config,
                    market_data=market_data,
                ),
                id=_PANEL_ID,
            ),
            _controls() if ips_config.pricing_feed is not None else html.Div(),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the panel's callbacks: re-render, options, review, confirm."""

    @app.callback(
        Output(_PANEL_ID, "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_panel(_version: int) -> Component:
        return _render_panel_logic(
            state=app.program_state,
            ips_config=ips_config,
            market_data=app.market_data,
        )

    if ips_config.pricing_feed is None:
        return

    @app.callback(
        Output(_TARGET, "options"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _refresh_targets(_version: int) -> list[dict[str, str]]:
        return target_options(app.program_state)

    @app.callback(
        Output(_PENDING, "data"),
        Output(_CONFIRM_ROW, "hidden"),
        Output(_REVIEW_TEXT, "children"),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Input(_REVIEW_BUTTON, "n_clicks"),
        State(_TARGET, "value"),
        State(_ACTION, "value"),
        State(_VALUE, "value"),
        prevent_initial_call=True,
    )
    def _review(
        n_clicks: int | None,
        target: str | None,
        action: str | None,
        value: str | None,
    ) -> tuple[Any, ...]:
        if not n_clicks:
            return no_update, no_update, no_update, no_update
        return review_override(
            {"target": target, "action": action, "value": value},
            app.program_state,
        )

    @app.callback(
        Output(BOOK_VERSION_STORE, "data", allow_duplicate=True),
        Output(MUTATION_STATUS, "children", allow_duplicate=True),
        Output(_PENDING, "data", allow_duplicate=True),
        Output(_CONFIRM_ROW, "hidden", allow_duplicate=True),
        Output(_REVIEW_TEXT, "children", allow_duplicate=True),
        Input(_CONFIRM_BUTTON, "n_clicks"),
        State(_PENDING, "data"),
        State(BOOK_VERSION_STORE, "data"),
        prevent_initial_call=True,
    )
    def _confirm(
        n_clicks: int | None,
        pending: dict[str, Any] | None,
        version: int,
    ) -> tuple[Any, ...]:
        if not n_clicks:
            return (no_update,) * 5
        new_version, status, recorded = confirm_override(
            pending,
            version,
            app.program_state,
        )
        if not recorded:
            return new_version, status, no_update, no_update, no_update
        return new_version, status, None, True, []

    @app.callback(
        Output(_PENDING, "data", allow_duplicate=True),
        Output(_CONFIRM_ROW, "hidden", allow_duplicate=True),
        Output(_REVIEW_TEXT, "children", allow_duplicate=True),
        Input(_CANCEL_BUTTON, "n_clicks"),
        prevent_initial_call=True,
    )
    def _cancel(n_clicks: int | None) -> tuple[Any, ...]:
        if not n_clicks:
            return no_update, no_update, no_update
        return None, True, []
