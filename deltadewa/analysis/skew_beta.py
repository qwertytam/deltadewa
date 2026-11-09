"""Skew beta: the book's value sensitivity to downside skew (Part X #9).

The handbook defines it as ``Skew Beta = ∂V/∂Skew``, with *Skew* "the
difference between OTM put volatility and ATM volatility" (`Skew Exposure
/ Beta <https://qwertytam.github.io/deltadewa-handbook/part-6/skew-exposure-beta/>`_).
This is the finite difference of exactly that, built by composition from
machinery the crash repricing already has — no new pricing:

- **Base:** :func:`~deltadewa.analysis.crash_repricing.hedge_value`, each
  live leg at today's spot and its own vol.
- **Bumped:** the same legs repriced through
  :func:`~deltadewa.analysis.crash_repricing.crash_skew_vol` with a one
  vol-point steepening and **no** spot move and **no** flat vol bump. That
  mapping adds the steepening exactly at each OTM put's own
  ``skew_reference_delta`` wing, linearly in log-moneyness up to zero at
  the money, and leaves calls and ITM puts alone — so it raises "OTM put
  vol - ATM vol" by one point at the anchor while holding spot and ATM
  vol fixed, which is the handbook's partial derivative.

The difference is reported in dollars per vol point and as a percent of
the protected book (the normalizer crash convexity uses).

**No band.** The handbook grades skew beta only qualitatively — "low" for
ATM puts, "moderate" for moderately OTM, "high" for deep-OTM tails — and
gives no number. So there is no IPS key and no verdict here, and a
surface rendering this must not call it high, low, strong or weak. The
handbook also warns it is a different dimension from skew *level* (the
skew percentile): "a hedge may have strong skew beta even when skew is
expensive."

**Not gated on fetched data quality.** Unlike the skew percentile, this
reads no market feed: its inputs are the book's own hand-entered leg
vols, already graded by the provenance ledger (#367).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from deltadewa.analysis.crash_repricing import (
    crash_skew_vol,
    hedge_value,
    partition_expired_legs,
)
from deltadewa.analysis.repricing import MarketShock, reprice_portfolio

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio

#: One vol point (decimal). The finite-difference step **and** the unit the
#: result is quoted in ("per +1 vol point"), the way vega is quoted per
#: point — a unit of measure, not a threshold or policy.
SKEW_BETA_BUMP_VOL: Final[float] = 0.01


@dataclass(frozen=True)
class SkewBeta:
    """The book's skew beta, ungraded.

    Attributes:
        dollars_per_vol_pt: Change in hedge-only option value (no
            underlying) when OTM-put-minus-ATM skew steepens by one vol
            point at the wing anchor. Signed: long puts gain, short puts
            lose.
        pct_of_protected_book: ``dollars_per_vol_pt`` as a percent of
            ``abs(underlying_quantity * spot)``, or ``None`` when the book
            has no underlying to normalize by.
        skew_reference_delta: The put-delta magnitude of the wing the bump
            was anchored at (the IPS ``convexity.skew_reference_delta``).
        excluded_expired: Expired legs left out of both valuations.

    """

    dollars_per_vol_pt: float
    pct_of_protected_book: float | None
    skew_reference_delta: float
    excluded_expired: int


def calculate_skew_beta(
    portfolio: OptionPortfolio,
    *,
    skew_reference_delta: float,
) -> SkewBeta | None:
    """Reprice the book with one vol point of extra downside skew.

    Args:
        portfolio: The live book.
        skew_reference_delta: Put-delta magnitude of the wing the bump is
            anchored to — **required**, never defaulted; pass the IPS
            ``convexity.skew_reference_delta`` so this measures at the
            same wing the crash gauge prices.

    Returns:
        The :class:`SkewBeta`, or ``None`` when the book holds no live
        option leg (nothing to measure — not a zero).

    """
    live_legs, expired = partition_expired_legs(
        portfolio.positions,
        valuation_date=portfolio.valuation_date,
    )
    if not live_legs:
        return None
    base = hedge_value(portfolio, positions=live_legs)
    bumped = reprice_portfolio(
        portfolio,
        shock=MarketShock(spot_shock=0.0, vol_shock=0.0),
        vol_mapping=crash_skew_vol(
            skew_steepening=SKEW_BETA_BUMP_VOL,
            skew_reference_delta=skew_reference_delta,
        ),
        positions=live_legs,
    )
    dollars = bumped - base
    book = abs(portfolio.underlying_quantity * portfolio.spot_price)
    return SkewBeta(
        dollars_per_vol_pt=dollars,
        pct_of_protected_book=dollars / book * 100 if book else None,
        skew_reference_delta=skew_reference_delta,
        excluded_expired=len(expired),
    )
