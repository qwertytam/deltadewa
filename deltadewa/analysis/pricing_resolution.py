"""Decide, once, what the book is priced on (9b, adoption).

Every price in the program rests on four inputs: the index level (spot), the
risk-free rate, the dividend yield and each option's implied volatility.
Until 9b a person typed all four. With a ``pricing_feed`` policy the
nightly refresh caches Cboe's delayed SPX option chain and a FRED rate, and
this module chooses, **for each input, one value and where it came from**:

``FETCHED``
    Today's fetched value.
``LAST_GOOD``
    The last cached value, served past its TTL because a night's download
    failed, and still inside ``max_quote_age_days``.
``OVERRIDE``
    The operator's typed value, pinned above the feed.
``FALLBACK``
    The operator's typed value, because the feed has nothing usable for
    this input (no chain, a quote that cannot be priced from, or a feed
    older than ``max_quote_age_days``).
``ENTERED``
    The operator's typed value, because the policy does not adopt this
    input (or there is no ``pricing_feed`` section at all).

The resolver is **pure**: the feed is read once, by :func:`read_feed`, and
handed in, so one process can never price two pages on two chains. It does
not touch the book. :class:`~deltadewa.state.ProgramState` applies the
result to a *copy* of the typed book (the priced view), so what a human
typed is never overwritten and never saved as something fetched.

Order matters and is fixed: the rate, then the dividend yield, then spot,
then each option's IV. An IV and the (r, q) it was solved with are a pair
(9b.0): a mid reprices exactly only at the rate and yield it was solved at,
so each IV is solved at the **effective** r and q, never the typed ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from deltadewa.analysis.chain_quotes import read_contract
from deltadewa.analysis.implied_vol import cmt_to_continuous
from deltadewa.analysis.market_environment import (
    DataQuality,
    data_quality_of,
    worst_quality,
)
from deltadewa.marketdata import MarketDataError, Source
from deltadewa.marketdata.chain import MatchFlag

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date, datetime

    from deltadewa.analysis.chain_quotes import ChainReading
    from deltadewa.constants import OptionType
    from deltadewa.ips_config import IpsConfig, IpsPricingFeed
    from deltadewa.marketdata import MarketDataProvider, Observation
    from deltadewa.marketdata.chain import ChainSnapshot
    from deltadewa.portfolio.core import OptionPortfolio

__all__ = [
    "EnteredInputs",
    "FeedInputs",
    "InputOrigin",
    "LegTerms",
    "OverrideKind",
    "ResolvedInputs",
    "ResolvedValue",
    "SeriesUse",
    "TypedInUse",
    "leg_terms",
    "newer_cached_session",
    "read_feed",
    "resolve_pricing_inputs",
]

#: The three inputs a policy may adopt, as ``pricing_feed.adopt`` names them.
_SPOT: Final = "spot"
_RATE: Final = "risk_free_rate"
_VOLATILITY: Final = "volatility"

#: Why a quote cannot be priced from, in the words a panel shows.
_FLAG_REASONS: Final[dict[MatchFlag, str]] = {
    MatchFlag.ABSENT: "not listed on the chain",
    MatchFlag.ZERO_BID: "no bid",
    MatchFlag.NO_ASK: "no ask",
    MatchFlag.WIDE: "spread too wide",
    MatchFlag.CROSSED: "bid above ask",
    MatchFlag.NO_SOLVE: "no volatility reproduces the mid",
    MatchFlag.STALE_QUOTE: "quote too old",
    MatchFlag.AMBIGUOUS_ROOT: "both roots list the date",
}


class InputOrigin(StrEnum):
    """Where one effective pricing input came from."""

    FETCHED = "FETCHED"
    LAST_GOOD = "LAST_GOOD"
    OVERRIDE = "OVERRIDE"
    FALLBACK = "FALLBACK"
    ENTERED = "ENTERED"


class OverrideKind(StrEnum):
    """The inputs an operator can pin above the feed (D7).

    The rate is not one: it has no divergence threshold to warn against, and
    to price on your own rate you take it out of ``pricing_feed.adopt``.
    """

    SPOT = "spot"
    VOLATILITY = "volatility"


#: Origins that are the feed's own number (the others are typed values).
_FEED_ORIGINS: Final = frozenset({InputOrigin.FETCHED, InputOrigin.LAST_GOOD})


@dataclass(frozen=True)
class LegTerms:
    """The contract a held leg is, as the chain matches it."""

    position_id: str
    expiry: date
    option_type: OptionType
    strike: float


def leg_terms(portfolio: OptionPortfolio) -> tuple[LegTerms, ...]:
    """Read every held leg's contract off *portfolio*, in book order."""
    return tuple(
        LegTerms(
            position_id=position.position_id,
            expiry=position.option.maturity_date.date(),
            option_type=position.option.option_type,
            strike=position.option.strike_price,
        )
        for position in portfolio.positions
    )


