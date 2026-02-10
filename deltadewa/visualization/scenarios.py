"""Scenario analysis visualization for option charts."""

from typing import TYPE_CHECKING, Tuple
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from deltadewa.colours import DEFAULT_PALETTE

if TYPE_CHECKING:
    from deltadewa.visualization.base import OptionChartsBase


class ScenarioChartsMixin:
    """Mixin providing scenario analysis visualization."""

    def plot_scenario_analysis(
        self: "OptionChartsBase",
        scenario_df: pd.DataFrame,
        days_forward: int,
        valuation_date,
        current_spot: float,
        figsize: Tuple[int, int] = (14, 10),
    ) -> Figure:
        """
        Plot P&L and delta profiles for a scenario analysis at a forward date.

        Args:
            scenario_df: DataFrame with columns: spot_price, portfolio_pnl,
                        underlying_pnl, total_pnl, total_delta, net_delta
            days_forward: Days forward from today
            valuation_date: The valuation date for the analysis
            current_spot: Current spot price for reference line
            figsize: Figure size tuple

        Returns:
            Matplotlib Figure
        """
        fig, axes = plt.subplots(2, 1, figsize=figsize)

        # P&L Breakdown
        ax1 = axes[0]
        ax1.plot(
            scenario_df["spot_price"],
            scenario_df["portfolio_pnl"],
            label="Options P&L",
            linewidth=2.5,
        )
        ax1.plot(
            scenario_df["spot_price"],
            scenario_df["underlying_pnl"],
            label="Underlying P&L",
            linewidth=2.5,
        )
        ax1.plot(
            scenario_df["spot_price"],
            scenario_df["total_pnl"],
            label="Total P&L",
            linewidth=2.5,
            linestyle="--",
            color=DEFAULT_PALETTE.black,
        )
        ax1.axhline(
            y=0, color=DEFAULT_PALETTE.medium_grey, linestyle=":", linewidth=1
        )
        ax1.axvline(
            x=current_spot,
            color=DEFAULT_PALETTE.negative,
            linestyle=":",
            linewidth=1,
            label="Current Spot",
        )
        ax1.set_xlabel("Spot Price", fontsize=11)
        ax1.set_ylabel("P&L ($)", fontsize=11)
        ax1.yaxis.set_major_formatter(
            FuncFormatter(self.format_currency_compact)
        )

        # Add date info to title
        date_str = valuation_date.strftime("%Y-%m-%d")
        if days_forward == 0:
            title_suffix = f" (Today - {date_str})"
        else:
            title_suffix = f" ({days_forward} days forward - {date_str})"
        ax1.set_title(
            f"P&L Scenario Analysis{title_suffix}",
            fontsize=13,
            fontweight="bold",
        )
        ax1.legend(loc="best")
        ax1.grid(True, alpha=0.3)

        # Delta Profile
        ax2 = axes[1]
        ax2.plot(
            scenario_df["spot_price"],
            scenario_df["total_delta"],
            label="Portfolio Delta",
            linewidth=2.5,
        )
        ax2.plot(
            scenario_df["spot_price"],
            scenario_df["net_delta"],
            label="Net Delta (with Notional)",
            linewidth=2.5,
        )
        ax2.axhline(
            y=0, color=DEFAULT_PALETTE.medium_grey, linestyle=":", linewidth=1
        )
        ax2.axvline(
            x=current_spot,
            color=DEFAULT_PALETTE.negative,
            linestyle=":",
            linewidth=1,
            label="Current Spot",
        )
        ax2.set_xlabel("Spot Price", fontsize=11)
        ax2.set_ylabel("Delta", fontsize=11)
        ax2.set_title(
            "Delta Profile Across Spot Prices", fontsize=13, fontweight="bold"
        )
        ax2.legend(loc="best")
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        return fig
