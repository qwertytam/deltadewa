"""Price a candidate option on the market's smile, not a flat vol (9b).

A strike the book does not hold (a row of the strike grid, a sizing
workbench target, a ladder rung, the new strike a roll moves to) used to be
priced at the book's one flat IV, while the options the book *does* hold are
priced at the IV the chain implies for each. A roll was then sized on a
different basis from the options it replaces. :class:`ChainVolSource` reads
a candidate's IV off the same fetched chain, at the same rate and dividend
yield, so a candidate at a held strike and expiry gets exactly the held
leg's IV.

Rules, in order, and nothing is extrapolated:

1. **Exact.** The listed contract's own IV, solved from its close mid at the
   book's rate and yield (the same solve that prices a held leg).
2. **Between strikes.** On a listed expiry, linear in strike between the
   nearest listed contracts either side that have a usable quote.
3. **Between expiries.** On an expiry the chain does not list, each of the
   two listed expiries either side gives its IV at the strike (exact or
   between strikes), and the two are interpolated in **total variance**
   (``sigma^2 * T``), linear in time, the standard calendar interpolation.
4. **The book's flat volatility**, labelled ``BOOK_FLAT``, anywhere outside
   the listed range (a strike beyond the listed ones, an expiry before the
   first or after the last) or where a neighbour has no usable quote.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING, Final

from deltadewa.analysis.chain_quotes import read_contract
from deltadewa.portfolio.vol_quote import VolOrigin, VolQuote, VolSource

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from deltadewa.constants import OptionType
    from deltadewa.ips_config import IpsPricingFeed
    from deltadewa.marketdata.chain import ChainSnapshot

__all__ = [
    "ChainVolSource",
    "VolOrigin",
    "VolQuote",
    "VolSource",
    "vol_basis_note",
]

#: How many listed strikes either side to try before giving up on finding
#: one with a usable quote. The wings thin out; a long walk would reach a
#: strike so far from the candidate that interpolating to it means nothing.
_MAX_NEIGHBOURS: Final = 6

#: Two strikes closer than this are the same strike.
_STRIKE_TOLERANCE: Final = 1e-6

_DAYS_PER_YEAR: Final = 365.0

#: The origins that mean a candidate's IV was read off the fetched chain.
_CHAIN_ORIGINS: Final = frozenset(
    {VolOrigin.EXACT, VolOrigin.BETWEEN_STRIKES, VolOrigin.BETWEEN_EXPIRIES},
)

#: Words for each origin, in the order a reader should weigh them.
_ORIGIN_WORDS: Final[tuple[tuple[VolOrigin, str], ...]] = (
    (VolOrigin.EXACT, "at a listed contract"),
    (VolOrigin.BETWEEN_STRIKES, "between listed strikes"),
    (VolOrigin.BETWEEN_EXPIRIES, "between listed expiries"),
    (VolOrigin.OVERRIDE, "on your volatility override"),
    (VolOrigin.BOOK_FLAT, "on the book's flat volatility"),
)


class ChainVolSource:
    """Candidate volatilities read off one fetched option chain.

    Lazy and memoised: a contract's IV is solved the first time something
    asks for it, then remembered, so a strike grid or a delta solve that
    asks hundreds of times pays for each listed contract once. Safe to share
    between the app's request threads (a lost memo write only repeats a
    solve).
    """

    def __init__(  # pylint: disable=too-many-arguments
        self,
        snapshot: ChainSnapshot,
        *,
        risk_free_rate: float,
        dividend_yield: float,
        feed: IpsPricingFeed,
        program_date: date,
        book_vol: float,
    ) -> None:
        """Hold the chain and the inputs every IV is solved at.

        Args:
            snapshot: The parsed chain.
            risk_free_rate: The effective rate the book is priced at.
            dividend_yield: The effective yield the book is priced at.
            feed: The ``pricing_feed`` policy (spread and age limits).
            program_date: The book's valuation date, for the quote-age test.
            book_vol: The flat fallback volatility.

        """
        self._snapshot = snapshot
        self._risk_free_rate = risk_free_rate
        self._dividend_yield = dividend_yield
        self._feed = feed
        self._program_date = program_date
        self._book_vol = book_vol
        self._expiries = snapshot.expiries()
        self._solved_memo: dict[tuple[date, OptionType, float], float | None]
        self._solved_memo = {}
        self._listed_memo: dict[tuple[date, OptionType], tuple[float, ...]]
        self._listed_memo = {}

    def vol_for(
        self,
        *,
        strike: float,
        maturity: date,
        option_type: OptionType,
    ) -> VolQuote:
        """Return the volatility for a candidate contract.

        Args:
            strike: The candidate's strike in index points.
            maturity: Its expiry.
            option_type: Call or put.

        Returns:
            The IV and how it was decided; the book's flat volatility,
            labelled, when the chain cannot say.

        """
        if maturity in self._expiries:
            at_expiry = self._at_listed_expiry(maturity, option_type, strike)
            if at_expiry is not None:
                return VolQuote(*at_expiry)
        else:
            between = self._between_expiries(maturity, option_type, strike)
            if between is not None:
                return VolQuote(between, VolOrigin.BETWEEN_EXPIRIES)
        return VolQuote(self._book_vol, VolOrigin.BOOK_FLAT)

    # -- one listed expiry ------------------------------------------------

    def _listed_strikes(
        self,
        expiry: date,
        option_type: OptionType,
    ) -> tuple[float, ...]:
        key = (expiry, option_type)
        if key not in self._listed_memo:
            self._listed_memo[key] = self._snapshot.listed_strikes(
                expiry=expiry,
                option_type=option_type,
            )
        return self._listed_memo[key]

    def _solved(
        self,
        expiry: date,
        option_type: OptionType,
        strike: float,
    ) -> float | None:
        """Return a listed contract's IV, or ``None`` if it cannot be used."""
        key = (expiry, option_type, round(strike, 3))
        if key not in self._solved_memo:
            reading = read_contract(
                self._snapshot,
                label="candidate",
                expiry=expiry,
                option_type=option_type,
                strike=strike,
                risk_free_rate=self._risk_free_rate,
                dividend_yield=self._dividend_yield,
                max_spread_pct=self._feed.max_spread_pct,
                max_quote_age_days=self._feed.max_quote_age_days,
                program_date=self._program_date,
            )
            self._solved_memo[key] = (
                reading.solved_iv if reading.usable else None
            )
        return self._solved_memo[key]

    def _usable_neighbour(
        self,
        expiry: date,
        option_type: OptionType,
        candidates: Iterable[float],
    ) -> tuple[float, float] | None:
        """Return the first ``(strike, iv)`` among *candidates* with a quote."""
        for index, strike in enumerate(candidates):
            if index >= _MAX_NEIGHBOURS:
                return None
            iv = self._solved(expiry, option_type, strike)
            if iv is not None:
                return strike, iv
        return None

    def _at_listed_expiry(
        self,
        expiry: date,
        option_type: OptionType,
        strike: float,
    ) -> tuple[float, VolOrigin] | None:
        """Return the IV at *strike* on a listed expiry: exact, or between."""
        strikes = self._listed_strikes(expiry, option_type)
        if not strikes:
            return None
        if any(abs(listed - strike) <= _STRIKE_TOLERANCE for listed in strikes):
            exact = self._solved(expiry, option_type, strike)
            if exact is not None:
                return exact, VolOrigin.EXACT
        below = self._usable_neighbour(
            expiry,
            option_type,
            sorted(
                (k for k in strikes if k < strike - _STRIKE_TOLERANCE),
                reverse=True,
            ),
        )
        above = self._usable_neighbour(
            expiry,
            option_type,
            sorted(k for k in strikes if k > strike + _STRIKE_TOLERANCE),
        )
        if below is None or above is None:
            return None
        (low_strike, low_iv), (high_strike, high_iv) = below, above
        weight = (strike - low_strike) / (high_strike - low_strike)
        return low_iv + weight * (high_iv - low_iv), VolOrigin.BETWEEN_STRIKES

    # -- between two listed expiries --------------------------------------

    def _years(self, expiry: date) -> float:
        """Return years from the chain's own session to *expiry*.

        The chain's IVs are solved at its session date, so the same day
        count carries them into total variance and back out.
        """
        return (expiry - self._snapshot.session_date).days / _DAYS_PER_YEAR

    def _between_expiries(
        self,
        maturity: date,
        option_type: OptionType,
        strike: float,
    ) -> float | None:
        """Interpolate in total variance between the bracketing expiries."""
        earlier = [e for e in self._expiries if e < maturity]
        later = [e for e in self._expiries if e > maturity]
        if not earlier or not later:
            return None
        first, second = earlier[-1], later[0]
        near = self._at_listed_expiry(first, option_type, strike)
        far = self._at_listed_expiry(second, option_type, strike)
        if near is None or far is None:
            return None
        t_first, t_second = self._years(first), self._years(second)
        t_target = self._years(maturity)
        if not 0.0 < t_first < t_target < t_second:
            return None
        w_first = near[0] ** 2 * t_first
        w_second = far[0] ** 2 * t_second
        weight = (t_target - t_first) / (t_second - t_first)
        variance = w_first + weight * (w_second - w_first)
        if variance <= 0.0:
            return None
        return math.sqrt(variance / t_target)


