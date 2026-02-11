"""Tests for deltadewa.formatters module - scalar and HTML formatters."""

import pytest
from matplotlib.ticker import FuncFormatter
from deltadewa.formatters import (
    format_currency,
    format_currency_for_axis,
    format_percentage,
    format_percentage_for_axis,
    format_number,
    format_greek_value,
    format_html_badge,
    format_html_metric,
    format_html_percentage,
    get_currency_axis_formatter,
    get_percentage_axis_formatter,
    get_spot_price_axis_formatter,
)


class TestFormatCurrency:
    """Test cases for format_currency function."""

    def test_basic_currency(self):
        """Test basic currency formatting."""
        assert format_currency(1234.56) == "$1,234.56"
        assert format_currency(1000000) == "$1,000,000.00"

    def test_negative_currency(self):
        """Test negative currency formatting."""
        assert format_currency(-1234.56) == "-$1,234.56"
        assert format_currency(-1000) == "-$1,000.00"

    def test_compact_currency(self):
        """Test compact currency formatting."""
        assert format_currency(1234.56, compact=True) == "$1.23K"
        assert format_currency(1234567, compact=True) == "$1.23M"
        assert format_currency(1234567890, compact=True) == "$1.23B"

    def test_compact_small_values(self):
        """Test compact formatting with values < 1000."""
        assert format_currency(999.99, compact=True) == "$999.99"
        assert format_currency(123.45, compact=True) == "$123.45"

    def test_show_sign(self):
        """Test show_sign parameter."""
        assert format_currency(1234.56, show_sign=True) == "+$1,234.56"
        assert format_currency(-1234.56, show_sign=True) == "-$1,234.56"

    def test_precision(self):
        """Test precision parameter."""
        assert format_currency(1234.567, precision=1) == "$1,234.6"
        assert format_currency(1234.567, precision=3) == "$1,234.567"


class TestFormatCurrencyForAxis:
    """Test cases for format_currency_for_axis function."""

    def test_small_values(self):
        """Test formatting with values < $10k."""
        assert format_currency_for_axis(1234) == "$1,234"
        assert format_currency_for_axis(9999) == "$9,999"

    def test_thousands(self):
        """Test formatting with thousands."""
        assert format_currency_for_axis(12000) == "$12K"
        assert format_currency_for_axis(500000) == "$500K"

    def test_millions(self):
        """Test formatting with millions."""
        assert format_currency_for_axis(10000000) == "$10.0M"
        assert format_currency_for_axis(25500000) == "$25.5M"


class TestFormatPercentage:
    """Test cases for format_percentage function."""

    def test_from_decimal(self):
        """Test conversion from decimal (default)."""
        assert format_percentage(0.1523) == "15.23%"
        assert format_percentage(0.1523, decimals=1) == "15.2%"

    def test_from_percent(self):
        """Test when input is already percentage."""
        assert format_percentage(15.23, from_decimal=False) == "15.23%"
        assert format_percentage(15.23, from_decimal=False, decimals=1) == "15.2%"

    def test_show_sign(self):
        """Test show_sign parameter."""
        assert format_percentage(0.1523, show_sign=True) == "+15.23%"
        assert format_percentage(-0.1523, show_sign=True) == "-15.23%"


class TestFormatPercentageForAxis:
    """Test cases for format_percentage_for_axis function."""

    def test_basic_formatting(self):
        """Test basic percentage formatting for axis."""
        assert format_percentage_for_axis(0.25) == "25%"
        assert format_percentage_for_axis(0.5) == "50%"
        assert format_percentage_for_axis(1.0) == "100%"


class TestFormatNumber:
    """Test cases for format_number function."""

    def test_basic_formatting(self):
        """Test basic number formatting."""
        assert format_number(1234.5678) == "1,234.57"
        assert format_number(1234.5678, decimals=4) == "1,234.5678"

    def test_no_thousands_separator(self):
        """Test without thousands separator."""
        assert format_number(1234.5678, thousands_sep=False) == "1234.57"


class TestFormatGreekValue:
    """Test cases for format_greek_value function."""

    def test_currency_greeks(self):
        """Test formatting for currency greeks (theta, value, cost)."""
        assert format_greek_value(1234.56, "theta", True) == "$1.23K"
        assert format_greek_value(1234.56, "Value", True) == "$1.23K"

    def test_non_currency_greeks(self):
        """Test formatting for non-currency greeks (delta, gamma, etc)."""
        assert format_greek_value(0.1234, "delta", False) == "0.1234"
        assert format_greek_value(123.45, "gamma", False) == "123.45"

    def test_small_values(self):
        """Test small value handling."""
        assert format_greek_value(0.001, "delta") == "~0"


class TestFormatHtmlBadge:
    """Test cases for format_html_badge function."""

    def test_basic_badge(self):
        """Test basic badge creation."""
        badge = format_html_badge("Delta", "$1,234", "positive")
        assert "Delta" in badge
        assert "$1,234" in badge
        assert "display:inline-block" in badge

    def test_color_mapping(self):
        """Test color mapping."""
        badge_pos = format_html_badge("Test", "100", "positive")
        badge_neg = format_html_badge("Test", "100", "negative")
        badge_neu = format_html_badge("Test", "100", "neutral")
        
        # Should use different colors
        assert badge_pos != badge_neg
        assert badge_neg != badge_neu


class TestFormatHtmlMetric:
    """Test cases for format_html_metric function."""

    def test_currency_metric(self):
        """Test currency metric formatting."""
        badge = format_html_metric("Delta", 1234.56, is_currency=True)
        assert "Delta" in badge
        assert "$" in badge

    def test_non_currency_metric(self):
        """Test non-currency metric formatting."""
        badge = format_html_metric("Gamma", 1234.56, is_currency=False)
        assert "Gamma" in badge
        assert "$" not in badge

    def test_color_coding(self):
        """Test automatic color coding."""
        badge_pos = format_html_metric("Test", 100)
        badge_neg = format_html_metric("Test", -100)
        badge_zero = format_html_metric("Test", 0)
        
        # Different values should produce different badges
        assert badge_pos != badge_neg
        assert badge_neg != badge_zero


class TestFormatHtmlPercentage:
    """Test cases for format_html_percentage function."""

    def test_basic_percentage(self):
        """Test basic percentage badge creation."""
        badge = format_html_percentage("Return", 0.1523)
        assert "Return" in badge
        assert "%" in badge

    def test_small_percentage(self):
        """Test very small percentage."""
        badge = format_html_percentage("Change", 0.00001)
        assert "~0%" in badge


class TestAxisFormatterFactories:
    """Test cases for axis formatter factory functions."""

    def test_get_currency_axis_formatter(self):
        """Test currency axis formatter factory."""
        formatter = get_currency_axis_formatter()
        assert isinstance(formatter, FuncFormatter)

    def test_get_percentage_axis_formatter(self):
        """Test percentage axis formatter factory."""
        formatter = get_percentage_axis_formatter()
        assert isinstance(formatter, FuncFormatter)

    def test_get_spot_price_axis_formatter(self):
        """Test spot price axis formatter factory."""
        formatter = get_spot_price_axis_formatter(100.0)
        assert isinstance(formatter, FuncFormatter)
        
        # Test the formatter produces expected output
        result = formatter(110.0)
        assert "$110" in result
        assert "+10%" in result
