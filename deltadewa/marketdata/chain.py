"""Cboe delayed-quote option chain: parse it, date it, match a contract.

Pure: no I/O, no clock. The provider fetches and caches the raw payload;
this module turns it into a :class:`ChainSnapshot` and answers "which
listed contract is this leg?". Everything here was measured on a real
payload in the 9b.0 spike (``docs/market-data.md``, "Option-chain spike"):

- A contract is named in OCC form: root, ``YYMMDD``, ``C`` or ``P``, then
  the strike times 1000 as eight digits. The expiry date is read **from the
  symbol**, never recomputed as a third Friday: a standard monthly moves to
  the Thursday when the Friday is an exchange holiday.
- Three roots appear. ``SPX`` is the AM-settled monthly, ``SPXW`` the PM
  weekly/daily, and ``SPXO`` an unidentified third that is never matched.
  Where both ``SPX`` and ``SPXW`` list a date, ``SPX`` is preferred and the
  match says so (:attr:`MatchFlag.AMBIGUOUS_ROOT`).
- The top-level ``timestamp`` is **naive UTC**; the only quote time in the
  payload. A contract's ``last_trade_time`` says nothing about quote age.
- A contract's ``iv`` is a decimal fraction, and ``0`` means the vendor did
  not solve it (deep in the money, or unquoted): a bid and an IV are tested
  separately.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from functools import cached_property
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

import QuantLib as QtLib

from deltadewa.constants import OptionType
from deltadewa.marketdata._errors import MarketDataError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "SESSION_CLOSE",
    "ChainMatch",
    "ChainQuote",
    "ChainSnapshot",
    "MatchFlag",
    "parse_cboe_chain",
    "quote_session_date",
    "session_close",
]

_NEW_YORK: Final[ZoneInfo] = ZoneInfo("America/New_York")
_NYSE: Final[QtLib.Calendar] = QtLib.UnitedStates(QtLib.UnitedStates.NYSE)

#: Before this New York time a payload still describes the previous session.
_SESSION_OPEN: Final[time] = time(9, 30)

#: SPX options trade until 16:15 New York; the close a quote is dated to.
SESSION_CLOSE: Final[time] = time(16, 15)

#: Roots whose contracts are kept. ``SPXO`` (two odd Wednesdays, never
#: identified) is dropped at parse and can never be matched.
_STANDARD_ROOT: Final[str] = "SPX"
_WEEKLY_ROOT: Final[str] = "SPXW"
_KEPT_ROOTS: Final[frozenset[str]] = frozenset({_STANDARD_ROOT, _WEEKLY_ROOT})

_OCC: Final[re.Pattern[str]] = re.compile(
    r"^(?P<root>[A-Z]+)(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})"
    r"(?P<right>[CP])(?P<strike>\d{8})$",
)
_STRIKE_SCALE: Final[float] = 1000.0


class MatchFlag(StrEnum):
    """Why a chain reading is missing or not safe to price from."""

    ABSENT = "ABSENT"
    """The contract is not listed on either root."""
    ZERO_BID = "ZERO-BID"
    """No bid: a mid built from it is not a price anyone would pay."""
    NO_ASK = "NO-ASK"
    """No ask."""
    WIDE = "WIDE"
    """Spread wider than the policy's ``max_spread_pct``."""
    NO_SOLVE = "NO-SOLVE"
    """The mid is outside the no-arbitrage bounds at the book's r and q."""
    AMBIGUOUS_ROOT = "AMBIGUOUS-ROOT"
    """Both ``SPX`` and ``SPXW`` list the date; ``SPX`` was used."""
    STALE_QUOTE = "STALE-QUOTE"
    """The snapshot's session is older than ``max_quote_age_days``."""


@dataclass(frozen=True, slots=True)
class ChainQuote:
    """One listed contract's close quote.

    Attributes:
        symbol: The OCC symbol as the vendor wrote it.
        root: ``SPX`` or ``SPXW``.
        expiry: Expiry date, read from the symbol.
        option_type: Call or put.
        strike: Strike in index points.
        bid: Per-share bid (``0.0`` when absent).
        ask: Per-share ask (``0.0`` when absent).
        vendor_iv: The vendor's implied volatility as a fraction, or
            ``None`` when it did not solve one (the vendor writes ``0``).
        open_interest: Contracts, or ``None`` when absent.
        volume: Contracts traded, or ``None`` when absent.

    """

    symbol: str
    root: str
    expiry: date
    option_type: OptionType
    strike: float
    bid: float
    ask: float
    vendor_iv: float | None
    open_interest: int | None
    volume: int | None

    @property
    def mid(self) -> float:
        """Midpoint of bid and ask."""
        return (self.bid + self.ask) / 2.0

    @property
    def spread_pct(self) -> float | None:
        """``(ask - bid) / mid`` in percent; ``None`` without a mid."""
        mid = self.mid
        if mid <= 0.0:
            return None
        return (self.ask - self.bid) / mid * 100.0


