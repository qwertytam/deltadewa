"""Tests for deltadewa.dashboard.crash_payoff_display.CrashPayoffDisplay.

display() calls are no-ops outside IPython; we verify behaviour via the
print()ed headline (captured with capsys) and by checking display() does
not raise, mirroring test_position_detail.py's conventions.
"""

# pylint: disable=missing-function-docstring

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis.crash_payoff import crash_scenario_table
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.dashboard.crash_payoff_display import CrashPayoffDisplay
from deltadewa.ips_config import IpsConvexity
from deltadewa.portfolio.core import OptionPortfolio


def _make_long_put_portfolio(
    *,
    strike_price: float = 100.0,
    quantity: int = 10,
    spot_price: float = 100.0,
) -> OptionPortfolio:
    portfolio = OptionPortfolio(
        spot_price=spot_price,
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=strike_price,
        maturity_date=datetime.now(tz=UTC) + timedelta(days=60),
        quantity=quantity,
        option_type=OptionType.PUT,
    )
    return portfolio


def _make_ips_convexity(
    *,
    crash_scenario_pct: float = -20.0,
    target_min_pct: float = 0.0,
    target_max_pct: float = 100.0,
) -> IpsConvexity:
    return IpsConvexity(
        crash_scenario_pct=crash_scenario_pct,
        target_min_pct=target_min_pct,
        target_max_pct=target_max_pct,
    )


class TestCrashPayoffDisplayConstruction:
    """Tests for CrashPayoffDisplay construction."""

    def test_constructs_with_empty_portfolio(self, empty_portfolio) -> None:
        display = CrashPayoffDisplay(empty_portfolio)
        assert display is not None

    def test_constructs_with_long_put_portfolio(self) -> None:
        portfolio = _make_long_put_portfolio()
        display = CrashPayoffDisplay(portfolio)
        assert display is not None

    def test_stores_ips_convexity(self) -> None:
        portfolio = _make_long_put_portfolio()
        ips_convexity = _make_ips_convexity()
        display = CrashPayoffDisplay(portfolio, ips_convexity)
        # pylint: disable=protected-access
        assert display._ips_convexity is ips_convexity


class TestCrashPayoffDisplayMethod:
    """Tests for CrashPayoffDisplay.display()."""

    def test_empty_portfolio_prints_no_positions_message(
        self,
        empty_portfolio,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        CrashPayoffDisplay(empty_portfolio).display()
        out = capsys.readouterr().out
        assert "No positions in portfolio yet." in out

    def test_no_ips_convexity_prints_no_target_message(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        portfolio = _make_long_put_portfolio()
        CrashPayoffDisplay(portfolio, ips_convexity=None).display()
        out = capsys.readouterr().out
        assert "No IPS convexity target configured" in out

    def test_does_not_raise_with_shock_already_in_default_ladder(self) -> None:
        """crash_scenario_pct already present in the default shocks."""
        portfolio = _make_long_put_portfolio()
        ips_convexity = _make_ips_convexity(crash_scenario_pct=-20.0)
        CrashPayoffDisplay(portfolio, ips_convexity).display()

    def test_does_not_raise_with_shock_outside_default_ladder(self) -> None:
        """crash_scenario_pct missing from the default shocks (auto-add)."""
        portfolio = _make_long_put_portfolio()
        ips_convexity = _make_ips_convexity(crash_scenario_pct=-25.0)
        CrashPayoffDisplay(portfolio, ips_convexity).display()

    def test_headline_reports_pass_when_target_met(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Headline PASS/FAIL matches crash_scenario_table's meets_target."""
        portfolio = _make_long_put_portfolio(quantity=50)
        shocks = (-10.0, -20.0, -30.0, -40.0)
        # Discover the actual convexity_pct at -20% to build a target band
        # that this scenario is guaranteed to fall inside.
        oracle_rows = crash_scenario_table(portfolio, shocks=shocks)
        convexity_20 = next(
            row.convexity_pct for row in oracle_rows if row.shock_pct == -20.0
        )
        ips_convexity = _make_ips_convexity(
            crash_scenario_pct=-20.0,
            target_min_pct=convexity_20,
            target_max_pct=convexity_20,
        )

        CrashPayoffDisplay(portfolio, ips_convexity, shocks=shocks).display()

        out = capsys.readouterr().out
        assert "PASS" in out
        assert "FAIL" not in out

    def test_headline_reports_fail_when_target_missed(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        portfolio = _make_long_put_portfolio(quantity=50)
        shocks = (-10.0, -20.0, -30.0, -40.0)
        oracle_rows = crash_scenario_table(portfolio, shocks=shocks)
        convexity_20 = next(
            row.convexity_pct for row in oracle_rows if row.shock_pct == -20.0
        )
        # A band that excludes the actual convexity_pct value.
        ips_convexity = _make_ips_convexity(
            crash_scenario_pct=-20.0,
            target_min_pct=convexity_20 + 1.0,
            target_max_pct=convexity_20 + 2.0,
        )

        CrashPayoffDisplay(portfolio, ips_convexity, shocks=shocks).display()

        out = capsys.readouterr().out
        assert "FAIL" in out
