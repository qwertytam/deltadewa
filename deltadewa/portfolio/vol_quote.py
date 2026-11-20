"""The volatility a *candidate* option is priced at, and where it came from.

A held option carries its own IV. A candidate (a strike the book does not
hold yet: the strike grid, the sizing workbench, the ladder composer, the
cost of a roll) has none, and was priced at the book's single flat
volatility. With a fetched option chain it can be read off the market's own
smile instead, and a reader must be told which: an IV read at a listed
contract is not an IV interpolated between two, and neither is the flat
fallback outside the listed range.

This module is only the vocabulary, with no pricing in it, so the portfolio
layer can carry a source without importing the analysis layer above it
(``deltadewa.analysis.vol_source`` is the chain-backed implementation).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import date

    from deltadewa.constants import OptionType

__all__ = ["VolOrigin", "VolQuote", "VolSource"]


class VolOrigin(StrEnum):
    """How a candidate's volatility was decided."""

    EXACT = "EXACT"
    """The listed contract's own IV."""
    BETWEEN_STRIKES = "BETWEEN_STRIKES"
    """Interpolated linearly in strike between two listed contracts."""
    BETWEEN_EXPIRIES = "BETWEEN_EXPIRIES"
    """Interpolated in total variance between two listed expiries."""
    BOOK_FLAT = "BOOK_FLAT"
    """The book's flat volatility: outside the listed range, or no feed."""
    OVERRIDE = "OVERRIDE"
    """A volatility you typed into the workbench."""


@dataclass(frozen=True)
class VolQuote:
    """A candidate's volatility and where it came from.

    Attributes:
        vol: The implied volatility as a fraction.
        origin: How it was decided.

    """

    vol: float
    origin: VolOrigin


class VolSource(Protocol):
    """Anything that can say what volatility a candidate option trades at."""

    def vol_for(
        self,
        *,
        strike: float,
        maturity: date,
        option_type: OptionType,
    ) -> VolQuote:
        """Return the volatility for a candidate contract."""
        ...
