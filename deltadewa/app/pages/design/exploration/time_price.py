"""EXPLORATION zone: the Time x Price heatmap panel.

``basis_proportional`` is a parameter, not a module constant: the zone
heading and three of its five panels (this one, ``spot_vol``,
``monte_carlo``) share this basis chip text, so the string lives in
``page.py`` and is passed down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import Input, Output, dcc, html

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.stress import (
    build_time_price_grid_spec,
    days_to_max_maturity,
)
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import incomplete_notice as _incomplete
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.visualization.stress_charts_plotly import plot_time_price_heatmap

from ..book import BOOK_VERSION_STORE
from ..dials import _EXPLORATION_EMPTY_BOOK_MSG, _METRIC_OPTIONS

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.cache import ScenarioGridCache
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.portfolio.core import OptionPortfolio

_DEFAULT_TIME_SPOT_PCT = 50.0
_DEFAULT_TIME_STEPS = 10
_DEFAULT_PRICE_STEPS = 13
_DEFAULT_TIME_METRIC = "pnl"


def _render_time_price_panel_logic(
    *,
    portfolio: OptionPortfolio,
    cache: ScenarioGridCache,
    spot_pct: float | None,
    num_time_steps: float | None,
    num_price_steps: float | None,
    metric: str | None,
) -> Component:
    """Render the time x price stress heatmap for the current dials.

    ``spot_pct`` is collected as a percent and divided by 100 here — the
    same F5/B0 seam :func:`_render_spot_vol_panel_logic` uses.
    """
    if not portfolio.positions:
        return _incomplete(_EXPLORATION_EMPTY_BOOK_MSG)
    if (
        spot_pct is None
        or num_time_steps is None
        or num_price_steps is None
        or metric is None
    ):
        return _incomplete("All time/price dials are required.")

    def _build() -> Component:
        max_days = days_to_max_maturity(portfolio)
        grid_spec = build_time_price_grid_spec(
            spot_range_pct=spot_pct / 100.0,
            num_time_steps=int(num_time_steps),
            num_price_steps=int(num_price_steps),
            original_spot=portfolio.spot_price,
            original_date=portfolio.valuation_date,
            max_days_to_maturity=max_days,
        )
        analyzer = PortfolioAnalyzer(portfolio)
        result_df = cache.get_or_calculate(
            portfolio,
            analyzer,
            grid_spec.spot_scenarios,
            grid_spec.time_points,
            metric,
            baseline_spot=portfolio.spot_price,
            baseline_valuation_date=portfolio.valuation_date,
        )
        fig = plot_time_price_heatmap(
            result_df,
            original_spot=portfolio.spot_price,
            original_date=portfolio.valuation_date,
            metric=metric,
        )
        return dcc.Graph(figure=fig)

    return _safe_render(_build)


def layout(
    *,
    portfolio: OptionPortfolio,
    cache: ScenarioGridCache,
    basis_proportional: str,
) -> html.Div:
    """Build the Time x Price heatmap panel."""
    return html.Div(
        [
            html.H3(
                [
                    "Time x price heatmap",
                    basis_chip(basis_proportional),
                ],
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Spot range (%)"),
                            dcc.Input(
                                id="explore-time-spot-pct",
                                type="number",
                                value=_DEFAULT_TIME_SPOT_PCT,
                                debounce=True,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Metric"),
                            dcc.Dropdown(
                                id="explore-time-metric",
                                options=_METRIC_OPTIONS,
                                value=_DEFAULT_TIME_METRIC,
                                clearable=False,
                            ),
                        ],
                        className="editor-field",
                    ),
                ],
                className="editor-form",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Time steps"),
                            dcc.Slider(
                                id="explore-time-steps",
                                min=5,
                                max=20,
                                step=1,
                                value=_DEFAULT_TIME_STEPS,
                                marks=None,
                                updatemode="mouseup",
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
                            html.Label("Price steps"),
                            dcc.Slider(
                                id="explore-price-steps",
                                min=5,
                                max=19,
                                step=2,
                                value=_DEFAULT_PRICE_STEPS,
                                marks=None,
                                updatemode="mouseup",
                                tooltip={
                                    "placement": "bottom",
                                    "always_visible": True,
                                },
                            ),
                        ],
                        className="dial",
                    ),
                ],
                # #328: see spot_vol.py's matching comment — both dials
                # need .dial-row's stacking context or the tooltip paints
                # underneath the graph card below.
                className="dial-row",
            ),
            dcc.Loading(
                html.Div(
                    _render_time_price_panel_logic(
                        portfolio=portfolio,
                        cache=cache,
                        spot_pct=_DEFAULT_TIME_SPOT_PCT,
                        num_time_steps=_DEFAULT_TIME_STEPS,
                        num_price_steps=_DEFAULT_PRICE_STEPS,
                        metric=_DEFAULT_TIME_METRIC,
                    ),
                    id="explore-time-panel",
                ),
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp) -> None:
    """Wire the Time x Price heatmap panel's re-render callback."""

    @app.callback(
        Output("explore-time-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
        Input("explore-time-spot-pct", "value"),
        Input("explore-time-steps", "value"),
        Input("explore-price-steps", "value"),
        Input("explore-time-metric", "value"),
    )
    def _render_time_price_panel(
        _version: int,
        spot_pct: float | None,
        num_time_steps: float | None,
        num_price_steps: float | None,
        metric: str | None,
    ) -> Component:
        return _render_time_price_panel_logic(
            portfolio=app.program_state.portfolio,
            cache=app.scenario_cache,
            spot_pct=spot_pct,
            num_time_steps=num_time_steps,
            num_price_steps=num_price_steps,
            metric=metric,
        )
