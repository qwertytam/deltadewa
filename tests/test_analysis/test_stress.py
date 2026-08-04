"""Tests for deltadewa.analysis.stress — the M2.1 stress-panel compute seam.

Extracted from StressDashboard (dashboard/stress.py) so grid orchestration
and Monte Carlo risk/reward statistics are callable with no notebook/widget
dependency. Several of these pin behaviour that used to be characterised
only as standalone arithmetic in tests/test_dashboard/test_stress.py,
disconnected from any real function — moving here strengthens that
coverage to exercise the actual extracted code.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from deltadewa.analysis.stress import (
    build_spot_vol_grid_spec,
    build_time_price_grid_spec,
    compute_empirical_cdf,
    compute_pnl_histogram,
    days_to_max_maturity,
    percentile_of_value,
    recompute_concentration,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio

_AS_OF = datetime(2026, 7, 26, tzinfo=UTC)


def _make_put_portfolio(
    spot: float = 100.0,
    vol: float = 0.25,
    days_to_maturity: int = 45,
) -> OptionPortfolio:
    """Build a single-leg European put portfolio pinned to a fixed as-of.

    Args:
        spot: Current spot price.
        vol: Implied volatility.
        days_to_maturity: Days from `_AS_OF` to option expiry.

    Returns:
        Real OptionPortfolio with one European put.

    """
    portfolio = OptionPortfolio(
        spot_price=spot,
        volatility=vol,
        risk_free_rate=0.05,
        dividend_yield=0.02,
        valuation_date=_AS_OF,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=spot * 0.9,
        maturity_date=_AS_OF + timedelta(days=days_to_maturity),
        quantity=1,
        option_type=OptionType.PUT,
    )
    return portfolio


class TestDaysToMaxMaturity:
    """days_to_max_maturity reads the furthest-dated leg."""

    def test_matches_known_maturity(self) -> None:
        """Single-leg: days to max maturity matches days_to_maturity."""
        portfolio = _make_put_portfolio(days_to_maturity=45)

        assert days_to_max_maturity(portfolio) == 45

    def test_picks_the_furthest_of_several_legs(self) -> None:
        """With multiple legs, the furthest maturity wins."""
        portfolio = _make_put_portfolio(days_to_maturity=30)
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=_AS_OF + timedelta(days=90),
            quantity=1,
            option_type=OptionType.PUT,
        )

        assert days_to_max_maturity(portfolio) == 90


class TestBuildSpotVolGridSpec:
    """build_spot_vol_grid_spec: bounds, clamping, and baseline capture."""

    def test_spot_bounds_and_scenarios(self) -> None:
        """Spot axis is a linspace centred on portfolio.spot_price."""
        portfolio = _make_put_portfolio(spot=100.0)

        spec = build_spot_vol_grid_spec(
            portfolio,
            spot_shock_pct=0.25,
            vol_shock_pct=0.20,
            grid_resolution=5,
        )

        assert spec.spot_min == pytest.approx(75.0)
        assert spec.spot_max == pytest.approx(125.0)
        assert spec.original_spot == pytest.approx(100.0)
        assert len(spec.spot_scenarios) == 5
        assert spec.spot_scenarios[0] == pytest.approx(75.0)
        assert spec.spot_scenarios[-1] == pytest.approx(125.0)

    def test_vol_min_floor_clamp(self) -> None:
        """vol_min never drops below 0.05, even for a large shock pct."""
        portfolio = _make_put_portfolio(vol=0.25)

        spec = build_spot_vol_grid_spec(
            portfolio,
            spot_shock_pct=0.10,
            vol_shock_pct=1.0,
            grid_resolution=5,
        )

        assert spec.avg_vol == pytest.approx(0.25)
        assert spec.vol_min == pytest.approx(0.05)
        assert spec.vol_max == pytest.approx(0.50)

    def test_vol_max_ceiling_clamp(self) -> None:
        """vol_max never exceeds 3.0, even for a large shock pct."""
        portfolio = _make_put_portfolio(vol=2.0)

        spec = build_spot_vol_grid_spec(
            portfolio,
            spot_shock_pct=0.10,
            vol_shock_pct=1.0,
            grid_resolution=5,
        )

        assert spec.vol_min == pytest.approx(0.05)
        assert spec.vol_max == pytest.approx(3.0)

    def test_baseline_value_and_max_days(self) -> None:
        """baseline_value mirrors total_value(); max_days mirrors the
        furthest maturity."""
        portfolio = _make_put_portfolio(days_to_maturity=60)

        spec = build_spot_vol_grid_spec(
            portfolio,
            spot_shock_pct=0.10,
            vol_shock_pct=0.10,
            grid_resolution=3,
        )

        assert spec.baseline_value == pytest.approx(portfolio.total_value())
        assert spec.max_days == 60

    def test_spot_shock_pct_percent_shaped_value_raises(self) -> None:
        """A percent-shaped value (e.g. 30.0) raises ValueError, not a
        QuantLib RuntimeError from a negative spot."""
        portfolio = _make_put_portfolio(spot=100.0)

        with pytest.raises(ValueError, match="spot_shock_pct"):
            build_spot_vol_grid_spec(
                portfolio,
                spot_shock_pct=30.0,
                vol_shock_pct=0.20,
                grid_resolution=5,
            )

    def test_spot_shock_pct_at_one_raises(self) -> None:
        """spot_shock_pct == 1.0 drives spot_min to zero and raises."""
        portfolio = _make_put_portfolio(spot=100.0)

        with pytest.raises(ValueError, match="spot_shock_pct"):
            build_spot_vol_grid_spec(
                portfolio,
                spot_shock_pct=1.0,
                vol_shock_pct=0.20,
                grid_resolution=5,
            )

    def test_vol_shock_pct_non_positive_raises(self) -> None:
        """A zero or negative vol_shock_pct raises ValueError."""
        portfolio = _make_put_portfolio(spot=100.0)

        with pytest.raises(ValueError, match="vol_shock_pct"):
            build_spot_vol_grid_spec(
                portfolio,
                spot_shock_pct=0.10,
                vol_shock_pct=0.0,
                grid_resolution=5,
            )

        with pytest.raises(ValueError, match="vol_shock_pct"):
            build_spot_vol_grid_spec(
                portfolio,
                spot_shock_pct=0.10,
                vol_shock_pct=-0.1,
                grid_resolution=5,
            )


class TestBuildTimePriceGridSpec:
    """build_time_price_grid_spec: spot axis and the time-truncation quirk."""

    def test_time_axis_truncation_dedup_shortens_columns(self) -> None:
        """linspace(...).astype(int) truncates, so a short-dated portfolio
        produces fewer time points than num_time_steps requested (moved
        from tests/test_dashboard/test_stress.py — now exercises the real
        extracted function instead of standalone arithmetic)."""
        spec = build_time_price_grid_spec(
            spot_range_pct=0.10,
            num_time_steps=10,
            num_price_steps=5,
            original_spot=100.0,
            original_date=_AS_OF,
            max_days_to_maturity=3,
        )

        # astype(int) truncates 0, 0.33->0, 0.66->0, 1.0->1, ... 3.0->3;
        # after unique, only 4 distinct days remain: [0, 1, 2, 3].
        assert len(spec.time_days) < 10
        assert list(spec.time_days) == [0, 1, 2, 3]
        assert len(spec.time_points) == 4
        assert spec.time_points[0] == _AS_OF
        assert spec.time_points[-1] == _AS_OF + timedelta(days=3)

    def test_spot_axis_and_bounds(self) -> None:
        """Spot axis is a linspace centred on original_spot."""
        spec = build_time_price_grid_spec(
            spot_range_pct=0.10,
            num_time_steps=5,
            num_price_steps=5,
            original_spot=100.0,
            original_date=_AS_OF,
            max_days_to_maturity=90,
        )

        assert spec.spot_min == pytest.approx(90.0)
        assert spec.spot_max == pytest.approx(110.0)
        assert len(spec.spot_scenarios) == 5
        assert spec.spot_scenarios[2] == pytest.approx(100.0)

    def test_spot_range_pct_percent_shaped_value_raises(self) -> None:
        """A percent-shaped value (e.g. 30.0) raises ValueError, not a
        QuantLib RuntimeError from a negative spot."""
        with pytest.raises(ValueError, match="spot_range_pct"):
            build_time_price_grid_spec(
                spot_range_pct=30.0,
                num_time_steps=5,
                num_price_steps=5,
                original_spot=100.0,
                original_date=_AS_OF,
                max_days_to_maturity=90,
            )


class TestRecomputeConcentration:
    """recompute_concentration: the is_concentrated/concentration_pct
    override rule."""

    def test_concentrated_sample_overrides_both_fields(self) -> None:
        """A highly-concentrated sample recomputes both is_concentrated
        and concentration_pct, discarding whatever was passed in."""
        pnls_clean = np.full(1000, 100.0)
        most_common_pnl = (100.0, 900)

        is_concentrated, concentration_pct = recompute_concentration(
            pnls_clean,
            most_common_pnl,
            concentration_pct=0.0,
        )

        assert is_concentrated is True
        assert concentration_pct == pytest.approx(90.0)

    def test_spread_sample_passes_concentration_pct_through(self) -> None:
        """A spread-out sample recomputes is_concentrated=False and leaves
        concentration_pct exactly as passed in (never touched)."""
        pnls_clean = np.linspace(-1000.0, 1000.0, 2000)

        is_concentrated, concentration_pct = recompute_concentration(
            pnls_clean,
            most_common_pnl=(0.0, 1),
            concentration_pct=5.0,
        )

        assert is_concentrated is False
        assert concentration_pct == pytest.approx(5.0)

    def test_concentrated_but_no_most_common_pnl_passes_through(self) -> None:
        """Concentrated by the unique-count test, but most_common_pnl is
        None: concentration_pct is not recomputed (matches the original
        `if is_concentrated and most_common_pnl is not None:` guard)."""
        pnls_clean = np.full(1000, 100.0)

        is_concentrated, concentration_pct = recompute_concentration(
            pnls_clean,
            most_common_pnl=None,
            concentration_pct=7.0,
        )

        assert is_concentrated is True
        assert concentration_pct == pytest.approx(7.0)


class TestComputePnlHistogram:
    """compute_pnl_histogram: the bin-count rule and the resulting shape."""

    def test_concentrated_uses_fixed_30_bins(self) -> None:
        """is_concentrated=True always uses 30 bins, regardless of sample
        size (moved/strengthened from the dashboard's standalone
        arithmetic-only assertion)."""
        pnls_clean = np.full(1000, 100.0)

        histogram = compute_pnl_histogram(
            pnls_clean,
            min_pnl=99.0,
            max_pnl=101.0,
            is_concentrated=True,
        )

        assert len(histogram.bin_centers) == 30
        assert len(histogram.density) == 30

    def test_spread_uses_clamped_count_rule(self) -> None:
        """is_concentrated=False: min(50, max(20, n // 100)). For n=1000,
        this is min(50, max(20, 10)) == 20."""
        pnls_clean = np.linspace(-1000.0, 1000.0, 1000)

        histogram = compute_pnl_histogram(
            pnls_clean,
            min_pnl=-1000.0,
            max_pnl=1000.0,
            is_concentrated=False,
        )

        assert len(histogram.bin_centers) == 20

    def test_spread_count_rule_floors_at_20(self) -> None:
        """A small spread sample still gets at least 20 bins."""
        pnls_clean = np.linspace(-100.0, 100.0, 50)

        histogram = compute_pnl_histogram(
            pnls_clean,
            min_pnl=-100.0,
            max_pnl=100.0,
            is_concentrated=False,
        )

        assert len(histogram.bin_centers) == 20

    def test_density_integrates_to_one(self) -> None:
        """density * bin_width sums to ~1 over the full histogram."""
        rng = np.random.default_rng(42)
        pnls_clean = rng.normal(0, 100, 5000)

        histogram = compute_pnl_histogram(
            pnls_clean,
            min_pnl=float(pnls_clean.min()),
            max_pnl=float(pnls_clean.max()),
            is_concentrated=False,
        )

        total_mass = np.sum(histogram.density) * histogram.bin_width
        assert total_mass == pytest.approx(1.0, abs=1e-6)


class TestComputeEmpiricalCdf:
    """compute_empirical_cdf: sorted sample plus cumulative probability."""

    def test_small_fixed_array(self) -> None:
        """A hand-checkable 5-point CDF."""
        pnls_clean = np.array([3.0, 1.0, 5.0, 2.0, 4.0])

        result = compute_empirical_cdf(pnls_clean)

        assert list(result.sorted_pnls) == [1.0, 2.0, 3.0, 4.0, 5.0]
        np.testing.assert_allclose(result.cdf, [0.2, 0.4, 0.6, 0.8, 1.0])

    def test_cdf_is_monotonic_nondecreasing(self) -> None:
        """The CDF never decreases along the sorted sample."""
        rng = np.random.default_rng(7)
        pnls_clean = rng.normal(0, 50, 500)

        result = compute_empirical_cdf(pnls_clean)

        assert np.all(np.diff(result.cdf) >= 0)


class TestPercentileOfValue:
    """percentile_of_value: the searchsorted-based percentile lookup."""

    def test_value_at_an_existing_sample_point(self) -> None:
        """Looking up an exact sample value returns its rank fraction."""
        pnls_clean = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        cdf = compute_empirical_cdf(pnls_clean)

        assert percentile_of_value(cdf, 3.0) == pytest.approx(0.4)

    def test_value_below_the_sample_returns_zero(self) -> None:
        """A value below every sample point sits at percentile 0."""
        pnls_clean = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        cdf = compute_empirical_cdf(pnls_clean)

        assert percentile_of_value(cdf, 0.0) == pytest.approx(0.0)

    def test_value_at_or_beyond_the_top_returns_one(self) -> None:
        """A value at or beyond the top of the sample sits at percentile
        1.0 (the idx == len(sorted_pnls) branch)."""
        pnls_clean = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        cdf = compute_empirical_cdf(pnls_clean)

        assert percentile_of_value(cdf, 10.0) == pytest.approx(1.0)
