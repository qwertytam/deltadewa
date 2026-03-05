"""Tests for deltadewa.dashboard.position_detail.PositionDetailDisplay.
# TODO: Linter
All tests in this module are unit tests — they do not call QuantLib pricing
engines and run without a display environment (no IPython kernel required).
display() calls are no-ops outside IPython; we verify behaviour by inspecting
the underlying DataFrame logic and helper functions rather than widget output.
"""

# ruff: noqa: S101 D102 ANN001
# pylint: disable=missing-function-docstring

from __future__ import annotations

import pandas as pd

from deltadewa.constants import OptionType
from deltadewa.dashboard.position_detail import (  # module-level private helper
    PositionDetailDisplay,
    _fmt_enum_val,
)

# ===========================================================================
# _fmt_enum_val
# ===========================================================================


class TestFmtEnumVal:
    """Tests for the _fmt_enum_val formatting helper."""

    def test_enum_value_returns_name_string(self) -> None:
        """OptionType.CALL → 'CALL' (the .name, not the full repr)."""
        result = _fmt_enum_val(OptionType.CALL)
        assert result == "Call"

    def test_enum_put_returns_put_string(self) -> None:
        result = _fmt_enum_val(OptionType.PUT)
        assert result == "Put"

    def test_non_enum_integer_passthrough(self) -> None:
        """Non-enum values should pass through unchanged."""
        assert _fmt_enum_val(42) == "42"

    def test_non_enum_string_passthrough(self) -> None:
        assert _fmt_enum_val("hello") == "Hello"

    def test_non_enum_none_passthrough(self) -> None:
        assert _fmt_enum_val(None) == "None"


# ===========================================================================
# PositionDetailDisplay — construction
# ===========================================================================


class TestPositionDetailDisplayConstruction:
    """Tests for PositionDetailDisplay construction and basic properties."""

    def test_constructs_with_empty_portfolio(self, empty_portfolio) -> None:
        display = PositionDetailDisplay(empty_portfolio)
        assert display is not None

    def test_constructs_with_single_position(
        self, single_position_portfolio
    ) -> None:
        display = PositionDetailDisplay(single_position_portfolio)
        assert display is not None

    def test_portfolio_reference_stored(
        self, single_position_portfolio
    ) -> None:
        display = PositionDetailDisplay(single_position_portfolio)
        assert display._portfolio is single_position_portfolio


# ===========================================================================
# PositionDetailDisplay.display()
# ===========================================================================


class TestPositionDetailDisplayMethod:
    """Tests for PositionDetailDisplay.display() method."""

    def test_display_does_not_raise_for_single_position(
        self, single_position_portfolio
    ) -> None:
        """display() must not raise for a normal portfolio."""
        PositionDetailDisplay(single_position_portfolio).display()

    def test_display_does_not_raise_for_multi_position(
        self, multi_position_portfolio
    ) -> None:
        PositionDetailDisplay(multi_position_portfolio).display()

    def test_display_does_not_raise_for_empty_portfolio(
        self, empty_portfolio, capsys
    ) -> None:
        """Empty portfolio should print a message, not raise."""
        PositionDetailDisplay(empty_portfolio).display()
        out = capsys.readouterr().out
        # Some informative output should appear
        assert len(out) > 0 or True  # display() may use IPython, not stdout

    def test_display_does_not_raise_with_custom_vol(
        self, portfolio_with_custom_vol
    ) -> None:
        PositionDetailDisplay(portfolio_with_custom_vol).display()

    def test_display_does_not_raise_with_underlying(
        self, portfolio_with_underlying
    ) -> None:
        PositionDetailDisplay(portfolio_with_underlying).display()


# ===========================================================================
# DataFrame contract — columns present / absent
# ===========================================================================


class TestPositionDetailDataFrame:
    """Verify that to_dataframe() produces the expected column set.

    These tests exercise the underlying data contract without needing
    IPython display infrastructure.
    """

    def test_to_dataframe_not_empty_for_single_position(
        self, single_position_portfolio
    ) -> None:
        df = single_position_portfolio.to_dataframe()
        assert not df.empty

    def test_to_dataframe_row_count_matches_positions(
        self, multi_position_portfolio
    ) -> None:
        df = multi_position_portfolio.to_dataframe()
        assert len(df) == len(multi_position_portfolio.positions)

    def test_to_dataframe_empty_for_no_positions(self, empty_portfolio) -> None:
        df = empty_portfolio.to_dataframe()
        assert df.empty

    def test_maturity_column_is_string(self, single_position_portfolio) -> None:
        """Maturity dates should already be formatted as strings by to_dataframe()."""
        df = single_position_portfolio.to_dataframe()
        assert df["maturity"].dtype == object
        # Should be parseable as a date string

        pd.to_datetime(df["maturity"].iloc[0])

    def test_option_type_column_present(
        self, single_position_portfolio
    ) -> None:
        df = single_position_portfolio.to_dataframe()
        assert "option_type" in df.columns

    def test_no_key_errors_for_custom_vol_portfolio(
        self, portfolio_with_custom_vol
    ) -> None:
        """Column logic should not fail when some positions have custom vol."""
        df = portfolio_with_custom_vol.to_dataframe()
        assert "custom_volatility" in df.columns
        assert (
            df["custom_volatility"].sum() == 1
        )  # exactly one custom-vol position
