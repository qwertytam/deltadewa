"""Dash app factory: two pages, shared chrome, one shared program state.

Routing is a single ``dcc.Location`` plus one callback that swaps the page
content by pathname — not Dash's ``use_pages``/``register_page`` machinery,
which keeps registration in process-global state that's awkward to reset
between repeated ``create_app()`` calls (e.g. in tests). Two static
placeholder pages don't need it; revisit if a later milestone wants Dash
Pages' own nav/title support.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from dash import Dash, Input, Output, dcc, html
from flask import jsonify

from deltadewa.analysis.cache import ScenarioGridCache
from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.analysis.provenance import InputKind, build_provenance_ledger
from deltadewa.app.chrome import build_chrome
from deltadewa.app.health_checks import run_checks, summarize
from deltadewa.app.pages import design, monitor
from deltadewa.app.panel_guard import safe_chrome
from deltadewa.clock import program_trading_date
from deltadewa.ips_config import IpsPricingInputs
from deltadewa.marketdata import default_cache_dir

if TYPE_CHECKING:
    from flask import Flask, Response

    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.analysis.provenance import ProvenanceLedger
    from deltadewa.ips_config import IpsConfig
    from deltadewa.marketdata import MarketDataProvider
    from deltadewa.state import ProgramState

_logger = logging.getLogger(__name__)

_DEFAULT_ROUTE = "/monitor"
_ROUTES: dict[str, Callable[[ProgramDashApp], html.Div]] = {
    "/design": design.render,
    "/monitor": monitor.render,
}


def _market_data_payload(environment: MarketEnvironment) -> dict[str, Any]:
    """Build ``/health``'s ``market_data`` object.

    #368: ``fetched_at``/``series``/``oldest_series`` let an operator tell
    "one series is on its normal, expected lag" apart from "the pipeline
    stopped" — the confusion a 2026-08-25 field test hit with only
    ``source``/``as_of`` available here.
    """
    return {
        "source": environment.data_quality.value,
        "as_of": (
            environment.as_of.isoformat()
            if environment.as_of is not None
            else None
        ),
        "fetched_at": (
            environment.fetched_at.isoformat()
            if environment.fetched_at is not None
            else None
        ),
        "oldest_series": environment.oldest_series,
        "series": {
            series.name: {
                "quality": series.quality.value,
                "as_of": (
                    series.as_of.isoformat()
                    if series.as_of is not None
                    else None
                ),
                "fetched_at": (
                    series.fetched_at.isoformat()
                    if series.fetched_at is not None
                    else None
                ),
            }
            for series in environment.series
        },
    }


def _pricing_inputs_payload(ledger: ProvenanceLedger) -> dict[str, Any]:
    """Build ``/health``'s ``pricing_inputs`` object.

    #367: a sibling of ``market_data``, deliberately never merged into it —
    a stale hand-entered rate must not make this endpoint claim the
    *fetched* market data feed is stale, which would just relocate #368's
    confusion.
    """
    worst_hand_entered = ledger.worst_of(InputKind.HAND_ENTERED)
    return {
        "worst": (
            worst_hand_entered.freshness.value
            if worst_hand_entered is not None
            else None
        ),
        "entries": [
            {
                "key": entry.key,
                "label": entry.label,
                "freshness": entry.freshness.value,
                "as_of": (
                    entry.as_of.isoformat() if entry.as_of is not None else None
                ),
                "age_days": entry.age_days,
                "max_age_days": entry.max_age_days,
                "detail": entry.detail,
            }
            for entry in ledger.by_kind(InputKind.HAND_ENTERED)
        ],
    }


class FetchCapableProviderError(RuntimeError):
    """Raised when ``create_app`` is given a provider that can live-fetch.

    The app runs unattended and must never depend on network reachability —
    a feed outage should degrade the chrome to STALE, not take the app
    down. Checked structurally via ``MarketDataProvider.is_read_only``
    rather than trusted from a docstring.
    """


class ProgramDashApp(Dash):
    """A ``Dash`` app carrying the one shared program state + data provider.

    Attributes are set once in :func:`create_app` and read by every
    request — there is no per-request or per-session re-construction.
    """

    program_state: ProgramState
    market_data: MarketDataProvider
    ips_config: IpsConfig | None
    scenario_cache: ScenarioGridCache


def create_app(
    *,
    state: ProgramState,
    market_data: MarketDataProvider,
    ips_config: IpsConfig | None = None,
) -> ProgramDashApp:
    """Build the Dash app: two pages over one shared ``ProgramState``.

    Args:
        state: The single shared program state (see ``deltadewa.state``).
            Constructed once by the caller and threaded through — every
            request reads this same instance, never a per-session copy.
        market_data: Market data provider. Must never perform a live
            fetch — pass a read-only provider (e.g.
            ``CboeFredProvider(read_only=True)``); this app only reads
            cached/last-good values, so a feed outage degrades the chrome
            to STALE rather than taking the app down. Enforced at
            construction via ``market_data.is_read_only``.
        ips_config: Hedge program policy, used to classify market
            conditions for the chrome banner. ``None`` uses policy
            defaults.

    Returns:
        A ready-to-run ``Dash`` app.

    Raises:
        FetchCapableProviderError: If ``market_data.is_read_only`` is
            ``False``.

    """
    if not market_data.is_read_only:
        raise FetchCapableProviderError(
            "create_app() requires a read-only market data provider "
            f"(got {type(market_data).__name__} with "
            "is_read_only=False); pass e.g. "
            "CboeFredProvider(read_only=True)",
        )

    app = ProgramDashApp(__name__, suppress_callback_exceptions=True)
    app.program_state = state
    app.market_data = market_data
    app.ips_config = ips_config
    # One instance for the app's lifetime, not per-request/per-callback --
    # it self-invalidates on the portfolio state hash (and, for the
    # spot/vol grid, on vol_mapping + days_forward too), so sharing it is
    # what makes repeat EXPLORATION-zone dial moves free (M2.5 Prompt D).
    app.scenario_cache = ScenarioGridCache()

    env_policy = (
        ips_config.market_environment if ips_config is not None else None
    )
    pricing_inputs_policy = (
        ips_config.pricing_inputs
        if ips_config is not None
        else IpsPricingInputs()
    )
    program_tz = ips_config.program.timezone if ips_config is not None else None

    def _assess_provenance() -> tuple[MarketEnvironment, ProvenanceLedger]:
        # Re-assessed per request (not baked in once at startup) so a feed
        # outage that starts mid-session still shows STALE on the next
        # page load. Cheap: market_data is expected to be read-only, i.e.
        # a local cache read, never a network call.
        #
        # #381: this is shared *code*, never a shared *value*. Both
        # _serve_layout() and /health call it fresh inside their own
        # guard. Precomputing one result for both would mean a single
        # raise took down the page and the endpoint that would have
        # reported it — see safe_chrome()'s docstring, and #376's refusal
        # of the same shortcut one layer down in monitor.py.
        environment = assess_market_environment(market_data, env_policy)
        ledger = build_provenance_ledger(
            environment,
            state.portfolio,
            pricing_inputs_policy,
            as_of=program_trading_date(program_tz).date(),
        )
        return environment, ledger

    def _serve_layout() -> html.Div:
        # Only the chrome is guarded: dcc.Location and page-content mount
        # unconditionally, so a failed provenance assessment degrades the
        # banner without taking routing — or /monitor's own safe_render-
        # wrapped panels — down with it (#381).
        return html.Div(
            [
                safe_chrome(lambda: build_chrome(_assess_provenance()[1])),
                dcc.Location(id="url", refresh=False),
                html.Div(id="page-content"),
            ],
        )

    app.layout = _serve_layout
    design.register_callbacks(app)
    monitor.register_callbacks(app)

    @app.callback(Output("page-content", "children"), Input("url", "pathname"))
    def _render_page(pathname: str | None) -> html.Div:
        route = _ROUTES.get(pathname or _DEFAULT_ROUTE, _ROUTES[_DEFAULT_ROUTE])
        return route(app)

    # app.server is typed Any on Dash (it's pluggable, per-backend); cast
    # once so the route decorator below is properly typed rather than
    # silently erasing _health's own annotation.
    flask_app = cast("Flask", app.server)

    @flask_app.route("/health")
    def _health() -> tuple[Response, int]:
        # Reuses the same cheap, no-network read _serve_layout already
        # does for the chrome banner — a dead-man's-switch ping must not
        # itself trigger a fetch or a reprice. Every boot-wiring check
        # below is the same class: O(1) attribute reads, one Path.stat(),
        # or one mkdir+write+unlink — see health_checks.py's module
        # docstring (#309).
        # #381: the same guard _serve_layout() applies, for the same
        # reason one layer up — a raise here 500s the endpoint the
        # dead-man's switch reads, so the alarm dies with the program
        # (#364). Called fresh, never sharing _serve_layout()'s value.
        provenance_error: str | None = None
        market_data_payload: dict[str, Any] | None = None
        pricing_inputs_payload: dict[str, Any] | None = None
        try:
            environment, ledger = _assess_provenance()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _logger.exception("Provenance assessment failed for /health")
            # Deliberately not DataQuality.UNAVAILABLE in the block below:
            # that is a real value meaning "the provider failed and every
            # field is None" — a *successful* assessment with an empty
            # answer. Reusing it here would make a genuine feed outage
            # indistinguishable from a code fault. null plus a named
            # error keeps the two apart.
            provenance_error = f"{type(exc).__name__}: {exc}"
        else:
            market_data_payload = _market_data_payload(environment)
            pricing_inputs_payload = _pricing_inputs_payload(ledger)

        # #395: the same guard as _assess_provenance() above, one call
        # lower in the same route — run_checks()/summarize() carry no
        # documented "never raises" contract, and a couple of the
        # individual checks do attribute reads on state/state.portfolio
        # that assume a shape. wiring_status defaults to "degraded" so a
        # raise here still reads as unhealthy even before boot_wiring_error
        # is consulted; boot_wiring stays None rather than a fabricated
        # all-failing table, matching how market_data_payload/
        # pricing_inputs_payload stay None above.
        boot_wiring_error: str | None = None
        wiring_status = "degraded"
        boot_wiring: dict[str, dict[str, Any]] | None = None
        try:
            checks = run_checks(state, cache_dir=default_cache_dir())
            wiring_status, boot_wiring = summarize(checks)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            _logger.exception("Boot-wiring checks failed for /health")
            boot_wiring_error = f"{type(exc).__name__}: {exc}"
        # "status" reflects boot-wiring health, not just liveness — but
        # HTTP always stays 200 (see summarize()'s docstring): a policy
        # nit like a defaulted IPS section must never look like a reason
        # to restart-loop a working container. An unassessable provenance
        # or boot-wiring check joins it as degraded rather than becoming a
        # third or fourth status word: this is the field a dumb watcher
        # greps, so two values it can act on beat several it has to learn.
        # provenance_error/boot_wiring_error are where the distinguishing
        # detail lives. Note what this still does *not* cover: an
        # assessment that succeeds and comes back stale leaves status "ok"
        # — #393 owns that decision, deliberately not this one, since the
        # threshold is an alarm-fatigue question of its own (see chrome.py
        # on why the banner stays quiet at CACHED).
        status = (
            "degraded"
            if (
                wiring_status == "degraded"
                or provenance_error is not None
                or boot_wiring_error is not None
            )
            else "ok"
        )
        return jsonify(
            {
                "status": status,
                "state_loaded": state.loaded_from is not None,
                "market_data": market_data_payload,
                "pricing_inputs": pricing_inputs_payload,
                # #381: null unless the assessment itself raised, in which
                # case market_data/pricing_inputs above are null and this
                # names the fault — so a heartbeat watcher gets *an*
                # answer, and a diagnosis, instead of a 500.
                "provenance_error": provenance_error,
                # #355: who last wrote the shared state file, and whether
                # it has changed since this worker last read or wrote it
                # itself — a single Path.stat() under external_write_
                # detected(), no lock, no reprice. Lets the CLI importer
                # (or an operator) tell "the running worker already has
                # this" apart from "only the file has this."
                "state": {
                    "written_by": state.written_by,
                    "loaded_at": state.loaded_at,
                    "external_write_detected": (
                        state.external_write_detected()
                    ),
                },
                # #309: a small, explicit set of post-boot assertions on
                # the objects the real boot path constructed — see
                # health_checks.py for which six and why.
                "boot_wiring": boot_wiring,
                # #395: null unless run_checks()/summarize() itself raised,
                # in which case boot_wiring above is null and this names
                # the fault — the same shape provenance_error carries for
                # the assessment above it.
                "boot_wiring_error": boot_wiring_error,
            },
        ), 200

    return app
