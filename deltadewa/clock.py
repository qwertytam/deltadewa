"""The program's trading clock: what "today" means for this hedge program.

Two facts about the pricing engine drive everything in this module.

**QuantLib prices on a calendar date, not an instant.** ``OptionValuation``
builds its ``QtLib.Date`` from ``.day``/``.month``/``.year`` and discards the
time of day, so a valuation datetime of 09:30 and one of 23:30 on the same
date price identically. The valuation date is therefore a *date*-valued
concept that the codebase happens to carry in a ``datetime``.

**Which date it lands on depends on the timezone that datetime carries.**
Before #182 the default was ``datetime.now(tz=UTC)``, so the program's "today"
rolled over at 20:00 America/New_York. A US family office reviewing the book
after dinner saw it repriced a day forward — for a 21-day SPX put, a 7.3% drop
in value from the clock alone, with no market move behind it.

Both problems dissolve once the trading date is derived in the program's own
timezone and normalized to midnight:

- ``program_trading_date`` is the single seed for every default valuation date.
  Normalizing to midnight means the book prices the same all day, and the
  time of day can no longer leak into a day count.
- ``days_between`` is the single day-count helper. It subtracts calendar
  dates, which is exactly what QuantLib does, so a displayed days-to-expiry
  can never disagree with the priced one.

The timezone is policy, not presentation: it is ``program.timezone`` in
``ips.yaml``, defaulting to :data:`DEFAULT_PROGRAM_TIMEZONE`. It decides which
day's close a position is priced against, which is a program decision about
the market being hedged, not a display preference.
"""

from __future__ import annotations

from datetime import datetime as dt
from zoneinfo import ZoneInfo

__all__ = [
    "DEFAULT_PROGRAM_TIMEZONE",
    "days_between",
    "program_now",
    "program_trading_date",
]

#: The default market calendar for this program. SPX trades on the US
#: equity calendar, so a program that does not name a timezone gets the
#: exchange's, not the server's.
DEFAULT_PROGRAM_TIMEZONE = ZoneInfo("America/New_York")


def program_trading_date(
    tz: ZoneInfo | None = None,
    *,
    now: dt | None = None,
) -> dt:
    """Return the program's current trading date, as midnight in ``tz``.

    Args:
        tz: The program's timezone (``ips.program.timezone``). Defaults to
            :data:`DEFAULT_PROGRAM_TIMEZONE`.
        now: The instant to resolve, for tests and what-if evaluation.
            Converted into ``tz`` first, so passing a UTC instant does the
            right thing. Defaults to the current time.

    Returns:
        A timezone-aware ``datetime`` at midnight on the program's trading
        date. Midnight rather than the current instant because the value is
        consumed as a date: QuantLib ignores the time component, and every
        day count in the package is a calendar-date difference.

    """
    zone = tz if tz is not None else DEFAULT_PROGRAM_TIMEZONE
    moment = now.astimezone(zone) if now is not None else dt.now(tz=zone)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def program_now(tz: ZoneInfo | None = None) -> dt:
    """Return the current instant, expressed in the program's timezone.

    For timestamps a human reads or sorts by — export filenames, the
    market-data as-of stamp — where the time of day is the point.
    :func:`program_trading_date` is the one to use for anything a
    calculation consumes.

    Args:
        tz: The program's timezone. Defaults to
            :data:`DEFAULT_PROGRAM_TIMEZONE`.

    Returns:
        A timezone-aware ``datetime`` at the current instant in ``tz``.

    """
    return dt.now(tz=tz if tz is not None else DEFAULT_PROGRAM_TIMEZONE)


def days_between(as_of: dt, maturity: dt) -> int:
    """Return whole calendar days from ``as_of`` to ``maturity``.

    This is the day count the pricing engine uses. ``OptionValuation`` reads
    ``.day``/``.month``/``.year`` off each datetime as stored, so comparing
    ``.date()`` reproduces its arithmetic exactly — including the case where
    the two arguments carry different timezones, which subtracting the
    datetimes does not.

    Subtracting the datetimes instead floors the result, and so reads one day
    short whenever ``as_of`` has a non-zero time of day::

        as_of    = 2026-08-11 14:30   maturity = 2026-09-01 00:00
        (maturity - as_of).days       -> 20     # what the panels showed
        days_between(as_of, maturity) -> 21     # what the book was priced on

    That gap crossed the ``expiry_urgent_days`` / ``expiry_soon_days``
    trigger boundaries a day early (#182).

    Args:
        as_of: The valuation date to measure from.
        maturity: The expiry to measure to.

    Returns:
        Calendar days between the two dates; negative once ``maturity`` is
        in the past.

    """
    return (maturity.date() - as_of.date()).days
