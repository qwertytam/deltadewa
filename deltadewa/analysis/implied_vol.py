"""Solve an implied volatility with this program's own pricing engine.

A vendor's quoted IV is an answer to "which volatility reprices this mid at
*the vendor's* rate and dividend yield". The book is priced at *its* rate
and yield, so a vendor IV adopted next to a different (r, q) misprices the
leg: 9b.0 measured about 6-8% of a one-year put's price per percentage
point of difference (``docs/market-data.md``, "Option-chain spike"). The IV
solved here, from the mid, with :class:`~deltadewa.valuation.OptionValuation`
at the caller's own (r, q), reprices the leg to that mid by construction.

SPX options are European-exercise (CLAUDE.md, "Domain rules"), so this
always prices with the analytic engine.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import TYPE_CHECKING, Final

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.valuation import OptionValuation

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["cmt_to_continuous", "solve_implied_vol"]

#: Search bracket, as annualised fractions. Wide enough for any listed SPX
#: contract; a mid outside it is reported as unsolvable, not clamped.
_VOL_FLOOR: Final[float] = 0.01
_VOL_CEILING: Final[float] = 3.0
_MAX_STEPS: Final[int] = 80
_VOL_TOLERANCE: Final[float] = 1e-10


def cmt_to_continuous(yield_pct: float) -> float:
    """Convert a Treasury constant-maturity yield to a continuous rate.

    FRED's ``DGS`` series are bond-equivalent yields in percent (semi-annual
    compounding); the pricing engine takes a continuously compounded rate.

    Args:
        yield_pct: The yield in percent (``4.60`` for 4.60%).

    Returns:
        The continuously compounded rate as a fraction.

    """
    return 2.0 * math.log(1.0 + yield_pct / 200.0)


def _midnight(day: date) -> datetime:
    """Return midnight on *day* as the naive datetime the engine reads."""
    return datetime(day.year, day.month, day.day)


def solve_implied_vol(  # pylint: disable=too-many-arguments
    *,
    price: float,
    strike: float,
    expiry: date,
    option_type: OptionType,
    spot: float,
    risk_free_rate: float,
    dividend_yield: float,
    valuation_date: date,
) -> float | None:
    """Return the volatility at which the engine prices *price*, or ``None``.

    Bisection on the analytic European price, which rises with volatility.

    Args:
        price: Per-share price to match (a mid).
        strike: Strike in index points.
        expiry: Expiry date.
        option_type: Call or put.
        spot: Underlying level the price was struck against.
        risk_free_rate: Continuously compounded rate, as a fraction.
        dividend_yield: Continuous dividend yield, as a fraction.
        valuation_date: The date the price was struck (the quote's session).

    Returns:
        The annualised volatility as a fraction, or ``None`` when the price
        is not positive, the contract has expired, or the price lies outside
        what any volatility in the search bracket produces (a mid below the
        model's value at the floor, or above its value at the ceiling).

    """
    if price <= 0.0 or valuation_date >= expiry or spot <= 0.0:
        return None
    option = OptionValuation(
        spot_price=spot,
        strike_price=strike,
        maturity_date=_midnight(expiry),
        volatility=_VOL_FLOOR,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        exercise_style=ExerciseStyle.EUROPEAN,
        option_type=option_type,
        valuation_date=_midnight(valuation_date),
    )

    def model_price(vol: float) -> float:
        option.update_volatility(vol)
        return float(option.price())

    return _bisect(model_price, price)


def _bisect(
    model_price: Callable[[float], float],
    target: float,
) -> float | None:
    """Find the volatility in the bracket where the model hits *target*."""
    low, high = _VOL_FLOOR, _VOL_CEILING
    if model_price(low) > target or model_price(high) < target:
        return None
    for _ in range(_MAX_STEPS):
        middle = (low + high) / 2.0
        if model_price(middle) < target:
            low = middle
        else:
            high = middle
        if high - low < _VOL_TOLERANCE:
            break
    return (low + high) / 2.0
