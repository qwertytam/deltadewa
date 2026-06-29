"""Structural protocols for mixin composition.

These are never instantiated at runtime. They exist solely to give static
analysers (mypy, pyright, pylint) an accurate picture of what self looks
like inside each mixin at runtime — i.e., the full composed OptionPortfolio.
"""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

import numpy as np
import pandas as pd
from matplotlib.axes import Axes

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolioBase

# Covariant TypeVar for portfolio types
# Covariance allows subclasses (OptionPortfolio) to be used where the base
# class (OptionPortfolioBase) is expected
PortfolioT = TypeVar("PortfolioT", bound="OptionPortfolioBase")


class _VisualizationProtocol(Protocol, Generic[PortfolioT]):
    """Structural type of self inside all Visualization mixins.

    This protocol is generic and covariant over portfolio types. This allows
    both OptionPortfolioBase and OptionPortfolio (and any future subclasses)
    to be used interchangeably, while maintaining type safety.

    Type parameter:
        PortfolioT: The portfolio type (bounded to OptionPortfolioBase or
        subclass)
    """

    portfolio: PortfolioT

    # Mixin methods (defined in their respective mixin classes, but declared
    # here for static type checking)

    # OptionChartsBase
    def _get_expiry_label(self) -> str: ...

    # PnLChartsMixin
    def _plot_pnl_panel(
        self,
        ax: Axes,
        spot_range: np.ndarray[Any, np.dtype[Any]],
        pnl_values: (
            list[float] | np.ndarray[Any, np.dtype[Any]]
        ),
        analysis: dict[str, Any],
        analysis_key: str,
        title: str,
    ) -> None: ...

    # ThetaChartsMixin
    def _prepare_theta_data(
        self,
        df: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict[str, Any]]: ...

    def _plot_theta_by_bucket(
        self,
        ax: Axes,
        df_carry: pd.DataFrame,
    ) -> None: ...

    def _plot_theta_projection(
        self,
        ax: Axes,
        theta_metrics: dict[str, Any],
        projection_days: int,
    ) -> None: ...

    def _plot_carry_efficiency(
        self,
        ax: Axes,
        df_carry: pd.DataFrame,
    ) -> None: ...

    def _plot_theta_vs_contracts(
        self,
        ax: Axes,
        df_carry: pd.DataFrame,
    ) -> None: ...

    # GreekChartsMixin
    def _plot_greek_by_dimension(
        self,
        ax: Axes,
        df: pd.DataFrame,
        metric: str,
        dimension: str,
        title: str,
        xlabel: str | None = None,
    ) -> None: ...
