"""Tests for the program trading clock (#182).

These pin the two properties the rest of the package relies on:

1. ``days_between`` reproduces QuantLib's date arithmetic exactly. Every
   displayed or thresholded day count goes through it, so if this holds, no
   panel can disagree with the price.
2. ``program_trading_date`` does not advance while the US market's day has
   not — the 20:00 ET rollover that #182 fixed.

The "was" values in the docstrings below are what the code produced before
#182. They are recorded deliberately: this is a behaviour change, and a
future reader should be able to see what moved without digging through git.
"""

from __future__ import annotations

import datetime
from datetime import datetime as dt
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import QuantLib as QtLib

from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.clock import (
    DEFAULT_PROGRAM_TIMEZONE,
    days_between,
    program_trading_date,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import load_ips_config
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.valuation import OptionValuation

ET = ZoneInfo("America/New_York")
EXAMPLE_IPS_YAML = Path("config/ips.example.yaml")


class TestDaysBetween:
    """``days_between`` is a calendar difference, not a floored subtraction."""

    def test_ignores_time_of_day(self) -> None:
        """A day count must not depend on when in the day it is taken.

        Was: ``(maturity - as_of).days`` returned 20 for every hour past
        midnight, and 21 only at exactly 00:00.
        """
        maturity = dt(2026, 9, 1, tzinfo=datetime.UTC)
        for hour in (0, 9, 14, 23):
            as_of = dt(2026, 8, 11, hour, 30, tzinfo=datetime.UTC)
            assert days_between(as_of, maturity) == 21

    def test_matches_quantlib_date_arithmetic(self) -> None:
        """The count must equal the one the pricing engine uses.

        ``OptionValuation`` builds its ``QtLib.Date`` from the datetime's
        ``.day``/``.month``/``.year``. This is the property that makes a
        displayed days-to-expiry trustworthy.
        """
        maturity = dt(2026, 9, 1, tzinfo=datetime.UTC)
        for hour in (0, 9, 14, 23):
            as_of = dt(2026, 8, 11, hour, 30, tzinfo=datetime.UTC)
            ql_days = QtLib.Date(
                maturity.day,
                maturity.month,
                maturity.year,
            ) - QtLib.Date(as_of.day, as_of.month, as_of.year)
            assert days_between(as_of, maturity) == ql_days

    def test_reads_each_side_in_its_own_timezone(self) -> None:
        """Mixed timezones follow QuantLib, which reads the stored fields.

        A book loaded from YAML carries UTC-midnight maturities while the
        valuation date is in the program's timezone. Subtracting the
        datetimes would mix the two; comparing dates does not.
        """
        as_of = dt(2026, 8, 11, tzinfo=ET)
        maturity = dt(2026, 9, 1, tzinfo=datetime.UTC)
        assert days_between(as_of, maturity) == 21

    def test_negative_once_expired(self) -> None:
        """Past maturities count down through zero, not clamped."""
        as_of = dt(2026, 9, 3, 14, 30, tzinfo=datetime.UTC)
        maturity = dt(2026, 9, 1, tzinfo=datetime.UTC)
        assert days_between(as_of, maturity) == -2

    def test_zero_on_the_expiry_date(self) -> None:
        """Expiry day is day zero regardless of the hour it is evaluated."""
        maturity = dt(2026, 9, 1, tzinfo=datetime.UTC)
        assert days_between(dt(2026, 9, 1, 23, 59, tzinfo=ET), maturity) == 0


class TestProgramTradingDate:
    """The program's "today" tracks the market's day, not the server's."""

    def test_normalized_to_midnight(self) -> None:
        """Time of day is stripped, so the book prices the same all day."""
        now = dt(2026, 8, 11, 14, 37, 22, 123456, tzinfo=datetime.UTC)
        assert program_trading_date(ET, now=now) == dt(2026, 8, 11, tzinfo=ET)

    def test_does_not_roll_over_in_the_evening(self) -> None:
        """The 20:00 ET rollover #182 fixed.

        Was: 20:30 ET resolved to Aug 12, because UTC had already crossed
        midnight — repricing the whole book a day forward mid-review.
        """
        evening = dt(2026, 8, 11, 20, 30, tzinfo=ET)
        assert program_trading_date(ET, now=evening).date() == datetime.date(
            2026,
            8,
            11,
        )

    def test_converts_a_utc_instant_into_the_program_day(self) -> None:
        """A UTC ``now`` is converted, not reinterpreted."""
        utc_instant = dt(2026, 8, 12, 1, 30, tzinfo=datetime.UTC)
        resolved = program_trading_date(ET, now=utc_instant)
        assert resolved.date() == datetime.date(2026, 8, 11)

    def test_defaults_to_the_us_equity_calendar(self) -> None:
        """No timezone argument means the exchange's, not the server's."""
        utc_instant = dt(2026, 8, 12, 1, 30, tzinfo=datetime.UTC)
        assert program_trading_date(now=utc_instant) == program_trading_date(
            DEFAULT_PROGRAM_TIMEZONE,
            now=utc_instant,
        )

    def test_is_timezone_aware(self) -> None:
        """Never hands back a naive datetime — the #182 failure mode."""
        assert program_trading_date(ET).tzinfo is not None


class TestTheFixReachesTheDecisions:
    """The corrected day count reaches the panels, not just the helper.

    The floor was harmless in the helper and harmful here: a roll verdict
    reads a boundary in ``ips.yaml``, so a count one day short crossed
    ``expiry_urgent_days`` / ``expiry_soon_days`` a day early.
    """

    @staticmethod
    def _book_with_tenor(days: int, as_of: dt) -> OptionPortfolio:
        """A one-leg SPX put book with an exact *days* calendar tenor."""
        book = OptionPortfolio(
            spot_price=5000.0,
            volatility=0.20,
            risk_free_rate=0.04,
            dividend_yield=0.015,
            underlying_quantity=100.0,
            valuation_date=as_of,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        book.add_position(
            strike_price=4500.0,
            maturity_date=as_of + timedelta(days=days),
            quantity=10,
            option_type=OptionType.PUT,
        )
        return book

    def test_roll_status_dte_is_the_tenor_asked_for(self) -> None:
        """A 21-day book reports 21 days, at any hour of the day.

        Was: 20 at every hour past midnight, because the valuation date
        carried a time of day and the subtraction floored.
        """
        ips = load_ips_config(EXAMPLE_IPS_YAML)
        for hour in (0, 9, 14, 23):
            as_of = dt(2026, 8, 11, hour, 30, tzinfo=ET)
            book = self._book_with_tenor(21, as_of)

            records = evaluate_roll_status(book, ips)

            assert records[0].days_to_maturity == 21

    def test_dte_agrees_with_the_priced_tenor(self) -> None:
        """The displayed count equals the one QuantLib priced against.

        This is the property the whole fix exists for: a roll verdict and
        the price it is weighed against must describe the same option.
        """
        as_of = dt(2026, 8, 11, 14, 30, tzinfo=ET)
        book = self._book_with_tenor(21, as_of)
        ips = load_ips_config(EXAMPLE_IPS_YAML)

        record = evaluate_roll_status(book, ips)[0]
        option: OptionValuation = book.positions[0].option

        priced_days = option.ql_maturity_date - option.ql_valuation_date
        assert record.days_to_maturity == priced_days
