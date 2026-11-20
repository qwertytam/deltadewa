"""Synthetic Cboe option chains for tests (9b).

Every contract is priced by this repo's own European engine from a known
volatility smile, so a test can ask "does the solver recover the smile?"
exactly. Nothing here is, or is derived from, a real payload: the chain
payload is never committed (size, redistribution), only built.

Dates are pinned absolute dates, never the wall clock.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.valuation import OptionValuation

#: The trading session the default chain describes (a Monday).
SESSION = date(2026, 11, 16)

#: When the payload was generated: naive UTC, 20:33 New York on SESSION.
TIMESTAMP = "2026-11-17 01:33:27"

SPOT = 5000.0
RATE = 0.045
DIVIDEND = 0.013

#: A standard monthly that sits on a Thursday (the Friday is a holiday).
JUNE_THURSDAY = date(2027, 6, 17)
DECEMBER = date(2027, 12, 17)
#: Listed on both ``SPX`` and ``SPXW``.
BOTH_ROOTS = date(2026, 12, 18)
#: Listed on ``SPXW`` only.
WEEKLY_ONLY = date(2026, 11, 20)


def smile(strike: float, spot: float = SPOT) -> float:
    """Return the volatility the synthetic market quotes at *strike*."""
    downside = max((spot - strike) / spot, 0.0)
    return 0.18 + 0.4 * downside


def occ(
    root: str,
    expiry: date,
    option_type: OptionType,
    strike: float,
) -> str:
    """Return an OCC symbol: root, YYMMDD, C/P, strike x 1000 (8 digits)."""
    right = "C" if option_type is OptionType.CALL else "P"
    return f"{root}{expiry:%y%m%d}{right}{round(strike * 1000):08d}"


def raw_contract(
    symbol: str,
    *,
    bid: float,
    ask: float,
    iv: float,
    open_interest: int | None = 1000,
    volume: int | None = 10,
) -> dict[str, Any]:
    """Return one contract as the vendor writes it."""
    return {
        "option": symbol,
        "bid": bid,
        "bid_size": 10.0,
        "ask": ask,
        "ask_size": 10.0,
        "iv": iv,
        "open_interest": open_interest,
        "volume": volume,
        "last_trade_time": None,
    }


def _midnight(day: date) -> datetime:
    """Return midnight on *day* as the naive datetime the engine reads."""
    return datetime(day.year, day.month, day.day)


def engine_price(
    expiry: date,
    option_type: OptionType,
    strike: float,
    *,
    vol: float,
    spot: float = SPOT,
    rate: float = RATE,
    dividend: float = DIVIDEND,
    valuation: date = SESSION,
) -> float:
    """Return the engine's European price at the given market."""
    return float(
        OptionValuation(
            spot_price=spot,
            strike_price=strike,
            maturity_date=_midnight(expiry),
            volatility=vol,
            risk_free_rate=rate,
            dividend_yield=dividend,
            exercise_style=ExerciseStyle.EUROPEAN,
            option_type=option_type,
            valuation_date=_midnight(valuation),
        ).price(),
    )


def priced_contract(  # pylint: disable=too-many-arguments
    root: str,
    expiry: date,
    option_type: OptionType,
    strike: float,
    *,
    half_spread: float = 0.01,
    spot: float = SPOT,
    rate: float = RATE,
    dividend: float = DIVIDEND,
) -> dict[str, Any]:
    """Return a contract quoted around the engine's price on the smile.

    The vendor IV written is the smile's own, so a test can compare it
    with the IV solved back from the mid.
    """
    vol = smile(strike, spot)
    price = engine_price(
        expiry,
        option_type,
        strike,
        vol=vol,
        spot=spot,
        rate=rate,
        dividend=dividend,
    )
    return raw_contract(
        occ(root, expiry, option_type, strike),
        bid=round(price * (1 - half_spread), 4),
        ask=round(price * (1 + half_spread), 4),
        iv=vol,
    )


def payload(
    contracts: list[dict[str, Any]],
    *,
    spot: float = SPOT,
    timestamp: str = TIMESTAMP,
) -> dict[str, Any]:
    """Wrap *contracts* in the vendor's top-level shape."""
    return {
        "timestamp": timestamp,
        "symbol": "_SPX",
        "data": {"current_price": spot, "options": contracts},
    }


def standard_chain(
    *,
    spot: float = SPOT,
    timestamp: str = TIMESTAMP,
) -> dict[str, Any]:
    """Return a small chain with every case the matcher must handle.

    - ``JUNE_THURSDAY`` and ``DECEMBER``: ``SPX`` puts, a 100-point grid.
    - ``BOTH_ROOTS``: the same puts on ``SPX`` and ``SPXW``.
    - ``WEEKLY_ONLY``: ``SPXW`` puts.
    - an ``SPXO`` contract that must never be matched.
    """
    strikes = [float(k) for k in range(2500, 5101, 100)]
    contracts: list[dict[str, Any]] = []
    for expiry, roots in (
        (JUNE_THURSDAY, ("SPX",)),
        (DECEMBER, ("SPX",)),
        (BOTH_ROOTS, ("SPX", "SPXW")),
        (WEEKLY_ONLY, ("SPXW",)),
    ):
        for root in roots:
            contracts.extend(
                priced_contract(
                    root,
                    expiry,
                    OptionType.PUT,
                    strike,
                    spot=spot,
                )
                for strike in strikes
            )
    contracts.append(
        raw_contract(
            occ("SPXO", date(2026, 11, 18), OptionType.PUT, 5000.0),
            bid=1.0,
            ask=1.1,
            iv=0.2,
        ),
    )
    return payload(contracts, spot=spot, timestamp=timestamp)
