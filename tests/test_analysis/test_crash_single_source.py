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

import pytest

from deltadewa import constants as const
from deltadewa.analysis import health as health_module
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.candidate import evaluate_candidate
from deltadewa.analysis.crash_payoff import compute_crash_convexity
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.analysis.monitor_scenario import build_scenario
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
# Representative crash vol shock for the direct gauge calls.
_VOL_SHOCK = 0.15


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


def _make_ips(
    crash_scenario_pct: float,
    *,
    crash_vol_shock: float = 0.15,
) -> IpsConfig:
    """Full IpsConfig parameterised on the crash move and vol shock."""
    return IpsConfig(
        program=IpsProgram(name="test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=crash_scenario_pct,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=crash_vol_shock,
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=20.0),
        triggers=IpsTriggers(
            delta_ratio_deviation_warn_pct=5.0,
            delta_ratio_deviation_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_at_months_remaining=1.0,
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
            CrashShock(
                crash_scenario_pct=_SHALLOW_PCT,
                crash_vol_shock=_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=0.10,
            ),
        )
        deep = analyzer.calculate_crash_convexity_pct(
            CrashShock(
                crash_scenario_pct=_DEEP_PCT,
                crash_vol_shock=_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=0.10,
            ),
        )

        assert shallow != deep

    def test_health_metrics_and_hedge_success_move_together(self) -> None:
        """crash_convexity_pct AND hedge_success_pct track the scenario."""
        analyzer = PortfolioAnalyzer(_make_hedged_book())

        shallow = analyzer.calculate_health_metrics(
            cumulative_carry_paid=1_000.0,
            crash=_make_ips(_SHALLOW_PCT).convexity,
        )
        deep = analyzer.calculate_health_metrics(
            cumulative_carry_paid=1_000.0,
            crash=_make_ips(_DEEP_PCT).convexity,
        )

        assert shallow["crash_convexity_pct"] != deep["crash_convexity_pct"]
        assert shallow["hedge_success_pct"] != deep["hedge_success_pct"]

    def test_health_metrics_apply_the_bundled_vol_shock(self) -> None:
        """The bundled crash vol shock reaches the gauge (never zeroed).

        Regression for the diverging-knobs trap: before the fix a caller could
        pass a crash scenario while ``crash_vol_shock`` silently defaulted to
        ``0.0``, understating convexity with no signal. The scenario and its
        vol shock now travel together in one ``IpsConvexity``, so at the same
        scenario a larger shock must move the gauge.
        """
        analyzer = PortfolioAnalyzer(_make_hedged_book())

        spot_only = analyzer.calculate_health_metrics(
            crash=_make_ips(_DEEP_PCT, crash_vol_shock=0.0).convexity,
        )
        shocked = analyzer.calculate_health_metrics(
            crash=_make_ips(_DEEP_PCT, crash_vol_shock=0.30).convexity,
        )

        assert (
            spot_only["crash_convexity_pct"] != shocked["crash_convexity_pct"]
        )

    def test_scenario_table_moves_with_scenario(self) -> None:
        """The scenario table's IPS-anchored payoff ratio tracks the move."""
        portfolio = _make_hedged_book()

        shallow = compute_crash_convexity(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=0.0,
                crash_vol_shock=_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=0.10,
            ),
            ips_convexity=_make_ips(_SHALLOW_PCT).convexity,
        )
        deep = compute_crash_convexity(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=0.0,
                crash_vol_shock=_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=0.10,
            ),
            ips_convexity=_make_ips(_DEEP_PCT).convexity,
        )

        assert shallow.payoff_vs_premium != deep.payoff_vs_premium

    def test_roll_trigger_moves_with_scenario(self) -> None:
        """evaluate_roll_status's crash convexity tracks the IPS move."""
        portfolio = _make_hedged_book()

        shallow = evaluate_roll_status(portfolio, _make_ips(_SHALLOW_PCT))
        deep = evaluate_roll_status(portfolio, _make_ips(_DEEP_PCT))

        assert shallow[0].crash_convexity_pct != deep[0].crash_convexity_pct

    def test_missing_scenario_degrades_to_zero_not_a_literal(self) -> None:
        """With no IPS the crash gauges are disabled (0.0, never hardcoded)."""
        analyzer = PortfolioAnalyzer(_make_hedged_book())

        metrics = analyzer.calculate_health_metrics(
            cumulative_carry_paid=1_000.0,
            crash=None,
        )

        assert metrics["crash_convexity_pct"] == pytest.approx(0.0, rel=1e-8)
        assert metrics["hedge_success_pct"] == pytest.approx(0.0, rel=1e-8)

    def test_no_crash_scenario_literal_in_health_source(self) -> None:
        """grep guard: no hardcoded crash move survives in health.py."""
        source = Path(health_module.__file__).read_text(encoding="utf-8")

        # The old -20% multiplier default and its parameter name are gone.
        assert "0.80" not in source
        assert "crash_pct" not in source
        # Scenario is taken from a parameter, not a literal.
        assert "crash_scenario_pct" in source


