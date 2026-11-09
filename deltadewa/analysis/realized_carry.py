"""Realized carry: what the hedge actually cost over a past period (#313).

The handbook's `Realized Carry Methodology
<https://qwertytam.github.io/deltadewa-handbook/part-7/realized-carry-methodology/>`_,
computed from :mod:`deltadewa.portfolio.history`::

    Gross $ = V0 + P - R_routine - V1
    Net $   = Gross $ - R_monetization          (positive = a cost)
    annual  = $ / portfolio value x 365 / days in period

A period is the span between two **marks**, never between two arbitrary
dates. The mark that ends one period starts the next and is reused rather
than recomputed, so two adjacent periods sum exactly to the period that
spans them. A fill belongs to the period whose marks bracket its
``trade_date`` as ``start < trade_date <= end``.

This is not theta carry
    ``WeeklySnapshot.cumulative_carry_cost`` integrates the current
    book's theta over time. That is the handbook's *forward* measure, and
    it will not agree with this one: the book changes, the model is not
    the market, and theta never sees a fee. See the handbook's Ratio
    Disambiguation page. Nothing here reads or back-fills from it.

Breaks, not guesses
    Some periods cannot be reconciled against a statement. The book may
    have been edited without a fill, a fee or price may not have been
    captured, a lot may have expired without its settlement being
    recorded, or a fill may have been recorded after the mark that
    should have included it. The figure is still computed from what *was*
    recorded, and each cause is listed in :attr:`RealizedCarry.breaks` by
    name. A period with any break is :attr:`RealizedCarry.reconcilable`
    ``False``. The figure is never silently patched, and an uncaptured
    fee is never treated as zero.

UI-free: renderers decide how to show a break, this module only names it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING, Final

from deltadewa.portfolio.history import (
    BookMark,
    CloseReason,
    EditKind,
    Fill,
    FillKind,
    MarkBasis,
    PositionHistory,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import date, datetime

    from deltadewa.portfolio.history import BookEdit
    from deltadewa.portfolio.position import OptionPosition

_DAYS_PER_YEAR: Final = 365


@dataclass(frozen=True)
class RealizedCarry:  # pylint: disable=too-many-instance-attributes  # the identity's terms, each shown
    """One period's realized carry, with every term of the identity.

    Attributes:
        start: The opening mark's date.
        end: The closing mark's date.
        days: Calendar days between them.
        basis: The marks' shared pricing basis.
        v0: Hedge book value at ``start``.
        v1: Hedge book value at ``end``.
        paid: P. Net cash paid for lots opened in the period, fees
            included (negative if the opens were net credits, e.g. sold
            legs).
        received_routine: Routine R. Cash from routine closes and every
            settlement, net of fees.
        received_monetization: Monetization R. Cash from closes recorded
            as ``MONETIZATION``, net of fees.
        gross: ``v0 + paid - received_routine - v1``. The insurance
            premium, which is the figure the carry budget is measured
            against. Positive is a cost.
        net: ``gross - received_monetization``: the economic outcome.
        portfolio_value: The hedged portfolio's value at ``start``.
        gross_annual_pct: ``gross`` as an annualised percent of
            ``portfolio_value``; ``None`` when that is not positive.
        net_annual_pct: The same for ``net``.
        start_spot_age_days: Days from the start mark's spot confirmation
            to the mark; ``None`` if the spot was never confirmed.
        end_spot_age_days: The same for the end mark.
        breaks: One operator-readable sentence per reason this period
            cannot be reconciled against a statement.

    """

    start: date
    end: date
    days: int
    basis: MarkBasis
    v0: float
    v1: float
    paid: float
    received_routine: float
    received_monetization: float
    gross: float
    net: float
    portfolio_value: float
    gross_annual_pct: float | None
    net_annual_pct: float | None
    start_spot_age_days: int | None
    end_spot_age_days: int | None
    breaks: tuple[str, ...]

    @property
    def reconcilable(self) -> bool:
        """Whether nothing recorded stops this tying to a statement."""
        return not self.breaks


@dataclass(frozen=True)
class HedgedReturn:
    """The hedged portfolio's return over one period, hedge and no hedge.

    Attributes:
        before_hedge_pct: The underlying's price return,
            ``spot1 / spot0 - 1``, in percent. Dividends are excluded:
            the program records a dividend *yield* assumption, not
            dividends received, and a modelled figure is not a
            measurement.
        after_hedge_pct: ``before_hedge_pct`` less **net** realized carry
            as a percent of the starting portfolio value. Net, because
            monetization proceeds are cash the hedged portfolio actually
            received, so they belong in its return.
        unavailable_reason: Why the two figures are ``None``, if they are.

    """

    before_hedge_pct: float | None
    after_hedge_pct: float | None
    unavailable_reason: str | None


def _fill_cash_parts(fill: Fill) -> tuple[float, list[str]]:
    """Return the fill's known cash and a break for each unknown part."""
    missing: list[str] = []
    cash = 0.0
    if fill.price_per_share is None:
        missing.append("price")
    else:
        cash -= fill.quantity * fill.price_per_share * fill.terms.contract_size
    if fill.fees is None:
        missing.append("fees")
    else:
        cash -= fill.fees
    if not missing:
        return cash, []
    return cash, [
        (
            f"{fill.kind.value} {fill.terms.describe()} on "
            f"{fill.trade_date}: {' and '.join(missing)} not captured"
        ),
    ]


