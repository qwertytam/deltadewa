"""PLANNING zone: the Fetched inputs panel (9b).

Read-only. Shows what the nightly refresh cached from Cboe's delayed SPX
option chain and FRED, beside the values the book is priced on:

- the index level and the risk-free rate, fetched against typed;
- the dividend yield, which is **never** fetched: put-call parity cannot
  isolate it from funding and timing (9b.0), so it stays hand-entered;
- for each held option and each ``strike_ladder`` rung in ``ips.yaml``: the
  contract it matched, its close bid and ask, the vendor's IV, and the IV
  solved from the mid at the **book's own** rate and dividend yield.

Nothing here prices anything. The panel exists so the feed can be judged
(does every leg match? are the spreads sane? how far is each vendor IV from
the one the program's own engine solves?) before any input is adopted. With
no ``pricing_feed:`` section the panel says nothing is fetched and shows
nothing else.

No basis chip: nothing here is priced.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, html

from deltadewa.analysis.chain_quotes import (
    ChainReading,
    read_fetched_chain,
    read_positions,
    rung_readings,
)
from deltadewa.analysis.implied_vol import cmt_to_continuous
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec
from deltadewa.clock import program_trading_date
from deltadewa.marketdata import MarketDataError

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig, IpsPricingFeed
    from deltadewa.marketdata import MarketDataProvider
    from deltadewa.marketdata.chain import ChainSnapshot
    from deltadewa.portfolio.core import OptionPortfolio

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-fetched-inputs",
    title="Fetched inputs",
)

_PANEL_ID = "plan-fetched-inputs-panel"

_EXPLANATION = (
    "What the nightly refresh cached from Cboe's delayed SPX option chain "
    "and FRED, beside what the book is priced on. Nothing here prices "
    'anything. "IV at book r, q" is solved from the close mid with the '
    "program's own European engine at the book's rate and dividend yield, "
    "so it reprices the mid exactly; Cboe's IV is solved at Cboe's own "
    "rate and dividend, and differs from it by roughly half a vol point "
    "per point of rate or yield. The two are a pair with their rate and "
    "yield, never mixed."
)

_DIVIDEND_NOTE = (
    "Not fetched: put-call parity measures the dividend, funding and "
    "timing together and cannot isolate the yield. It stays hand-entered "
    "and is confirmed quarterly."
)

_NO_FEED = (
    "ips.yaml has no pricing_feed section, so nothing is fetched and every "
    "pricing input is hand-entered. Add the section (see "
    "config/ips.example.yaml) to start the nightly fetch."
)

_EM_DASH = "—"


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _fraction_pct(value: float | None) -> str:
    return _EM_DASH if value is None else f"{value * 100:.2f}%"


def _adopt_text(feed: IpsPricingFeed) -> str:
    named = ", ".join(feed.adopt) if feed.adopt else "nothing"
    return (
        f"Policy adopt: {named}. Nothing is priced on the feed in this "
        "build, so this is recorded, not applied."
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


def _reading_row(
    label: str,
    reading: ChainReading,
    typed_iv: float | None,
) -> html.Tr:
    quote = reading.quote
    return html.Tr(
        [
            html.Td(label),
            html.Td(_contract_text(reading)),
            html.Td(_quote_text(reading)),
            html.Td(_spread_text(reading)),
            html.Td(_fraction_pct(quote.vendor_iv if quote else None)),
            html.Td(_fraction_pct(reading.solved_iv)),
            html.Td(_fraction_pct(typed_iv)),
            html.Td(_open_interest_text(reading)),
            html.Td(_flags_text(reading)),
        ],
    )


_HEADER = html.Tr(
    [
        html.Th("Leg"),
        html.Th("Contract"),
        html.Th("Bid / ask (mid)"),
        html.Th("Spread"),
        html.Th("Cboe IV"),
        html.Th("IV at book r, q"),
        html.Th("Typed IV"),
        html.Th("Open interest"),
        html.Th("Flags"),
    ],
)


def _leg_label(index: int, portfolio: OptionPortfolio) -> str:
    option = portfolio.positions[index].option
    return (
        f"{option.option_type.value} {option.strike_price:g} exp "
        f"{option.maturity_date:%Y-%m-%d}"
    )


def _rate_cells(
    provider: MarketDataProvider,
    feed: IpsPricingFeed,
) -> tuple[str, str]:
    """Return the fetched rate's text and its provenance line."""
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
    portfolio: OptionPortfolio,
    snapshot: ChainSnapshot,
    source: str,
    rate: tuple[str, str],
) -> html.Table:
    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Input"),
                        html.Th("Typed (the book)"),
                        html.Th("Fetched"),
                        html.Th("Source"),
                    ],
                ),
            ),
            html.Tbody(
                [
                    html.Tr(
                        [
                            html.Td("Index level (spot)"),
                            html.Td(_money(portfolio.spot_price)),
                            html.Td(_money(snapshot.spot)),
                            html.Td(
                                f"chain, {snapshot.session_date:%Y-%m-%d} "
                                f"close, {source}",
                            ),
                        ],
                    ),
                    html.Tr(
                        [
                            html.Td("Risk-free rate"),
                            html.Td(
                                f"{portfolio.risk_free_rate * 100:.2f}%",
                            ),
                            html.Td(rate[0]),
                            html.Td(rate[1]),
                        ],
                    ),
                    html.Tr(
                        [
                            html.Td("Dividend yield"),
                            html.Td(
                                f"{portfolio.dividend_yield * 100:.2f}%",
                            ),
                            html.Td(_EM_DASH),
                            html.Td(_DIVIDEND_NOTE),
                        ],
                    ),
                ],
            ),
        ],
        className="planning-table",
    )