@dataclass(frozen=True)
class EnteredInputs:
    """What a human typed, read off the typed book.

    Attributes:
        spot: The typed index level.
        risk_free_rate: The typed continuous rate.
        dividend_yield: The typed continuous yield.
        leg_vols: Each leg's typed IV by ``position_id``.
        spot_pinned: The operator pinned the typed spot above the feed.
        pinned_legs: Legs whose typed IV the operator pinned.

    """

    spot: float
    risk_free_rate: float
    dividend_yield: float
    leg_vols: Mapping[str, float]
    spot_pinned: bool
    pinned_legs: frozenset[str]

    @classmethod
    def from_portfolio(cls, portfolio: OptionPortfolio) -> EnteredInputs:
        """Snapshot the typed book's inputs and pins."""
        return cls(
            spot=portfolio.spot_price,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            leg_vols={
                position.position_id: position.option.volatility
                for position in portfolio.positions
            },
            spot_pinned=portfolio.spot_override,
            pinned_legs=frozenset(
                position.position_id
                for position in portfolio.positions
                if position.volatility_override
            ),
        )


@dataclass(frozen=True)
class FeedInputs:
    """What the feed held when the process read it, read once.

    A member is ``None`` when it was not read (the policy does not adopt
    what it feeds) or nothing is cached for it.
    """

    chain: Observation[ChainSnapshot] | None = None
    rate: Observation[float] | None = None
    index_spot: Observation[float] | None = None


def read_feed(
    provider: MarketDataProvider,
    ips_config: IpsConfig | None,
) -> FeedInputs:
    """Read, once, the cached series the policy's ``adopt`` list needs.

    Reads nothing without a ``pricing_feed`` section, and only the series an
    adopted input uses. A series nothing has cached is ``None``, not an
    error: the resolver reads that as "the feed has nothing" and falls back.

    Args:
        provider: The market-data provider (read-only in the app).
        ips_config: The policy.

    Returns:
        The readings.

    """
    policy = ips_config.pricing_feed if ips_config is not None else None
    if ips_config is None or policy is None:
        return FeedInputs()
    instrument = ips_config.program.instrument
    adopt = frozenset(policy.adopt)
    chain = None
    if adopt & {_SPOT, _VOLATILITY}:
        try:
            chain = provider.get_option_chain(instrument)
        except MarketDataError:
            chain = None
    rate = None
    if _RATE in adopt:
        try:
            rate = provider.get_rate(policy.rate_series)
        except MarketDataError:
            rate = None
    index_spot = None
    if _SPOT in adopt:
        try:
            index_spot = provider.get_spot(instrument)
        except MarketDataError:
            index_spot = None
    return FeedInputs(chain=chain, rate=rate, index_spot=index_spot)


def newer_cached_session(
    provider: MarketDataProvider,
    ips_config: IpsConfig | None,
    resolution: ResolvedInputs,
) -> date | None:
    """Return the chain session cached now, if it is later than the priced one.

    The app reads the feed once, at start, so a refresh that lands after
    the start is cached but not adopted until the next restart. This is the
    one question the pages and ``/health`` ask to say so ("a newer chain is
    cached; restart the app to price on it"). Never raises.

    Args:
        provider: The market-data provider.
        ips_config: The policy.
        resolution: What the process priced the book on.

    Returns:
        The newer session's date, or ``None`` when nothing newer is cached,
        nothing is adopted, or the chain cannot be read.

    """
    policy = ips_config.pricing_feed if ips_config is not None else None
    if ips_config is None or policy is None or not resolution.adopting:
        return None
    if not frozenset(policy.adopt) & {_SPOT, _VOLATILITY}:
        return None
    try:
        cached = provider.get_option_chain(ips_config.program.instrument)
    except MarketDataError:
        return None
    session = cached.value.session_date
    if resolution.session_date is None or session > resolution.session_date:
        return session
    return None


