"""Tests for deltadewa.visualization.formatters module."""

import matplotlib.pyplot as plt
from deltadewa.visualization.formatters import FormattersMixin


class TestFormattersMixin:
    """Test cases for FormattersMixin class."""

    def test_format_currency_compact_small(self):
        """Test format_currency_compact with small values."""
        result = FormattersMixin.format_currency_compact(1234)
        assert result == "$1,234"
        
        result = FormattersMixin.format_currency_compact(-5000)
        assert result == "$-5,000"

    def test_format_currency_compact_thousands(self):
        """Test format_currency_compact with thousands."""
        result = FormattersMixin.format_currency_compact(12000)
        assert result == "$12k"
        
        result = FormattersMixin.format_currency_compact(500000)
        assert result == "$500k"

    def test_format_currency_compact_millions(self):
        """Test format_currency_compact with millions."""
        result = FormattersMixin.format_currency_compact(10000000)
        assert result == "$10.0M"
        
        result = FormattersMixin.format_currency_compact(25500000)
        assert result == "$25.5M"

    def test_format_currency_full(self):
        """Test format_currency_full."""
        result = FormattersMixin.format_currency_full(1234.56)
        assert result == "$1,235"
        
        result = FormattersMixin.format_currency_full(1000000)
        assert result == "$1,000,000"

    def test_format_currency_full_with_pos(self):
        """Test format_currency_full with position parameter."""
        result = FormattersMixin.format_currency_full(1234.56, pos=0)
        assert result == "$1,235"

    def test_apply_volatility_percent(self):
        """Test apply_volatility_percent."""
        fig, ax = plt.subplots()
        FormattersMixin.apply_volatility_percent(ax)
        
        # Verify formatter was applied
        assert ax.yaxis.get_major_formatter() is not None
        plt.close(fig)

    def test_apply_spot_price_with_pct(self):
        """Test apply_spot_price_with_pct."""
        fig, ax = plt.subplots()
        current_spot = 100.0
        FormattersMixin.apply_spot_price_with_pct(ax, current_spot)
        
        # Verify formatter was applied
        assert ax.xaxis.get_major_formatter() is not None
        plt.close(fig)
