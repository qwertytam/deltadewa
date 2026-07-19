"""Tests for the vol-regime figure (Mo4).

The regime figure is a **true** percentile — the rank of the current implied
vol against the trailing VIX distribution — when history is available, and an
honestly-labelled min-max normalized figure otherwise. A normalized figure must
never be presented as a percentile it never computed.
"""

from unittest.mock import Mock

import pytest

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.health import (
    VOL_REGIME_LOOKBACK_DAYS,
    VolRegime,
    VolRegimeBasis,
    compute_vol_regime,
)
from deltadewa.ips_config import (
    DEFAULT_VOL_REGIME_HIGH,
    DEFAULT_VOL_REGIME_LOW,
)


def _analyzer(volatility: float) -> PortfolioAnalyzer:
    """PortfolioAnalyzer over a mock carrying just the vol the metric reads."""
    portfolio = Mock()
    portfolio.positions = []
    portfolio.volatility = volatility
    portfolio.summary_stats.return_value = {
        "net_delta": 0.0,
        "underlying_quantity": 100.0,
        "total_theta": -10.0,
        "total_underlying_value": 10_000.0,
        "total_vega": 20.0,
        "total_portfolio_value": 20_000.0,
    }
    return PortfolioAnalyzer(portfolio)


class TestComputeVolRegimePercentile:
    """A supplied VIX history yields a true percentile."""

    def test_known_series_gives_exact_percentile(self) -> None:
        """Rank is the fraction of history at or below current vol, x100."""
        # History in points -> decimals 0.10, 0.12, 0.14, 0.16, 0.18, 0.20.
        history = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]

        regime = compute_vol_regime(0.16, vix_history=history)

        # 0.10, 0.12, 0.14, 0.16 are <= 0.16 -> 4 of 6.
        assert regime.value == pytest.approx(4 / 6 * 100)
        assert regime.basis is VolRegimeBasis.PERCENTILE
        assert regime.lookback_days == VOL_REGIME_LOOKBACK_DAYS
        assert regime.sample_size == 6

    def test_current_vol_decimal_ranked_against_points_history(self) -> None:
        """Units differ: current is decimal, history is VIX points."""
        regime = compute_vol_regime(0.20, vix_history=[10.0, 20.0, 30.0])

        # decimals 0.10, 0.20, 0.30; <= 0.20 -> 2 of 3.
        assert regime.value == pytest.approx(2 / 3 * 100)

    def test_rank_is_inclusive_of_equal_values(self) -> None:
        """A current vol equal to a history point counts that point."""
        regime = compute_vol_regime(0.20, vix_history=[20.0, 20.0, 40.0])

        # Both 0.20s are <= 0.20 -> 2 of 3.
        assert regime.value == pytest.approx(2 / 3 * 100)

    def test_only_last_lookback_observations_are_ranked(self) -> None:
        """The window trims to the last *lookback_days* closes."""
        # Leading high closes (1.00 decimal) would drag the rank down if the
        # whole series were used; the window drops them.
        history = [100.0, 100.0, 100.0, 100.0, 100.0, 10.0, 10.0, 10.0]

        windowed = compute_vol_regime(
            0.15,
            vix_history=history,
            lookback_days=3,
        )
        full = compute_vol_regime(0.15, vix_history=history, lookback_days=99)

        assert windowed.value == pytest.approx(100.0)  # last 3 are 0.10 <= 0.15
        assert windowed.sample_size == 3
        assert full.value == pytest.approx(3 / 8 * 100)


class TestComputeVolRegimeNormalizedFallback:
    """No history -> an honest, labelled normalized figure."""

    def test_none_history_is_normalized(self) -> None:
        """A ``None`` history takes the labelled normalized fallback."""
        regime = compute_vol_regime(0.25, vix_history=None)

        assert regime.basis is VolRegimeBasis.NORMALIZED
        assert regime.lookback_days is None
        assert regime.sample_size is None

    def test_empty_history_is_normalized(self) -> None:
        """An empty history is treated the same as no history."""
        assert compute_vol_regime(0.25, vix_history=[]).basis is (
            VolRegimeBasis.NORMALIZED
        )

    def test_normalized_matches_min_max_endpoints(self) -> None:
        """Normalized figure is linear min-max, clamped to [0, 100]."""
        low, high = DEFAULT_VOL_REGIME_LOW, DEFAULT_VOL_REGIME_HIGH
        mid = (low + high) / 2

        assert compute_vol_regime(low - 0.05, vix_history=None).value == 0.0
        assert compute_vol_regime(low, vix_history=None).value == 0.0
        assert compute_vol_regime(mid, vix_history=None).value == pytest.approx(
            50.0,
        )
        assert compute_vol_regime(high, vix_history=None).value == 100.0
        assert compute_vol_regime(high + 0.05, vix_history=None).value == 100.0


class TestVolRegimeTypes:
    """Basis labels and the result dataclass."""

    def test_basis_string_values(self) -> None:
        """The enum serializes to the strings surfaced in the result dict."""
        assert VolRegimeBasis.PERCENTILE.value == "percentile"
        assert VolRegimeBasis.NORMALIZED.value == "normalized"

    def test_result_is_frozen(self) -> None:
        """VolRegime is an immutable value object."""
        regime = VolRegime(50.0, VolRegimeBasis.NORMALIZED, None, None)
        with pytest.raises(AttributeError):
            regime.value = 0.0  # type: ignore[misc]


class TestCalculateVolRegimePercentileMethod:
    """HealthMixin.calculate_vol_regime_percentile delegates to the core."""

    def test_history_gives_percentile_value(self) -> None:
        """With history, the method returns the true-percentile value."""
        value = _analyzer(0.16).calculate_vol_regime_percentile(
            vix_history=[10.0, 12.0, 14.0, 16.0, 18.0, 20.0],
        )
        assert value == pytest.approx(4 / 6 * 100)

    def test_no_history_returns_normalized_value(self) -> None:
        """Without history, the method returns the normalized figure."""
        value = _analyzer(0.25).calculate_vol_regime_percentile()
        assert value == pytest.approx(50.0)


class TestCalculateHealthMetricsSurfacesBasis:
    """calculate_health_metrics distinguishes percentile from normalized."""

    def test_history_labels_percentile_with_lookback(self) -> None:
        """Supplied history -> basis 'percentile' and a set lookback window."""
        metrics = _analyzer(0.16).calculate_health_metrics(
            vix_history=[10.0, 12.0, 14.0, 16.0, 18.0, 20.0],
        )

        assert metrics["vol_regime_basis"] == "percentile"
        assert metrics["vol_regime_lookback_days"] == VOL_REGIME_LOOKBACK_DAYS
        assert metrics["vol_regime_percentile"] == pytest.approx(4 / 6 * 100)

    def test_no_history_labels_normalized_with_no_lookback(self) -> None:
        """No history -> basis 'normalized' and no lookback window."""
        metrics = _analyzer(0.25).calculate_health_metrics()

        assert metrics["vol_regime_basis"] == "normalized"
        assert metrics["vol_regime_lookback_days"] is None
        assert metrics["vol_regime_percentile"] == pytest.approx(50.0)