@dataclass(frozen=True)
class ResolvedValue:
    """One effective input, with where it came from.

    Attributes:
        value: The number the book is priced on.
        origin: Where it came from.
        detail: The label shown beside it ("Cboe 2026-11-16 close", "your
            override", "feed unusable: no bid; your value").
        session: The trading session of a fed value, else ``None``.
        fetched: The feed's own figure, when there is one and it is not what
            prices (an override or a fallback shows it beside the value).
        quality: The feed series' grade for a fed value, else ``None``.

    """

    value: float
    origin: InputOrigin
    detail: str
    session: date | None = None
    fetched: float | None = None
    quality: DataQuality | None = None

    @property
    def from_feed(self) -> bool:
        """Whether the feed's own number prices this input."""
        return self.origin in _FEED_ORIGINS


@dataclass(frozen=True)
class SeriesUse:
    """One feed series an adopted input depends on, graded as fetched data.

    Attributes:
        name: ``"chain"`` or ``"rate"``.
        quality: The series' grade. ``UNAVAILABLE`` when nothing usable is
            cached, or the cached value is older than ``max_quote_age_days``
            (so the book is not priced on it).
        as_of: The observation date of the datum itself.
        fetched_at: When the process last retrieved it.
        detail: One clause for a panel.

    """

    name: str
    quality: DataQuality
    as_of: datetime | None
    fetched_at: datetime | None
    detail: str


@dataclass(frozen=True)
class TypedInUse:
    """Which typed values are what prices the book right now.

    The review button stamps only these: confirming a typed value the feed
    is hiding would launder it into looking freshly checked, and the next
    night the feed fails it would price the book unchallenged.
    """

    spot: bool
    risk_free_rate: bool
    dividend_yield: bool
    legs: frozenset[str]


@dataclass(frozen=True)
class ResolvedInputs:  # pylint: disable=too-many-instance-attributes  # the resolution, stated
    """The book's effective inputs, each with its origin.

    Attributes:
        spot: The index level.
        risk_free_rate: The continuous rate.
        dividend_yield: The continuous yield (always typed).
        legs: Each leg's IV by ``position_id``.
        readings: The chain reading behind each leg that was read.
        series: The feed series the adopted inputs depend on.
        feed_down_since: The session of the newest data the feed had, when
            an adopted input fell back because that data is too old.
        error: Why resolution failed (everything is then ``ENTERED``), or
            ``None``.
        resolved_at: When the process read the prices.
        session_date: The chain session the prices are from, if any.
        is_identity: Whether every effective value equals the typed one, so
            the book needs no priced view at all.
        adopting: Whether the policy adopts anything from the feed. False
            with no ``pricing_feed`` section or an empty ``adopt`` list,
            when the pages say nothing about prices being read.

    """

    spot: ResolvedValue
    risk_free_rate: ResolvedValue
    dividend_yield: ResolvedValue
    legs: Mapping[str, ResolvedValue]
    readings: Mapping[str, ChainReading]
    series: tuple[SeriesUse, ...]
    feed_down_since: date | None
    error: str | None
    resolved_at: datetime
    session_date: date | None
    is_identity: bool
    adopting: bool = False

    @classmethod
    def all_entered(
        cls,
        entered: EnteredInputs,
        *,
        resolved_at: datetime,
        error: str | None = None,
        adopting: bool = False,
    ) -> ResolvedInputs:
        """Price on every typed value, optionally saying why.

        The result when there is no policy, nothing is adopted, or the
        resolver itself failed (*error* then names why).
        """
        return cls(
            spot=_typed(entered.spot),
            risk_free_rate=_typed(entered.risk_free_rate),
            dividend_yield=_typed(entered.dividend_yield),
            legs={
                position_id: _typed(vol)
                for position_id, vol in entered.leg_vols.items()
            },
            readings={},
            series=(),
            feed_down_since=None,
            error=error,
            resolved_at=resolved_at,
            session_date=None,
            is_identity=True,
            adopting=adopting,
        )

    def typed_in_use(self) -> TypedInUse:
        """Return which typed values currently price the book."""
        return TypedInUse(
            spot=not self.spot.from_feed,
            risk_free_rate=not self.risk_free_rate.from_feed,
            dividend_yield=True,
            legs=frozenset(
                position_id
                for position_id, leg in self.legs.items()
                if not leg.from_feed
            ),
        )

    @property
    def worst_series_quality(self) -> DataQuality | None:
        """The least trustworthy adopted series, or ``None`` if none."""
        if not self.series:
            return None
        return worst_quality(use.quality for use in self.series)


