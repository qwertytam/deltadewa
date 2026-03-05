"""Dashboard setup and initialisation utilities.

This module encapsulates the boilerplate that previously lived in the first
few cells of options_dashboard.ipynb:

- ``configure_display_defaults()``  — pandas / matplotlib environment setup
- ``initialize_portfolio()``        — detect-imported-or-load-default logic
- ``build_global_assumptions()``    — construct and link GlobalAssumptions
widget
- ``print_portfolio_summary()``     — formatted portfolio summary block
"""

# TODO: Linter
from __future__ import annotations

import datetime
from collections.abc import Callable
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from deltadewa.analysis.volatility import get_volatility_stats
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.factory import create_default_portfolio
from deltadewa.reporting import ConsoleReporter
from deltadewa.widgets.assumptions import GlobalAssumptions
from deltadewa.widgets.convenience import link_portfolio_to_assumptions

# ---------------------------------------------------------------------------
# Display / environment
# ---------------------------------------------------------------------------


def configure_display_defaults(
    max_columns: int | None = None,
    precision: int = 4,
    mpl_style: str = "seaborn-v0_8-darkgrid",
) -> None:
    """Set pandas display options and matplotlib style.

    Call once at notebook startup before any display output is produced.

    Parameters
    ----------
    max_columns:
        Value passed to ``pd.set_option("display.max_columns", ...)``.
        ``None`` means "show all columns" (pandas default unlimited).
    precision:
        Number of decimal places for pandas float display.
    mpl_style:
        Matplotlib style sheet name.

    """
    pd.set_option("display.max_columns", max_columns)
    pd.set_option("display.precision", precision)
    plt.style.use(mpl_style)


# ---------------------------------------------------------------------------
# Portfolio initialisation
# ---------------------------------------------------------------------------


def initialize_portfolio(
    portfolio: OptionPortfolio,
    reporter: ConsoleReporter | None = None,
    *,
    globals_dict: dict | None = None,
) -> bool:
    """Detect an already-imported portfolio, or load the default.

    The notebook creates an empty ``portfolio`` object at setup time and may
    have a separately-imported portfolio in scope (e.g. via a
    ``%run import_portfolio.ipynb`` cell).  This function replicates the
    three-cell detection + copy-over logic into a single callable:

    1. Check whether ``globals_dict`` (pass ``globals()`` from the notebook)
       contains a live ``portfolio`` object with at least one position.
    2. If yes → log success and return ``True`` (portfolio unchanged).
    3. If no  → copy the default portfolio's fields *in-place* into
       ``portfolio`` so that all existing widget/widget-callback references
       to the object remain valid, then return ``False``.

    Parameters
    ----------
    portfolio:
        The ``OptionPortfolio`` instance created at notebook startup.
        This object is mutated in-place when the default is loaded.
    reporter:
        ``ConsoleReporter`` instance for output.  A default one is created
        when ``None`` is supplied.
    globals_dict:
        Pass ``globals()`` from the notebook cell so that the function can
        inspect the notebook's own namespace.  When ``None`` the check is
        skipped and the default portfolio is always loaded.

    Returns
    -------
    bool
        ``True`` if an imported portfolio was detected and used,
        ``False`` if the default portfolio was loaded.

    """
    _reporter = reporter or ConsoleReporter(width=100)

    portfolio_imported = False
    try:
        if globals_dict is not None and "portfolio" in globals_dict:
            nb_portfolio = globals_dict["portfolio"]
            positions = getattr(nb_portfolio, "positions", None)
            if positions is not None and len(positions) > 0:
                portfolio_imported = True
    except Exception as exc:  # pylint: disable=broad-except
        _reporter.warning(f"Error checking import status: {exc}")
        portfolio_imported = False

    if portfolio_imported:
        _reporter.success(
            "Imported portfolio detected; using imported portfolio.",
        )
        return True

    # Load default and copy fields in-place so widget references stay valid
    _reporter.warning("No portfolio imported; loading default portfolio.")
    default_pf = create_default_portfolio()

    portfolio.underlying_quantity = default_pf.underlying_quantity
    portfolio.spot_price = default_pf.spot_price
    portfolio.volatility = default_pf.volatility
    portfolio.risk_free_rate = default_pf.risk_free_rate
    portfolio.dividend_yield = default_pf.dividend_yield
    portfolio.symbol = default_pf.symbol

    # Replace positions in-place (preserves any external references to the list)
    portfolio.positions.clear()
    portfolio.positions.extend(default_pf.positions)

    _reporter.success("Default portfolio loaded.")
    return False


