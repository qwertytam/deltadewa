"""Structural protocols for mixin composition.

These are never instantiated at runtime. They exist solely to give static
analysers (mypy, pyright, pylint) an accurate picture of what self looks
like inside each mixin at runtime — i.e., the full composed PortfolioAnalyzer.
"""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import numpy as np
from matplotlib.axes import Axes

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


class _VisualizationProtocol(Protocol):
    """Structural type of self inside all Visualization mixins."""

    # Use the base portfolio type here (mutable/invariant) so static
    # analysers accept both the composed `OptionPortfolio` and the
    # lightweight `OptionPortfolioBase` instances used in some places.
    portfolio: "OptionPortfolio"  # noqa: UP037

    # Mixin methods (defined in their respective mixin classes, but declared
    # here for static type checking)

    # OptionsChartsBase
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
