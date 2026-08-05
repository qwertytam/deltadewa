"""The `/monitor` page: crash-led headline, decisions, position detail.

Read-mostly book review for the non-technical partner (see
``docs/implementation-plan.md`` M2.4). Layout is built once per request
in :func:`render`, at the default dial values; the scenario explorer's
three dials only *update* it afterward, via :func:`register_callbacks`.
No arithmetic happens in this module — every number comes from
``analysis/`` (``monitor_scenario.build_scenario``,
``monitor_scenario.build_scenario_curve``, ``roll_status.evaluate_roll_status``,
``monetization.build_monetization_plan``) and is only formatted here
(``app.format``) or handed to a chart builder
(``visualization.crash_charts_plotly``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import Input, Output, Patch, dcc, html
from dash.development.base_component import Component

from deltadewa.analysis.crash_repricing import hedge_value
from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.analysis.monetization import build_monetization_plan
from deltadewa.analysis.monitor_scenario import (
    build_scenario,
    build_scenario_curve,
)
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.app import format as fmt
from deltadewa.app.bands import band_bar
from deltadewa.app.basis_chip import basis_chip
from deltadewa.visualization.crash_charts_plotly import plot_scenario_curve

if TYPE_CHECKING:
    from deltadewa.analysis.monetization import MonetizationPlan
    from deltadewa.analysis.monitor_scenario import ScenarioResult
    from deltadewa.analysis.roll_status import RollStatusRecord
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

_SPOT_SLIDER_MIN = -50.0
_SPOT_SLIDER_MAX = 10.0
_VOL_SLIDER_MIN = 0.0
_VOL_SLIDER_MAX = 0.30


def _no_ips_layout() -> html.Div:
    """Build the single "no IPS policy loaded" state for the /monitor page."""
    return html.Div(
        [
            html.H1("Monitor"),
            html.P(
                "No IPS policy is loaded, so there is no crash anchor to "
                "render this page around. Check that config/ips.yaml (or "
                "whatever path this program state was loaded with) exists "
                "and parses — see the server log at startup for the "
                "reason it was skipped.",
                className="no-ips-message",
            ),
        ],
        className="page page-monitor",
    )


def _scenario_numbers(result: ScenarioResult) -> list[Component]:
    """Build the scenario-numbers children.

    Shows hedge value (shocked), hedge gain, underlying loss, net, and
    the offset ratio.
    """
    offset_text = (
        f"{result.offset_ratio:.2f}x"
        if result.offset_ratio is not None
        else "n/a"
    )
    return [
        html.Div(
            [
                html.Span(
                    "Hedge value (shocked)",
                    className="big-number-label",
                ),
                html.Span(
                    fmt.compact_currency(result.hedge_value_shocked),
                    id="hedge-value-shocked",
                    title=fmt.currency(
                        result.hedge_value_shocked,
                        decimals=2,
                    ),
                    className="big-number",
                ),
            ],
            className="scenario-figure",
        ),
        html.Div(
            [
                html.Span("Hedge gain", className="big-number-label"),
                html.Span(
                    fmt.signed_compact_currency(result.hedge_gain),
                    title=fmt.signed_currency(result.hedge_gain),
                    className="big-number",
                ),
            ],
            className="scenario-figure",
        ),
        html.Div(
            [
                html.Span("Underlying loss", className="big-number-label"),
                html.Span(
                    fmt.signed_compact_currency(result.underlying_loss),
                    title=fmt.signed_currency(result.underlying_loss),
                    className="big-number",
                ),
            ],
            className="scenario-figure",
        ),
        html.Div(
            [
                html.Span("Net", className="big-number-label"),
                html.Span(
                    fmt.signed_compact_currency(result.net),
                    title=fmt.signed_currency(result.net),
                    className="big-number",
                ),
            ],
            className="scenario-figure",
        ),
        html.Div(
            [
                html.Span(
                    "Offset ratio",
                    className="big-number-label",
                    title=(
                        "Hedge dollars gained per dollar of underlying loss"
                    ),
                ),
                html.Span(offset_text, className="big-number"),
            ],
            className="scenario-figure",
        ),
    ]


def _cost_panel(
    result: ScenarioResult,
    ips_config: IpsConfig,
) -> list[Component]:
    """Build the cost-panel children: carry % of notional vs. IPS budget."""
    budget_pct = ips_config.budget.annual_carry_pct
    verdict = "within budget" if result.carry.within_budget else "over budget"
    verdict_class = "within" if result.carry.within_budget else "over"
    return [
        html.Div(
            [
                html.Span(
                    "Annual carry (theta)",
                    className="big-number-label",
                    title=(
                        "Theta: the option book's daily time-decay cost, "
                        "annualized"
                    ),
                ),
                html.Span(
                    fmt.signed_compact_currency(result.carry.theta_annual),
                    id="carry-theta-annual",
                    title=fmt.signed_currency(result.carry.theta_annual),
                    className="big-number",
                ),
            ],
        ),
        html.Div(
            [
                html.Span("Carry", className="big-number-label"),
                html.Span(
                    fmt.percent(result.carry.carry_pct_of_notional),
                    className="big-number",
                ),
                html.Span(
                    f" of notional vs {fmt.percent(budget_pct)} budget "
                    f"({verdict})",
                    className=f"cost-verdict cost-verdict--{verdict_class}",
                ),
                band_bar(
                    value=result.carry.carry_pct_of_notional,
                    low=0.0,
                    high=budget_pct,
                ),
            ],
        ),
        html.P(
            f"This {fmt.compact_currency(abs(result.carry.theta_annual))}"
            "/year carry cost doesn't change with the quantity dial — "
            "only the percentage of book (and the budget verdict) does, "
            "since a smaller book turns the same dollar cost into a "
            "bigger share.",
            className="plain-language",
        ),
    ]


def _headline_sentence(result: ScenarioResult) -> html.P:
    """Build the always-visible headline scenario sentence."""
    return html.P(
        f"A {fmt.signed_percent(result.spot_pct)} spot move with a "
        f"{result.vol_points:+.2f} vol-point shock nets "
        f"{fmt.signed_compact_currency(result.net)}: the hedge gains "
        f"{fmt.signed_compact_currency(result.hedge_gain)} against an "
        "underlying loss of "
        f"{fmt.signed_compact_currency(result.underlying_loss)} "
        f"on {result.quantity:,.0f} shares.",
        className="plain-language plain-language--headline",
    )


def _verdict_badge(record: RollStatusRecord) -> html.Span:
    """Build a colored verdict badge for one roll status record."""
    modifier = record.verdict.value.lower()
    return html.Span(
        record.verdict.value,
        className=f"verdict-badge verdict-badge--{modifier}",
    )


def _decisions_section(
    records: list[RollStatusRecord],
    plan: MonetizationPlan,
) -> html.Div:
    """Build the DECISIONS section: roll verdicts plus monetization."""
    roll_rows = [
        html.Div(
            [
                _verdict_badge(record),
                html.Span(
                    f"{record.position.option.option_type.value} "
                    f"{record.position.option.strike_price:,.0f} — "
                    f"{fmt.roll_verdict_reason(record)}",
                    className="decision-reason",
                ),
                band_bar(
                    value=record.crash_convexity_pct,
                    low=record.convexity_target_min_pct,
                    high=record.convexity_target_max_pct,
                ),
            ],
            className="decision-row",
        )
        for record in records
    ]

    if plan.gain_basis == "unknown":
        monetization_children: list[Component] = [
            html.P(
                "No entry price is recorded for the protective puts, so "
                "hedge gain — and this monetization schedule — can't be "
                "evaluated.",
            ),
        ]
    else:
        gain_text = (
            fmt.percent(plan.current_gain_pct)
            if plan.current_gain_pct is not None
            else "n/a"
        )
        monetization_children = [
            html.P(
                f"Current hedge gain: {gain_text} — recommended cumulative "
                f"sell: {fmt.percent(plan.recommended_cumulative_sell_pct)} "
                f"({fmt.compact_currency(plan.value_to_harvest)} to "
                "harvest — the dollar amount recommended to sell at this "
                "gain level).",
            ),
        ]
    if plan.vol_spike_context is not None:
        monetization_children.append(
            html.P(plan.vol_spike_context, className="vol-spike-context"),
        )

    return html.Div(
        [
            html.H2("Decisions"),
            html.P(
                "HOLD — no action needed. MONITOR — watching a metric "
                "approach its threshold. REVIEW — a trigger has fired. "
                "ROLL — time to replace this position.",
                className="verdict-legend",
            ),
            html.P(
                "Each position's roll verdict, and any monetization "
                "already recommended by the IPS schedule at the current "
                "mark.",
                className="plain-language",
            ),
            html.Div(roll_rows, className="decision-list"),
            html.Div(
                monetization_children,
                id="monetization-panel",
                className="monetization-panel",
            ),
        ],
        className="decisions-section",
    )


def _position_row(
    record: RollStatusRecord,
    portfolio: OptionPortfolio,
) -> html.Tr:
    """Build one <tr> of the position-detail table.

    The plain per-leg ledger — "what do I actually hold" — not a second
    copy of the DECISIONS section's risk narrative (verdict/reasons
    already live there).
    """
    position = record.position
    current_value = hedge_value(portfolio, positions=[position])
    return html.Tr(
        [
            html.Td(f"{position.option.strike_price:,.0f}"),
            html.Td(position.option.option_type.value),
            html.Td(position.option.maturity_date.strftime("%Y-%m-%d")),
            html.Td(f"{record.days_to_maturity}d"),
            html.Td(f"{position.quantity:,.0f}"),
            html.Td(
                fmt.signed_compact_currency(current_value),
                title=fmt.signed_currency(current_value),
            ),
        ],
    )


def _position_detail_table(
    records: list[RollStatusRecord],
    portfolio: OptionPortfolio,
) -> html.Details:
    """Build the collapsed position-detail table: the plain per-leg ledger."""
    header = html.Tr(
        [
            html.Th("Strike"),
            html.Th("Type"),
            html.Th("Expiry"),
            html.Th("DTE"),
            html.Th("Quantity"),
            html.Th("Current value"),
        ],
    )
    rows = [_position_row(record, portfolio) for record in records]
    return html.Details(
        [
            html.Summary("Position detail"),
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="position-detail-table",
            ),
        ],
        className="position-detail",
    )


def render(app: ProgramDashApp) -> html.Div:
    """Build the /monitor page: crash-led headline, decisions, position detail.

    Every policy-dependent panel needs ``app.ips_config`` — when it's
    ``None`` there is no crash anchor to render around, so the whole
    page becomes a single "no IPS policy loaded" state rather than
    fabricating one.
    """
    if app.ips_config is None:
        return _no_ips_layout()

    ips_config = app.ips_config
    convexity = ips_config.convexity
    portfolio = app.program_state.portfolio

    spot_pct = convexity.crash_scenario_pct
    vol_points = convexity.crash_vol_shock
    quantity = portfolio.underlying_quantity

    result = build_scenario(
        portfolio,
        ips_config,
        spot_pct=spot_pct,
        vol_points=vol_points,
        quantity=quantity,
    )
    curve = build_scenario_curve(
        portfolio,
        ips_config,
        vol_points=vol_points,
        quantity=quantity,
    )
    figure = plot_scenario_curve(
        curve,
        marker_pct=result.spot_pct,
        marker_hedge_value=result.hedge_value_shocked,
        ips_crash_pct=convexity.crash_scenario_pct,
    )

    records = evaluate_roll_status(portfolio, ips_config)
    market_env = assess_market_environment(
        app.market_data,
        ips_config.market_environment,
    )
    plan = build_monetization_plan(
        portfolio,
        ips_config,
        market_env=market_env,
    )

    scenario_explorer = html.Div(
        [
            html.H2(
                [
                    "Crash scenario",
                    basis_chip("basis: crash-skew (IPS anchor)"),
                ],
            ),
            html.P(
                f"Today's {portfolio.get_symbol()} spot: "
                f"{fmt.currency(portfolio.spot_price, decimals=2)} — the "
                "shocks below move from this reference point.",
                className="plain-language",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label(
                                "Spot shock",
                                title="How far SPX falls in this scenario",
                            ),
                            dcc.Slider(
                                id="spot-slider",
                                min=_SPOT_SLIDER_MIN,
                                max=_SPOT_SLIDER_MAX,
                                step=1.0,
                                value=spot_pct,
                                marks=None,
                                tooltip={
                                    "placement": "bottom",
                                    "always_visible": True,
                                },
                            ),
                        ],
                        className="dial",
                    ),
                    html.Div(
                        [
                            html.Label(
                                "Vol shock (points)",
                                title=(
                                    "Implied volatility increase applied "
                                    "in this scenario, in vol points"
                                ),
                            ),
                            dcc.Slider(
                                id="vol-slider",
                                min=_VOL_SLIDER_MIN,
                                max=_VOL_SLIDER_MAX,
                                step=0.01,
                                value=vol_points,
                                marks=None,
                                tooltip={
                                    "placement": "bottom",
                                    "always_visible": True,
                                },
                            ),
                        ],
                        className="dial",
                    ),
                    html.Div(
                        [
                            html.Label("Underlying quantity"),
                            dcc.Input(
                                id="qty-input",
                                type="number",
                                value=quantity,
                            ),
                        ],
                        className="dial",
                    ),
                    html.Button("Reset", id="reset-button", n_clicks=0),
                ],
                className="dial-row",
            ),
            dcc.Graph(id="payoff-curve", figure=figure),
            html.Div(
                _scenario_numbers(result),
                id="scenario-numbers",
                className="scenario-numbers",
            ),
            html.Div(
                _cost_panel(result, ips_config),
                id="cost-panel",
                className="cost-panel",
            ),
            _headline_sentence(result),
        ],
        className="scenario-explorer",
    )

    return html.Div(
        [
            html.H1("Monitor"),
            scenario_explorer,
            _decisions_section(records, plan),
            _position_detail_table(records, portfolio),
        ],
        className="page page-monitor",
    )


def register_callbacks(app: ProgramDashApp) -> None:
    """Wire the scenario explorer's three dials to the curve/numbers/cost panel.

    No ``ProgramState`` mutator is ever called here — every dial value
    is scenario-local. The quantity dial in particular never gets
    written back to ``portfolio.underlying_quantity``.
    """
    ips_config = app.ips_config
    if ips_config is None:
        return

    @app.callback(
        Output("payoff-curve", "figure"),
        Input("vol-slider", "value"),
        Input("qty-input", "value"),
        prevent_initial_call=True,
    )
    def _update_curve(vol_points: float, quantity: float) -> Patch:
        curve = build_scenario_curve(
            app.program_state.portfolio,
            ips_config,
            vol_points=vol_points,
            quantity=quantity,
        )

        patched = Patch()
        patched["data"][0]["y"] = [point.net for point in curve]
        patched["data"][1]["y"] = [point.hedge_value for point in curve]
        patched["data"][2]["y"] = [point.underlying_loss for point in curve]
        patched["data"][3]["y"] = [point.offset_ratio for point in curve]
        return patched

    @app.callback(
        Output("payoff-curve", "figure", allow_duplicate=True),
        Output("scenario-numbers", "children"),
        Output("cost-panel", "children"),
        Input("spot-slider", "value"),
        Input("vol-slider", "value"),
        Input("qty-input", "value"),
        prevent_initial_call=True,
    )
    def _update_scenario(
        spot_pct: float,
        vol_points: float,
        quantity: float,
    ) -> tuple[Patch, list[Component], list[Component]]:
        result = build_scenario(
            app.program_state.portfolio,
            ips_config,
            spot_pct=spot_pct,
            vol_points=vol_points,
            quantity=quantity,
        )

        patched = Patch()
        patched["data"][4]["x"] = [result.spot_pct]
        patched["data"][4]["y"] = [result.hedge_value_shocked]
        return (
            patched,
            _scenario_numbers(result),
            _cost_panel(result, ips_config),
        )

    @app.callback(
        Output("spot-slider", "value"),
        Output("vol-slider", "value"),
        Output("qty-input", "value"),
        Input("reset-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def _reset_dials(_n_clicks: int) -> tuple[float, float, float]:
        return (
            ips_config.convexity.crash_scenario_pct,
            ips_config.convexity.crash_vol_shock,
            app.program_state.portfolio.underlying_quantity,
        )
