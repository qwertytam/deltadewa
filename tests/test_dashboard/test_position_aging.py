"""Tests for deltadewa.dashboard.position_aging.PositionAgingDisplay.

Focus areas:
- _get_urgency_category: exhaustive boundary coverage
- _URGENCY_ORDER constant integrity
- PositionAgingDisplay.display(): smoke tests + freshness of "today"
"""

# ruff: noqa: S101 D101 D102 ANN001
# pylint: disable=missing-class-docstring, missing-function-docstring, protected-access

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.dashboard.position_aging import (
    _URGENCY_ORDER,
    PositionAgingDisplay,
    _get_urgency_category,
)

# ===========================================================================
# _URGENCY_ORDER constant
# ===========================================================================


class TestUrgencyOrderConstant:
    def test_has_five_tiers(self) -> None:
        assert len(_URGENCY_ORDER) == 5

    def test_no_duplicate_tiers(self) -> None:
        assert len(_URGENCY_ORDER) == len(set(_URGENCY_ORDER))

    def test_urgent_tier_present(self) -> None:
        assert any("URGENT" in tier for tier in _URGENCY_ORDER)

    def test_long_term_tier_present(self) -> None:
        assert any("LONG-TERM" in tier for tier in _URGENCY_ORDER)


# ===========================================================================
# _get_urgency_category — boundary value analysis
# ===========================================================================


class TestGetUrgencyCategory:
    @pytest.mark.parametrize(
        "days, expected_fragment",
        [
            # URGENT: 0 - 6  # noqa: ERA001
            (0, "URGENT"),
            (1, "URGENT"),
            (6, "URGENT"),
            # SOON: 7 - 13  # noqa: ERA001
            (7, "SOON"),
            (13, "SOON"),
            # APPROACHING: 14 - 20  # noqa: ERA001
            (14, "APPROACHING"),
            (20, "APPROACHING"),
            # NORMAL: 21 - 44  # noqa: ERA001
            (21, "NORMAL"),
            (44, "NORMAL"),
            # LONG-TERM: 45+
            (45, "LONG-TERM"),
            (90, "LONG-TERM"),
            (365, "LONG-TERM"),
        ],
    )
    def test_boundary_values(self, days: int, expected_fragment: str) -> None:
        result = _get_urgency_category(days)
        assert expected_fragment in result, (
            f"days={days}: expected fragment '{expected_fragment}' "
            f"in result '{result}'"
        )

    def test_negative_days_maps_to_urgent(self) -> None:
        """Expired positions (days < 0) should be treated as most urgent."""
        result = _get_urgency_category(-1)
        assert "URGENT" in result

    def test_large_number_maps_to_long_term(self) -> None:
        result = _get_urgency_category(1000)
        assert "LONG-TERM" in result

    def test_return_value_is_in_urgency_order(self) -> None:
        """Every returned category must be one of the canonical tier strings."""
        for days in [0, 6, 7, 13, 14, 20, 21, 44, 45, 100]:
            result = _get_urgency_category(days)
            assert (
                result in _URGENCY_ORDER
            ), f"days={days}: '{result}' not found in _URGENCY_ORDER"


# ===========================================================================
# PositionAgingDisplay — construction
# ===========================================================================


class TestPositionAgingDisplayConstruction:
    def test_constructs_with_portfolio_only(
        self,
        single_position_portfolio,
    ) -> None:
        d = PositionAgingDisplay(single_position_portfolio)
        assert d is not None

    def test_constructs_with_reporter(
        self,
        single_position_portfolio,
        reporter,
    ) -> None:
        d = PositionAgingDisplay(single_position_portfolio, reporter)
        assert d is not None

    def test_default_reporter_created_when_none(
        self,
        single_position_portfolio,
    ) -> None:
        d = PositionAgingDisplay(single_position_portfolio)
        assert d._reporter is not None

    def test_custom_reporter_stored(
        self,
        single_position_portfolio,
        reporter,
    ) -> None:
        d = PositionAgingDisplay(single_position_portfolio, reporter)
        assert d._reporter is reporter


class TestPositionAgingDisplayMethod:
    def test_display_does_not_raise_empty_portfolio(
        self,
        empty_portfolio,
    ) -> None:
        PositionAgingDisplay(empty_portfolio).display()

    def test_display_does_not_raise_single_position(
        self,
        single_position_portfolio,
    ) -> None:
        PositionAgingDisplay(single_position_portfolio).display()

    def test_display_does_not_raise_multi_position(
        self,
        multi_position_portfolio,
    ) -> None:
        PositionAgingDisplay(multi_position_portfolio).display()

    def test_display_does_not_raise_with_underlying(
        self,
        portfolio_with_underlying,
    ) -> None:
        PositionAgingDisplay(portfolio_with_underlying).display()

    def test_display_outputs_strike_for_single_position(
        self,
        single_position_portfolio,
        capsys,
    ) -> None:
        PositionAgingDisplay(single_position_portfolio).display()
        out = capsys.readouterr().out
        # The strike price (100.0) should appear somewhere in the output
        assert "100" in out

    def test_display_outputs_all_urgency_rows_for_multi_position(
        self,
        multi_position_portfolio,
        capsys,
    ) -> None:
        """Multi-position portfolio has positions in 3 different urgency tiers.

        All 3 positions' strikes should appear.
        """
        PositionAgingDisplay(multi_position_portfolio).display()
        out = capsys.readouterr().out
        for strike in ("95", "100", "105"):
            assert strike in out, f"Expected strike {strike} in output"

    def test_display_uses_fresh_today_on_each_call(
        self,
        single_position_portfolio,
        capsys,
    ) -> None:
        """Each display() call computes 'today' freshly — not cached at init."""
        d = PositionAgingDisplay(single_position_portfolio)

        # First call: "today" is now
        fixed_t0 = datetime.now(tz=UTC)
        d.display(today=fixed_t0)
        out_t0 = capsys.readouterr().out

        # Second call: "today" is 10 days later → days-to-expiry should decrease
        fixed_t1 = fixed_t0 + timedelta(days=10)
        d.display(today=fixed_t1)
        out_t1 = capsys.readouterr().out

        # Both outputs should be non-empty and differ
        assert out_t0
        assert out_t1
        # The later call should show fewer days remaining
        # (exact string comparison is fragile; just assert they're different)
        assert out_t0 != out_t1
