"""Base class and final composition for option charts visualization."""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

from deltadewa.visualization.crash_charts import CrashChartsMixin
from deltadewa.visualization.greeks_charts import GreeksChartsMixin
from deltadewa.visualization.pnl_charts import PnLChartsMixin
from deltadewa.visualization.scenarios import ScenarioChartsMixin
from deltadewa.visualization.theta_charts import ThetaChartsMixin

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolioBase


class OptionChartsBase:
    """Base class with portfolio reference and style setup.

    This class provides the foundation for all charting utilities, managing
    the portfolio reference and matplotlib style configuration.

    Attributes:
        portfolio: OptionPortfolio instance to visualize
        style: Matplotlib style to use

    """

    def __init__(
        self,
        portfolio: OptionPortfolioBase,
        style: str = "seaborn-v0_8-darkgrid",
    ) -> None:
        """Initialize OptionChartsBase with a portfolio.

        Args:
            portfolio: OptionPortfolio instance to visualize
            style: Matplotlib style name (default: 'seaborn-v0_8-darkgrid')

        """
        self.portfolio = portfolio
        self.style = style
        self._apply_style()

    def _apply_style(self) -> None:
        """Apply matplotlib style if available."""
        try:
            plt.style.use(self.style)
        except Exception:  # pylint: disable=broad-except
            warnings.warn(
                f"Style '{self.style}' not available, using default",
                stacklevel=1,
            )

    def _get_expiry_label(self) -> str:
        """Get expiry label for chart titles."""
        if self.portfolio.positions:
            maturities = sorted(
                {pos.option.maturity_date for pos in self.portfolio.positions},
            )
            if len(maturities) == 1:
                return maturities[0].strftime("%Y-%m-%d")
            return (
                f"{maturities[0].strftime('%Y-%m-%d')} "
                f"→ {maturities[-1].strftime('%Y-%m-%d')}"
            )
        return "N/A"

    @staticmethod
    def create_chart_grid(
        rows: int,
        cols: int,
        titles: list[str],
        figsize: tuple[int, int] | None = None,
    ) -> tuple[Figure, np.ndarray[Any, np.dtype[Any]]]:
        """Create standardized multi-panel chart grid with consistent styling.

        Args:
            rows: Number of rows
            cols: Number of columns
            titles: list of titles for each panel
            figsize: Figure size tuple (default: calculated based on rows/cols)

        Returns:
            tuple of (Figure, axes array)

        """
        if figsize is None:
            figsize = (8 * cols, 6 * rows)

        fig, axes = plt.subplots(rows, cols, figsize=figsize)

        # Ensure axes is always an array
        if rows * cols == 1:
            axes = np.array([axes])
        else:
            axes = np.array(axes).flatten()

        # Apply titles and styling
        for ax, title in zip(axes, titles, strict=False):
            ax.set_title(title, fontsize=12, fontweight="bold")
            ax.grid(True, alpha=0.3)

        return fig, axes.reshape(rows, cols) if rows * cols > 1 else axes


class OptionCharts(
    PnLChartsMixin,
    GreeksChartsMixin,
    ThetaChartsMixin,
    ScenarioChartsMixin,
    CrashChartsMixin,
    OptionChartsBase,
):
    """Comprehensive charting utilities for options portfolio analysis.

    This class provides methods to create standardized, publication-quality
    charts for options analysis including P&L diagrams, Greek distributions,
    risk decomposition, theta decay analysis, and scenario analysis.

    Composed from specialized mixins:
    - PnLChartsMixin: P&L diagram plotting methods
    - GreeksChartsMixin: Greek visualization methods
    - ThetaChartsMixin: Theta and carry analysis charts
    - ScenarioChartsMixin: Scenario analysis visualization
    - CrashChartsMixin: Crash payoff and convexity charts
    - OptionChartsBase: Core portfolio reference and style setup

    Attributes:
        portfolio: OptionPortfolio instance
        style: Matplotlib style to use (default: 'seaborn-v0_8-darkgrid')

    """
