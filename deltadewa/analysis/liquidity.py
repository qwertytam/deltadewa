"""Grade hand-entered liquidity quotes: Part X #12 as a checklist (8c, N10).

The real Part X #12 Liquidity Risk metric needs per-strike bid/ask and
open interest from an options-chain feed (#156), which the free CBOE/FRED
provider does not have. This module grades what the operator *can*
supply instead — a quote read off their broker for each held leg
(:class:`~deltadewa.portfolio.liquidity.LiquidityObservation`) — and
turns a data-blocked metric into a checklist: which legs have never been
checked, which checks are overdue, which spread was wide when last read,
and which legs are in a roll window and need a fresh read now.

Three rules keep it honest:

- **Thresholds are IPS policy** (``ips_config.IpsLiquidity``). The
  handbook names wide spreads and low open interest as warning signs but
  gives no number, so there are no defaults here: with no ``liquidity:``
  section every quote is shown ``UNGRADED``.
- **Age reuses #367's rule** (``analysis.provenance.grade_hand_entered``)
  rather than a staleness rule invented for one metric.
- **It never joins the provenance ledger or its alarm.** A leg with no
  quote would grade ``UNKNOWN`` there, and ``assess_freshness`` alarms
  on ``UNKNOWN`` — every never-checked leg would put "STALE DATA" on the
  digest and a permanent banner on the app (#398's alarm fatigue
  again). The ledger is also "every *pricing* input", and a spread
  prices nothing.

The headline is counts, never one verdict word: "the book's liquidity is
fine" is not a sentence a handful of point-in-time quotes can support.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from deltadewa.analysis.provenance import Freshness, grade_hand_entered
from deltadewa.analysis.roll_status import RollVerdict

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from deltadewa.analysis.provenance import InputProvenance
    from deltadewa.analysis.roll_status import RollStatusRecord
    from deltadewa.ips_config import IpsLiquidity
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.liquidity import LiquidityObservation
    from deltadewa.portfolio.position import OptionPosition


class SpreadGrade(StrEnum):
    """How a recorded spread compares with ``spread_warn_pct``."""

    WITHIN = "WITHIN"
    """At or inside the IPS spread threshold when it was read."""
    WIDE = "WIDE"
    """Wider than the IPS spread threshold when it was read."""
    UNGRADED = "UNGRADED"
    """No ``liquidity:`` policy in ips.yaml to grade against."""


class OpenInterestGrade(StrEnum):
    """How recorded open interest compares with ``open_interest_min``."""

    ADEQUATE = "ADEQUATE"
    """At or above the IPS minimum when it was read."""
    LOW = "LOW"
    """Below the IPS minimum when it was read."""
    UNGRADED = "UNGRADED"
    """No minimum set, or the quote was recorded without open interest."""


# Roll verdicts that mean "this leg is about to be traded": the exit side
# of a roll is exactly when the handbook says liquidity matters. EXPIRED
# is excluded — there is nothing left to trade.
_ROLL_DUE_VERDICTS = frozenset({RollVerdict.ROLL, RollVerdict.REVIEW})

# Binary-float noise on a percent, far below any quote's precision.
_FLOAT_TOLERANCE_PCT = 1e-9


@dataclass(frozen=True)
class LegLiquidity:
    """One leg's liquidity checklist line.

    Attributes:
        position_id: The leg's stable id.
        label: Human-readable leg name, e.g. ``"put 4200 exp 2027-06-18"``.
        quantity: Signed contracts held — for the held-vs-OI share.
        observation: The last recorded quote, or ``None`` if never checked.
        freshness: The quote's age graded by #367's rule, or ``None`` when
            there is no ``liquidity:`` policy (no cadence to grade it by).
        spread_grade: The recorded spread against policy, or ``None`` when
            never checked. A grade on a quote that is not ``FRESH``
            describes the moment it was read, not now — renderers say so.
        open_interest_grade: Recorded OI against policy, or ``None`` when
            never checked.
        held_share_of_oi_pct: ``|quantity| / open_interest * 100`` —
            shown as context ("you hold 4% of the open interest") and
            deliberately ungraded: the handbook gives no threshold.
            ``None`` without a recorded, non-zero open interest.
        roll_due: The leg's roll status is ``ROLL`` or ``REVIEW``.
        capture_due: A fresh quote is due now — never checked, the last
            check not ``FRESH``, or the leg is in a roll window.

    """

    position_id: str
    label: str
    quantity: int
    observation: LiquidityObservation | None
    freshness: InputProvenance | None
    spread_grade: SpreadGrade | None
    open_interest_grade: OpenInterestGrade | None
    held_share_of_oi_pct: float | None
    roll_due: bool
    capture_due: bool


@dataclass(frozen=True)
class LiquidityChecklist:
    """Every leg's liquidity line, plus counts — never one verdict.

    Attributes:
        legs: One line per position, in book order.
        policy_present: Whether ips.yaml has a ``liquidity:`` section.
        never_checked: Legs with no recorded quote.
        overdue: Legs whose last quote is older than the policy cadence.
        wide_at_last_check: Legs whose last recorded spread graded WIDE.
        capture_due: Legs needing a fresh quote now.

    """

    legs: tuple[LegLiquidity, ...]
    policy_present: bool
    never_checked: int
    overdue: int
    wide_at_last_check: int
    capture_due: int


def roll_due_position_ids(
    records: Sequence[RollStatusRecord],
) -> frozenset[str]:
    """Return the ids of legs whose roll status says "trade soon".

    Args:
        records: ``roll_status.evaluate_roll_status`` output.

    Returns:
        Position ids with a ``ROLL`` or ``REVIEW`` verdict.

    """
    return frozenset(
        record.position.position_id
        for record in records
        if record.verdict in _ROLL_DUE_VERDICTS
    )


def _leg_label(position: OptionPosition) -> str:
    option = position.option
    return (
        f"{option.option_type.value} {option.strike_price:g} exp "
        f"{option.maturity_date:%Y-%m-%d}"
    )


def _spread_grade(
    observation: LiquidityObservation,
    policy: IpsLiquidity | None,
) -> SpreadGrade:
    if policy is None:
        return SpreadGrade.UNGRADED
    # Tolerance, not policy: a cent-quoted spread exactly at the threshold
    # (1.90/2.10 vs 10%) computes as 10.000000000000009 in binary float
    # and must not grade WIDE on rounding noise.
    if observation.spread_pct > policy.spread_warn_pct + _FLOAT_TOLERANCE_PCT:
        return SpreadGrade.WIDE
    return SpreadGrade.WITHIN


def _open_interest_grade(
    observation: LiquidityObservation,
    policy: IpsLiquidity | None,
) -> OpenInterestGrade:
    if (
        policy is None
        or policy.open_interest_min is None
        or observation.open_interest is None
    ):
        return OpenInterestGrade.UNGRADED
    if observation.open_interest < policy.open_interest_min:
        return OpenInterestGrade.LOW
    return OpenInterestGrade.ADEQUATE


def _held_share_of_oi_pct(
    position: OptionPosition,
    observation: LiquidityObservation | None,
) -> float | None:
    if observation is None or not observation.open_interest:
        return None
    return abs(position.quantity) / observation.open_interest * 100


def _assess_leg(
    position: OptionPosition,
    policy: IpsLiquidity | None,
    *,
    as_of: date,
    roll_due: bool,
) -> LegLiquidity:
    observation = position.liquidity
    label = _leg_label(position)
    freshness = (
        grade_hand_entered(
            key=f"leg.{position.position_id}.liquidity",
            label=f"{label} quote",
            stamp=observation.observed_at if observation is not None else None,
            max_age_days=policy.observation_max_age_days,
            as_of=as_of,
        )
        if policy is not None
        else None
    )
    stale = freshness is not None and freshness.freshness is not Freshness.FRESH
    return LegLiquidity(
        position_id=position.position_id,
        label=label,
        quantity=position.quantity,
        observation=observation,
        freshness=freshness,
        spread_grade=(
            _spread_grade(observation, policy)
            if observation is not None
            else None
        ),
        open_interest_grade=(
            _open_interest_grade(observation, policy)
            if observation is not None
            else None
        ),
        held_share_of_oi_pct=_held_share_of_oi_pct(position, observation),
        roll_due=roll_due,
        capture_due=observation is None or stale or roll_due,
    )


def assess_liquidity(
    portfolio: OptionPortfolio,
    policy: IpsLiquidity | None,
    *,
    as_of: date,
    roll_due_ids: frozenset[str] = frozenset(),
) -> LiquidityChecklist:
    """Build the liquidity checklist for every held leg.

    Never raises and fetches nothing: every input is a plain attribute on
    the book, so this is safe to call from a panel without a guard of
    its own (the panel still renders inside ``safe_render``).

    Args:
        portfolio: The live book.
        policy: ``ips_config.liquidity`` — ``None`` grades nothing.
        as_of: The program trading date (``program_trading_date().date()``)
            every quote's age is measured against.
        roll_due_ids: Legs about to be traded
            (:func:`roll_due_position_ids`), which need a fresh quote
            regardless of how recent the last one is.

    Returns:
        A :class:`LiquidityChecklist` in book order.

    """
    legs = tuple(
        _assess_leg(
            position,
            policy,
            as_of=as_of,
            roll_due=position.position_id in roll_due_ids,
        )
        for position in portfolio.positions
    )
    return LiquidityChecklist(
        legs=legs,
        policy_present=policy is not None,
        never_checked=sum(1 for leg in legs if leg.observation is None),
        overdue=sum(
            1
            for leg in legs
            if leg.observation is not None
            and leg.freshness is not None
            and leg.freshness.freshness is Freshness.AGING
        ),
        wide_at_last_check=sum(
            1 for leg in legs if leg.spread_grade is SpreadGrade.WIDE
        ),
        capture_due=sum(1 for leg in legs if leg.capture_due),
    )
