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
from dash import Input, Output, State, dcc, html, no_update
from dash.development.base_component import Component

from deltadewa import __version__
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.analysis.decision_matrix import (
    decision_matrix,
    entry_timing_tree,
)
from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.analysis.maturity import MaturityBuckets
from deltadewa.analysis.monetization import build_monetization_plan
from deltadewa.analysis.provenance import build_provenance_ledger
from deltadewa.analysis.repricing import proportional_vol
from deltadewa.analysis.roll_planner import build_roll_plan
from deltadewa.analysis.roll_status import RollVerdict, evaluate_roll_status
from deltadewa.analysis.sizing import size_hedge
from deltadewa.analysis.stress import (
    build_spot_vol_grid_spec,
    build_time_price_grid_spec,
    compute_empirical_cdf,
    compute_pnl_histogram,
    days_to_max_maturity,
    percentile_of_value,
)
from deltadewa.analysis.strike_ladder import build_strike_ladder
from deltadewa.analysis.volatility import build_volatility_profile
from deltadewa.app import format as fmt
from deltadewa.app.bands import band_bar
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.ips_notice import build_no_ips_layout
from deltadewa.app.panel_guard import NoticeKind, panel_notice
from deltadewa.app.panel_guard import (
    incomplete_notice as _incomplete,
)
from deltadewa.app.panel_guard import (
    safe_render as _safe_render,
)
from deltadewa.app.provenance_panel import build_provenance_panel
from deltadewa.app.shape_notice import shape_notice_text
from deltadewa.clock import program_trading_date
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
from .book import _mark_inputs_reviewed_logic
from .planning import (
    convexity_cliff,
    delta_drift,
    hedge_triggers,
    position_aging,
)

if TYPE_CHECKING:
    from deltadewa.analysis.cache import ScenarioGridCache
    from deltadewa.analysis.decision_matrix import (
        DecisionResult,
        EntryTimingResult,
    )
    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.analysis.maturity import MaturityVegaExposure
    from deltadewa.analysis.monetization import (
        MonetizationPlan,
        MonetizationStepStatus,
    )
    from deltadewa.analysis.roll_planner import RollPlanRecord
    from deltadewa.analysis.roll_status import MoneynessDrift, RollStatusRecord
    from deltadewa.analysis.sizing import HedgeSizingResult
    from deltadewa.analysis.strike_ladder import (
        LadderRung,
        StrikeLadderResult,
        UnsolvableRung,
    )
    from deltadewa.analysis.volatility import (
        PositionVolatilityDetail,
        VolatilityProfile,
    )
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import (
        IpsConfig,
        IpsMarketEnvironment,
        IpsMaturitySelection,
    )
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.state import ProgramState

_logger = logging.getLogger(__name__)

# PLANNING zone: dial defaults. Carried over from the sizing/ladder cells of
# hedge_design.ipynb, which Stage 4.3 deleted — these are the starting point
# that notebook hardcoded, kept here as adjustable dial defaults. Genuinely
# presentation, not policy: no IPS strike-selection section exists to read
# them from, and inventing one is its own decision, not #316's (which is
# about tenor, not delta/OTM). The two MATURITY dial defaults these used to
# sit beside were #316's actual bug (0.5y, unbacked by any policy) and now
# come from ips_config.maturity_selection instead — see render().
_DEFAULT_SIZING_PCT_OTM = 20.0
_DEFAULT_LADDER_TARGET_DELTAS = "0.05, 0.10, 0.15"

# #326: safe_render's BLOCKED remediation pointer for the two panels that
# raise ValueError on a book with no underlying position (size_hedge,
# build_strike_ladder). Presentation, on the page that knows where the
# fix lives -- not baked into the analysis-layer exception text.
_SIZING_BLOCKED_HINT = (
    "Set the underlying spot and quantity in the BOOK zone; sizing "
    "needs them to size a candidate hedge."
)
_LADDER_BLOCKED_HINT = (
    "Set the underlying spot and quantity in the BOOK zone; the ladder "
    "sizes every rung against them."
)

# Every PLANNING panel prices this basis — size_hedge, build_strike_ladder,
# and evaluate_roll_status each build CrashShock.from_ips(...) internally,
# the same construction /monitor's build_scenario uses at the IPS crash
# point. One literal, so the zone header and every panel's chip say the
# same thing.
_BASIS_CRASH_SKEW = "basis: crash-skew (IPS anchor)"
# The market-environment panel reprices nothing — it reads the live feed —
# so it must not carry PLANNING's crash-skew chip.
_BASIS_LIVE_MARKET_DATA = "basis: live market data"
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


def _parse_float_list(raw: str | None) -> list[float] | None:
    """Parse a comma-separated list of floats.

    Returns ``None`` on a blank or malformed string — a dial-parsing
    failure, not an engine error, so it's handled before :func:`_safe_render`
    ever runs.
    """
    if raw is None or not raw.strip():
        return None
    try:
        values = [
            float(part.strip()) for part in raw.split(",") if part.strip()
        ]
    except ValueError:
        return None
    return values or None


