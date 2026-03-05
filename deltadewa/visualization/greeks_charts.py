"""Greek visualization methods for option charts."""

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.container import BarContainer
from matplotlib.figure import Figure

from deltadewa.colours import DEFAULT_PALETTE

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolioBase


class GreeksChartsMixin:
    """Mixin providing Greek visualization methods."""

    if TYPE_CHECKING:
        portfolio: "OptionPortfolioBase"

    def plot_greeks_by_strike(
        self,
        metrics: list[str] | None = None,
        figsize: tuple[int, int] = (18, 16),
    ) -> Figure:
        """Create stacked bar charts of Greeks by strike price.

        Args:
            metrics: list of Greeks to plot (default: ['delta', 'gamma',
            'vega'])
            figsize: Figure size tuple

        Returns:
            Matplotlib Figure object

        """
        if metrics is None:
            metrics = ["delta", "gamma", "vega"]

        df_positions = self.portfolio.to_dataframe()

        nrows = len(metrics)
        fig, axes = plt.subplots(nrows, 1, figsize=figsize)
        if nrows == 1:
            axes = [axes]

        for ax, metric in zip(axes, metrics, strict=False):
            self._plot_greek_by_dimension(
                ax,
                df_positions,
                metric,
                "strike",
                f"{metric.title()} Exposure by Strike",
            )

        plt.tight_layout()
        return fig

    def plot_greeks_by_maturity(
        self,
        metrics: list[str] | None = None,
        figsize: tuple[int, int] = (18, 16),
    ) -> Figure:
        """Create stacked bar charts of Greeks by maturity date.

        Args:
            metrics: list of Greeks to plot (default: ['delta', 'gamma',
            'vega'])
            figsize: Figure size tuple

        Returns:
            Matplotlib Figure object

        """
        if metrics is None:
            metrics = ["delta", "gamma", "vega"]

        df_positions = self.portfolio.to_dataframe()
        df_positions["maturity_label"] = pd.to_datetime(
            df_positions["maturity"],
        ).dt.strftime("%Y-%m-%d")

        nrows = len(metrics)
        fig, axes = plt.subplots(nrows, 1, figsize=figsize)
        if nrows == 1:
            axes = [axes]

        for ax, metric in zip(axes, metrics, strict=False):
            self._plot_greek_by_dimension(
                ax,
                df_positions,
                metric,
                "maturity_label",
                f"{metric.title()} Exposure by Maturity",
                xlabel="Maturity Date",
            )

        plt.tight_layout()
        return fig

    def _plot_greek_by_dimension(
        self,
        ax: Axes,
        df: pd.DataFrame,
        metric: str,
        dimension: str,
        title: str,
        xlabel: str | None = None,
    ) -> None:
        """Plot Greek exposure by a dimension (strike or maturity).

        Args:
            ax: Matplotlib axes
            df: Portfolio DataFrame
            metric: Greek name ('delta', 'gamma', etc.)
            dimension: Grouping dimension ('strike', 'maturity_label', etc.)
            title: Chart title
            xlabel: X-axis label (defaults to dimension.title())

        """
        position_metric = f"position_{metric}"

        # Create pivot table
        pivot = df.pivot_table(
            values=position_metric,
            index=dimension,
            columns="option_type",
            aggfunc="sum",
            fill_value=0,
        )

        # Plot stacked bar chart
        pivot.plot(kind="bar", stacked=True, ax=ax, alpha=0.8, width=0.7)

        # Reference line at zero
        ax.axhline(
            y=0,
            color=DEFAULT_PALETTE.black,
            linestyle="--",
            linewidth=1,
            alpha=0.5,
        )

        # Formatting
        ax.set_xlabel(xlabel or dimension.replace("_", " ").title())
        ax.set_ylabel(f"Position {metric.title()}")
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.legend(title="option_type", loc="best")
        ax.grid(True, alpha=0.3, axis="y")
        ax.tick_params(axis="x", rotation=45)

        # Add total annotations on bars
        for container in ax.containers:
            if isinstance(container, BarContainer):
                ax.bar_label(
                    container,
                    fmt="%.0f",
                    label_type="edge",
                    fontsize=8,
                )
