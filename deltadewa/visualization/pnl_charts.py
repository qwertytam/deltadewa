"""P&L diagram plotting methods for option charts."""

from typing import TYPE_CHECKING, Dict, List, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from scipy import stats  # type: ignore

from deltadewa import constants as const
from deltadewa.colours import DEFAULT_PALETTE

# Import centralized formatters
from deltadewa.formatters import (
    format_spot_with_pct as format_spot_with_pct_centralized,
    format_currency_for_axis,
)
from deltadewa.analysis import PortfolioAnalyzer

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolioBase


class PnLChartsMixin:
    """Mixin providing P&L diagram plotting methods."""

    if TYPE_CHECKING:
        portfolio: "OptionPortfolioBase"

        def _get_expiry_label(self) -> str: ...

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

        # Calculate P&L curves using vectorized operations
        pnl_options = self.portfolio.vectorized_pnl_at_expiry(  # type: ignore
            spot_range, include_underlying=False
        )
        pnl_total = self.portfolio.vectorized_pnl_at_expiry(  # type: ignore
            spot_range, include_underlying=True
        )

        # Get risk/reward metrics
        analyzer = PortfolioAnalyzer(self.portfolio)
        analysis = analyzer.risk_reward_analysis()

        # Determine expiration label
        # pylint: disable=assignment-from-no-return
        expiry_label = (  # type: ignore
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
        spot_range_pct: float = 100.0,
        num_points: int = 1000,
        figsize: Tuple[int, int] = (16, 8),
        include_underlying: bool = True,
        show_probability_overlay: bool = False,
    ) -> Figure:
        """
        Create P&L distribution chart with annotated key metrics and probability analysis.

        Shows:
        - P&L curve at maturity
        - Break-even points (black diamonds with vertical dashed lines)
        - Max loss point (red triangle down)
        - Max profit point (green triangle up)
        - Expected value from risk analysis (gold star)
        - Current spot marker (vertical dashed line)
        - Profit/loss zones (green/red shading)
        - Probability density function (light blue background)
        - 5th and 95th percentile levels (purple dotted lines - 90% confidence interval)
        - X-axis shows both dollar values and % change from current spot

        Args:
            spot_range_pct: Percentage range around current spot (default: 100%)
            num_points: Resolution of P&L curve (default: 1000)
            figsize: Figure dimensions (default: (16, 8))
            include_underlying: Include underlying position in P&L (default: True)
            show_probability_overlay: Reserved for future use to toggle PDF overlay
                (default: False). Currently, PDF overlay is always shown.

        Returns:
            Matplotlib Figure object with P&L distribution and probability overlay
        """
        # Note: show_probability_overlay parameter is reserved for future implementation
        # Currently, PDF overlay is always displayed
        _ = show_probability_overlay

        # Generate spot price range
        current_spot = self.portfolio.spot_price
        spot_min = max(0.01, current_spot * (1 - spot_range_pct / 100))
        spot_max = current_spot * (1 + spot_range_pct / 100)
        spot_range = np.linspace(spot_min, spot_max, num_points)

        # Calculate P&L curve using vectorized operations
        pnl_values = self.portfolio.vectorized_pnl_at_expiry(  # type: ignore
            spot_range, include_underlying=include_underlying
        )

        # Get risk/reward metrics
        # CRITICAL: Pass spot_range=None to allow comprehensive range check for max loss/profit
        # The visualization uses spot_range only for the chart display
        analyzer = PortfolioAnalyzer(self.portfolio)
        analysis = analyzer.risk_reward_analysis(spot_range=None)

        # Use pre-calculated Monte Carlo expected value if available to ensure consistency
        # between the main analysis and the chart visualization
        mc_results = self.portfolio.monte_carlo_results
        if (
            mc_results is not None
            and isinstance(mc_results, dict)
            and "expected_pnl" in mc_results
        ):
            analysis["expected_value"] = mc_results["expected_pnl"]

        # Create figure and plot main P&L curve
        fig, ax = plt.subplots(1, 1, figsize=figsize)

        # Set figure and axes backgrounds to transparent for better PDF visibility
        fig.patch.set_alpha(0.0)
        ax.patch.set_alpha(0.0)

        # Calculate probability density function for spot prices at maturity
        # Use the nearest maturity date for time horizon
        if self.portfolio.positions:
            min_maturity = min(
                pos.option.maturity_date for pos in self.portfolio.positions
            )
            days_to_maturity = max(
                1, (min_maturity - self.portfolio.valuation_date).days
            )
            time_to_maturity = days_to_maturity / const.DAYS_PER_YEAR
        else:
            time_to_maturity = (
                const.CALENDAR_DAYS_PER_MONTH / const.DAYS_PER_YEAR
            )  # Default to 30 days

        # Calculate log-normal PDF for terminal spot prices (GBM assumption)
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

        # Calculate PDF values
        pdf_values = (1 / (spot_range * sigma * np.sqrt(2 * np.pi))) * np.exp(
            -((np.log(spot_range) - mu) ** 2) / (2 * sigma**2)
        )

        # Scale PDF to fit full height of chart
        pnl_range = pnl_values.max() - pnl_values.min()
        pdf_height = pnl_range  # Full height

        # Normalize PDF to this height
        pdf_scaled = (pdf_values / pdf_values.max()) * pdf_height

        # Position PDF at bottom of chart
        pdf_baseline = pnl_values.min()
        pdf_plot_values = pdf_baseline + pdf_scaled

        # Plot PDF on MAIN axis with zorder=1 (behind other elements)
        ax.fill_between(
            spot_range,
            pdf_baseline,
            pdf_plot_values,
            color=DEFAULT_PALETTE.medium_background,
            alpha=0.4,
            zorder=1,
        )

        # Calculate 5th and 95th percentile spot prices (90% confidence interval)
        # Using analytical log-normal distribution (inverse CDF)
        # For log-normal with parameters mu and sigma:
        # percentile_p = exp(mu + sigma * z_p) where z_p is the standard normal quantile
        try:
            z_5th = stats.norm.ppf(
                0.05
            )  # Standard normal quantile for 5th percentile
            z_95th = stats.norm.ppf(
                0.95
            )  # Standard normal quantile for 95th percentile
        except ImportError:
            # Fallback to approximation if scipy not available
            # Using inverse error function approximation for standard normal quantiles
            # z_0.05 ≈ -1.645, z_0.95 ≈ 1.645
            z_5th = -1.6449
            z_95th = 1.6449

        spot_5th_percentile = np.exp(mu + sigma * z_5th)
        spot_95th_percentile = np.exp(mu + sigma * z_95th)

        # Determine visible range bounds
        spot_range_min = spot_range.min()
        spot_range_max = spot_range.max()

        # Check if percentiles are within visible range
        is_5th_in_range = (
            spot_range_min <= spot_5th_percentile <= spot_range_max
        )
        is_95th_in_range = (
            spot_range_min <= spot_95th_percentile <= spot_range_max
        )

        # Add vertical dashed lines for percentiles only if in range
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

        if is_5th_in_range:
            ax.text(
                spot_5th_percentile,
                y_annotation,
                f"5% @ ${spot_5th_percentile:,.0f}",
                ha="center",
                va="top",
                fontsize=9,
                color=DEFAULT_PALETTE.dark_background,
                fontweight="bold",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor=DEFAULT_PALETTE.white,
                    edgecolor=DEFAULT_PALETTE.dark_background,
                    alpha=0.8,
                ),
            )
        else:
            # 5th percentile is below visible range - show arrow on left edge
            ax.annotate(
                f"5%\n${spot_5th_percentile:,.0f}",
                xy=(spot_range_min, y_mid),
                xytext=(30, 0),
                textcoords="offset points",
                fontsize=9,
                color=DEFAULT_PALETTE.dark_background,
                fontweight="bold",
                ha="left",
                va="center",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor=DEFAULT_PALETTE.white,
                    edgecolor=DEFAULT_PALETTE.dark_background,
                    alpha=0.8,
                ),
                arrowprops=dict(
                    arrowstyle="<-",
                    color=DEFAULT_PALETTE.dark_background,
                    lw=1.5,
                ),
            )

        if is_95th_in_range:
            ax.text(
                spot_95th_percentile,
                y_annotation,
                f"95% @ ${spot_95th_percentile:,.0f}",
                ha="center",
                va="top",
                fontsize=9,
                color=DEFAULT_PALETTE.dark_background,
                fontweight="bold",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor=DEFAULT_PALETTE.white,
                    edgecolor=DEFAULT_PALETTE.dark_background,
                    alpha=0.8,
                ),
            )
        else:
            # 95th percentile is above visible range - show arrow on right edge
            ax.annotate(
                f"95%\n${spot_95th_percentile:,.0f}",
                xy=(spot_range_max, y_mid),
                xytext=(-30, 0),
                textcoords="offset points",
                fontsize=9,
                color=DEFAULT_PALETTE.dark_background,
                fontweight="bold",
                ha="right",
                va="center",
                bbox=dict(
                    boxstyle="round,pad=0.3",
                    facecolor=DEFAULT_PALETTE.white,
                    edgecolor=DEFAULT_PALETTE.dark_background,
                    alpha=0.8,
                ),
                arrowprops=dict(
                    arrowstyle="<-",
                    color=DEFAULT_PALETTE.dark_background,
                    lw=1.5,
                ),
            )

        # Add profit/loss zones with fill_between
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

        # Add zero line and current spot marker
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
            bbox=dict(
                boxstyle="round,pad=0.3",
                facecolor=DEFAULT_PALETTE.white,
                edgecolor=DEFAULT_PALETTE.black,
                alpha=0.8,
            ),
        )

        # Annotate break-even points
        be_key = (
            "breakeven_total" if include_underlying else "breakeven_options"
        )
        if analysis.get(be_key):
            for i, be in enumerate(analysis[be_key]):
                be_pnl = self.portfolio.calculate_pnl_at_expiry(  # type: ignore
                    be, include_underlying=include_underlying
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
                    markerfacecolor="yellow",
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
                    bbox=dict(
                        boxstyle="round,pad=0.5",
                        facecolor="yellow",
                        alpha=0.7,
                        edgecolor=DEFAULT_PALETTE.black,
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
                    bbox=dict(
                        boxstyle="round,pad=0.5",
                        facecolor=DEFAULT_PALETTE.negative_faded,
                        alpha=0.8,
                        edgecolor=DEFAULT_PALETTE.negative,
                    ),
                    arrowprops=dict(
                        arrowstyle="->", connectionstyle="arc3,rad=0", lw=1.5
                    ),
                )
            else:
                # Max loss is outside visible range - show arrow at edge
                if ml_spot < spot_range_min:
                    edge_spot = spot_range_min
                    edge_pnl = pnl_values[0]
                    arrow_direction = "<-"
                    text_offset = (40, -30)
                    ha = "left"
                else:
                    edge_spot = spot_range_max
                    edge_pnl = pnl_values[-1]
                    arrow_direction = "<-"
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
                    bbox=dict(
                        boxstyle="round,pad=0.5",
                        facecolor=DEFAULT_PALETTE.negative_faded,
                        alpha=0.8,
                        edgecolor=DEFAULT_PALETTE.negative,
                    ),
                    arrowprops=dict(
                        arrowstyle=arrow_direction,
                        connectionstyle="arc3,rad=0",
                        lw=1.5,
                        color=DEFAULT_PALETTE.negative,
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
                bbox=dict(
                    boxstyle="round,pad=0.5",
                    facecolor=DEFAULT_PALETTE.positive_faded,
                    alpha=0.8,
                    edgecolor=DEFAULT_PALETTE.positive,
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
                f"EV ${expected_value:,.0f}",
                xy=(ev_spot, ev_pnl),
                xytext=(50, 20),
                textcoords="offset points",
                fontsize=10,
                fontweight="bold",
                ha="center",
                bbox=dict(
                    boxstyle="round,pad=0.5",
                    facecolor=DEFAULT_PALETTE.orange_faded,
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

        # Apply currency formatters
        ax.yaxis.set_major_formatter(FuncFormatter(format_currency_for_axis))

        # Custom x-axis formatter showing price + % change (use centralized formatter)
        def format_spot_with_pct(x, pos):  # pylint: disable=unused-argument
            """Format x-axis to show spot price and % change from current spot."""
            return format_spot_with_pct_centralized(x, current_spot, pos)

        ax.xaxis.set_major_formatter(FuncFormatter(format_spot_with_pct))
        ax.tick_params(
            axis="x", which="major", pad=8
        )  # Add padding for two-line labels

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
        ax.axhline(
            y=0,
            color=DEFAULT_PALETTE.black,
            linestyle="--",
            linewidth=0.8,
            alpha=0.5,
        )
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
        color = (
            DEFAULT_PALETTE.dark_background
            if analysis_key == "options"
            else DEFAULT_PALETTE.dark_background
        )
        label = "Options P&L" if analysis_key == "options" else "Total P&L"
        ax.plot(spot_range, pnl_values, linewidth=2.5, color=color, label=label)

        # Breakeven points
        be_key = f"breakeven_{analysis_key}"
        if analysis.get(be_key):
            for i, be in enumerate(analysis[be_key]):
                be_pnl = self.portfolio.calculate_pnl_at_expiry(  # type: ignore
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
                arrowprops=dict(
                    arrowstyle="->", color=DEFAULT_PALETTE.negative, lw=2
                ),
            )

        # Formatting
        ax.set_xlabel(
            "Spot Price at Expiration ($)", fontsize=12, fontweight="bold"
        )
        ax.set_ylabel("P&L ($)", fontsize=12, fontweight="bold")
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=10)
        ax.yaxis.set_major_formatter(FuncFormatter(format_currency_for_axis))
