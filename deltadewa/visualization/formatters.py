"""Axis and value formatting utilities for option charts."""

from typing import TYPE_CHECKING

from matplotlib.ticker import FuncFormatter

if TYPE_CHECKING:
    pass


class FormattersMixin:
    """Mixin providing axis and value formatting utilities."""

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
    def format_currency_full(x, pos=None):
        """
        Format currency with full dollar precision and comma separators.

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
    def apply_volatility_percent(ax):
        """
        Format y-axis to display percentages for volatility values.

        Assumes axis values are in decimal form (e.g. 0.25 -> '25%').

        Args:
            ax: Matplotlib Axes object
        """
        ax.yaxis.set_major_formatter(
            FuncFormatter(lambda x, pos: f"{x*100:.0f}%")
        )

    @staticmethod
    def apply_spot_price_with_pct(ax, current_spot: float):
        """
        Format the x-axis to show the spot price in currency on the top line
        and the percent change from `current_spot` on the second line.

        Example tick label:
            $420
            +10%

        Args:
            ax: Matplotlib Axes object
            current_spot: Current spot price to calculate percentage from
        """

        def _fmt(x, pos):  # pylint: disable=unused-argument
            # Avoid division by zero
            try:
                pct = (x / current_spot - 1) * 100
            except Exception:  # pylint: disable=broad-except
                pct = 0
            # Import locally to avoid circular import
            from deltadewa.visualization.formatters import FormattersMixin
            curr = FormattersMixin.format_currency_full(x)
            return f"{curr}\n{pct:+.0f}%"

        ax.xaxis.set_major_formatter(FuncFormatter(_fmt))
        # Slightly tighten tick padding so two-line labels don't overlap title
        ax.tick_params(axis="x", which="major", pad=6)