def _ladder_maturities_text(selection: IpsMaturitySelection) -> str:
    """Format the ladder dial's initial text from IPS policy (#316).

    ``ladder_maturities_years`` is already derived from the three
    ``maturity_selection`` fields, so this is only the text-rendering
    step of that -- not a fourth place the tenor could drift from them.
    """
    return ", ".join(str(years) for years in selection.ladder_maturities_years)


def _env_metric_row(
    *,
    label: str,
    headline: str,
    detail: str,
    bar: Component | None = None,
) -> Component:
    """One market-environment metric: name, reading, and what it means."""
    children: list[Component] = [
        html.Span(label, className="env-metric-label"),
        html.Span(headline, className="env-metric-value"),
        html.Span(detail, className="env-metric-detail"),
    ]
    if bar is not None:
        children.append(bar)
    return html.Div(children, className="env-metric")


def _env_unavailable_row(label: str, why: str) -> Component:
    """One metric the provider didn't return.

    Rendered as an explicit absence rather than omitted or zeroed: a
    silently missing row reads as "nothing to report", which is the
    opposite of what a failed fetch means.
    """
    return _env_metric_row(
        label=label,
        headline="unavailable",
        detail=why,
    )


def _vol_regime_row(
    market_env: MarketEnvironment,
    policy: IpsMarketEnvironment,
) -> Component:
    """Part X #6 — the volatility regime, banded against the IPS."""
    if market_env.vix is None or market_env.regime_label is None:
        return _env_unavailable_row(
            "Vol regime",
            "no VIX reading in this snapshot",
        )

    percentile = (
        f", regime percentile {market_env.regime_percentile:.0f}"
        if market_env.regime_percentile is not None
        else ""
    )
    # The IPS band is decimal implied vol compared against VIX/100
    # (market_environment.classify_vix_regime), so the bar is drawn on the
    # VIX level in vol points — the units the reading is actually in —
    # rather than on the derived percentile.
    return _env_metric_row(
        label="Vol regime",
        headline=f"{market_env.regime_label.value} — VIX {market_env.vix:.1f}",
        detail=(
            f"IPS band {policy.vol_regime_low * 100:.0f}-"
            f"{policy.vol_regime_high * 100:.0f} VIX points{percentile}"
        ),
        bar=band_bar(
            value=market_env.vix,
            low=policy.vol_regime_low * 100,
            high=policy.vol_regime_high * 100,
        ),
    )


def _skew_row(
    market_env: MarketEnvironment,
    policy: IpsMarketEnvironment,
) -> Component:
    """Part X #7 — the SKEW percentile, banded against the IPS."""
    if market_env.skew_percentile is None:
        return _env_unavailable_row(
            "Skew percentile",
            "no SKEW reading in this snapshot",
        )

    # skew_percentile is a 0-1 fraction (the units get_skew_percentile
    # returns and assess_market_environment compares in), while the IPS band
    # is stated on 0-100. Converted back here, once, for display — the same
    # boundary market_environment.py:303-308 crosses in the other direction.
    percentile_pct = market_env.skew_percentile * 100
    index_text = (
        f", SKEW index {market_env.skew_index:.1f}"
        if market_env.skew_index is not None
        else ""
    )
    return _env_metric_row(
        label="Skew percentile",
        headline=f"{percentile_pct:.0f}th percentile",
        detail=(
            f"IPS band {policy.skew_low_pctile:.0f}-"
            f"{policy.skew_high_pctile:.0f}{index_text}"
        ),
        bar=band_bar(
            value=percentile_pct,
            low=policy.skew_low_pctile,
            high=policy.skew_high_pctile,
        ),
    )


def _forward_variance_row(market_env: MarketEnvironment) -> Component:
    """Part X #8 — forward variance, as a level with no band.

    The IPS states no forward-variance band, so this deliberately gets no
    ``band_bar``: inventing one here would be exactly the presentation-side
    policy the ``market_environment`` section exists to prevent. It is read
    alongside the hedge-cost verdict below instead.
    """
    if market_env.forward_vol_front_3m is None:
        return _env_unavailable_row(
            "Forward variance",
            "needs both VIX and VIX3M; one is missing",
        )

    shape_text = (
        f", term structure {market_env.term_shape.value}"
        if market_env.term_shape is not None
        else ""
    )
    return _env_metric_row(
        label="Forward variance",
        headline=f"{market_env.forward_vol_front_3m:.1f} vol points",
        detail=(
            f"front-to-3M implied forward vol; no IPS band{shape_text} — "
            "read against the hedge-cost verdict below"
        ),
    )


def _entry_timing_rows(timing: EntryTimingResult) -> list[Component]:
    """Render the entry-timing tree's path, step by step."""
    rows: list[Component] = [
        html.P(
            f"Entry timing: {timing.recommendation}",
            className="env-verdict",
        ),
    ]
    if timing.data_quality_note is not None:
        rows.append(
            html.P(timing.data_quality_note, className="plain-language"),
        )
    rows.extend(
        html.P(
            f"{step.step}. {step.label}: {step.value} — {step.recommendation}",
            className="env-timing-step",
        )
        for step in timing.steps
    )
    return rows


