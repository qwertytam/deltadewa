"""deltadewa — SPX tail-risk hedging system, QuantLib-priced."""

from ._version import __version__
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

# InteractiveOutput/PortfolioWidgets deliberately NOT re-exported here:
# they pull in the notebook-only widgets/ package (ipywidgets), which
# would make importing anything under `deltadewa` — including the
# production `deltadewa.app` — require ipywidgets. Import them from
# `deltadewa.widgets` directly (matches `deltadewa.formatters`' own
# "import from submodules directly" convention). Confirmed unused
# anywhere in this repo before removing.

__all__ = [
    "BUSINESS_DAYS_PER_YEAR",
    "DAYS_PER_WEEK",
    "DAYS_PER_YEAR",
    "HOURS_PER_DAY",
    "TRADING_DAYS_PER_YEAR",
    "WEEKS_PER_YEAR",
    "BatchPricer",
    "OptionPortfolio",
    "OptionValuation",
    "__version__",
    "create_empty_portfolio",
]
