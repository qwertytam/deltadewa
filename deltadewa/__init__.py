"""deltadewa — SPX tail-risk hedging system, QuantLib-priced."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("deltadewa")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

from .batch_pricer import BatchPricer
from .constants import (
    BUSINESS_DAYS_PER_YEAR,
    DAYS_PER_WEEK,
    DAYS_PER_YEAR,
    HOURS_PER_DAY,
    TRADING_DAYS_PER_YEAR,
    WEEKS_PER_YEAR,
)
from .portfolio.core import OptionPortfolio
from .portfolio.factory import create_empty_portfolio
from .valuation import OptionValuation
from .widgets import InteractiveOutput, PortfolioWidgets

__all__ = [
    "BUSINESS_DAYS_PER_YEAR",
    "DAYS_PER_WEEK",
    "DAYS_PER_YEAR",
    "HOURS_PER_DAY",
    "TRADING_DAYS_PER_YEAR",
    "WEEKS_PER_YEAR",
    "BatchPricer",
    "InteractiveOutput",
    "OptionPortfolio",
    "OptionValuation",
    "PortfolioWidgets",
    "create_empty_portfolio",
]
