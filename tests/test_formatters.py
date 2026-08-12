"""Tests for deltadewa.formatters module - centralized formatting functions."""

from deltadewa.formatters.values import (
    format_currency,
    format_currency_for_axis,
    format_greek_value,
    format_number,
    format_number_auto_precision,
    format_percentage,
    format_percentage_for_axis,
    format_spot_with_pct,
)


class TestFormatCurrency:
    """Test cases for format_currency function."""

    def test_format_currency_basic(self) -> None:
        """Test basic currency formatting."""
        assert format_currency(1234.56) == "$1,234.56"
        assert format_currency(1000000) == "$1,000,000.00"

    def test_format_currency_for_axis(self) -> None:
        """Test compact currency formatting."""
        # Values < 1000 stay in full format with precision
        assert format_currency(500, compact=True) == "$500.00"
        assert format_currency(999.99, compact=True) == "$999.99"
        # Values >= 1000 get compact notation
        assert format_currency(12345.67, compact=True) == "$12.35K"
        assert format_currency(1500, compact=True) == "$1,500.00"
        assert format_currency(1234567, compact=True) == "$1.23M"
        assert format_currency(1234567890, compact=True) == "$1.23B"

    def test_format_currency_negative(self) -> None:
        """Test negative currency values."""
        assert format_currency(-1234.56) == "$-1,234.56"
        assert format_currency(-1234567, compact=True) == "-$1.23M"

    def test_format_currency_precision(self) -> None:
        """Test precision parameter."""
        assert format_currency(1234.5678, precision=0) == "$1,235"
        assert format_currency(1234.5678, precision=4) == "$1,234.5678"

    def test_format_currency_show_sign(self) -> None:
        """Test show_sign parameter."""
        assert format_currency(1234.56, show_sign=True) == "+$1,234.56"
        assert format_currency(-1234.56, show_sign=True) == "$-1,234.56"


class TestFormatCurrencyForAxis:
    """Test cases for format_currency_for_axis function."""

    def test_format_currency_for_axis_small(self) -> None:
        """Test axis formatter with small values."""
        assert format_currency_for_axis(1234) == "$1,234"
        assert format_currency_for_axis(5000) == "$5,000"

    def test_format_currency_for_axis_thousands(self) -> None:
        """Test axis formatter with thousands."""
        assert format_currency_for_axis(12000) == "$12k"
        assert format_currency_for_axis(500000) == "$500k"

    def test_format_currency_for_axis_millions(self) -> None:
        """Test axis formatter with millions."""
        assert format_currency_for_axis(10000000) == "$10.0M"
        assert format_currency_for_axis(25500000) == "$25.5M"


class TestFormatPercentage:
    """Test cases for format_percentage function."""

    def test_format_percentage_from_decimal(self) -> None:
        """Test percentage formatting from decimal."""
        assert format_percentage(0.1523) == "15.23%"
        assert format_percentage(0.1523, decimals=1) == "15.2%"

    def test_format_percentage_already_percent(self) -> None:
        """Test percentage formatting when value is already percentage."""
        assert format_percentage(15.23, from_decimal=False) == "15.23%"
        assert (
            format_percentage(15.23, from_decimal=False, decimals=1) == "15.2%"
        )

    def test_format_percentage_show_sign(self) -> None:
        """Test show_sign parameter."""
        assert format_percentage(0.1523, show_sign=True) == "+15.23%"
        assert format_percentage(-0.1523, show_sign=True) == "-15.23%"


class TestFormatPercentageForAxis:
    """Test cases for format_percentage_for_axis function."""

    def test_format_percentage_for_axis(self) -> None:
        """Test axis percentage formatter."""
        assert format_percentage_for_axis(0.25) == "25%"
        assert format_percentage_for_axis(0.5) == "50%"
        assert format_percentage_for_axis(1.0) == "100%"


