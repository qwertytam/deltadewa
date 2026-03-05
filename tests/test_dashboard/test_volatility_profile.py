"""Tests for deltadewa.dashboard.volatility_profile.VolatilityProfileDisplay.

Key areas:
- display() with pre-computed vol_stats passes through without recomputing
- display() with vol_stats=None computes stats internally
- Empty portfolio handled gracefully
- Multi-position output contains per-position info
"""

# ruff: noqa: S101 D101 D102 ANN001
# pylint: disable=missing-function-docstring, missing-class-docstring

from __future__ import annotations

import datetime
from datetime import timedelta, timezone

from deltadewa.analysis.volatility import get_volatility_stats
from deltadewa.constants import OptionType
from deltadewa.dashboard.volatility_profile import VolatilityProfileDisplay
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.reporting.console import ConsoleReporter

# ===========================================================================
# Construction
# ===========================================================================


class TestVolatilityProfileDisplayConstruction:
    def test_constructs_with_portfolio_only(
        self, single_position_portfolio
    ) -> None:
        d = VolatilityProfileDisplay(single_position_portfolio)
        assert d is not None

    def test_constructs_with_reporter(
        self, single_position_portfolio, reporter
    ) -> None:
        d = VolatilityProfileDisplay(single_position_portfolio, reporter)
        assert d is not None

    def test_default_reporter_created_when_none(
        self, single_position_portfolio
    ) -> None:
        d = VolatilityProfileDisplay(single_position_portfolio)
        assert d._reporter is not None
        assert isinstance(d._reporter, ConsoleReporter)

    def test_custom_reporter_stored(
        self, single_position_portfolio, reporter
    ) -> None:
        d = VolatilityProfileDisplay(single_position_portfolio, reporter)
        assert d._reporter is reporter


# ===========================================================================
# display() — smoke tests
# ===========================================================================


class TestVolatilityProfileDisplay:
    def test_display_does_not_raise_empty_portfolio(
        self, empty_portfolio
    ) -> None:
        VolatilityProfileDisplay(empty_portfolio).display()

    def test_display_does_not_raise_single_position(
        self, single_position_portfolio
    ) -> None:
        VolatilityProfileDisplay(single_position_portfolio).display()

    def test_display_does_not_raise_multi_position(
        self, multi_position_portfolio
    ) -> None:
        VolatilityProfileDisplay(multi_position_portfolio).display()

    def test_display_with_precomputed_stats_does_not_raise(
        self, single_position_portfolio
    ) -> None:
        vol_stats = get_volatility_stats(single_position_portfolio)
        VolatilityProfileDisplay(single_position_portfolio).display(
            vol_stats=vol_stats
        )

    def test_display_without_stats_does_not_raise(
        self, single_position_portfolio
    ) -> None:
        VolatilityProfileDisplay(single_position_portfolio).display(
            vol_stats=None
        )


# ===========================================================================
# Output content assertions
# ===========================================================================


class TestVolatilityProfileOutput:
    def test_volatility_value_appears_in_output(
        self, single_position_portfolio, capsys
    ) -> None:
        """The portfolio's default volatility (20%) should appear somewhere."""
        VolatilityProfileDisplay(single_position_portfolio).display()
        out = capsys.readouterr().out
        # 20% could appear as "20" or "0.20" or "20.00%"
        assert "20" in out

    def test_empty_portfolio_outputs_message(
        self, empty_portfolio, capsys
    ) -> None:
        VolatilityProfileDisplay(empty_portfolio).display()
        out = capsys.readouterr().out
        assert len(out) > 0

    def test_multi_position_output_has_multiple_lines(
        self, multi_position_portfolio, capsys
    ) -> None:
        """3-position portfolio should produce more output than a 1-position one."""
        VolatilityProfileDisplay(multi_position_portfolio).display()
        multi_out = capsys.readouterr().out

        single = OptionPortfolio(spot_price=100.0, volatility=0.20)
        single.add_position(
            strike_price=100.0,
            maturity_date=datetime.datetime.now(tz=timezone.utc)
            + timedelta(days=45),
            quantity=1,
            option_type=OptionType.CALL,
        )
        VolatilityProfileDisplay(single).display()
        single_out = capsys.readouterr().out

        assert len(multi_out) > len(single_out)

    def test_custom_vol_position_highlighted(
        self, portfolio_with_custom_vol, capsys
    ) -> None:
        """Custom volatility of 30% should appear in output."""
        VolatilityProfileDisplay(portfolio_with_custom_vol).display()
        out = capsys.readouterr().out
        assert "30" in out


# ===========================================================================
# Internal stats computation matches direct call
# ===========================================================================


class TestVolatilityProfileStatsConsistency:
    def test_internal_computation_matches_get_volatility_stats(
        self, single_position_portfolio
    ) -> None:
        """The stats computed internally by display() should equal those from
        get_volatility_stats() called directly."""
        d = VolatilityProfileDisplay(single_position_portfolio)
        # Expose internal computation via a helper method
        internal_stats = d._compute_vol_stats()
        direct_stats = get_volatility_stats(single_position_portfolio)
        assert internal_stats == direct_stats

    def test_empty_portfolio_stats_is_empty_dict(self, empty_portfolio) -> None:
        d = VolatilityProfileDisplay(empty_portfolio)
        stats = d._compute_vol_stats()
        assert stats == {}