@dataclass(frozen=True, slots=True)
class ChainMatch:
    """The result of looking one contract up.

    Attributes:
        quote: The contract used, or ``None`` when it is not listed.
        flags: What is wrong with it (empty when it is clean).
        other_root: The same contract on the other root, when both list it.

    """

    quote: ChainQuote | None
    flags: frozenset[MatchFlag]
    other_root: ChainQuote | None = None


@dataclass(frozen=True)
class ChainSnapshot:
    """A parsed chain: the index level, when it was struck, the contracts.

    Attributes:
        underlying: The vendor's symbol for the chain (``_SPX``).
        spot: The index level in the payload (``current_price``), struck at
            the same instant as the quotes.
        quoted_at: When the payload was generated (timezone-aware UTC).
        session_date: The trading session the quotes belong to.
        quotes: Every kept contract.

    """

    underlying: str
    spot: float
    quoted_at: datetime
    session_date: date
    quotes: tuple[ChainQuote, ...]

    @cached_property
    def _index(
        self,
    ) -> dict[tuple[date, OptionType, float], list[ChainQuote]]:
        index: dict[tuple[date, OptionType, float], list[ChainQuote]] = {}
        for quote in self.quotes:
            key = (quote.expiry, quote.option_type, round(quote.strike, 3))
            index.setdefault(key, []).append(quote)
        return index

    @property
    def session_close(self) -> datetime:
        """The close the snapshot is dated to (aware, New York)."""
        return session_close(self.session_date)

    def match(
        self,
        *,
        expiry: date,
        option_type: OptionType,
        strike: float,
        max_spread_pct: float,
    ) -> ChainMatch:
        """Find one contract and say whether its quote is usable.

        ``SPX`` is preferred; ``SPXW`` is used only where ``SPX`` does not
        list the date. Where both list it the match carries
        :attr:`MatchFlag.AMBIGUOUS_ROOT` and the other root's quote.

        Args:
            expiry: The expiry date.
            option_type: Call or put.
            strike: The strike in index points.
            max_spread_pct: Spread above which the quote is ``WIDE``.

        Returns:
            The match. ``quote`` is ``None`` (flag ``ABSENT``) when neither
            root lists the contract.

        """
        candidates = self._index.get((expiry, option_type, round(strike, 3)))
        if not candidates:
            return ChainMatch(None, frozenset({MatchFlag.ABSENT}))
        by_root = {quote.root: quote for quote in candidates}
        flags: set[MatchFlag] = set()
        other: ChainQuote | None = None
        if _STANDARD_ROOT in by_root:
            quote = by_root[_STANDARD_ROOT]
            if _WEEKLY_ROOT in by_root:
                flags.add(MatchFlag.AMBIGUOUS_ROOT)
                other = by_root[_WEEKLY_ROOT]
        else:
            quote = by_root[_WEEKLY_ROOT]
        if quote.bid <= 0.0:
            flags.add(MatchFlag.ZERO_BID)
        if quote.ask <= 0.0:
            flags.add(MatchFlag.NO_ASK)
        spread = quote.spread_pct
        if (
            quote.bid > 0.0
            and quote.ask > 0.0
            and spread is not None
            and spread > max_spread_pct
        ):
            flags.add(MatchFlag.WIDE)
        return ChainMatch(quote, frozenset(flags), other)

    def expiries(self, *, root: str = _STANDARD_ROOT) -> tuple[date, ...]:
        """Return the expiry dates *root* lists, ascending."""
        return tuple(
            sorted({q.expiry for q in self.quotes if q.root == root}),
        )

    def listed_strikes(
        self,
        *,
        expiry: date,
        option_type: OptionType,
    ) -> tuple[float, ...]:
        """Return the strikes listed on *expiry* (either root), ascending."""
        return tuple(
            sorted(
                {
                    q.strike
                    for q in self.quotes
                    if q.expiry == expiry and q.option_type is option_type
                },
            ),
        )


def _is_trading_day(day: date) -> bool:
    """Whether the NYSE is open on *day*."""
    return bool(
        _NYSE.isBusinessDay(QtLib.Date(day.day, day.month, day.year)),
    )