def _late_fill_breaks(
    fills: Iterable[Fill],
    start: BookMark,
    end: BookMark,
) -> list[str]:
    """Name fills recorded too late for a mark this period depends on.

    Two cases distort this period, and only these two:

    * the fill's cash is in this period (``start < trade_date <= end``) but
      it was recorded after the end mark, so V1 lacks the lot;
    * the fill's cash is in an earlier period (``trade_date <= start``) but
      it was recorded between the two marks, so the lot is in V1 and not
      in V0, with no cash here to explain it.

    A fill recorded after *both* marks with its cash in an earlier period
    is that period's break, not this one's.
    """
    breaks: list[str] = []
    for fill in fills:
        cash_here_lot_missing = (
            start.mark_date < fill.trade_date <= end.mark_date
            and fill.recorded_at > end.marked_at
        )
        lot_here_cash_earlier = (
            fill.trade_date <= start.mark_date
            and start.marked_at < fill.recorded_at <= end.marked_at
        )
        if cash_here_lot_missing or lot_here_cash_earlier:
            missed = end if cash_here_lot_missing else start
            breaks.append(
                f"{fill.kind.value} {fill.terms.describe()} dated "
                f"{fill.trade_date} was recorded after the "
                f"{missed.mark_date} mark was taken, so that mark does "
                "not include it",
            )
    return breaks


def _edit_breaks(edits: Iterable[BookEdit]) -> list[str]:
    return [
        f"book edited without a fill on {edit.effective_date} "
        f"({edit.kind.value}): {edit.detail}"
        for edit in edits
    ]


def _expired_breaks(marks: Iterable[BookMark]) -> list[str]:
    return [
        f"{leg.terms.describe()} was past expiry at the {mark.mark_date} "
        "mark with no settlement recorded — the model marks it at zero, "
        "not its settlement value"
        for mark in marks
        for leg in mark.expired_unsettled_legs
    ]


def _spot_age_days(mark: BookMark) -> int | None:
    if mark.spot_as_of is None:
        return None
    return (mark.mark_date - mark.spot_as_of.date()).days


def _annualised_pct(
    amount: float,
    portfolio_value: float,
    days: int,
) -> float | None:
    if portfolio_value <= 0:
        return None
    return amount / portfolio_value * _DAYS_PER_YEAR / days * 100.0


