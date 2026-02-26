"""Shared fixtures for test_dashboard tests.

All fixtures here are available to every test_dashboard module without
any explicit import — pytest discovers this conftest.py automatically.
"""

# pylint: disable=redefined-outer-name

from __future__ import annotations

import datetime
from datetime import timedelta

import pytest

from deltadewa.constants import OptionType, PortfolioAction
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.reporting.audit import PortfolioLogger
from deltadewa.reporting.console import ConsoleReporter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = datetime.UTC


def _make_call(
    portfolio: OptionPortfolio,
    strike: float = 100.0,
    days: int = 45,
    quantity: int = 1,
) -> None:
    """Add a single ATM call to *portfolio*."""
    portfolio.add_position(
        strike_price=strike,
        maturity_date=datetime.datetime.now(tz=UTC) + timedelta(days=days),
        quantity=quantity,
        option_type=OptionType.CALL,
    )


# ---------------------------------------------------------------------------
# Portfolio fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_portfolio() -> OptionPortfolio:
    """Portfolio with no positions."""
    return OptionPortfolio(spot_price=100.0, volatility=0.20)


@pytest.fixture()
def single_position_portfolio() -> OptionPortfolio:
    """Portfolio with exactly one ATM call, 45 days to expiry."""
    p = OptionPortfolio(spot_price=100.0, volatility=0.20)
    _make_call(p)
    return p


@pytest.fixture()
def multi_position_portfolio() -> OptionPortfolio:
    """Portfolio with 3 calls at different strikes / maturities."""
    p = OptionPortfolio(spot_price=100.0, volatility=0.20)
    _make_call(p, strike=95.0, days=10)  # URGENT tier
    _make_call(p, strike=100.0, days=30)  # NORMAL tier
    _make_call(p, strike=105.0, days=60)  # LONG-TERM tier
    return p


@pytest.fixture()
def portfolio_with_underlying() -> OptionPortfolio:
    """Portfolio with underlying shares and one call hedge."""
    p = OptionPortfolio(
        underlying_quantity=1000.0,
        spot_price=100.0,
        volatility=0.20,
    )
    _make_call(p, quantity=-5)
    return p


@pytest.fixture()
def portfolio_with_custom_vol() -> OptionPortfolio:
    """Portfolio where one position carries a custom non-default volatility."""
    p = OptionPortfolio(spot_price=100.0, volatility=0.20)
    p.add_position(
        strike_price=100.0,
        maturity_date=datetime.datetime.now(tz=UTC) + timedelta(days=45),
        quantity=1,
        option_type=OptionType.CALL,
        volatility=0.30,  # custom vol
    )
    _make_call(p, strike=110.0, days=45)  # uses portfolio default vol
    return p


# ---------------------------------------------------------------------------
# Reporting fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def reporter() -> ConsoleReporter:
    """ConsoleReporter with fixed width for consistent test output."""
    return ConsoleReporter(width=80)


# ---------------------------------------------------------------------------
# PortfolioLogger / changelog fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_changelog() -> PortfolioLogger:
    """Logger that has only the automatic INITIALIZE entry."""
    return PortfolioLogger()


@pytest.fixture()
def changelog_with_add(
    single_position_portfolio: OptionPortfolio,
) -> PortfolioLogger:
    """Logger with one INITIALIZE + one ADD entry."""
    logger = PortfolioLogger()
    logger.log_portfolio_change(
        portfolio=single_position_portfolio,
        action_type=PortfolioAction.ADD,
        details="Added 1x CALL $100 exp 2026-04-12 American",
        impact_delta=0.52,
        impact_cost=-450.0,
    )
    return logger


@pytest.fixture()
def changelog_with_multiple_actions(
    multi_position_portfolio: OptionPortfolio,
) -> PortfolioLogger:
    """Logger with INITIALIZE + 3 ADD + 1 REMOVE entries."""
    logger = PortfolioLogger()
    p = multi_position_portfolio
    for i in range(3):
        logger.log_portfolio_change(
            portfolio=p,
            action_type=PortfolioAction.ADD,
            details=f"Added position {i + 1}",
            impact_delta=0.5,
            impact_cost=-300.0,
        )
    logger.log_portfolio_change(
        portfolio=p,
        action_type=PortfolioAction.REMOVE,
        details="Removed position 1",
        impact_delta=-0.5,
        impact_cost=250.0,
    )
    return logger
