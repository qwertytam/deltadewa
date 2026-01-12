"""
Visualization Module for Options Portfolio Analysis

This module provides comprehensive charting and plotting utilities for options
portfolio analysis, including P&L diagrams, Greek distributions, heatmaps,
theta decay analysis, and interactive scenario visualizations.

Usage:
    from deltadewa.visualization import OptionCharts

    charts = OptionCharts(portfolio)
    charts.plot_pnl_diagram()
    charts.plot_greeks_by_strike()
    charts.plot_theta_analysis()

Author: DeltaDewa Team
Date: 2026-01-12
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from typing import Optional, List, Dict, Tuple, Union
import warnings


class OptionCharts:
    """
    Comprehensive charting utilities for options portfolio analysis.

    This class provides methods to create standardized, publication-quality
    charts for options analysis including P&L diagrams, Greek distributions,
    risk decomposition, and scenario analysis.

    Attributes:
        portfolio: OptionPortfolio instance
        style: Matplotlib style to use (default: 'seaborn-v0_8-darkgrid')
    """

    def __init__(self, portfolio, style: str = "seaborn-v0_8-darkgrid"):
        """
        Initialize OptionCharts with a portfolio.

        Args:
            portfolio: OptionPortfolio instance to visualize
            style: Matplotlib style name
        """
        self.portfolio = portfolio
        self.style = style
        self._apply_style()

    def _apply_style(self):
        """Apply matplotlib style if available."""
        try:
            plt.style.use(self.style)
        except:
            warnings.warn(f"Style '{self.style}' not available, using default")

    @staticmethod
    def format_currency_compact(x, pos=None):
        """
        Format currency values in compact form.

        - Values < $10k: $X,XXX
        - Values < $10M: $XXXk
        - Values >= $10M: $X.XM

        Args:
            x: Value to format
            pos: Position (for FuncFormatter compatibility)

        Returns:
            Formatted string
        """
        if abs(x) < 10_000:
            return f"${x:,.0f}"
        elif abs(x) < 10_000_000:
            return f"${x/1_000:,.0f}k"
        else:
            return f"${x/1_000_000:,.1f}M"

    # ========================================================================
    # P&L Visualization
    # ========================================================================

    def plot_pnl_diagram(
        self,
        spot_range_pct: float = 40.0,
        num_points: int = 300,
        show_underlying: bool = True,
        figsize: Tuple[int, int] = (14, 12),
    ) -> Figure:
        """
        Create comprehensive P&L diagram at expiration.

        Shows two panels:
        1. Options-only P&L
        2. Total portfolio P&L (options + underlying)

        Includes breakeven points, max loss/profit markers, and profit/loss zones.

        Args:
            spot_range_pct: Percentage range around current spot (default: 40%)
            num_points: Number of points in spot price range
            show_underlying: Whether to show underlying P&L panel
            figsize: Figure size tuple

        Returns:
            Matplotlib Figure object
        """
        # Create spot price range
        spot_min = max(0.01, self.portfolio.spot_price * (1 - spot_range_pct / 100))
        spot_max = self.portfolio.spot_price * (1 + spot_range_pct / 100)
        spot_range = np.linspace(spot_min, spot_max, num_points)

        # Calculate P&L curves
        pnl_options = [
            self.portfolio.calculate_pnl_at_expiry(spot, include_underlying=False)
            for spot in spot_range
        ]
        pnl_total = [
            self.portfolio.calculate_pnl_at_expiry(spot, include_underlying=True)
            for spot in spot_range
        ]

        # Get risk/reward metrics
        analysis = self.portfolio.risk_reward_analysis()

        # Determine expiration label
        expiry_label = self._get_expiry_label()

        # Create figure
        nrows = 2 if (show_underlying and self.portfolio.underlying_quantity != 0) else 1
        fig, axes = plt.subplots(nrows, 1, figsize=figsize)
        if nrows == 1:
            axes = [axes]

        # Plot 1: Options Only P&L
        self._plot_pnl_panel(
            axes[0],
            spot_range,
            pnl_options,
            analysis,
            "options",
            "Options Only - P&L at Expiration",
        )

        # Plot 2: Total Portfolio P&L (if applicable)
        if nrows == 2:
            self._plot_pnl_panel(
                axes[1],
                spot_range,
                pnl_total,
                analysis,
                "total",
                "Total Portfolio - P&L at Expiration (Options + Underlying)",
            )

        plt.tight_layout()
        return fig

    def _plot_pnl_panel(
        self,
        ax: plt.Axes,
        spot_range: np.ndarray,
        pnl_values: List[float],
        analysis: Dict,
        analysis_key: str,
        title: str,
    ):
        """
        Plot a single P&L panel.

        Args:
            ax: Matplotlib axes
            spot_range: Array of spot prices
            pnl_values: P&L values corresponding to spot_range
            analysis: Risk/reward analysis dictionary
            analysis_key: 'options' or 'total'
            title: Chart title
        """
        # Reference lines
        ax.axhline(y=0, color="black", linestyle="--", linewidth=0.8, alpha=0.5)
        ax.axvline(
            x=self.portfolio.spot_price,
            color="blue",
            linestyle="--",
            linewidth=1.5,
            alpha=0.7,
            label="Current Spot",
        )

        # Fill profit/loss zones
        pnl_array = np.array(pnl_values)
        ax.fill_between(
            spot_range,
            pnl_values,
            0,
            where=pnl_array >= 0,
            color="green",
            alpha=0.2,
            label="Profit Zone",
        )
        ax.fill_between(
            spot_range,
            pnl_values,
            0,
            where=pnl_array < 0,
            color="red",
            alpha=0.2,
            label="Loss Zone",
        )

        # P&L curve
        color = "darkblue" if analysis_key == "options" else "purple"
        label = "Options P&L" if analysis_key == "options" else "Total P&L"
        ax.plot(spot_range, pnl_values, linewidth=2.5, color=color, label=label)

        # Breakeven points
        be_key = f"breakeven_{analysis_key}"
        if analysis.get(be_key):
            for i, be in enumerate(analysis[be_key]):
                be_pnl = self.portfolio.calculate_pnl_at_expiry(
                    be, include_underlying=(analysis_key == "total")
                )
                ax.plot(
                    be,
                    be_pnl,
                    "ko",
                    markersize=10,
                    markeredgewidth=2,
                    markerfacecolor="yellow",
                    label=f"Breakeven: ${be:.2f}" if i == 0 else "",
                )

        # Max loss marker
        ml_key = f"max_loss_{analysis_key}"
        if not analysis[ml_key]["is_unlimited"]:
            ml_spot = analysis[ml_key]["spot_at_max_loss"]
            ml_val = analysis[ml_key]["max_loss"]
            ax.plot(
                ml_spot,
                ml_val,
                "rv",
                markersize=12,
                markeredgewidth=2,
                markerfacecolor="red",
                label=f"Max Loss: ${-ml_val:,.0f}",
            )

        # Max profit marker
        mp_key = f"max_profit_{analysis_key}"
        if not analysis[mp_key]["is_unlimited"]:
            mp_spot = analysis[mp_key]["spot_at_max_profit"]
            mp_val = analysis[mp_key]["max_profit"]
            ax.plot(
                mp_spot,
                mp_val,
                "g^",
                markersize=12,
                markeredgewidth=2,
                markerfacecolor="green",
                label=f"Max Profit: ${mp_val:,.0f}",
            )
        else:
            # Unlimited profit annotation
            ax.annotate(
                "Unlimited Profit →",
                xy=(spot_range[-1] * 0.95, pnl_values[-1]),
                xytext=(spot_range[-1] * 0.8, pnl_values[-1] * 0.8),
                fontsize=11,
                fontweight="bold",
                color="green",
                arrowprops=dict(arrowstyle="->", color="green", lw=2),
            )

        # Formatting
        ax.set_xlabel("Spot Price at Expiration ($)", fontsize=12, fontweight="bold")
        ax.set_ylabel("P&L ($)", fontsize=12, fontweight="bold")
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=10)
        ax.yaxis.set_major_formatter(FuncFormatter(self.format_currency_compact))

    # ========================================================================
    # Greek Visualization
    # ========================================================================

    def plot_greeks_by_strike(
        self, metrics: Optional[List[str]] = None, figsize: Tuple[int, int] = (18, 16)
    ) -> plt.Figure:
        """
        Create stacked bar charts of Greeks by strike price.

        Args:
            metrics: List of Greeks to plot (default: ['delta', 'gamma', 'vega'])
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

        for ax, metric in zip(axes, metrics):
            self._plot_greek_by_dimension(
                ax, df_positions, metric, "strike", f"{metric.title()} Exposure by Strike"
            )

        plt.tight_layout()
        return fig

    def plot_greeks_by_maturity(
        self, metrics: Optional[List[str]] = None, figsize: Tuple[int, int] = (18, 16)
    ) -> Figure:
        """
        Create stacked bar charts of Greeks by maturity date.

        Args:
            metrics: List of Greeks to plot (default: ['delta', 'gamma', 'vega'])
            figsize: Figure size tuple

        Returns:
            Matplotlib Figure object
        """
        if metrics is None:
            metrics = ["delta", "gamma", "vega"]

        df_positions = self.portfolio.to_dataframe()
        df_positions["maturity_label"] = pd.to_datetime(df_positions["maturity"]).dt.strftime(
            "%Y-%m-%d"
        )

        nrows = len(metrics)
        fig, axes = plt.subplots(nrows, 1, figsize=figsize)
        if nrows == 1:
            axes = [axes]

        for ax, metric in zip(axes, metrics):
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
        ax: plt.Axes,
        df: pd.DataFrame,
        metric: str,
        dimension: str,
        title: str,
        xlabel: Optional[str] = None,
    ):
        """
        Plot Greek exposure by a dimension (strike or maturity).

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
            values=position_metric, index=dimension, columns="type", aggfunc="sum", fill_value=0
        )

        # Plot stacked bar chart
        pivot.plot(kind="bar", stacked=True, ax=ax, alpha=0.8, width=0.7)

        # Reference line at zero
        ax.axhline(y=0, color="black", linestyle="--", linewidth=1, alpha=0.5)

        # Formatting
        ax.set_xlabel(xlabel or dimension.replace("_", " ").title())
        ax.set_ylabel(f"Position {metric.title()}")
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.legend(title="Type", loc="best")
        ax.grid(True, alpha=0.3, axis="y")
        ax.tick_params(axis="x", rotation=45)

        # Add total annotations on bars
        for container in ax.containers:
            ax.bar_label(container, fmt="%.0f", label_type="edge", fontsize=8)

    # ========================================================================
    # Theta Decay Visualization
    # ========================================================================

    def plot_theta_analysis(
        self, projection_days: int = 30, figsize: Tuple[int, int] = (16, 12)
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

    def _prepare_theta_data(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
        """Prepare data for theta analysis."""
        df_carry = df.copy()

        # Calculate days to expiry
        df_carry["days_to_expiry"] = df_carry["maturity"].apply(
            lambda x: (pd.to_datetime(x) - pd.Timestamp.now()).days
        )

        # Maturity buckets
        def classify_maturity(days):
            if days <= 7:
                return "0-7 days"
            elif days <= 30:
                return "8-30 days"
            elif days <= 60:
                return "31-60 days"
            elif days <= 90:
                return "61-90 days"
            else:
                return "90+ days"

        df_carry["maturity_bucket"] = df_carry["days_to_expiry"].apply(classify_maturity)

        # Calculate theta metrics
        total_theta_daily = df_carry["position_theta"].sum()
        theta_metrics = {
            "daily": total_theta_daily,
            "weekly": total_theta_daily * 7,
            "monthly": total_theta_daily * 30,
            "annual": total_theta_daily * 365,
        }

        return df_carry, theta_metrics

    def _plot_theta_by_bucket(self, ax: plt.Axes, df_carry: pd.DataFrame):
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
        bucket_order = ["0-7 days", "8-30 days", "31-60 days", "61-90 days", "90+ days"]
        theta_pivot = theta_pivot.reindex([b for b in bucket_order if b in theta_pivot.index])

        if len(theta_pivot) > 0:
            theta_pivot.plot(kind="bar", stacked=True, ax=ax, alpha=0.8, width=0.7)
            ax.axhline(y=0, color="black", linestyle="--", linewidth=1)

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
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)

        ax.set_xlabel("Maturity Bucket")
        ax.set_ylabel("Daily Theta ($)")
        ax.set_title("Daily Theta by Maturity Bucket", fontsize=12, fontweight="bold")
        ax.grid(True, alpha=0.3, axis="y")
        ax.legend(loc="best")

    def _plot_theta_projection(self, ax: plt.Axes, theta_metrics: Dict, projection_days: int):
        """Plot cumulative theta projection."""
        days_range = np.arange(0, projection_days + 1)
        cumulative_theta = days_range * theta_metrics["daily"]

        ax.plot(days_range, cumulative_theta, linewidth=2, marker="o", markersize=4, markevery=5)
        ax.axhline(y=0, color="gray", linestyle=":", linewidth=1)
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
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="yellow", alpha=0.3),
                )

        ax.set_xlabel("Days Forward")
        ax.set_ylabel("Cumulative Theta P&L ($)")
        ax.set_title("Projected Theta Accumulation", fontsize=12, fontweight="bold")
        ax.grid(True, alpha=0.3)

    def _plot_carry_efficiency(self, ax: plt.Axes, df_carry: pd.DataFrame):
        """Plot theta/value ratio by bucket."""
        bucket_order = ["0-7 days", "8-30 days", "31-60 days", "61-90 days", "90+ days"]

        bucket_summary = (
            df_carry.groupby("maturity_bucket")
            .agg({"position_theta": "sum", "position_value": lambda x: x.abs().sum()})
            .reset_index()
        )

        bucket_summary["theta_pct"] = (
            (bucket_summary["position_theta"] / bucket_summary["position_value"]) * 100 * 365
        )

        bucket_summary = bucket_summary.set_index("maturity_bucket")
        bucket_summary = bucket_summary.reindex(
            [b for b in bucket_order if b in bucket_summary.index]
        )

        if len(bucket_summary) > 0 and not bucket_summary["theta_pct"].isna().all():
            colors = ["green" if x > 0 else "red" for x in bucket_summary["theta_pct"]]
            bucket_summary["theta_pct"].plot(kind="barh", ax=ax, color=colors, alpha=0.7)
            ax.axvline(x=0, color="black", linestyle="--", linewidth=1)
        else:
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)

        ax.set_xlabel("Annualized Theta / Position Value (%)")
        ax.set_ylabel("Maturity Bucket")
        ax.set_title("Carry Efficiency by Bucket", fontsize=12, fontweight="bold")
        ax.grid(True, alpha=0.3, axis="x")

    def _plot_theta_vs_contracts(self, ax: plt.Axes, df_carry: pd.DataFrame):
        """Plot contract count vs theta contribution."""
        bucket_order = ["0-7 days", "8-30 days", "31-60 days", "61-90 days", "90+ days"]

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
            ax.text(0.5, 0.5, "No data available", ha="center", va="center", transform=ax.transAxes)

        ax.set_xlabel("Maturity Bucket")
        ax.set_title("Contracts vs Theta Contribution", fontsize=12, fontweight="bold")
        ax.tick_params(axis="x", rotation=45)
        ax.grid(True, alpha=0.3, axis="y")

    # ========================================================================
    # Utility Methods
    # ========================================================================

    def _get_expiry_label(self) -> str:
        """Get expiry label for chart titles."""
        if self.portfolio.positions:
            maturities = sorted({pos.option.maturity_date for pos in self.portfolio.positions})
            if len(maturities) == 1:
                return maturities[0].strftime("%Y-%m-%d")
            else:
                return (
                    f"{maturities[0].strftime('%Y-%m-%d')} → {maturities[-1].strftime('%Y-%m-%d')}"
                )
        return "N/A"

    @staticmethod
    def create_chart_grid(
        rows: int, cols: int, titles: List[str], figsize: Optional[Tuple[int, int]] = None
    ) -> Tuple[plt.Figure, np.ndarray]:
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


# ============================================================================
# Module-Level Convenience Functions
# ============================================================================


def plot_pnl_diagram(portfolio, **kwargs):
    """
    Convenience function to plot P&L diagram.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_pnl_diagram()

    Returns:
        Matplotlib Figure
    """
    charts = OptionCharts(portfolio)
    return charts.plot_pnl_diagram(**kwargs)


def plot_greeks_by_strike(portfolio, **kwargs):
    """
    Convenience function to plot Greeks by strike.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_greeks_by_strike()

    Returns:
        Matplotlib Figure
    """
    charts = OptionCharts(portfolio)
    return charts.plot_greeks_by_strike(**kwargs)


def plot_theta_analysis(portfolio, **kwargs):
    """
    Convenience function to plot theta analysis.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_theta_analysis()

    Returns:
        Matplotlib Figure
    """
    charts = OptionCharts(portfolio)
    return charts.plot_theta_analysis(**kwargs)


# ============================================================================
# Module Metadata
# ============================================================================

__all__ = [
    "OptionCharts",
    "plot_pnl_diagram",
    "plot_greeks_by_strike",
    "plot_theta_analysis",
]
