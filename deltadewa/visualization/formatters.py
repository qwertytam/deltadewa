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
        """Format currency values in compact form. Delegates to centralized formatter."""
        return format_currency_for_axis(x, pos)

    @staticmethod
    def format_currency_full(x, pos=None):
        """Format currency with full dollar precision."""
        return format_currency(x, compact=False, precision=0)

    @staticmethod
    def apply_volatility_percent(ax):
        """Format y-axis to display percentages for volatility values."""
        ax.yaxis.set_major_formatter(
            FuncFormatter(format_percentage_for_axis)
        )

    @staticmethod
    def apply_spot_price_with_pct(ax, current_spot: float):
        """Format x-axis to show spot price with % change."""
        ax.xaxis.set_major_formatter(get_spot_price_axis_formatter(current_spot))
        ax.tick_params(axis="x", which="major", pad=6)