class TestFormatNumber:
    """Test cases for format_number function."""

    def test_format_number_basic(self) -> None:
        """Test basic number formatting."""
        assert format_number(1234.5678) == "1,234.57"
        assert format_number(1234.5678, decimals=4) == "1,234.5678"

    def test_format_number_no_thousands_sep(self) -> None:
        """Test number formatting without thousands separator."""
        assert format_number(1234.5678, thousands_sep=False) == "1234.57"

    def test_format_number_compact(self) -> None:
        """Test compact number formatting."""
        assert format_number(1234567, compact=True) == "1.23M"
        assert format_number(12345, compact=True) == "12.35K"


class TestFormatGreekValue:
    """Test cases for format_greek_value function."""

    def test_format_greek_delta(self) -> None:
        """Test Greek formatting for delta."""
        assert format_greek_value(0.5432, greek="delta") == "0.5432"
        assert (
            format_greek_value(15000, greek="delta", compact=True) == "15.00K"
        )

    def test_format_greek_gamma(self) -> None:
        """Test Greek formatting for gamma."""
        assert format_greek_value(0.000123, greek="gamma") == "0.000123"

    def test_format_greek_vega(self) -> None:
        """Test Greek formatting for vega."""
        assert format_greek_value(123.45, greek="vega") == "123.45"


class TestFormatSpotWithPct:
    """Test cases for format_spot_with_pct function."""

    def test_format_spot_with_pct_basic(self) -> None:
        """Test spot price with percentage formatting."""
        result = format_spot_with_pct(110, 100)
        assert "$110" in result
        assert "+10%" in result

    def test_format_spot_with_pct_negative(self) -> None:
        """Test spot price with negative percentage."""
        result = format_spot_with_pct(90, 100)
        assert "$90" in result
        assert "-10%" in result


class TestFormatNumberAutoPrecision:
    """Test cases for format_number_auto_precision function."""

    def test_millions(self) -> None:
        """Test formatting of millions."""
        assert format_number_auto_precision(1234567.0) == "1,234,567"

    def test_ten_thousands(self) -> None:
        """Test formatting of ten thousands."""
        assert format_number_auto_precision(12345.0) == "12,345"

    def test_hundreds(self) -> None:
        """Test formatting of hundreds."""
        assert format_number_auto_precision(123.456) == "123.46"

    def test_tens(self) -> None:
        """Test formatting of tens."""
        assert format_number_auto_precision(12.3456) == "12.346"

    def test_small(self) -> None:
        """Test formatting of small numbers (0.1-1)."""
        assert format_number_auto_precision(0.1234) == "0.1234"

    def test_very_small(self) -> None:
        """Test formatting of very small numbers (<0.1)."""
        assert format_number_auto_precision(0.001234) == "0.001234"

    def test_negative(self) -> None:
        """Test formatting of negative numbers."""
        assert format_number_auto_precision(-1234567.0) == "-1,234,567"
        assert format_number_auto_precision(-12.3456) == "-12.346"

    def test_boundary_million(self) -> None:
        """Test boundary at 1 million."""
        assert format_number_auto_precision(1_000_000.0) == "1,000,000"
        assert format_number_auto_precision(999_999.0) == "999,999"

    def test_boundary_ten_thousand(self) -> None:
        """Test boundary at 10,000."""
        assert format_number_auto_precision(10_000.0) == "10,000"
        assert format_number_auto_precision(9_999.0) == "9,999.00"

    def test_boundary_hundred(self) -> None:
        """Test boundary at 100."""
        assert format_number_auto_precision(100.0) == "100.00"
        assert format_number_auto_precision(99.999) == "99.999"

    def test_boundary_ten(self) -> None:
        """Test boundary at 10."""
        assert format_number_auto_precision(10.0) == "10.000"
        assert format_number_auto_precision(9.9999) == "9.9999"

    def test_boundary_tenth(self) -> None:
        """Test boundary at 0.1."""
        assert format_number_auto_precision(0.1) == "0.1000"
        assert format_number_auto_precision(0.09999) == "0.099990"