def _typed(value: float, detail: str = "your value") -> ResolvedValue:
    return ResolvedValue(value, InputOrigin.ENTERED, detail)


def _age_days(program_date: date, observed: datetime | None) -> int | None:
    return None if observed is None else (program_date - observed.date()).days


def _within(age: int | None, limit: int) -> bool:
    """Whether data of *age* days is young enough (no date means unknown)."""
    return age is None or age <= limit


def _feed_origin(source: Source) -> InputOrigin:
    """``LAST_GOOD`` for a value served past its TTL, else ``FETCHED``."""
    return (
        InputOrigin.LAST_GOOD
        if source is Source.STALE
        else (InputOrigin.FETCHED)
    )


def _why(reading: ChainReading) -> str:
    """Return why a reading cannot be priced from, as one clause."""
    reasons = [
        _FLAG_REASONS[flag]
        for flag in sorted(reading.flags, key=lambda flag: flag.value)
        if flag is not MatchFlag.AMBIGUOUS_ROOT
    ]
    if reading.quote is not None and reading.solved_iv is None and not reasons:
        reasons.append("no two-sided quote")
    return ", ".join(reasons) or "unusable quote"


def _resolve_rate(
    entered: EnteredInputs,
    policy: IpsPricingFeed,
    feed: FeedInputs,
    program_date: date,
) -> tuple[ResolvedValue, SeriesUse | None]:
    """Choose the rate and grade the series it came from."""
    if _RATE not in policy.adopt:
        return _typed(entered.risk_free_rate), None
    observation = feed.rate
    if observation is None:
        return (
            ResolvedValue(
                entered.risk_free_rate,
                InputOrigin.FALLBACK,
                "no rate cached; your value",
            ),
            SeriesUse(
                "rate",
                DataQuality.UNAVAILABLE,
                None,
                None,
                f"no {policy.rate_series} observation cached",
            ),
        )
    age = _age_days(program_date, observation.as_of)
    if not _within(age, policy.max_quote_age_days):
        return (
            ResolvedValue(
                entered.risk_free_rate,
                InputOrigin.FALLBACK,
                f"{policy.rate_series} is {age} days old "
                f"(limit {policy.max_quote_age_days}); your value",
            ),
            SeriesUse(
                "rate",
                DataQuality.UNAVAILABLE,
                observation.as_of,
                observation.fetched_at,
                f"{policy.rate_series} observation {age} days old "
                f"(limit {policy.max_quote_age_days})",
            ),
        )
    quality = data_quality_of(observation.source)
    observed = (
        f"{observation.as_of:%Y-%m-%d}"
        if observation.as_of is not None
        else "?"
    )
    return (
        ResolvedValue(
            cmt_to_continuous(observation.value),
            _feed_origin(observation.source),
            f"FRED {policy.rate_series}, {observed}",
            session=None
            if observation.as_of is None
            else observation.as_of.date(),
            quality=quality,
        ),
        SeriesUse(
            "rate",
            quality,
            observation.as_of,
            observation.fetched_at,
            f"{policy.rate_series}, {observed}",
        ),
    )