def session_close(day: date) -> datetime:
    """Return the SPX options close on *day* (16:15, aware New York)."""
    return datetime.combine(day, SESSION_CLOSE, tzinfo=_NEW_YORK)


def quote_session_date(quoted_at: datetime) -> date:
    """Return the trading session a payload's quotes belong to.

    A payload generated overnight, at a weekend or on a holiday describes
    the last session that closed; one generated from 09:30 New York on a
    trading day describes that day.

    Args:
        quoted_at: When the payload was generated (timezone-aware).

    Returns:
        The session date.

    Raises:
        ValueError: If *quoted_at* is naive.

    """
    if quoted_at.tzinfo is None:
        raise ValueError("quoted_at must be timezone-aware")
    local = quoted_at.astimezone(_NEW_YORK)
    day = local.date()
    if local.time() < _SESSION_OPEN:
        day -= timedelta(days=1)
    while not _is_trading_day(day):
        day -= timedelta(days=1)
    return day


def _number(raw: Any, field: str, symbol: str) -> float:  # ruff: ignore[any-type]  # JSON scalar
    """Read a numeric contract field, treating null as zero."""
    if raw is None:
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise MarketDataError(
            f"chain contract {symbol}: field {field!r} is not a number",
        ) from exc
    if not math.isfinite(value):
        # JSON's Infinity/NaN parse as floats; int() of one would raise an
        # OverflowError the job does not contain.
        raise MarketDataError(
            f"chain contract {symbol}: field {field!r} is not finite",
        )
    return value


def _parse_quote(raw: Mapping[str, Any]) -> ChainQuote | None:
    """Parse one contract, or return ``None`` for a dropped root."""
    symbol = str(raw["option"])
    found = _OCC.match(symbol)
    if found is None:
        raise MarketDataError(
            f"chain contract symbol {symbol!r} is not in OCC form",
        )
    root = found["root"]
    if root not in _KEPT_ROOTS:
        return None
    try:
        expiry = date(
            2000 + int(found["yy"]),
            int(found["mm"]),
            int(found["dd"]),
        )
    except ValueError as exc:
        raise MarketDataError(
            f"chain contract symbol {symbol!r} has an invalid date",
        ) from exc
    iv = _number(raw.get("iv"), "iv", symbol)
    oi = raw.get("open_interest")
    volume = raw.get("volume")
    return ChainQuote(
        symbol=symbol,
        root=root,
        expiry=expiry,
        option_type=(
            OptionType.CALL if found["right"] == "C" else OptionType.PUT
        ),
        strike=int(found["strike"]) / _STRIKE_SCALE,
        bid=_number(raw.get("bid"), "bid", symbol),
        ask=_number(raw.get("ask"), "ask", symbol),
        vendor_iv=iv if iv > 0.0 else None,
        open_interest=None if oi is None else int(_number(oi, "oi", symbol)),
        volume=None if volume is None else int(_number(volume, "vol", symbol)),
    )


def parse_cboe_chain(payload: Mapping[str, Any]) -> ChainSnapshot:
    """Turn a Cboe delayed-quote payload into a :class:`ChainSnapshot`.

    ``SPXO`` contracts are dropped. Every way this can fail is reported as
    :class:`~deltadewa.marketdata.MarketDataError`, never as a bare
    ``KeyError`` or ``ValueError``: it runs inside the refresh job's fetch,
    where only ``MarketDataError`` is contained per series, and a payload
    that does not parse must not replace a good cache entry.

    Args:
        payload: The decoded JSON (``timestamp``, ``data``, ``symbol``).

    Returns:
        The parsed snapshot.

    Raises:
        MarketDataError: On any malformed or unrecognised payload.

    """
    try:
        data = payload["data"]
        stamp = datetime.strptime(  # parsed naive, tagged UTC next
            str(payload["timestamp"]),
            "%Y-%m-%d %H:%M:%S",
        ).replace(tzinfo=UTC)
        spot = float(data["current_price"])
        raw_options = data["options"]
        quotes = tuple(
            quote
            for quote in (_parse_quote(raw) for raw in raw_options)
            if quote is not None
        )
        underlying = str(payload.get("symbol", ""))
    except (
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        OverflowError,
    ) as exc:
        raise MarketDataError(
            f"unreadable option-chain payload: {exc}",
        ) from exc
    if spot <= 0.0 or not quotes:
        raise MarketDataError(
            "option-chain payload has no usable index level or contracts",
        )
    return ChainSnapshot(
        underlying=underlying,
        spot=spot,
        quoted_at=stamp,
        session_date=quote_session_date(stamp),
        quotes=quotes,
    )
