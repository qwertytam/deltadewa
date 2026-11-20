"""Read listed contracts off a chain snapshot, with the IV our engine solves.

One function, :func:`read_contract`, answers "what does the chain say about
this contract, and is it safe to price from?": the matched symbol, the
close quote, the vendor's IV beside the IV solved from the mid at **the
caller's own rate and dividend yield** (``analysis.implied_vol``), and the
reasons the quote may be unusable. The ``/design`` Pricing inputs panel and
the liquidity autofill both read through it, so they cannot disagree about
which contract a leg is or whether its quote is good.

Nothing here prices the book. The IV is solved at the snapshot's own index
level and session date (a hand-entered spot older than the quotes would put
its age into the IV), and nothing it returns is written anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final

from deltadewa import constants as const
from deltadewa.analysis.implied_vol import solve_implied_vol
from deltadewa.constants import OptionType
from deltadewa.marketdata import MarketDataError
from deltadewa.marketdata.chain import MatchFlag

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date, datetime

    from deltadewa.ips_config import IpsConfig, IpsPricingFeed
    from deltadewa.marketdata import MarketDataProvider, Observation
    from deltadewa.marketdata.chain import ChainQuote, ChainSnapshot
    from deltadewa.portfolio.core import OptionPortfolio

__all__ = [
    "ChainReading",
    "FetchedChain",
    "read_contract",
    "read_fetched_chain",
    "read_positions",
    "rung_readings",
]

#: Flags that do not make a quote unusable: the match is still the right
#: contract, and ``SPX`` was preferred.
_BENIGN_FLAGS: Final[frozenset[MatchFlag]] = frozenset(
    {MatchFlag.AMBIGUOUS_ROOT},
)


@dataclass(frozen=True)
class ChainReading:
    """What the chain says about one contract.

    Attributes:
        label: A caller-supplied name (a leg ordinal, a rung).
        quote: The matched contract, or ``None`` when it is not listed.
        solved_iv: The IV solved from the mid at the caller's r and q, as a
            fraction, or ``None`` when there is no two-sided quote or the
            mid is outside the no-arbitrage bounds.
        flags: Everything wrong with the reading.
        session_date: The trading session the quote belongs to.
        quoted_at: When the vendor generated the payload (aware UTC).

    """

    label: str
    quote: ChainQuote | None
    solved_iv: float | None
    flags: frozenset[MatchFlag]
    session_date: date
    quoted_at: datetime

    @property
    def usable(self) -> bool:
        """Whether a price could be built from this reading."""
        return (
            self.quote is not None
            and self.solved_iv is not None
            and not (self.flags - _BENIGN_FLAGS)
        )


def read_contract(  # pylint: disable=too-many-arguments
    snapshot: ChainSnapshot,
    *,
    label: str,
    expiry: date,
    option_type: OptionType,
    strike: float,
    risk_free_rate: float,
    dividend_yield: float,
    max_spread_pct: float,
    max_quote_age_days: int,
    program_date: date,
) -> ChainReading:
    """Match one contract and solve its IV at the caller's r and q.

    Args:
        snapshot: The parsed chain.
        label: A name for the reading (a leg ordinal, a rung).
        expiry: The contract's expiry date.
        option_type: Call or put.
        strike: The strike in index points.
        risk_free_rate: Continuously compounded rate, as a fraction.
        dividend_yield: Continuous dividend yield, as a fraction.
        max_spread_pct: Spread above which the quote is ``WIDE``.
        max_quote_age_days: Age of the snapshot's session, in calendar days,
            beyond which every reading is ``STALE_QUOTE``.
        program_date: The program's trading date.

    Returns:
        The reading. The IV is solved only from a two-sided, uncrossed
        quote: a mid built from a missing bid or ask, or from a bid above
        the ask, is not a price.

    """
    match = snapshot.match(
        expiry=expiry,
        option_type=option_type,
        strike=strike,
        max_spread_pct=max_spread_pct,
    )
    flags = set(match.flags)
    if (program_date - snapshot.session_date).days > max_quote_age_days:
        flags.add(MatchFlag.STALE_QUOTE)
    solved: float | None = None
    quote = match.quote
    if (
        quote is not None
        and MatchFlag.ZERO_BID not in flags
        and MatchFlag.NO_ASK not in flags
        and MatchFlag.CROSSED not in flags
    ):
        solved = solve_implied_vol(
            price=quote.mid,
            strike=quote.strike,
            expiry=quote.expiry,
            option_type=quote.option_type,
            spot=snapshot.spot,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
            valuation_date=snapshot.session_date,
        )
        if solved is None:
            flags.add(MatchFlag.NO_SOLVE)
    return ChainReading(
        label=label,
        quote=quote,
        solved_iv=solved,
        flags=frozenset(flags),
        session_date=snapshot.session_date,
        quoted_at=snapshot.quoted_at,
    )


@dataclass(frozen=True)
class FetchedChain:
    """The cached chain, or the plain reason there is none.

    Attributes:
        observation: The chain with its provenance, or ``None``.
        note: Why there is no chain (no ``pricing_feed`` section, nothing
            cached yet), or ``""`` when there is one.

    """

    observation: Observation[ChainSnapshot] | None
    note: str


def read_fetched_chain(
    provider: MarketDataProvider,
    ips_config: IpsConfig,
) -> FetchedChain:
    """Read the cached option chain for the program's instrument.

    Never raises. Without a ``pricing_feed`` section nothing is fetched, so
    nothing is read and the note says so; with one, a chain the refresh job
    has not yet cached (a cold cache, a failed run) is a note, not an error.

    Args:
        provider: The market-data provider (the app's read-only one).
        ips_config: The policy.

    Returns:
        The chain or the reason it is absent.

    """
    if ips_config.pricing_feed is None:
        return FetchedChain(
            None,
            "ips.yaml has no pricing_feed section, so no option chain is "
            "fetched and every pricing input is hand-entered.",
        )
    try:
        observation = provider.get_option_chain(ips_config.program.instrument)
    except MarketDataError:
        return FetchedChain(
            None,
            "No option chain is cached yet: the nightly refresh has not "
            "fetched one (or its last run failed).",
        )
    return FetchedChain(observation, "")


def read_positions(
    snapshot: ChainSnapshot,
    portfolio: OptionPortfolio,
    feed: IpsPricingFeed,
    *,
    program_date: date,
) -> dict[str, ChainReading]:
    """Read every held leg off the chain, at the book's own r and q.

    Args:
        snapshot: The parsed chain.
        portfolio: The live book.
        feed: The ``pricing_feed`` policy (spread and age limits).
        program_date: The program's trading date.

    Returns:
        ``position_id`` to reading, in book order. Labels are ``L1``,
        ``L2`` ... by book order.

    """
    return {
        position.position_id: read_contract(
            snapshot,
            label=f"L{index}",
            expiry=position.option.maturity_date.date(),
            option_type=position.option.option_type,
            strike=position.option.strike_price,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            max_spread_pct=feed.max_spread_pct,
            max_quote_age_days=feed.max_quote_age_days,
            program_date=program_date,
        )
        for index, position in enumerate(portfolio.positions, start=1)
    }


def rung_readings(  # pylint: disable=too-many-arguments
    snapshot: ChainSnapshot,
    ips_config: IpsConfig,
    feed: IpsPricingFeed,
    *,
    risk_free_rate: float,
    dividend_yield: float,
    program_date: date,
) -> tuple[ChainReading, ...]:
    """Read the IPS ``strike_ladder`` rungs off the chain.

    Each rung's strike is ``pct_otm`` below the snapshot's index level,
    snapped to the nearest listed strike; its expiry is the standard
    (``SPX``) expiry nearest the rung's tenor (``maturity_years``, else the
    program's ``entry_tenor_years``). A rung is a candidate the book does
    not hold, so this is how a roll candidate's quote is seen before the
    roll is sized.

    Args:
        snapshot: The parsed chain.
        ips_config: The policy (its ``strike_ladder`` and entry tenor).
        feed: The ``pricing_feed`` policy (spread and age limits).
        risk_free_rate: Continuously compounded rate, as a fraction.
        dividend_yield: Continuous dividend yield, as a fraction.
        program_date: The program's trading date.

    Returns:
        One reading per rung, in policy order; empty without a ladder.

    """
    ladder = ips_config.strike_ladder
    if ladder is None:
        return ()
    expiries = snapshot.expiries()
    readings: list[ChainReading] = []
    for rung in ladder.rungs:
        tenor = (
            rung.maturity_years
            if rung.maturity_years is not None
            else ips_config.maturity_selection.entry_tenor_years
        )
        label = f"{rung.pct_otm:g}% OTM, {tenor:g}y"
        target = snapshot.session_date + timedelta(
            days=round(tenor * const.DAYS_PER_YEAR),
        )
        if not expiries:
            readings.append(_absent(label, snapshot))
            continue
        expiry = _nearest_expiry(expiries, target)
        strikes = snapshot.listed_strikes(
            expiry=expiry,
            option_type=OptionType.PUT,
        )
        if not strikes:
            readings.append(_absent(label, snapshot))
            continue
        wanted = snapshot.spot * (1.0 - rung.pct_otm / 100.0)
        strike = min(strikes, key=_distance_to(wanted))
        readings.append(
            read_contract(
                snapshot,
                label=label,
                expiry=expiry,
                option_type=OptionType.PUT,
                strike=strike,
                risk_free_rate=risk_free_rate,
                dividend_yield=dividend_yield,
                max_spread_pct=feed.max_spread_pct,
                max_quote_age_days=feed.max_quote_age_days,
                program_date=program_date,
            ),
        )
    return tuple(readings)


def _nearest_expiry(expiries: Sequence[date], target: date) -> date:
    """Return the listed expiry closest to *target*."""
    return min(expiries, key=lambda day: abs((day - target).days))


def _distance_to(wanted: float) -> Callable[[float], float]:
    """Return a sort key: how far a strike is from *wanted*."""
    return lambda listed: abs(listed - wanted)


def _absent(label: str, snapshot: ChainSnapshot) -> ChainReading:
    """Return the reading for a rung the chain lists nothing for."""
    return ChainReading(
        label=label,
        quote=None,
        solved_iv=None,
        flags=frozenset({MatchFlag.ABSENT}),
        session_date=snapshot.session_date,
        quoted_at=snapshot.quoted_at,
    )
