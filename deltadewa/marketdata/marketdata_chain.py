"""MarketData.app as the option-chain source (9b, ``chain_source: marketdata``).

Cboe's delayed-quote file, the first chain source, has been refused to
automated clients since November 2026. MarketData.app sells the same
contracts through a REST API under a licence for internal use, which is
how this program uses them (a private app and its own encrypted backup; no
redistribution).

**What is fetched, and when it is from.** One request for the whole SPX
chain (both roots, every expiry) **for the last fully closed session**,
``GET /v1/options/chain/SPX/?date=<session>&expiration=all``. A session is
"fully closed", and so available, from 09:30 New York on the next trading
day; until then the one before it is the latest. A date request is cheap
(the vendor charges one credit per thousand contracts, about 25 credits for
the whole chain), and it carries the official close: the contracts' close
quotes and, as ``underlyingPrice``, the index's official close. The vendor
returns no IV for a dated request; nothing here needs one, because every IV
this program uses is solved from the mid by its own engine.

**Why the lag is accepted.** A dated request serves only fully closed
sessions (the vendor's trial tier allows nothing else), so the book is
priced on the previous session's close for the whole of the next trading
day (and on Thursday's close over a weekend, until Monday's 09:30
release). Every surface already states which close
the book is priced on, and ``pricing_feed.max_quote_age_days`` bounds it.

**The token** is ``MARKETDATA_TOKEN`` in the jobs container's environment
(the host's ``.env``). It is sent only in the ``Authorization`` header,
never in a URL, a log line or an error message. The app never fetches, so
it never needs the token.

**The cached payload** is the vendor's response, unchanged, wrapped with
the session it was requested for: ``{"source": "marketdata",
"session_date": "YYYY-MM-DD", "response": {...}}``. The parse runs inside
the fetch, before the cache write, so a response that does not parse never
replaces a good entry.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

import requests

from deltadewa.marketdata._errors import MarketDataError
from deltadewa.marketdata.chain import (
    ChainQuote,
    ChainSnapshot,
    finite_number,
    is_trading_day,
    parse_occ_symbol,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "MARKETDATA_TOKEN_ENV",
    "fetch_marketdata_chain",
    "latest_closed_session",
    "marketdata_session_date",
    "parse_marketdata_chain",
]

#: The environment variable holding the API token (the jobs container's
#: ``.env``). Never logged.
MARKETDATA_TOKEN_ENV: Final[str] = "MARKETDATA_TOKEN"  # ruff: ignore[hardcoded-password-string] - a variable name, not a secret

_CHAIN_URL: Final[str] = "https://api.marketdata.app/v1/options/chain/{und}/"

#: The whole chain is a few megabytes; the default 10 s is too short.
_TIMEOUT_SECONDS: Final[int] = 60

_NEW_YORK: Final[ZoneInfo] = ZoneInfo("America/New_York")

#: A session becomes available ("fully closed") at this New York time on
#: the next trading day (the vendor's data-freshness rule).
_RELEASE: Final[time] = time(9, 30)

#: The vendor's "your plan cannot do this" status, used for a session the
#: plan cannot see yet.
_PAYMENT_REQUIRED: Final[int] = 402

#: Statuses carrying a body: 200, and 203 (served from the vendor's cache).
_OK_STATUSES: Final[frozenset[int]] = frozenset({200, 203})

#: The vendor's 402 for a session the plan cannot yet see names the latest
#: one it can: "... the latest available is 2026-11-19."
_LATEST_AVAILABLE: Final[re.Pattern[str]] = re.compile(
    r"latest available is (\d{4}-\d{2}-\d{2})",
)

#: The column arrays a dated chain response must carry, one element per
#: contract.
_COLUMNS: Final[tuple[str, ...]] = (
    "optionSymbol",
    "bid",
    "ask",
    "underlyingPrice",
)

_SOURCE: Final[str] = "marketdata"


def _previous_trading_day(day: date) -> date:
    day -= timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def latest_closed_session(now: datetime) -> date:
    """Return the last session the vendor serves as fully closed at *now*.

    A session is released at 09:30 New York on the trading day after it.
    So the answer is the trading day before the latest release that has
    passed: Saturday gives Thursday (Friday's is released on Monday), and a
    weekday before 09:30 gives the session two trading days back.

    Raises:
        ValueError: If *now* is naive.

    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(_NEW_YORK)
    released_on = local.date()
    if not is_trading_day(released_on) or local.time() < _RELEASE:
        released_on = _previous_trading_day(released_on)
    return _previous_trading_day(released_on)


def _error_text(response: requests.Response) -> str:
    """Return the vendor's ``errmsg``, or the status line; never the request."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(body, dict) and isinstance(body.get("errmsg"), str):
        return f"HTTP {response.status_code}: {body['errmsg']}"
    return f"HTTP {response.status_code}"


def _request(
    session: requests.Session,
    *,
    token: str,
    underlying: str,
    day: date,
) -> requests.Response:
    try:
        return session.get(
            _CHAIN_URL.format(und=underlying),
            params={"date": day.isoformat(), "expiration": "all"},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        # The exception text can carry the URL, never the header; still,
        # name only its type so nothing request-shaped reaches a log.
        raise MarketDataError(
            f"MarketData chain request failed ({type(exc).__name__})",
        ) from None


def fetch_marketdata_chain(
    session: requests.Session,
    *,
    token: str | None,
    underlying: str,
    now: datetime,
) -> dict[str, Any]:
    """Download the chain for the last fully closed session.

    If the vendor says a later session is not yet available and names the
    latest one it serves, that one is requested instead, once: its release
    can run late, and a holiday the two calendars disagree on must not cost
    the night's chain.

    Args:
        session: The HTTP session.
        token: The API token, or ``None`` when it is not configured.
        underlying: The chain's underlying (``SPX``).
        now: The current instant (aware), to choose the session.

    Returns:
        The cache payload: the vendor's response wrapped with its session.

    Raises:
        MarketDataError: With no token, on any HTTP or vendor error, or a
            body that is not a successful chain. The token never appears in
            the message.

    """
    if not token:
        raise MarketDataError(
            f"{MARKETDATA_TOKEN_ENV} is not set: the MarketData chain "
            "source needs the API token in the jobs container's .env",
        )
    day = latest_closed_session(now)
    response = _request(session, token=token, underlying=underlying, day=day)
    if response.status_code == _PAYMENT_REQUIRED:
        named = _LATEST_AVAILABLE.search(_error_text(response))
        if named is not None:
            earlier = date.fromisoformat(named.group(1))
            if earlier < day:
                day = earlier
                response = _request(
                    session,
                    token=token,
                    underlying=underlying,
                    day=day,
                )
    if response.status_code not in _OK_STATUSES:
        raise MarketDataError(
            f"MarketData chain for {day}: {_error_text(response)}",
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise MarketDataError(
            "MarketData chain response is not valid JSON",
        ) from exc
    if not isinstance(body, dict) or body.get("s") != "ok":
        status = body.get("s") if isinstance(body, dict) else None
        raise MarketDataError(
            f"MarketData chain for {day} returned status {status!r}",
        )
    return {
        "source": _SOURCE,
        "session_date": day.isoformat(),
        "response": body,
    }


def marketdata_session_date(payload: Mapping[str, Any]) -> date | None:
    """Return the session a cached payload was fetched for, or ``None``.

    Cheap and never raises: the disk cache uses it to decide whether a new
    payload is a new session (the ``.prev`` rotation).
    """
    try:
        return date.fromisoformat(str(payload["session_date"]))
    except (KeyError, TypeError, ValueError):
        return None


def _columns(response: Mapping[str, Any]) -> dict[str, list[Any]]:
    """Read the column arrays, all the same length, or raise."""
    columns: dict[str, list[Any]] = {}
    for name in (
        *_COLUMNS,
        "updated",
        "iv",
        "openInterest",
        "volume",
    ):
        values = response.get(name)
        if values is None and name not in _COLUMNS:
            continue
        if not isinstance(values, list):
            raise MarketDataError(
                f"MarketData chain response has no {name!r} column",
            )
        columns[name] = values
    lengths = {len(values) for values in columns.values()}
    if len(lengths) != 1:
        raise MarketDataError(
            "MarketData chain response columns differ in length",
        )
    return columns


def _optional_int(
    values: list[Any] | None,
    index: int,
    field: str,
    symbol: str,
) -> int | None:
    if values is None or values[index] is None:
        return None
    return int(finite_number(values[index], field, symbol))


def _quote(columns: dict[str, list[Any]], index: int) -> ChainQuote | None:
    symbol = str(columns["optionSymbol"][index])
    terms = parse_occ_symbol(symbol)
    if terms is None:
        return None
    ivs = columns.get("iv")
    iv = finite_number(ivs[index], "iv", symbol) if ivs is not None else 0.0
    return ChainQuote(
        symbol=symbol,
        root=terms.root,
        expiry=terms.expiry,
        option_type=terms.option_type,
        strike=terms.strike,
        bid=finite_number(columns["bid"][index], "bid", symbol),
        ask=finite_number(columns["ask"][index], "ask", symbol),
        vendor_iv=iv if iv > 0.0 else None,
        open_interest=_optional_int(
            columns.get("openInterest"),
            index,
            "openInterest",
            symbol,
        ),
        volume=_optional_int(columns.get("volume"), index, "volume", symbol),
    )


def _quoted_at(columns: dict[str, list[Any]], session_date: date) -> datetime:
    """When the quotes were struck: the latest ``updated``, as aware UTC.

    A dated response's quotes are that session's close; an ``updated`` on
    another day means the vendor served a session other than the one asked
    for, which must not be cached under the wrong date.
    """
    stamps = [
        finite_number(value, "updated", "chain")
        for value in columns.get("updated", [])
        if value is not None
    ]
    if not stamps:
        return datetime.combine(
            session_date,
            time(16, 0),
            tzinfo=_NEW_YORK,
        ).astimezone(UTC)
    quoted_at = datetime.fromtimestamp(max(stamps), tz=UTC)
    if quoted_at.astimezone(_NEW_YORK).date() != session_date:
        raise MarketDataError(
            f"MarketData chain asked for {session_date} carries quotes "
            f"from {quoted_at.astimezone(_NEW_YORK).date()}",
        )
    return quoted_at


def parse_marketdata_chain(payload: Mapping[str, Any]) -> ChainSnapshot:
    """Turn a cached MarketData payload into a :class:`ChainSnapshot`.

    Every way this can fail is a :class:`MarketDataError`: it runs inside
    the refresh job's fetch, where only that error is contained per series.

    Raises:
        MarketDataError: On a malformed payload, mismatched columns, a
            non-finite number, no usable index level or no contracts.

    """
    try:
        if payload.get("source") != _SOURCE:
            raise MarketDataError("not a MarketData chain payload")
        session_date = date.fromisoformat(str(payload["session_date"]))
        response = payload["response"]
        if not isinstance(response, dict):
            raise MarketDataError("MarketData chain payload has no response")
        columns = _columns(response)
        count = len(columns["optionSymbol"])
        quotes = tuple(
            quote
            for quote in (_quote(columns, index) for index in range(count))
            if quote is not None
        )
        spots = [
            finite_number(value, "underlyingPrice", "chain")
            for value in columns["underlyingPrice"]
            if value is not None
        ]
        quoted_at = _quoted_at(columns, session_date)
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OverflowError,
    ) as exc:
        raise MarketDataError(
            f"unreadable MarketData chain payload: {exc}",
        ) from exc
    spot = max(spots) if spots else 0.0
    if not math.isfinite(spot) or spot <= 0.0 or not quotes:
        raise MarketDataError(
            "MarketData chain has no usable index level or contracts",
        )
    underlyings = response.get("underlying")
    return ChainSnapshot(
        underlying=(
            str(underlyings[0])
            if isinstance(underlyings, list) and underlyings
            else ""
        ),
        spot=spot,
        quoted_at=quoted_at,
        session_date=session_date,
        quotes=quotes,
    )
