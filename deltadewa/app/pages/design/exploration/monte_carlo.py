"""EXPLORATION zone: the Monte Carlo Distribution panel.

``basis_proportional`` is a parameter, not a module constant: the zone
heading and three of its five panels (this one, ``spot_vol``,
``time_price``) share this basis chip text, so the string lives in
``page.py`` and is passed down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import numpy as np
from dash import Input, Output, dcc, html

from deltadewa.analysis.stress import (
    compute_empirical_cdf,
    compute_pnl_histogram,
    percentile_of_value,
)
from deltadewa.app import format as fmt
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import incomplete_notice as _incomplete
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec
from deltadewa.portfolio.monte_carlo import drift_measure_label
from deltadewa.visualization.distribution_charts_plotly import (
    plot_pnl_distribution,
)

from ..book import BOOK_VERSION_STORE
from ..dials import _EXPLORATION_EMPTY_BOOK_MSG

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.portfolio.core import OptionPortfolio

_DEFAULT_MC_PATHS = 100_000
_DEFAULT_MC_SEED = 42

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-monte-carlo",
    title="Monte Carlo distribution",
)


def _mc_stats_block(results: dict[str, Any]) -> Component:
    """Format the Monte Carlo panel's summary stats — text only.

    Surfaces ``drift_measure_label`` next to "probability of profit"
    (M1.3) — a bare probability figure is never shown without naming the
    drift assumption behind it.
    """
    drift_label = drift_measure_label(results["drift_measure"])
    return html.Div(
        [
            html.P(
                f"{results['num_simulations']:,} simulations, "
                f"{results['days_to_expiry']} days to horizon.",
                className="plain-language",
            ),
            html.P(
                "Expected P&L "
                f"{fmt.currency(results['expected_pnl'])} (median "
                f"{fmt.currency(results['median_pnl'])}); probability of "
                f"profit {fmt.percent(results['prob_profit'] * 100)} "
                f"({drift_label} drift).",
            ),
            html.P(
                f"95% VaR {fmt.currency(results['var_95'])}, 95% CVaR "
                f"{fmt.currency(results['cvar_95'])}, worst case "
                f"{fmt.currency(results['max_loss'])}.",
            ),
        ],
    )


def _render_mc_panel_logic(
    *,
    portfolio: OptionPortfolio,
    num_paths: float | None,
    horizon_days: float | None,
    expected_return_pct: float | None,
    seed: float | None,
) -> Component:
    """Run a scenario-local Monte Carlo simulation and render it.

    Always passes ``persist_cache=False`` — this is a what-if panel, not
    the shared book-level cache other readers (``visualization/
    pnl_charts.py``, ``widgets/summary.py``) rely on (B0's containment,
    F6). ``horizon_days``/``expected_return_pct``/``seed`` blank map to
    the engine's own ``None`` defaults (nearest maturity, risk-neutral
    drift, true randomness), not to a fabricated zero.
    """
    if not portfolio.positions:
        return _incomplete(_EXPLORATION_EMPTY_BOOK_MSG)
    if num_paths is None:
        return _incomplete("Number of paths is required.")

    def _build() -> Component:
        results = portfolio.run_monte_carlo_simulation(
            num_simulations=int(num_paths),
            days_to_expiry=(
                int(horizon_days) if horizon_days is not None else None
            ),
            expected_return=(
                expected_return_pct / 100.0
                if expected_return_pct is not None
                else None
            ),
            random_seed=int(seed) if seed is not None else None,
            persist_cache=False,
        )
        pnls_clean = np.asarray(results["simulated_pnls"], dtype=float)
        histogram = compute_pnl_histogram(
            pnls_clean,
            min_pnl=results["min_pnl"],
            max_pnl=results["max_pnl"],
            is_concentrated=results["is_concentrated"],
        )
        empirical_cdf = compute_empirical_cdf(pnls_clean)
        expected_percentile = percentile_of_value(
            empirical_cdf,
            results["expected_pnl"],
        )
        fig = plot_pnl_distribution(
            histogram=histogram,
            empirical_cdf=empirical_cdf,
            expected_pnl=results["expected_pnl"],
            median_pnl=results["median_pnl"],
            var_95=results["var_95"],
            cvar_95=results["cvar_95"],
            max_loss=results["max_loss"],
            is_concentrated=results["is_concentrated"],
            most_common_pnl=results["most_common_pnl"],
            concentration_pct=results["concentration_pct"],
            expected_percentile=expected_percentile,
            drift_measure=results["drift_measure"],
        )
        return html.Div([dcc.Graph(figure=fig), _mc_stats_block(results)])

    return _safe_render(_build)


def layout(
    *,
    portfolio: OptionPortfolio,
    basis_proportional: str,
) -> html.Div:
    """Build the Monte Carlo Distribution panel."""
    return html.Div(
        [
            html.H3(
                [
                    SECTION.title,
                    basis_chip(basis_proportional),
                ],
                id=SECTION.anchor_id,
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Paths"),
                            dcc.Input(
                                id="explore-mc-paths",
                                type="number",
                                value=_DEFAULT_MC_PATHS,
                                debounce=True,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label(
                                ("Horizon (days, blank = nearest maturity)"),
                            ),
                            dcc.Input(
                                id="explore-mc-horizon-days",
                                type="number",
                                debounce=True,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label(
                                ("Expected return (%, blank = risk-neutral)"),
                            ),
                            dcc.Input(
                                id="explore-mc-expected-return",
                                type="number",
                                debounce=True,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label(
                                "Random seed (blank = true randomness)",
                            ),
                            dcc.Input(
                                id="explore-mc-seed",
                                type="number",
                                value=_DEFAULT_MC_SEED,
                                debounce=True,
                            ),
                        ],
                        className="editor-field",
                    ),
                ],
                className="editor-form",
            ),
            dcc.Loading(
                html.Div(
                    _render_mc_panel_logic(
                        portfolio=portfolio,
                        num_paths=_DEFAULT_MC_PATHS,
                        horizon_days=None,
                        expected_return_pct=None,
                        seed=_DEFAULT_MC_SEED,
                    ),
                    id="explore-mc-panel",
                ),
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp) -> None:
    """Wire the Monte Carlo Distribution panel's re-render callback."""

    @app.callback(
        Output("explore-mc-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
        Input("explore-mc-paths", "value"),
        Input("explore-mc-horizon-days", "value"),
        Input("explore-mc-expected-return", "value"),
        Input("explore-mc-seed", "value"),
    )
    def _render_mc_panel(
        _version: int,
        num_paths: float | None,
        horizon_days: float | None,
        expected_return_pct: float | None,
        seed: float | None,
    ) -> Component:
        return _render_mc_panel_logic(
            portfolio=app.program_state.portfolio,
            num_paths=num_paths,
            horizon_days=horizon_days,
            expected_return_pct=expected_return_pct,
            seed=seed,
        )
