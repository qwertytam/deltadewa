"""The `/design` page: editor (BOOK), planners (PLANNING), stress (EXPLORATION).

BOOK: add/remove positions, the underlying quantity, and guarded
import/export. PLANNING: the read-only planners — sizing, strike ladder,
roll, monetization — each a thin wrapper over its `analysis/` function,
pricing the same IPS crash basis `/monitor`'s gauge uses, alongside the
panels that read a different basis and chip themselves accordingly
(market environment, hedge triggers, delta drift, convexity cliff).
EXPLORATION: the three notebook stress surfaces — spot/vol heatmap,
time/price heatmap, Monte Carlo distribution — priced on a *different*
basis (proportional vol, a generic GBM move) than PLANNING's crash-skew;
the zone header, a boundary sentence, and a basis chip on every panel say
so, so the two zones' numbers disagreeing on the same cell reads as two
questions, not a bug. Gates at the page level: without ``ips_config``
there is no source for the exercise-style default and no policy to plan
against, so the whole page becomes a single "no IPS policy loaded" state,
the same discipline ``monitor.py`` uses.

BOOK's own mutators, and the guarded-mutation convention they share
(:func:`~deltadewa.app.pages.design.book._guarded_mutation`, module-level
``_..._logic`` functions directly callable from tests), now live in
:mod:`~deltadewa.app.pages.design.book` — see that module's docstring.
PLANNING's and EXPLORATION's own reads have no mutator to guard, so they
route through :func:`_safe_render` instead — the same no-leaked-traceback
discipline, applied to an engine ``ValueError`` (a structurally missing
input, e.g. no underlying position or an out-of-range dial) rather than
a failed mutation. Every panel here watches ``book.BOOK_VERSION_STORE`` —
the single ``dcc.Store`` a successful BOOK edit bumps — for "the book
changed, re-read it."
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from dash import Input, Output, dcc, html
from dash.development.base_component import Component

from deltadewa import __version__
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.analysis.maturity import MaturityBuckets
from deltadewa.analysis.repricing import proportional_vol
from deltadewa.analysis.stress import (
    build_spot_vol_grid_spec,
    build_time_price_grid_spec,
    compute_empirical_cdf,
    compute_pnl_histogram,
    days_to_max_maturity,
    percentile_of_value,
)
from deltadewa.analysis.volatility import build_volatility_profile
from deltadewa.app import format as fmt
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.ips_notice import build_no_ips_layout
from deltadewa.app.panel_guard import (
    incomplete_notice as _incomplete,
)
from deltadewa.app.panel_guard import (
    safe_render as _safe_render,
)
from deltadewa.app.shape_notice import shape_notice_text
from deltadewa.portfolio.monte_carlo import drift_measure_label
from deltadewa.visualization.distribution_charts_plotly import (
    plot_pnl_distribution,
)
from deltadewa.visualization.stress_charts_plotly import (
    STRESS_METRICS,
    plot_spot_vol_heatmap,
    plot_time_price_heatmap,
)

from . import book
from .planning import (
    convexity_cliff,
    delta_drift,
    hedge_triggers,
    ladder,
    monetization,
    position_aging,
    provenance,
    roll_plan,
    roll_status,
    sizing,
)
from .planning import market_env as market_env_panel

if TYPE_CHECKING:
    from deltadewa.analysis.cache import ScenarioGridCache
    from deltadewa.analysis.maturity import MaturityVegaExposure
    from deltadewa.analysis.volatility import (
        PositionVolatilityDetail,
        VolatilityProfile,
    )
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import (
        IpsConfig,
    )
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.state import ProgramState

_logger = logging.getLogger(__name__)

# Every PLANNING panel prices this basis — size_hedge, build_strike_ladder,
# and evaluate_roll_status each build CrashShock.from_ips(...) internally,
# the same construction /monitor's build_scenario uses at the IPS crash
# point. One literal, so the zone header and every panel's chip say the
# same thing.
_BASIS_CRASH_SKEW = "basis: crash-skew (IPS anchor)"
# The market-environment panel's own _BASIS_LIVE_MARKET_DATA now lives in
# planning/market_env.py, its only reader.
# Nor does the trigger panel: it reads the book's Greeks at today's market,
# with no crash shock applied at all.
_BASIS_BOOK_GREEKS = "basis: book Greeks at today's market"
# The delta drift panel's own _BASIS_MINUS_5PCT, and the convexity cliff
# panel's own _BASIS_MATURITY_CALENDAR, now live in
# planning/delta_drift.py and planning/convexity_cliff.py — each is that
# panel's only reader.
# Nor does the EXPLORATION zone's volatility profile panel: it reads each
# leg's own stored volatility and vega-weights them, but shocks nothing --
# a structural read of today's book, like the vega term exposure panel,
# not a stress scenario.
_BASIS_BOOK_VOLATILITY = "basis: each leg's stored volatility (nothing shocked)"

# EXPLORATION zone: dial defaults, carried over from the
# GlobalAssumptions/StressDashboard cell literals of hedge_design.ipynb
# (deleted in Stage 4.3). Presentation, not policy.
_DEFAULT_SPOTVOL_SPOT_PCT = 50.0
_DEFAULT_SPOTVOL_VOL_PCT = 50.0
_DEFAULT_SPOTVOL_RESOLUTION = 21  # matches the measured 21x21 grid (F4)
_DEFAULT_SPOTVOL_DAYS_FORWARD = 0
_DEFAULT_SPOTVOL_METRIC = "pnl"
_DEFAULT_TIME_SPOT_PCT = 50.0
_DEFAULT_TIME_STEPS = 10
_DEFAULT_PRICE_STEPS = 13
_DEFAULT_TIME_METRIC = "pnl"
_DEFAULT_MC_PATHS = 100_000
_DEFAULT_MC_SEED = 42
_FALLBACK_MAX_DAYS = 90  # matches build_spot_vol_grid_spec's own default
# for an empty book, used only to bound the days-forward slider at layout
# time before any position has been added.

_METRIC_OPTIONS = [
    {"label": spec.label, "value": key} for key, spec in STRESS_METRICS.items()
]

_EXPLORATION_EMPTY_BOOK_MSG = (
    "Add a position in the BOOK zone to explore stress scenarios."
)

# Every EXPLORATION panel prices this basis instead — a generic vol move,
# not the policy crash. proportional_vol is always passed explicitly to
# the cache (M2.1 finding (c): VolMapping is required, never defaulted).
_BASIS_PROPORTIONAL = "basis: proportional vol (GBM, risk-neutral drift)"


def _no_ips_layout(state: ProgramState) -> html.Div:
    """Build the single "no IPS policy loaded" state for the /design page."""
    return build_no_ips_layout(
        state,
        title="Design",
        lead=(
            "No IPS policy is loaded, so there is no policy to plan "
            "against — sizing targets, ladder bands, and roll thresholds "
            "are all policy-derived, and the position editor's "
            "exercise-style default has no source either."
        ),
        page_class="page-design",
    )


def _volatility_profile_row(
    detail: PositionVolatilityDetail,
) -> html.Tr:
    """One position's volatility and its ratio to the book's average."""
    label = f"{detail.option_type.value} {detail.strike_price:,.0f}"
    if detail.is_custom:
        label += " (custom)"
    return html.Tr(
        [
            html.Td(label),
            html.Td(f"{detail.volatility:.2%}"),
            html.Td(f"{detail.relative_to_avg * 100:.0f}% of avg"),
        ],
    )


def _volatility_profile_panel_view(
    profile: VolatilityProfile,
) -> Component:
    """Render #260: the book's volatility profile.

    Frames the panel as what it is -- the assumption every EXPLORATION
    grid below is built on, not a standalone statistic. Every grid scales
    each leg's volatility by the same factor (``proportional_vol``) so the
    vega-weighted average reaches whatever level the axis asks for; this
    panel shows that average and the skew (each leg's ratio to it) being
    held constant while it moves.
    """
    header = html.Tr(
        [html.Th("Leg"), html.Th("Volatility"), html.Th("vs. average")],
    )
    rows = [_volatility_profile_row(detail) for detail in profile.positions]
    return html.Div(
        [
            html.P(
                "Every EXPLORATION grid below scales each leg's "
                "volatility by the same factor so the vega-weighted "
                "average reaches the level on the axis -- this is the "
                "average, and the skew being held constant while it "
                "moves.",
                className="plain-language",
            ),
            html.P(
                f"Vega-weighted average {profile.avg_volatility:.2%}, "
                f"range {profile.min_volatility:.2%}-"
                f"{profile.max_volatility:.2%} "
                f"({profile.volatility_range:.2%} wide).",
                className="env-verdict",
            ),
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="planning-table",
            ),
        ],
    )


def _render_volatility_profile_panel_logic(
    *,
    portfolio: OptionPortfolio,
) -> Component:
    """Render the volatility profile panel for the current book."""
    if not portfolio.positions:
        return _incomplete(_EXPLORATION_EMPTY_BOOK_MSG)

    def _build() -> Component:
        profile = build_volatility_profile(portfolio)
        if profile is None:  # pragma: no cover - guarded above
            return _incomplete(_EXPLORATION_EMPTY_BOOK_MSG)
        return _volatility_profile_panel_view(profile)

    return _safe_render(_build)


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
        return dcc.Graph(figure=fig)

    return _safe_render(_build)


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


def _vega_term_panel_view(exposure: MaturityVegaExposure) -> Component:
    """Render Part X §14: vega bucketed by maturity, a structural view.

    Not a stress scenario — a read of today's book, so it carries the
    ``_BASIS_BOOK_GREEKS`` chip (like the PLANNING zone's hedge triggers
    panel) rather than EXPLORATION's default proportional-vol basis.
    """
    header = html.Tr([html.Th("Maturity bucket"), html.Th("Vega")])
    rows = [
        html.Tr([html.Td(bucket), html.Td(f"{vega:,.1f}")])
        for bucket, vega in exposure.vega_by_bucket.items()
    ]
    return html.Div(
        [
            html.P(
                "Where the book's volatility sensitivity sits across the "
                "term structure — a structural read, not a stress "
                "scenario. Institutional tail hedges typically prefer "
                "long-dated vega exposure.",
                className="plain-language",
            ),
            html.P(
                f"Total vega {exposure.total_vega:,.1f}.",
                className="env-verdict",
            ),
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="planning-table",
            ),
        ],
    )


def _render_vega_term_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the vega term exposure panel for the current book.

    Takes ``ips_config`` for the bucket edges (#305): where the term
    structure is cut is policy, not presentation, and this is the panel the
    old weekly-options edges rendered useless on an 18-month ladder.
    """
    buckets = MaturityBuckets.from_ips(ips_config.maturity_buckets)
    return _safe_render(
        lambda: _vega_term_panel_view(
            PortfolioAnalyzer(portfolio).calculate_vega_by_maturity(buckets),
        ),
    )


def render(app: ProgramDashApp) -> html.Div:
    """Build the /design page: the BOOK zone and the PLANNING zone.

    BOOK is the editor (add/remove, import/export); PLANNING is the
    read-only planners (sizing, strike ladder, roll, monetization) priced on
    the same IPS crash basis ``/monitor``'s gauge uses, plus the panels
    carrying their own basis chip. Built
    fresh per request from ``app.program_state``/``app.ips_config`` — no
    module-level singleton, so this page's content actually differs from
    ``/monitor``'s (``test_pages.py``'s distinctness assertion).
    """
    if app.ips_config is None:
        return _no_ips_layout(app.program_state)

    ips_config = app.ips_config
    portfolio = app.program_state.portfolio
    default_style = ips_config.pricing.exercise_style.value
    # One assessment shared by the market-environment and monetization
    # panels. Both need the same snapshot, and a second fetch could return a
    # different one — the two panels would then disagree on the same page.
    market_env = assess_market_environment(
        app.market_data,
        ips_config.market_environment,
    )
    # Bounds the spot-vol days-forward slider at layout-build time; the
    # empty-book fallback matches build_spot_vol_grid_spec's own default.
    max_days = (
        days_to_max_maturity(portfolio)
        if portfolio.positions
        else _FALLBACK_MAX_DAYS
    )

    book_zone = book.layout(
        app=app,
        portfolio=portfolio,
        default_style=default_style,
    )

    planning_zone = html.Div(
        [
            html.H2(["Planning", basis_chip(_BASIS_CRASH_SKEW)]),
            html.P(
                "Every panel below that prices the book prices the IPS "
                "crash — the same basis /monitor's gauge uses. Those agree "
                "with /monitor to the cent. Any panel on a different basis — "
                "reading the live feed, the book's Greeks unshocked, another "
                "shock, or just the position calendar — carries its own "
                "chip.",
                className="plain-language",
            ),
            market_env_panel.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                market_env=market_env,
            ),
            sizing.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_crash_skew=_BASIS_CRASH_SKEW,
            ),
            ladder.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_crash_skew=_BASIS_CRASH_SKEW,
            ),
            roll_plan.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_crash_skew=_BASIS_CRASH_SKEW,
            ),
            roll_status.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_crash_skew=_BASIS_CRASH_SKEW,
            ),
            provenance.layout(
                app=app,
                portfolio=portfolio,
                ips_config=ips_config,
            ),
            position_aging.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_book_greeks=_BASIS_BOOK_GREEKS,
            ),
            hedge_triggers.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_book_greeks=_BASIS_BOOK_GREEKS,
            ),
            delta_drift.layout(portfolio=portfolio),
            convexity_cliff.layout(
                portfolio=portfolio,
                ips_config=ips_config,
            ),
            monetization.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                market_env=market_env,
                basis_crash_skew=_BASIS_CRASH_SKEW,
            ),
        ],
        className="zone-planning",
    )

    exploration_zone = html.Div(
        [
            html.H2(["Exploration", basis_chip(_BASIS_PROPORTIONAL)]),
            html.P(
                "These grids price a generic volatility move — every leg "
                "scaled so the vega-weighted average reaches the level on "
                "the axis. The PLANNING panels above price the IPS crash "
                "with its wing-anchored skew instead. The same spot/vol "
                "cell will read differently on the two — they are answers "
                "to different questions, not a disagreement.",
                className="plain-language",
            ),
            dcc.Link(
                "See the policy crash number on /monitor.",
                href="/monitor",
            ),
            html.Div(
                [
                    html.H3(
                        [
                            "Volatility profile",
                            basis_chip(_BASIS_BOOK_VOLATILITY),
                        ],
                    ),
                    html.Div(
                        _render_volatility_profile_panel_logic(
                            portfolio=portfolio,
                        ),
                        id="explore-volatility-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(
                        ["Spot x vol heatmap", basis_chip(_BASIS_PROPORTIONAL)],
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
                    dcc.Loading(
                        html.Div(
                            _render_spot_vol_panel_logic(
                                portfolio=portfolio,
                                cache=app.scenario_cache,
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
            ),
            html.Div(
                [
                    html.H3(
                        [
                            "Time x price heatmap",
                            basis_chip(_BASIS_PROPORTIONAL),
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
                    dcc.Loading(
                        html.Div(
                            _render_time_price_panel_logic(
                                portfolio=portfolio,
                                cache=app.scenario_cache,
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
            ),
            html.Div(
                [
                    html.H3(
                        [
                            "Monte Carlo distribution",
                            basis_chip(_BASIS_PROPORTIONAL),
                        ],
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
                                        (
                                            "Horizon (days, "
                                            "blank = nearest maturity)"
                                        ),
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
                                        (
                                            "Expected return (%, "
                                            "blank = risk-neutral)"
                                        ),
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
            ),
            html.Div(
                [
                    html.H3(
                        [
                            "Vega term exposure",
                            basis_chip(_BASIS_BOOK_GREEKS),
                        ],
                    ),
                    html.Div(
                        _render_vega_term_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                        ),
                        id="explore-vega-term-panel",
                    ),
                ],
                className="panel",
            ),
        ],
        className="zone-exploration",
    )

    return html.Div(
        [
            html.H1("Design"),
            html.Div(
                shape_notice_text(portfolio),
                id="shape-notice",
                className="shape-notice",
            ),
            book_zone,
            planning_zone,
            exploration_zone,
            _page_footer(),
        ],
        className="page page-design",
    )


def _page_footer() -> html.Div:
    """Build the page's own last element: a muted build-version stamp.

    #359 (originally fixed on /monitor, applied here to match): a
    build-version stamp styled identically to the surrounding financial
    sentences gets skimmed past. This used to be a ``.plain-language``
    paragraph sandwiched inside the exploration zone, after the vega
    term exposure panel. Placed here instead — the true last child of
    the page, after every zone — it stays in the same place regardless
    of which panels are expanded or collapsed, and its styling (shared
    ``.page-footer`` class, same as /monitor) marks it as metadata
    rather than portfolio commentary.
    """
    return html.Div(
        html.P(f"Running v{__version__}"),
        className="page-footer",
    )


def register_callbacks(  # pylint: disable=too-many-locals
    app: ProgramDashApp,
) -> None:
    """Wire the BOOK zone's mutating callbacks and the read-only panels.

    One nested callback per mutator/panel is the natural shape of this
    function — the local count tracks how many the page wires, not
    unrelated complexity, so a targeted disable is more honest than
    restructuring around the lint.

    A no-op when ``app.ips_config is None`` — mirrors ``render()``'s own
    page-level gate, so a gated page has nothing wired to a mutator
    either.
    """
    if app.ips_config is None:
        return
    # Captured once into a local rather than re-read from app.ips_config
    # inside each nested callback below: mypy narrows a local variable's
    # None-ness across a closure, but not a property re-accessed later
    # (the same reason monitor.py's register_callbacks does this).
    ips_config = app.ips_config

    book.register(app)
    convexity_cliff.register(app, ips_config=ips_config)
    position_aging.register(app, ips_config=ips_config)
    hedge_triggers.register(app, ips_config=ips_config)
    delta_drift.register(app)
    sizing.register(app, ips_config=ips_config)
    ladder.register(app, ips_config=ips_config)
    roll_plan.register(app, ips_config=ips_config)
    roll_status.register(app, ips_config=ips_config)
    provenance.register(app, ips_config=ips_config)
    monetization.register(app, ips_config=ips_config)
    market_env_panel.register(app, ips_config=ips_config)

    @app.callback(
        Output("shape-notice", "children"),
        Input("book-version", "data"),
    )
    def _render_shape_notice(_version: int) -> str | None:
        # Restores #261: /design can change the book's shape (add/remove a
        # position) without a re-import, so this has to watch book-version
        # like every other read-only panel on this page, not just render
        # once at page load.
        return shape_notice_text(app.program_state.portfolio)

    @app.callback(
        Output("explore-volatility-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_volatility_profile_panel(_version: int) -> Component:
        return _render_volatility_profile_panel_logic(
            portfolio=app.program_state.portfolio,
        )

    @app.callback(
        Output("explore-spotvol-panel", "children"),
        Input("book-version", "data"),
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

    @app.callback(
        Output("explore-time-panel", "children"),
        Input("book-version", "data"),
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

    @app.callback(
        Output("explore-mc-panel", "children"),
        Input("book-version", "data"),
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

    @app.callback(
        Output("explore-vega-term-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_vega_term_panel(_version: int) -> Component:
        return _render_vega_term_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )
