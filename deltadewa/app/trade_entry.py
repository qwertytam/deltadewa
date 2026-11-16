"""Close, settle and roll: from a form's raw values to a recorded trade (#446).

The ``/design`` BOOK zone's trade forms are thin: they hand their raw field
values to this module and render what comes back. Everything that decides
whether a form is complete, what it would record, and what to tell the
operator before it does lives here, with no Dash import, so it is tested
with plain values.

Review, then confirm
    Each form is two steps. :func:`parse_close` (and its siblings) turn the
    raw values into a typed entry or raise :class:`TradeEntryError` naming
    the field; ``review_*`` says in words exactly what the entry would
    record, including the cash, from :func:`~deltadewa.portfolio.history.
    fill_cash` (the one cash formula, shared with a recorded fill); ``record_*``
    calls the ``ProgramState`` trade method with ``confirm=True``. The page
    keeps the *raw values* between the two steps and parses them again at
    confirm, so what is recorded is what was reviewed and no serialiser sits
    between them.

Unknown is not zero
    A fee, a price or a settlement value left blank is **refused**, never
    read as ``0.0``: ``0.0`` is a recorded zero and blank is "not captured",
    and the history keeps them apart. Every check here is ``is None``, never
    falsiness, because ``0.0`` is falsy and a legitimate answer.

Dates
    A blank trade date means today's program date, which ``ProgramState``
    resolves from :mod:`deltadewa.clock` when it is ``None``. This module
    is handed ``today`` and reads the clock only through
    :func:`program_day`, which is :func:`~deltadewa.clock.
    program_trading_date`; it never calls the stdlib. A trade dated in the
    future is refused. One dated on or before the latest boundary mark is
    allowed but warned about: that mark was taken without it, so realized
    carry will not tie around that date. It is listed as a break when the
    mark falls after the opening mark (``realized_carry._late_fill_breaks``)
    and by no period when it falls before it, so the warning promises only
    that the figures will not tie, never that a break will say so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING, Any, Final

from deltadewa.analysis.crash_repricing import is_expired
from deltadewa.analysis.roll_planner import group_into_structures
from deltadewa.clock import program_trading_date
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.formatters.values import format_currency
from deltadewa.portfolio.history import (
    CloseReason,
    ContractTerms,
    OpenOrder,
    RollLeg,
    fill_cash,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from deltadewa.portfolio.position import OptionPosition
    from deltadewa.state import ProgramState

#: The roll form's structure choices: a tagged structure by its tag, a
#: standalone lot by its own id, so a single leg is a structure of one.
_TAG_PREFIX: Final = "tag:"
_LOT_PREFIX: Final = "lot:"


class TradeEntryError(ValueError):
    """A form is incomplete or names something the book does not hold."""


@dataclass(frozen=True)
class Review:
    """What a trade would record, in words, before it is recorded.

    Attributes:
        summary: One sentence naming the trade.
        lines: One line per fill, with its cash.
        warnings: Things the operator should know that do not block it.

    """

    summary: str
    lines: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class CloseEntry:
    """A validated close form."""

    position_id: str
    contracts: int
    price_per_share: float
    fees: float
    reason: CloseReason
    trade_date: date | None
    note: str | None


@dataclass(frozen=True)
class SettleEntry:
    """A validated settle form."""

    position_id: str
    settlement_per_share: float
    fees: float
    trade_date: date
    note: str | None


@dataclass(frozen=True)
class RollLegEntry:  # pylint: disable=too-many-instance-attributes  # one field per form column
    """One leg's block of a validated roll form."""

    position_id: str
    close_price_per_share: float
    close_fees: float
    strike: float
    maturity: date
    quantity: int | None
    price_per_share: float
    fees: float


@dataclass(frozen=True)
class RollEntry:
    """A validated roll form: every leg of one structure, rolled together."""

    legs: tuple[RollLegEntry, ...]
    reason: CloseReason
    trade_date: date | None
    structure_tag: str | None
    note: str | None


def program_day(state: ProgramState) -> datetime:
    """Return the program's current trading date, as midnight in its zone."""
    zone = state.ips_config.program.timezone if state.ips_config else None
    return program_trading_date(zone)


