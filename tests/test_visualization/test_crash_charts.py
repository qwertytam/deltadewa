"""Tests for deltadewa.visualization.crash_charts."""

from datetime import UTC, datetime, timedelta

import matplotlib
import matplotlib.pyplot as plt
import pytest

from deltadewa.analysis.crash_payoff import (
    CrashConvexityResult,
    PremiumBasis,
    compute_crash_convexity,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsConvexity
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.visualization.crash_charts import plot_crash_convexity

matplotlib.use("Agg")

# ruff: noqa: S101


def _make_long_put_portfolio(
    *,
    quantity: int = 10,
    spot_price: float = 100.0,
) -> OptionPortfolio:
    portfolio = OptionPortfolio(
        spot_price=spot_price,
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=100.0,
        maturity_date=datetime.now(tz=UTC) + timedelta(days=60),
        quantity=quantity,
        option_type=OptionType.PUT,
    )
    return portfolio


def _empty_result() -> CrashConvexityResult:
    return CrashConvexityResult(
        rows=[],
        headline_row=None,
        premium=0.0,
        premium_basis=PremiumBasis.MARK,
        ips_convexity=None,
    )


class TestPlotCrashConvexity:
    """Tests for plot_crash_convexity."""

    def test_returns_figure_with_two_axes(self) -> None:
        """plot_crash_convexity returns a Figure with exactly 2 Axes."""
        portfolio = _make_long_put_portfolio()
        result = compute_crash_convexity(
            portfolio, shocks=[-10.0, -20.0, -30.0],
        )

        fig = plot_crash_convexity(result)
        try:
            assert len(fig.axes) == 2
        finally:
            plt.close(fig)

    def test_with_ips_convexity_does_not_raise(self) -> None:
        """plot_crash_convexity with an ips_convexity band runs cleanly."""
        portfolio = _make_long_put_portfolio()
        ips = IpsConvexity(
            crash_scenario_pct=-20.0,
            target_min_pct=2.0,
            target_max_pct=10.0,
        )
        result = compute_crash_convexity(
            portfolio, shocks=[-10.0, -20.0, -30.0], ips_convexity=ips,
        )

        fig = plot_crash_convexity(result)
        try:
            assert fig is not None
        finally:
            plt.close(fig)

    def test_empty_rows_does_not_raise(self) -> None:
        """Empty result rows produce a valid Figure without raising."""
        result = _empty_result()
        fig = plot_crash_convexity(result)
        try:
            assert len(fig.axes) == 2
        finally:
            plt.close(fig)

    def test_custom_figsize_is_respected(self) -> None:
        """Figsize parameter is passed through to the Figure."""
        result = _empty_result()
        fig = plot_crash_convexity(result, figsize=(8, 4))
        try:
            w, h = fig.get_size_inches()
            assert w == pytest.approx(8.0)
            assert h == pytest.approx(4.0)
        finally:
            plt.close(fig)

    def test_mixin_delegates_to_module_function(self) -> None:
        """CrashChartsMixin.plot_crash_convexity returns same figure type."""
        from deltadewa.visualization.base import OptionCharts

        portfolio = _make_long_put_portfolio()
        charts = OptionCharts(portfolio)
        result = compute_crash_convexity(portfolio, shocks=[-20.0])

        fig = charts.plot_crash_convexity(result)
        try:
            assert len(fig.axes) == 2
        finally:
            plt.close(fig)
