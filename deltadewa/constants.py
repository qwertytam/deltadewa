"""Project-wide constants.

Keep simple, typed, immutable values here. Use `typing.Final` to indicate
these are constants; they are module-level values intended for import by
other modules.
"""

from enum import Enum, StrEnum
from typing import Final

# Calendar / time constants
DAYS_PER_YEAR: Final[int] = 365
DAYS_PER_WEEK: Final[int] = 7
HOURS_PER_DAY: Final[int] = 24

# Derived values
WEEKS_PER_YEAR: Final[float] = DAYS_PER_YEAR / DAYS_PER_WEEK

# Finance / trading conventions
# Common market convention for trading/business days in a year
TRADING_DAYS_PER_YEAR: Final[int] = 252
BUSINESS_DAYS_PER_YEAR: Final[int] = 252
CALENDAR_DAYS_PER_MONTH: Final[int] = 30

# Logging action types for portfolio changes


class PortfolioAction(StrEnum):
    """Enum of portfolio action types.

    Use this when you want attribute access like `PORTFOLIO_ACTION_TYPES.ADD`.
    The values are plain strings so they remain friendly for serialization
    and display.
    """

    ADD = "ADD"
    REMOVE = "REMOVE"
    ROLL = "ROLL"
    UPDATE = "UPDATE"
    REBALANCE = "REBALANCE"
    INITIALIZE = "INITIALIZE"


class OptionType(StrEnum):
    """Enum of option types."""

    CALL = "CALL"
    PUT = "PUT"


class ExerciseStyle(StrEnum):
    """Enum of option exercise styles."""

    AMERICAN = "AMERICAN"
    EUROPEAN = "EUROPEAN"


class FDGridResolution(int, Enum):
    """Grid dimensions for finite difference engine."""

    FAST = 75
    STANDARD = 125
    PRECISE = 250


__all__ = [
    "BUSINESS_DAYS_PER_YEAR",
    "CALENDAR_DAYS_PER_MONTH",
    "DAYS_PER_WEEK",
    "DAYS_PER_YEAR",
    "HOURS_PER_DAY",
    "TRADING_DAYS_PER_YEAR",
    "WEEKS_PER_YEAR",
    "ExerciseStyle",
    "FDGridResolution",
    "OptionType",
    "PortfolioAction",
]
