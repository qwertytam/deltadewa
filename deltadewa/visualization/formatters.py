"""Axis and value formatting utilities for option charts."""

from typing import TYPE_CHECKING

from matplotlib.ticker import FuncFormatter

# Import centralized formatters
from deltadewa.formatters import (
    format_currency,
    format_currency_for_axis,
    format_percentage_for_axis,
    get_spot_price_axis_formatter,
)

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
        
        Note:
            Uses centralized formatter from deltadewa.formatters
        """
        return format_currency_for_axis(x, pos)

    @staticmethod
    def format_currency_full(x, pos=None):
        """
        Format currency with full dollar precision and comma separators.
        
        Note: 'full' refers to displaying full dollar amounts without compact 
        notation (no k/M/B). Precision is set to 0 to avoid cluttering axis 
        labels with cents.

        Args:
            x: numeric value
            pos: FuncFormatter position (unused)

        Returns:
            String like "$1,234"
        
        Note:
            Uses centralized formatter from deltadewa.formatters
        """
        _ = pos
        try:
            return format_currency(x, compact=False, precision=0)
        except Exception:  # pylint: disable=broad-except
            return f"${x}"

    @staticmethod
    def apply_volatility_percent(ax):
        """
        Format y-axis to display percentages for volatility values.

        Assumes axis values are in decimal form (e.g. 0.25 -> '25%').

        Args:
            ax: Matplotlib Axes object
        
        Note:
            Uses centralized formatter from deltadewa.formatters
        """
        ax.yaxis.set_major_formatter(
            FuncFormatter(format_percentage_for_axis)
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
        
        Note:
            Uses centralized formatter from deltadewa.formatters
        """
        ax.xaxis.set_major_formatter(get_spot_price_axis_formatter(current_spot))
        # Slightly tighten tick padding so two-line labels don't overlap title
        ax.tick_params(axis="x", which="major", pad=6)