def realized_carry(
    history: PositionHistory,
    *,
    start: BookMark,
    end: BookMark,
) -> RealizedCarry:
    """Compute the identity over the period ``[start, end]``.

    Args:
        history: Everything recorded.
        start: The mark opening the period.
        end: The mark closing it. Must be later than *start*.

    Returns:
        Every term of the identity, the gross and net figures, and the
        reasons (if any) the period cannot be reconciled.

    Raises:
        ValueError: If *end* is not after *start*, or the two marks were
            priced on different bases. A cross-basis figure would be a
            number with no meaning, so none is produced.

    """
    if end.mark_date <= start.mark_date:
        raise ValueError(
            f"period end {end.mark_date} is not after start {start.mark_date}",
        )
    if start.basis is not end.basis:
        raise ValueError(
            f"the {start.mark_date} mark is {start.basis.value} and the "
            f"{end.mark_date} mark is {end.basis.value}; realized carry "
            "needs one basis at both ends",
        )

    fills = history.fills_between(start.mark_date, end.mark_date)
    paid = 0.0
    received_routine = 0.0
    received_monetization = 0.0
    breaks: list[str] = []
    for fill in fills:
        cash, missing = _fill_cash_parts(fill)
        breaks.extend(missing)
        if fill.kind is FillKind.OPEN:
            paid -= cash
        elif fill.effective_reason is CloseReason.MONETIZATION:
            received_monetization += cash
        else:
            received_routine += cash

    breaks.extend(
        _edit_breaks(history.edits_between(start.mark_date, end.mark_date)),
    )
    breaks.extend(_expired_breaks((start, end)))
    breaks.extend(_late_fill_breaks(history.fills, start, end))

    v0 = start.hedge_value
    v1 = end.hedge_value
    gross = v0 + paid - received_routine - v1
    net = gross - received_monetization
    days = (end.mark_date - start.mark_date).days
    portfolio_value = start.portfolio_value
    return RealizedCarry(
        start=start.mark_date,
        end=end.mark_date,
        days=days,
        basis=start.basis,
        v0=v0,
        v1=v1,
        paid=paid,
        received_routine=received_routine,
        received_monetization=received_monetization,
        gross=gross,
        net=net,
        portfolio_value=portfolio_value,
        gross_annual_pct=_annualised_pct(gross, portfolio_value, days),
        net_annual_pct=_annualised_pct(net, portfolio_value, days),
        start_spot_age_days=_spot_age_days(start),
        end_spot_age_days=_spot_age_days(end),
        breaks=tuple(breaks),
    )


def since_inception(history: PositionHistory) -> RealizedCarry | None:
    """Realized carry from the first mark to the latest.

    Returns:
        ``None`` until there are two marks. One mark is a starting point,
        not a measurement, and the caller must say so rather than show a
        zero.

    """
    if len(history.marks) < 2:  # a period needs two ends
        return None
    return realized_carry(
        history,
        start=history.marks[0],
        end=history.marks[-1],
    )


def latest_period(history: PositionHistory) -> RealizedCarry | None:
    """Realized carry between the two most recent marks, or ``None``."""
    if len(history.marks) < 2:  # a period needs two ends
        return None
    return realized_carry(
        history,
        start=history.marks[-2],
        end=history.marks[-1],
    )


def hedged_return(
    carry: RealizedCarry,
    *,
    start: BookMark,
    end: BookMark,
) -> HedgedReturn:
    """Before- and after-hedge return over the period *carry* covers.

    Args:
        carry: The period's realized carry.
        start: The mark *carry* starts at.
        end: The mark *carry* ends at.

    Returns:
        Both figures, or neither with the reason. They are ``None`` when
        the underlying quantity changed between the marks, because a
        price return no longer describes the portfolio's return without
        the flows, which are not recorded. They are also ``None`` when the
        starting portfolio value is not positive.

    Raises:
        ValueError: If *start*/*end* are not the marks *carry* was
            computed between.

    """
    if (start.mark_date, end.mark_date) != (carry.start, carry.end):
        raise ValueError("hedged_return needs the marks carry was computed on")
    if start.underlying_quantity != end.underlying_quantity:
        return HedgedReturn(
            before_hedge_pct=None,
            after_hedge_pct=None,
            unavailable_reason=(
                f"the underlying holding changed between {start.mark_date} "
                f"({start.underlying_quantity:,.0f}) and {end.mark_date} "
                f"({end.underlying_quantity:,.0f}); its flows are not "
                "recorded, so a return over this period would be invented"
            ),
        )
    if start.portfolio_value <= 0:
        return HedgedReturn(
            before_hedge_pct=None,
            after_hedge_pct=None,
            unavailable_reason="no underlying holding is recorded",
        )
    before = (end.spot / start.spot - 1.0) * 100.0
    after = before - carry.net / start.portfolio_value * 100.0
    return HedgedReturn(
        before_hedge_pct=before,
        after_hedge_pct=after,
        unavailable_reason=None,
    )


