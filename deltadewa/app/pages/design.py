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

Every mutating callback routes through a module-level ``_..._logic``
function that is directly callable from tests (the ``@app.callback``-
decorated function is a thin wrapper reading Dash-specific context, e.g.
``dash.ctx``, and handing plain values to it). Failures are contained by
:func:`_guarded_mutation` — except :func:`_import_logic`, which needs to
tell a policy refusal apart from any other failure and so handles its
own try/except — so nothing here ever leaks a traceback to the browser,
and a failed mutation never bumps ``book-version``: the single
``dcc.Store`` every read-only panel in this page (BOOK's position table,
every PLANNING panel, and every EXPLORATION panel) watches for "the book
changed, re-read it." PLANNING's and EXPLORATION's own reads have no
mutator to guard, so they use :func:`_safe_render` instead — the same
no-leaked-traceback discipline, applied to an engine ``ValueError`` (a
structurally missing input, e.g. no underlying position or an
out-of-range dial) rather than a failed mutation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from dash import ALL, Input, Output, State, ctx, dcc, html, no_update
from dash.development.base_component import Component

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.analysis.decision_matrix import (
    decision_matrix,
    entry_timing_tree,
)
from deltadewa.analysis.health import NO_LONG_PUTS_CLIFF_DAYS
from deltadewa.analysis.hedge_triggers import (
    HedgeTriggerThresholds,
    evaluate_hedge_trigger_set,
)
from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.analysis.monetization import build_monetization_plan
from deltadewa.analysis.repricing import proportional_vol
from deltadewa.analysis.roll_status import evaluate_roll_status
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
from deltadewa.app.shape_notice import shape_notice_text
from deltadewa.clock import program_now
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.monte_carlo import drift_measure_label
from deltadewa.state import ConfirmationRequiredError
from deltadewa.visualization.distribution_charts_plotly import (
    plot_pnl_distribution,
)
from deltadewa.visualization.stress_charts_plotly import (
    STRESS_METRICS,
    plot_spot_vol_heatmap,
    plot_time_price_heatmap,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from deltadewa.analysis.cache import ScenarioGridCache
    from deltadewa.analysis.decision_matrix import (
        DecisionResult,
        EntryTimingResult,
    )
    from deltadewa.analysis.hedge_triggers import (
        HedgeTriggerReason,
        HedgeTriggerSet,
    )
    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.analysis.maturity import MaturityVegaExposure
    from deltadewa.analysis.monetization import (
        MonetizationPlan,
        MonetizationStepStatus,
    )
    from deltadewa.analysis.roll_status import MoneynessDrift, RollStatusRecord
    from deltadewa.analysis.scenarios import DeltaDrift, DeltaDriftLeg
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
        IpsConvexity,
        IpsMarketEnvironment,
    )
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition
    from deltadewa.state import ProgramState

_logger = logging.getLogger(__name__)

_REQUIRED_ADD_FIELDS_MSG = "Strike, maturity, and quantity are required."

# PLANNING zone: dial defaults. Carried over from the sizing/ladder cells of
# hedge_design.ipynb, which Stage 4.3 deleted — these are the starting point
# that notebook hardcoded, kept here as adjustable dial defaults. They are
# presentation, not policy: nothing grades against them.
_DEFAULT_SIZING_PCT_OTM = 20.0
_DEFAULT_SIZING_MATURITY_YEARS = 0.5
_DEFAULT_LADDER_TARGET_DELTAS = "0.05, 0.10, 0.15"
_DEFAULT_LADDER_MATURITIES_YEARS = "0.25, 0.5, 1.0"

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
# Nor does the delta drift panel: it reprices at the handbook's own fixed
# -5% spot shock (Part X §13), not the IPS crash anchor -- a distinct basis
# from every other PLANNING panel.
_BASIS_MINUS_5PCT = "basis: spot -5%, flat vol (not the IPS crash)"
# Nor does the convexity cliff panel, which is the only PLANNING panel that
# touches no market input whatsoever: it compares each long put's maturity date
# against the valuation date. Nothing is priced and no Greek is read, so it
# cannot honestly carry even the book-Greeks chip.
_BASIS_MATURITY_CALENDAR = "basis: position maturities (nothing priced)"
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