def _chain_use(
    policy: IpsPricingFeed,
    feed: FeedInputs,
    program_date: date,
) -> tuple[SeriesUse | None, bool]:
    """Grade the chain series, and say whether the book may price on it."""
    if not frozenset(policy.adopt) & {_SPOT, _VOLATILITY}:
        return None, False
    observation = feed.chain
    if observation is None:
        return (
            SeriesUse(
                "chain",
                DataQuality.UNAVAILABLE,
                None,
                None,
                "no option chain cached",
            ),
            False,
        )
    snapshot = observation.value
    age = (program_date - snapshot.session_date).days
    if age > policy.max_quote_age_days:
        return (
            SeriesUse(
                "chain",
                DataQuality.UNAVAILABLE,
                observation.as_of,
                observation.fetched_at,
                f"newest chain is the {snapshot.session_date} session, "
                f"{age} days old (limit {policy.max_quote_age_days})",
            ),
            False,
        )
    return (
        SeriesUse(
            "chain",
            data_quality_of(observation.source),
            observation.as_of,
            observation.fetched_at,
            f"{snapshot.session_date} session",
        ),
        True,
    )


def _resolve_spot(  # pylint: disable=too-many-arguments
    entered: EnteredInputs,
    policy: IpsPricingFeed,
    feed: FeedInputs,
    program_date: date,
    *,
    chain_usable: bool,
) -> ResolvedValue:
    """Choose spot.

    The pin, else the chain's own index level, else the nightly index
    close, else the typed value.
    """
    if _SPOT not in policy.adopt:
        return _typed(entered.spot)
    fetched, session, source = _fetched_spot(
        feed,
        policy,
        program_date,
        chain_usable=chain_usable,
    )
    if entered.spot_pinned:
        return ResolvedValue(
            entered.spot,
            InputOrigin.OVERRIDE,
            "your override",
            session=session,
            fetched=fetched,
        )
    if fetched is None or source is None:
        return ResolvedValue(
            entered.spot,
            InputOrigin.FALLBACK,
            "no usable index level on the feed; your value",
        )
    return ResolvedValue(
        fetched,
        _feed_origin(source),
        f"Cboe index level, {session} close"
        if chain_usable
        else f"index close, {session}",
        session=session,
        quality=data_quality_of(source),
    )


def _fetched_spot(
    feed: FeedInputs,
    policy: IpsPricingFeed,
    program_date: date,
    *,
    chain_usable: bool,
) -> tuple[float | None, date | None, Source | None]:
    """Return the feed's spot, its session, and how fresh its source is.

    The chain's own index level first (struck at the same instant as the
    quotes the IVs are solved from), then the nightly index close.
    """
    if chain_usable and feed.chain is not None:
        snapshot = feed.chain.value
        return snapshot.spot, snapshot.session_date, feed.chain.source
    index = feed.index_spot
    if index is not None and _within(
        _age_days(program_date, index.as_of),
        policy.max_quote_age_days,
    ):
        return (
            index.value,
            None if index.as_of is None else index.as_of.date(),
            index.source,
        )
    return None, None, None


def _resolve_leg(  # pylint: disable=too-many-arguments,too-many-locals
    leg: LegTerms,
    label: str,
    entered: EnteredInputs,
    policy: IpsPricingFeed,
    feed: FeedInputs,
    program_date: date,
    *,
    risk_free_rate: float,
    dividend_yield: float,
    chain_usable: bool,
) -> tuple[ResolvedValue, ChainReading | None]:
    """Choose one leg's IV, solved at the **effective** r and q."""
    typed = entered.leg_vols[leg.position_id]
    if _VOLATILITY not in policy.adopt:
        return _typed(typed), None
    if leg.expiry < program_date:
        return _typed(typed, "expired; your value"), None
    reading: ChainReading | None = None
    if feed.chain is not None:
        reading = read_contract(
            feed.chain.value,
            label=label,
            expiry=leg.expiry,
            option_type=leg.option_type,
            strike=leg.strike,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
            max_spread_pct=policy.max_spread_pct,
            max_quote_age_days=policy.max_quote_age_days,
            program_date=program_date,
        )
    solved = reading.solved_iv if reading is not None else None
    usable = (
        chain_usable
        and reading is not None
        and reading.usable
        and solved is not None
    )
    if leg.position_id in entered.pinned_legs:
        return (
            ResolvedValue(
                typed,
                InputOrigin.OVERRIDE,
                "your override",
                session=None if reading is None else reading.session_date,
                fetched=solved if usable else None,
            ),
            reading,
        )
    if (
        usable
        and reading is not None
        and solved is not None
        and feed.chain is not None
    ):
        return (
            ResolvedValue(
                solved,
                _feed_origin(feed.chain.source),
                f"solved from the {reading.session_date} close mid",
                session=reading.session_date,
                quality=data_quality_of(feed.chain.source),
            ),
            reading,
        )
    why = _why(reading) if reading is not None else "no option chain cached"
    return (
        ResolvedValue(
            typed,
            InputOrigin.FALLBACK,
            f"{why}; your value",
        ),
        reading,
    )


