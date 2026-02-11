"""Tests for deltadewa.formatters module - centralized formatting functions."""

import pytest
from deltadewa.formatters import (
    format_currency,
    format_currency_for_axis,
    format_percentage,
    format_percentage_for_axis,
    format_number,
    format_greek_value,
    format_spot_with_pct,
    format_html_badge,
    format_html_metric,
)


class TestFormatCurrency:
    """Test cases for format_currency function."""

    def test_format_currency_basic(self):
        """Test basic currency formatting."""
        assert format_currency(1234.56) == "$1,234.56"
        assert format_currency(1000000) == "$1,000,000.00"

    def test_format_currency_compact(self):
        """Test compact currency formatting."""
        # Values < 1000 stay in full format with precision
        assert format_currency(500, compact=True) == "$500.00"
        assert format_currency(999.99, compact=True) == "$999.99"
        # Values >= 1000 get compact notation
        assert format_currency(1234.56, compact=True) == "$1.23K"
        assert format_currency(1500, compact=True) == "$1.50K"
        assert format_currency(1234567, compact=True) == "$1.23M"
        assert format_currency(1234567890, compact=True) == "$1.23B"

    def test_format_currency_negative(self):
        """Test negative currency values."""
        assert format_currency(-1234.56) == "$-1,234.56"
        assert format_currency(-1234567, compact=True) == "-$1.23M"

    def test_format_currency_precision(self):
        """Test precision parameter."""
        assert format_currency(1234.5678, precision=0) == "$1,235"
        assert format_currency(1234.5678, precision=4) == "$1,234.5678"

    def test_format_currency_show_sign(self):
        """Test show_sign parameter."""
        assert format_currency(1234.56, show_sign=True) == "+$1,234.56"
        assert format_currency(-1234.56, show_sign=True) == "$-1,234.56"


class TestFormatCurrencyForAxis:
    """Test cases for format_currency_for_axis function."""

    def test_format_currency_for_axis_small(self):
        """Test axis formatter with small values."""
        assert format_currency_for_axis(1234) == "$1,234"
        assert format_currency_for_axis(5000) == "$5,000"

    def test_format_currency_for_axis_thousands(self):
        """Test axis formatter with thousands."""
        assert format_currency_for_axis(12000) == "$12k"
        assert format_currency_for_axis(500000) == "$500k"

    def test_format_currency_for_axis_millions(self):
        """Test axis formatter with millions."""
        assert format_currency_for_axis(10000000) == "$10.0M"
        assert format_currency_for_axis(25500000) == "$25.5M"


class TestFormatPercentage:
    """Test cases for format_percentage function."""

    def test_format_percentage_from_decimal(self):
        """Test percentage formatting from decimal."""
        assert format_percentage(0.1523) == "15.23%"
        assert format_percentage(0.1523, decimals=1) == "15.2%"

    def test_format_percentage_already_percent(self):
        """Test percentage formatting when value is already percentage."""
        assert format_percentage(15.23, from_decimal=False) == "15.23%"
        assert format_percentage(15.23, from_decimal=False, decimals=1) == "15.2%"

    def test_format_percentage_show_sign(self):
        """Test show_sign parameter."""
        assert format_percentage(0.1523, show_sign=True) == "+15.23%"
        assert format_percentage(-0.1523, show_sign=True) == "-15.23%"


class TestFormatPercentageForAxis:
    """Test cases for format_percentage_for_axis function."""

    def test_format_percentage_for_axis(self):
        """Test axis percentage formatter."""
        assert format_percentage_for_axis(0.25) == "25%"
        assert format_percentage_for_axis(0.5) == "50%"
        assert format_percentage_for_axis(1.0) == "100%"


class TestFormatNumber:
    """Test cases for format_number function."""

    def test_format_number_basic(self):
        """Test basic number formatting."""
        assert format_number(1234.5678) == "1,234.57"
        assert format_number(1234.5678, decimals=4) == "1,234.5678"

    def test_format_number_no_thousands_sep(self):
        """Test number formatting without thousands separator."""
        assert format_number(1234.5678, thousands_sep=False) == "1234.57"

    def test_format_number_compact(self):
        """Test compact number formatting."""
        assert format_number(1234567, compact=True) == "1.23M"
        assert format_number(1234, compact=True) == "1.23K"


