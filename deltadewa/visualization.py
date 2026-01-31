# pylint: disable=too-many-lines
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

from typing import Optional, List, Dict, Tuple
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.axes import Axes
from matplotlib.ticker import FuncFormatter
from matplotlib.container import BarContainer


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
        except Exception:  # pylint: disable=broad-except
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
        _ = pos
        if abs(x) < 10_000:
            return f"${x:,.0f}"
        elif abs(x) < 10_000_000:
            return f"${x/1_000:,.0f}k"
        else:
            return f"${x/1_000_000:,.1f}M"

    @staticmethod
    def apply_volatility_percent(ax):
        """
        Format the y-axis of an Axes to display percentages for volatility values.

        Assumes the axis values are in decimal form (e.g. 0.25 -> '25%').
        """
        ax.yaxis.set_major_formatter(
            FuncFormatter(lambda x, pos: f"{x*100:.0f}%")
        )

    @staticmethod
    def format_currency_full(x, pos=None):
        """Format currency with full dollar precision and comma separators.

        Args:
            x: numeric value
            pos: FuncFormatter position (unused)

        Returns:
            String like "$1,234"
        """
        _ = pos
        try:
            return f"${x:,.0f}"
        except Exception:  # pylint: disable=broad-except
            return f"${x}"

    @staticmethod
    def apply_spot_price_with_pct(ax, current_spot: float):
        """
        Format the x-axis to show the spot price in currency on the top line
        and the percent change from `current_spot` on the second line.

        Example tick label:\
            $420\n+10%

        Assumes axis values are spot prices in the same units as `current_spot`.
        """

        def _fmt(x, pos):  # pylint: disable=unused-argument
            # Avoid division by zero
            try:
                pct = (x / current_spot - 1) * 100
            except Exception:  # pylint: disable=broad-except
                pct = 0
            curr = OptionCharts.format_currency_full(x)
            return f"{curr}\n{pct:+.0f}%"

        ax.xaxis.set_major_formatter(FuncFormatter(_fmt))
        # Slightly tighten tick padding so two-line labels don't overlap title
        ax.tick_params(axis="x", which="major", pad=6)

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
        spot_min = max(
            0.01, self.portfolio.spot_price * (1 - spot_range_pct / 100)
        )
        spot_max = self.portfolio.spot_price * (1 + spot_range_pct / 100)
        spot_range = np.linspace(spot_min, spot_max, num_points)

        # Calculate P&L curves
        pnl_options = [
            self.portfolio.calculate_pnl_at_expiry(
                spot, include_underlying=False
            )
            for spot in spot_range
        ]
        pnl_total = [
            self.portfolio.calculate_pnl_at_expiry(
                spot, include_underlying=True
            )
            for spot in spot_range
        ]

        # Get risk/reward metrics
        analysis = self.portfolio.risk_reward_analysis()

        # Determine expiration label
        expiry_label = (
            self._get_expiry_label()
        )  # pylint: disable=unused-variable
        _ = expiry_label  # To avoid unused variable warning

        # Create figure
        nrows = (
            2
            if (show_underlying and self.portfolio.underlying_quantity != 0)
            else 1
        )
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

    def plot_pnl_distribution_with_metrics(
        self,
        spot_range_pct: float = 50.0,
        num_points: int = 500,
        figsize: Tuple[int, int] = (16, 8),
        include_underlying: bool = True,
        show_probability_overlay: bool = False,
    ) -> Figure:
        """
        Create P&L distribution chart with annotated key metrics.

        Shows:
        - P&L curve at maturity
        - Break-even points (black diamonds)
        - Max loss point (red triangle down)
        - Max profit point (green triangle up)
        - Expected value from risk analysis (gold star)
        - Current spot marker (vertical dashed line)
        - Profit/loss zones (green/red shading)

        Args:
            spot_range_pct: Percentage range around current spot (default: 50%)
            num_points: Resolution of P&L curve (default: 500)
            figsize: Figure dimensions (default: (16, 8))
            include_underlying: Include underlying position in P&L (default: True)
            show_probability_overlay: Add probability density overlay
                                     (default: False, reserved for future)

        Returns:
            Matplotlib Figure object
        """
        # Store parameter for future use
        _ = show_probability_overlay

        # Generate spot price range
        current_spot = self.portfolio.spot_price
        spot_min = max(0.01, current_spot * (1 - spot_range_pct / 100))
        spot_max = current_spot * (1 + spot_range_pct / 100)
        spot_range = np.linspace(spot_min, spot_max, num_points)

        # Calculate P&L curve
        pnl_values = np.array(
            [
                self.portfolio.calculate_pnl_at_expiry(
                    spot, include_underlying=include_underlying
                )
                for spot in spot_range
            ]
        )

        # Get risk/reward metrics
        analysis = self.portfolio.risk_reward_analysis(spot_range=spot_range)

        # Create figure and plot main P&L curve
        fig, ax = plt.subplots(1, 1, figsize=figsize)
        ax.plot(
            spot_range,
            pnl_values,
            linewidth=3,
            color="#1f77b4",
            label="P&L at Maturity",
            zorder=3,
        )

        # Add profit/loss zones with fill_between
        ax.fill_between(
            spot_range,
            pnl_values,
            0,
            where=(pnl_values >= 0),
            color="green",
            alpha=0.2,
            label="Profit Zone",
        )
        ax.fill_between(
            spot_range,
            pnl_values,
            0,
            where=(pnl_values < 0),
            color="red",
            alpha=0.2,
            label="Loss Zone",
        )

        # Add zero line and current spot marker
        ax.axhline(0, color="black", linestyle="-", linewidth=1, alpha=0.5)
        ax.axvline(
            current_spot,
            color="black",
            linestyle="--",
            linewidth=2,
            alpha=0.7,
            label=f"Current Spot: ${current_spot:.2f}",
        )

        # Annotate break-even points
        be_key = (
            "breakeven_total" if include_underlying else "breakeven_options"
        )
        if analysis.get(be_key):
            for i, be in enumerate(analysis[be_key]):
                be_pnl = self.portfolio.calculate_pnl_at_expiry(
                    be, include_underlying=include_underlying
                )
                # Plot marker
                ax.plot(
                    be,
                    be_pnl,
                    marker="D",
                    markersize=12,
                    markeredgewidth=2,
                    markerfacecolor="yellow",
                    markeredgecolor="black",
                    zorder=5,
                )
                # Add annotation
                ax.annotate(
                    f"Break-Even\n${be:.2f}",
                    xy=(be, be_pnl),
                    xytext=(0, 30 if i % 2 == 0 else -40),
                    textcoords="offset points",
                    fontsize=10,
                    fontweight="bold",
                    ha="center",
                    bbox=dict(
                        boxstyle="round,pad=0.5",
                        facecolor="yellow",
                        alpha=0.7,
                        edgecolor="black",
                    ),
                    arrowprops=dict(
                        arrowstyle="->", connectionstyle="arc3,rad=0", lw=1.5
                    ),
                )

        # Annotate maximum loss
        ml_key = "max_loss_total" if include_underlying else "max_loss_options"
        max_loss_info = analysis[ml_key]
        if not max_loss_info["is_unlimited"]:
            ml_spot = max_loss_info["spot_at_max_loss"]
            ml_val = max_loss_info["max_loss"]
            # Plot marker
            ax.plot(
                ml_spot,
                ml_val,
                marker="v",
                markersize=15,
                markeredgewidth=2,
                markerfacecolor="red",
                markeredgecolor="darkred",
                zorder=5,
            )
            # Add annotation
            ax.annotate(
                f"Max Loss\n${ml_val:,.0f}",
                xy=(ml_spot, ml_val),
                xytext=(0, -50),
                textcoords="offset points",
                fontsize=10,
                fontweight="bold",
                ha="center",
                bbox=dict(
                    boxstyle="round,pad=0.5",
                    facecolor="#ffcccc",
                    alpha=0.8,
                    edgecolor="darkred",
                ),
                arrowprops=dict(
                    arrowstyle="->", connectionstyle="arc3,rad=0", lw=1.5
                ),
            )

        # Annotate maximum profit
        mp_key = (
            "max_profit_total" if include_underlying else "max_profit_options"
        )
        max_profit_info = analysis[mp_key]
        if not max_profit_info["is_unlimited"]:
            mp_spot = max_profit_info["spot_at_max_profit"]
            mp_val = max_profit_info["max_profit"]
            # Plot marker
            ax.plot(
                mp_spot,
                mp_val,
                marker="^",
                markersize=15,
                markeredgewidth=2,
                markerfacecolor="green",
                markeredgecolor="darkgreen",
                zorder=5,
            )
            # Add annotation
            ax.annotate(
                f"Max Profit\n${mp_val:,.0f}",
                xy=(mp_spot, mp_val),
                xytext=(0, 50),
                textcoords="offset points",
                fontsize=10,
                fontweight="bold",
                ha="center",
                bbox=dict(
                    boxstyle="round,pad=0.5",
                    facecolor="#ccffcc",
                    alpha=0.8,
                    edgecolor="darkgreen",
                ),
                arrowprops=dict(
                    arrowstyle="->", connectionstyle="arc3,rad=0", lw=1.5
                ),
            )

        # Annotate expected value
        expected_value = analysis.get("expected_value", 0)
        if expected_value is not None:
            # Find the spot price closest to the expected value on P&L curve
            idx_closest = np.argmin(np.abs(pnl_values - expected_value))
            ev_spot = spot_range[idx_closest]
            ev_pnl = pnl_values[idx_closest]

            # Plot marker
            ax.plot(
                ev_spot,
                ev_pnl,
                marker="*",
                markersize=20,
                markeredgewidth=2,
                markerfacecolor="gold",
                markeredgecolor="orange",
                zorder=5,
            )
            # Add annotation
            ax.annotate(
                f"Expected Value\n${expected_value:,.0f}",
                xy=(ev_spot, ev_pnl),
                xytext=(50, 20),
                textcoords="offset points",
                fontsize=10,
                fontweight="bold",
                ha="center",
                bbox=dict(
                    boxstyle="round,pad=0.5",
                    facecolor="#ffffcc",
                    alpha=0.8,
                    edgecolor="orange",
                ),
                arrowprops=dict(
                    arrowstyle="->", connectionstyle="arc3,rad=0.2", lw=1.5
                ),
            )

        # Format axes and labels
        ax.set_xlabel(
            "Spot Price at Maturity ($)", fontsize=13, fontweight="bold"
        )
        ax.set_ylabel("Profit / Loss ($)", fontsize=13, fontweight="bold")
        title_suffix = (
            " (Options + Underlying)"
            if include_underlying
            else " (Options Only)"
        )
        ax.set_title(
            f"P&L Distribution with Key Metrics{title_suffix}",
            fontsize=15,
            fontweight="bold",
            pad=20,
        )
        ax.grid(True, alpha=0.3, linestyle=":", linewidth=0.8)
        ax.legend(loc="best", fontsize=10, framealpha=0.9)

        # Apply currency formatters
        ax.yaxis.set_major_formatter(
            FuncFormatter(self.format_currency_compact)
        )
        ax.xaxis.set_major_formatter(FuncFormatter(self.format_currency_full))

        # Return figure
        plt.tight_layout()
        return fig

    def _plot_pnl_panel(
        self,
        ax: Axes,
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
            where=(pnl_array >= 0).tolist(),
            color="green",
            alpha=0.2,
            label="Profit Zone",
        )
        ax.fill_between(
            spot_range,
            pnl_values,
            0,
            where=(pnl_array < 0).tolist(),
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
        ax.set_xlabel(
            "Spot Price at Expiration ($)", fontsize=12, fontweight="bold"
        )
        ax.set_ylabel("P&L ($)", fontsize=12, fontweight="bold")
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=10)
        ax.yaxis.set_major_formatter(
            FuncFormatter(self.format_currency_compact)
        )

    # ========================================================================
    # Greek Visualization
    # ========================================================================

    def plot_greeks_by_strike(
        self,
        metrics: Optional[List[str]] = None,
        figsize: Tuple[int, int] = (18, 16),
    ) -> Figure:
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
        metrics: Optional[List[str]] = None,
        figsize: Tuple[int, int] = (18, 16),
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
        df_positions["maturity_label"] = pd.to_datetime(
            df_positions["maturity"]
        ).dt.strftime("%Y-%m-%d")

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
        ax: Axes,
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
            values=position_metric,
            index=dimension,
            columns="type",
            aggfunc="sum",
            fill_value=0,
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
            if isinstance(container, BarContainer):
                ax.bar_label(
                    container, fmt="%.0f", label_type="edge", fontsize=8
                )

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

        df_carry["maturity_bucket"] = df_carry["days_to_expiry"].apply(
            classify_maturity
        )

        # Calculate theta metrics
        total_theta_daily = df_carry["position_theta"].sum()
        theta_metrics = {
            "daily": total_theta_daily,
            "weekly": total_theta_daily * 7,
            "monthly": total_theta_daily * 30,
            "annual": total_theta_daily * 365,
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
        self, ax: Axes, theta_metrics: Dict, projection_days: int
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
            * 365
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
                "green" if x > 0 else "red" for x in bucket_summary["theta_pct"]
            ]
            bucket_summary["theta_pct"].plot(
                kind="barh", ax=ax, color=colors, alpha=0.7
            )
            ax.axvline(x=0, color="black", linestyle="--", linewidth=1)
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

    # ========================================================================
    # Utility Methods
    # ========================================================================

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

    # ========================================================================
    # Scenario Analysis (Forward Date)
    # ========================================================================

    def plot_scenario_analysis(
        self,
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
            color="black",
        )
        ax1.axhline(y=0, color="gray", linestyle=":", linewidth=1)
        ax1.axvline(
            x=current_spot,
            color="red",
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
        ax2.axhline(y=0, color="gray", linestyle=":", linewidth=1)
        ax2.axvline(
            x=current_spot,
            color="red",
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


def plot_pnl_distribution_with_metrics(portfolio, **kwargs):
    """
    Convenience function to plot P&L distribution with key metrics.

    Args:
        portfolio: OptionPortfolio instance
        **kwargs: Passed to OptionCharts.plot_pnl_distribution_with_metrics()

    Returns:
        Matplotlib Figure
    """
    charts = OptionCharts(portfolio)
    return charts.plot_pnl_distribution_with_metrics(**kwargs)


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


def plot_greeks_consolidated(
    portfolio,
    top_n: int = 5,
    figsize: Tuple[int, int] = (16, 10),
    show_detailed: bool = False,
) -> Figure:
    """
    Create consolidated Greeks view optimized for the EXPLAIN mode.

    This function provides the default 80% use case view: a compact summary
    showing net portfolio Greeks and top contributors. Detailed breakdowns
    are available via the show_detailed parameter.

    Args:
        portfolio: OptionPortfolio instance
        top_n: Number of top contributors to show (default: 5)
        figsize: Figure size tuple
        show_detailed: Whether to include detailed breakdown panels

    Returns:
        Matplotlib Figure with consolidated Greeks visualization

    Panels (default view):
        1. Net portfolio Greeks (single row table display)
        2. Top N contributors bar chart for each Greek
        3. Greeks sensitivity heatmap (how net Greeks change with spot)

    Panels (detailed view):
        4. Strike-by-strike breakdown
        5. Maturity-by-maturity breakdown
    """
    df = portfolio.to_dataframe()

    if df.empty:
        # Return empty figure if no positions
        fig, ax = plt.subplots(1, 1, figsize=(10, 6))
        ax.text(
            0.5,
            0.5,
            "No positions in portfolio",
            ha="center",
            va="center",
            fontsize=16,
        )
        ax.axis("off")
        return fig

    # Calculate net Greeks
    stats = portfolio.summary_stats()
    net_greeks = {
        "Delta": stats["total_delta"],
        "Theta": stats["total_theta"],
        "Gamma": stats["total_gamma"],
        "Vega": stats["total_vega"],
        "Rho": stats.get("total_rho", 0.0),
    }

    # Determine number of panels
    nrows = 2 if not show_detailed else 4
    fig, axes = plt.subplots(nrows, 2, figsize=figsize)

    # Panel 1: Net Greeks Summary Table (spans 2 columns visually)
    ax_net = axes[0, 0]
    ax_net.axis("off")

    net_table_data = [
        ["Greek", "Net Value"],
        ["Delta", f"{net_greeks['Delta']:.2f}"],
        ["Theta", f"${net_greeks['Theta']:.2f}/day"],
        ["Gamma", f"{net_greeks['Gamma']:.4f}"],
        ["Vega", f"{net_greeks['Vega']:.2f}"],
        ["Rho", f"{net_greeks['Rho']:.2f}"],
    ]

    table = ax_net.table(
        cellText=net_table_data,
        cellLoc="center",
        loc="center",
        bbox=[0, 0, 1, 1],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1, 2)

    # Style header row
    for i in range(2):
        table[(0, i)].set_facecolor("#0F4761")
        table[(0, i)].set_text_props(weight="bold", color="white")

    # Color code Greek values
    for i in range(1, len(net_table_data)):
        value = net_greeks[net_table_data[i][0]]
        if value > 0:
            table[(i, 1)].set_facecolor("#c8e6c9")  # Light green
        elif value < 0:
            table[(i, 1)].set_facecolor("#ffcdd2")  # Light red
        else:
            table[(i, 1)].set_facecolor("#eeeeee")  # Light gray

    ax_net.set_title(
        "Net Portfolio Greeks", fontsize=14, fontweight="bold", pad=10
    )

    # Panel 2: Net Greeks Bar Chart
    ax_bar = axes[0, 1]
    greek_names = list(net_greeks.keys())
    greek_values = list(net_greeks.values())

    colors = [
        "green" if v > 0 else "red" if v < 0 else "gray" for v in greek_values
    ]
    bars = ax_bar.barh(greek_names, greek_values, color=colors, alpha=0.7)
    ax_bar.axvline(x=0, color="black", linestyle="--", linewidth=1)
    ax_bar.set_xlabel("Value")
    ax_bar.set_title("Net Greeks Overview", fontsize=12, fontweight="bold")
    ax_bar.grid(True, alpha=0.3, axis="x")

    # Add value labels on bars
    for b, value in zip(bars, greek_values):
        if value != 0:
            label_x = value + (
                0.05
                * max(abs(v) for v in greek_values)
                * (1 if value > 0 else -1)
            )
            ax_bar.text(
                label_x,
                b.get_y() + b.get_height() / 2,
                f"{value:.2f}",
                ha="left" if value > 0 else "right",
                va="center",
                fontsize=9,
            )

    # Panel 3 & 4: Top Contributors for Delta and Gamma
    for idx, (greek_name, column_name) in enumerate(
        [("Delta", "position_delta"), ("Gamma", "position_gamma")]
    ):
        ax = axes[1, idx]

        # Calculate top contributors
        df_sorted = df.copy()
        df_sorted["abs_value"] = df_sorted[column_name].abs()
        df_sorted = df_sorted.nlargest(top_n, "abs_value")

        if len(df_sorted) > 0:
            # Create labels combining symbol, type, strike
            labels = [
                f"{row['symbol']} {row['type'].upper()[:1]}{row['strike']:.0f}"
                for _, row in df_sorted.iterrows()
            ]
            values = df_sorted[column_name].tolist()
            colors_contrib = ["green" if v > 0 else "red" for v in values]

            bars = ax.barh(labels, values, color=colors_contrib, alpha=0.7)
            ax.axvline(x=0, color="black", linestyle="--", linewidth=1)
            ax.set_xlabel(greek_name)
            ax.set_title(
                f"Top {top_n} {greek_name} Contributors",
                fontsize=11,
                fontweight="bold",
            )
            ax.grid(True, alpha=0.3, axis="x")

            # Add value labels
            for b, value in zip(bars, values):
                if value != 0:
                    label_x = value + (
                        0.05
                        * max(abs(v) for v in values)
                        * (1 if value > 0 else -1)
                    )
                    ax.text(
                        label_x,
                        b.get_y() + b.get_height() / 2,
                        f"{value:.2f}",
                        ha="left" if value > 0 else "right",
                        va="center",
                        fontsize=8,
                    )
        else:
            ax.text(
                0.5,
                0.5,
                "No data",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.axis("off")

    # Detailed panels (if requested)
    if show_detailed:
        # Panel 5: Top Vega Contributors
        ax = axes[2, 0]
        df_sorted = df.copy()
        df_sorted["abs_value"] = df_sorted["position_vega"].abs()
        df_sorted = df_sorted.nlargest(top_n, "abs_value")

        if len(df_sorted) > 0:
            labels = [
                f"{row['symbol']} {row['type'].upper()[:1]}{row['strike']:.0f}"
                for _, row in df_sorted.iterrows()
            ]
            values = df_sorted["position_vega"].tolist()
            colors_contrib = ["green" if v > 0 else "red" for v in values]

            bars = ax.barh(labels, values, color=colors_contrib, alpha=0.7)
            ax.axvline(x=0, color="black", linestyle="--", linewidth=1)
            ax.set_xlabel("Vega")
            ax.set_title(
                f"Top {top_n} Vega Contributors", fontsize=11, fontweight="bold"
            )
            ax.grid(True, alpha=0.3, axis="x")
        else:
            ax.text(
                0.5,
                0.5,
                "No data",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.axis("off")

        # Panel 6: Top Theta Contributors
        ax = axes[2, 1]
        df_sorted = df.copy()
        df_sorted["abs_value"] = df_sorted["position_theta"].abs()
        df_sorted = df_sorted.nlargest(top_n, "abs_value")

        if len(df_sorted) > 0:
            labels = [
                f"{row['symbol']} {row['type'].upper()[:1]}{row['strike']:.0f}"
                for _, row in df_sorted.iterrows()
            ]
            values = df_sorted["position_theta"].tolist()
            colors_contrib = ["green" if v > 0 else "red" for v in values]

            bars = ax.barh(labels, values, color=colors_contrib, alpha=0.7)
            ax.axvline(x=0, color="black", linestyle="--", linewidth=1)
            ax.set_xlabel("Theta ($/day)")
            ax.set_title(
                f"Top {top_n} Theta Contributors",
                fontsize=11,
                fontweight="bold",
            )
            ax.grid(True, alpha=0.3, axis="x")
        else:
            ax.text(
                0.5,
                0.5,
                "No data",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.axis("off")

        # Panel 7: Greeks by Strike
        ax = axes[3, 0]
        greek_by_strike = df.groupby("strike").agg(
            {"position_delta": "sum", "position_gamma": "sum"}
        )

        if len(greek_by_strike) > 0:
            greek_by_strike.plot(kind="bar", ax=ax, alpha=0.7, width=0.7)
            ax.set_xlabel("Strike Price")
            ax.set_ylabel("Greek Value")
            ax.set_title("Greeks by Strike", fontsize=11, fontweight="bold")
            ax.legend(["Delta", "Gamma"], loc="best")
            ax.grid(True, alpha=0.3, axis="y")
            ax.tick_params(axis="x", rotation=45)
        else:
            ax.text(
                0.5,
                0.5,
                "No data",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.axis("off")

        # Panel 8: Greeks by Maturity
        ax = axes[3, 1]
        df["maturity_label"] = pd.to_datetime(df["maturity"]).dt.strftime(
            "%Y-%m-%d"
        )
        greek_by_maturity = df.groupby("maturity_label").agg(
            {"position_delta": "sum", "position_gamma": "sum"}
        )

        if len(greek_by_maturity) > 0:
            greek_by_maturity.plot(kind="bar", ax=ax, alpha=0.7, width=0.7)
            ax.set_xlabel("Maturity Date")
            ax.set_ylabel("Greek Value")
            ax.set_title("Greeks by Maturity", fontsize=11, fontweight="bold")
            ax.legend(["Delta", "Gamma"], loc="best")
            ax.grid(True, alpha=0.3, axis="y")
            ax.tick_params(axis="x", rotation=45)
        else:
            ax.text(
                0.5,
                0.5,
                "No data",
                ha="center",
                va="center",
                transform=ax.transAxes,
            )
            ax.axis("off")

    plt.tight_layout()
    return fig


# ============================================================================
# Module Metadata
# ============================================================================

__all__ = [
    "OptionCharts",
    "plot_pnl_diagram",
    "plot_pnl_distribution_with_metrics",
    "plot_greeks_by_strike",
    "plot_theta_analysis",
    "plot_greeks_consolidated",
]