def print_portfolio_summary(
    portfolio: OptionPortfolio,
    reporter: ConsoleReporter | None = None,
) -> None:
    """Sync portfolio volatility then print a formatted summary block.

    Replicates the "Display portfolio configuration" cell:
    - Reads vol stats and sets ``portfolio.volatility`` to the avg.
    - Prints a ``reporter.section`` block.

    Parameters
    ----------
    portfolio:
        Configured ``OptionPortfolio`` instance.
    reporter:
        ``ConsoleReporter`` for output.

    """
    _reporter = reporter or ConsoleReporter(width=100)

    vol_stats = get_volatility_stats(portfolio)
    portfolio.set_volatility(vol_stats["avg_volatility"])
    vol_stats = get_volatility_stats(portfolio)  # re-read after update

    summary = (
        f"\nSymbol:          {portfolio.get_symbol()}"
        f"\nUnderlying Qty:  {portfolio.underlying_quantity:,}"
        f"\nSpot Price:      ${portfolio.spot_price:,.2f}"
        f"\nVolatility:      {portfolio.volatility:.1%}"
        f"\nRisk-Free Rate:  {portfolio.risk_free_rate:.2%}"
        f"\nDividend Yield:  {portfolio.dividend_yield:.2%}"
        f"\nValuation Date:  {portfolio.valuation_date.strftime('%Y-%m-%d')}"
        f"\nPositions:       {len(portfolio.positions)}"
        f"\n"
    )
    _reporter.section("PORTFOLIO SUMMARY", summary)
    _reporter.divider()


# ---------------------------------------------------------------------------
# Global Assumptions widget
# ---------------------------------------------------------------------------


def build_global_assumptions(
    portfolio: OptionPortfolio,
    *,
    spot_range_pct: float = 30.0,
    vol_range: tuple[float, float] = (0.05, 1.00),
) -> tuple[GlobalAssumptions, Callable[..., None]]:
    """Construct and wire a ``GlobalAssumptions`` widget to *portfolio*.

    Replicates the "Initialize Global Assumptions Panel" cell.

    Parameters
    ----------
    portfolio:
        The live ``OptionPortfolio`` instance.  Used to seed initial widget
        values and as the target of the on-change callback.
    spot_range_pct:
        Passed through to ``GlobalAssumptions`` (slider ± range).
    vol_range:
        ``(min_vol, max_vol)`` for the volatility slider.

    Returns
    -------
    global_assumptions : GlobalAssumptions
        The fully wired widget panel.
    assumptions_link_cb : Callable
        The registered callback (return value of
        ``link_portfolio_to_assumptions``).  Callers may ignore this unless
        they need to unregister the callback later.

    """
    global_assumptions = GlobalAssumptions(
        spot_price=portfolio.spot_price,
        volatility=portfolio.volatility,
        risk_free_rate=portfolio.risk_free_rate,
        dividend_yield=portfolio.dividend_yield,
        valuation_date=portfolio.valuation_date,
        portfolio_time_horizon=portfolio.get_days_to_furthest_maturity(),
        spot_range_pct=spot_range_pct,
        vol_range=vol_range,
    )

    assumptions_link_cb = link_portfolio_to_assumptions(
        portfolio,
        global_assumptions,
    )

    return global_assumptions, assumptions_link_cb


# ---------------------------------------------------------------------------
# All-in-one convenience wrapper
# ---------------------------------------------------------------------------


def setup_dashboard(
    portfolio: OptionPortfolio,
    reporter: ConsoleReporter | None = None,
    *,
    globals_dict: dict | None = None,
    export_dir: str | Path | None = None,
) -> dict:
    """Run the full MODE 0 setup sequence and return a context dict.

    This is a convenience wrapper that calls, in order:

    1. ``configure_display_defaults()``
    2. ``initialize_portfolio(portfolio, reporter, globals_dict=globals_dict)``
    3. ``print_portfolio_summary(portfolio, reporter)``
    4. ``build_global_assumptions(portfolio)``

    Parameters
    ----------
    portfolio:
        Empty ``OptionPortfolio`` created just before this call.
    reporter:
        ``ConsoleReporter`` instance shared across the notebook session.
    globals_dict:
        Pass ``globals()`` from the calling notebook cell.
    export_dir:
        Optional override for the export directory path (default:
        ``./exports``).

    Returns
    -------
    dict with keys:
        ``portfolio_imported`` (bool),
        ``global_assumptions`` (GlobalAssumptions),
        ``assumptions_link_cb`` (Callable),
        ``today`` (datetime),
        ``export_dir`` (Path).

    """
    _reporter = reporter or ConsoleReporter(width=100)

    configure_display_defaults()

    portfolio_imported = initialize_portfolio(
        portfolio,
        _reporter,
        globals_dict=globals_dict,
    )

    print_portfolio_summary(portfolio, _reporter)

    global_assumptions, assumptions_link_cb = build_global_assumptions(
        portfolio
    )

    _export_dir = Path(export_dir) if export_dir else Path.cwd() / "exports"

    return {
        "portfolio_imported": portfolio_imported,
        "global_assumptions": global_assumptions,
        "assumptions_link_cb": assumptions_link_cb,
        "today": datetime.datetime.now(tz=datetime.UTC),
        "export_dir": _export_dir,
    }
