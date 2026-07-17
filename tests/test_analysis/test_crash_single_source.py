"""Mo1 single-source guard: one crash scenario drives every panel.

These tests pin the M1.2/Mo1 contract from ``docs/repricing-methodology.md``
§2: the crash *move* is single-sourced from
``IpsConvexity.crash_scenario_pct``. Changing that one value must move the
health gauge, the crash scenario table, the roll-status trigger, and the
hedge-success gauge together, and no crash-scenario literal may survive in the
crash-convexity code path.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from deltadewa.analysis import health as health_module
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_payoff import compute_crash_convexity
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.constants import ExerciseStyle, OptionType
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

# Two clearly-distinct crash moves used throughout: a shallow -10% and a deep
# -30%. For a 90-strike put on a spot-100 book these bracket the strike, so
# every crash-derived figure must differ between them.
_SHALLOW_PCT = -10.0
_DEEP_PCT = -30.0


def _make_hedged_book() -> OptionPortfolio:
    """Long index + one 10%-OTM long put — a non-degenerate crash book."""
    portfolio = OptionPortfolio(
        spot_price=100.0,
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        underlying_quantity=100.0,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=90.0,
        maturity_date=datetime.now(tz=UTC) + timedelta(days=200),
        quantity=10,
        option_type=OptionType.PUT,
    )
    portfolio.positions[0].entry_premium = 2.0
    return portfolio


def _make_ips(crash_scenario_pct: float) -> IpsConfig:
    """Full IpsConfig parameterised only on the crash move."""
    return IpsConfig(
        program=IpsProgram(name="test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=crash_scenario_pct,
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


class TestCrashScenarioSingleSource:
    """§7.5 — one crash move moves every crash-derived panel together."""

    def test_health_gauge_moves_with_scenario(self) -> None:
        """The crash-convexity gauge tracks crash_scenario_pct."""
        analyzer = PortfolioAnalyzer(_make_hedged_book())

        shallow = analyzer.calculate_crash_convexity_pct(
            crash_scenario_pct=_SHALLOW_PCT,
        )
        deep = analyzer.calculate_crash_convexity_pct(
            crash_scenario_pct=_DEEP_PCT,
        )

        assert shallow != deep

    def test_health_metrics_and_hedge_success_move_together(self) -> None:
        """crash_convexity_pct AND hedge_success_pct track the scenario."""
        analyzer = PortfolioAnalyzer(_make_hedged_book())

        shallow = analyzer.calculate_health_metrics(
            cumulative_carry_paid=1_000.0,
            crash_scenario_pct=_SHALLOW_PCT,
        )
        deep = analyzer.calculate_health_metrics(
            cumulative_carry_paid=1_000.0,
            crash_scenario_pct=_DEEP_PCT,
        )

        assert shallow["crash_convexity_pct"] != deep["crash_convexity_pct"]
        assert shallow["hedge_success_pct"] != deep["hedge_success_pct"]

    def test_scenario_table_moves_with_scenario(self) -> None:
        """The scenario table's IPS-anchored payoff ratio tracks the move."""
        portfolio = _make_hedged_book()

        shallow = compute_crash_convexity(
            portfolio,
            ips_convexity=_make_ips(_SHALLOW_PCT).convexity,
        )
        deep = compute_crash_convexity(
            portfolio,
            ips_convexity=_make_ips(_DEEP_PCT).convexity,
        )

        assert shallow.payoff_ratio != deep.payoff_ratio

    def test_roll_trigger_moves_with_scenario(self) -> None:
        """evaluate_roll_status's crash convexity tracks the IPS move."""
        portfolio = _make_hedged_book()

        shallow = evaluate_roll_status(portfolio, _make_ips(_SHALLOW_PCT))
        deep = evaluate_roll_status(portfolio, _make_ips(_DEEP_PCT))

        assert shallow[0].crash_convexity_pct != deep[0].crash_convexity_pct

    def test_missing_scenario_degrades_to_zero_not_a_literal(self) -> None:
        """With no IPS scenario the crash gauges read 0.0 (never hardcoded)."""
        analyzer = PortfolioAnalyzer(_make_hedged_book())

        metrics = analyzer.calculate_health_metrics(
            cumulative_carry_paid=1_000.0,
            crash_scenario_pct=None,
        )

        assert metrics["crash_convexity_pct"] == 0.0
        assert metrics["hedge_success_pct"] == 0.0

    def test_no_crash_scenario_literal_in_health_source(self) -> None:
        """grep guard: no hardcoded crash move survives in health.py."""
        source = Path(health_module.__file__).read_text(encoding="utf-8")

        # The old -20% multiplier default and its parameter name are gone.
        assert "0.80" not in source
        assert "crash_pct" not in source
        # Scenario is taken from a parameter, not a literal.
        assert "crash_scenario_pct" in source
