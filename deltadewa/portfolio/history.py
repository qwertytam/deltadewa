"""Position history: the records realized carry is computed from (#313).

The handbook's `Realized Carry Methodology
<https://qwertytam.github.io/deltadewa-handbook/part-7/realized-carry-methodology/>`_
measures what the hedge actually cost over a period that has already
happened::

    Realized Carry $ = V0 + P - R - V1          (positive = a cost)

It needs two things nothing else in the program records. The first is
**fills** (P and R): cash paid for positions opened and received for
positions closed or settled, fees included, a roll as two events. The
second is **boundary marks** (V0 and V1): the book's mark-to-market at
each end of the period, on a stated basis, computed once and shared by
the two periods that meet at it. This module holds exactly those records
and nothing a period figure could be derived from instead. Greeks,
risk metrics, cash totals and carry are all derived, in
:mod:`deltadewa.analysis.realized_carry`.

Three record types
    :class:`Fill`
        A cash-moving trade: ``OPEN``, ``CLOSE`` (full or partial) or
        ``SETTLE`` (expiry; worthless is a settlement at zero; SPX is
        European and cash-settled, so exercise and assignment are
        settlements too).
    :class:`BookEdit`
        A change to the book that has **no fill**: a leg's terms or
        quantity edited in place, a leg deleted, the whole book replaced
        by an import. These are recorded rather than forbidden, so
        ``/design``'s correction workflow keeps working, and any period
        containing one is reported as not reconcilable. That is the
        handbook's reconciliation break, caught at the moment it happens
        rather than found at year-end.
    :class:`BookMark`
        One per program date: every open leg's model mark plus the
        inputs it was priced on, including how stale the spot was.

Unknown is not zero
    ``Fill.price_per_share`` and ``Fill.fees`` are nullable, and ``None``
    means *not captured*. Fees "booked to the account but never captured
    against a position" are the handbook's first-listed cause of a
    reconciliation break, so a missing fee must never quietly read as
    ``0.0``. An explicit ``0.0`` is a legal, recorded zero.

Before the history existed
    There is none. The layer starts at an *opening mark*
    (:attr:`BookMark.is_opening`), and legs held before it come in at
    that mark's V0, never as synthetic ``OPEN`` fills built from
    ``entry_premium``, which would charge years of premium to the first
    week. See :mod:`deltadewa.history`.

Storage is :mod:`deltadewa.history_store`; this module does no IO.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from deltadewa.constants import ExerciseStyle, OptionType

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition

#: On-disk record version. A reader refuses any other value rather than
#: guessing at a shape it was not written for.
SCHEMA_VERSION: Final = 1


class HistorySchemaError(ValueError):
    """A stored history record is malformed or of an unknown version."""


class FillKind(StrEnum):
    """What a cash-moving trade did to the book."""

    OPEN = "OPEN"
    CLOSE = "CLOSE"
    SETTLE = "SETTLE"


class EditKind(StrEnum):
    """A change to the book that moved no cash."""

    AMEND = "AMEND"
    DELETE = "DELETE"
    REPLACE = "REPLACE"


class CloseReason(StrEnum):
    """Why a position was closed: the handbook's gross/net partition of R.

    ``ROUTINE`` proceeds (expiries, scheduled rolls) reduce gross carry,
    which is the insurance premium measured against the carry budget.
    ``MONETIZATION`` proceeds, discretionary gains harvested in stress,
    are kept out of gross carry and reported in net carry only. The
    choice is recorded when the trade is entered, before the crisis, as
    the handbook asks, and never inferred afterwards.
    """

    ROUTINE = "ROUTINE"
    MONETIZATION = "MONETIZATION"


class MarkBasis(StrEnum):
    """How a mark was priced.

    The identity is only meaningful when both ends of a period share a
    basis. ``MODEL`` (the analytic engine at the book's hand-entered
    volatilities) is the only basis the program can produce today. A
    future mid-market basis would be a new member, and a period whose two
    marks disagree is refused rather than compared.
    """

    MODEL = "MODEL"


def new_event_id() -> str:
    """Return a fresh, unique event id."""
    return str(uuid.uuid4())


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware, got {value!r}")


@dataclass(frozen=True)
class ContractTerms:
    """The contract a lot holds: what is traded, not how much of it.

    Attributes:
        option_type: Put or call.
        strike: Strike price.
        expiry: Expiry date.
        contract_size: Shares per contract.
        exercise_style: European or American.

    """

    option_type: OptionType
    strike: float
    expiry: date
    contract_size: int
    exercise_style: ExerciseStyle

    @classmethod
    def from_position(cls, position: OptionPosition) -> ContractTerms:
        """Read the terms off a live position."""
        return cls(
            option_type=OptionType(position.option.option_type),
            strike=float(position.option.strike_price),
            expiry=position.option.maturity_date.date(),
            contract_size=int(position.contract_size),
            exercise_style=ExerciseStyle(position.exercise_style),
        )

    def describe(self) -> str:
        """Return a short label, e.g. ``PUT 4200 2027-06-18``."""
        return f"{self.option_type.value} {self.strike:g} {self.expiry}"

    def to_json(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "option_type": self.option_type.value,
            "strike": self.strike,
            "expiry": self.expiry.isoformat(),
            "contract_size": self.contract_size,
            "exercise_style": self.exercise_style.value,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ContractTerms:
        """Deserialize from :meth:`to_json`'s output."""
        return cls(
            option_type=OptionType(data["option_type"]),
            strike=float(data["strike"]),
            expiry=date.fromisoformat(data["expiry"]),
            contract_size=int(data["contract_size"]),
            exercise_style=ExerciseStyle(data["exercise_style"]),
        )


