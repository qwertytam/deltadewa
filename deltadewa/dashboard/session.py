"""Single-call bootstrap for a dashboard session.

Bundles the objects previously created ad hoc across several notebook
setup cells — reporter, changelog, portfolio, serializer, market data
provider, IPS policy, and ``GlobalAssumptions`` — into one
``start_session()`` call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING

from deltadewa import create_empty_portfolio
from deltadewa.dashboard.setup import setup_dashboard
from deltadewa.ips_config import IpsConfigError, load_ips_config
from deltadewa.marketdata import (
    CboeFredProvider,
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


@dataclass
class SessionContext:
    """Bundled state returned by ``start_session()`` for one session."""

    portfolio: OptionPortfolio
    ips_config: IpsConfig | None
    market_data: MarketDataProvider
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
    ips_path: Path = Path("examples/ips.yaml"),
    use_live_market_data: bool = False,
    export_dir: Path | None = None,
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
        use_live_market_data: If ``True``, use ``CboeFredProvider()`` (live
            CBOE/FRED data). Defaults to ``False``, which seeds a
            ``StaticProvider`` from the portfolio's current values — no
            network calls in the default path.
        export_dir: Export directory override (default ``./exports``).

    Returns:
        A fully wired ``SessionContext``.

    """
    reporter = ConsoleReporter(width=100)
    changelog = PortfolioLogger(name="changelog")

    portfolio = globals_dict.get("portfolio") or create_empty_portfolio()
    resolved_export_dir = (
        export_dir if export_dir is not None else Path.cwd() / "exports"
    )
    serializer = PortfolioSerializer(export_dir=str(resolved_export_dir))

    try:
        ips_config = load_ips_config(ips_path)
    except IpsConfigError as exc:
        reporter.warning(f"ips.yaml unavailable, continuing without it: {exc}")
        ips_config = None

    market_data: MarketDataProvider
    if use_live_market_data:
        market_data = CboeFredProvider()
    else:
        market_data = StaticProvider(
            spot_prices={portfolio.get_symbol(): portfolio.spot_price},
            vix=portfolio.volatility * 100,
        )

    ctx = setup_dashboard(
        portfolio,
        reporter=reporter,
        globals_dict=globals_dict,
        export_dir=resolved_export_dir,
        market_data=market_data,
        ips_config=ips_config,
    )

    return SessionContext(
        portfolio=portfolio,
        ips_config=ips_config,
        market_data=market_data,
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
