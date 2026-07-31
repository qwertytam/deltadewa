"""Dash app factory: two pages, shared chrome, one shared program state.

Routing is a single ``dcc.Location`` plus one callback that swaps the page
content by pathname — not Dash's ``use_pages``/``register_page`` machinery,
which keeps registration in process-global state that's awkward to reset
between repeated ``create_app()`` calls (e.g. in tests). Two static
placeholder pages don't need it; revisit if a later milestone wants Dash
Pages' own nav/title support.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import Dash, Input, Output, dcc, html

from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.app.chrome import build_chrome
from deltadewa.app.pages import design, monitor

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsConfig
    from deltadewa.marketdata import MarketDataProvider
    from deltadewa.state import ProgramState

_DEFAULT_ROUTE = "/monitor"
_ROUTES = {
    "/design": design.layout,
    "/monitor": monitor.layout,
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

    app = ProgramDashApp(__name__)
    app.program_state = state
    app.market_data = market_data
    app.ips_config = ips_config

    env_policy = (
        ips_config.market_environment if ips_config is not None else None
    )

    def _serve_layout() -> html.Div:
        # Re-assessed per request (not baked in once at startup) so a feed
        # outage that starts mid-session still shows STALE on the next
        # page load. Cheap: market_data is expected to be read-only, i.e.
        # a local cache read, never a network call.
        environment = assess_market_environment(market_data, env_policy)
        return html.Div(
            [
                build_chrome(environment),
                dcc.Location(id="url", refresh=False),
                html.Div(id="page-content"),
            ],
        )

    app.layout = _serve_layout

    @app.callback(Output("page-content", "children"), Input("url", "pathname"))
    def _render_page(pathname: str | None) -> html.Div:
        return _ROUTES.get(pathname or _DEFAULT_ROUTE, _ROUTES[_DEFAULT_ROUTE])

    return app