def program_today(state: ProgramState) -> date:
    """Return the program's current trading date."""
    return program_day(state).date()


def _utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


# ── Parsing ─────────────────────────────────────────────────────────────


def _number(
    raw: Mapping[str, Any],
    key: str,
    label: str,
    *,
    minimum: float = 0.0,
    hint: str = "",
) -> float:
    """Return a required, finite number at or above *minimum*."""
    value = raw.get(key)
    if value is None or value == "":
        raise TradeEntryError(f"{label} is required{hint}.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TradeEntryError(f"{label} must be a number.") from exc
    if not math.isfinite(number):
        raise TradeEntryError(f"{label} must be a number.")
    if number < minimum:
        raise TradeEntryError(f"{label} cannot be below {minimum:g}.")
    return number


def _fees(raw: Mapping[str, Any], key: str, label: str) -> float:
    return _number(raw, key, label, hint=" (enter 0 if there were none)")


def _whole(raw: Mapping[str, Any], key: str, label: str) -> int:
    number = _number(raw, key, label, minimum=1.0)
    if not number.is_integer():
        raise TradeEntryError(f"{label} must be a whole number of contracts.")
    return int(number)


def _date(value: object, label: str) -> date:
    if not isinstance(value, str) or not value:
        raise TradeEntryError(f"{label} is required.")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise TradeEntryError(f"{label} is not a valid date.") from exc


def _optional_date(
    raw: Mapping[str, Any],
    key: str,
    label: str,
    *,
    today: date,
) -> date | None:
    """Read an optional date: blank is today, a future one is refused."""
    value = raw.get(key)
    if value is None or value == "":
        return None
    parsed = _date(value, label)
    if parsed > today:
        raise TradeEntryError(
            f"{label} is {parsed}, after today ({today}): record a trade "
            "once it has happened.",
        )
    return parsed


def _reason(raw: Mapping[str, Any]) -> CloseReason:
    value = raw.get("reason")
    if value is None or value == "":
        raise TradeEntryError(
            "Reason is required: ROUTINE or MONETIZATION decides whether "
            "the proceeds count against gross carry.",
        )
    try:
        return CloseReason(value)
    except ValueError as exc:
        raise TradeEntryError(f"Unknown reason {value!r}.") from exc


def _position_id(raw: Mapping[str, Any], label: str = "Lot") -> str:
    value = raw.get("position_id")
    if not isinstance(value, str) or not value:
        raise TradeEntryError(f"{label} is required: pick one.")
    return value


def _note(raw: Mapping[str, Any]) -> str | None:
    text = raw.get("note")
    return text.strip() or None if isinstance(text, str) else None


def parse_close(raw: Mapping[str, Any], *, today: date) -> CloseEntry:
    """Validate a close form.

    Raises:
        TradeEntryError: A field is blank, not a number, or in the future.

    """
    return CloseEntry(
        position_id=_position_id(raw),
        contracts=_whole(raw, "contracts", "Contracts to close"),
        price_per_share=_number(raw, "price", "Price per share"),
        fees=_fees(raw, "fees", "Fees"),
        reason=_reason(raw),
        trade_date=_optional_date(raw, "date", "Trade date", today=today),
        note=_note(raw),
    )


def parse_settle(raw: Mapping[str, Any], *, today: date) -> SettleEntry:
    """Validate a settle form.

    The date is required: it decides which period the cash lands in, and
    the right answer is a fact from the statement, not a default.

    Raises:
        TradeEntryError: A field is blank, not a number, or in the future.

    """
    settled_on = _date(raw.get("date"), "Settlement date")
    if settled_on > today:
        raise TradeEntryError(
            f"Settlement date is {settled_on}, after today ({today}).",
        )
    return SettleEntry(
        position_id=_position_id(raw),
        settlement_per_share=_number(
            raw,
            "settlement",
            "Settlement value per share",
            hint=" (enter 0 if it expired worthless)",
        ),
        fees=_fees(raw, "fees", "Fees"),
        trade_date=settled_on,
        note=_note(raw),
    )


def _new_quantity(raw: Mapping[str, Any]) -> int | None:
    """Read the new lot's signed size; ``None`` keeps the old lot's."""
    value = raw.get("quantity")
    if value is None or value == "":
        return None
    try:
        signed = float(value)
    except (TypeError, ValueError) as exc:
        raise TradeEntryError("New quantity must be a number.") from exc
    if not math.isfinite(signed) or not signed.is_integer() or signed == 0:
        raise TradeEntryError(
            "New quantity must be a non-zero whole number of contracts "
            "(negative for a short leg), or blank to keep the old quantity.",
        )
    return int(signed)


def _parse_roll_leg(raw: Mapping[str, Any], number: int) -> RollLegEntry:
    try:
        return RollLegEntry(
            position_id=_position_id(raw),
            close_price_per_share=_number(
                raw,
                "close_price",
                "Closing price per share",
            ),
            close_fees=_fees(raw, "close_fees", "Closing fees"),
            strike=_number(raw, "strike", "New strike", minimum=0.01),
            maturity=_date(raw.get("maturity"), "New maturity"),
            quantity=_new_quantity(raw),
            price_per_share=_number(raw, "price", "New price per share"),
            fees=_fees(raw, "fees", "New fees"),
        )
    except TradeEntryError as exc:
        raise TradeEntryError(f"Leg {number}: {exc}") from exc


def parse_roll(raw: Mapping[str, Any], *, today: date) -> RollEntry:
    """Validate a roll form: one block per leg of the chosen structure.

    Raises:
        TradeEntryError: A field is blank, not a number, or in the future,
            or the form has no legs.

    """
    leg_values = raw.get("legs")
    if not isinstance(leg_values, (list, tuple)) or not leg_values:
        raise TradeEntryError("Pick the structure to roll.")
    tag = raw.get("tag")
    return RollEntry(
        legs=tuple(
            _parse_roll_leg(values, number)
            for number, values in enumerate(leg_values, start=1)
        ),
        reason=_reason(raw),
        trade_date=_optional_date(raw, "date", "Trade date", today=today),
        structure_tag=tag.strip() or None if isinstance(tag, str) else None,
        note=_note(raw),
    )


_ADD_REQUIRED_MESSAGE: Final = "Strike, maturity, and quantity are required."


def parse_open(
    raw: Mapping[str, Any],
    *,
    today: date,
) -> tuple[OpenOrder, date | None]:
    """Validate the add-position form as the opening fill it records.

    The premium and the fees are both required: ``OpenOrder`` has no
    "price not captured", and a trade entered through this form is entered
    *as* a fill, so a blank fee is refused rather than recorded as zero. A
    lot already held, with no trade to record, comes in through the
    importer, which starts the history at an opening mark.

    Returns:
        The order, and the trade date (``None`` for today's program date).

    Raises:
        TradeEntryError: A field is blank, not a number, or in the future.

    """
    strike = raw.get("strike")
    maturity = raw.get("maturity")
    quantity = raw.get("quantity")
    if strike is None or not maturity or quantity is None:
        raise TradeEntryError(_ADD_REQUIRED_MESSAGE)
    whole = _number(raw, "quantity", "Quantity", minimum=-1e9)
    if not whole.is_integer() or whole == 0:
        raise TradeEntryError(
            "Quantity must be a non-zero whole number of contracts.",
        )
    tag = raw.get("structure_id")
    order = OpenOrder(
        strike_price=_number(raw, "strike", "Strike", minimum=0.01),
        maturity_date=_utc_midnight(_date(maturity, "Maturity")),
        option_type=OptionType(str(raw.get("option_type"))),
        quantity=int(whole),
        price_per_share=_number(
            raw,
            "price",
            "Entry premium",
            hint=" (the fill price per share)",
        ),
        fees=_fees(raw, "fees", "Fees"),
        exercise_style=ExerciseStyle(str(raw.get("exercise_style"))),
        structure_id=tag.strip() or None if isinstance(tag, str) else None,
    )
    return order, _optional_date(raw, "date", "Trade date", today=today)


# ── What the book holds ─────────────────────────────────────────────────


def _lot(
    positions: Sequence[OptionPosition], position_id: str
) -> OptionPosition:
    for position in positions:
        if position.position_id == position_id:
            return position
    raise TradeEntryError(
        "That lot is no longer in the book (it was changed or removed since "
        "the form was filled in). Pick it again.",
    )


def lot_label(position: OptionPosition) -> str:
    """Name a lot as the history does, with its signed size."""
    terms = ContractTerms.from_position(position)
    return f"{terms.describe()} ({int(position.quantity):+d})"


def unsettled_lots(
    positions: Sequence[OptionPosition],
    *,
    valuation_date: datetime,
) -> tuple[OptionPosition, ...]:
    """Return the lots at or past expiry that are still in the book.

    The boundary is :func:`~deltadewa.analysis.crash_repricing.is_expired`,
    the same call ``mark_book`` makes for ``LegMark.expired_unsettled``.
    Pass the program's day (:func:`program_day`), not the running app's
    ``portfolio.valuation_date``: the weekly job loads the book afresh, so
    its mark is taken on the program's day, while the app's own date is
    seeded once at boot and lags after a midnight. A settled lot has left the
    book, so what remains here is by construction not settled.
    """
    return tuple(
        position
        for position in positions
        if is_expired(position, valuation_date=valuation_date)
    )


def structure_options(
    positions: Sequence[OptionPosition],
) -> list[dict[str, str]]:
    """Return the roll form's structure choices, in book order."""
    options: list[dict[str, str]] = []
    for structure in group_into_structures(positions):
        legs = ", ".join(lot_label(leg) for leg in structure.legs)
        if structure.structure_id is None:
            value = f"{_LOT_PREFIX}{structure.legs[0].position_id}"
            label = legs
        else:
            value = f"{_TAG_PREFIX}{structure.structure_id}"
            label = f"{structure.structure_id}: {legs}"
        options.append({"label": label, "value": value})
    return options


def structure_legs(
    positions: Sequence[OptionPosition],
    key: str,
) -> tuple[OptionPosition, ...]:
    """Return the legs of the structure a roll form's choice names.

    Raises:
        TradeEntryError: The choice is not in the book any more.

    """
    for structure in group_into_structures(positions):
        if structure.structure_id is None:
            candidate = f"{_LOT_PREFIX}{structure.legs[0].position_id}"
        else:
            candidate = f"{_TAG_PREFIX}{structure.structure_id}"
        if candidate == key:
            return structure.legs
    raise TradeEntryError(
        "That structure is no longer in the book. Pick it again.",
    )


# ── Review ──────────────────────────────────────────────────────────────


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _warnings(
    trade_date: date | None,
    *,
    today: date,
    last_mark: date | None,
) -> tuple[str, ...]:
    """Warn about a trade dated inside a period the history already closed."""
    when = trade_date or today
    if last_mark is not None and when <= last_mark:
        return (
            (
                f"Dated {when}, on or before the {last_mark} boundary mark, "
                "which was taken without this trade: realized carry will "
                "not tie to your statements for that stretch. Record trades "
                "the week they happen."
            ),
        )
    return ()


def _side(quantity: int) -> str:
    return "Buy" if quantity > 0 else "Sell"


def _fill_line(  # pylint: disable=too-many-arguments
    verb: str,
    count: int,
    terms: ContractTerms,
    *,
    price: float,
    fees: float,
    quantity: int,
) -> str:
    cash = fill_cash(
        quantity=quantity,
        price_per_share=price,
        fees=fees,
        contract_size=terms.contract_size,
    )
    return (
        f"{verb} {count} x {terms.describe()} at {_money(price)} per share, "
        f"fees {_money(fees)}: cash {format_currency(cash, show_sign=True)}"
    )


def _when(trade_date: date | None, today: date) -> str:
    return f"{trade_date}" if trade_date else f"{today} (today)"


def review_close(
    entry: CloseEntry,
    positions: Sequence[OptionPosition],
    *,
    today: date,
    last_mark: date | None,
) -> Review:
    """Say what a close would record.

    Raises:
        TradeEntryError: The lot is gone, or fewer contracts are held than
            the form asks to close.

    """
    position = _lot(positions, entry.position_id)
    held = int(position.quantity)
    if entry.contracts > abs(held):
        raise TradeEntryError(
            f"Cannot close {entry.contracts} contracts of a "
            f"{abs(held)}-contract lot.",
        )
    direction = 1 if held > 0 else -1
    moved = -direction * entry.contracts
    terms = ContractTerms.from_position(position)
    remaining = abs(held) - entry.contracts
    left = f"{remaining} remain" if remaining else "the lot is closed"
    return Review(
        summary=(
            f"Close {entry.contracts} of {abs(held)} contracts of "
            f"{terms.describe()} ({entry.reason.value}); {left}. "
            f"Dated {_when(entry.trade_date, today)}."
        ),
        lines=(
            _fill_line(
                "Buy back" if held < 0 else "Sell",
                entry.contracts,
                terms,
                price=entry.price_per_share,
                fees=entry.fees,
                quantity=moved,
            ),
        ),
        warnings=_warnings(entry.trade_date, today=today, last_mark=last_mark),
    )


def review_settle(
    entry: SettleEntry,
    positions: Sequence[OptionPosition],
    *,
    today: date,
    last_mark: date | None,
) -> Review:
    """Say what a settlement would record.

    Raises:
        TradeEntryError: The lot is gone, or the date precedes its expiry.

    """
    position = _lot(positions, entry.position_id)
    terms = ContractTerms.from_position(position)
    if entry.trade_date < terms.expiry:
        raise TradeEntryError(
            f"{terms.describe()} expires {terms.expiry}; it cannot settle "
            f"on {entry.trade_date}.",
        )
    held = int(position.quantity)
    worthless = (
        " (expired worthless)" if entry.settlement_per_share == 0 else ""
    )
    return Review(
        summary=(
            f"Settle {abs(held)} contracts of {terms.describe()}"
            f"{worthless}. Dated {entry.trade_date}. The lot leaves the book."
        ),
        lines=(
            _fill_line(
                "Settle",
                abs(held),
                terms,
                price=entry.settlement_per_share,
                fees=entry.fees,
                quantity=-held,
            ),
        ),
        warnings=_warnings(entry.trade_date, today=today, last_mark=last_mark),
    )


def review_roll(
    entry: RollEntry,
    positions: Sequence[OptionPosition],
    *,
    today: date,
    last_mark: date | None,
) -> Review:
    """Say what a roll would record: two fills per leg, each its own cash.

    The package net is shown so it can be checked against the broker's
    confirmation, and labelled as what it is: the fills are recorded
    separately and the net is not stored.

    Raises:
        TradeEntryError: A lot is gone, or the legs are not the whole of
            the structure they came from.

    """
    held = [_lot(positions, leg.position_id) for leg in entry.legs]
    _require_whole_structure(held, positions)
    lines: list[str] = []
    net = 0.0
    for number, (leg, old) in enumerate(zip(entry.legs, held, strict=True), 1):
        old_terms = ContractTerms.from_position(old)
        old_qty = int(old.quantity)
        new_qty = leg.quantity if leg.quantity is not None else old_qty
        size = old_terms.contract_size
        new_terms = ContractTerms(
            option_type=old_terms.option_type,
            strike=leg.strike,
            expiry=leg.maturity,
            contract_size=size,
            exercise_style=old_terms.exercise_style,
        )
        lines.append(
            f"Leg {number} close: "
            + _fill_line(
                "Buy back" if old_qty < 0 else "Sell",
                abs(old_qty),
                old_terms,
                price=leg.close_price_per_share,
                fees=leg.close_fees,
                quantity=-old_qty,
            ),
        )
        lines.append(
            f"Leg {number} open: "
            + _fill_line(
                _side(new_qty),
                abs(new_qty),
                new_terms,
                price=leg.price_per_share,
                fees=leg.fees,
                quantity=new_qty,
            ),
        )
        net += fill_cash(
            quantity=-old_qty,
            price_per_share=leg.close_price_per_share,
            fees=leg.close_fees,
            contract_size=size,
        ) + fill_cash(
            quantity=new_qty,
            price_per_share=leg.price_per_share,
            fees=leg.fees,
            contract_size=size,
        )
    lines.append(
        f"Package net {format_currency(net, show_sign=True)}: for checking "
        "against the broker's confirmation only. The fills above are "
        "recorded separately; the net is not stored.",
    )
    count = len(entry.legs)
    return Review(
        summary=(
            f"Roll {count} leg{'s' if count != 1 else ''} "
            f"({entry.reason.value}), each as a close and an open at its own "
            f"price and fees. Dated {_when(entry.trade_date, today)}. "
            "All legs are recorded together, or none are."
        ),
        lines=tuple(lines),
        warnings=_warnings(entry.trade_date, today=today, last_mark=last_mark),
    )


def _require_whole_structure(
    held: Sequence[OptionPosition],
    positions: Sequence[OptionPosition],
) -> None:
    """Refuse a roll that would leave part of a structure behind.

    The form is built from a structure's legs; a leg added to that
    structure since would stay on the old maturity beside the rolled ones.
    """
    tags = {leg.structure_id for leg in held}
    if len(tags) != 1:
        raise TradeEntryError(
            "These lots are not one structure. Pick the structure again.",
        )
    (tag,) = tags
    if tag is None:
        return
    members = {p.position_id for p in positions if p.structure_id == tag}
    chosen = {leg.position_id for leg in held}
    if members != chosen:
        raise TradeEntryError(
            f"Structure {tag!r} changed since the form was opened. Pick it "
            "again.",
        )


# ── Recording ───────────────────────────────────────────────────────────


def record_close(entry: CloseEntry, state: ProgramState) -> None:
    """Record a close. The operator has confirmed it."""
    state.close_position(
        entry.position_id,
        contracts=entry.contracts,
        price_per_share=entry.price_per_share,
        fees=entry.fees,
        reason=entry.reason,
        trade_date=entry.trade_date,
        note=entry.note,
        confirm=True,
    )


def record_settle(entry: SettleEntry, state: ProgramState) -> None:
    """Record a settlement. The operator has confirmed it."""
    state.settle_position(
        entry.position_id,
        settlement_per_share=entry.settlement_per_share,
        fees=entry.fees,
        trade_date=entry.trade_date,
        note=entry.note,
        confirm=True,
    )


def _roll_leg(
    leg: RollLegEntry,
    old: OptionPosition,
    *,
    tag: str | None,
) -> RollLeg:
    """Build one leg's request, inheriting what the form does not ask."""
    return RollLeg(
        position_id=leg.position_id,
        close_price_per_share=leg.close_price_per_share,
        close_fees=leg.close_fees,
        into=OpenOrder(
            strike_price=leg.strike,
            maturity_date=_utc_midnight(leg.maturity),
            option_type=OptionType(old.option.option_type),
            quantity=(
                leg.quantity if leg.quantity is not None else int(old.quantity)
            ),
            price_per_share=leg.price_per_share,
            fees=leg.fees,
            contract_size=int(old.contract_size),
            exercise_style=ExerciseStyle(old.exercise_style),
            structure_id=tag if tag is not None else old.structure_id,
        ),
    )


def record_roll(entry: RollEntry, state: ProgramState) -> None:
    """Record a roll of one structure, atomically. The operator confirmed.

    Raises:
        TradeEntryError: A lot is gone or the structure changed.

    """
    positions = state.positions_snapshot()
    held = [_lot(positions, leg.position_id) for leg in entry.legs]
    _require_whole_structure(held, positions)
    state.roll_structure(
        [
            _roll_leg(leg, old, tag=entry.structure_tag)
            for leg, old in zip(entry.legs, held, strict=True)
        ],
        reason=entry.reason,
        trade_date=entry.trade_date,
        note=entry.note,
        confirm=True,
    )


def last_mark_date(state: ProgramState) -> date | None:
    """Return the latest boundary mark's date, or ``None`` if there is none."""
    history = state.history
    if history is None:
        return None
    marks = history.load().marks
    return marks[-1].mark_date if marks else None
