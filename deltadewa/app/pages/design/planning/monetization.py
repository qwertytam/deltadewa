"""PLANNING zone: the Monetization panel.

The market-environment snapshot (``market_env``) is a parameter, not
computed here — see ``market_env.py``'s module docstring for the
shared-snapshot invariant this panel is the other half of.

``basis_crash_skew`` is a parameter, not a module constant: every
PLANNING panel that prices the IPS crash shares this basis chip text,
so the string lives in ``page.py`` and is passed down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import Input, Output, html

from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.analysis.monetization import build_monetization_plan
from deltadewa.app import format as fmt
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import safe_render as _safe_render

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.analysis.monetization import (
        MonetizationPlan,
        MonetizationStepStatus,
    )
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio


def _monetization_step_row(step: MonetizationStepStatus) -> html.Tr:
    """One row of the IPS monetization schedule."""
    return html.Tr(
        [
            html.Td(fmt.percent(step.gain_pct)),
            html.Td(fmt.percent(step.sell_pct)),
            html.Td("triggered" if step.triggered else "not yet"),
            html.Td(fmt.compact_currency(step.cumulative_sell_value)),
        ],
    )


def _monetization_panel_view(plan: MonetizationPlan) -> Component:
    """Render the full IPS monetization schedule at the current mark.

    Unlike /monitor's one-sentence summary, shows every schedule step —
    now meaningful for a hand-entered book once B0 gave entry_premium a
    write path.
    """
    children: list[Component]
    if plan.gain_basis == "unknown":
        children = [
            html.P(
                "No entry price is recorded for the protective puts, so "
                "hedge gain — and this monetization schedule — can't be "
                "evaluated.",
                className="plain-language",
            ),
        ]
    else:
        gain_text = (
            fmt.percent(plan.current_gain_pct)
            if plan.current_gain_pct is not None
            else "n/a"
        )
        header = html.Tr(
            [
                html.Th("Gain trigger"),
                html.Th("Sell %"),
                html.Th("Status"),
                # #327: explicit about granularity, per the issue -- a
                # marginal (this-step-alone) figure sitting next to a
                # cumulative summary line below would invite misreading.
                html.Th("Cumulative value"),
            ],
        )
        rows = [_monetization_step_row(step) for step in plan.steps]
        children = [
            html.P(
                f"Current hedge gain: {gain_text}.",
                className="plain-language",
            ),
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="planning-table",
            ),
            html.P(
                "Recommended cumulative sell: "
                f"{fmt.percent(plan.recommended_cumulative_sell_pct)} "
                f"({fmt.compact_currency(plan.value_to_harvest)} to "
                "harvest) — "
                f"{fmt.percent(plan.remaining_sell_capacity)} remaining "
                "sell capacity in the schedule.",
            ),
        ]
    if plan.vol_spike_context is not None:
        children.append(
            html.P(plan.vol_spike_context, className="vol-spike-context"),
        )
    return html.Div(children)


def _render_monetization_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    market_env: MarketEnvironment | None,
) -> Component:
    """Render the monetization panel at the current mark."""
    return _safe_render(
        lambda: _monetization_panel_view(
            build_monetization_plan(
                portfolio,
                ips_config,
                market_env=market_env,
            ),
        ),
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    market_env: MarketEnvironment | None,
    basis_crash_skew: str,
) -> html.Div:
    """Build the Monetization panel."""
    return html.Div(
        [
            html.H3(["Monetization", basis_chip(basis_crash_skew)]),
            html.Div(
                _render_monetization_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                    market_env=market_env,
                ),
                id="plan-monetization-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Monetization panel's re-render callback."""

    @app.callback(
        Output("plan-monetization-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_monetization_panel(_version: int) -> Component:
        return _render_monetization_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            market_env=assess_market_environment(
                app.market_data,
                ips_config.market_environment,
            ),
        )