def _apply(
    quantities: dict[str, int],
    event: Fill | BookEdit,
) -> None:
    if isinstance(event, Fill):
        quantities[event.position_id] += event.quantity
    elif event.kind is EditKind.DELETE and event.position_id is not None:
        quantities[event.position_id] = 0
    elif (
        event.kind is EditKind.AMEND
        and event.position_id is not None
        and event.quantity_after is not None
    ):
        quantities[event.position_id] = event.quantity_after


def _compare(
    expected: dict[str, int],
    actual: dict[str, int],
    *,
    label: str,
) -> list[str]:
    findings: list[str] = []
    for lot in sorted(set(expected) | set(actual)):
        want = expected.get(lot, 0)
        got = actual.get(lot, 0)
        if want != got:
            findings.append(
                f"{label}: lot {lot} — the history implies {want} "
                f"contracts, {got} are held",
            )
    return findings


def _segment_findings(
    baseline: BookMark,
    events: Sequence[Fill | BookEdit],
    actual: dict[str, int],
    *,
    label: str,
) -> list[str]:
    replaced = [
        e
        for e in events
        if not isinstance(e, Fill) and e.kind is EditKind.REPLACE
    ]
    if replaced:
        return [
            (
                f"{label}: the book was replaced by an import on "
                f"{replaced[0].effective_date}, so its lots cannot be "
                "checked against the history until the next mark"
            ),
        ]
    expected: dict[str, int] = defaultdict(int)
    for leg in baseline.legs:
        expected[leg.position_id] = leg.quantity
    for event in events:
        _apply(expected, event)
    return _compare(
        {k: v for k, v in expected.items() if v},
        actual,
        label=label,
    )


def _events_after(
    history: PositionHistory,
    after: datetime,
    until: datetime | None,
) -> list[Fill | BookEdit]:
    # The originals, not the corrections: a correction cannot change a
    # quantity (see _resolve_supersession), and it was not a book change.
    originals: list[Fill | BookEdit] = [
        f for f in history.recorded_fills if f.supersedes is None
    ]
    events = [
        e
        for e in [*originals, *history.edits]
        if e.recorded_at > after and (until is None or e.recorded_at <= until)
    ]
    return sorted(events, key=lambda e: e.recorded_at)


def reconcile_book(
    history: PositionHistory,
    positions: Sequence[OptionPosition],
) -> tuple[str, ...]:
    """Check that the history explains every lot the book holds.

    Each mark is a snapshot of the book as it stood when the mark was
    taken. Starting from each mark and applying every fill and edit
    recorded after it must reproduce the next mark's lots, and the last
    mark plus everything since must reproduce the live book. Any
    difference means a change reached the book without reaching the
    history, or the reverse. Nothing is replayed into the book: this
    only reports.

    Args:
        history: Everything recorded.
        positions: The live book's lots.

    Returns:
        One finding per lot that disagrees, or per segment that cannot be
        checked. Empty when the history explains the book, or when there
        is no mark to start from.

    """
    findings: list[str] = []
    marks = history.marks
    for prior, following in pairwise(marks):
        findings.extend(
            _segment_findings(
                prior,
                _events_after(history, prior.marked_at, following.marked_at),
                {leg.position_id: leg.quantity for leg in following.legs},
                label=f"{following.mark_date} mark",
            ),
        )
    if marks:
        findings.extend(
            _segment_findings(
                marks[-1],
                _events_after(history, marks[-1].marked_at, None),
                {p.position_id: int(p.quantity) for p in positions},
                label="live book",
            ),
        )
    return tuple(findings)
