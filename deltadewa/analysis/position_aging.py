"""Per-leg expiry bucketing and expiration calendar, driven by ips.yaml.

Answers "when does this book start rolling off, and how much at a time" --
the question ``/monitor``'s raw per-leg DTE column and ``/design``'s
book-wide hedge-trigger grade both leave open.

Every bucket boundary is an existing :class:`~deltadewa.ips_config.IpsTriggers`
key. No new policy surface was added for this module, and no boundary is a
literal here: see :func:`expiry_boundaries`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from deltadewa import constants as const
from deltadewa.clock import days_between

if TYPE_CHECKING:
    from datetime import datetime as dt

    from deltadewa.ips_config import IpsConfig, IpsTriggers
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition


class ExpiryBucketLabel(StrEnum):
    """Expiry urgency grades, in increasing order of time remaining.

    The labels deliberately carry **no day counts**. The boundaries are
    policy (:class:`ExpiryBoundaries`, read from ``ips.yaml``), so baking
    them into the label -- as the retired Jupyter widget's
    ``"URGENT (<7d)"`` did -- makes the label lie the moment the IPS is
    edited. Callers render the window from :class:`ExpiryBoundaries`.

    ``EXPIRED`` (#365) is not one of those policy-boundary grades -- it is
    the same ``maturity.date() <= valuation_date.date()`` boundary
    :func:`~deltadewa.analysis.crash_repricing.is_expired` uses, not an IPS
    trigger day count. A leg lands here only via a restore path (a real
    historical or autosaved book), since ``OptionPortfolio.add_position``
    refuses an expired maturity by default.
    """

    EXPIRED = "EXPIRED"
    URGENT = "URGENT"
    SOON = "SOON"
    ROLL_DUE = "ROLL DUE"
    ROLL_REVIEW = "ROLL REVIEW"
    LONG_TERM = "LONG-TERM"


# Chronological order, shortest runway first -- EXPIRED sorts before URGENT
# since it is more "gone" than "urgent" (#365). A plain `groupby` would sort
# these alphabetically ("EXPIRED" < "LONG-TERM" < "ROLL DUE" < "SOON" <
# "URGENT"), which scrambles the urgency ordering -- this is the canonical
# order the aging panel reads against, the same convention
# `maturity._BUCKET_ORDER` uses.
BUCKET_ORDER: Final[tuple[ExpiryBucketLabel, ...]] = (
    ExpiryBucketLabel.EXPIRED,
    ExpiryBucketLabel.URGENT,
    ExpiryBucketLabel.SOON,
    ExpiryBucketLabel.ROLL_DUE,
    ExpiryBucketLabel.ROLL_REVIEW,
    ExpiryBucketLabel.LONG_TERM,
)


@dataclass(frozen=True)
class ExpiryBoundaries:
    """The four IPS-derived day boundaries separating the five buckets.

    Attributes:
        urgent_days: ``triggers.expiry_urgent_days``. Below this, a leg is
            URGENT.
        soon_days: ``triggers.expiry_soon_days``. Below this, SOON.
        roll_due_days: The program's roll window in days --
            ``triggers.roll_at_months_remaining`` converted at
            ``const.CALENDAR_DAYS_PER_MONTH``. At or below this, ROLL DUE.
            This is the handbook's own roll trigger ("maturity < 9 months
            remaining", `Part VII Rule 1 — Time-Based Roll
            <https://qwertytam.github.io/deltadewa-handbook/0.1/part-7/rolling-rules/#rule-1-time-based-roll>`_).
            Pinned to handbook version 0.1: the quoted figure and its
            *remaining*-maturity referent are the handbook's, so the citation
            has to keep resolving to the wording quoted here. Drop the
            ``/0.1/`` segment for the current rule.
        roll_review_days: ``roll_due_days * triggers.roll_review_buffer``.
            At or below this, ROLL REVIEW; beyond it, LONG-TERM.

    """

    urgent_days: int
    soon_days: int
    roll_due_days: int
    roll_review_days: int


@dataclass(frozen=True)
class AgedPosition:
    """One leg, with its runway and the bucket that runway falls in."""

    position: OptionPosition
    days_to_expiry: int
    bucket: ExpiryBucketLabel


@dataclass(frozen=True)
class SignedTotals:
    """The long and short sides of one aggregate, kept apart (#334).

    A net is the right headline for a roll plan -- it is the mark you'd
    realise unwinding the whole group -- but a net of zero is
    indistinguishable from an empty group unless both sides are carried
    alongside it. Grouping different strikes under one maturity date is
    legitimate (that is the calendar's whole axis); silently cancelling
    opposing legs to nothing is not.

    Sign convention, verified against
    :class:`~deltadewa.portfolio.position.OptionPosition`: a LONG put
    (positive ``quantity``) carries positive ``position_value`` and
    NEGATIVE ``position_theta`` (it decays); a SHORT put (negative
    ``quantity``) carries negative ``position_value`` and POSITIVE
    ``position_theta`` (the writer collects it). A leg is classified by
    the sign of its own ``quantity``, independent of strike.

    Attributes:
        long_contracts: Sum of positive-quantity legs (``>= 0``).
        short_contracts: Sum of negative-quantity legs (``<= 0``).
        long_value: Gross mark of the long side (``>= 0``).
        short_value: Gross mark of the short side (``<= 0``).
        long_theta: Gross daily theta of the long side (``<= 0``,
            long options decay).
        short_theta: Gross daily theta of the short side (``>= 0``,
            short options collect).

    """

    long_contracts: int
    short_contracts: int
    long_value: float
    short_value: float
    long_theta: float
    short_theta: float

    @property
    def net_contracts(self) -> int:
        """Signed contract count -- the size a roll would need to cover."""
        return self.long_contracts + self.short_contracts

    @property
    def net_value(self) -> float:
        """Net mark -- what unwinding the whole group realises today."""
        return self.long_value + self.short_value

    @property
    def net_theta(self) -> float:
        """Net daily theta -- the group's combined bleed."""
        return self.long_theta + self.short_theta

    @property
    def is_offsetting(self) -> bool:
        """``True`` when both a long and a short leg contribute.

        Distinguishes "the net is a cancellation" from "there is
        nothing here" -- a rendering surface should show the gross
        sides whenever this is ``True``, not only when the net happens
        to round to zero.
        """
        # Two independent comparisons on two different fields, not a
        # chainable range check -- pylint's R1716 misreads the shared
        # "0" as a middle term to merge, which would change the meaning.
        return (
            self.long_contracts > 0  # pylint: disable=chained-comparison
            and self.short_contracts < 0
        )


def _signed_totals(members: Sequence[AgedPosition]) -> SignedTotals:
    """Split *members* into long/short and sum each side separately."""
    longs = [m for m in members if m.position.quantity > 0]
    shorts = [m for m in members if m.position.quantity < 0]
    return SignedTotals(
        long_contracts=sum(m.position.quantity for m in longs),
        short_contracts=sum(m.position.quantity for m in shorts),
        long_value=sum(m.position.position_value() for m in longs),
        short_value=sum(m.position.position_value() for m in shorts),
        long_theta=sum(m.position.position_theta() for m in longs),
        short_theta=sum(m.position.position_theta() for m in shorts),
    )


@dataclass(frozen=True)
class ExpiryBucketTotal:
    """What sits in one bucket: how many legs, and how much.

    ``contracts``, ``position_value`` and ``position_theta`` are the
    signed net -- read them for "how much rolls off"; read ``totals``
    for the long/short breakdown a net of zero can hide (#334).
    """

    label: ExpiryBucketLabel
    legs: int
    totals: SignedTotals

    @property
    def contracts(self) -> int:
        """Signed contract count (negative for a net-short bucket)."""
        return self.totals.net_contracts

    @property
    def position_value(self) -> float:
        """Net mark of every leg in the bucket."""
        return self.totals.net_value

    @property
    def position_theta(self) -> float:
        """Net daily theta of every leg in the bucket."""
        return self.totals.net_theta


@dataclass(frozen=True)
class ExpiryCalendarEntry:
    """One dated roll-off event: every leg sharing a maturity date.

    The calendar is the "how much at a time" half of the panel -- one row
    per distinct expiry, so a book whose legs are stacked on a single date
    reads differently from one laddered across four. ``contracts``,
    ``position_value`` and ``position_theta`` are the signed net; see
    ``totals`` for the long/short breakdown a net of zero can hide when
    legs at different strikes share a maturity (#334).
    """

    maturity_date: dt
    days_to_expiry: int
    bucket: ExpiryBucketLabel
    legs: int
    totals: SignedTotals

    @property
    def contracts(self) -> int:
        """Signed contract count (negative for a net-short entry)."""
        return self.totals.net_contracts

    @property
    def position_value(self) -> float:
        """Net mark of every leg sharing this maturity date."""
        return self.totals.net_value

    @property
    def position_theta(self) -> float:
        """Net daily theta of every leg sharing this maturity date."""
        return self.totals.net_theta


@dataclass(frozen=True)
class PositionAging:
    """The full aging read: boundaries, bucket totals, legs, calendar.

    Attributes:
        boundaries: The resolved IPS boundaries, so a caller can print the
            window each bucket covers without re-deriving it.
        buckets: One total per canonical bucket, in :data:`BUCKET_ORDER`,
            **zero-filled** when empty -- a real absence of legs in that
            bucket, not missing data (matches
            :class:`~deltadewa.analysis.maturity.MaturityVegaExposure`).
        positions: Every leg, ascending by days to expiry.
        calendar: One entry per distinct maturity date, ascending.

    """

    boundaries: ExpiryBoundaries
    buckets: tuple[ExpiryBucketTotal, ...]
    positions: tuple[AgedPosition, ...]
    calendar: tuple[ExpiryCalendarEntry, ...]


def expiry_boundaries(triggers: IpsTriggers) -> ExpiryBoundaries:
    """Derive the five buckets' boundaries from existing IPS trigger keys.

    All four boundaries come from keys ``IpsTriggers`` already owns --
    ``expiry_urgent_days``, ``expiry_soon_days``,
    ``roll_at_months_remaining`` and ``roll_review_buffer``. The upper two
    are exactly the window
    :func:`~deltadewa.analysis.roll_status.evaluate_roll_status` grades its
    time trigger against, so the aging panel and the roll table cannot
    disagree about where a leg sits.

    ``IpsTriggers`` validates ``expiry_urgent_days < expiry_soon_days`` but
    nothing constrains ``expiry_soon_days`` against the roll window: a
    program with a short ``roll_at_months_remaining`` is a legal IPS. The upper
    boundaries are therefore clamped upward to keep the ladder monotonic
    (a bucket may collapse to empty), rather than raising -- a display
    panel must not refuse to render a valid config.

    Args:
        triggers: The IPS ``triggers:`` section.

    Returns:
        The four day boundaries, monotonically non-decreasing.

    """
    urgent_days = triggers.expiry_urgent_days
    soon_days = triggers.expiry_soon_days
    roll_due_days = max(
        round(
            triggers.roll_at_months_remaining * const.CALENDAR_DAYS_PER_MONTH
        ),
        soon_days,
    )
    roll_review_days = max(
        round(roll_due_days * triggers.roll_review_buffer),
        roll_due_days,
    )
    return ExpiryBoundaries(
        urgent_days=urgent_days,
        soon_days=soon_days,
        roll_due_days=roll_due_days,
        roll_review_days=roll_review_days,
    )


def classify_expiry_bucket(
    days_to_expiry: int,
    boundaries: ExpiryBoundaries,
) -> ExpiryBucketLabel:
    """Grade one leg's remaining runway against *boundaries*.

    The mixed ``<`` / ``<=`` comparisons are deliberate: each boundary keeps
    the comparison its owning consumer already uses --
    :mod:`~deltadewa.analysis.hedge_triggers` counts urgent legs with ``<``,
    and :func:`~deltadewa.analysis.roll_status._time_trigger_verdict` fires
    the roll window with ``<=``. Normalising them would put a leg in
    ROLL DUE here while the roll table still said HOLD.

    ``days_to_expiry <= 0`` grades ``EXPIRED`` (#365) ahead of every IPS
    boundary check -- this is
    :func:`~deltadewa.analysis.crash_repricing.is_expired`'s own boundary
    (``days_between`` returns ``0`` on the expiry day itself, matching
    ``maturity.date() <= valuation_date.date()``), not a policy trigger, so
    it is checked first and unconditionally.

    Args:
        days_to_expiry: Calendar days from the valuation date to maturity.
        boundaries: Resolved IPS boundaries from :func:`expiry_boundaries`.

    Returns:
        The bucket this runway falls in.

    """
    if days_to_expiry <= 0:
        return ExpiryBucketLabel.EXPIRED
    if days_to_expiry < boundaries.urgent_days:
        return ExpiryBucketLabel.URGENT
    if days_to_expiry < boundaries.soon_days:
        return ExpiryBucketLabel.SOON
    if days_to_expiry <= boundaries.roll_due_days:
        return ExpiryBucketLabel.ROLL_DUE
    if days_to_expiry <= boundaries.roll_review_days:
        return ExpiryBucketLabel.ROLL_REVIEW
    return ExpiryBucketLabel.LONG_TERM


def _bucket_totals(
    aged: tuple[AgedPosition, ...],
) -> tuple[ExpiryBucketTotal, ...]:
    """Aggregate *aged* into one zero-filled total per canonical bucket."""
    return tuple(
        _total_for(
            label,
            tuple(entry for entry in aged if entry.bucket == label),
        )
        for label in BUCKET_ORDER
    )


def _total_for(
    label: ExpiryBucketLabel,
    members: tuple[AgedPosition, ...],
) -> ExpiryBucketTotal:
    """Sum one bucket's members into an :class:`ExpiryBucketTotal`."""
    return ExpiryBucketTotal(
        label=label,
        legs=len(members),
        totals=_signed_totals(members),
    )


def _calendar(
    aged: tuple[AgedPosition, ...],
) -> tuple[ExpiryCalendarEntry, ...]:
    """Collapse *aged* into one entry per distinct maturity date, ascending."""
    by_date: dict[dt, list[AgedPosition]] = {}
    for entry in aged:
        by_date.setdefault(entry.position.option.maturity_date, []).append(
            entry,
        )

    return tuple(
        ExpiryCalendarEntry(
            maturity_date=maturity_date,
            days_to_expiry=members[0].days_to_expiry,
            bucket=members[0].bucket,
            legs=len(members),
            totals=_signed_totals(members),
        )
        for maturity_date, members in sorted(by_date.items())
    )


def evaluate_position_aging(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> PositionAging:
    """Bucket every leg of *portfolio* by expiry and build the calendar.

    Days to expiry are measured against the portfolio's (what-if)
    ``valuation_date``, not the wall clock, and as a calendar-date
    difference via :func:`~deltadewa.clock.days_between` -- so moving the
    valuation date re-buckets the book, and the boundaries land where the
    pricing engine puts them (#182).

    Args:
        portfolio: Live OptionPortfolio to age.
        ips_config: Hedge program policy (see :mod:`deltadewa.ips_config`).

    Returns:
        The bucket totals, per-leg grades and expiration calendar. An empty
        book returns real boundaries with zero-filled buckets and no legs.

    """
    boundaries = expiry_boundaries(ips_config.triggers)
    as_of = portfolio.valuation_date

    aged: list[AgedPosition] = []
    for position in portfolio.positions:
        days_to_expiry = days_between(as_of, position.option.maturity_date)
        aged.append(
            AgedPosition(
                position=position,
                days_to_expiry=days_to_expiry,
                bucket=classify_expiry_bucket(days_to_expiry, boundaries),
            ),
        )

    ordered = tuple(sorted(aged, key=lambda entry: entry.days_to_expiry))

    return PositionAging(
        boundaries=boundaries,
        buckets=_bucket_totals(ordered),
        positions=ordered,
        calendar=_calendar(ordered),
    )
