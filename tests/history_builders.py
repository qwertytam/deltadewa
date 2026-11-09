"""Builders for crafted position-history records (#313).

Every date here is a pinned absolute date, never derived from the wall
clock, so a realized-carry figure is exact and stays exact as the calendar
moves (see CLAUDE.md, "The program's day comes from deltadewa/clock.py").
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.history import (
    BookEdit,
    BookMark,
    CloseReason,
    ContractTerms,
    EditKind,
    Fill,
    FillKind,
    LegMark,
    MarkBasis,
    new_event_id,
)

SIZE = 100
EXPIRY = date(2027, 6, 18)


def terms(strike: float = 4200.0, expiry: date = EXPIRY) -> ContractTerms:
    """Return a European SPX put contract."""
    return ContractTerms(
        option_type=OptionType.PUT,
        strike=strike,
        expiry=expiry,
        contract_size=SIZE,
        exercise_style=ExerciseStyle.EUROPEAN,
    )


def at(day: date, hour: int = 12) -> datetime:
    """Return a UTC instant on *day*."""
    return datetime.combine(day, time(hour), tzinfo=UTC)


def leg(
    position_id: str,
    quantity: int,
    price: float,
    *,
    contract: ContractTerms | None = None,
    expired_unsettled: bool = False,
) -> LegMark:
    """Return one lot's mark."""
    contract = contract or terms()
    return LegMark(
        position_id=position_id,
        terms=contract,
        quantity=quantity,
        volatility=0.2,
        volatility_as_of=None,
        price_per_share=price,
        value=quantity * price * contract.contract_size,
        expired_unsettled=expired_unsettled,
    )


def mark(  # every argument is a mark field a test varies
    day: date,
    legs: tuple[LegMark, ...] = (),
    *,
    spot: float = 5000.0,
    underlying_quantity: float = 1000.0,
    marked_at: datetime | None = None,
    spot_as_of: datetime | None = None,
    is_opening: bool = False,
) -> BookMark:
    """Return a book mark. Taken at 22:00 UTC on *day* unless overridden."""
    return BookMark(
        mark_date=day,
        marked_at=marked_at or at(day, 22),
        written_by="test",
        basis=MarkBasis.MODEL,
        spot=spot,
        spot_as_of=spot_as_of,
        risk_free_rate=0.04,
        dividend_yield=0.015,
        underlying_quantity=underlying_quantity,
        legs=legs,
        is_opening=is_opening,
    )


def fill(  # every argument is a fill field a test varies
    kind: FillKind,
    position_id: str,
    quantity: int,
    price: float | None,
    *,
    day: date,
    fees: float | None = 0.0,
    reason: CloseReason | None = None,
    contract: ContractTerms | None = None,
    recorded_at: datetime | None = None,
    roll_id: str | None = None,
    supersedes: str | None = None,
    event_id: str | None = None,
) -> Fill:
    """Return a fill, recorded at noon UTC on its trade date by default."""
    return Fill(
        event_id=event_id or new_event_id(),
        kind=kind,
        trade_date=day,
        recorded_at=recorded_at or at(day),
        written_by="test",
        position_id=position_id,
        terms=contract or terms(),
        quantity=quantity,
        price_per_share=price,
        fees=fees,
        reason=reason,
        roll_id=roll_id,
        supersedes=supersedes,
    )


def edit(
    kind: EditKind,
    position_id: str | None,
    *,
    day: date,
    quantity_before: int | None = None,
    quantity_after: int | None = None,
    recorded_at: datetime | None = None,
) -> BookEdit:
    """Return a book edit."""
    return BookEdit(
        event_id=new_event_id(),
        kind=kind,
        effective_date=day,
        recorded_at=recorded_at or at(day),
        written_by="test",
        position_id=position_id,
        before=terms() if position_id else None,
        after=terms() if kind is EditKind.AMEND else None,
        quantity_before=quantity_before,
        quantity_after=quantity_after,
        detail=f"{kind.value} in a test",
    )
