"""Structural protocols for mixin composition.

These are never instantiated at runtime. They exist solely to give static
analysers (mypy, pyright, pylint) an accurate picture of what self looks
like inside each mixin at runtime — i.e., the full composed PortfolioAnalyzer.
"""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

if TYPE_CHECKING:
    from deltadewa.portfolio.position import OptionPosition


class _PortfolioProtocol(Protocol):
    """Structural type of self inside all PortfolioAnalyzer mixins."""

    positions: list[OptionPosition]
    underlying_quantity: float
    volatility: float
    valuation_date: datetime
    spot_price: float
    risk_free_rate: float
    dividend_yield: float
    monte_carlo_results: dict[str, float | int | np.ndarray] | None

    # OptionPortfolioBase methods
    def total_value(self) -> float: ...
    def total_underlying_value(self) -> float: ...
    def total_portfolio_value(self) -> float: ...
    def summary_stats(self) -> dict: ...

    # GreeksMixin methods
    def net_delta(self) -> float: ...
    def total_delta(self) -> float: ...
    def total_rho(self) -> float: ...
    def total_vega(self) -> float: ...
    def total_theta(self) -> float: ...
    def total_gamma(self) -> float: ...
    def all_greeks(self) -> dict: ...
    def delta_adjustment_needed(self) -> float: ...
    def hedge_ratio(self) -> float: ...

    # PnLMixin methods
    def calculate_pnl_at_expiry(
        self,
        spot_price_at_expiry: float,
        include_underlying: bool = False,
    ) -> float: ...
    def vectorized_pnl_at_expiry(
        self,
        spot_scenarios: np.ndarray,
        include_underlying: bool = True,
    ) -> np.ndarray: ...

    # MonteCarloMixin methods
    def _empty_monte_carlo_results(
        self,
        days_to_expiry: int,
    ) -> dict[str, Any]: ...
    def _calculate_theoretical_max_loss(self) -> float | None: ...
    def _analyze_concentration(
        self,
        pnls: np.ndarray,
    ) -> tuple[bool, float, tuple[float, int] | None]: ...

    # RiskMixin methods
    def calculate_breakeven_points(
        self,
        spot_range: np.ndarray | None = None,
        include_underlying: bool = False,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> list[float]: ...
    def _get_spot_range(
        self,
        spot_range: np.ndarray | None = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
        num_points: int = 250,
        use_comprehensive_range: bool = False,
    ) -> np.ndarray: ...
    def _check_unlimited_trend(
        self,
        pnl_array: np.ndarray,
        check_increasing: bool,
    ) -> bool: ...
