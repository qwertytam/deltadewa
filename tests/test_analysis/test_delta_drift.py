"""Tests for the delta-drift-vs-target metric (M1).

Delta drift is redefined as deviation from a stated target net-delta-to-equity
ratio (``IpsTriggers.target_delta_ratio_pct``) rather than distance from full
delta-neutrality. Unset ``underlying_quantity`` reports the metric unavailable
(``None``) instead of a fabricated ``0.0``.
"""

from types import SimpleNamespace
from unittest.mock import Mock

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.health import delta_drift_from_target


def _analyzer(net_delta: float, underlying_qty: float) -> PortfolioAnalyzer:
    """PortfolioAnalyzer over a mock whose summary_stats is crafted."""
    portfolio = Mock()
    portfolio.positions = []
    portfolio.volatility = 0.25
    portfolio.summary_stats.return_value = {
        "net_delta": net_delta,
        "underlying_quantity": underlying_qty,
        "total_theta": -10.0,
        "total_underlying_value": 10_000.0,
        "total_vega": 20.0,
        "total_portfolio_value": 20_000.0,
    }
    return PortfolioAnalyzer(portfolio)


class TestDeltaDriftFromTarget:
    """The single-sourced helper shared by the gauge and the trigger."""

    def test_at_target_reads_zero(self) -> None:
        """A book at exactly the target has zero drift."""
        assert delta_drift_from_target(90.0, 100.0, 90.0) == 0.0

    def test_under_hedged_is_positive(self) -> None:
        """More net long than target (less hedged) reads positive."""
        assert delta_drift_from_target(95.0, 100.0, 90.0) == 5.0

    def test_over_hedged_is_negative(self) -> None:
        """Less net long than target (more hedged) reads negative."""
        assert delta_drift_from_target(80.0, 100.0, 90.0) == -10.0

    def test_unset_underlying_is_none(self) -> None:
        """No equity position -> unavailable, never a fabricated 0.0."""
        assert delta_drift_from_target(0.0, 0.0, 90.0) is None

    def test_target_shifts_drift(self) -> None:
        """Same book, different target moves the drift by the difference."""
        assert delta_drift_from_target(97.0, 100.0, 90.0) == 7.0
        assert delta_drift_from_target(97.0, 100.0, 85.0) == 12.0


class TestCalculateDeltaDriftPct:
    """HealthMixin.calculate_delta_drift_pct delegates to the helper."""

    def test_measures_deviation_from_target(self) -> None:
        """Drift is the ratio minus the target, in percentage points."""
        assert _analyzer(95.0, 100.0).calculate_delta_drift_pct(90.0) == 5.0

    def test_at_target_reads_zero(self) -> None:
        """A book at target reads exactly 0.0."""
        assert _analyzer(90.0, 100.0).calculate_delta_drift_pct(90.0) == 0.0

    def test_unset_underlying_is_none(self) -> None:
        """Unset underlying_quantity returns None (unavailable)."""
        assert _analyzer(0.0, 0.0).calculate_delta_drift_pct(90.0) is None


class TestCalculateHealthMetricsThreadsTarget:
    """calculate_health_metrics threads the target like the crash scenario."""

    def test_threads_target_into_drift(self) -> None:
        """A supplied target drives delta_drift_pct."""
        metrics = _analyzer(95.0, 100.0).calculate_health_metrics(
            target_delta_ratio_pct=90.0,
        )
        assert metrics["delta_drift_pct"] == 5.0

    def test_none_target_reads_unavailable(self) -> None:
        """Without a target (no IPS), delta_drift_pct is None."""
        metrics = _analyzer(95.0, 100.0).calculate_health_metrics()
        assert metrics["delta_drift_pct"] is None


class TestOverallHealthScoreSkipsUnavailable:
    """The overall score ignores metrics reported unavailable."""

    def test_none_metric_excluded_from_score(self) -> None:
        """A None-actual metric contributes no score."""
        analyzer = PortfolioAnalyzer(Mock())
        metrics = {
            "unavailable": SimpleNamespace(
                actual=None,
                min_val=0.0,
                max_val=100.0,
                invert_colors=False,
            ),
            "good": SimpleNamespace(
                actual=100.0,
                min_val=0.0,
                max_val=100.0,
                invert_colors=False,
            ),
        }
        assert analyzer.calculate_overall_health_score(metrics) == 100.0

    def test_all_unavailable_returns_neutral(self) -> None:
        """With no scorable metrics the score falls back to neutral 50."""
        analyzer = PortfolioAnalyzer(Mock())
        metrics = {
            "unavailable": SimpleNamespace(
                actual=None,
                min_val=0.0,
                max_val=100.0,
                invert_colors=False,
            ),
        }
        assert analyzer.calculate_overall_health_score(metrics) == 50
