"""EXPLORATION zone: the Spot x Vol heatmap panel.

``basis_proportional`` is a parameter, not a module constant: the zone
heading and three of its five panels (this one, ``time_price``,
``monte_carlo``) share this basis chip text, so the string lives in
``page.py`` and is passed down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, dcc, html

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.repricing import proportional_vol
from deltadewa.analysis.stress import (
    build_spot_vol_grid_spec,
    days_to_max_maturity,
)
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import incomplete_notice as _incomplete
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec
from deltadewa.visualization.stress_charts_plotly import (
    STRESS_BASELINE_NOTE,
    plot_spot_vol_heatmap,
)

from ..book import BOOK_VERSION_STORE
from ..dials import _EXPLORATION_EMPTY_BOOK_MSG, _METRIC_OPTIONS

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.cache import ScenarioGridCache
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.portfolio.core import OptionPortfolio

_DEFAULT_SPOTVOL_SPOT_PCT = 50.0
_DEFAULT_SPOTVOL_VOL_PCT = 50.0
_DEFAULT_SPOTVOL_RESOLUTION = 21  # matches the measured 21x21 grid (F4)
_DEFAULT_SPOTVOL_DAYS_FORWARD = 0
_DEFAULT_SPOTVOL_METRIC = "pnl"
_FALLBACK_MAX_DAYS = 90  # matches build_spot_vol_grid_spec's own default
# for an empty book, used only to bound the days-forward slider at layout
# time before any position has been added.

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-spot-vol",
    title="Spot x vol heatmap",
)


def _render_spot_vol_panel_logic(  # pylint: disable=too-many-arguments
    *,
    portfolio: OptionPortfolio,
    cache: ScenarioGridCache,
    spot_pct: float | None,
    vol_pct: float | None,
    resolution: float | None,
    days_forward: float | None,
    metric: str | None,
) -> Component:
    """Render the spot x vol stress heatmap for the current dials.

    ``spot_pct``/``vol_pct`` are collected as percents and divided by 100
    here — the F5/B0 percent-fraction seam. A value that still ends up
    out of range (e.g. 250%) reaches ``build_spot_vol_grid_spec`` as a
    fraction >= 1 and is rejected there with its own ``ValueError``,
    caught by :func:`_safe_render`.
    """
    if not portfolio.positions:
        return _incomplete(_EXPLORATION_EMPTY_BOOK_MSG)
    if (
        spot_pct is None
        or vol_pct is None
        or resolution is None
        or days_forward is None
        or metric is None
    ):
        return _incomplete("All spot/vol dials are required.")

    def _build() -> Component:
        grid_spec = build_spot_vol_grid_spec(
            portfolio,
            spot_shock_pct=spot_pct / 100.0,
            vol_shock_pct=vol_pct / 100.0,
            grid_resolution=int(resolution),
        )
        analyzer = PortfolioAnalyzer(portfolio)
        result_df = cache.get_or_calculate_spot_vol(
            portfolio,
            analyzer,
            grid_spec.spot_scenarios,
            grid_spec.vol_scenarios,
            vol_mapping=proportional_vol,
            metric=metric,
            baseline_value=grid_spec.baseline_value,
            days_forward=int(days_forward),
        )
        fig = plot_spot_vol_heatmap(
            result_df,
            spot_scenarios=grid_spec.spot_scenarios,
            vol_scenarios=grid_spec.vol_scenarios,
            original_spot=grid_spec.original_spot,
            avg_vol=grid_spec.avg_vol,
            metric=metric,
        )
        graph = dcc.Graph(figure=fig)
        # #329: only "pnl" is baseline-relative -- "value" is the book's
        # absolute value in that scenario, no "minus today" step, so the
        # note (which describes exactly that subtraction) would misstate
        # it; every other metric is a raw Greek reading, not "vs
        # current," for the same reason.
        if metric != "pnl":
            return graph
        return html.Div(
            [
                graph,
                html.P(STRESS_BASELINE_NOTE, className="plain-language"),
            ],
        )

    return _safe_render(_build)


def layout(
    *,
    portfolio: OptionPortfolio,
    cache: ScenarioGridCache,
    basis_proportional: str,
) -> html.Div:
    """Build the Spot x Vol heatmap panel.

    Bounds the days-forward slider at layout-build time; the empty-book
    fallback matches ``build_spot_vol_grid_spec``'s own default.
    """
    max_days = (
        days_to_max_maturity(portfolio)
        if portfolio.positions
        else _FALLBACK_MAX_DAYS
    )
    return html.Div(
        [
            html.H3(
                [SECTION.title, basis_chip(basis_proportional)],
                id=SECTION.anchor_id,
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Spot range (%)"),
                            dcc.Input(
                                id="explore-spotvol-spot-pct",
                                type="number",
                                value=_DEFAULT_SPOTVOL_SPOT_PCT,
                                debounce=True,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Vol range (%)"),
                            dcc.Input(
                                id="explore-spotvol-vol-pct",
                                type="number",
                                value=_DEFAULT_SPOTVOL_VOL_PCT,
                                debounce=True,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Metric"),
                            dcc.Dropdown(
                                id="explore-spotvol-metric",
                                options=_METRIC_OPTIONS,
                                value=_DEFAULT_SPOTVOL_METRIC,
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
                            html.Label("Grid resolution"),
                            dcc.Slider(
                                id="explore-spotvol-resolution",
                                min=10,
                                max=41,
                                step=1,
                                value=_DEFAULT_SPOTVOL_RESOLUTION,
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
                            html.Label("Days forward"),
                            dcc.Slider(
                                id="explore-spotvol-days-forward",
                                min=0,
                                max=max_days,
                                step=max(1, max_days // 20),
                                value=_DEFAULT_SPOTVOL_DAYS_FORWARD,
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
                # #328: both dials need the stacking context .dial-row
                # establishes (deltadewa.css) — without it, the slider
                # handle's own transform creates a nested stacking context
                # that traps the tooltip underneath the graph card below.
                className="dial-row",
            ),
            dcc.Loading(
                html.Div(
                    _render_spot_vol_panel_logic(
                        portfolio=portfolio,
                        cache=cache,
                        spot_pct=_DEFAULT_SPOTVOL_SPOT_PCT,
                        vol_pct=_DEFAULT_SPOTVOL_VOL_PCT,
                        resolution=_DEFAULT_SPOTVOL_RESOLUTION,
                        days_forward=_DEFAULT_SPOTVOL_DAYS_FORWARD,
                        metric=_DEFAULT_SPOTVOL_METRIC,
                    ),
                    id="explore-spotvol-panel",
                ),
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp) -> None:
    """Wire the Spot x Vol heatmap panel's re-render callback."""

    @app.callback(
        Output("explore-spotvol-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
        Input("explore-spotvol-spot-pct", "value"),
        Input("explore-spotvol-vol-pct", "value"),
        Input("explore-spotvol-resolution", "value"),
        Input("explore-spotvol-days-forward", "value"),
        Input("explore-spotvol-metric", "value"),
    )
    def _render_spot_vol_panel(  # pylint: disable=too-many-arguments
        _version: int,
        spot_pct: float | None,
        vol_pct: float | None,
        resolution: float | None,
        days_forward: float | None,
        metric: str | None,
    ) -> Component:
        return _render_spot_vol_panel_logic(
            portfolio=app.program_state.portfolio,
            cache=app.scenario_cache,
            spot_pct=spot_pct,
            vol_pct=vol_pct,
            resolution=resolution,
            days_forward=days_forward,
            metric=metric,
        )