def _no_ips_layout() -> html.Div:
    """Build the single "no IPS policy loaded" state for the /design page."""
    return html.Div(
        [
            html.H1("Design"),
            html.P(
                "No IPS policy is loaded, so there is no policy to plan "
                "against — sizing targets, ladder bands, and roll "
                "thresholds are all policy-derived, and the position "
                "editor's exercise-style default has no source either. "
                "Check that config/ips.yaml (or whatever path this "
                "program state was loaded with) exists and parses — see "
                "the server log at startup for the reason it was "
                "skipped.",
                className="no-ips-message",
            ),
        ],
        className="page page-design",
    )


def _status(message: str, *, error: bool) -> html.Div:
    """Build a status line for the BOOK zone's mutation feedback."""
    modifier = "error" if error else "success"
    return html.Div(
        message,
        className=f"status-message status-message--{modifier}",
    )


def _guarded_mutation(action: Callable[[], None]) -> str | None:
    """Run a ``ProgramState`` mutator; never let it leak a traceback.

    Args:
        action: A zero-argument callable performing exactly one
            ``ProgramState`` mutation. Its return value is ignored — the
            caller supplies its own success message, since this only
            ever reports failure.

    Returns:
        ``None`` on success, or a clean, user-facing message on failure.

    """
    try:
        action()
    except ConfirmationRequiredError as exc:
        return str(exc)
    except (ValueError, IndexError) as exc:
        return str(exc)
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Unexpected error applying a /design mutation")
        return "Something went wrong — see the server log."
    return None


def _position_row(index: int, position: OptionPosition) -> html.Tr:
    """Build one editable <tr>: the position, plus a confirm-gated remove."""
    entry_premium_text = (
        f"{position.entry_premium:,.2f}"
        if position.entry_premium is not None
        else "—"
    )
    confirm_message = (
        f"Remove position {index}: {position.quantity:,.0f}x "
        f"{position.option.option_type.value} "
        f"{position.option.strike_price:,.0f} exp "
        f"{position.option.maturity_date.strftime('%Y-%m-%d')}? This "
        "cannot be undone from this page — re-add it manually if needed."
    )
    return html.Tr(
        [
            html.Td(f"{position.option.strike_price:,.0f}"),
            html.Td(position.option.option_type.value),
            html.Td(position.exercise_style.value),
            html.Td(position.option.maturity_date.strftime("%Y-%m-%d")),
            html.Td(f"{position.quantity:,.0f}"),
            html.Td(entry_premium_text),
            html.Td(
                dcc.ConfirmDialogProvider(
                    id={"type": "remove-confirm", "index": index},
                    message=confirm_message,
                    children=html.Button(
                        "Remove",
                        className="btn btn-remove",
                    ),
                ),
            ),
        ],
    )


def _net_delta_readout(portfolio: OptionPortfolio) -> Component:
    """Render Part X #10's scalar: net delta, right now.

    The grid form survived the Dash rebuild (``net_delta`` is one of the
    EXPLORATION heatmaps' metric options); the scalar the notebooks' Net
    Hedge Summary showed did not. It belongs beside the underlying quantity
    because that input is the other half of the same sentence — how much
    equity is held, and how much of it the options actually offset.
    """
    stats = portfolio.summary_stats()
    net_delta = stats.get("net_delta")
    if net_delta is None:
        return html.P(
            "Net delta is unavailable — the book's Greeks could not be "
            "computed.",
            className="plain-language",
        )
    return html.P(
        f"Net delta {net_delta:,.0f} against "
        f"{portfolio.underlying_quantity:,.0f} shares of underlying — the "
        "book's total directional exposure, options and equity combined.",
        className="plain-language",
    )


def _render_position_table_logic(
    *,
    portfolio: OptionPortfolio,
) -> Component:
    """Build the position table wholesale from the live portfolio.

    Always a full rebuild, never a ``Patch()`` — removing a position
    shifts every later index, so every remove button's id must be
    recomputed from the current list, not patched in place.
    """
    if not portfolio.positions:
        return html.P("No positions in the book yet.")

    header = html.Tr(
        [
            html.Th("Strike"),
            html.Th("Type"),
            html.Th("Exercise"),
            html.Th("Expiry"),
            html.Th("Quantity"),
            html.Th("Entry premium"),
            html.Th(""),
        ],
    )
    rows = [
        _position_row(index, position)
        for index, position in enumerate(portfolio.positions)
    ]
    return html.Table(
        [html.Thead(header), html.Tbody(rows)],
        className="position-table",
    )


