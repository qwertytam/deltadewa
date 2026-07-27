"""Self-test for the clock-shift probe: proof that it still bites.

DO NOT REMOVE. A green clock-shift matrix only means something if the probe is
demonstrably able to fail on an unpinned target. Without these two tests, a
plugin that silently stopped shifting anything — a rename, a lost ``-p``, an
import-order regression — would report a perfectly green suite and prove
nothing at all.

Both tests are live at *every* shift, including 0. There is deliberately no
``skipif``, no inverted exit code, and no hardcoded golden: each of those is a
way for the check to quietly become a no-op, which is the exact failure mode
this file exists to prevent. At shift 0 they assert the clock did **not** move;
at any other shift they assert it did, and that it reached library code.

They therefore also run in the default gate, where they cost one pricing call
each and pin the unshifted branch.

Run under the probe with::

    CLOCK_SHIFT_DAYS=90 poetry run pytest -q -p tests.clockshift_plugin
"""

from __future__ import annotations

import datetime
import os
import time

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio

UTC = datetime.UTC

# time.time() is never patched by the probe, so this is the *real* now even
# under a shifted clock. Everything below is anchored on it: a canary that
# measured itself with the clock it is testing could not detect anything.
_REAL_NOW = datetime.datetime.fromtimestamp(time.time(), tz=UTC)

# Ten years out, so the option is still alive at the largest shift in the
# matrix (+3000d leaves ~650 days of tenor). An expiring canary would raise
# from QuantLib instead of asserting, turning a clear signal into a crash.
_MATURITY = _REAL_NOW + datetime.timedelta(days=3650)

# Same variable and same default as the plugin, so the two cannot disagree
# about how far the clock was supposed to move.
_EXPECTED_SHIFT = datetime.timedelta(
    days=int(os.environ.get("CLOCK_SHIFT_DAYS", "0")),
)

# Clock reads either side of a call can straddle midnight. Tolerate that, and
# nothing else.
_CLOCK_TOLERANCE = datetime.timedelta(minutes=5)
_DRIFT_BAND = 1.5


def _put_value(valuation_date: datetime.datetime | None) -> float:
    """Value a long-dated SPX put as of *valuation_date*.

    ``None`` leaves the portfolio to reach for ``datetime.now()`` itself,
    which is the code path the probe has to reach.
    """
    book = OptionPortfolio(
        spot_price=5000.0,
        volatility=0.20,
        risk_free_rate=0.04,
        dividend_yield=0.015,
        valuation_date=valuation_date,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    position = book.add_position(
        strike_price=4000.0,
        maturity_date=_MATURITY,
        quantity=10,
        option_type=OptionType.PUT,
    )
    return position.position_value()


class TestClockShiftProbeBites:
    """The probe must move the clock, and move it where it matters."""

    def test_probe_moves_the_library_clock(self) -> None:
        """deltadewa's own now() — not just the test module's — is shifted.

        This is the property whose absence once produced a confident report of
        23 broken tests when only 4 were real: the library was shifted while
        the test modules feeding it were not.
        """
        book = OptionPortfolio(spot_price=5000.0)

        observed = book.valuation_date - _REAL_NOW

        assert abs(observed - _EXPECTED_SHIFT) < _CLOCK_TOLERANCE

    def test_probe_moves_a_dte_sensitive_price(self) -> None:
        """A price anchored on now() moves under the shift, and only then.

        Reproduces the #205 defect shape exactly — absolute maturity, now()
        valuation date, assertion on a time-to-expiry-sensitive number — so a
        shift that fails to break this would also fail to break a real bomb.

        Self-calibrating against one day of theta rather than a golden: a
        golden here would itself drift with the calendar, which would be a
        fine irony and a bad test.
        """
        one_day = abs(
            _put_value(_REAL_NOW)
            - _put_value(_REAL_NOW + datetime.timedelta(days=1)),
        )
        assert one_day > 0.0, "put value is not time-sensitive; canary is blind"

        drift = abs(_put_value(None) - _put_value(_REAL_NOW))

        if _EXPECTED_SHIFT:
            assert drift > _DRIFT_BAND * one_day
        else:
            assert drift < _DRIFT_BAND * one_day