class TestRollMatchesGauge:
    """§7.5 — the roll trigger shares the gauge basis AND the IPS vol shock."""

    @staticmethod
    def _gauge(portfolio: OptionPortfolio, ips: IpsConfig) -> float:
        """The health-gauge convexity at the IPS scenario and vol shock."""
        return PortfolioAnalyzer(portfolio).calculate_crash_convexity_pct(
            CrashShock.from_ips(ips.convexity),
        )

    def test_roll_convexity_equals_gauge_for_same_book(self) -> None:
        """roll_status's crash convexity == the gauge's, same book and IPS.

        Regression for the spot-only roll trigger: before the fix the roll
        used ``vol_shock=0`` while the gauge used the IPS shock, so a
        conformant book could read as failing convexity on the roll and
        passing on the gauge.
        """
        portfolio = _make_hedged_book()
        ips = _make_ips(_DEEP_PCT, crash_vol_shock=0.15)

        roll = evaluate_roll_status(portfolio, ips)[0].crash_convexity_pct

        assert roll == pytest.approx(self._gauge(portfolio, ips))

    def test_roll_and_gauge_move_together_with_vol_shock(self) -> None:
        """Changing only crash_vol_shock moves roll and gauge together."""
        portfolio = _make_hedged_book()
        ips_lo = _make_ips(_DEEP_PCT, crash_vol_shock=0.10)
        ips_hi = _make_ips(_DEEP_PCT, crash_vol_shock=0.20)

        roll_lo = evaluate_roll_status(portfolio, ips_lo)[0].crash_convexity_pct
        roll_hi = evaluate_roll_status(portfolio, ips_hi)[0].crash_convexity_pct

        # The vol shock is actually consulted (the two differ)...
        assert roll_lo != roll_hi
        # ...and the roll tracks the gauge at each shock.
        assert roll_lo == pytest.approx(self._gauge(portfolio, ips_lo))
        assert roll_hi == pytest.approx(self._gauge(portfolio, ips_hi))


# A fixed valuation date (not datetime.now()) so a maturity built from an
# integer day count round-trips exactly through evaluate_candidate's own
# ``valuation_date + timedelta(days=round(maturity_years * DAYS_PER_YEAR))``
# reconstruction — two independent ``datetime.now()`` calls a few
# microseconds apart would not.
_VALUATION_DATE = datetime(2026, 1, 1, tzinfo=UTC)
_MATURITY_DAYS = 200


def _make_single_leg_book() -> OptionPortfolio:
    """One long put, quantity 10 — the whole hedge value IS this one leg's.

    ``crash_hedge_value`` excludes the underlying and there is nothing else
    in the book, so the all-legs value ``/monitor`` reads is exactly this
    leg's own repriced value at quantity 10 — no aggregation to account for.
    """
    portfolio = OptionPortfolio(
        spot_price=100.0,
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        underlying_quantity=100.0,
        valuation_date=_VALUATION_DATE,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=90.0,
        maturity_date=_VALUATION_DATE + timedelta(days=_MATURITY_DAYS),
        quantity=10,
        option_type=OptionType.PUT,
    )
    return portfolio


class TestPlanningZoneAgreesWithMonitor:
    """/design's PLANNING zone must reprice the IPS crash exactly as /monitor.

    ``candidate.py``'s own docstring promises this ("evaluating a candidate
    at a strike the book already holds yields the held leg's per-contract
    crash value exactly"). Pinned here as a regression test against the two
    real call sites — ``sizing.py``'s ``evaluate_candidate`` (the PLANNING
    zone's engine call) and ``monitor_scenario.build_scenario`` (/monitor)
    — not just the shared helper underneath them, so the PLANNING zone
    header's "agrees with /monitor to the cent" claim is enforced, not
    merely asserted. If this ever fails, that header text is a lie.
    """

    def test_sizing_candidate_matches_monitor_at_ips_crash_point(self) -> None:
        portfolio = _make_single_leg_book()
        ips = _make_ips(_DEEP_PCT, crash_vol_shock=0.15)
        maturity_years = _MATURITY_DAYS / const.DAYS_PER_YEAR

        candidate = evaluate_candidate(
            portfolio,
            strike=90.0,
            maturity_years=maturity_years,
            shock=CrashShock.from_ips(ips.convexity),
        )
        monitor_value = build_scenario(
            portfolio,
            ips,
            spot_pct=ips.convexity.crash_scenario_pct,
            vol_points=ips.convexity.crash_vol_shock,
            quantity=portfolio.underlying_quantity,
        ).hedge_value_shocked

        # Single-leg book (quantity 10): the whole hedge value IS this one
        # candidate's repriced value, ten times over.
        assert candidate.per_contract_payoff * 10 == pytest.approx(
            monitor_value,
            abs=0.005,
        )
