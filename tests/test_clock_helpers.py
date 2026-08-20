"""Tests for tests/clock_helpers.py.

Near-tautological by construction: these pin the property that
``days_from_today`` and ``program_date`` never disagree with
``deltadewa.clock.days_between`` about how far apart two dates are,
across the hours where a UTC-anchored seed would (#321, #343). The point
is to trip if a future edit quietly reverts a helper to a raw
``datetime.now(tz=UTC)`` seed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from deltadewa.clock import days_between
from tests.clock_helpers import days_from_today, program_date

# Instants spanning the program day, including the 20:00-24:00 ET window
# where a UTC-anchored seed and the program trading date disagree, plus a
# US DST fold so the offset arithmetic is exercised there too.
_INSTANTS = [
    ("morning ET", datetime(2026, 3, 14, 12, 0, tzinfo=UTC)),
    ("21:00 ET — inside the window", datetime(2026, 8, 21, 1, 0, tzinfo=UTC)),
    ("23:59 ET — window edge", datetime(2026, 8, 21, 3, 59, tzinfo=UTC)),
    ("00:00 ET — just outside", datetime(2026, 8, 21, 4, 0, tzinfo=UTC)),
    ("DST fold", datetime(2026, 11, 1, 5, 30, tzinfo=UTC)),
]

_DAY_COUNTS = [-30, 0, 1, 3, 15, 200, 500]


@pytest.mark.parametrize(("label", "instant"), _INSTANTS)
@pytest.mark.parametrize("days", _DAY_COUNTS)
def test_days_from_today_reproduces_the_requested_count(
    days: int,
    label: str,
    instant: datetime,
) -> None:
    """Test days_between(program_date, days_from_today(N)) == N always."""
    del label  # pytest id only
    as_of = program_date(now=instant)
    target = days_from_today(days, now=instant)

    assert days_between(as_of, target) == days


@pytest.mark.parametrize(("label", "instant"), _INSTANTS)
def test_program_date_is_midnight_normalized(
    label: str,
    instant: datetime,
) -> None:
    """Test program_date always lands on midnight, matching clock.py."""
    del label  # pytest id only
    as_of = program_date(now=instant)

    assert (as_of.hour, as_of.minute, as_of.second, as_of.microsecond) == (
        0,
        0,
        0,
        0,
    )