class TestFormatGreekValue:
    """Test cases for format_greek_value function."""

    def test_format_greek_delta(self):
        """Test Greek formatting for delta."""
        assert format_greek_value(0.5432, greek="delta") == "0.5432"
        assert format_greek_value(1500, greek="delta", compact=True) == "1.50K"

    def test_format_greek_gamma(self):
        """Test Greek formatting for gamma."""
        assert format_greek_value(0.000123, greek="gamma") == "0.000123"

    def test_format_greek_vega(self):
        """Test Greek formatting for vega."""
        assert format_greek_value(123.45, greek="vega") == "123.45"


class TestFormatSpotWithPct:
    """Test cases for format_spot_with_pct function."""

    def test_format_spot_with_pct_basic(self):
        """Test spot price with percentage formatting."""
        result = format_spot_with_pct(110, 100)
        assert "$110" in result
        assert "+10%" in result

    def test_format_spot_with_pct_negative(self):
        """Test spot price with negative percentage."""
        result = format_spot_with_pct(90, 100)
        assert "$90" in result
        assert "-10%" in result


class TestFormatHtmlBadge:
    """Test cases for format_html_badge function."""

    def test_format_html_badge_basic(self):
        """Test HTML badge formatting."""
        result = format_html_badge("Label", "Value")
        assert "Label" in result
        assert "Value" in result
        assert "display:inline-block" in result

    def test_format_html_badge_colors(self):
        """Test HTML badge with different colors."""
        result = format_html_badge("Label", "Value", color="positive")
        assert "Label" in result
        assert "Value" in result


class TestFormatHtmlMetric:
    """Test cases for format_html_metric function."""

    def test_format_html_metric_number(self):
        """Test HTML metric formatting for numbers."""
        result = format_html_metric("Delta", 1234.56, format_type="number")
        assert "Delta" in result
        # Should format as "1,234.56" (2 decimal places by default)
        assert "1,234.56" in result

    def test_format_html_metric_currency(self):
        """Test HTML metric formatting for currency."""
        result = format_html_metric("Value", 1000000, format_type="currency")
        assert "Value" in result
        # Should format as $1.00M
        assert "$1.00M" in result

    def test_format_html_metric_percentage(self):
        """Test HTML metric formatting for percentages."""
        result = format_html_metric("Volatility", 0.25, format_type="percentage")
        assert "Volatility" in result
        assert "%" in result
    
    def test_format_html_metric_near_zero(self):
        """Test HTML metric formatting for near-zero values."""
        # Currency at threshold boundary (0.01)
        result = format_html_metric("Value", 0.01, format_type="currency")
        # At exactly threshold, should format normally (not as ~$0)
        assert "$0.01" in result
        
        # Currency below threshold
        result = format_html_metric("Value", 0.001, format_type="currency")
        assert "~$0" in result
        
        # Percentage at threshold boundary (0.0001 = 0.01%)
        # At exactly threshold, should format normally (not as ~0%)
        result = format_html_metric("Change", 0.0001, format_type="percentage")
        assert "0.01%" in result
        
        # Percentage below threshold should show as ~0%
        result = format_html_metric("Change", 0.00001, format_type="percentage")
        assert "~0%" in result
        
        # Number at threshold boundary (0.01)
        result = format_html_metric("Delta", 0.01, format_type="number")
        # At exactly threshold, should format normally
        assert "0.01" in result
        
        # Number below threshold
        result = format_html_metric("Delta", 0.001, format_type="number")
        assert "~0" in result


class TestBackwardCompatibility:
    """Test backward compatibility with old imports."""

    def test_utils_format_currency(self):
        """Test that utils.format_currency still works."""
        from deltadewa.utils import format_currency as utils_format_currency
        assert utils_format_currency(1234.56) == "$1,234.56"

    def test_utils_format_percentage(self):
        """Test that utils.format_percentage still works."""
        from deltadewa.utils import format_percentage as utils_format_percentage
        assert utils_format_percentage(0.1523) == "15.23%"

    def test_utils_format_number(self):
        """Test that utils.format_number still works."""
        from deltadewa.utils import format_number as utils_format_number
        assert utils_format_number(1234.5678) == "1,234.57"

    def test_utils_format_currency_compact(self):
        """Test that utils.format_currency_compact still works."""
        from deltadewa.utils import format_currency_compact as utils_format_currency_compact
        assert utils_format_currency_compact(12000, None) == "$12k"
