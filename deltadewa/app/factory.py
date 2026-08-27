"""Dash app factory: two pages, shared chrome, one shared program state.

Routing is a single ``dcc.Location`` plus one callback that swaps the page
content by pathname — not Dash's ``use_pages``/``register_page`` machinery,
which keeps registration in process-global state that's awkward to reset
between repeated ``create_app()`` calls (e.g. in tests). Two static
placeholder pages don't need it; revisit if a later milestone wants Dash
Pages' own nav/title support.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from dash import Dash, Input, Output, dcc, html
from flask import jsonify

from deltadewa.analysis.cache import ScenarioGridCache
from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.analysis.provenance import InputKind, build_provenance_ledger
from deltadewa.app.chrome import build_chrome
from deltadewa.app.health_checks import run_checks, summarize
from deltadewa.app.pages import design, monitor
from deltadewa.clock import program_trading_date
from deltadewa.ips_config import IpsPricingInputs
from deltadewa.marketdata import default_cache_dir

if TYPE_CHECKING:
    from flask import Flask, Response

    from deltadewa.ips_config import IpsConfig
    from deltadewa.marketdata import MarketDataProvider
    from deltadewa.state import ProgramState

_DEFAULT_ROUTE = "/monitor"
_ROUTES: dict[str, Callable[[ProgramDashApp], html.Div]] = {
    "/design": design.render,
    "/monitor": monitor.render,
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

    def _serve_layout() -> html.Div:
        # Re-assessed per request (not baked in once at startup) so a feed
        # outage that starts mid-session still shows STALE on the next
        # page load. Cheap: market_data is expected to be read-only, i.e.
        # a local cache read, never a network call.
        environment = assess_market_environment(market_data, env_policy)
        ledger = build_provenance_ledger(
            environment,
            state.portfolio,
            pricing_inputs_policy,
            as_of=program_trading_date(program_tz).date(),
        )
        return html.Div(
            [
                build_chrome(ledger),
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
        environment = assess_market_environment(market_data, env_policy)
        ledger = build_provenance_ledger(
            environment,
            state.portfolio,
            pricing_inputs_policy,
            as_of=program_trading_date(program_tz).date(),
        )
        as_of = (
            environment.as_of.isoformat()
            if environment.as_of is not None
            else None
        )
        worst_hand_entered = ledger.worst_of(InputKind.HAND_ENTERED)
        checks = run_checks(state, cache_dir=default_cache_dir())
        wiring_status, boot_wiring = summarize(checks)
        # "status" reflects boot-wiring health, not just liveness — but
        # HTTP always stays 200 (see summarize()'s docstring): a policy
        # nit like a defaulted IPS section must never look like a reason
        # to restart-loop a working container.
        return jsonify(
            {
                "status": wiring_status,
                "state_loaded": state.loaded_from is not None,
                # #368: fetched_at/series/oldest_series let an operator
                # tell "one series is on its normal, expected lag" apart
                # from "the pipeline stopped" — the confusion a 2026-08-25
                # field test hit with only source/as_of available here.
                "market_data": {
                    "source": environment.data_quality.value,
                    "as_of": as_of,
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
                },
                # #367: a sibling object, deliberately never merged into
                # market_data above — a stale hand-entered rate must not
                # make this endpoint claim the *fetched* market data feed
                # is stale, which would just relocate #368's confusion.
                "pricing_inputs": {
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
                                entry.as_of.isoformat()
                                if entry.as_of is not None
                                else None
                            ),
                            "age_days": entry.age_days,
                            "max_age_days": entry.max_age_days,
                            "detail": entry.detail,
                        }
                        for entry in ledger.by_kind(InputKind.HAND_ENTERED)
                    ],
                },
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
            },
        ), 200

    return app
