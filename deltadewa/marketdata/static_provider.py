"""No-network MarketDataProvider backed by explicit/assumption values."""

from __future__ import annotations

from dataclasses import dataclass, field

from deltadewa.marketdata._errors import MarketDataUnavailableError
from deltadewa.marketdata._observation import Observation

_DEFAULT_VIX_TERM_STRUCTURE = {
    "VIX9D": 15.5,
    "VIX": 16.0,
    "VIX3M": 17.0,
    "VIX6M": 17.5,
    "VIX1Y": 18.0,
}


@dataclass
class StaticProvider:
    """No-network ``MarketDataProvider`` backed by explicit values.

    Default provider for tests and offline use — fully
    deterministic, performs no I/O. Every value is returned as a
    ``Source.STATIC`` ``Observation`` with no timestamps: a synthetic number
    has no observation date, and saying so is the honest answer rather than a
    gap that could read as "unknown but probably fine".

    Attributes:
        spot_prices: Mapping of symbol to spot price.
        vix: Current VIX level.
        vix_term_structure: VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels.
        skew_index: Current CBOE SKEW index level.
        skew_percentile: Fixed percentile rank returned by
            ``get_skew_percentile`` regardless of ``lookback_days``.
        vix_history: Optional VIX close history in vol points, oldest first.
            Empty by default — the offline provider carries no history, so
            ``get_vix_history`` raises and vol-regime callers fall back to a
            (labelled) normalized figure rather than a fabricated percentile.
            Tests can inject a series to exercise the true-percentile path.

    """

    spot_prices: dict[str, float] = field(default_factory=dict)
    vix: float = 16.0
    vix_term_structure: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_VIX_TERM_STRUCTURE),
    )
    skew_index: float = 120.0
    skew_percentile: float = 0.5
    vix_history: list[float] = field(default_factory=list)

    @property
    def is_read_only(self) -> bool:
        """Always ``True`` — ``StaticProvider`` performs no I/O at all."""
        return True

    def get_spot(self, symbol: str) -> Observation[float]:
        """Return the spot price registered for *symbol*.

        Raises:
            MarketDataUnavailableError: If *symbol* has no registered price.

        """
        try:
            return Observation.static(self.spot_prices[symbol])
        except KeyError as exc:
            raise MarketDataUnavailableError(
                f"No spot price registered for symbol '{symbol}'",
            ) from exc

    def get_vix(self) -> Observation[float]:
        """Return the current VIX level."""
        return Observation.static(self.vix)

    def get_vix_history(
        self,
        lookback_days: int = 252,
    ) -> Observation[list[float]]:
        """Return the last *lookback_days* of injected ``vix_history``.

        Raises:
            MarketDataUnavailableError: If no ``vix_history`` was registered —
                the default offline case, which signals vol-regime callers to
                fall back to a labelled normalized figure.

        """
        if not self.vix_history:
            raise MarketDataUnavailableError("No VIX history registered")
        return Observation.static(list(self.vix_history[-lookback_days:]))

    def get_vix_term_structure(self) -> Observation[dict[str, float]]:
        """Return VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels keyed by index name."""
        return Observation.static(dict(self.vix_term_structure))

    def get_skew_index(self) -> Observation[float]:
        """Return the current CBOE SKEW index level."""
        return Observation.static(self.skew_index)

    def get_skew_percentile(
        self,
        lookback_days: int = 252,
    ) -> Observation[float]:
        """Return the fixed ``skew_percentile`` value.

        ``lookback_days`` is accepted for ``MarketDataProvider`` parity but
        is unused — ``StaticProvider`` holds a single static value.
        """
        _ = lookback_days
        return Observation.static(self.skew_percentile)
