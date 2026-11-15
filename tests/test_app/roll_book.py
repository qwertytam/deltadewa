"""A book that exercises every roll action, for the browser smoke suite (#476).

The smoke fixture used to boot with no IPS, so the roll plan, the roll status
table and ``/monitor``'s Decisions panel were never rendered in CI: #468's
screenshots had to come from a scratch script because the suite could not
take them. This is the book the IPS-backed fixture seeds, so each of those
three surfaces renders each of the five actions the plan can print.

It is built for ``config/ips.example.yaml`` (a 180-day roll window, a 270-day
review buffer, rally bands of 5/10/15/20% and a 10-20% crash-convexity band)
and for nothing else: change the example IPS and
``test_the_book_covers_every_action`` fails, which is the point of pinning it.

Every leg is a long SPX put, priced off one spot, with a distinct strike so a
row is findable by its label. What puts each one where it is:

========  ====  =====================================================
strike    DTE   why it lands on its action
========  ====  =====================================================
5,000     120   inside the 180-day window: the time trigger reads ROLL
5,200     230   in the review buffer, entered at today's spot: ROLL BY
5,400     240   in the buffer, but the spot has *fallen* since entry
                (the put is nearer the money, gaining gamma) and
                convexity is in band: DELAY
5,600     400   outside the buffer; the spot has rallied 12% since
                entry (the rally REVIEW band) and convexity is in
                band, so the review's condition is checked: CHECKED
5,800     420   outside the buffer, no rally: HOLD (no label printed)
========  ====  =====================================================

The underlying is sized so the book's crash convexity sits mid-band: DELAY
and CHECKED both need it ``WITHIN``, and a book out of band would turn every
leg's action into ROLL NOW (convexity BELOW) or hide the others behind it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final, NamedTuple

from deltadewa.constants import OptionType
from tests.clock_helpers import days_from_today

if TYPE_CHECKING:
    from deltadewa.state import ProgramState

SPOT: Final[float] = 6_300.0
"""The book's spot, and what the smoke fixture's market data reports."""

UNDERLYING_QUANTITY: Final[int] = 500
"""Sized for a crash convexity of about 14%: mid-way through 10-20%."""


class RollLeg(NamedTuple):
    """One seeded leg and the action the example IPS gives it."""

    strike: float
    days_to_maturity: int
    entry_spot: float
    action: str | None
    """The label the plan prints, or ``None`` for a leg that prints none."""


LEGS: Final[tuple[RollLeg, ...]] = (
    RollLeg(5_000.0, 120, SPOT, "ROLL NOW"),
    RollLeg(5_200.0, 230, SPOT, "ROLL BY"),
    RollLeg(5_400.0, 240, SPOT * 1.04, "DELAY"),
    RollLeg(5_600.0, 400, SPOT / 1.12, "CHECKED"),
    RollLeg(5_800.0, 420, SPOT, None),
)


def expected_label(leg: RollLeg, *, roll_window_days: int) -> str | None:
    """The action label the plan prints for *leg*, date included.

    A ROLL BY label carries the date the window opens: the leg's maturity less
    the window. Worked out here from the calendar, not asked of the code under
    test, so the browser tests compare the app against an independent count.
    """
    if leg.action != "ROLL BY":
        return leg.action
    maturity = days_from_today(leg.days_to_maturity).date()
    opens = maturity - timedelta(days=roll_window_days)
    return f"ROLL BY {opens.isoformat()}"


def seed_every_roll_action(state: ProgramState) -> None:
    """Fill *state*'s book with the five legs above, and its underlying."""
    portfolio = state.portfolio
    portfolio.symbol = "SPX"
    portfolio.spot_price = SPOT
    portfolio.underlying_quantity = UNDERLYING_QUANTITY
    for leg in LEGS:
        state.add_position(
            strike_price=leg.strike,
            maturity_date=days_from_today(leg.days_to_maturity),
            quantity=1,
            option_type=OptionType.PUT,
            entry_spot=leg.entry_spot,
            entry_premium=10.0,
        )
