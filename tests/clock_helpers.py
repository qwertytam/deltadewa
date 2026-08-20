"""Date seeds for fixtures, anchored on the program clock, not on UTC.

A fixture that seeds a maturity from ``datetime.now(tz=UTC)`` and a
portfolio that defaults its valuation date to
:func:`deltadewa.clock.program_trading_date` are reading two different
clocks. Between 20:00 and 24:00 in the program timezone the two disagree
on the calendar date, so a fixture asking for "3 days out" can silently
seed 2 or 4 (#321, #343).

Use these two helpers wherever a test needs "N days from today" or "the
program's today" — they route through :func:`~deltadewa.clock.
program_trading_date`, the same seed the portfolio itself defaults to, so
a fixture and the code under test can never disagree about what day it is.

Both accept an explicit ``now``, for tests that pin a specific instant
rather than reading the real clock — see ``tests/test_clock_helpers.py``
and ``TestFixturesAgreeWithTheProgramClock`` in
``tests/test_analysis/test_position_aging.py``.

Residual: with ``now=None`` each call reads the real clock independently,
so two calls a run apart could still land on either side of program
midnight. That window is microseconds wide — the same residual
``tests/test_clockshift_canary.py`` already accepts by bracketing two
reads — and pinning ``now`` removes it entirely.
"""

from __future__ import annotations

from datetime import datetime as dt
from datetime import timedelta
from zoneinfo import ZoneInfo

from deltadewa.clock import program_trading_date

__all__ = ["days_from_today", "program_date"]


def program_date(
    *,
    now: dt | None = None,
    tz: ZoneInfo | None = None,
) -> dt:
    """Return the program's trading date — the seed fixtures should share.

    A thin, explicitly-named wrapper over
    :func:`~deltadewa.clock.program_trading_date`, so a fixture reaches for
    "today" the same way the portfolio it constructs does.

    Args:
        now: The instant to resolve, for pinned tests. Defaults to the
            current time.
        tz: The program's timezone. Defaults to
            :data:`~deltadewa.clock.DEFAULT_PROGRAM_TIMEZONE`.

    Returns:
        Midnight on the program's trading date, in ``tz``.

    """
    return program_trading_date(tz, now=now)


def days_from_today(
    days: int,
    *,
    now: dt | None = None,
    tz: ZoneInfo | None = None,
) -> dt:
    """Return midnight ``days`` calendar days from the program trading date.

    Replaces the ``datetime.now(tz=UTC) + timedelta(days=N)`` seeding
    pattern: that pattern anchors on a UTC instant, while
    :func:`~deltadewa.clock.days_between` (and every trigger built on it)
    measures from the program trading date, so the two can disagree for up
    to four hours a day. Seeding through this helper instead means the
    fixture and the day count agree by construction.

    Args:
        days: Calendar days from today; negative for a past date.
        now: The instant to resolve "today" from, for pinned tests.
            Defaults to the current time.
        tz: The program's timezone. Defaults to
            :data:`~deltadewa.clock.DEFAULT_PROGRAM_TIMEZONE`.

    Returns:
        Midnight, ``days`` calendar days from the program trading date.

    """
    return program_date(now=now, tz=tz) + timedelta(days=days)