def _add_position_logic(  # pylint: disable=too-many-arguments
    *,
    strike: float | None,
    maturity: str | None,
    quantity: float | None,
    option_type: str,
    exercise_style: str,
    entry_premium: float | None,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component, Any, Any, Any, Any, Any, Any]:
    """Add a position from the BOOK zone's add-form.

    Returns:
        A tuple matching the callback's Outputs: the new ``book-version``
        (or ``no_update`` on failure), a status message, and the six
        form fields' next values — cleared on success (so the operator
        isn't typing over stale values on the next add) and left as
        ``no_update`` on failure (so a typo can be fixed and resubmitted
        rather than retyped from scratch).

    """
    if strike is None or maturity is None or quantity is None:
        return (
            no_update,
            _status(_REQUIRED_ADD_FIELDS_MSG, error=True),
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
        )

    maturity_date = datetime.strptime(maturity, "%Y-%m-%d").replace(
        tzinfo=UTC,
    )

    def _do_add() -> None:
        # A plain def, not a lambda: state.add_position returns the new
        # OptionPosition, and _guarded_mutation's Callable[[], None]
        # discards a def's return value more predictably under mypy
        # than a lambda's inferred return type does.
        state.add_position(
            strike_price=strike,
            maturity_date=maturity_date,
            quantity=int(quantity),
            option_type=OptionType(option_type),
            exercise_style=ExerciseStyle(exercise_style),
            entry_premium=entry_premium,
        )

    error = _guarded_mutation(_do_add)
    if error is not None:
        return (
            no_update,
            _status(error, error=True),
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
        )

    # Reset the exercise-style field back to the IPS default rather than
    # whatever was just submitted — ips_config is guaranteed non-None in
    # practice (the page is gated on it), the None branch only exists so
    # this stays type-safe without a runtime assertion.
    reset_style = (
        state.ips_config.pricing.exercise_style.value
        if state.ips_config is not None
        else exercise_style
    )
    return (
        version + 1,
        _status("Added.", error=False),
        None,
        None,
        None,
        OptionType.PUT.value,
        reset_style,
        None,
    )


def _remove_position_logic(
    *,
    index: int,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component]:
    """Remove position *index* — the browser's confirm already happened.

    ``ConfirmDialogProvider``'s ``submit_n_clicks`` only increments once
    the native confirm dialog is accepted, so ``confirm=True`` is always
    correct here; the confirm gate lives client-side, not as a second
    Python-level check.
    """
    error = _guarded_mutation(
        lambda: state.remove_position(index, confirm=True),
    )
    if error is not None:
        return no_update, _status(error, error=True)
    return version + 1, _status("Removed.", error=False)


def _set_underlying_quantity_logic(
    *,
    value: float | None,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component]:
    """Set the underlying notional being hedged."""
    if value is None:
        return no_update, _status(
            "Underlying quantity cannot be blank.",
            error=True,
        )
    error = _guarded_mutation(lambda: state.set_underlying_quantity(value))
    if error is not None:
        return no_update, _status(error, error=True)
    return version + 1, _status("Underlying quantity updated.", error=False)


def _import_logic(
    *,
    confirm: bool,
    target: str | None,
    version: int,
    state: ProgramState,
) -> tuple[Any, Component, Any, Any]:
    """Import a portfolio export, refusing over unsaved changes.

    Doesn't route through :func:`_guarded_mutation` — unlike the other
    mutators, this needs to tell a policy refusal
    (``ConfirmationRequiredError``) apart from any other failure, since
    only a refusal should remember *target* and reveal the confirm row;
    any other failure (a bad path, a malformed file) should not offer
    "confirm and retry," since retrying would just fail again the same
    way.

    Returns:
        ``(book_version, status, pending_path, confirm_row_hidden)``.

    """
    if not target:
        # Unrelated to the confirm flow — leave any existing pending
        # path/reveal state exactly as it was.
        return (
            no_update,
            _status("An import path is required.", error=True),
            no_update,
            no_update,
        )

    try:
        state.import_portfolio(Path(target), confirm=confirm)
    except ConfirmationRequiredError as exc:
        return no_update, _status(str(exc), error=True), target, False
    except (ValueError, OSError) as exc:
        return no_update, _status(str(exc), error=True), no_update, True
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Unexpected error importing a /design portfolio")
        return (
            no_update,
            _status("Something went wrong — see the server log.", error=True),
            no_update,
            True,
        )
    return version + 1, _status("Imported.", error=False), None, True


