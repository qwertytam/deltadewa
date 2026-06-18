"""Single-call bootstrap for a full MODE 0 dashboard session.

Bundles portfolio creation, the change-log/serializer/widgets trio, market
data provider selection, IPS policy loading, ``GlobalAssumptions``, and
hedge-trigger thresholds into one ``start_session()`` call — replacing the
manual sequence of setup cells that previously lived in the notebook.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime as dt
from pathlib import Path
from typing import TYPE_CHECKING

from deltadewa import create_empty_portfolio
from deltadewa.analysis.hedge_triggers import HedgeTriggerThresholds
from deltadewa.dashboard.setup import setup_dashboard
from deltadewa.ips_config import IpsConfigError, load_ips_config
from deltadewa.marketdata import (
    MarketDataError,
    MarketDataProvider,
    StaticProvider,
)
from deltadewa.persistence import PortfolioSerializer
from deltadewa.reporting import ConsoleReporter, PortfolioLogger
from deltadewa.widgets import PortfolioWidgets

if TYPE_CHECKING:
    from collections.abc import Callable

    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.widgets.assumptions import GlobalAssumptions

_DEFAULT_IPS_CONFIG_PATH = Path("examples/ips.yaml")


@dataclass
class SessionContext:
    """Bundled state returned by ``start_session()`` for one session."""

    portfolio: OptionPortfolio
    reporter: ConsoleReporter
    global_assumptions: GlobalAssumptions
    assumptions_link_cb: Callable[..., None]
    portfolio_imported: bool
    today: dt
    export_dir: Path
    portfolio_changelog: PortfolioLogger
    portfolio_serializer: PortfolioSerializer
    portfolio_widgets: PortfolioWidgets
    market_data: MarketDataProvider
    ips_config: IpsConfig | None
    hedge_thresholds: HedgeTriggerThresholds

    def current_spot(self) -> float:
        """Resolve the current spot price for Roll Status and similar uses.

        Tries ``market_data`` first, falling back to ``global_assumptions``
        when the provider has no price for this portfolio's symbol.
        """
        try:
            return self.market_data.get_spot(self.portfolio.get_symbol())
        except MarketDataError:
            return self.global_assumptions.spot_price.value


def start_session(
    portfolio: OptionPortfolio | None = None,
    *,
    reporter: ConsoleReporter | None = None,
    globals_dict: dict | None = None,
    export_dir: str | Path | None = None,
    market_data: MarketDataProvider | None = None,
    ips_config_path: Path | None = None,
    changelog_name: str = "changelog",
) -> SessionContext:
    """Bootstrap a full MODE 0 dashboard session in one call.

    Replaces the manual sequence of ``create_empty_portfolio()``,
    ``PortfolioLogger``, ``PortfolioSerializer``, ``PortfolioWidgets``,
    ``setup_dashboard(...)``, and ``HedgeTriggerThresholds`` derivation that
    previously lived across several notebook cells.

    Args:
        portfolio: Existing portfolio to bootstrap into (e.g. set up by an
            earlier cell). A fresh empty one is created via
            ``create_empty_portfolio()`` if omitted.
        reporter: Shared ``ConsoleReporter``; a default one is created if
            ``None``.
        globals_dict: Pass ``globals()`` from the calling notebook cell
            (forwarded to ``setup_dashboard``'s import-detection).
        export_dir: Export directory override (default ``./exports``).
        market_data: ``MarketDataProvider`` for seeding ``GlobalAssumptions``
            and Roll Status's current spot. Defaults to a no-network
            ``StaticProvider()`` — never makes HTTP calls. Pass a
            ``CboeFredProvider()`` instance for live CBOE/FRED data.
        ips_config_path: Path to the hedge program policy file. Defaults to
            ``examples/ips.yaml``. If missing or invalid, ``ips_config`` is
            ``None`` and ``hedge_thresholds`` falls back to
            ``HedgeTriggerThresholds()`` defaults — this never raises.
        changelog_name: Name passed to ``PortfolioLogger``.

    Returns:
        A fully wired ``SessionContext``.

    """
    portfolio = portfolio or create_empty_portfolio()
    _reporter = reporter or ConsoleReporter(width=100)  # noqa: RUF052
    _export_dir = (  # noqa: RUF052
        Path(export_dir) if export_dir else Path.cwd() / "exports"
    )

    portfolio_changelog = PortfolioLogger(name=changelog_name)
    portfolio_serializer = PortfolioSerializer(export_dir=str(_export_dir))
    portfolio_widgets = PortfolioWidgets(
        portfolio,
        portfolio_serializer,
        portfolio_changelog,
    )

    _market_data = market_data or StaticProvider()  # noqa: RUF052

    try:
        ips_config = load_ips_config(
            ips_config_path or _DEFAULT_IPS_CONFIG_PATH,
        )
    except IpsConfigError as exc:
        _reporter.warning(f"ips.yaml unavailable, continuing without it: {exc}")
        ips_config = None

    ctx = setup_dashboard(
        portfolio,
        reporter=_reporter,
        globals_dict=globals_dict,
        export_dir=_export_dir,
        market_data=_market_data,
        ips_config=ips_config,
    )

    hedge_thresholds = (
        HedgeTriggerThresholds.from_ips(ips_config.triggers)
        if ips_config is not None
        else HedgeTriggerThresholds()
    )

    return SessionContext(
        portfolio=portfolio,
        reporter=_reporter,
        global_assumptions=ctx["global_assumptions"],
        assumptions_link_cb=ctx["assumptions_link_cb"],
        portfolio_imported=ctx["portfolio_imported"],
        today=ctx["today"],
        export_dir=ctx["export_dir"],
        portfolio_changelog=portfolio_changelog,
        portfolio_serializer=portfolio_serializer,
        portfolio_widgets=portfolio_widgets,
        market_data=_market_data,
        ips_config=ips_config,
        hedge_thresholds=hedge_thresholds,
    )
