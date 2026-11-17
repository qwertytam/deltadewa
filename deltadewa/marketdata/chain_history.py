"""A small daily record of the option chain: the start of our own IV history.

Cboe's free delayed-quote endpoint has no history: a day's quotes that are
not saved are gone. The refresh job therefore appends a few hundred rows
after each live chain fetch to ``exports/chain-history/SPX-<year>.jsonl``.
They are the raw close quotes (bid, ask, the vendor's IV, open interest), not
a solved IV: a raw row can be re-solved at any rate and dividend yield later.

Two kinds of row, both keyed by the chain's trading **session**:

- ``held``: one per option the book holds, so the book's own contracts have
  a daily quote history without anyone remembering to look.
- ``market``: about 120 fixed points: the standard ``SPX`` expiries from 30
  days to 3 years out, the listed put nearest 5, 10, 20, 30, 40 and 50% out
  of the money, and the at-the-money put and call. These survive rolls, so
  the series stays comparable year to year.

This is the only chain data under ``exports/`` (the raw payload lives in the
cache folder, outside the git-backed backup): about 5 MB a year.

Idempotent per session: a second run for a session already recorded writes
nothing. A book that cannot be read costs only the ``held`` rows.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from deltadewa import constants as const
from deltadewa.constants import OptionType

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from deltadewa.marketdata.chain import ChainQuote, ChainSnapshot

__all__ = [
    "HeldContract",
    "append_daily_record",
    "market_quotes",
    "read_held_contracts",
]

_logger = logging.getLogger(__name__)

#: How far out of the money the fixed market points sit.
_PCT_OTM: Final[tuple[float, ...]] = (5.0, 10.0, 20.0, 30.0, 40.0, 50.0)
_MIN_DAYS_OUT: Final[int] = 30
_MAX_DAYS_OUT: Final[int] = 3 * const.DAYS_PER_YEAR

#: A spread no quote reaches: the record keeps every quote, usable or not.
_ANY_SPREAD: Final[float] = float("inf")


@dataclass(frozen=True)
class HeldContract:
    """One option the book holds, as the chain names it."""

    expiry: date
    option_type: OptionType
    strike: float


def read_held_contracts(book_path: Path) -> tuple[HeldContract, ...]:
    """Read the held options from the book file, read-only.

    Deliberately not :meth:`ProgramState.load`: that attaches the position
    history and takes the state lock, and the refresh job must have no such
    side effects on a book the app owns.

    Args:
        book_path: ``exports/program_state.json``.

    Returns:
        The distinct contracts, in book order.

    Raises:
        OSError: If the file cannot be read.
        ValueError: If it is not JSON.
        KeyError: If a position lacks a contract field.
        TypeError: If the document is not the expected shape.

    """
    document = json.loads(book_path.read_text(encoding="utf-8"))
    held: list[HeldContract] = []
    for position in document["positions"]:
        contract = HeldContract(
            expiry=datetime.fromisoformat(position["maturity_date"]).date(),
            option_type=OptionType(position["option_type"]),
            strike=float(position["strike_price"]),
        )
        if contract not in held:
            held.append(contract)
    return tuple(held)


def _nearest(strikes: Sequence[float], wanted: float) -> float:
    """Return the listed strike closest to *wanted*."""
    return min(strikes, key=lambda listed: abs(listed - wanted))


def market_quotes(snapshot: ChainSnapshot) -> list[ChainQuote]:
    """Return the fixed market points off *snapshot*.

    Args:
        snapshot: The parsed chain.

    Returns:
        One quote per distinct (expiry, type, strike) point, for the
        standard expiries 30 days to 3 years out.

    """
    low = snapshot.session_date + timedelta(days=_MIN_DAYS_OUT)
    high = snapshot.session_date + timedelta(days=_MAX_DAYS_OUT)
    points: dict[tuple[date, OptionType, float], ChainQuote] = {}
    for expiry in snapshot.expiries():
        if not low <= expiry <= high:
            continue
        puts = snapshot.listed_strikes(
            expiry=expiry,
            option_type=OptionType.PUT,
        )
        calls = snapshot.listed_strikes(
            expiry=expiry,
            option_type=OptionType.CALL,
        )
        wanted: list[tuple[OptionType, float]] = []
        if puts:
            wanted.extend(
                (
                    OptionType.PUT,
                    _nearest(puts, snapshot.spot * (1.0 - pct / 100.0)),
                )
                for pct in _PCT_OTM
            )
            wanted.append((OptionType.PUT, _nearest(puts, snapshot.spot)))
        if calls:
            wanted.append((OptionType.CALL, _nearest(calls, snapshot.spot)))
        for option_type, strike in wanted:
            quote = snapshot.match(
                expiry=expiry,
                option_type=option_type,
                strike=strike,
                max_spread_pct=_ANY_SPREAD,
            ).quote
            if quote is not None:
                points[expiry, option_type, strike] = quote
    return list(points.values())


def _row(
    kind: str,
    quote: ChainQuote,
    snapshot: ChainSnapshot,
) -> dict[str, Any]:
    """Serialise one quote."""
    return {
        "session": snapshot.session_date.isoformat(),
        "kind": kind,
        "symbol": quote.symbol,
        "root": quote.root,
        "expiry": quote.expiry.isoformat(),
        "type": quote.option_type.value,
        "strike": quote.strike,
        "bid": quote.bid,
        "ask": quote.ask,
        "vendor_iv": quote.vendor_iv,
        "open_interest": quote.open_interest,
        "volume": quote.volume,
        "underlying": snapshot.spot,
    }


def _last_session(path: Path) -> str | None:
    """Return the session of the file's last readable row, or ``None``."""
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            return str(json.loads(line)["session"])
        except (ValueError, KeyError, TypeError):
            continue
    return None


def append_daily_record(
    snapshot: ChainSnapshot,
    held: Iterable[HeldContract] | None,
    history_dir: Path,
) -> int:
    """Append one session's rows to ``<history_dir>/SPX-<year>.jsonl``.

    Args:
        snapshot: The parsed chain.
        held: The contracts the book holds, or ``None`` when the book could
            not be read (the market rows are still written).
        history_dir: Where the yearly files live; created if absent.

    Returns:
        The number of rows written; ``0`` when this session is already
        recorded.

    """
    history_dir.mkdir(parents=True, exist_ok=True)
    path = history_dir / f"SPX-{snapshot.session_date.year}.jsonl"
    session = snapshot.session_date.isoformat()
    if _last_session(path) == session:
        return 0
    rows: list[dict[str, Any]] = []
    for contract in held or ():
        quote = snapshot.match(
            expiry=contract.expiry,
            option_type=contract.option_type,
            strike=contract.strike,
            max_spread_pct=_ANY_SPREAD,
        ).quote
        if quote is None:
            _logger.warning(
                "chain history: a held option is not listed on the chain",
            )
            continue
        rows.append(_row("held", quote, snapshot))
    rows.extend(
        _row("market", quote, snapshot) for quote in market_quotes(snapshot)
    )
    payload = "".join(json.dumps(row) + "\n" for row in rows)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
    return len(rows)
