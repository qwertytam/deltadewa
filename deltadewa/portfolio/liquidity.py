"""Liquidity observations for one option leg (8c, N10; 9b).

Part X #12 Liquidity Risk needs per-strike bid/ask and open interest. The
first source (8c) was the operator's own observation at the moments the
handbook says liquidity matters: "monetizing hedges during crashes,
rolling positions, scaling hedge size" (`Tier 4 §12
<https://qwertytam.github.io/deltadewa-handbook/part-10/tier-4-tactical-optional-trading-metrics/>`_).
The second (9b) is the nightly option-chain fetch, for every held leg.

What an observation is
    A point-in-time quote the operator read off their broker for **this
    leg's contract** — bid, ask, and (if they had it) open interest —
    stamped with when they read it. It is a fact about that moment, not
    about now. ``analysis.liquidity`` grades its spread against IPS
    policy and its age against the same review-cadence rule #367 applies
    to every other hand-entered input.

What it is not
    A liquidity feed. It cannot see a strike the book does not hold,
    depth behind the quote, traded volume, or a spread that has widened
    since it was read. When ``ips.yaml`` has a ``pricing_feed`` section the
    nightly chain fetch adds a second kind of observation for each held
    leg (``source=FETCHED``), derived at read time and never stored; see
    ``docs/market-data.md``, "Liquidity".

When it is (and isn't) set
    Only by ``OptionPortfolioBase.record_liquidity`` — an explicit
    operator act. Unlike a confirmation stamp
    (``deltadewa.portfolio.stamps``), an observation *is* the data, so
    ``confirm_current_inputs`` ("mark inputs reviewed") never touches it:
    re-confirming spot does not re-read a bid/ask. The import path
    restores whatever was serialized, never re-stamping. An edit that
    changes the leg's contract (strike, maturity, type, or exercise
    style) discards the observation — it described a different contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class LiquiditySource(StrEnum):
    """Who read a quote."""

    OPERATOR = "OPERATOR"
    """Typed in by the operator from their broker; the only kind ever
    persisted with the book."""
    FETCHED = "FETCHED"
    """Derived from the nightly option-chain fetch (9b) at read time for
    a held leg; never stored, so it can never overwrite an operator quote
    or put a nightly write on the book."""


@dataclass(frozen=True)
class LiquidityObservation:
    """One operator-read quote for a leg's contract.

    Attributes:
        bid: Per-share bid when observed. ``0.0`` is legal — a no-bid
            contract is the strongest liquidity warning there is.
        ask: Per-share ask when observed. Must be positive and not below
            the bid (a crossed quote is a typing error, not a market).
        open_interest: Contracts of open interest, or ``None`` when the
            operator recorded the quote without it.
        observed_at: When the quote was read: by the operator, or (for a
            fetched quote) the close of the trading session it belongs to.
        source: Who read it. Defaults to the operator, which is what every
            quote written to the book is.

    Raises:
        ValueError: On a negative bid, a non-positive ask, a crossed
            quote, or negative open interest.

    """

    bid: float
    ask: float
    open_interest: int | None
    observed_at: datetime
    source: LiquiditySource = LiquiditySource.OPERATOR

    def __post_init__(self) -> None:
        """Reject a quote no market could have shown."""
        if self.bid < 0:
            raise ValueError(f"bid must be >= 0, got {self.bid}")
        if self.ask <= 0:
            raise ValueError(f"ask must be > 0, got {self.ask}")
        if self.ask < self.bid:
            raise ValueError(
                f"crossed quote: ask {self.ask} is below bid {self.bid}",
            )
        if self.open_interest is not None and self.open_interest < 0:
            raise ValueError(
                f"open interest must be >= 0, got {self.open_interest}",
            )

    @property
    def mid(self) -> float:
        """Midpoint of the observed quote."""
        return (self.bid + self.ask) / 2

    @property
    def spread_pct(self) -> float:
        """Bid-ask spread as a percent of mid — the handbook's ``Spread %``.

        ``(Ask - Bid) / Mid * 100`` (Tier 4 §12). A no-bid quote reads
        ``200.0``: honestly as wide as a spread can be.
        """
        return (self.ask - self.bid) / self.mid * 100