def _market_env_panel_view(
    market_env: MarketEnvironment,
    decision: DecisionResult,
    timing: EntryTimingResult,
    policy: IpsMarketEnvironment,
) -> Component:
    """Render the market environment panel: matrix inputs, then its verdict.

    Part X #6, #7 and #8 are exactly the three inputs
    :func:`~deltadewa.analysis.decision_matrix.decision_matrix` takes, so
    they are shown here together with the verdict they produce. Splitting
    them across surfaces — the numbers nowhere, the verdict in the Sunday
    digest — is what the 2026-08-06 re-audit found had lost them.
    """
    cost_text = (
        market_env.hedge_cost_verdict.value
        if market_env.hedge_cost_verdict is not None
        else "unavailable"
    )
    return html.Div(
        [
            html.P(
                "The three readings the decision matrix takes, and the "
                'verdict they produce — so "should I buy today" can be '
                "asked on any day, not only when the weekly digest lands.",
                className="plain-language",
            ),
            html.Div(
                [
                    _vol_regime_row(market_env, policy),
                    _skew_row(market_env, policy),
                    _forward_variance_row(market_env),
                ],
                className="env-metrics",
            ),
            html.P(
                f"Hedge cost: {cost_text}",
                className="env-verdict",
            ),
            html.P(
                f"Decision: {decision.verdict.value} — {decision.rationale}",
                className="env-verdict",
            ),
            *(
                [
                    html.P(
                        decision.data_quality_note,
                        className="plain-language",
                    ),
                ]
                if decision.data_quality_note is not None
                else []
            ),
            *_entry_timing_rows(timing),
        ],
    )


def _render_market_env_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    market_env: MarketEnvironment,
) -> Component:
    """Render the market environment panel for the current book and feed."""

    def _build() -> Component:
        convexity_now_pct = PortfolioAnalyzer(
            portfolio,
        ).calculate_crash_convexity_pct(
            CrashShock.from_ips(ips_config.convexity),
        )
        plan = build_monetization_plan(
            portfolio,
            ips_config,
            market_env=market_env,
        )
        decision = decision_matrix(
            market_env,
            convexity_now_pct=convexity_now_pct,
            ips_convexity=ips_config.convexity,
            monetization_plan=plan,
        )
        return _market_env_panel_view(
            market_env,
            decision,
            entry_timing_tree(
                market_env,
                vix_very_high=ips_config.market_environment.vix_very_high,
                vix_caution=ips_config.market_environment.vix_caution,
                vix_low=ips_config.market_environment.vix_low,
            ),
            ips_config.market_environment,
        )

    return _safe_render(_build)


