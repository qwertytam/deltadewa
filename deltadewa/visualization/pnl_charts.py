"""P&L diagram plotting methods for option charts."""

from typing import TYPE_CHECKING, Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from scipy import stats

from deltadewa import constants as const
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.clock import days_between
from deltadewa.colours import DEFAULT_PALETTE

# Import centralized formatters
from deltadewa.formatters.values import format_currency_for_axis
from deltadewa.formatters.values import (
    format_spot_with_pct as format_spot_with_pct_centralized,
)
from deltadewa.spot_utils import generate_spot_range

if TYPE_CHECKING:
    from deltadewa.visualization._protocols import _VisualizationProtocol


class PnLChartsMixin:
    """Mixin providing P&L diagram plotting methods."""

    if TYPE_CHECKING:
        _self: "_VisualizationProtocol[Any]"

    def plot_pnl_diagram(
        self: "_VisualizationProtocol[Any]",
        spot_range_pct: float = 40.0,
        num_points: int = 300,
        show_underlying: bool = True,
        figsize: tuple[int, int] = (14, 12),
    ) -> Figure:
        """Create comprehensive P&L diagram at expiration.

        Shows two panels:
        1. Options-only P&L
        2. Total portfolio P&L (options + underlying)

        Includes breakeven points, max loss/profit markers, and profit/loss
        zones.

        Args:
            spot_range_pct: Percentage range around current spot (default: 40%)
            num_points: Number of points in spot price range
            show_underlying: Whether to show underlying P&L panel
            figsize: Figure size tuple

        Returns:
            Matplotlib Figure object

        """
        # Create spot price range
        # Note: spot_range_pct is symmetric ± percentage (e.g., 40 means 60% to
        # 140%)
        # Convert to spot_min_pct and spot_max_pct for generate_spot_range
        spot_min_pct = 100 - spot_range_pct
        spot_max_pct = 100 + spot_range_pct
        spot_range = generate_spot_range(
            spot_price=self.portfolio.spot_price,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
            num_points=num_points,
        )

        # Calculate P&L curves using vectorized operations
        pnl_options = self.portfolio.vectorized_pnl_at_expiry(
            spot_range,
            include_underlying=False,
        )
        pnl_total = self.portfolio.vectorized_pnl_at_expiry(
            spot_range,
            include_underlying=True,
        )

        # Get risk/reward metrics
        analyzer = PortfolioAnalyzer(self.portfolio)
        analysis = analyzer.risk_reward_analysis()

        # Determine expiration label
        expiry_label = self._get_expiry_label()
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
        self: "_VisualizationProtocol[Any]",
        spot_range_pct: float = 100.0,
        num_points: int = 1000,
        figsize: tuple[int, int] = (16, 8),
        include_underlying: bool = True,
        show_probability_overlay: bool = False,
    ) -> Figure:
        """Create P&L distribution chart.

        Charts created with annotated key metrics and probability analysis.

        Shows:
        - P&L curve at maturity
        - Break-even points (black diamonds with vertical dashed lines)
        - Max loss point (red triangle down)
        - Max profit point (green triangle up)
        - Expected value from risk analysis (gold star)
        - Current spot marker (vertical dashed line)
        - Profit/loss zones (green/red shading)
        - Probability density function (light blue background)
        - 5th and 95th percentile levels (purple dotted lines - 90% confidence
        interval)
        - X-axis shows both dollar values and % change from current spot

        Args:
            spot_range_pct: Percentage range around current spot (default: 100%)
            num_points: Resolution of P&L curve (default: 1000)
            figsize: Figure dimensions (default: (16, 8))
            include_underlying: Include underlying position in P&L (default:
            True)
            show_probability_overlay: Reserved for future use to toggle PDF
            overlay (default: False). Currently, PDF overlay is always shown.

        Returns:
            Matplotlib Figure object with P&L distribution and probability
            overlay

        """
        # Note: show_probability_overlay parameter is reserved for future
        # implementation
        # Currently, PDF overlay is always displayed
        _ = show_probability_overlay

        # Generate spot price range
        # Note: spot_range_pct is symmetric ± percentage (e.g., 100 means 0% to
        # 200%)
        current_spot = self.portfolio.spot_price
        spot_range = generate_spot_range(
            spot_price=current_spot,
            spot_min_pct=100 - spot_range_pct,
            spot_max_pct=100 + spot_range_pct,
            num_points=num_points,
        )

        # Calculate P&L curve using vectorized operations
        pnl_values = self.portfolio.vectorized_pnl_at_expiry(
            spot_range,
            include_underlying=include_underlying,
        )

        # Get risk/reward metrics
        # CRITICAL: Pass spot_range=None to allow comprehensive range check for
        # max loss/profit
        # The visualization uses spot_range only for the chart display
        analysis = PortfolioAnalyzer(self.portfolio).risk_reward_analysis(
            spot_range=None,
        )

        # Use pre-calculated Monte Carlo expected value if available to ensure
        # consistency between the main analysis and the chart visualization
        mc_results = self.portfolio.monte_carlo_results
        if (
            mc_results is not None
            and isinstance(mc_results, dict)
            and "expected_pnl" in mc_results
        ):
            analysis["expected_pnl"] = mc_results["expected_pnl"]

        # Create figure and plot main P&L curve
        fig, ax = plt.subplots(1, 1, figsize=figsize)

        # Set figure and axes backgrounds to transparent for better PDF
        # visibility
        fig.patch.set_alpha(0.0)
        ax.patch.set_alpha(0.0)

        time_to_maturity = self._compute_time_to_maturity()
        (
            pdf_baseline,
            pdf_plot_values,
            spot_5th_percentile,
            spot_95th_percentile,
        ) = self._compute_pdf_overlay_and_percentiles(
            spot_range,
            pnl_values,
            current_spot,
            time_to_maturity,
        )
        self._shade_probability_density(
            ax,
            spot_range,
            pdf_baseline,
            pdf_plot_values,
        )

        # Determine visible range bounds
        spot_range_min = spot_range.min()
        spot_range_max = spot_range.max()
        is_5th_in_range = (
            spot_range_min <= spot_5th_percentile <= spot_range_max
        )
        is_95th_in_range = (
            spot_range_min <= spot_95th_percentile <= spot_range_max
        )
        self._annotate_percentile_lines(
            ax,
            is_5th_in_range,
            is_95th_in_range,
            spot_5th_percentile,
            spot_95th_percentile,
        )

        ax.plot(
            spot_range,
            pnl_values,
            linewidth=3,
            color=DEFAULT_PALETTE.medium_background,
            label="P&L at Maturity",
            zorder=3,
        )

        # Add annotations for percentile levels
        y_annotation = pnl_values.max() * 0.95
        y_mid = (pnl_values.max() + pnl_values.min()) / 2
        self._annotate_percentile_label(
            ax,
            "5%",
            spot_5th_percentile,
            is_5th_in_range,
            spot_range_min,
            (y_annotation, y_mid),
            "left",
        )
        self._annotate_percentile_label(
            ax,
            "95%",
            spot_95th_percentile,
            is_95th_in_range,
            spot_range_max,
            (y_annotation, y_mid),
            "right",
        )

        self._shade_profit_loss_zones(ax, spot_range, pnl_values)
        self._annotate_current_spot_marker(ax, current_spot, pnl_values)

        self._annotate_breakevens(
            ax,
            analysis,
            "breakeven_total" if include_underlying else "breakeven_options",
            include_underlying,
        )

        self._annotate_max_loss(
            ax,
            analysis,
            "max_loss_total" if include_underlying else "max_loss_options",
            spot_range_min,
            spot_range_max,
            pnl_values,
        )

        self._annotate_max_profit(
            ax,
            analysis,
            (
                "max_profit_total"
                if include_underlying
                else "max_profit_options"
            ),
        )

        self._annotate_expected_value(ax, analysis, spot_range, pnl_values)

        self._format_pnl_distribution_axes(
            ax,
            include_underlying,
            current_spot,
        )

        # Return figure
        plt.tight_layout()
        return fig

    def _compute_time_to_maturity(
        self: "_VisualizationProtocol[Any]",
    ) -> float:
        """Compute years to nearest position maturity, else 30-day default."""
        if self.portfolio.positions:
            min_maturity = min(
                pos.option.maturity_date for pos in self.portfolio.positions
            )
            days_to_maturity = max(
                1,
                days_between(self.portfolio.valuation_date, min_maturity),
            )
            return float(days_to_maturity / const.DAYS_PER_YEAR)
        # Default to 30 days
        return const.CALENDAR_DAYS_PER_MONTH / const.DAYS_PER_YEAR

    def _compute_pdf_overlay_and_percentiles(
        self: "_VisualizationProtocol[Any]",
        spot_range: np.ndarray[Any, np.dtype[Any]],
        pnl_values: np.ndarray[Any, np.dtype[Any]],
        current_spot: float,
        time_to_maturity: float,
    ) -> tuple[float, np.ndarray[Any, np.dtype[Any]], float, float]:
        """Compute the terminal-spot PDF overlay and 5th/95th percentiles.

        Returns the PDF baseline and scaled plot values (for shading under
        the P&L curve) plus the 5th and 95th percentile spot prices, using
        log-normal (GBM) parameters.
        """
        volatility = self.portfolio.volatility
        risk_free_rate = self.portfolio.risk_free_rate
        dividend_yield = self.portfolio.dividend_yield

        # Log-normal parameters
        mu = (
            np.log(current_spot)
            + (risk_free_rate - dividend_yield - 0.5 * volatility**2)
            * time_to_maturity
        )
        sigma = volatility * np.sqrt(time_to_maturity)

        # Calculate PDF values, scaled to fit the full height of the chart
        pdf_values = (1 / (spot_range * sigma * np.sqrt(2 * np.pi))) * np.exp(
            -((np.log(spot_range) - mu) ** 2) / (2 * sigma**2),
        )
        pdf_height = pnl_values.max() - pnl_values.min()
        pdf_scaled = (pdf_values / pdf_values.max()) * pdf_height
        pdf_baseline = pnl_values.min()
        pdf_plot_values = pdf_baseline + pdf_scaled

        # Calculate 5th and 95th percentile spot prices (90% confidence
        # interval) using the analytical log-normal inverse CDF
        try:
            z_5th = stats.norm.ppf(0.05)
            z_95th = stats.norm.ppf(0.95)
        except ImportError:
            # Fallback standard-normal quantile approximation
            z_5th = -1.6449
            z_95th = 1.6449

        spot_5th_percentile = np.exp(mu + sigma * z_5th)
        spot_95th_percentile = np.exp(mu + sigma * z_95th)

        return (
            pdf_baseline,
            pdf_plot_values,
            spot_5th_percentile,
            spot_95th_percentile,
        )

    def _shade_probability_density(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        spot_range: np.ndarray[Any, np.dtype[Any]],
        pdf_baseline: float,
        pdf_plot_values: np.ndarray[Any, np.dtype[Any]],
    ) -> None:
        """Shade the terminal-spot probability density under the P&L curve."""
        # Plot PDF on MAIN axis with zorder=1 (behind other elements)
        ax.fill_between(
            spot_range,
            pdf_baseline,
            pdf_plot_values,
            color=DEFAULT_PALETTE.medium_background,
            alpha=0.4,
            zorder=1,
        )

    def _annotate_percentile_lines(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        is_5th_in_range: bool,
        is_95th_in_range: bool,
        spot_5th_percentile: float,
        spot_95th_percentile: float,
    ) -> None:
        """Draw vertical dashed lines at the 5th/95th percentile spots."""
        if is_5th_in_range:
            ax.axvline(
                spot_5th_percentile,
                color=DEFAULT_PALETTE.dark_background,
                linestyle=":",
                linewidth=2,
                alpha=0.7,
                zorder=2,
                label="5% Probability Level",
            )
        if is_95th_in_range:
            ax.axvline(
                spot_95th_percentile,
                color=DEFAULT_PALETTE.dark_background,
                linestyle=":",
                linewidth=2,
                alpha=0.7,
                zorder=2,
                label="95% Probability Level",
            )

    def _annotate_percentile_label(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        pct_label: str,
        spot_value: float,
        in_range: bool,
        edge_spot: float,
        y_positions: tuple[float, float],
        side: str,
    ) -> None:
        """Label a percentile spot in-range, or point to it from the edge.

        Args:
            ax: Matplotlib axes.
            pct_label: e.g. "5%" or "95%".
            spot_value: The percentile spot price.
            in_range: Whether spot_value falls within the visible x-range.
            edge_spot: Chart edge to anchor the out-of-range callout to.
            y_positions: (y_annotation, y_mid) — text-box Y position for the
                in-range case, callout Y position for the out-of-range case.
            side: "left" or "right" — edge/arrow direction to use.

        """
        y_annotation, y_mid = y_positions
        if in_range:
            ax.text(
                spot_value,
                y_annotation,
                f"{pct_label} @ ${spot_value:,.0f}",
                ha="center",
                va="top",
                fontsize=9,
                color=DEFAULT_PALETTE.dark_background,
                fontweight="bold",
                bbox={
                    "boxstyle": "round,pad=0.3",
                    "facecolor": DEFAULT_PALETTE.white,
                    "edgecolor": DEFAULT_PALETTE.dark_background,
                    "alpha": 0.8,
                },
            )
            return

        offset = (30, 0) if side == "left" else (-30, 0)
        ax.annotate(
            f"{pct_label}\n${spot_value:,.0f}",
            xy=(edge_spot, y_mid),
            xytext=offset,
            textcoords="offset points",
            fontsize=9,
            color=DEFAULT_PALETTE.dark_background,
            fontweight="bold",
            ha=side,
            va="center",
            bbox={
                "boxstyle": "round,pad=0.3",
                "facecolor": DEFAULT_PALETTE.white,
                "edgecolor": DEFAULT_PALETTE.dark_background,
                "alpha": 0.8,
            },
            arrowprops={
                "arrowstyle": "<-",
                "color": DEFAULT_PALETTE.dark_background,
                "lw": 1.5,
            },
        )

    def _shade_profit_loss_zones(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        spot_range: np.ndarray[Any, np.dtype[Any]],
        pnl_values: np.ndarray[Any, np.dtype[Any]],
    ) -> None:
        """Shade profit (P&L >= 0) and loss (P&L < 0) zones under the curve."""
        ax.fill_between(
            spot_range,
            pnl_values,
            0,
            where=(pnl_values >= 0).tolist(),
            color=DEFAULT_PALETTE.negative,
            alpha=0.2,
            label="Profit Zone",
        )
        ax.fill_between(
            spot_range,
            pnl_values,
            0,
            where=(pnl_values < 0).tolist(),
            color=DEFAULT_PALETTE.negative,
            alpha=0.2,
            label="Loss Zone",
        )

    def _annotate_current_spot_marker(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        current_spot: float,
        pnl_values: np.ndarray[Any, np.dtype[Any]],
    ) -> None:
        """Draw the zero line, current-spot line, and its label."""
        ax.axhline(
            0,
            color=DEFAULT_PALETTE.black,
            linestyle="-",
            linewidth=1,
            alpha=0.5,
        )
        ax.axvline(
            current_spot,
            color=DEFAULT_PALETTE.black,
            linestyle="--",
            linewidth=2,
            alpha=0.7,
        )
        # Add Current Spot label at top of line
        ax.text(
            current_spot,
            pnl_values.max() * 0.95,
            f"Current Spot\n${current_spot:,.0f}",
            ha="center",
            va="top",
            fontsize=9,
            fontweight="bold",
            color=DEFAULT_PALETTE.black,
            bbox={
                "boxstyle": "round,pad=0.3",
                "facecolor": DEFAULT_PALETTE.white,
                "edgecolor": DEFAULT_PALETTE.black,
                "alpha": 0.8,
            },
        )

    def _annotate_breakevens(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        analysis: dict[str, Any],
        be_key: str,
        include_underlying: bool,
    ) -> None:
        """Mark break-even points with a diamond, line, and $-value label."""
        if not analysis.get(be_key):
            return
        for i, be in enumerate(analysis[be_key]):
            be_pnl = self.portfolio.calculate_pnl_at_expiry(
                be,
                include_underlying=include_underlying,
            )
            # Add vertical dashed line at break-even
            ax.axvline(
                be,
                color=DEFAULT_PALETTE.medium_grey,
                linestyle="--",
                linewidth=1.5,
                alpha=0.6,
                zorder=2,
            )

            # Plot marker
            ax.plot(
                be,
                be_pnl,
                marker="D",
                markersize=12,
                markeredgewidth=2,
                markerfacecolor=DEFAULT_PALETTE.yellow,
                markeredgecolor=DEFAULT_PALETTE.black,
                zorder=5,
            )
            # Add annotation
            ax.annotate(
                f"BE ${be:.2f}",
                xy=(be, be_pnl),
                xytext=(0, 30 if i % 2 == 0 else -40),
                textcoords="offset points",
                fontsize=10,
                fontweight="bold",
                ha="center",
                bbox={
                    "boxstyle": "round,pad=0.5",
                    "facecolor": DEFAULT_PALETTE.yellow,
                    "alpha": 0.7,
                    "edgecolor": DEFAULT_PALETTE.black,
                },
                arrowprops={
                    "arrowstyle": "->",
                    "connectionstyle": "arc3,rad=0",
                    "lw": 1.5,
                },
            )

    def _annotate_max_loss(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        analysis: dict[str, Any],
        ml_key: str,
        spot_range_min: float,
        spot_range_max: float,
        pnl_values: np.ndarray[Any, np.dtype[Any]],
    ) -> None:
        """Mark the maximum-loss point, or point to it if off-chart."""
        max_loss_info = analysis[ml_key]
        if max_loss_info["is_unlimited"]:
            return

        ml_spot = max_loss_info["spot_at_max_loss"]
        ml_val = max_loss_info["max_loss"]

        # Check if max loss spot is within visible range
        is_ml_in_range = spot_range_min <= ml_spot <= spot_range_max

        if is_ml_in_range:
            # Plot marker at actual location
            ax.plot(
                ml_spot,
                ml_val,
                marker="v",
                markersize=15,
                markeredgewidth=2,
                markerfacecolor=DEFAULT_PALETTE.negative,
                markeredgecolor=DEFAULT_PALETTE.negative,
                zorder=5,
            )
            # Add annotation
            ax.annotate(
                f"ML ${ml_val:,.0f}",
                xy=(ml_spot, ml_val),
                xytext=(0, -50),
                textcoords="offset points",
                fontsize=10,
                fontweight="bold",
                ha="center",
                bbox={
                    "boxstyle": "round,pad=0.5",
                    "facecolor": DEFAULT_PALETTE.negative_faded,
                    "alpha": 0.8,
                    "edgecolor": DEFAULT_PALETTE.negative,
                },
                arrowprops={
                    "arrowstyle": "->",
                    "connectionstyle": "arc3,rad=0",
                    "lw": 1.5,
                },
            )
            return

        # Max loss is outside visible range - show arrow at edge
        if ml_spot < spot_range_min:
            edge_spot = spot_range_min
            edge_pnl = pnl_values[0]
            text_offset = (40, -30)
            ha = "left"
        else:
            edge_spot = spot_range_max
            edge_pnl = pnl_values[-1]
            text_offset = (-40, -30)
            ha = "right"

        ax.annotate(
            f"ML ${ml_val:,.0f} @ ${ml_spot:,.0f}",
            xy=(edge_spot, edge_pnl),
            xytext=text_offset,
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            ha=ha,
            bbox={
                "boxstyle": "round,pad=0.5",
                "facecolor": DEFAULT_PALETTE.negative_faded,
                "alpha": 0.8,
                "edgecolor": DEFAULT_PALETTE.negative,
            },
            arrowprops={
                "arrowstyle": "<-",
                "connectionstyle": "arc3,rad=0",
                "lw": 1.5,
                "color": DEFAULT_PALETTE.negative,
            },
        )

    def _annotate_max_profit(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        analysis: dict[str, Any],
        mp_key: str,
    ) -> None:
        """Mark the maximum-profit point on the P&L curve."""
        max_profit_info = analysis[mp_key]
        if max_profit_info["is_unlimited"]:
            return

        mp_spot = max_profit_info["spot_at_max_profit"]
        mp_val = max_profit_info["max_profit"]
        # Plot marker
        ax.plot(
            mp_spot,
            mp_val,
            marker="^",
            markersize=15,
            markeredgewidth=2,
            markerfacecolor=DEFAULT_PALETTE.negative,
            markeredgecolor=DEFAULT_PALETTE.positive,
            zorder=5,
        )
        # Add annotation
        ax.annotate(
            f"MP ${mp_val:,.0f}",
            xy=(mp_spot, mp_val),
            xytext=(0, 50),
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            ha="center",
            bbox={
                "boxstyle": "round,pad=0.5",
                "facecolor": DEFAULT_PALETTE.positive_faded,
                "alpha": 0.8,
                "edgecolor": DEFAULT_PALETTE.positive,
            },
            arrowprops={
                "arrowstyle": "->",
                "connectionstyle": "arc3,rad=0",
                "lw": 1.5,
            },
        )

    def _annotate_expected_value(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        analysis: dict[str, Any],
        spot_range: np.ndarray[Any, np.dtype[Any]],
        pnl_values: np.ndarray[Any, np.dtype[Any]],
    ) -> None:
        """Mark the expected-value point closest to it on the P&L curve."""
        expected_pnl = analysis.get("expected_pnl", 0)
        if expected_pnl is None:
            return

        # Find the spot price closest to the expected value on P&L curve
        idx_closest = np.argmin(np.abs(pnl_values - expected_pnl))
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
            f"EV ${expected_pnl:,.0f}",
            xy=(ev_spot, ev_pnl),
            xytext=(50, 20),
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            ha="center",
            bbox={
                "boxstyle": "round,pad=0.5",
                "facecolor": DEFAULT_PALETTE.orange_faded,
                "alpha": 0.8,
                "edgecolor": "orange",
            },
            arrowprops={
                "arrowstyle": "->",
                "connectionstyle": "arc3,rad=0.2",
                "lw": 1.5,
            },
        )

    def _format_pnl_distribution_axes(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        include_underlying: bool,
        current_spot: float,
    ) -> None:
        """Apply axis labels, title, grid, and currency/pct tick formatters."""
        ax.set_xlabel(
            "Spot Price at Maturity ($)",
            fontsize=13,
            fontweight="bold",
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

        # Apply currency formatters
        ax.yaxis.set_major_formatter(FuncFormatter(format_currency_for_axis))

        # Custom x-axis formatter showing price + % change (use centralized
        # formatter)
        def format_spot_with_pct(
            x: float,
            pos: int | None = None,
        ) -> str:  # pylint: disable=unused-argument
            """Format x-axis to show spot price and % change from spot."""
            return format_spot_with_pct_centralized(x, current_spot, pos)

        ax.xaxis.set_major_formatter(FuncFormatter(format_spot_with_pct))
        ax.tick_params(
            axis="x",
            which="major",
            pad=8,
        )  # Add padding for two-line labels

    def _plot_pnl_panel(
        self: "_VisualizationProtocol[Any]",
        ax: Axes,
        spot_range: np.ndarray[Any, np.dtype[Any]],
        pnl_values: (list[float] | np.ndarray[Any, np.dtype[Any]]),
        analysis: dict[str, Any],
        analysis_key: str,
        title: str,
    ) -> None:
        """Plot a single P&L panel.

        Args:
            ax: Matplotlib axes
            spot_range: Array of spot prices
            pnl_values: P&L values corresponding to spot_range
            analysis: Risk/reward analysis dictionary
            analysis_key: 'options' or 'total'
            title: Chart title

        """
        # Reference lines
        ax.axhline(
            y=0,
            color=DEFAULT_PALETTE.black,
            linestyle="--",
            linewidth=0.8,
            alpha=0.5,
        )
        ax.axvline(
            x=self.portfolio.spot_price,
            color=DEFAULT_PALETTE.medium_background,
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
            color=DEFAULT_PALETTE.negative,
            alpha=0.2,
            label="Profit Zone",
        )
        ax.fill_between(
            spot_range,
            pnl_values,
            0,
            where=(pnl_array < 0).tolist(),
            color=DEFAULT_PALETTE.negative,
            alpha=0.2,
            label="Loss Zone",
        )

        # P&L curve
        color = DEFAULT_PALETTE.dark_background
        label = "Options P&L" if analysis_key == "options" else "Total P&L"
        ax.plot(spot_range, pnl_values, linewidth=2.5, color=color, label=label)

        # Breakeven points
        be_key = f"breakeven_{analysis_key}"
        if analysis.get(be_key):
            for i, be in enumerate(analysis[be_key]):
                be_pnl = self.portfolio.calculate_pnl_at_expiry(
                    be,
                    include_underlying=(analysis_key == "total"),
                )
                ax.plot(
                    be,
                    be_pnl,
                    "ko",
                    markersize=10,
                    markeredgewidth=2,
                    markerfacecolor=DEFAULT_PALETTE.yellow,
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
                markerfacecolor=DEFAULT_PALETTE.negative,
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
                markerfacecolor=DEFAULT_PALETTE.negative,
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
                color=DEFAULT_PALETTE.negative,
                arrowprops={
                    "arrowstyle": "->",
                    "color": DEFAULT_PALETTE.negative,
                    "lw": 2,
                },
            )

        # Formatting
        ax.set_xlabel(
            "Spot Price at Expiration ($)",
            fontsize=12,
            fontweight="bold",
        )
        ax.set_ylabel("P&L ($)", fontsize=12, fontweight="bold")
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=10)
        ax.yaxis.set_major_formatter(FuncFormatter(format_currency_for_axis))
