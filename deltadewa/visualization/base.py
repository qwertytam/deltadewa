"""Base class and final composition for option charts visualization."""

import warnings
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

from deltadewa.visualization.formatters import FormattersMixin
from deltadewa.visualization.greeks_charts import GreeksChartsMixin
from deltadewa.visualization.pnl_charts import PnLChartsMixin
from deltadewa.visualization.scenarios import ScenarioChartsMixin
from deltadewa.visualization.theta_charts import ThetaChartsMixin


class OptionChartsBase:
    """
    Base class with portfolio reference and style setup.

    This class provides the foundation for all charting utilities, managing
    the portfolio reference and matplotlib style configuration.

    Attributes:
        portfolio: OptionPortfolio instance to visualize
        style: Matplotlib style to use
    """

    def __init__(self, portfolio, style: str = "seaborn-v0_8-darkgrid"):
        """
        Initialize OptionChartsBase with a portfolio.

        Args:
            portfolio: OptionPortfolio instance to visualize
            style: Matplotlib style name (default: 'seaborn-v0_8-darkgrid')
        """
        self.portfolio = portfolio
        self.style = style
        self._apply_style()

    def _apply_style(self):
        """Apply matplotlib style if available."""
        try:
            plt.style.use(self.style)
        except Exception:  # pylint: disable=broad-except
            warnings.warn(f"Style '{self.style}' not available, using default")

    def _get_expiry_label(self) -> str:
        """Get expiry label for chart titles."""
        if self.portfolio.positions:
            maturities = sorted(
                {pos.option.maturity_date for pos in self.portfolio.positions}
            )
            if len(maturities) == 1:
                return maturities[0].strftime("%Y-%m-%d")
            else:
                result = (
                    f"{maturities[0].strftime('%Y-%m-%d')} "
                    + f"→ {maturities[-1].strftime('%Y-%m-%d')}"
                )
                return result
        return "N/A"

    @staticmethod
    def create_chart_grid(
        rows: int,
        cols: int,
        titles: List[str],
        figsize: Optional[Tuple[int, int]] = None,
    ) -> Tuple[Figure, np.ndarray]:
        """
        Create standardized multi-panel chart grid with consistent styling.

        Args:
            rows: Number of rows
            cols: Number of columns
            titles: List of titles for each panel
            figsize: Figure size tuple (default: calculated based on rows/cols)

        Returns:
            Tuple of (Figure, axes array)
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
        for ax, title in zip(axes, titles):
            ax.set_title(title, fontsize=12, fontweight="bold")
            ax.grid(True, alpha=0.3)

        return fig, axes.reshape(rows, cols) if rows * cols > 1 else axes


class OptionCharts(
    FormattersMixin,
    PnLChartsMixin,
    GreeksChartsMixin,
    ThetaChartsMixin,
    ScenarioChartsMixin,
    OptionChartsBase,
):
    """
    Comprehensive charting utilities for options portfolio analysis.

    This class provides methods to create standardized, publication-quality
    charts for options analysis including P&L diagrams, Greek distributions,
    risk decomposition, theta decay analysis, and scenario analysis.

    Composed from specialized mixins:
    - FormattersMixin: Axis and value formatting utilities
    - PnLChartsMixin: P&L diagram plotting methods
    - GreeksChartsMixin: Greek visualization methods
    - ThetaChartsMixin: Theta and carry analysis charts
    - ScenarioChartsMixin: Scenario analysis visualization
    - OptionChartsBase: Core portfolio reference and style setup

    Attributes:
        portfolio: OptionPortfolio instance
        style: Matplotlib style to use (default: 'seaborn-v0_8-darkgrid')
    """

    pass  # pylint: disable=unnecessary-pass
