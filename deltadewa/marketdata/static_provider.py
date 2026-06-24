"""No-network MarketDataProvider backed by explicit/assumption values."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from deltadewa.marketdata._errors import MarketDataUnavailableError

if TYPE_CHECKING:
    from deltadewa.widgets.assumptions import GlobalAssumptions

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

    Default provider for tests and offline/notebook use — fully
    deterministic, performs no I/O.  ``assess_market_environment``
    returns ``DataQuality.STATIC`` for this provider via the
    ``data_quality_hint`` class attribute.

    Attributes:
        spot_prices: Mapping of symbol to spot price.
        vix: Current VIX level.
        vix_term_structure: VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels.
        skew_index: Current CBOE SKEW index level.
        skew_percentile: Fixed percentile rank returned by
            ``get_skew_percentile`` regardless of ``lookback_days``.

    """

    data_quality_hint: ClassVar[str] = "STATIC"

    spot_prices: dict[str, float] = field(default_factory=dict)
    vix: float = 16.0
    vix_term_structure: dict[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_VIX_TERM_STRUCTURE),
    )
    skew_index: float = 120.0
    skew_percentile: float = 0.5

    @classmethod
    def from_assumptions(
        cls,
        assumptions: GlobalAssumptions,
        symbol: str = "SPX",
    ) -> StaticProvider:
        """Build a provider from a ``GlobalAssumptions`` widget's values.

        Args:
            assumptions: Widget holding current market parameter values.
            symbol: Symbol to associate with ``assumptions.spot_price``.

        Returns:
            A ``StaticProvider`` seeded from the widget's current values.

        """
        return cls(spot_prices={symbol: assumptions.spot_price.value})

    def get_spot(self, symbol: str) -> float:
        """Return the spot price registered for *symbol*.

        Raises:
            MarketDataUnavailableError: If *symbol* has no registered price.

        """
        try:
            return self.spot_prices[symbol]
        except KeyError as exc:
            raise MarketDataUnavailableError(
                f"No spot price registered for symbol '{symbol}'",
            ) from exc

    def get_vix(self) -> float:
        """Return the current VIX level."""
        return self.vix

    def get_vix_term_structure(self) -> dict[str, float]:
        """Return VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels keyed by index name."""
        return dict(self.vix_term_structure)

    def get_skew_index(self) -> float:
        """Return the current CBOE SKEW index level."""
        return self.skew_index

    def get_skew_percentile(self, lookback_days: int = 252) -> float:
        """Return the fixed ``skew_percentile`` value.

        ``lookback_days`` is accepted for ``MarketDataProvider`` parity but
        is unused — ``StaticProvider`` holds a single static value.
        """
        _ = lookback_days
        return self.skew_percentile