def _panel_view(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    market_data: MarketDataProvider,
) -> Component:
    feed = ips_config.pricing_feed
    if feed is None:
        return html.Div([html.P(_NO_FEED, className="plain-language")])
    body: list[Component] = [
        html.P(_EXPLANATION, className="plain-language"),
        html.P(_adopt_text(feed), className="plain-language"),
    ]
    chain = read_fetched_chain(market_data, ips_config)
    if chain.observation is None:
        body.append(html.P(chain.note, className="env-verdict"))
        return html.Div(body)
    snapshot = chain.observation.value
    program_date = program_trading_date(ips_config.program.timezone).date()
    body.append(
        html.P(
            f"Chain generated {snapshot.quoted_at:%Y-%m-%d %H:%M} UTC; "
            f"quotes are the {snapshot.session_date:%Y-%m-%d} close "
            f"({chain.observation.source.value}); a quote older than "
            f"{feed.max_quote_age_days} days is flagged STALE-QUOTE, one "
            f"wider than {feed.max_spread_pct:g}% of mid WIDE.",
            className="env-verdict",
        ),
    )
    body.append(
        _inputs_table(
            portfolio,
            snapshot,
            chain.observation.source.value,
            _rate_cells(market_data, feed),
        ),
    )
    held = read_positions(snapshot, portfolio, feed, program_date=program_date)
    if held:
        body.append(html.H4("Held options"))
        body.append(
            html.Table(
                [
                    html.Thead(_HEADER),
                    html.Tbody(
                        [
                            _reading_row(
                                _leg_label(index, portfolio),
                                reading,
                                portfolio.positions[index].option.volatility,
                            )
                            for index, reading in enumerate(held.values())
                        ],
                    ),
                ],
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
                    html.Thead(_HEADER),
                    html.Tbody(
                        [
                            _reading_row(reading.label, reading, None)
                            for reading in rungs
                        ],
                    ),
                ],
                className="planning-table",
            ),
        )
    return html.Div(body)


def _render_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    market_data: MarketDataProvider,
) -> Component:
    """Render the Fetched inputs panel for the current book."""
    return _safe_render(
        lambda: _panel_view(portfolio, ips_config, market_data),
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    market_data: MarketDataProvider,
) -> html.Div:
    """Build the panel: heading, then the guarded body."""
    return html.Div(
        [
            html.H3(SECTION.title, id=SECTION.anchor_id),
            html.Div(
                _render_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                    market_data=market_data,
                ),
                id=_PANEL_ID,
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the panel's one callback: re-render when the book changes."""

    @app.callback(
        Output(_PANEL_ID, "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_panel(_version: int) -> Component:
        return _render_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            market_data=app.market_data,
        )
