"""Theta and carry analysis charts for option visualization."""

from typing import TYPE_CHECKING, Dict, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from deltadewa import constants as const
from deltadewa.colours import DEFAULT_PALETTE

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolioBase


class ThetaChartsMixin:
    """Mixin providing theta and carry analysis charts."""

    if TYPE_CHECKING:
        portfolio: "OptionPortfolioBase"

    def plot_theta_analysis(
        self,
        projection_days: int = 30,
        figsize: Tuple[int, int] = (16, 12),
    ) -> Figure:
        """
        Create 4-panel theta decay analysis chart.

        Panels:
        1. Theta by maturity bucket (stacked bar)
        2. Cumulative theta projection over time
        3. Theta/value ratio (carry efficiency)
        4. Contract count vs theta contribution

        Args:
            projection_days: Days to project theta accumulation
            figsize: Figure size tuple

        Returns:
            Matplotlib Figure object
        """
        df_positions = self.portfolio.to_dataframe()

        # Calculate theta metrics
        df_carry, theta_metrics = self._prepare_theta_data(df_positions)

        # Create figure
        fig, axes = plt.subplots(2, 2, figsize=figsize)

        # Panel 1: Theta by maturity bucket
        self._plot_theta_by_bucket(axes[0, 0], df_carry)

        # Panel 2: Cumulative theta projection
        self._plot_theta_projection(axes[0, 1], theta_metrics, projection_days)

        # Panel 3: Carry efficiency
        self._plot_carry_efficiency(axes[1, 0], df_carry)

        # Panel 4: Contracts vs theta
        self._plot_theta_vs_contracts(axes[1, 1], df_carry)

        plt.tight_layout()
        return fig

    def _prepare_theta_data(
        self, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, Dict]:
        """Prepare data for theta analysis."""
        df_carry = df.copy()

        # Calculate days to expiry
        df_carry["days_to_expiry"] = df_carry["maturity"].apply(
            lambda x: (pd.to_datetime(x) - pd.Timestamp.now()).days
        )

        # Maturity buckets
        def classify_maturity(days):
            if days <= const.DAYS_PER_WEEK:
                return "0-7 days"
            elif days <= const.CALENDAR_DAYS_PER_MONTH:
                return "8-30 days"
            elif days <= const.CALENDAR_DAYS_PER_MONTH * 2:
                return "31-60 days"
            elif days <= const.CALENDAR_DAYS_PER_MONTH * 3:
                return "61-90 days"
            else:
                return "90+ days"

        df_carry["maturity_bucket"] = df_carry["days_to_expiry"].apply(
            classify_maturity
        )

        # Calculate theta metrics
        total_theta_daily = df_carry["position_theta"].sum()
        theta_metrics = {
            "daily": total_theta_daily,
            "weekly": total_theta_daily * const.DAYS_PER_WEEK,
            "monthly": total_theta_daily * const.CALENDAR_DAYS_PER_MONTH,
            "annual": total_theta_daily * const.DAYS_PER_YEAR,
        }

        return df_carry, theta_metrics

    def _plot_theta_by_bucket(self, ax: Axes, df_carry: pd.DataFrame):
        """Plot theta by maturity bucket."""
        theta_by_bucket = (
            df_carry.groupby(["maturity_bucket", "type"])
            .agg({"position_theta": "sum"})
            .reset_index()
        )

        theta_pivot = theta_by_bucket.pivot_table(
            values="position_theta",
            index="maturity_bucket",
            columns="type",
            aggfunc="sum",
            fill_value=0,
        )

        # Sort by bucket order
        bucket_order = [
            "0-7 days",
            "8-30 days",
            "31-60 days",
            "61-90 days",
            "90+ days",
        ]
        theta_pivot = theta_pivot.reindex(
            [b for b in bucket_order if b in theta_pivot.index]
        )

        if len(theta_pivot) > 0:
            theta_pivot.plot(
                kind="bar", stacked=True, ax=ax, alpha=0.8, width=0.7
            )
            ax.axhline(
                y=0, color=DEFAULT_PALETTE.black, linestyle="--", linewidth=1
            )

            # Net theta annotations
            for i, bucket in enumerate(theta_pivot.index):
                net_theta = theta_pivot.loc[bucket].sum()
                ax.text(
                    i,
                    net_theta,
                    f"${net_theta:.1f}",
                    ha="center",
                    va="bottom" if net_theta > 0 else "top",
                )
        else:
            ax.text(
                0.5,
                0.5,
                "No data available",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )

        ax.set_xlabel("Maturity Bucket")
        ax.set_ylabel("Daily Theta ($)")
        ax.set_title(
            "Daily Theta by Maturity Bucket", fontsize=12, fontweight="bold"
        )
        ax.grid(True, alpha=0.3, axis="y")
        ax.legend(loc="best")

    def _plot_theta_projection(
        self,
        ax: Axes,
        theta_metrics: Dict,
        projection_days: int,
    ):
        """Plot cumulative theta projection."""
        days_range = np.arange(0, projection_days + 1)
        cumulative_theta = days_range * theta_metrics["daily"]

        ax.plot(
            days_range,
            cumulative_theta,
            linewidth=2,
            marker="o",
            markersize=4,
            markevery=5,
        )
        ax.axhline(
            y=0, color=DEFAULT_PALETTE.medium_grey, linestyle=":", linewidth=1
        )
        ax.fill_between(days_range, 0, cumulative_theta, alpha=0.2)

        # Milestone annotations
        for day in [7, 14, 21, 30]:
            if day <= projection_days:
                pnl = day * theta_metrics["daily"]
                ax.annotate(
                    f"${pnl:.0f}",
                    xy=(day, pnl),
                    xytext=(5, 5),
                    textcoords="offset points",
                    fontsize=9,
                    bbox=dict(
                        boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.3
                    ),
                )

        ax.set_xlabel("Days Forward")
        ax.set_ylabel("Cumulative Theta P&L ($)")
        ax.set_title(
            "Projected Theta Accumulation", fontsize=12, fontweight="bold"
        )
        ax.grid(True, alpha=0.3)

    def _plot_carry_efficiency(self, ax: Axes, df_carry: pd.DataFrame):
        """Plot theta/value ratio by bucket."""
        bucket_order = [
            "0-7 days",
            "8-30 days",
            "31-60 days",
            "61-90 days",
            "90+ days",
        ]

        bucket_summary = (
            df_carry.groupby("maturity_bucket")
            .agg(
                {
                    "position_theta": "sum",
                    "position_value": lambda x: x.abs().sum(),
                }
            )
            .reset_index()
        )

        bucket_summary["theta_pct"] = (
            (
                bucket_summary["position_theta"]
                / bucket_summary["position_value"]
            )
            * 100
            * const.DAYS_PER_YEAR
        )

        bucket_summary = bucket_summary.set_index("maturity_bucket")
        bucket_summary = bucket_summary.reindex(
            [b for b in bucket_order if b in bucket_summary.index]
        )

        if (
            len(bucket_summary) > 0
            and not bucket_summary["theta_pct"].isna().all()
        ):
            colors = [
                DEFAULT_PALETTE.negative if x > 0 else DEFAULT_PALETTE.negative
                for x in bucket_summary["theta_pct"]
            ]
            bucket_summary["theta_pct"].plot(
                kind="barh", ax=ax, color=colors, alpha=0.7
            )
            ax.axvline(
                x=0, color=DEFAULT_PALETTE.black, linestyle="--", linewidth=1
            )
        else:
            ax.text(
                0.5,
                0.5,
                "No data available",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )

        ax.set_xlabel("Annualized Theta / Position Value (%)")
        ax.set_ylabel("Maturity Bucket")
        ax.set_title(
            "Carry Efficiency by Bucket", fontsize=12, fontweight="bold"
        )
        ax.grid(True, alpha=0.3, axis="x")

    def _plot_theta_vs_contracts(self, ax: Axes, df_carry: pd.DataFrame):
        """Plot contract count vs theta contribution."""
        bucket_order = [
            "0-7 days",
            "8-30 days",
            "31-60 days",
            "61-90 days",
            "90+ days",
        ]

        bucket_summary = (
            df_carry.groupby("maturity_bucket")
            .agg({"position_theta": "sum", "quantity": lambda x: x.abs().sum()})
            .reset_index()
        )

        bucket_summary = bucket_summary.set_index("maturity_bucket")
        bucket_summary = bucket_summary.reindex(
            [b for b in bucket_order if b in bucket_summary.index]
        )

        if len(bucket_summary) > 0 and not bucket_summary.empty:
            ax_twin = ax.twinx()

            bucket_summary["quantity"].plot(
                kind="bar",
                ax=ax,
                color="steelblue",
                alpha=0.6,
                width=0.4,
                position=0,
                label="Contracts",
            )
            bucket_summary["position_theta"].plot(
                kind="bar",
                ax=ax_twin,
                color="coral",
                alpha=0.6,
                width=0.4,
                position=1,
                label="Theta",
            )

            ax.set_ylabel("Total Contracts", color="steelblue")
            ax_twin.set_ylabel("Daily Theta ($)", color="coral")
            ax.tick_params(axis="y", labelcolor="steelblue")
            ax_twin.tick_params(axis="y", labelcolor="coral")

            ax.legend(loc="upper left")
            ax_twin.legend(loc="upper right")
        else:
            ax.text(
                0.5,
                0.5,
                "No data available",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )

        ax.set_xlabel("Maturity Bucket")
        ax.set_title(
            "Contracts vs Theta Contribution", fontsize=12, fontweight="bold"
        )
        ax.tick_params(axis="x", rotation=45)
        ax.grid(True, alpha=0.3, axis="y")
