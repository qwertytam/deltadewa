"""PLANNING zone: the Market Environment panel (Part X #6, #7, #8).

The three readings :func:`~deltadewa.analysis.decision_matrix.decision_matrix`
takes, shown together with the verdict they produce. Splitting them
across surfaces — the numbers nowhere, the verdict in the Sunday
digest — is what the 2026-08-06 re-audit found had lost them.

The market-environment snapshot (``market_env``) is a parameter, not
computed here: ``page.py``'s ``render()`` assesses it once and passes
the same snapshot to both this panel and ``monetization.py`` — a
second fetch could return a different reading, and the two panels
would then disagree on the same page. Each panel's own callback keeps
its own independent re-assessment, since a callback fires later than
the render it followed and there is no snapshot from that render left
to share.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

from dash import Input, Output, html

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.analysis.decision_matrix import (
    decision_matrix,
    entry_timing_tree,
)
from deltadewa.analysis.market_environment import (
    assess_market_environment,
    describe_skew_percentile,
)
from deltadewa.analysis.monetization import build_monetization_plan
from deltadewa.app.bands import band_bar
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from collections.abc import Callable

    from dash.development.base_component import Component

    from deltadewa.analysis.decision_matrix import (
        DecisionResult,
        EntryTimingResult,
        EntryTimingStep,
    )
    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig, IpsMarketEnvironment
    from deltadewa.portfolio.core import OptionPortfolio

# The market-environment panel reprices nothing — it reads the live feed —
# so it must not carry PLANNING's crash-skew chip.
_BASIS_LIVE_MARKET_DATA = "basis: live market data"

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-market-environment",
    title="Market environment",
)


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


def _band_position_text(position: float | None) -> str:
    """Say where VIX sits in the IPS band — never as a "percentile".

    ``MarketEnvironment.regime_band_position_pct`` is a clamped band
    position, not a rank against history (8c, N5). Rendered as "regime
    percentile 0" it read as "the cheapest VIX of the year" on days VIX
    merely sat below 15, and "regime percentile 53" on a day VIX ranked
    95th over the trailing year. At the clamps the honest statement is
    which edge it is past, not a 0 or 100.
    """
    if position is None:
        return ""
    if position <= 0.0:
        return " — at or below the band's low end"
    if position >= 100.0:  # the clamp's own upper bound, not policy
        return " — at or above the band's high end"
    return f" — {position:.0f}% of the way up the band"


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

    position = _band_position_text(market_env.regime_band_position_pct)
    # The IPS band is decimal implied vol compared against VIX/100
    # (market_environment.classify_vix_regime), so the bar is drawn on the
    # VIX level in vol points — the units the reading is actually in —
    # rather than on the derived band position.
    return _env_metric_row(
        label="Vol regime",
        headline=f"{market_env.regime_label.value} — VIX {market_env.vix:.1f}",
        detail=(
            f"IPS band {policy.vol_regime_low * 100:.0f}-"
            f"{policy.vol_regime_high * 100:.0f} VIX points{position}"
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
        # The window is stated every time (#317) — the handbook's condition
        # for ranking skew over any window at all.
        headline=describe_skew_percentile(
            market_env.skew_percentile,
            market_env.skew_lookback_days,
        ),
        detail=(
            f"IPS band {policy.skew_low_pctile:.0f}-"
            f"{policy.skew_high_pctile:.0f}{index_text}"
        ),
        bar=band_bar(
            value=percentile_pct,
            low=policy.skew_low_pctile,
            high=policy.skew_high_pctile,
            fmt=lambda v: f"{v:.0f}",
        ),
    )


def _forward_variance_row(market_env: MarketEnvironment) -> Component:
    """Part X #8 — forward variance, as a level with no band.

    The handbook reads forward variance cheap/normal/high but gives no
    cut, and the program ranks no forward-variance history, so this row
    deliberately gets no ``band_bar`` and no chip: a band here would be
    invented policy (borrowing skew's 30/70 would misapply bands the
    handbook says its skew page "owns").

    The text says what substitutes for the band, and says it exactly
    (N11, #417). The pre-8c wording told the reader to "read against the
    hedge-cost verdict", but ``_hedge_cost_verdict`` never reads forward
    variance — it reads the term-structure *shape*, which says whether
    3-month vol sits above or below the front, not whether either is
    cheap against its own history. The data for a real percentile exists
    (Cboe VIX3M history back to 2007, already cached in full); the
    missing piece is a handbook band to grade it against.
    """
    if market_env.forward_vol_front_3m is None:
        return _env_unavailable_row(
            "Forward variance",
            "needs both VIX and VIX3M; one is missing",
        )

    shape_text = (
        f"The term-structure shape ({market_env.term_shape.value.lower()})"
        if market_env.term_shape is not None
        else "The term-structure shape"
    )
    return _env_metric_row(
        label="Forward variance",
        headline=f"{market_env.forward_vol_front_3m:.1f} vol points",
        detail=(
            "Front-to-3M implied forward vol. No historical band: the "
            "handbook gives no cheap/normal/high cut, and the program "
            "ranks no forward-variance history. "
            f"{shape_text} is what feeds the hedge-cost verdict in its "
            "place — it says whether 3-month vol sits above or below the "
            "front, not whether either is cheap against its own history."
        ),
    )


def _verdict_word(token: str) -> str:
    """Render an analysis verdict token for a reader.

    ``INSUFFICIENT_DATA`` is an enum value, not a word; the panel shows it
    as ``INSUFFICIENT DATA`` (N5). Single-word verdicts (``BUY``,
    ``CHEAP``) pass through unchanged.
    """
    return token.replace("_", " ")


def _vix_step_value(value: float | str, _env: MarketEnvironment) -> str:
    return f"{float(value):.1f}"


def _skew_step_value(value: float | str, env: MarketEnvironment) -> str:
    # The same formatter as the skew row above, so step 2 and the row
    # cannot disagree on rounding or omit the window (#317).
    return describe_skew_percentile(float(value), env.skew_lookback_days)


def _term_step_value(value: float | str, _env: MarketEnvironment) -> str:
    return str(value).lower()


class _StepFormat(NamedTuple):
    """How one entry-timing step's factor reads on the page."""

    name: str
    value: Callable[[float | str, MarketEnvironment], str]


#: N5: every factor label ``entry_timing_tree`` emits, mapped to the words a
#: reader sees. Before this the panel rendered the label and value raw —
#: ``skew_percentile: 0.876984126984127``. A test drives the tree through
#: every branch and fails if a label is missing from this table.
TIMING_STEP_FORMATS: Final[dict[str, _StepFormat]] = {
    "VIX": _StepFormat("VIX", _vix_step_value),
    "skew_percentile": _StepFormat("Skew", _skew_step_value),
    "term_shape": _StepFormat("Term structure", _term_step_value),
}


def format_timing_step(
    step: EntryTimingStep,
    market_env: MarketEnvironment,
) -> str:
    """Render one entry-timing step as a sentence a reader can use."""
    fmt = TIMING_STEP_FORMATS.get(step.label)
    # Unreachable for any label the tree emits today (pinned by test); a
    # new label still reads as words rather than a Python identifier.
    name = fmt.name if fmt is not None else step.label.replace("_", " ")
    if step.value is None:
        value_text = "unavailable"
    elif fmt is not None:
        value_text = fmt.value(step.value, market_env)
    else:
        value_text = str(step.value)
    return f"{step.step}. {name}: {value_text} — {step.recommendation}"


def _entry_timing_rows(
    timing: EntryTimingResult,
    market_env: MarketEnvironment,
) -> list[Component]:
    """Render the entry-timing tree's path, step by step."""
    rows: list[Component] = [
        html.P(
            f"Entry timing: {_verdict_word(timing.recommendation)}",
            className="env-verdict",
        ),
    ]
    if timing.data_quality_note is not None:
        rows.append(
            html.P(timing.data_quality_note, className="plain-language"),
        )
    rows.extend(
        html.P(
            format_timing_step(step, market_env),
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
                f"Decision: {_verdict_word(decision.verdict.value)} — "
                f"{decision.rationale}",
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
            *_entry_timing_rows(timing, market_env),
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
                skew_high=(
                    ips_config.market_environment.skew_high_pctile / 100.0
                ),
                skew_low=ips_config.market_environment.skew_low_pctile / 100.0,
            ),
            ips_config.market_environment,
        )

    return _safe_render(_build)


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    market_env: MarketEnvironment,
) -> html.Div:
    """Build the Market Environment panel."""
    return html.Div(
        [
            html.H3(
                [
                    SECTION.title,
                    basis_chip(_BASIS_LIVE_MARKET_DATA),
                ],
                id=SECTION.anchor_id,
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
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Market Environment panel's re-render callback."""

    @app.callback(
        Output("plan-market-env-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
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
