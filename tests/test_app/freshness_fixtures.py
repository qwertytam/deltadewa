"""Providers and books at a chosen freshness, for ``/health``'s #393 rule.

``StaticProvider`` — every other app test's provider — grades
``DataQuality.STATIC``, which #393 makes ``/health`` report as degraded.
That is the right verdict (a book priced on synthetic numbers is not a
healthy program), but it means a test that wants a genuinely healthy
endpoint needs two things this suite had no helper for:

- a provider whose observations carry a real ``Source`` and timestamps,
  so ``assess_market_environment`` can combine them to ``CACHED`` (or to
  whichever grade the test is pinning), and
- a book whose hand-entered pricing inputs are actually *stamped* —
  ``MarketParameterStamps`` defaults all three to ``None``, which the
  provenance ledger grades ``UNKNOWN`` rather than fresh (#367), so an
  unstamped book degrades ``/health`` no matter how good the feed is.

Both are seeded off the program clock (``tests/clock_helpers.py``), never
``datetime.now``, per CLAUDE.md's rule and #321/#343.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from deltadewa.marketdata import Observation, Source, StaticProvider
from tests.clock_helpers import days_from_today

if TYPE_CHECKING:
    from datetime import datetime

    from deltadewa.portfolio import OptionPortfolio


@dataclass
class GradedProvider(StaticProvider):
    """A ``StaticProvider`` whose observations carry a chosen ``Source``.

    Only the four series ``assess_market_environment`` actually combines
    are overridden — VIX, the term structure, the SKEW index and its
    percentile. ``get_spot``/``get_vix_history`` keep ``StaticProvider``'s
    own behaviour, since the environment's combined grade does not read
    them.

    Attributes:
        source: The ``Source`` every overridden observation carries.
            ``STATIC`` is rejected — it is what plain ``StaticProvider``
            already does, and ``Observation`` forbids the timestamps
            below on a ``STATIC`` reading.
        age_days: How many days back the observations' ``as_of`` sits.

    """

    source: Source = Source.CACHED
    age_days: int = 1

    def _observed(self, value: object) -> Observation[object]:
        stamp: datetime = days_from_today(-self.age_days)
        return Observation(
            value=value,
            source=self.source,
            as_of=stamp,
            fetched_at=stamp,
        )

    def get_vix(self) -> Observation[float]:
        """Return the VIX level at this provider's grade."""
        return self._observed(self.vix)  # type: ignore[return-value]

    def get_vix_term_structure(self) -> Observation[dict[str, float]]:
        """Return the term structure at this provider's grade."""
        return self._observed(  # type: ignore[return-value]
            dict(self.vix_term_structure),
        )

    def get_skew_index(self) -> Observation[float]:
        """Return the SKEW index at this provider's grade."""
        return self._observed(self.skew_index)  # type: ignore[return-value]

    def get_skew_percentile(
        self,
        lookback_days: int = 252,
    ) -> Observation[float]:
        """Return the fixed skew percentile at this provider's grade."""
        _ = lookback_days
        return self._observed(  # type: ignore[return-value]
            self.skew_percentile,
        )


def cached_provider(**kwargs: object) -> GradedProvider:
    """A provider grading ``CACHED`` — the healthy steady state."""
    return GradedProvider(
        spot_prices={"SPX": 5000.0},
        vix=18.0,
        source=Source.CACHED,
        **kwargs,  # type: ignore[arg-type]
    )


def stale_provider() -> GradedProvider:
    """A provider grading ``STALE`` — cache served, live fetch failed."""
    return GradedProvider(
        spot_prices={"SPX": 5000.0},
        vix=18.0,
        source=Source.STALE,
    )


def stamp_inputs(portfolio: OptionPortfolio, *, days_ago: int = 0) -> None:
    """Stamp every hand-entered pricing input *days_ago* days back.

    Goes through ``confirm_current_inputs`` — the same call
    ``ProgramState.mark_inputs_reviewed`` makes — rather than writing
    stamps onto the dataclass, so a test exercises the path an operator
    actually has.
    """
    portfolio.confirm_current_inputs(as_of=days_from_today(-days_ago))