def _vega_sufficiency_block(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render Part X #4 — is the book big enough to answer a vol spike.

    Sits inside the sizing panel because it is the same question one step
    back: sizing asks "how many contracts", this asks "does what we already
    hold respond to volatility at all". It describes **the current book**,
    not the sized candidate above it, and says so — otherwise the reading
    is naturally taken for the candidate's.

    The denominator is named for the same reason.
    ``calculate_vega_sufficiency_pct`` normalizes by total portfolio value
    (options **plus** underlying), which on a tail-hedge book is dominated
    by the equity leg — a reader assuming the option book alone would take
    this figure for something roughly two orders of magnitude larger.
    """
    band = ips_config.vega
    value = PortfolioAnalyzer(portfolio).calculate_vega_sufficiency_pct()
    verdict = (
        "within band"
        if band.sufficiency_min_pct <= value <= band.sufficiency_max_pct
        else "outside band"
    )
    return html.Div(
        [
            html.H4("Vega sufficiency"),
            html.P(
                f"The book as it stands moves {fmt.percent(value)} of total "
                "portfolio value (options plus underlying) per +10 vol "
                f"points, against an IPS band of "
                f"{fmt.percent(band.sufficiency_min_pct)}-"
                f"{fmt.percent(band.sufficiency_max_pct)} ({verdict}). "
                "This describes the current book, not the candidate sized "
                "above.",
                className="plain-language",
            ),
            band_bar(
                value=value,
                low=band.sufficiency_min_pct,
                high=band.sufficiency_max_pct,
            ),
        ],
        id="vega-sufficiency",
    )


def _sizing_panel_view(
    result: HedgeSizingResult,
    ips_config: IpsConfig,
) -> Component:
    """Render one sized candidate: the rationale first, then the answer.

    The intrinsic floor is a labelled conservative lower bound, surfaced only
    when the IPS opts in (``convexity.crash_floor_reported``) and never the
    headline — it reads far below the repriced payoff (2.5x against 17.5x in
    the handbook's worked example), so a program may reasonably keep it off
    the page rather than risk it being read as the protection on offer. See
    ``docs/repricing-methodology.md`` §3/§5.
    """
    conv = ips_config.convexity
    carry_verdict = "within" if result.within_budget else "over"
    convexity_verdict = "within" if result.meets_convexity_target else "over"
    intrinsic_floor_text = (
        " (intrinsic floor "
        + fmt.currency(result.per_contract_intrinsic_floor, decimals=2)
        + ")"
        if conv.crash_floor_reported
        else ""
    )
    return html.Div(
        [
            html.H4("Rationale"),
            html.P(
                f"Book notional {fmt.currency(result.book_notional)} x "
                f"beta {result.portfolio_beta:.2f} = beta-adjusted "
                f"notional {fmt.currency(result.beta_adjusted_notional)}. "
                "The hedge must recover "
                f"{fmt.currency(result.required_crash_offset)} beyond the "
                "drawdown tolerance at the IPS crash.",
                className="plain-language",
            ),
            html.H4("Candidate economics"),
            html.P(
                f"{result.candidate_pct_otm:.1f}% OTM, "
                f"{result.candidate_maturity_years:.2f}y to expiry — "
                "crash payoff "
                f"{fmt.currency(result.per_contract_payoff, decimals=2)}"
                f"/contract{intrinsic_floor_text}, "
                f"carry {fmt.currency(result.per_contract_carry, decimals=2)}"
                "/contract/year.",
                className="plain-language",
            ),
            html.H4("Sizing"),
            html.P(
                f"{result.contracts_needed:,} contracts needed — implied "
                f"annual carry {fmt.currency(result.implied_annual_carry)} "
                f"vs {fmt.currency(result.carry_budget)} budget "
                f"({carry_verdict} budget, headroom "
                f"{fmt.signed_currency(result.carry_headroom)}; max "
                f"affordable {result.max_affordable_contracts:,} contracts).",
            ),
            band_bar(
                value=result.implied_annual_carry,
                low=0.0,
                high=result.carry_budget,
            ),
            html.P(
                "Achieved convexity "
                f"{fmt.percent(result.achieved_convexity_pct)} vs "
                f"{fmt.percent(conv.target_min_pct)}-"
                f"{fmt.percent(conv.target_max_pct)} target "
                f"({convexity_verdict} target).",
            ),
            band_bar(
                value=result.achieved_convexity_pct,
                low=conv.target_min_pct,
                high=conv.target_max_pct,
            ),
        ],
    )


def _render_sizing_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    pct_otm: float | None,
    maturity_years: float | None,
    vol_override: float | None,
) -> Component:
    """Render the sizing panel: the candidate, then the book's vega reading.

    The vega-sufficiency block is a sibling of the candidate rather than
    part of :func:`_sizing_panel_view`, and is rendered *whatever* the
    candidate does. It depends on neither the dials nor an underlying
    position, so folding it into the candidate's own render would let an
    unfinished dial or an empty book take Part X #4 off the page again —
    which is the regression this restores.
    """
    candidate: Component
    if pct_otm is None or maturity_years is None:
        candidate = _incomplete(
            "Enter a strike (% OTM) and a maturity (years) to size a "
            "candidate hedge.",
        )
    else:

        def _build() -> Component:
            result = size_hedge(
                portfolio,
                ips_config,
                candidate_pct_otm=pct_otm,
                candidate_maturity_years=maturity_years,
                vol=vol_override,
            )
            return _sizing_panel_view(result, ips_config)

        candidate = _safe_render(_build, blocked_hint=_SIZING_BLOCKED_HINT)

    return html.Div(
        [
            candidate,
            _safe_render(
                lambda: _vega_sufficiency_block(portfolio, ips_config),
            ),
        ],
    )


def _unsolvable_rung_line(rung: UnsolvableRung) -> html.P:
    """One unsolvable ladder cell, surfaced explicitly — never dropped.

    Not the ``Mi5`` finding (that's the unrelated ``include_underlying``
    scalar/vectorized P&L default, already closed in M1.3/M1.4) — this
    is M1.4's strike-ladder bullet's third clause, which was never given
    its own finding number in ``docs/implementation-plan.md``.
    """
    return html.P(
        f"{rung.target_delta:.2f}Δ @ {rung.maturity_years:.2f}y — "
        f"{rung.reason}",
        className="unsolvable-note",
    )


def _ladder_rung_row(rung: LadderRung) -> html.Tr:
    """One solved ladder rung."""
    verdict = "within" if rung.meets_target_within_budget else "over"
    return html.Tr(
        [
            html.Td(f"{rung.target_delta:.2f}Δ"),
            html.Td(f"{rung.maturity_years:.2f}y"),
            html.Td(f"{rung.metrics.strike:,.0f}"),
            html.Td(f"{rung.metrics.pct_otm:.1f}%"),
            html.Td(f"{rung.metrics.put_delta:.3f}"),
            html.Td(fmt.currency(rung.metrics.premium, decimals=2)),
            html.Td(
                fmt.currency(rung.metrics.per_contract_payoff, decimals=2),
            ),
            html.Td(f"{rung.contracts_needed:,}"),
            html.Td(fmt.percent(rung.achieved_convexity_pct)),
            html.Td(verdict),
        ],
    )


def _ladder_panel_view(result: StrikeLadderResult) -> Component:
    """Render the solved rungs table, then the unsolvable cells.

    Unsolvable rungs are shown, never dropped — see
    :func:`_unsolvable_rung_line` for the finding-ID note. #326's third
    mode: when nothing at all solved, that is its own dead end (the
    engine ran and answered "nothing"), rendered as a
    :attr:`NoticeKind.EMPTY` notice rather than as a bare "Unsolvable"
    heading — the same table-less shape #326 reported as
    indistinguishable from a panel that had not built yet.
    """
    if not result.rungs and not result.unsolvable:
        # Unreachable by construction: _render_ladder_panel_logic only
        # calls build_strike_ladder with two non-empty sequences (a
        # None list already short-circuits to the INPUT notice above
        # it), and itertools.product of two non-empty sequences always
        # yields at least one cell, which lands in rungs or unsolvable.
        # Kept as a real INPUT notice rather than deleted, in case that
        # invariant ever changes.
        return _incomplete("No rungs requested.")

    if not result.rungs:
        return panel_notice(
            "No rung solves at these inputs.",
            kind=NoticeKind.EMPTY,
            body=[_unsolvable_rung_line(rung) for rung in result.unsolvable],
        )

    header = html.Tr(
        [
            html.Th("Delta"),
            html.Th("Maturity"),
            html.Th("Strike"),
            html.Th("%OTM"),
            html.Th("Put delta"),
            html.Th("Premium"),
            html.Th("Crash payoff"),
            html.Th("Contracts"),
            html.Th("Achieved convexity"),
            html.Th("Budget"),
        ],
    )
    rows = [_ladder_rung_row(rung) for rung in result.rungs]
    children: list[Component] = [
        html.Table(
            [html.Thead(header), html.Tbody(rows)],
            className="planning-table",
        ),
    ]
    if result.unsolvable:
        # A partial answer, not an empty one -- the table above already
        # says the panel worked, so this stays plain markup rather than
        # a second notice.
        children.append(html.H4("Unsolvable"))
        children.extend(
            _unsolvable_rung_line(rung) for rung in result.unsolvable
        )
    return html.Div(children)


def _render_ladder_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    target_deltas_raw: str | None,
    maturities_years_raw: str | None,
) -> Component:
    """Render the strike ladder for comma-separated deltas/maturities."""
    target_deltas = _parse_float_list(target_deltas_raw)
    maturities_years = _parse_float_list(maturities_years_raw)
    if target_deltas is None or maturities_years is None:
        return _incomplete(
            "Enter comma-separated deltas and maturities, e.g. "
            "0.05, 0.10, 0.15 and 0.25, 0.5, 1.0.",
        )

    def _build() -> Component:
        result = build_strike_ladder(
            portfolio,
            ips_config,
            target_deltas=target_deltas,
            maturities_years=maturities_years,
        )
        return _ladder_panel_view(result)

    return _safe_render(_build, blocked_hint=_LADDER_BLOCKED_HINT)


def _otm_pair_text(moneyness: MoneynessDrift) -> str:
    """Format "entry OTM% / current OTM%", entry as "n/a" when unrecorded."""
    entry = (
        fmt.signed_percent(moneyness.entry_otm_pct)
        if moneyness.entry_otm_pct is not None
        else "n/a"
    )
    return f"{entry} / {fmt.signed_percent(moneyness.current_otm_pct)}"


def _dte_text(record: RollStatusRecord) -> str:
    """Days-to-maturity cell — or the expiry date for a leg already gone.

    ``-435d / 180d`` is technically the day count but reads as an extreme
    roll urgency; the sign is the only signal and it is easy to miss (#373).
    """
    if record.verdict is RollVerdict.EXPIRED:
        return f"expired {record.position.option.maturity_date.date()}"
    return f"{record.days_to_maturity}d / {record.roll_window_days}d"


def _leg_convexity_text(record: RollStatusRecord) -> str:
    """Render this leg's own contribution to book crash convexity (#306).

    The neighbouring Convexity cell is a **book-level** gate — the IPS band
    is stated against the whole book, so it cannot be applied per leg. This
    cell is the per-tranche number that gate never carried: contributions
    sum exactly to the book figure, so this is the column that answers
    *which* tranche to roll.

    ``n/a`` for an expired leg, which was never priced — not ``+0.00``,
    which would read as a worthless leg rather than an unpriced one.
    """
    contribution = record.leg_convexity_contribution_pct
    if contribution is None:
        return "n/a"
    return f"{contribution:+.2f} pp"


def _roll_record_row(record: RollStatusRecord) -> html.Tr:
    """One position's roll status, with all three trigger reasons (G3)."""
    position = record.position
    cost_text = (
        fmt.currency(record.estimated_roll_up_cost, decimals=2)
        if record.estimated_roll_up_cost is not None
        else "n/a"
    )
    return html.Tr(
        [
            html.Td(
                html.Span(
                    record.verdict.value,
                    className=(
                        "verdict-badge verdict-badge--"
                        f"{record.verdict.value.lower()}"
                    ),
                ),
            ),
            html.Td(
                f"{position.option.option_type.value} "
                f"{position.option.strike_price:,.0f}",
            ),
            html.Td(_otm_pair_text(record.moneyness)),
            html.Td(_dte_text(record)),
            html.Td(cost_text),
            html.Td(_leg_convexity_text(record)),
            html.Td(
                f"Time: {record.time_trigger.verdict.value} — "
                f"{record.time_trigger.reason}"
            ),
            html.Td(
                f"Convexity (book): {record.convexity_trigger.verdict.value}"
                f" — {record.convexity_trigger.reason}",
            ),
            html.Td(
                f"Rally: {record.rally_trigger.verdict.value} — "
                f"{record.rally_trigger.reason}",
            ),
        ],
    )


def _roll_panel_view(records: list[RollStatusRecord]) -> Component:
    """Render the per-position roll table.

    The evidence layer under the roll plan above: every position (not
    just long puts) and every trigger reading behind its verdict.
    """
    intro = html.P(
        "The evidence behind the roll plan above — every position in "
        "the book, and how each of its three IPS triggers reads. The "
        "plan turns these grades into an action; this table is where "
        "you check one.",
        className="plain-language",
    )
    if not records:
        return html.Div(
            [
                intro,
                html.P(
                    "No positions in the book yet.",
                    className="plain-language",
                ),
            ],
        )

    header = html.Tr(
        [
            html.Th("Verdict"),
            html.Th("Position"),
            html.Th("OTM entry / now"),
            html.Th("DTE / window"),
            html.Th("Est. roll-up cost"),
            html.Th("This leg's convexity"),
            html.Th("Time trigger"),
            html.Th("Convexity trigger (book)"),
            html.Th("Rally trigger"),
        ],
    )
    rows = [_roll_record_row(record) for record in records]
    return html.Div(
        [
            intro,
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="planning-table",
            ),
        ],
    )


def _render_roll_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the roll status table for every position in the book."""
    return _safe_render(
        lambda: _roll_panel_view(evaluate_roll_status(portfolio, ips_config)),
    )


def _roll_plan_row(record: RollPlanRecord, *, grouped: bool = False) -> html.Tr:
    """One long put's recommended action, proposal, and reasoning.

    The reasoning cell is not decoration. ``DELAY`` is a recommendation
    to *not* act on a trigger that has fired, so it has to arrive with
    its justification attached or it reads as the tool losing the
    signal.

    Args:
        record: The leg to render.
        grouped: Whether this row sits under a
            :func:`_plan_group_header_row` — when it does, the header
            already names the structure, so the leg text drops the
            redundant ``(structure_id)`` suffix (#333).

    """
    strike_text = (
        f"{record.target_strike:,.0f}"
        if record.target_strike is not None
        else "n/a"
    )
    cost_text = (
        fmt.signed_currency(record.roll_up_cost)
        if record.roll_up_cost is not None
        else "n/a"
    )
    excluded = record.action is None
    action_text = (
        "—" if record.action is None else record.action.value.replace("_", " ")
    )
    action_class = (
        "verdict-badge verdict-badge--excluded"
        if record.action is None
        else f"verdict-badge verdict-badge--{record.action.value.lower()}"
    )
    row_classes = " ".join(
        cls
        for cls in (
            "plan-row--excluded" if excluded else None,
            "plan-row--grouped" if grouped else None,
        )
        if cls is not None
    )
    return html.Tr(
        [
            html.Td(html.Span(action_text, className=action_class)),
            html.Td(_plan_leg_text(record, show_structure_suffix=not grouped)),
            html.Td(strike_text),
            html.Td(cost_text),
            html.Td(f"{record.gamma:,.4f} / {record.theta:,.2f}"),
            html.Td(record.rationale, className="plan-rationale"),
        ],
        className=row_classes or None,
    )


def _plan_leg_text(
    record: RollPlanRecord,
    *,
    show_structure_suffix: bool = True,
) -> str:
    """Name the leg, and the structure it rolls with when it has one.

    ``show_structure_suffix=False`` drops the ``(structure_id)`` suffix for
    a row already sitting under that structure's group header (#333) — the
    tag would otherwise be said twice.
    """
    position = record.position
    leg = (
        f"{position.option.option_type.value} "
        f"{position.option.strike_price:,.0f}"
    )
    if record.structure_id is None or not show_structure_suffix:
        return leg
    return f"{leg} ({record.structure_id})"


def _group_plan_records(
    records: list[RollPlanRecord],
) -> list[tuple[str | None, list[RollPlanRecord]]]:
    """Cluster *records* by ``structure_id`` for display only (#333).

    Pure rendering grouping — the underlying records are unchanged, one
    per leg, in whatever order ``build_roll_plan`` returned them. This
    only decides how they're clustered on screen: legs sharing a tag move
    together, in the order their tag was first seen; a leg with no tag is
    always its own singleton group. Mirrors
    :func:`~deltadewa.analysis.roll_planner.group_into_structures`'s own
    tag-or-singleton grouping, but over :class:`RollPlanRecord` rather
    than ``OptionPosition``.
    """
    grouped: dict[object, list[RollPlanRecord]] = {}
    for record in records:
        tag = record.structure_id
        key: object = tag if tag is not None else object()
        grouped.setdefault(key, []).append(record)
    return [(legs[0].structure_id, legs) for legs in grouped.values()]


def _plan_group_header_row(
    structure_id: str,
    legs: list[RollPlanRecord],
) -> html.Tr:
    """One header row naming a multi-leg structure's grouped rows (#333).

    Target strike and roll-up cost are already identical across every leg
    in the group — netted once in ``roll_planner`` — so they are stated
    here rather than repeated silently on each leg row below.
    """
    priced = next((r for r in legs if r.target_strike is not None), None)
    strike_text = (
        f"target {priced.target_strike:,.0f}" if priced is not None else "n/a"
    )
    cost_text = (
        fmt.signed_currency(priced.roll_up_cost)
        if priced is not None and priced.roll_up_cost is not None
        else "n/a"
    )
    return html.Tr(
        html.Td(
            f"{structure_id} — {len(legs)} legs, rolled as one structure "
            f"({strike_text}, net cost {cost_text})",
            colSpan=6,
            className="plan-group-header",
        ),
    )


def _roll_plan_panel_view(records: list[RollPlanRecord]) -> Component:
    """Render the per-put roll plan: action, proposal, and reasoning.

    Deliberately a separate panel from the roll status table below it,
    and deliberately not a second opinion on the same question. The
    table grades each tranche's three triggers; this turns those grades
    into one action per long put, applying the handbook's gamma/theta
    nuance that the table's verdicts have no vocabulary for — and says
    what to roll *to* and what that would cost.
    """
    intro = html.P(
        "One recommended action per leg — what to roll it to, and what "
        "that roll would cost. Built on the same trigger grades as the "
        "roll status table below, so the two never disagree: this panel "
        "adds the handbook's gamma/theta judgement, which is the only "
        "thing that can turn a fired trigger into DELAY. Legs that get no "
        "recommendation of their own — short legs of a spread, non-puts, "
        "expired legs — are still listed, greyed, with the reason: a leg "
        "the planner skipped must never just be absent.",
        className="plain-language",
    )
    if not records:
        return html.Div(
            [
                intro,
                html.P(
                    "No positions in the book yet.",
                    className="plain-language",
                ),
            ],
        )

    header = html.Tr(
        [
            html.Th("Action"),
            html.Th("Position"),
            html.Th("Target strike"),
            html.Th("Roll-up cost"),
            html.Th("Gamma / theta"),
            html.Th("Reasoning"),
        ],
    )
    rows: list[html.Tr] = []
    for structure_id, legs in _group_plan_records(records):
        if structure_id is not None and len(legs) > 1:
            rows.append(_plan_group_header_row(structure_id, legs))
            rows.extend(_roll_plan_row(r, grouped=True) for r in legs)
        else:
            rows.extend(_roll_plan_row(r) for r in legs)
    return html.Div(
        [
            intro,
            html.Table(
                [
                    html.Thead(header),
                    html.Tbody(rows),
                ],
                className="planning-table",
            ),
        ],
    )


def _render_roll_plan_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the roll plan for every long put in the book."""
    return _safe_render(
        lambda: _roll_plan_panel_view(build_roll_plan(portfolio, ips_config)),
    )


def _render_provenance_panel_logic(
    *,
    app: ProgramDashApp,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the pricing-input provenance panel (Batch 3d, #367/#368).

    Reassesses market data fresh in this closure rather than sharing
    ``render()``'s own ``market_env`` — ``assess_market_environment``
    never raises, so sharing would be safe, but a fresh call here keeps
    this panel's isolation independent of whatever ``render()`` happens
    to compute elsewhere, matching monitor.py's convention for this
    specific panel.
    """

    def _build() -> Component:
        environment = assess_market_environment(
            app.market_data,
            ips_config.market_environment,
        )
        ledger = build_provenance_ledger(
            environment,
            portfolio,
            ips_config.pricing_inputs,
            as_of=program_trading_date(ips_config.program.timezone).date(),
        )
        return build_provenance_panel(ledger)

    return _safe_render(_build)


def _monetization_step_row(step: MonetizationStepStatus) -> html.Tr:
    """One row of the IPS monetization schedule."""
    return html.Tr(
        [
            html.Td(fmt.percent(step.gain_pct)),
            html.Td(fmt.percent(step.sell_pct)),
            html.Td("triggered" if step.triggered else "not yet"),
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
            [html.Th("Gain trigger"), html.Th("Sell %"), html.Th("Status")],
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
    # #316: the sizing/ladder maturity dials' initial values come from
    # policy (entry tenor / maintain range), not a hardcoded 0.5y.
    sizing_maturity_default = ips_config.maturity_selection.entry_tenor_years
    ladder_maturities_default = _ladder_maturities_text(
        ips_config.maturity_selection,
    )
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
            html.Div(
                [
                    html.H3(
                        [
                            "Market environment",
                            basis_chip(_BASIS_LIVE_MARKET_DATA),
                        ],
                    ),
                    html.Div(
                        _render_market_env_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                            market_env=market_env,
                        ),
                        id="plan-market-env-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(
                        ["Sizing workbench", basis_chip(_BASIS_CRASH_SKEW)]
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Strike (% OTM)"),
                                    dcc.Input(
                                        id="sizing-pct-otm",
                                        type="number",
                                        value=_DEFAULT_SIZING_PCT_OTM,
                                        debounce=True,
                                    ),
                                ],
                                className="editor-field",
                            ),
                            html.Div(
                                [
                                    html.Label("Maturity (years)"),
                                    dcc.Input(
                                        id="sizing-maturity-years",
                                        type="number",
                                        value=sizing_maturity_default,
                                        debounce=True,
                                    ),
                                ],
                                className="editor-field",
                            ),
                            html.Div(
                                [
                                    html.Label("Vol override (optional)"),
                                    dcc.Input(
                                        id="sizing-vol-override",
                                        type="number",
                                        debounce=True,
                                    ),
                                ],
                                className="editor-field",
                            ),
                        ],
                        className="editor-form",
                    ),
                    html.Div(
                        _render_sizing_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                            pct_otm=_DEFAULT_SIZING_PCT_OTM,
                            maturity_years=sizing_maturity_default,
                            vol_override=None,
                        ),
                        id="plan-sizing-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(["Strike ladder", basis_chip(_BASIS_CRASH_SKEW)]),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Target deltas"),
                                    dcc.Input(
                                        id="ladder-target-deltas",
                                        type="text",
                                        value=_DEFAULT_LADDER_TARGET_DELTAS,
                                        debounce=True,
                                    ),
                                ],
                                className="editor-field",
                            ),
                            html.Div(
                                [
                                    html.Label("Maturities (years)"),
                                    dcc.Input(
                                        id="ladder-maturities-years",
                                        type="text",
                                        value=ladder_maturities_default,
                                        debounce=True,
                                    ),
                                ],
                                className="editor-field",
                            ),
                        ],
                        className="editor-form",
                    ),
                    html.Div(
                        _render_ladder_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                            target_deltas_raw=_DEFAULT_LADDER_TARGET_DELTAS,
                            maturities_years_raw=ladder_maturities_default,
                        ),
                        id="plan-ladder-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(["Roll plan", basis_chip(_BASIS_CRASH_SKEW)]),
                    html.Div(
                        _render_roll_plan_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                        ),
                        id="plan-roll-plan-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(
                        [
                            "Roll status by tranche",
                            basis_chip(_BASIS_CRASH_SKEW),
                        ],
                    ),
                    html.Div(
                        _render_roll_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                        ),
                        id="plan-roll-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    # No basis chip: unlike every other PLANNING panel,
                    # this one grades staleness, not a priced quantity —
                    # there is no crash-skew or book-greeks basis for it
                    # to name (Batch 3d, #367/#368).
                    html.H3("Pricing input provenance"),
                    html.Div(
                        _render_provenance_panel_logic(
                            app=app,
                            portfolio=portfolio,
                            ips_config=ips_config,
                        ),
                        id="plan-provenance-panel",
                    ),
                    dcc.ConfirmDialogProvider(
                        id="mark-inputs-reviewed-confirm",
                        message=(
                            "Mark every hand-entered pricing input "
                            "(spot, risk-free rate, dividend yield, and "
                            "every leg's volatility) as confirmed "
                            "current, as of now? This clears any "
                            "existing staleness signal — it does not "
                            "change any value, only its confirmed date."
                        ),
                        children=html.Button(
                            "Mark pricing inputs reviewed",
                            className="btn btn-secondary",
                        ),
                    ),
                ],
                className="panel",
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
            html.Div(
                [
                    html.H3(["Monetization", basis_chip(_BASIS_CRASH_SKEW)]),
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

    @app.callback(
        Output("plan-sizing-panel", "children"),
        Input("book-version", "data"),
        Input("sizing-pct-otm", "value"),
        Input("sizing-maturity-years", "value"),
        Input("sizing-vol-override", "value"),
    )
    def _render_sizing_panel(
        _version: int,
        pct_otm: float | None,
        maturity_years: float | None,
        vol_override: float | None,
    ) -> Component:
        return _render_sizing_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            pct_otm=pct_otm,
            maturity_years=maturity_years,
            vol_override=vol_override,
        )

    @app.callback(
        Output("plan-ladder-panel", "children"),
        Input("book-version", "data"),
        Input("ladder-target-deltas", "value"),
        Input("ladder-maturities-years", "value"),
    )
    def _render_ladder_panel(
        _version: int,
        target_deltas_raw: str | None,
        maturities_years_raw: str | None,
    ) -> Component:
        return _render_ladder_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            target_deltas_raw=target_deltas_raw,
            maturities_years_raw=maturities_years_raw,
        )

    @app.callback(
        Output("plan-roll-plan-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_roll_plan_panel(_version: int) -> Component:
        return _render_roll_plan_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    @app.callback(
        Output("plan-roll-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_roll_panel(_version: int) -> Component:
        return _render_roll_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    @app.callback(
        Output("plan-provenance-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_provenance_panel(_version: int) -> Component:
        return _render_provenance_panel_logic(
            app=app,
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    @app.callback(
        Output("book-version", "data", allow_duplicate=True),
        Output("mutation-status", "children", allow_duplicate=True),
        Input("mark-inputs-reviewed-confirm", "submit_n_clicks"),
        State("book-version", "data"),
        prevent_initial_call=True,
    )
    def _mark_inputs_reviewed(
        submit_n_clicks: int | None,
        version: int,
    ) -> tuple[Any, Any]:
        if not submit_n_clicks:
            return no_update, no_update
        return _mark_inputs_reviewed_logic(
            version=version,
            state=app.program_state,
        )

    @app.callback(
        Output("plan-monetization-panel", "children"),
        Input("book-version", "data"),
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
        Output("plan-market-env-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_market_env_panel(_version: int) -> Component:
        # Watches book-version like every other PLANNING panel: the readings
        # themselves don't depend on the book, but the decision verdict does
        # (it takes current convexity and the monetization plan), so an edit
        # that moves convexity out of band has to move this verdict too.
        return _render_market_env_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            market_env=assess_market_environment(
                app.market_data,
                ips_config.market_environment,
            ),
        )

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
