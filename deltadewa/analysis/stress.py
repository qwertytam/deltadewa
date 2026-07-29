"""Stress-panel compute: grid orchestration and Monte Carlo statistics.

Extracted from ``dashboard.stress.StressDashboard`` (M2.1) so both are
callable from a future Dash callback with no notebook/widget dependency.
:func:`build_spot_vol_grid_spec` and :func:`days_to_max_maturity` read
*portfolio* but never assign to it; every other function takes plain arrays
and has no portfolio dependency at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from deltadewa.analysis.volatility import calculate_portfolio_avg_volatility

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


# ---------------------------------------------------------------------------
# Spot x Vol grid orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpotVolGridSpec:
    """Scenario axes and baseline context for the spot/vol heatmap.

    Attributes:
        spot_scenarios: Spot-price axis, ascending.
        vol_scenarios: Volatility axis, ascending, clamped to [0.05, 3.0].
        spot_min: Lower bound of ``spot_scenarios``.
        spot_max: Upper bound of ``spot_scenarios``.
        vol_min: Lower bound of ``vol_scenarios`` (post-clamp).
        vol_max: Upper bound of ``vol_scenarios`` (post-clamp).
        avg_vol: Vega-weighted average volatility at the base state.
        original_spot: The portfolio's spot price at build time.
        baseline_value: ``portfolio.total_value()`` at build time.
        max_days: Days to the portfolio's furthest-dated position (or 90
            when the portfolio holds no positions).

    """

    spot_scenarios: np.ndarray[Any, np.dtype[Any]]
    vol_scenarios: np.ndarray[Any, np.dtype[Any]]
    spot_min: float
    spot_max: float
    vol_min: float
    vol_max: float
    avg_vol: float
    original_spot: float
    baseline_value: float
    max_days: int


def days_to_max_maturity(portfolio: OptionPortfolio) -> int:
    """Return days from the portfolio's valuation date to its furthest leg.

    Precondition: ``portfolio.positions`` is non-empty.

    Args:
        portfolio: Live portfolio (read-only).

    Returns:
        Whole days between ``portfolio.valuation_date`` and the latest
        ``maturity_date`` across all positions.

    """
    max_maturity = max(pos.option.maturity_date for pos in portfolio.positions)
    return (max_maturity - portfolio.valuation_date).days


def build_spot_vol_grid_spec(
    portfolio: OptionPortfolio,
    *,
    spot_shock_pct: float,
    vol_shock_pct: float,
    grid_resolution: int,
) -> SpotVolGridSpec:
    """Derive the spot/vol scenario axes and baseline for the heatmap.

    Args:
        portfolio: Live portfolio (read-only).
        spot_shock_pct: Fractional spot range either side of the current
            spot (e.g. ``0.25`` for +/-25%).
        vol_shock_pct: Fractional vol range either side of the average
            volatility.
        grid_resolution: Number of points on each axis.

    Returns:
        The scenario axes plus the baseline context used to render and
        annotate the heatmap.

    """
    original_spot = portfolio.spot_price
    baseline_value = portfolio.total_value()
    avg_vol = calculate_portfolio_avg_volatility(portfolio)

    spot_min = original_spot * (1 - spot_shock_pct)
    spot_max = original_spot * (1 + spot_shock_pct)
    spot_scenarios = np.linspace(spot_min, spot_max, grid_resolution)

    vol_min = max(avg_vol * (1 - vol_shock_pct), 0.05)
    vol_max = min(avg_vol * (1 + vol_shock_pct), 3.0)
    vol_scenarios = np.linspace(vol_min, vol_max, grid_resolution)

    max_days = days_to_max_maturity(portfolio) if portfolio.positions else 90

    return SpotVolGridSpec(
        spot_scenarios=spot_scenarios,
        vol_scenarios=vol_scenarios,
        spot_min=spot_min,
        spot_max=spot_max,
        vol_min=vol_min,
        vol_max=vol_max,
        avg_vol=avg_vol,
        original_spot=original_spot,
        baseline_value=baseline_value,
        max_days=max_days,
    )


# ---------------------------------------------------------------------------
# Time x Price grid construction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimePriceGridSpec:
    """Scenario axes for the time/price heatmap.

    Attributes:
        spot_scenarios: Spot-price axis, ascending.
        spot_min: Lower bound of ``spot_scenarios``.
        spot_max: Upper bound of ``spot_scenarios``.
        time_days: Distinct day offsets from ``original_date``. May be
            shorter than the requested step count: the axis is built via
            ``linspace(...).astype(int)`` then deduplicated, so short-dated
            portfolios collapse adjacent fractional-day steps onto the same
            integer day.
        time_points: ``original_date + timedelta(days=d)`` for each entry
            in ``time_days``.

    """

    spot_scenarios: np.ndarray[Any, np.dtype[Any]]
    spot_min: float
    spot_max: float
    time_days: np.ndarray[Any, np.dtype[Any]]
    time_points: list[datetime]


def build_time_price_grid_spec(
    *,
    spot_range_pct: float,
    num_time_steps: int,
    num_price_steps: int,
    original_spot: float,
    original_date: datetime,
    max_days_to_maturity: int,
) -> TimePriceGridSpec:
    """Derive the spot/time scenario axes for the time/price heatmap.

    Args:
        spot_range_pct: Fractional spot range either side of
            ``original_spot``.
        num_time_steps: Requested number of time-axis points (the actual
            axis may be shorter; see :class:`TimePriceGridSpec`).
        num_price_steps: Number of spot-axis points.
        original_spot: Spot price the axis is centred on.
        original_date: Valuation date the time axis is offset from.
        max_days_to_maturity: Upper bound of the time axis, in days.

    Returns:
        The spot and time scenario axes.

    """
    spot_min = original_spot * (1 - spot_range_pct)
    spot_max = original_spot * (1 + spot_range_pct)
    spot_scenarios = np.linspace(spot_min, spot_max, num_price_steps)

    time_days = np.unique(
        np.linspace(0, max_days_to_maturity, num_time_steps).astype(int),
    )
    time_points = [original_date + timedelta(days=int(d)) for d in time_days]

    return TimePriceGridSpec(
        spot_scenarios=spot_scenarios,
        spot_min=spot_min,
        spot_max=spot_max,
        time_days=time_days,
        time_points=time_points,
    )


# ---------------------------------------------------------------------------
# Monte Carlo risk/reward compute
# ---------------------------------------------------------------------------


def recompute_concentration(
    pnls_clean: np.ndarray[Any, np.dtype[Any]],
    most_common_pnl: tuple[float, int] | None,
    concentration_pct: float,
) -> tuple[bool, float]:
    """Recompute distribution concentration from the raw P&L sample.

    A distribution is "concentrated" when the number of distinct
    (2-decimal-rounded) outcomes is small relative to the sample size —
    typical for short-option strategies where most paths expire worthless.
    Callers should not trust an ``is_concentrated``/``concentration_pct``
    pair supplied alongside *pnls_clean*; this recomputes both from the
    sample itself.

    Args:
        pnls_clean: Finite simulated P&L values.
        most_common_pnl: ``(value, count)`` of the modal outcome, or
            ``None`` when unavailable.
        concentration_pct: Fallback percentage, returned unchanged when the
            sample is not concentrated (or *most_common_pnl* is ``None``).

    Returns:
        ``(is_concentrated, concentration_pct)``.

    """
    unique_rounded = np.unique(np.round(pnls_clean, 2))
    is_concentrated = len(unique_rounded) < (len(pnls_clean) / 100)

    if is_concentrated and most_common_pnl is not None:
        concentration_pct = most_common_pnl[1] / len(pnls_clean) * 100

    return is_concentrated, concentration_pct


@dataclass(frozen=True)
class PnlHistogram:
    """A P&L probability-density histogram.

    Attributes:
        bin_centers: Midpoint of each bin.
        density: Probability density per bin (counts normalised by
            ``total_count * bin_width``).
        bin_width: Width of a single bin.

    """

    bin_centers: np.ndarray[Any, np.dtype[Any]]
    density: np.ndarray[Any, np.dtype[Any]]
    bin_width: float


def compute_pnl_histogram(
    pnls_clean: np.ndarray[Any, np.dtype[Any]],
    *,
    min_pnl: float,
    max_pnl: float,
    is_concentrated: bool,
) -> PnlHistogram:
    """Bin a P&L sample into a probability-density histogram.

    Bin count is fixed at 30 for a concentrated distribution (so the modal
    spike renders as a single tall bar); otherwise
    ``min(50, max(20, len(pnls_clean) // 100))``.

    Args:
        pnls_clean: Finite simulated P&L values.
        min_pnl: Lower edge of the histogram range.
        max_pnl: Upper edge of the histogram range.
        is_concentrated: Whether the distribution is concentrated.

    Returns:
        The binned histogram.

    """
    n_bins = 30 if is_concentrated else min(50, max(20, len(pnls_clean) // 100))
    bin_edges = np.linspace(min_pnl, max_pnl, n_bins + 1)
    bin_edges[-1] += 1e-10
    counts, bin_edges = np.histogram(pnls_clean, bins=bin_edges)
    bin_width = bin_edges[1] - bin_edges[0]
    total_count = counts.sum()
    density = (
        (counts / (total_count * bin_width))
        if (total_count > 0 and bin_width > 0)
        else counts.astype(float)
    )
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

    return PnlHistogram(
        bin_centers=bin_centers,
        density=density,
        bin_width=float(bin_width),
    )


@dataclass(frozen=True)
class EmpiricalCdf:
    """An empirical cumulative distribution function.

    Attributes:
        sorted_pnls: *pnls_clean*, sorted ascending.
        cdf: Cumulative probability at each entry in ``sorted_pnls``.

    """

    sorted_pnls: np.ndarray[Any, np.dtype[Any]]
    cdf: np.ndarray[Any, np.dtype[Any]]


def compute_empirical_cdf(
    pnls_clean: np.ndarray[Any, np.dtype[Any]],
) -> EmpiricalCdf:
    """Build the empirical CDF of a P&L sample.

    Args:
        pnls_clean: Finite simulated P&L values.

    Returns:
        The sorted sample and its cumulative probability.

    """
    sorted_pnls = np.sort(pnls_clean)
    cdf = np.arange(1, len(sorted_pnls) + 1) / len(sorted_pnls)
    return EmpiricalCdf(sorted_pnls=sorted_pnls, cdf=cdf)


def percentile_of_value(cdf: EmpiricalCdf, value: float) -> float:
    """Return the empirical percentile (in [0, 1]) at which *value* sits.

    Args:
        cdf: An empirical CDF from :func:`compute_empirical_cdf`.
        value: The P&L value to locate.

    Returns:
        The fraction of the sample at or below *value*; ``1.0`` when
        *value* is at or beyond the top of the sample.

    """
    idx = np.searchsorted(cdf.sorted_pnls, value)
    if idx < len(cdf.sorted_pnls):
        return float(idx / len(cdf.sorted_pnls))
    return 1.0
