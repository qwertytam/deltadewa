"""Tests for deltadewa.analysis.health module.

Direct unit tests for the HealthMixin gauge metrics, covering the three
zero-reference functions (calculate_vega_sufficiency_pct,
calculate_hedge_success_pct, calculate_convexity_cliff_days) and the
remaining wrapper methods. Uses the established _analyzer() Mock-portfolio
pattern from test_vol_regime.py / test_delta_ratio_deviation.py.

Note: calculate_net_carry_pct, calculate_delta_ratio_deviation_pct,
calculate_crash_convexity_pct, and compute_vol_regime have existing
coverage elsewhere (test_delta_ratio_deviation.py, test_vol_regime.py,
test_crash_single_source.py, test_crash_repricing.py); this file adds
boundary and degenerate cases not yet covered, plus full normal/boundary
/degenerate suites for the three uncovered functions.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deltadewa import constants as const
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.health import (
    VolRegimeBasis,
    compute_vol_regime,
)
from deltadewa.constants import OptionType
from deltadewa.ips_config import (
    DEFAULT_VOL_REGIME_HIGH,
    DEFAULT_VOL_REGIME_LOW,
)


def _analyzer(**stats_overrides: float) -> PortfolioAnalyzer:
    """PortfolioAnalyzer over a mock with customizable summary_stats.

    Args:
        stats_overrides: Keys/values to override in the default
            summary_stats dict (e.g., net_delta=95.0).

    Returns:
        PortfolioAnalyzer wrapping a Mock portfolio.
    """
    portfolio = Mock()
    portfolio.positions = []
    portfolio.volatility = 0.25
    portfolio.spot_price = 100.0
    portfolio.summary_stats.return_value = {
        "net_delta": 0.0,
        "underlying_quantity": 100.0,
        "total_theta": -10.0,
        "total_underlying_value": 10_000.0,
        "total_vega": 20.0,
        "total_portfolio_value": 20_000.0,
        **stats_overrides,
    }
    return PortfolioAnalyzer(portfolio)


class TestCalculateVegaSufficiencyPct:
    """Zero-reference: vega sufficiency as portfolio % per vol shock."""

    def test_positive_vega_yields_positive_pct(self) -> None:
        """Long-vega position (positive vega) → positive pct."""
        analyzer = _analyzer(total_vega=100.0)
        result = analyzer.calculate_vega_sufficiency_pct(vol_shock_points=10.0)
        assert result == pytest.approx(5.0)  # 100 * 10 / 20_000 * 100

    def test_negative_vega_yields_negative_pct(self) -> None:
        """Short-vega position (negative vega) → negative pct."""
        analyzer = _analyzer(total_vega=-50.0)
        result = analyzer.calculate_vega_sufficiency_pct(vol_shock_points=10.0)
        assert result == pytest.approx(-2.5)  # -50 * 10 / 20_000 * 100

    def test_vol_shock_points_param_scales_linearly(self) -> None:
        """Non-default vol_shock_points scales the result linearly."""
        analyzer = _analyzer(total_vega=100.0)

        result_5pts = analyzer.calculate_vega_sufficiency_pct(
            vol_shock_points=5.0
        )
        result_20pts = analyzer.calculate_vega_sufficiency_pct(
            vol_shock_points=20.0
        )

        assert result_5pts == pytest.approx(2.5)
        assert result_20pts == pytest.approx(10.0)
        assert result_20pts == pytest.approx(result_5pts * 4.0)

    def test_boundary_at_dashboard_threshold_positive(self) -> None:
        """Result landing exactly at +20.0 pct (dashboard max_val).

        vega_needed = 20.0 * portfolio_value / 100 / vol_shock_points
        = 20.0 * 20_000 / 100 / 10.0 = 400.0
        """
        analyzer = _analyzer(total_vega=400.0)
        result = analyzer.calculate_vega_sufficiency_pct(vol_shock_points=10.0)
        assert result == pytest.approx(20.0)

    def test_boundary_at_dashboard_threshold_negative(self) -> None:
        """Result landing exactly at -20.0 pct (dashboard min_val)."""
        # min_val from health_dashboard.py: -20.0 pct
        analyzer = _analyzer(total_vega=-400.0)
        result = analyzer.calculate_vega_sufficiency_pct(vol_shock_points=10.0)
        assert result == pytest.approx(-20.0)

    def test_zero_portfolio_value_returns_zero(self) -> None:
        """portfolio_value == 0 → returns 0.0 (current behavior).

        NOTE: This is inconsistent with calculate_net_carry_pct /
        calculate_delta_ratio_deviation_pct, which return None when the
        denominator is unset. Returning a literal 0.0 here vs None there is
        a known inconsistency not addressed in this scope — this test pins
        the current contract.
        """
        analyzer = _analyzer(total_vega=100.0, total_portfolio_value=0.0)
        result = analyzer.calculate_vega_sufficiency_pct(vol_shock_points=10.0)
        assert result == pytest.approx(0.0, rel=1e-8)


class TestCalculateHedgeSuccessPct:
    """Zero-reference: hedge P&L vs carry paid (M2.4 placeholder, issue #70).

    This class characterizes the CURRENT proxy behavior as of M2.4's planning
    date. The gauge uses a simplified measure: portfolio PnL at the crash
    spot divided by carry paid, via calculate_pnl_at_expiry(...,
    include_underlying=True). This is NOT a validated hedge-success formula;
    it is pending real carry/P&L tracking in M2.4 (issue #70 / docs/
    implementation-plan.md). Tests document the current contract, not the
    correctness of the proxy.

    See: deltadewa/analysis/health.py:365-406, issue #70.
    """

    def test_normal_case_formula(self) -> None:
        """Formula applies: (hedge_pnl / carry_paid) * 100."""
        portfolio = Mock()
        portfolio.spot_price = 100.0
        portfolio.summary_stats.return_value = {
            "underlying_quantity": 100.0,
        }
        # Mock calculate_pnl_at_expiry to return a known value.
        portfolio.calculate_pnl_at_expiry.return_value = 500.0

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_hedge_success_pct(
            cumulative_carry_paid=100.0,
            crash_scenario_pct=-25.0,
        )

        # Verify the crash_spot is computed as spot * (1 + pct/100)
        # = 100.0 * (1 + -25.0/100) = 75.0
        portfolio.calculate_pnl_at_expiry.assert_called_once_with(
            75.0,
            include_underlying=True,
        )
        # 500.0 / 100.0 * 100 = 500.0
        assert result == pytest.approx(500.0)

    def test_include_underlying_is_true_in_call(self) -> None:
        """Methodological choice: include_underlying=True in the PnL call."""
        portfolio = Mock()
        portfolio.spot_price = 100.0
        portfolio.calculate_pnl_at_expiry.return_value = 1000.0

        analyzer = PortfolioAnalyzer(portfolio)
        analyzer.calculate_hedge_success_pct(
            cumulative_carry_paid=100.0,
            crash_scenario_pct=-20.0,
        )

        # The include_underlying must be True (passed as kwarg).
        call_args = portfolio.calculate_pnl_at_expiry.call_args
        assert call_args.kwargs.get("include_underlying") is True

    def test_crash_scenario_pct_to_spot_conversion(self) -> None:
        """crash_scenario_pct is converted: crash_spot = spot*(1+pct/100)."""
        portfolio = Mock()
        portfolio.spot_price = 200.0
        portfolio.calculate_pnl_at_expiry.return_value = 100.0

        analyzer = PortfolioAnalyzer(portfolio)
        analyzer.calculate_hedge_success_pct(
            cumulative_carry_paid=50.0,
            crash_scenario_pct=-30.0,
        )

        # crash_spot = 200.0 * (1 + -30.0/100) = 200 * 0.7 = 140.0
        portfolio.calculate_pnl_at_expiry.assert_called_once_with(
            140.0,
            include_underlying=True,
        )

    def test_boundary_at_zero_carry_cutoff(self) -> None:
        """Literal < 0.01 cutoff: at 0.009999 it short-circuits to 0.0."""
        portfolio = Mock()
        portfolio.spot_price = 100.0

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_hedge_success_pct(
            cumulative_carry_paid=0.009999,
            crash_scenario_pct=-25.0,
        )

        # Short-circuit before calling calculate_pnl_at_expiry.
        portfolio.calculate_pnl_at_expiry.assert_not_called()
        assert result == pytest.approx(0.0, rel=1e-8)

    def test_boundary_at_exactly_zero_point_zero_one_carry(self) -> None:
        """At carry == 0.01 exactly, the normal path runs."""
        portfolio = Mock()
        portfolio.spot_price = 100.0
        portfolio.calculate_pnl_at_expiry.return_value = 200.0

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_hedge_success_pct(
            cumulative_carry_paid=0.01,
            crash_scenario_pct=-25.0,
        )

        portfolio.calculate_pnl_at_expiry.assert_called_once()
        # (200.0 / 0.01) * 100 = 2_000_000.0
        assert result == pytest.approx(2_000_000.0)

    def test_degenerate_zero_carry_paid_returns_zero(self) -> None:
        """cumulative_carry_paid == 0.0 → 0.0 (documented contract)."""
        portfolio = Mock()
        portfolio.spot_price = 100.0

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_hedge_success_pct(
            cumulative_carry_paid=0.0,
            crash_scenario_pct=-25.0,
        )

        # Short-circuit before calling calculate_pnl_at_expiry.
        portfolio.calculate_pnl_at_expiry.assert_not_called()
        assert result == pytest.approx(0.0, rel=1e-8)


class TestCalculateConvexityCliffDays:
    """Zero-reference: days until long puts hit high-gamma region."""

    def test_normal_single_long_put(self) -> None:
        """A single long put at 200 days to maturity, threshold=180."""
        valuation = datetime(2026, 1, 1, tzinfo=UTC)
        maturity = valuation + timedelta(days=200)

        pos = SimpleNamespace(
            option=SimpleNamespace(
                option_type=OptionType.PUT,
                maturity_date=maturity,
            ),
            quantity=1,  # long
        )

        portfolio = Mock()
        portfolio.positions = [pos]
        portfolio.valuation_date = valuation

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_convexity_cliff_days(
            cliff_threshold_days=180
        )

        # 200 days to maturity, threshold 180 → cliff_until = 200 - 180 = 20
        assert result == 20

    def test_multiple_long_puts_picks_minimum(self) -> None:
        """Multiple long puts → picks the minimum days_until_cliff."""
        valuation = datetime(2026, 1, 1, tzinfo=UTC)

        positions = [
            SimpleNamespace(
                option=SimpleNamespace(
                    option_type=OptionType.PUT,
                    maturity_date=valuation + timedelta(days=200),
                ),
                quantity=1,
            ),
            SimpleNamespace(
                option=SimpleNamespace(
                    option_type=OptionType.PUT,
                    maturity_date=valuation + timedelta(days=150),
                ),
                quantity=2,
            ),
            SimpleNamespace(
                option=SimpleNamespace(
                    option_type=OptionType.PUT,
                    maturity_date=valuation + timedelta(days=300),
                ),
                quantity=1,
            ),
        ]

        portfolio = Mock()
        portfolio.positions = positions
        portfolio.valuation_date = valuation

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_convexity_cliff_days(
            cliff_threshold_days=180
        )

        # 150 days → -30 clamped to 0; 200 days → 20; 300 days → 120
        # Min is 0
        assert result == 0

    def test_excludes_short_puts(self) -> None:
        """Short puts (quantity <= 0) are excluded."""
        valuation = datetime(2026, 1, 1, tzinfo=UTC)

        positions = [
            SimpleNamespace(
                option=SimpleNamespace(
                    option_type=OptionType.PUT,
                    maturity_date=valuation + timedelta(days=200),
                ),
                quantity=-1,  # short
            ),
        ]

        portfolio = Mock()
        portfolio.positions = positions
        portfolio.valuation_date = valuation

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_convexity_cliff_days(
            cliff_threshold_days=180
        )

        # No long puts → sentinel 999
        assert result == 999

    def test_excludes_calls(self) -> None:
        """Calls (long or short) are excluded."""
        valuation = datetime(2026, 1, 1, tzinfo=UTC)

        positions = [
            SimpleNamespace(
                option=SimpleNamespace(
                    option_type=OptionType.CALL,
                    maturity_date=valuation + timedelta(days=200),
                ),
                quantity=1,  # long call
            ),
        ]

        portfolio = Mock()
        portfolio.positions = positions
        portfolio.valuation_date = valuation

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_convexity_cliff_days(
            cliff_threshold_days=180
        )

        # No long puts → sentinel 999
        assert result == 999

    def test_boundary_exactly_at_cliff_threshold(self) -> None:
        """Position exactly at threshold days: cliff_until = 0."""
        valuation = datetime(2026, 1, 1, tzinfo=UTC)

        pos = SimpleNamespace(
            option=SimpleNamespace(
                option_type=OptionType.PUT,
                maturity_date=valuation + timedelta(days=180),
            ),
            quantity=1,
        )

        portfolio = Mock()
        portfolio.positions = [pos]
        portfolio.valuation_date = valuation

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_convexity_cliff_days(
            cliff_threshold_days=180
        )

        # 180 days → 180 - 180 = 0
        assert result == 0

    def test_boundary_inside_cliff_threshold_clamped_to_zero(self) -> None:
        """Position inside threshold (days < threshold) → clamped to 0."""
        valuation = datetime(2026, 1, 1, tzinfo=UTC)

        pos = SimpleNamespace(
            option=SimpleNamespace(
                option_type=OptionType.PUT,
                maturity_date=valuation + timedelta(days=150),
            ),
            quantity=1,
        )

        portfolio = Mock()
        portfolio.positions = [pos]
        portfolio.valuation_date = valuation

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_convexity_cliff_days(
            cliff_threshold_days=180
        )

        # 150 days → 150 - 180 = -30, clamped to 0
        assert result == 0

    def test_custom_cliff_threshold_honored(self) -> None:
        """Non-default cliff_threshold_days changes the boundary."""
        valuation = datetime(2026, 1, 1, tzinfo=UTC)

        pos = SimpleNamespace(
            option=SimpleNamespace(
                option_type=OptionType.PUT,
                maturity_date=valuation + timedelta(days=100),
            ),
            quantity=1,
        )

        portfolio = Mock()
        portfolio.positions = [pos]
        portfolio.valuation_date = valuation

        analyzer = PortfolioAnalyzer(portfolio)

        # With default 180: 100 - 180 = -80 → 0
        result_default = analyzer.calculate_convexity_cliff_days()
        assert result_default == 0

        # With custom 90: 100 - 90 = 10
        result_custom = analyzer.calculate_convexity_cliff_days(
            cliff_threshold_days=90
        )
        assert result_custom == 10

    def test_degenerate_no_positions_returns_sentinel(self) -> None:
        """No positions → sentinel 999."""
        portfolio = Mock()
        portfolio.positions = []
        portfolio.valuation_date = datetime(2026, 1, 1, tzinfo=UTC)

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_convexity_cliff_days()

        assert result == 999

    def test_degenerate_all_calls_returns_sentinel(self) -> None:
        """Only calls (no long puts) → sentinel 999."""
        valuation = datetime(2026, 1, 1, tzinfo=UTC)

        positions = [
            SimpleNamespace(
                option=SimpleNamespace(
                    option_type=OptionType.CALL,
                    maturity_date=valuation + timedelta(days=100),
                ),
                quantity=1,
            ),
            SimpleNamespace(
                option=SimpleNamespace(
                    option_type=OptionType.CALL,
                    maturity_date=valuation + timedelta(days=200),
                ),
                quantity=-1,
            ),
        ]

        portfolio = Mock()
        portfolio.positions = positions
        portfolio.valuation_date = valuation

        analyzer = PortfolioAnalyzer(portfolio)
        result = analyzer.calculate_convexity_cliff_days()

        assert result == 999


class TestCalculateDeltaRatioDeviationPct:
    """Delta ratio deviation wrapper + boundary/degenerate complement.

    Complements test_delta_ratio_deviation with wrapper-level stats
    plumbing and IPS threshold boundaries not covered elsewhere.
    """

    def test_wrapper_reads_summary_stats(self) -> None:
        """Wrapper correctly reads net_delta/underlying_qty from stats."""
        analyzer = _analyzer(net_delta=95.0, underlying_quantity=100.0)
        result = analyzer.calculate_delta_ratio_deviation_pct(
            target_delta_ratio_pct=90.0
        )
        assert result == pytest.approx(5.0)

    def test_boundary_at_delta_ratio_deviation_warn_pct(self) -> None:
        """Result landing exactly at IPS warn threshold (5.0 pp).

        IPS value from the retired Jupyter setup suite (#279).
        drift = net_delta / underlying * 100 - target
        For drift = 5.0: net_delta/underlying*100 = target + 5
        If target=90, then net_delta/100*100 = 95
        """
        analyzer = _analyzer(net_delta=95.0, underlying_quantity=100.0)
        result = analyzer.calculate_delta_ratio_deviation_pct(
            target_delta_ratio_pct=90.0
        )
        assert result == pytest.approx(5.0)

    def test_boundary_at_delta_ratio_deviation_action_pct(self) -> None:
        """Result landing exactly at IPS action threshold (10.0 pp)."""
        # If target=90, then net_delta/100*100 = 100 for drift=10
        analyzer = _analyzer(net_delta=100.0, underlying_quantity=100.0)
        result = analyzer.calculate_delta_ratio_deviation_pct(
            target_delta_ratio_pct=90.0
        )
        assert result == pytest.approx(10.0)

    def test_degenerate_zero_underlying_quantity_returns_none(self) -> None:
        """underlying_quantity == 0 → None (metric unavailable)."""
        analyzer = _analyzer(
            net_delta=50.0,
            underlying_quantity=0.0,
        )
        result = analyzer.calculate_delta_ratio_deviation_pct(
            target_delta_ratio_pct=90.0
        )
        assert result is None


class TestCalculateNetCarryPct:
    """Theta/carry wrapper + boundary complement to
    test_delta_ratio_deviation."""

    def test_normal_positive_theta_positive_carry_pct(self) -> None:
        """Positive theta (earning carry) → positive pct."""
        # Carry pct = (theta * DAYS_PER_YEAR / underlying_value) * 100
        # DAYS_PER_YEAR = 365; theta=10, underlying=10_000
        # → (10*365/10_000)*100 = 36.5
        analyzer = _analyzer(
            total_theta=10.0,
            total_underlying_value=10_000.0,
        )
        result = analyzer.calculate_net_carry_pct()
        assert result == pytest.approx(36.5)

    def test_normal_negative_theta_negative_carry_pct(self) -> None:
        """Negative theta (paying carry) → negative pct."""
        analyzer = _analyzer(
            total_theta=-10.0,
            total_underlying_value=10_000.0,
        )
        result = analyzer.calculate_net_carry_pct()
        # DAYS_PER_YEAR = 365: (-10*365/10_000)*100 = -36.5
        assert result == pytest.approx(-36.5)

    def test_boundary_at_ips_theta_cost_acceptable_pct(self) -> None:
        """Result landing exactly at IPS acceptable threshold (2.0 pct).

        Note: This threshold is consumed downstream by hedge_triggers.py,
        not by calculate_net_carry_pct itself, but the crossing is the
        policy-meaningful point to pin.

        IPS theta_cost_acceptable_pct = 2.0 from the retired setup suite
        For 2.0 pct: theta = 2.0 * underlying / DAYS_PER_YEAR / 100
        = 2.0 * 10_000 / 365 / 100 ≈ 0.548
        """
        theta_for_2pct = 2.0 * 10_000.0 / const.DAYS_PER_YEAR / 100.0
        analyzer = _analyzer(
            total_theta=theta_for_2pct,
            total_underlying_value=10_000.0,
        )
        result = analyzer.calculate_net_carry_pct()
        assert result == pytest.approx(2.0)

    def test_degenerate_zero_underlying_value_returns_none(self) -> None:
        """total_underlying_value == 0 → None (unavailable)."""
        analyzer = _analyzer(
            total_theta=-10.0,
            total_underlying_value=0.0,
        )
        result = analyzer.calculate_net_carry_pct()
        assert result is None


class TestComputeVolRegimeBoundaries:
    """Vol regime clamp/window edges not covered by test_vol_regime.py."""

    def test_normalized_clamp_at_low_boundary(self) -> None:
        """current_vol <= DEFAULT_VOL_REGIME_LOW → exactly 0.0."""
        result = compute_vol_regime(
            0.15,
            vix_history=None,
            normalized_low=DEFAULT_VOL_REGIME_LOW,
            normalized_high=DEFAULT_VOL_REGIME_HIGH,
        )
        assert result.value == pytest.approx(0.0, rel=1e-8)
        assert result.basis == VolRegimeBasis.NORMALIZED

    def test_normalized_clamp_at_high_boundary(self) -> None:
        """current_vol >= DEFAULT_VOL_REGIME_HIGH → exactly 100.0."""
        result = compute_vol_regime(
            0.35,
            vix_history=None,
            normalized_low=DEFAULT_VOL_REGIME_LOW,
            normalized_high=DEFAULT_VOL_REGIME_HIGH,
        )
        assert result.value == pytest.approx(100.0, rel=1e-5)
        assert result.basis == VolRegimeBasis.NORMALIZED

    def test_normalized_below_low_boundary(self) -> None:
        """current_vol < low → clamped to 0.0."""
        result = compute_vol_regime(
            0.10,
            vix_history=None,
            normalized_low=DEFAULT_VOL_REGIME_LOW,
            normalized_high=DEFAULT_VOL_REGIME_HIGH,
        )
        assert result.value == pytest.approx(0.0, rel=1e-8)
        assert result.basis == VolRegimeBasis.NORMALIZED

    def test_normalized_above_high_boundary(self) -> None:
        """current_vol > high → clamped to 100.0."""
        result = compute_vol_regime(
            0.50,
            vix_history=None,
            normalized_low=DEFAULT_VOL_REGIME_LOW,
            normalized_high=DEFAULT_VOL_REGIME_HIGH,
        )
        assert result.value == pytest.approx(100.0, rel=1e-5)
        assert result.basis == VolRegimeBasis.NORMALIZED

    def test_vix_history_none_selects_normalized(self) -> None:
        """vix_history=None selects normalized fallback."""
        result = compute_vol_regime(
            0.25,
            vix_history=None,
            normalized_low=DEFAULT_VOL_REGIME_LOW,
            normalized_high=DEFAULT_VOL_REGIME_HIGH,
        )
        assert result.basis == VolRegimeBasis.NORMALIZED
        assert result.lookback_days is None
        assert result.sample_size is None

    def test_vix_history_empty_selects_normalized(self) -> None:
        """vix_history=[] (empty) selects normalized fallback."""
        result = compute_vol_regime(
            0.25,
            vix_history=[],
            normalized_low=DEFAULT_VOL_REGIME_LOW,
            normalized_high=DEFAULT_VOL_REGIME_HIGH,
        )
        assert result.basis == VolRegimeBasis.NORMALIZED

    def test_percentile_lookback_window_truncation(self) -> None:
        """History longer than lookback_days only ranks the trailing slice."""
        # History: 100 levels spanning 2 years; rank against last 252 days.
        long_history = [10.0 + i * 0.1 for i in range(600)]
        current_vol = 20.0  # 20 points = 0.20 decimal

        result = compute_vol_regime(
            current_vol / 100.0,
            vix_history=long_history,
            lookback_days=252,
        )

        assert result.basis == VolRegimeBasis.PERCENTILE
        assert result.lookback_days == 252
        assert result.sample_size == 252  # Not 600


class TestCalculateHealthMetricsDisablingContract:
    """Aggregation + disabling contract on absent IPS fields."""

    def test_crash_none_disables_both_crash_derived_gauges(self) -> None:
        """crash=None → crash_convexity_pct=0.0, hedge_success_pct=0.0."""
        analyzer = _analyzer()

        metrics = analyzer.calculate_health_metrics(
            cumulative_carry_paid=1_000.0,
            crash=None,
        )

        # Both crash-derived gauges disabled as a pair.
        assert metrics["crash_convexity_pct"] == pytest.approx(0.0, rel=1e-8)
        assert metrics["hedge_success_pct"] == pytest.approx(0.0, rel=1e-8)

    def test_target_delta_ratio_none_makes_delta_drift_unavailable(
        self,
    ) -> None:
        """target_delta_ratio_pct=None → delta_ratio_deviation_pct=None."""
        analyzer = _analyzer()

        metrics = analyzer.calculate_health_metrics(
            crash=None,
            target_delta_ratio_pct=None,
        )

        assert metrics["delta_ratio_deviation_pct"] is None

    def test_all_metrics_keys_present_in_output(self) -> None:
        """Aggregated dict contains all documented gauge keys."""
        analyzer = _analyzer()

        metrics = analyzer.calculate_health_metrics(crash=None)

        expected_keys = {
            "net_carry_pct",
            "crash_convexity_pct",
            "vega_sufficiency_pct",
            "delta_ratio_deviation_pct",
            "convexity_cliff_days",
            "vol_regime_percentile",
            "vol_regime_basis",
            "vol_regime_lookback_days",
            "hedge_success_pct",
        }
        assert set(metrics.keys()) == expected_keys


def _score_metric(
    actual: float | None,
    min_val: float,
    max_val: float,
    *,
    invert_colors: bool = False,
) -> SimpleNamespace:
    """A metric object shaped the way calculate_overall_health_score reads it.

    These tests used to build real ``HedgeHealthMetric`` instances from
    ``widgets/health_dashboard.py``. Stage 4.3 deleted that module, and the
    scorer never needed it: it is annotated ``dict[str, Any]`` and touches
    only the four attributes below — ``name``/``description``/``start``/
    ``end``/``unit`` were carried purely to satisfy the widget's
    constructor. Building the real contract here rather than importing a
    gauge class keeps the test honest about what the function requires.
    """
    return SimpleNamespace(
        actual=actual,
        min_val=min_val,
        max_val=max_val,
        invert_colors=invert_colors,
    )


class TestCalculateOverallHealthScore:
    """Aggregation score: normal values within band, boundaries, degenerate."""

    def test_normal_value_in_middle_of_band(self) -> None:
        """Metric at mid-range → score around 50 (depending on direction)."""
        metrics = {"test": _score_metric(50.0, min_val=0, max_val=100)}

        analyzer = _analyzer()
        score = analyzer.calculate_overall_health_score(metrics)
        assert score == pytest.approx(50.0)

    def test_boundary_at_min_val_exact(self) -> None:
        """actual == min_val exactly → score = 0 (non-inverted)."""
        metrics = {"test": _score_metric(25.0, min_val=25, max_val=75)}

        analyzer = _analyzer()
        score = analyzer.calculate_overall_health_score(metrics)
        assert score == pytest.approx(0.0)

    def test_boundary_at_max_val_exact(self) -> None:
        """actual == max_val exactly → score = 100 (non-inverted)."""
        metrics = {"test": _score_metric(75.0, min_val=25, max_val=75)}

        analyzer = _analyzer()
        score = analyzer.calculate_overall_health_score(metrics)
        assert score == pytest.approx(100.0)

    def test_inverted_colors_min_val_exact(self) -> None:
        """Inverted: actual == min_val → score = 100 (inverted)."""
        metrics = {
            "test": _score_metric(
                5.0,
                min_val=5,
                max_val=95,
                invert_colors=True,
            ),
        }

        analyzer = _analyzer()
        score = analyzer.calculate_overall_health_score(metrics)
        assert score == pytest.approx(100.0)

    def test_inverted_colors_max_val_exact(self) -> None:
        """Inverted: actual == max_val → score = 0 (inverted)."""
        metrics = {
            "test": _score_metric(
                95.0,
                min_val=5,
                max_val=95,
                invert_colors=True,
            ),
        }

        analyzer = _analyzer()
        score = analyzer.calculate_overall_health_score(metrics)
        assert score == pytest.approx(0.0)

    def test_multiple_metrics_averaged(self) -> None:
        """Multiple metrics → averaged score."""
        metrics = {
            "m1": _score_metric(100.0, min_val=0, max_val=100),
            "m2": _score_metric(0.0, min_val=0, max_val=100),
        }

        analyzer = _analyzer()
        score = analyzer.calculate_overall_health_score(metrics)
        # (100 + 0) / 2 = 50
        assert score == pytest.approx(50.0)

    def test_metric_actual_none_skipped_in_average(self) -> None:
        """Metrics with actual=None are skipped (unavailable gauges)."""
        metrics = {
            "available": _score_metric(100.0, min_val=0, max_val=100),
            "unavailable": _score_metric(None, min_val=0, max_val=100),
        }

        analyzer = _analyzer()
        score = analyzer.calculate_overall_health_score(metrics)
        # Only the available=100 metric; (100) / 1 = 100
        assert score == pytest.approx(100.0)

    def test_degenerate_empty_metrics_dict_returns_neutral_default(
        self,
    ) -> None:
        """Empty metrics dict → sentinel 50 (neutral default)."""
        analyzer = _analyzer()
        score = analyzer.calculate_overall_health_score({})
        assert score == pytest.approx(50.0, rel=1e-4)