@dataclass(frozen=True)
class Fill:  # pylint: disable=too-many-instance-attributes  # one field per handbook column
    """One cash-moving trade.

    Attributes:
        event_id: Unique id; what :attr:`supersedes` points at.
        kind: ``OPEN``, ``CLOSE`` or ``SETTLE``.
        trade_date: When the trade happened, as a program trading date.
            Decides which period the cash belongs to.
        recorded_at: When it was entered (timezone-aware). Separate from
            ``trade_date`` so a fill recorded after the mark it should
            have been in is detectable as late.
        written_by: The writing process's label (#355).
        position_id: The lot. Cost basis is specific identification by
            lot: a partial close reduces this lot and no other.
        terms: The contract traded.
        quantity: Signed contracts moved **into** the book: ``+`` bought,
            ``-`` sold. Closing or settling a long leg is negative.
        price_per_share: The fill price, or for ``SETTLE`` the
            settlement value per share (``0.0`` when worthless). ``None``
            means not captured.
        fees: Commissions and fees, ``>= 0``. ``None`` means not captured,
            which is not the same as zero.
        reason: The R partition. Required for ``CLOSE``; ``SETTLE`` is
            always ``ROUTINE``; ``OPEN`` has none.
        roll_id: Links the close and open of one roll. A roll is two
            fills, never one net figure.
        supersedes: The ``event_id`` this record corrects. History is
            append-only: a mistyped fill is replaced by a later record,
            never edited in place.
        note: Free text for the operator.

    """

    event_id: str
    kind: FillKind
    trade_date: date
    recorded_at: datetime
    written_by: str
    position_id: str
    terms: ContractTerms
    quantity: int
    price_per_share: float | None
    fees: float | None
    reason: CloseReason | None = None
    roll_id: str | None = None
    supersedes: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        """Reject a fill no trade could have produced."""
        _require_aware(self.recorded_at, "recorded_at")
        if self.quantity == 0:
            raise ValueError("a fill must move a non-zero quantity")
        if self.price_per_share is not None and self.price_per_share < 0:
            raise ValueError(
                f"price_per_share must be >= 0, got {self.price_per_share}",
            )
        if self.fees is not None and self.fees < 0:
            raise ValueError(f"fees must be >= 0, got {self.fees}")
        if self.kind is FillKind.OPEN and self.reason is not None:
            raise ValueError("an OPEN fill has no close reason")
        if self.kind is FillKind.CLOSE and self.reason is None:
            raise ValueError(
                "a CLOSE fill needs a reason (ROUTINE or MONETIZATION) — "
                "it decides whether the proceeds count against gross carry",
            )
        if self.kind is FillKind.SETTLE and self.reason not in {
            None,
            CloseReason.ROUTINE,
        }:
            raise ValueError("a SETTLE fill is always ROUTINE")
        if self.supersedes == self.event_id:
            raise ValueError("a fill cannot supersede itself")

    @property
    def effective_reason(self) -> CloseReason | None:
        """The close reason, with ``SETTLE`` resolved to ``ROUTINE``."""
        if self.kind is FillKind.SETTLE:
            return CloseReason.ROUTINE
        return self.reason

    def cash_flow(self) -> float | None:
        """Return cash into the account: ``+`` received, ``-`` paid.

        The one place cash is derived from a fill:
        ``-quantity * price_per_share * contract_size - fees``. Buying
        pays (negative), selling and settling a long leg receive
        (positive), and fees always reduce cash.

        Returns:
            The signed cash flow, or ``None`` when either the price or
            the fees were not captured. Never a guess.

        """
        if self.price_per_share is None or self.fees is None:
            return None
        gross = -self.quantity * self.price_per_share * self.terms.contract_size
        return gross - self.fees

    def to_json(self) -> dict[str, Any]:
        """Serialize to a JSON-safe record."""
        return {
            "schema": SCHEMA_VERSION,
            "record": "fill",
            "event_id": self.event_id,
            "kind": self.kind.value,
            "trade_date": self.trade_date.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "written_by": self.written_by,
            "position_id": self.position_id,
            "terms": self.terms.to_json(),
            "quantity": self.quantity,
            "price_per_share": self.price_per_share,
            "fees": self.fees,
            "reason": self.reason.value if self.reason else None,
            "roll_id": self.roll_id,
            "supersedes": self.supersedes,
            "note": self.note,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Fill:
        """Deserialize from :meth:`to_json`'s output."""
        reason = data.get("reason")
        return cls(
            event_id=data["event_id"],
            kind=FillKind(data["kind"]),
            trade_date=date.fromisoformat(data["trade_date"]),
            recorded_at=datetime.fromisoformat(data["recorded_at"]),
            written_by=data["written_by"],
            position_id=data["position_id"],
            terms=ContractTerms.from_json(data["terms"]),
            quantity=int(data["quantity"]),
            price_per_share=_optional_float(data.get("price_per_share")),
            fees=_optional_float(data.get("fees")),
            reason=CloseReason(reason) if reason else None,
            roll_id=data.get("roll_id"),
            supersedes=data.get("supersedes"),
            note=data.get("note"),
        )


@dataclass(frozen=True)
class BookEdit:  # pylint: disable=too-many-instance-attributes  # before/after pairs
    """A change to the book that moved no cash.

    Attributes:
        event_id: Unique id.
        kind: ``AMEND``, ``DELETE`` or ``REPLACE``.
        effective_date: The program trading date it was made on.
        recorded_at: When it was made (timezone-aware).
        written_by: The writing process's label (#355).
        position_id: The lot edited; ``None`` for a whole-book ``REPLACE``.
        before: The lot's terms before the edit, if it existed.
        after: The lot's terms after the edit, if it still exists.
        quantity_before: The lot's quantity before, if it existed.
        quantity_after: The lot's quantity after, if it still exists.
        detail: An operator-readable sentence, quoted in the caveat of
            every period this edit falls in.

    """

    event_id: str
    kind: EditKind
    effective_date: date
    recorded_at: datetime
    written_by: str
    position_id: str | None
    before: ContractTerms | None
    after: ContractTerms | None
    quantity_before: int | None
    quantity_after: int | None
    detail: str

    def __post_init__(self) -> None:
        """Reject an edit that names no lot unless it replaces the book."""
        _require_aware(self.recorded_at, "recorded_at")
        if self.position_id is None and self.kind is not EditKind.REPLACE:
            raise ValueError(f"a {self.kind.value} edit must name its lot")

    def to_json(self) -> dict[str, Any]:
        """Serialize to a JSON-safe record."""
        return {
            "schema": SCHEMA_VERSION,
            "record": "edit",
            "event_id": self.event_id,
            "kind": self.kind.value,
            "effective_date": self.effective_date.isoformat(),
            "recorded_at": self.recorded_at.isoformat(),
            "written_by": self.written_by,
            "position_id": self.position_id,
            "before": self.before.to_json() if self.before else None,
            "after": self.after.to_json() if self.after else None,
            "quantity_before": self.quantity_before,
            "quantity_after": self.quantity_after,
            "detail": self.detail,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> BookEdit:
        """Deserialize from :meth:`to_json`'s output."""
        before = data.get("before")
        after = data.get("after")
        return cls(
            event_id=data["event_id"],
            kind=EditKind(data["kind"]),
            effective_date=date.fromisoformat(data["effective_date"]),
            recorded_at=datetime.fromisoformat(data["recorded_at"]),
            written_by=data["written_by"],
            position_id=data.get("position_id"),
            before=ContractTerms.from_json(before) if before else None,
            after=ContractTerms.from_json(after) if after else None,
            quantity_before=data.get("quantity_before"),
            quantity_after=data.get("quantity_after"),
            detail=data["detail"],
        )


@dataclass(frozen=True)
class LegMark:
    """One open lot's mark inside a :class:`BookMark`.

    Attributes:
        position_id: The lot.
        terms: Its contract.
        quantity: Signed contracts held at the mark.
        volatility: The volatility it was priced at.
        volatility_as_of: When a human last confirmed that volatility, or
            ``None`` if never (#367).
        price_per_share: The per-share mark.
        value: ``quantity * price_per_share * contract_size``, signed.
        expired_unsettled: The lot is at or past expiry and no settlement
            has been recorded, so it is still in the book. The model
            prices an expired option at zero, which is not its settlement
            value, so any period this mark bounds is not reconcilable
            until the ``SETTLE`` fill is entered.

    """

    position_id: str
    terms: ContractTerms
    quantity: int
    volatility: float
    volatility_as_of: datetime | None
    price_per_share: float
    value: float
    expired_unsettled: bool

    def to_json(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "position_id": self.position_id,
            "terms": self.terms.to_json(),
            "quantity": self.quantity,
            "volatility": self.volatility,
            "volatility_as_of": _optional_iso(self.volatility_as_of),
            "price_per_share": self.price_per_share,
            "value": self.value,
            "expired_unsettled": self.expired_unsettled,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LegMark:
        """Deserialize from :meth:`to_json`'s output."""
        return cls(
            position_id=data["position_id"],
            terms=ContractTerms.from_json(data["terms"]),
            quantity=int(data["quantity"]),
            volatility=float(data["volatility"]),
            volatility_as_of=_optional_datetime(data.get("volatility_as_of")),
            price_per_share=float(data["price_per_share"]),
            value=float(data["value"]),
            expired_unsettled=bool(data["expired_unsettled"]),
        )


@dataclass(frozen=True)
class BookMark:  # pylint: disable=too-many-instance-attributes  # the mark's inputs, stated
    """The whole hedge book, marked once on one program date.

    A boundary mark is computed once and reused: the mark that ends one
    period starts the next, so a discrepancy cannot fall between them
    (the handbook's warning on boundary marks).

    Attributes:
        mark_date: The program trading date the book was priced on. At
            most one mark per date.
        marked_at: When the mark was taken (timezone-aware).
        written_by: The writing process's label (#355).
        basis: How the legs were priced.
        spot: The spot the book was priced on.
        spot_as_of: When a human last confirmed that spot, or ``None`` if
            never. A mark on a stale spot is still a mark, but the reader
            is told.
        risk_free_rate: The rate the book was priced on.
        dividend_yield: The dividend yield the book was priced on.
        underlying_quantity: Shares of the hedged underlying. With
            ``spot``, this gives the portfolio value that realized carry
            is expressed against, and the before-hedge return.
        legs: Every lot in the book at the mark.
        is_opening: The migration mark that starts the history. There is
            no data before it, and the book held then enters at its
            value here.

    """

    mark_date: date
    marked_at: datetime
    written_by: str
    basis: MarkBasis
    spot: float
    spot_as_of: datetime | None
    risk_free_rate: float
    dividend_yield: float
    underlying_quantity: float
    legs: tuple[LegMark, ...]
    is_opening: bool = False

    def __post_init__(self) -> None:
        """Reject a mark with no time or no price to have been taken at."""
        _require_aware(self.marked_at, "marked_at")
        if self.spot <= 0:
            raise ValueError(f"spot must be > 0, got {self.spot}")

    @property
    def hedge_value(self) -> float:
        """V: the signed sum of every lot's mark."""
        return sum(leg.value for leg in self.legs)

    @property
    def portfolio_value(self) -> float:
        """The hedged portfolio's value: ``underlying_quantity * spot``."""
        return self.underlying_quantity * self.spot

    @property
    def expired_unsettled_legs(self) -> tuple[LegMark, ...]:
        """Lots marked past expiry with no settlement recorded."""
        return tuple(leg for leg in self.legs if leg.expired_unsettled)

    def to_json(self) -> dict[str, Any]:
        """Serialize to a JSON-safe record."""
        return {
            "schema": SCHEMA_VERSION,
            "record": "mark",
            "mark_date": self.mark_date.isoformat(),
            "marked_at": self.marked_at.isoformat(),
            "written_by": self.written_by,
            "basis": self.basis.value,
            "spot": self.spot,
            "spot_as_of": _optional_iso(self.spot_as_of),
            "risk_free_rate": self.risk_free_rate,
            "dividend_yield": self.dividend_yield,
            "underlying_quantity": self.underlying_quantity,
            "legs": [leg.to_json() for leg in self.legs],
            "is_opening": self.is_opening,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> BookMark:
        """Deserialize from :meth:`to_json`'s output."""
        return cls(
            mark_date=date.fromisoformat(data["mark_date"]),
            marked_at=datetime.fromisoformat(data["marked_at"]),
            written_by=data["written_by"],
            basis=MarkBasis(data["basis"]),
            spot=float(data["spot"]),
            spot_as_of=_optional_datetime(data.get("spot_as_of")),
            risk_free_rate=float(data["risk_free_rate"]),
            dividend_yield=float(data["dividend_yield"]),
            underlying_quantity=float(data["underlying_quantity"]),
            legs=tuple(LegMark.from_json(leg) for leg in data["legs"]),
            is_opening=bool(data.get("is_opening")),
        )


HistoryRecord = Fill | BookEdit | BookMark

_DECODERS: Final[dict[str, Callable[[dict[str, Any]], HistoryRecord]]] = {
    "fill": Fill.from_json,
    "edit": BookEdit.from_json,
    "mark": BookMark.from_json,
}


def record_from_json(data: object) -> HistoryRecord:
    """Decode one stored record, refusing anything it was not written as.

    Raises:
        HistorySchemaError: If *data* is not a mapping, carries a schema
            version other than :data:`SCHEMA_VERSION`, names an unknown
            record type, or is missing or mistyping a field.

    """
    if not isinstance(data, dict):
        raise HistorySchemaError(
            f"history record must be a mapping, got {type(data).__name__}",
        )
    version = data.get("schema")
    if version != SCHEMA_VERSION:
        raise HistorySchemaError(
            f"history record schema {version!r} is not {SCHEMA_VERSION} — "
            "written by a different version of deltadewa; refusing to guess",
        )
    decoder = _DECODERS.get(str(data.get("record")))
    if decoder is None:
        raise HistorySchemaError(
            f"unknown history record type {data.get('record')!r}",
        )
    try:
        return decoder(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise HistorySchemaError(f"malformed history record: {exc}") from exc


@dataclass(frozen=True)
class PositionHistory:
    """Everything recorded, with corrections resolved.

    Attributes:
        recorded_fills: Every fill as stored, superseded ones included,
            in record order. Kept for audit; :attr:`fills` is what any
            calculation reads.
        edits: Every book edit, in record order.
        marks: Every mark, sorted by ``mark_date``.

    Raises:
        ValueError: If two marks share a date, a mark other than the
            earliest is an opening mark, or a fill supersedes an event
            that was never recorded.

    """

    recorded_fills: tuple[Fill, ...] = ()
    edits: tuple[BookEdit, ...] = ()
    marks: tuple[BookMark, ...] = ()
    _active_fills: tuple[Fill, ...] = field(
        default=(),
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Order the marks, check them, and resolve supersession."""
        ordered = tuple(sorted(self.marks, key=lambda m: m.mark_date))
        object.__setattr__(self, "marks", ordered)
        dates = [m.mark_date for m in ordered]
        if len(dates) != len(set(dates)):
            raise ValueError("two marks share a mark_date")
        if any(m.is_opening for m in ordered[1:]):
            raise ValueError("only the earliest mark can be the opening mark")
        object.__setattr__(
            self,
            "_active_fills",
            _resolve_supersession(self.recorded_fills),
        )

    @property
    def fills(self) -> tuple[Fill, ...]:
        """Fills in force: each superseded record replaced by its correction."""
        return self._active_fills

    @property
    def history_start(self) -> date | None:
        """The first mark's date: there is no data before it."""
        return self.marks[0].mark_date if self.marks else None

    @property
    def opening_mark(self) -> BookMark | None:
        """The migration mark, if the history was started with one."""
        if self.marks and self.marks[0].is_opening:
            return self.marks[0]
        return None

    def fills_between(self, start: date, end: date) -> tuple[Fill, ...]:
        """Return the fills with ``start < trade_date <= end``.

        A mark on date ``D`` reflects every trade dated ``D`` or earlier,
        so a period ``[m0, m1]`` owns the fills after ``m0`` up to and
        including ``m1``.
        """
        return tuple(f for f in self.fills if start < f.trade_date <= end)

    def edits_between(self, start: date, end: date) -> tuple[BookEdit, ...]:
        """Return the book edits with ``start < effective_date <= end``."""
        return tuple(e for e in self.edits if start < e.effective_date <= end)

    def records(self) -> Iterable[HistoryRecord]:
        """Every stored record, fills and edits first, then marks."""
        yield from self.recorded_fills
        yield from self.edits
        yield from self.marks


def _resolve_supersession(fills: tuple[Fill, ...]) -> tuple[Fill, ...]:
    """Replace each corrected fill with its correction.

    A correction fixes what was *recorded* about a trade: its price, fees,
    reason, date or note. It cannot change which lot moved, in which
    direction, or by how much, because that would change the book itself,
    and a book change is a :class:`BookEdit` (``AMEND``), journaled as
    one. Keeping the two apart is what lets the lot reconciliation in
    :mod:`deltadewa.analysis.realized_carry` stay exact.
    """
    by_id = {f.event_id: f for f in fills}
    superseded: set[str] = set()
    for fill in fills:
        if fill.supersedes is None:
            continue
        original = by_id.get(fill.supersedes)
        if original is None:
            raise ValueError(
                f"fill {fill.event_id} supersedes {fill.supersedes}, "
                "which was never recorded",
            )
        if (
            fill.kind,
            fill.position_id,
            fill.terms,
            fill.quantity,
        ) != (
            original.kind,
            original.position_id,
            original.terms,
            original.quantity,
        ):
            raise ValueError(
                f"fill {fill.event_id} corrects {original.event_id} but "
                "changes its kind, lot, contract or quantity — a "
                "correction may only fix price, fees, reason, date or "
                "note; record a book AMEND for anything else",
            )
        if fill.supersedes in superseded:
            raise ValueError(
                f"fill {fill.supersedes} is corrected more than once — "
                "correct the latest correction instead",
            )
        superseded.add(fill.supersedes)
    return tuple(f for f in fills if f.event_id not in superseded)


def mark_book(
    portfolio: OptionPortfolio,
    *,
    marked_at: datetime,
    written_by: str,
    basis: MarkBasis = MarkBasis.MODEL,
    is_opening: bool = False,
) -> BookMark:
    """Mark the whole book on its own valuation date.

    The mark's date is the portfolio's ``valuation_date``, not an
    argument, so a mark cannot carry a different day from the one it was
    priced on. Each lot is valued through ``OptionPosition.position_value``,
    the same read every other "a leg's value today" surface uses (pinned
    by ``tests/test_portfolio/test_leg_marks_agree.py``), so the history
    adds no new pricing route.

    Args:
        portfolio: The live book, already priced at its valuation date.
        marked_at: When the mark is being taken.
        written_by: The writing process's label (#355).
        basis: The pricing basis. Only ``MODEL`` exists today.
        is_opening: Whether this is the migration mark that starts the
            history.

    Returns:
        The mark. Nothing is written.

    """
    # Local import: deltadewa.analysis imports OptionPortfolio, so a
    # module-level import here would be circular (see core.add_position).
    # pylint: disable-next=import-outside-toplevel
    from deltadewa.analysis.crash_repricing import is_expired

    valuation_date = portfolio.valuation_date
    legs = tuple(
        LegMark(
            position_id=pos.position_id,
            terms=ContractTerms.from_position(pos),
            quantity=int(pos.quantity),
            volatility=float(pos.option.volatility),
            volatility_as_of=pos.volatility_as_of,
            price_per_share=float(pos.option.price()),
            value=float(pos.position_value()),
            expired_unsettled=is_expired(pos, valuation_date=valuation_date),
        )
        for pos in portfolio.positions
    )
    return BookMark(
        mark_date=valuation_date.date(),
        marked_at=marked_at,
        written_by=written_by,
        basis=basis,
        spot=float(portfolio.spot_price),
        spot_as_of=portfolio.stamps.spot_as_of,
        risk_free_rate=float(portfolio.risk_free_rate),
        dividend_yield=float(portfolio.dividend_yield),
        underlying_quantity=float(portfolio.underlying_quantity),
        legs=legs,
        is_opening=is_opening,
    )


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _optional_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None
