"""Tests for deltadewa.dashboard.roll_status.RollStatusDisplay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.dashboard.roll_status import RollStatusDisplay
from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMonetization,
    IpsPricing,
    IpsProgram,
    IpsTriggers,
)
from deltadewa.portfolio.core import OptionPortfolio


def _make_ips_config() -> IpsConfig:
    return IpsConfig(
        program=IpsProgram(name="test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=20.0),
        triggers=IpsTriggers(
            delta_drift_warn_pct=5.0,
            delta_drift_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_time_months=1.0,
            rally_rebalance_pct=15.0,
            strike_drift_max_otm_pct=45.0,
        ),
        monetization=IpsMonetization(schedule=()),
    )


class TestRollStatusDisplay:
    """Smoke + output tests for RollStatusDisplay.display()."""

    def test_display_does_not_raise_empty_portfolio(self) -> None:
        """Test display() handles an empty portfolio gracefully."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        display = RollStatusDisplay(portfolio, _make_ips_config())

        display.display()

    def test_display_empty_portfolio_message(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test display() prints a no-positions message when empty."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        display = RollStatusDisplay(portfolio, _make_ips_config())

        display.display()

        out = capsys.readouterr().out
        assert "No positions" in out

    def test_display_shows_roll_verdict_for_imminent_position(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test display() shows a ROLL badge for a near-maturity position."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=90.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=5),
            quantity=10,
            option_type=OptionType.PUT,
        )
        display = RollStatusDisplay(portfolio, _make_ips_config())

        display.display()

        out = capsys.readouterr().out
        assert "ROLL" in out
        assert "PUT" in out
        assert "$90" in out

    def test_display_shows_hold_verdict_for_comfortable_position(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test display() shows a HOLD badge when nothing is triggered."""
        # No underlying notional means crash convexity is exactly 0%, so
        # widen the target band to include it (this test exercises the
        # time/drift triggers only, not the convexity trigger).
        ips = IpsConfig(
            program=IpsProgram(name="test", instrument="SPX"),
            pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
            budget=IpsBudget(annual_carry_pct=2.0),
            convexity=IpsConvexity(
                crash_scenario_pct=-25.0,
                target_min_pct=0.0,
                target_max_pct=100.0,
            ),
            drawdown=IpsDrawdown(max_tolerance_pct=20.0),
            triggers=IpsTriggers(
                delta_drift_warn_pct=5.0,
                delta_drift_action_pct=10.0,
                theta_cost_acceptable_pct=2.0,
                roll_time_months=1.0,
                rally_rebalance_pct=15.0,
                strike_drift_max_otm_pct=45.0,
            ),
            monetization=IpsMonetization(schedule=()),
        )
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=90.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=200),
            quantity=10,
            option_type=OptionType.PUT,
        )
        display = RollStatusDisplay(portfolio, ips)

        display.display(current_spot=100.0)

        out = capsys.readouterr().out
        assert "HOLD" in out

    def test_display_shows_na_roll_up_cost_for_hold(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test display() shows n/a roll-up cost when verdict is HOLD."""
        portfolio = OptionPortfolio(
            spot_price=100.0,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )
        portfolio.add_position(
            strike_price=90.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=200),
            quantity=10,
            option_type=OptionType.PUT,
            entry_spot=100.0,
        )
        ips = _make_ips_config()
        display = RollStatusDisplay(portfolio, ips)

        display.display(current_spot=100.0)

        out = capsys.readouterr().out
        assert "roll-up cost:" in out