def resolve_pricing_inputs(  # pylint: disable=too-many-arguments,too-many-locals
    *,
    entered: EnteredInputs,
    legs: Sequence[LegTerms],
    policy: IpsPricingFeed | None,
    feed: FeedInputs,
    program_date: date,
    resolved_at: datetime,
) -> ResolvedInputs:
    """Choose every pricing input's effective value and its origin.

    Pure. The order is fixed (rate, yield, spot, then each IV at the
    effective rate and yield) because an IV and the (r, q) it was solved
    with are a pair.

    Args:
        entered: What a human typed, with the pins.
        legs: Every held leg's contract, in book order.
        policy: ``ips.yaml``'s ``pricing_feed`` section, or ``None`` (every
            input is then typed).
        feed: The feed as read once at start (:func:`read_feed`).
        program_date: The program's trading date.
        resolved_at: When the feed was read, for the "prices read at" line.

    Returns:
        The resolution.

    """
    if policy is None or not policy.adopt:
        return ResolvedInputs.all_entered(entered, resolved_at=resolved_at)

    rate, rate_use = _resolve_rate(entered, policy, feed, program_date)
    dividend = _typed(entered.dividend_yield)
    chain_use, chain_usable = _chain_use(policy, feed, program_date)
    spot = _resolve_spot(
        entered,
        policy,
        feed,
        program_date,
        chain_usable=chain_usable,
    )
    resolved_legs: dict[str, ResolvedValue] = {}
    readings: dict[str, ChainReading] = {}
    for index, leg in enumerate(legs, start=1):
        value, reading = _resolve_leg(
            leg,
            f"L{index}",
            entered,
            policy,
            feed,
            program_date,
            risk_free_rate=rate.value,
            dividend_yield=dividend.value,
            chain_usable=chain_usable,
        )
        resolved_legs[leg.position_id] = value
        if reading is not None:
            readings[leg.position_id] = reading

    series = tuple(use for use in (chain_use, rate_use) if use is not None)
    session_date = (
        feed.chain.value.session_date
        if chain_usable and feed.chain is not None
        else None
    )
    identical = (
        spot.value == entered.spot
        and rate.value == entered.risk_free_rate
        and all(
            value.value == entered.leg_vols[position_id]
            for position_id, value in resolved_legs.items()
        )
    )
    return ResolvedInputs(
        spot=spot,
        risk_free_rate=rate,
        dividend_yield=dividend,
        legs=resolved_legs,
        readings=readings,
        series=series,
        feed_down_since=_down_since(chain_use, rate_use, feed),
        error=None,
        resolved_at=resolved_at,
        session_date=session_date,
        is_identity=identical,
        adopting=True,
    )


def _down_since(
    chain_use: SeriesUse | None,
    rate_use: SeriesUse | None,
    feed: FeedInputs,
) -> date | None:
    """Return the session of the newest data an unusable series still has."""
    if (
        chain_use is not None
        and chain_use.quality is DataQuality.UNAVAILABLE
        and feed.chain is not None
    ):
        return feed.chain.value.session_date
    if (
        rate_use is not None
        and rate_use.quality is DataQuality.UNAVAILABLE
        and feed.rate is not None
        and feed.rate.as_of is not None
    ):
        return feed.rate.as_of.date()
    return None