def _export_logic(*, state: ProgramState) -> tuple[Any, Component]:
    """Snapshot the live book and package it for browser download.

    Read-only — doesn't touch ``book-version``, correctly outside the
    "failed mutation" concern entirely.
    """
    # Stamped in the program's timezone: the file name is what a human
    # sorts and cites, so it should read as the desk's clock, not UTC.
    stamp = program_now(
        state.ips_config.program.timezone
        if state.ips_config is not None
        else None,
    )
    filename = f"design-export-{stamp:%Y%m%dT%H%M%S}.json"
    try:
        path = state.export_snapshot(filename)
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Unexpected error exporting the /design book")
        return no_update, _status(
            "Something went wrong — see the server log.",
            error=True,
        )
    # dash has no stub for dcc.send_file.
    download = dcc.send_file(  # type: ignore[attr-defined,no-untyped-call]
        str(path),
    )
    return download, _status(f"Exported to {filename}.", error=False)


def _incomplete(message: str) -> html.P:
    """Build an "incomplete inputs" notice.

    Never render zeros for a missing or malformed dial — an unfinished
    input says so in words. Distinct from :func:`_status`: this isn't a
    failed action, there is no action to fail.
    """
    return html.P(message, className="plain-language")


def _safe_render(build: Callable[[], Component]) -> Component:
    """Render a PLANNING panel, turning a structural ``ValueError`` into text.

    Read-only counterpart to :func:`_guarded_mutation`. ``size_hedge`` and
    ``build_strike_ladder`` raise ``ValueError`` when the book has no
    underlying position rather than fabricating a zero result — this turns
    that into the panel's own "incomplete" message instead of a failed
    callback. Anything else (an unexpected engine failure) is logged and
    shown generically, the same no-leaked-traceback discipline the BOOK
    zone's mutators use.
    """
    try:
        return build()
    except ValueError as exc:
        return _incomplete(str(exc))
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception(
            "Unexpected error rendering a /design planning panel",
        )
        return _status(
            "Something went wrong — see the server log.",
            error=True,
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

        candidate = _safe_render(_build)

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
    :func:`_unsolvable_rung_line` for the finding-ID note.
    """
    if not result.rungs and not result.unsolvable:
        return _incomplete("No rungs requested.")

    children: list[Component] = []
    if result.rungs:
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
        children.append(
            html.Table(
                [html.Thead(header), html.Tbody(rows)],
                className="planning-table",
            ),
        )
    if result.unsolvable:
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

    return _safe_render(_build)


def _otm_pair_text(moneyness: MoneynessDrift) -> str:
    """Format "entry OTM% / current OTM%", entry as "n/a" when unrecorded."""
    entry = (
        fmt.signed_percent(moneyness.entry_otm_pct)
        if moneyness.entry_otm_pct is not None
        else "n/a"
    )
    return f"{entry} / {fmt.signed_percent(moneyness.current_otm_pct)}"


def _roll_record_row(record: RollStatusRecord) -> html.Tr:
    """One position's roll status, with all three trigger reasons (G3)."""
    position = record.position
    suppressed_note = (
        " (strike-drift roll suppressed — convexity in-band, no time pressure)"
        if record.suppressed
        else ""
    )
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
            html.Td(f"{record.days_to_maturity}d / {record.roll_window_days}d"),
            html.Td(cost_text),
            html.Td(
                f"Time: {record.time_trigger.verdict.value} — "
                f"{record.time_trigger.reason}"
            ),
            html.Td(
                f"Convexity: {record.convexity_trigger.verdict.value} — "
                f"{record.convexity_trigger.reason}",
            ),
            html.Td(
                f"Drift: {record.drift_trigger.verdict.value} — "
                f"{record.drift_trigger.reason}{suppressed_note}",
            ),
        ],
    )


def _roll_panel_view(records: list[RollStatusRecord]) -> Component:
    """Render the per-position roll table."""
    if not records:
        return html.P(
            "No positions in the book yet.",
            className="plain-language",
        )

    header = html.Tr(
        [
            html.Th("Verdict"),
            html.Th("Position"),
            html.Th("OTM entry / now"),
            html.Th("DTE / window"),
            html.Th("Est. roll-up cost"),
            html.Th("Time trigger"),
            html.Th("Convexity trigger"),
            html.Th("Drift trigger"),
        ],
    )
    rows = [_roll_record_row(record) for record in records]
    return html.Table(
        [html.Thead(header), html.Tbody(rows)],
        className="planning-table",
    )


