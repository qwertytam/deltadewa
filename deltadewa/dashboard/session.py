"""Single-call bootstrap for a dashboard session.

Bundles the objects previously created ad hoc across several notebook
setup cells — reporter, changelog, portfolio, serializer, market data
provider, IPS policy, and ``GlobalAssumptions`` — into one
``start_session()`` call.

Market data defaults to fully offline: ``start_session()`` (i.e.
``use_live_market_data=False``, the default) seeds a ``StaticProvider``
from the portfolio's own current values and never makes an HTTP call. To
use live data instead, flip the one flag::

    ctx = start_session(globals_dict=globals(), use_live_market_data=True)

This switches to ``CboeFredProvider``, which pulls from CBOE's public CSV
endpoints and FRED. Two caveats apply to that live path:

- The data is delayed/end-of-day, not real-time — don't rely on it for
  intraday decisions.
- CBOE/FRED feeds carry their own redistribution restrictions; check the
  source's terms before redistributing pulled data outside this session.

Network requirements for the live path:

- ``cdn.cboe.com`` — SPX, VIX-family, and SKEW history (public CSV)
- ``fred.stlouisfed.org`` — VIXCLS series (public CSV, no API key)

If either host is unreachable and no disk cache exists,
``start_session`` warns via the reporter and automatically falls back to
``StaticProvider`` (seeded from the portfolio's own values). The returned
``ctx.market_data_source`` records which path was used: ``"live"``,
``"static"``, or ``"static (live unavailable)"``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from deltadewa import create_empty_portfolio
from deltadewa.dashboard.setup import setup_dashboard
from deltadewa.ips_config import IpsConfigError, load_ips_config
from deltadewa.marketdata import (
    CboeFredProvider,
    MarketDataError,
    MarketDataProvider,
    StaticProvider,
)
from deltadewa.persistence import PortfolioSerializer
from deltadewa.reporting import ConsoleReporter, PortfolioLogger

if TYPE_CHECKING:
    from collections.abc import Callable

    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.widgets.assumptions import GlobalAssumptions


def _load_dashboard_config(
    path: Path,
    reporter: ConsoleReporter,
) -> dict[str, Any] | None:
    """Load HedgeHealthDashboard presentation config, never raising.

    Returns ``None`` (after a reporter warning) if the file is missing,
    unreadable, malformed, or its root isn't a mapping. Supports YAML
    (default) and JSON, dispatched by file suffix.
    """
    if not path.exists():
        reporter.warning(f"dashboard.yaml not found at {path}, using defaults")
        return None

    try:
        text = path.read_text(encoding="utf-8")
        data = (
            json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)
        )
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        reporter.warning(f"dashboard.yaml invalid ({exc}), using defaults")
        return None
    except json.JSONDecodeError as exc:
        reporter.warning(f"dashboard.json invalid ({exc}), using defaults")
        return None

    if not isinstance(data, dict):
        reporter.warning(
            "dashboard.yaml root must be a mapping, using defaults",
        )
        return None

    return data


@dataclass
class SessionContext:
    """Bundled state returned by ``start_session()`` for one session."""

    portfolio: OptionPortfolio
    ips_config: IpsConfig | None
    dashboard_config: dict[str, Any] | None
    market_data: MarketDataProvider
    market_data_source: str
    global_assumptions: GlobalAssumptions
    assumptions_link_cb: Callable[..., None]
    reporter: ConsoleReporter
    changelog: PortfolioLogger
    serializer: PortfolioSerializer
    today: dt
    export_dir: Path
    portfolio_imported: bool
    role: str


def start_session(
    *,
    role: str = "combined",
    globals_dict: dict,
    ips_path: Path = Path("config/ips.yaml"),
    dashboard_path: Path = Path("config/dashboard.yaml"),
    use_live_market_data: bool = False,
    export_dir: Path | None = None,
    auto_load_default: bool = True,
    examples_dir: Path = Path("examples"),
) -> SessionContext:
    """Bootstrap a dashboard session in one call.

    Owns the objects currently created ad hoc in the notebook's setup
    cells: the reporter and changelog, the portfolio and serializer, the
    market data provider, and the IPS policy — then wires them all through
    ``setup_dashboard``.

    Args:
        role: Stored on the returned context for later use. No
            role-conditional behaviour exists yet — that lands separately.
        globals_dict: Pass ``globals()`` from the calling notebook cell.
            If it already contains a ``portfolio`` (e.g. set up by an
            earlier cell), that object is reused; otherwise a fresh empty
            one is created via ``create_empty_portfolio()``.
        ips_path: Path to the hedge program policy file. If missing or
            invalid, ``ips_config`` is ``None`` and the session still
            starts — this never raises.
        dashboard_path: Path to the ``HedgeHealthDashboard`` presentation
            config (gauge ranges). If missing or invalid, ``dashboard_config``
            is ``None`` and the session still starts — this never raises.
        use_live_market_data: If ``True``, attempt ``CboeFredProvider``
            (live CBOE/FRED data — delayed/end-of-day, subject to the
            source's redistribution restrictions). On ``MarketDataError``
            (network unavailable, no cached data), warns and falls back to
            ``StaticProvider`` automatically. Defaults to ``False``, which
            seeds a ``StaticProvider`` from the portfolio's current values
            — no network calls in the default path.
        export_dir: Export directory override (default ``./exports``).
        auto_load_default: When ``True`` (default), ``setup_dashboard``
            falls back to a demo portfolio if nothing was imported via
            ``globals_dict``. Pass ``False`` for sessions that must start
            empty until the caller imports a portfolio explicitly.
        examples_dir: Directory to load the default demo portfolio from, if

    Returns:
        A fully wired ``SessionContext``.

    """
    reporter = ConsoleReporter(width=100)
    changelog = PortfolioLogger(name="changelog")

    portfolio = globals_dict.get("portfolio") or create_empty_portfolio()
    resolved_export_dir = (
        export_dir if export_dir is not None else Path.cwd() / "exports"
    )
    resolved_examples_dir = (
        examples_dir if examples_dir is not None else Path.cwd() / "examples"
    )
    serializer = PortfolioSerializer(
        export_dir=str(resolved_export_dir),
        examples_dir=str(resolved_examples_dir),
    )

    try:
        ips_config = load_ips_config(ips_path)
    except IpsConfigError as exc:
        reporter.warning(f"ips.yaml unavailable, continuing without it: {exc}")
        ips_config = None

    dashboard_config = _load_dashboard_config(dashboard_path, reporter)

    market_data: MarketDataProvider
    market_data_source: str
    if use_live_market_data:
        live_provider = CboeFredProvider()
        try:
            live_provider.get_vix()
            market_data = live_provider
            market_data_source = "live"
        except MarketDataError as exc:
            reporter.warning(
                "Live market data unavailable"
                f" — falling back to offline data: {exc}",
            )
            market_data = StaticProvider(
                spot_prices={portfolio.get_symbol(): portfolio.spot_price},
                vix=portfolio.volatility * 100,
            )
            market_data_source = "static (live unavailable)"
    else:
        market_data = StaticProvider(
            spot_prices={portfolio.get_symbol(): portfolio.spot_price},
            vix=portfolio.volatility * 100,
        )
        market_data_source = "static"

    ctx = setup_dashboard(
        portfolio,
        reporter=reporter,
        globals_dict=globals_dict,
        export_dir=resolved_export_dir,
        market_data=market_data,
        ips_config=ips_config,
        auto_load_default=auto_load_default,
    )

    return SessionContext(
        portfolio=portfolio,
        ips_config=ips_config,
        dashboard_config=dashboard_config,
        market_data=market_data,
        market_data_source=market_data_source,
        global_assumptions=ctx["global_assumptions"],
        assumptions_link_cb=ctx["assumptions_link_cb"],
        reporter=reporter,
        changelog=changelog,
        serializer=serializer,
        today=ctx["today"],
        export_dir=ctx["export_dir"],
        portfolio_imported=ctx["portfolio_imported"],
        role=role,
    )
