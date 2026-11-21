"""Synthetic MarketData.app chain responses, from the engine-priced chains.

Never a real response: the contracts are the ones ``tests/chain_builders``
prices with this repo's own engine, re-laid in MarketData's column-array
shape the way a dated request (``?date=...&expiration=all``) returns it:
the session's close quotes, the index close as ``underlyingPrice``, every
``updated`` at 16:00 New York on the session, and no IV (the vendor solves
none for a dated request).
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from tests.chain_builders import SESSION, SPOT, standard_chain

_NEW_YORK = ZoneInfo("America/New_York")


def close_stamp(session: date) -> int:
    """Return 16:00 New York on *session* as Unix seconds (the vendor's)."""
    return int(
        datetime.combine(session, time(16, 0), tzinfo=_NEW_YORK).timestamp()
    )


def md_response(
    cboe_payload: dict[str, Any] | None = None,
    *,
    session: date = SESSION,
    spot: float = SPOT,
) -> dict[str, Any]:
    """Return a MarketData chain response holding *cboe_payload*'s contracts."""
    contracts = (cboe_payload or standard_chain(spot=spot))["data"]["options"]
    count = len(contracts)
    stamp = close_stamp(session)
    return {
        "s": "ok",
        "optionSymbol": [c["option"] for c in contracts],
        "underlying": ["SPX"] * count,
        "bid": [c["bid"] for c in contracts],
        "ask": [c["ask"] for c in contracts],
        "openInterest": [c.get("open_interest") for c in contracts],
        "volume": [c.get("volume") for c in contracts],
        "underlyingPrice": [spot] * count,
        "updated": [stamp] * count,
        "iv": [None] * count,
    }


def md_payload(
    response: dict[str, Any] | None = None,
    *,
    session: date = SESSION,
) -> dict[str, Any]:
    """Return the cache payload the fetch writes: response and session."""
    return {
        "source": "marketdata",
        "session_date": session.isoformat(),
        "response": response
        if response is not None
        else md_response(session=session),
    }