def _render_roll_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the roll planner for every position in the book."""
    return _safe_render(
        lambda: _roll_panel_view(evaluate_roll_status(portfolio, ips_config)),
    )


def _hedge_trigger_row(trigger: HedgeTriggerReason) -> html.Tr:
    """One rebalance trigger: status badge, name, and the reason for it.

    Reuses the ``verdict-badge`` styling the roll table already uses, so
    the two tables read alike — but see :func:`_hedge_triggers_panel_view`
    for why they are not the same set.
    """
    return html.Tr(
        [
            html.Td(
                html.Span(
                    trigger.status.value,
                    className=(
                        "verdict-badge verdict-badge--"
                        f"{trigger.status.value.lower()}"
                    ),
                ),
            ),
            html.Td(trigger.label),
            html.Td(trigger.reason),
        ],
    )


def _hedge_triggers_panel_view(triggers: HedgeTriggerSet) -> Component:
    """Render the book-level rebalance triggers, each with its reasoning.

    Deliberately **not** merged into the roll planner directly above it,
    despite the shared vocabulary: the roll table asks "should this tranche
    be replaced" per position, while these four ask "is the book still
    hedged the way policy says" for the book as a whole. They are different
    questions with different thresholds, and a combined table would imply
    one verdict where there are two.
    """
    header = html.Tr(
        [html.Th("Status"), html.Th("Trigger"), html.Th("Reading vs policy")],
    )
    children: list[Component] = [
        html.P(
            "Book-level rebalance triggers — distinct from the roll planner "
            "above, which judges each tranche separately. These ask whether "
            "the book as a whole is still hedged the way the IPS says.",
            className="plain-language",
        ),
        html.Table(
            [
                html.Thead(header),
                html.Tbody([_hedge_trigger_row(t) for t in triggers]),
            ],
            className="planning-table",
        ),
    ]
    if triggers.actions:
        children.append(
            html.Ul(
                [
                    html.Li(f"{priority}: {description}")
                    for priority, description in triggers.actions
                ],
                className="trigger-actions",
            ),
        )
    else:
        children.append(
            html.P(
                "No action required — every trigger is inside its band.",
                className="plain-language",
            ),
        )
    return html.Div(children)


def _render_hedge_triggers_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the hedge rebalance triggers for the current book."""
    return _safe_render(
        lambda: _hedge_triggers_panel_view(
            evaluate_hedge_trigger_set(
                portfolio,
                HedgeTriggerThresholds.from_ips(ips_config.triggers),
            ),
        ),
    )


def _delta_drift_leg_row(leg: DeltaDriftLeg) -> html.Tr:
    """One option leg's delta today, at -5%, and the drift between them."""
    label = (
        f"{leg.position.option.option_type.value} "
        f"{leg.position.option.strike_price:,.0f}"
    )
    return html.Tr(
        [
            html.Td(label),
            html.Td(f"{leg.delta_now:,.1f}"),
            html.Td(f"{leg.delta_shocked:,.1f}"),
            html.Td(f"{leg.drift:,.1f}"),
        ],
    )


def _delta_drift_panel_view(drift: DeltaDrift) -> Component:
    """Render Part X §13: hedge delta today vs. at the handbook's -5% shock.

    Sits beside the hedge triggers panel — same "does the book need
    rebalancing" question, asked a different way: not whether a threshold
    has been crossed, but how quickly the hedge itself would start
    offsetting losses in an early-stage decline.
    """
    header = html.Tr(
        [
            html.Th("Leg"),
            html.Th("Delta now"),
            html.Th(f"Delta at {drift.shock_pct:.0f}%"),
            html.Th("Drift"),
        ],
    )
    return html.Div(
        [
            html.P(
                "Hedge-only delta (options, no underlying) today vs. "
                f"spot {drift.shock_pct:.0f}% — the handbook's own "
                "worked example, not the IPS crash scenario.",
                className="plain-language",
            ),
            html.P(
                f"Delta now {drift.delta_now:,.1f}, at "
                f"{drift.shock_pct:.0f}% {drift.delta_shocked:,.1f} — "
                f"drift {drift.drift:,.1f}.",
                className="env-verdict",
            ),
            html.Table(
                [
                    html.Thead(header),
                    html.Tbody(
                        [_delta_drift_leg_row(leg) for leg in drift.legs],
                    ),
                ],
                className="planning-table",
            ),
        ],
    )


def _render_delta_drift_panel_logic(
    *,
    portfolio: OptionPortfolio,
) -> Component:
    """Render the delta drift panel for the current book."""
    return _safe_render(
        lambda: _delta_drift_panel_view(
            PortfolioAnalyzer(portfolio).calculate_delta_drift(),
        ),
    )


