"""Project-wide constants.

Keep simple, typed, immutable values here. Use `typing.Final` to indicate
these are constants; they are module-level values intended for import by
other modules.
"""

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

__all__ = [
    "DAYS_PER_YEAR",
    "DAYS_PER_WEEK",
    "HOURS_PER_DAY",
    "WEEKS_PER_YEAR",
    "TRADING_DAYS_PER_YEAR",
    "BUSINESS_DAYS_PER_YEAR",
    "CALENDAR_DAYS_PER_MONTH",
]
