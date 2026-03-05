"""Structural protocols for mixin composition.

These are never instantiated at runtime. They exist solely to give static
analysers (mypy, pyright, pylint) an accurate picture of what self looks
like inside each mixin at runtime — i.e., the full composed OptionPortfolio.
"""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

import numpy as np
from matplotlib.axes import Axes

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolioBase

# Covariant TypeVar for portfolio types
# Covariance allows subclasses (OptionPortfolio) to be used where the base
# class (OptionPortfolioBase) is expected
PortfolioT = TypeVar("PortfolioT", bound="OptionPortfolioBase", covariant=True)


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
        spot_range: np.ndarray,
        pnl_values: list[float] | np.ndarray,
        analysis: dict,
        analysis_key: str,
        title: str,
    ) -> None: ...