def _cliff_verdict(days: int, conv: IpsConvexity) -> str:
    """Grade the cliff runway against the IPS review/urgent lines.

    One-sided by construction: more runway is better without limit, so there
    is no "too far from the cliff" verdict and deliberately no band bar. The
    vocabulary matches the hedge-trigger panel's so the two read consistently
    when a reader scans down the zone.
    """
    if days <= conv.cliff_urgent_days:
        return "URGENT"
    if days <= conv.cliff_review_days:
        return "REVIEW"
    return "OK"


def _convexity_cliff_panel_view(days: int, conv: IpsConvexity) -> Component:
    """Render Part X's "Time to Convexity Cliff" for the current book.

    Sits after delta drift because it answers the same rebalancing question on
    the calendar axis: not how the hedge behaves if spot moves now, but how
    long the book keeps the convexity it was bought for. A tail hedge that is
    still nominally in place can already have stopped paying off in a crash.

    The no-long-puts case is reported as unavailable rather than as the
    sentinel's numeric value — see
    :data:`~deltadewa.analysis.health.NO_LONG_PUTS_CLIFF_DAYS`.
    """
    if days == NO_LONG_PUTS_CLIFF_DAYS:
        return html.P(
            "The book holds no long puts, so there is no hedge convexity to "
            "decay and this metric does not apply.",
            className="plain-language",
        )
    lead = (
        "A long put loses convexity quickly once its remaining maturity gets "
        f"short. Counting from {conv.cliff_threshold_days} days to expiry as "
        "the start of that high-gamma region, "
    )
    if days == 0:
        # The engine floors the runway at zero, so it cannot say how far past
        # the boundary a leg already is: a put at 120 DTE and one at 30 DTE
        # both read 0 against a 180-day region. Saying "already inside"
        # rather than "0 days" keeps the panel from implying the two are the
        # same decision, without claiming a number it doesn't have.
        return html.Div(
            [
                html.P(
                    lead + "the nearest long put in the book is already "
                    "inside it.",
                    className="plain-language",
                ),
                html.P(
                    "Past the cliff — URGENT. Convexity is already decaying; "
                    "the roll trigger should have fired first "
                    f"({conv.cliff_review_days}d review, "
                    f"{conv.cliff_urgent_days}d urgent).",
                    className="env-verdict",
                ),
            ],
        )
    verdict = _cliff_verdict(days, conv)
    return html.Div(
        [
            html.P(
                lead + "the nearest long put in the book has "
                f"{days:,} days of runway before it gets there.",
                className="plain-language",
            ),
            html.P(
                f"{days:,} days to the cliff — {verdict} against the IPS "
                f"lines ({conv.cliff_review_days}d review, "
                f"{conv.cliff_urgent_days}d urgent).",
                className="env-verdict",
            ),
        ],
    )


