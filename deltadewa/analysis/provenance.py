"""The provenance ledger: one worst-of grade over every pricing input.

Batch 3d / #367. ``build_chrome`` (``app/chrome.py``) and the weekly digest
have graded only ``MarketEnvironment.data_quality`` — the six *fetched*
market readings (VIX, term structure, SKEW). Four inputs a book is
actually **priced** on are hand-entered and never fetched at all: spot,
the risk-free rate, the dividend yield (book-level,
``deltadewa.portfolio.stamps.MarketParameterStamps``), and per-leg
implied volatility (``OptionPosition.volatility_as_of``). None of them
have a feed to grade staleness against, so "stale" here means "unconfirmed
for longer than the review cadence ``ips_config.IpsPricingInputs``
sets" — a policy judgment, not a market fact.

This module builds one ``ProvenanceLedger`` covering both kinds of input
side by side, so a single worst-of can drive the banner and the digest
gate (#367's acceptance) while ``/health`` can still show fetched market
data and hand-entered pricing inputs as two separate, never-merged
objects (#368) — a stale hand-entered rate must never make ``/health``
claim the *market data feed itself* is stale.

``Freshness`` is deliberately a different vocabulary from ``DataQuality``:
a hand-entered input was never "cached" or "live" in the fetched sense,
and an input that has *never* been confirmed (``UNKNOWN``) is a strictly
worse — not merely different — condition than one confirmed long ago
(``AGING``), which is itself worse than one with no confirmation date
because the channel was never fetched at all in a way that makes an
age meaningful (that last case does not occur for hand-entered inputs;
see ``InputProvenance`` on ``MISSING``). ``ProvenanceLedger.combined_quality``
maps the overall worst grade back onto ``DataQuality`` so the digest's
existing ``_STALE_OR_WORSE`` gate and ``/health``'s vocabulary need no new
grade string — see that property for the (deliberate, lossy) mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from deltadewa.analysis.market_environment import DataQuality

if TYPE_CHECKING:
    from datetime import date, datetime

    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.ips_config import IpsPricingInputs
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition


class InputKind(StrEnum):
    """Whether an input is fetched from a provider or hand-entered."""

    FETCHED = "FETCHED"
    """Comes from a ``MarketDataProvider`` — graded via ``DataQuality``."""
    HAND_ENTERED = "HAND_ENTERED"
    """Typed by an operator — graded via a review-age policy instead."""


class Freshness(StrEnum):
    """How trustworthy a single provenance entry currently is.

    Ordered ``FRESH < AGING < UNKNOWN < MISSING``. ``UNKNOWN`` outranks
    ``AGING`` deliberately: an aging input's damage is bounded (you know
    it is, say, 40 days stale), while an unconfirmed one's is not — it
    could be five minutes old or five years old, and nothing here can
    tell the difference.
    """

    FRESH = "FRESH"
    """Fetched within its TTL, or hand-entered and confirmed recently."""
    AGING = "AGING"
    """Fetched past its TTL (cache-served), or confirmed but overdue."""
    UNKNOWN = "UNKNOWN"
    """Synthetic fetch, or a hand-entered input never explicitly confirmed."""
    MISSING = "MISSING"
    """A fetched channel with no cached reading at all. Hand-entered inputs
    never take this grade — a book always carries *some* value for spot,
    rate, dividend yield, and per-leg IV; only its confirmation age can be
    unknown, which is ``UNKNOWN`` above, a distinct and lesser condition."""


_FRESHNESS_SEVERITY: Final[dict[Freshness, int]] = {
    Freshness.FRESH: 0,
    Freshness.AGING: 1,
    Freshness.UNKNOWN: 2,
    Freshness.MISSING: 3,
}

# How a FETCHED entry's own DataQuality maps onto the shared Freshness
# scale. Monotonic with _SOURCE_SEVERITY in marketdata._observation, so
# comparing a FETCHED entry against a HAND_ENTERED one on Freshness alone
# is meaningful.
_QUALITY_TO_FRESHNESS: Final[dict[DataQuality, Freshness]] = {
    DataQuality.LIVE: Freshness.FRESH,
    DataQuality.CACHED: Freshness.FRESH,
    DataQuality.STALE: Freshness.AGING,
    DataQuality.STATIC: Freshness.UNKNOWN,
    DataQuality.UNAVAILABLE: Freshness.MISSING,
}

# The reverse mapping, for HAND_ENTERED entries only (a FETCHED entry's
# own .quality is used verbatim instead — see combined_quality). A
# deliberate, lossy re-use of DataQuality's existing vocabulary rather
# than a new grade string, so the digest's _STALE_OR_WORSE gate and
# /health's consumers need no changes to recognize a stale hand-entered
# input. No FRESH entry here: a HAND_ENTERED entry that is the ledger's
# worst *and* FRESH means nothing anywhere is worse than fine, so
# combined_quality falls back to the fetched market data's own quality.
_FRESHNESS_TO_QUALITY: Final[dict[Freshness, DataQuality]] = {
    Freshness.AGING: DataQuality.STALE,
    Freshness.UNKNOWN: DataQuality.STATIC,
    Freshness.MISSING: DataQuality.UNAVAILABLE,
}


@dataclass(frozen=True)
class InputProvenance:
    """One graded pricing input — fetched or hand-entered.

    Attributes:
        key: Stable identifier (e.g. ``"book.spot"``,
            ``"leg.<position_id>.iv"``, ``"market_data"``).
        label: Human-readable name for the panel/banner.
        kind: Whether this is fetched or hand-entered.
        freshness: The graded freshness.
        as_of: When this value was last confirmed (hand-entered) or
            observed (fetched). ``None`` iff never confirmed/unavailable.
        age_days: Whole calendar days between ``as_of`` and the ledger's
            ``as_of`` (see ``build_provenance_ledger``). ``None`` iff
            ``as_of`` is ``None``.
        max_age_days: The policy age this was graded against.
            ``None`` for ``FETCHED`` entries, which have no such policy.
        quality: The underlying ``DataQuality``, ``FETCHED`` entries only.
        detail: A one-clause human explanation of the grade.

    """

    key: str
    label: str
    kind: InputKind
    freshness: Freshness
    as_of: datetime | None
    age_days: int | None
    max_age_days: int | None
    quality: DataQuality | None
    detail: str


@dataclass(frozen=True)
class ProvenanceLedger:
    """One worst-of view over every pricing input, fetched and hand-entered.

    ``entries`` is what the banner and the provenance panel iterate;
    ``market_data_*``/``oldest_series`` are carried as separate top-level
    fields (rather than requiring a consumer to filter ``entries`` for
    the ``"market_data"`` key) specifically so ``/health`` can render a
    ``market_data`` object and a ``pricing_inputs`` object as two never-
    merged siblings (#368) — a stale hand-entered rate must not make
    ``/health`` say the *fetched market data* is stale.
    """

    entries: tuple[InputProvenance, ...]
    market_data_as_of: datetime | None
    market_data_fetched_at: datetime | None
    market_data_quality: DataQuality
    oldest_series: str | None

    @property
    def worst(self) -> InputProvenance | None:
        """The single least-trustworthy entry, or ``None`` if empty."""
        if not self.entries:
            return None
        return max(
            self.entries,
            key=lambda entry: _FRESHNESS_SEVERITY[entry.freshness],
        )

    @property
    def needs_banner(self) -> bool:
        """Whether an unmissable banner (not just the quiet stamp) is due.

        Only when the worst entry is not ``FRESH`` — a healthy fetched
        pipeline that happens to include one lagged-but-CACHED series
        (VIX's normal FRED lag, #368) must not mount a banner, or every
        addition #367 makes to what gets graded would make the banner
        permanently on, and operators would stop reading it.
        """
        worst = self.worst
        return worst is not None and worst.freshness is not Freshness.FRESH

    @property
    def combined_quality(self) -> DataQuality:
        """The ledger's worst entry, re-expressed as a ``DataQuality``.

        This is what the digest's existing ``_STALE_OR_WORSE`` gate and
        ``/health``'s vocabulary read — a deliberate, lossy trade so
        neither needs a new grade string. A ``FETCHED`` worst entry's own
        ``quality`` is used verbatim (preserving the ``LIVE``/``CACHED``
        distinction ``Freshness`` collapses); a ``HAND_ENTERED`` worst
        entry maps through ``_FRESHNESS_TO_QUALITY``, falling back to the
        fetched market data's own quality when the worst entry is
        ``FRESH`` (nothing anywhere is worse than fine).
        """
        worst = self.worst
        if worst is None:
            return self.market_data_quality
        if worst.quality is not None:
            return worst.quality
        return _FRESHNESS_TO_QUALITY.get(
            worst.freshness,
            self.market_data_quality,
        )

    def by_kind(self, kind: InputKind) -> tuple[InputProvenance, ...]:
        """Return only the entries of the given *kind*."""
        return tuple(entry for entry in self.entries if entry.kind is kind)


def _age_days(as_of: date, stamp: datetime) -> int:
    """Whole calendar days from *stamp* to *as_of*, never negative.

    Calendar-date subtraction, not instant subtraction — the same
    discipline ``clock.days_between`` applies, just against a plain
    ``date`` rather than another ``datetime`` (callers here are the
    weekly digest, which already narrows to a ``date``, and any
    per-request builder, which can narrow the same way). Clamped at
    zero: a stamp that is, by clock skew or a backdated confirmation,
    "in the future" relative to *as_of* has no honest negative age to
    report.
    """
    return max((as_of - stamp.date()).days, 0)


def _grade_hand_entered(
    *,
    key: str,
    label: str,
    stamp: datetime | None,
    max_age_days: int,
    as_of: date,
) -> InputProvenance:
    """Grade one hand-entered input against its policy max age.

    ``stamp is None`` — never explicitly confirmed, including every
    position and book that predates #367 — grades ``UNKNOWN``, never
    ``FRESH``: an unrecorded confirmation date is not the same as a
    fresh one, and treating it as fresh would launder every existing
    stale input into a clean banner the first time this code runs.
    """
    if stamp is None:
        return InputProvenance(
            key=key,
            label=label,
            kind=InputKind.HAND_ENTERED,
            freshness=Freshness.UNKNOWN,
            as_of=None,
            age_days=None,
            max_age_days=max_age_days,
            quality=None,
            detail=f"{label} has never been confirmed",
        )
    age_days = _age_days(as_of, stamp)
    freshness = Freshness.FRESH if age_days <= max_age_days else Freshness.AGING
    detail = f"{label} confirmed {age_days}d ago (policy: {max_age_days}d)"
    return InputProvenance(
        key=key,
        label=label,
        kind=InputKind.HAND_ENTERED,
        freshness=freshness,
        as_of=stamp,
        age_days=age_days,
        max_age_days=max_age_days,
        quality=None,
        detail=detail,
    )


def _leg_label(position: OptionPosition) -> str:
    """Human-readable label for one position's IV provenance entry."""
    option = position.option
    return (
        f"{option.option_type.value} {option.strike_price:g} exp "
        f"{option.maturity_date:%Y-%m-%d} IV"
    )


def build_provenance_ledger(
    environment: MarketEnvironment,
    portfolio: OptionPortfolio,
    policy: IpsPricingInputs,
    *,
    as_of: date,
) -> ProvenanceLedger:
    """Build the ledger covering fetched market data and hand-entered inputs.

    Never raises: every field it reads (``environment``'s already-assessed
    quality, ``portfolio.stamps``, each position's ``volatility_as_of``)
    is a plain attribute with no provider call behind it, so there is
    nothing here to fail. Safe to call unguarded from ``build_chrome``
    and ``/health``, which both render unconditionally.

    Args:
        environment: A pre-assessed ``MarketEnvironment`` — this function
            does not fetch anything itself; pass the same instance the
            page (or digest) already built, per the "one grader" rule.
        portfolio: The live book — read for ``portfolio.stamps`` and
            each position's ``volatility_as_of``.
        policy: ``ips_config.pricing_inputs`` — the review-cadence bands.
        as_of: The program's current trading date (a plain ``date``,
            e.g. ``program_trading_date().date()``), against which every
            hand-entered stamp's age is measured.

    Returns:
        A ``ProvenanceLedger`` with one entry for the fetched market data
        as a whole, one each for the book-level spot/rate/dividend
        stamps, and one per position's volatility stamp.

    """
    market_data_freshness = _QUALITY_TO_FRESHNESS[environment.data_quality]
    market_data_entry = InputProvenance(
        key="market_data",
        label="Fetched market data (VIX, term structure, SKEW)",
        kind=InputKind.FETCHED,
        freshness=market_data_freshness,
        as_of=environment.as_of,
        age_days=(
            _age_days(as_of, environment.as_of)
            if environment.as_of is not None
            else None
        ),
        max_age_days=None,
        quality=environment.data_quality,
        detail=f"combined grade: {environment.data_quality.value}",
    )

    entries: list[InputProvenance] = [market_data_entry]
    entries.append(
        _grade_hand_entered(
            key="book.spot",
            label="Spot price",
            stamp=portfolio.stamps.spot_as_of,
            max_age_days=policy.spot_max_age_days,
            as_of=as_of,
        ),
    )
    entries.append(
        _grade_hand_entered(
            key="book.risk_free_rate",
            label="Risk-free rate",
            stamp=portfolio.stamps.risk_free_rate_as_of,
            max_age_days=policy.risk_free_rate_max_age_days,
            as_of=as_of,
        ),
    )
    entries.append(
        _grade_hand_entered(
            key="book.dividend_yield",
            label="Dividend yield",
            stamp=portfolio.stamps.dividend_yield_as_of,
            max_age_days=policy.dividend_yield_max_age_days,
            as_of=as_of,
        ),
    )
    entries.extend(
        _grade_hand_entered(
            key=f"leg.{position.position_id}.iv",
            label=_leg_label(position),
            stamp=position.volatility_as_of,
            max_age_days=policy.volatility_max_age_days,
            as_of=as_of,
        )
        for position in portfolio.positions
    )

    return ProvenanceLedger(
        entries=tuple(entries),
        market_data_as_of=environment.as_of,
        # Wired to a real value once MarketEnvironment carries its own
        # fetched_at (#368) — until then, no such timestamp exists to
        # report, and None is the honest answer, not a fabricated one.
        market_data_fetched_at=getattr(environment, "fetched_at", None),
        market_data_quality=environment.data_quality,
        oldest_series=getattr(environment, "oldest_series", None),
    )