def vol_basis_note(quotes: Iterable[VolQuote | None]) -> str | None:
    """Say, in one sentence, what the candidates in view were priced on.

    A panel that shows candidates priced on a surface must say so: the
    reader otherwise assumes the book's flat volatility, which is what the
    page said before the feed. Counts each origin, in the order that
    matters (a candidate at a listed contract is better grounded than one
    interpolated between expiries, which is better than the flat fallback).

    Args:
        quotes: One per candidate shown; ``None`` (a candidate with no
            recorded quote) is skipped.

    Returns:
        The sentence, or ``None`` when every candidate is on the book's flat
        volatility (nothing to say beyond what the page always said).

    """
    counts = Counter(q.origin for q in quotes if q is not None)
    if not counts or set(counts) == {VolOrigin.BOOK_FLAT}:
        return None
    if not set(counts) & _CHAIN_ORIGINS:
        # Only your override and/or the flat fallback: nothing came from the
        # chain, and saying "from the fetched chain" would be false.
        return "Candidates are priced on the volatility you entered."
    parts = [
        f"{counts[origin]} {words}"
        for origin, words in _ORIGIN_WORDS
        if counts[origin]
    ]
    return (
        "Candidates are priced from the fetched chain: "
        + "; ".join(parts)
        + "."
    )