def _render_convexity_cliff_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the convexity cliff panel for the current book."""
    return _safe_render(
        lambda: _convexity_cliff_panel_view(
            PortfolioAnalyzer(portfolio).calculate_convexity_cliff_days(
                cliff_threshold_days=ips_config.convexity.cliff_threshold_days,
            ),
            ips_config.convexity,
        ),
    )


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
) -> Component:
    """Render the vega term exposure panel for the current book."""
    return _safe_render(
        lambda: _vega_term_panel_view(
            PortfolioAnalyzer(portfolio).calculate_vega_by_maturity(),
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
        return _no_ips_layout()

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

    book_zone = html.Div(
        [
            html.H2("Book"),
            html.Div(
                [
                    html.Label("Underlying quantity"),
                    dcc.Input(
                        id="underlying-qty",
                        type="number",
                        value=portfolio.underlying_quantity,
                        debounce=True,
                    ),
                ],
                className="editor-field",
            ),
            html.Div(
                _safe_render(lambda: _net_delta_readout(portfolio)),
                id="net-delta-readout",
            ),
            html.H3("Add a position"),
            html.P(
                "Editing a position is remove + add, not in-place edit — "
                "there is no separate 'update' form.",
                className="plain-language",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Strike"),
                            dcc.Input(id="add-strike", type="number"),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Maturity"),
                            dcc.DatePickerSingle(id="add-maturity"),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Quantity"),
                            dcc.Input(id="add-quantity", type="number"),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Type"),
                            dcc.RadioItems(
                                id="add-option-type",
                                options=[
                                    OptionType.PUT.value,
                                    OptionType.CALL.value,
                                ],
                                value=OptionType.PUT.value,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Exercise style"),
                            dcc.RadioItems(
                                id="add-exercise-style",
                                options=[
                                    ExerciseStyle.EUROPEAN.value,
                                    ExerciseStyle.AMERICAN.value,
                                ],
                                value=default_style,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Entry premium (optional)"),
                            dcc.Input(
                                id="add-entry-premium",
                                type="number",
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Button(
                        "Add position",
                        id="add-submit",
                        className="btn btn-primary",
                    ),
                ],
                className="editor-form",
            ),
            html.Div(id="mutation-status"),
            html.H3("Positions"),
            html.Div(
                _render_position_table_logic(portfolio=portfolio),
                id="position-table",
            ),
            html.H3("Import / export"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Import path"),
                            dcc.Input(id="import-path", type="text"),
                        ],
                        className="editor-field",
                    ),
                    html.Button(
                        "Import",
                        id="import-submit",
                        className="btn btn-primary",
                    ),
                    html.Button(
                        "Export",
                        id="export-submit",
                        className="btn btn-primary",
                    ),
                ],
                className="editor-form",
            ),
            html.Div(
                [
                    html.P(
                        "Unsaved changes would be discarded by this import.",
                    ),
                    html.Button(
                        "Confirm & import",
                        id="import-confirm-submit",
                        className="btn btn-primary",
                    ),
                ],
                id="import-confirm-row",
                className="import-confirm-row",
                hidden=True,
            ),
            dcc.Download(id="export-download"),
            dcc.Store(id="book-version", data=0),
            dcc.Store(id="import-pending-path", data=None),
        ],
        className="zone-book",
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
                                        value=_DEFAULT_SIZING_MATURITY_YEARS,
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
                            maturity_years=_DEFAULT_SIZING_MATURITY_YEARS,
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
                                        value=_DEFAULT_LADDER_MATURITIES_YEARS,
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
                            maturities_years_raw=(
                                _DEFAULT_LADDER_MATURITIES_YEARS
                            ),
                        ),
                        id="plan-ladder-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(["Roll planner", basis_chip(_BASIS_CRASH_SKEW)]),
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
                    html.H3(
                        [
                            "Hedge rebalance triggers",
                            basis_chip(_BASIS_BOOK_GREEKS),
                        ],
                    ),
                    html.Div(
                        _render_hedge_triggers_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                        ),
                        id="plan-hedge-triggers-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(
                        ["Delta drift", basis_chip(_BASIS_MINUS_5PCT)],
                    ),
                    html.Div(
                        _render_delta_drift_panel_logic(portfolio=portfolio),
                        id="plan-delta-drift-panel",
                    ),
                ],
                className="panel",
            ),
            html.Div(
                [
                    html.H3(
                        [
                            "Convexity cliff",
                            basis_chip(_BASIS_MATURITY_CALENDAR),
                        ],
                    ),
                    html.Div(
                        _render_convexity_cliff_panel_logic(
                            portfolio=portfolio,
                            ips_config=ips_config,
                        ),
                        id="plan-convexity-cliff-panel",
                    ),
                ],
                className="panel",
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
                                        "Horizon (days, blank = nearest "
                                        "maturity)",
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
                                        "Expected return (%, blank = "
                                        "risk-neutral)",
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
                        _render_vega_term_panel_logic(portfolio=portfolio),
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
        ],
        className="page page-design",
    )


def register_callbacks(app: ProgramDashApp) -> None:
    """Wire the BOOK zone's mutating callbacks and the read-only panels.

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

    @app.callback(
        Output("book-version", "data", allow_duplicate=True),
        Output("mutation-status", "children", allow_duplicate=True),
        Output("add-strike", "value"),
        Output("add-maturity", "date"),
        Output("add-quantity", "value"),
        Output("add-option-type", "value"),
        Output("add-exercise-style", "value"),
        Output("add-entry-premium", "value"),
        Input("add-submit", "n_clicks"),
        State("add-strike", "value"),
        State("add-maturity", "date"),
        State("add-quantity", "value"),
        State("add-option-type", "value"),
        State("add-exercise-style", "value"),
        State("add-entry-premium", "value"),
        State("book-version", "data"),
        prevent_initial_call=True,
    )
    def _add_position(  # pylint: disable=too-many-arguments
        _n_clicks: int,
        strike: float | None,
        maturity: str | None,
        quantity: float | None,
        option_type: str,
        exercise_style: str,
        entry_premium: float | None,
        version: int,
    ) -> tuple[Any, Component, Any, Any, Any, Any, Any, Any]:
        return _add_position_logic(
            strike=strike,
            maturity=maturity,
            quantity=quantity,
            option_type=option_type,
            exercise_style=exercise_style,
            entry_premium=entry_premium,
            version=version,
            state=app.program_state,
        )

    @app.callback(
        Output("book-version", "data", allow_duplicate=True),
        Output("mutation-status", "children", allow_duplicate=True),
        Input({"type": "remove-confirm", "index": ALL}, "submit_n_clicks"),
        State("book-version", "data"),
        prevent_initial_call=True,
    )
    def _remove_position(
        _all_submit_clicks: list[int | None],
        version: int,
    ) -> tuple[Any, Any]:
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            # Defensive only — prevent_initial_call=True already keeps
            # this from firing without a real click.
            return no_update, no_update
        # A pattern-matching ALL input fires once, with submit_n_clicks
        # still None, the moment a *new* matching component first
        # appears in the DOM (e.g. the position table's first render) —
        # not just on an actual confirmed click. prevent_initial_call
        # only suppresses the callback's own initial dispatch, not this;
        # ctx.triggered[0]["value"] is the real click count, so a falsy
        # value here means "just appeared," not "confirmed."
        if not ctx.triggered[0]["value"]:
            return no_update, no_update
        return _remove_position_logic(
            index=triggered["index"],
            version=version,
            state=app.program_state,
        )

    @app.callback(
        Output("book-version", "data", allow_duplicate=True),
        Output("mutation-status", "children", allow_duplicate=True),
        Input("underlying-qty", "value"),
        State("book-version", "data"),
        prevent_initial_call=True,
    )
    def _set_underlying_quantity(
        value: float | None,
        version: int,
    ) -> tuple[Any, Component]:
        return _set_underlying_quantity_logic(
            value=value,
            version=version,
            state=app.program_state,
        )

    @app.callback(
        Output("book-version", "data", allow_duplicate=True),
        Output("mutation-status", "children", allow_duplicate=True),
        Output("import-pending-path", "data"),
        Output("import-confirm-row", "hidden"),
        Input("import-submit", "n_clicks"),
        Input("import-confirm-submit", "n_clicks"),
        State("import-path", "value"),
        State("import-pending-path", "data"),
        State("book-version", "data"),
        prevent_initial_call=True,
    )
    def _import(  # pylint: disable=too-many-arguments
        _submit_clicks: int | None,
        _confirm_clicks: int | None,
        path: str | None,
        pending_path: str | None,
        version: int,
    ) -> tuple[Any, Component, Any, Any]:
        if ctx.triggered_id == "import-confirm-submit":
            confirm, target = True, pending_path
        else:
            confirm, target = False, path
        return _import_logic(
            confirm=confirm,
            target=target,
            version=version,
            state=app.program_state,
        )

    @app.callback(
        Output("export-download", "data"),
        Output("mutation-status", "children", allow_duplicate=True),
        Input("export-submit", "n_clicks"),
        prevent_initial_call=True,
    )
    def _export(_n_clicks: int) -> tuple[Any, Component]:
        return _export_logic(state=app.program_state)

    @app.callback(
        Output("position-table", "children"),
        Input("book-version", "data"),
    )
    def _render_position_table(_version: int) -> Component:
        return _render_position_table_logic(
            portfolio=app.program_state.portfolio,
        )

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
        Output("plan-roll-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_roll_panel(_version: int) -> Component:
        return _render_roll_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    @app.callback(
        Output("plan-hedge-triggers-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_hedge_triggers_panel(_version: int) -> Component:
        return _render_hedge_triggers_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    @app.callback(
        Output("plan-delta-drift-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_delta_drift_panel(_version: int) -> Component:
        return _render_delta_drift_panel_logic(
            portfolio=app.program_state.portfolio,
        )

    @app.callback(
        Output("plan-convexity-cliff-panel", "children"),
        Input("book-version", "data"),
    )
    def _render_convexity_cliff_panel(_version: int) -> Component:
        return _render_convexity_cliff_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
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
        Output("net-delta-readout", "children"),
        Input("book-version", "data"),
    )
    def _render_net_delta(_version: int) -> Component:
        portfolio = app.program_state.portfolio
        return _safe_render(lambda: _net_delta_readout(portfolio))

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
        )
