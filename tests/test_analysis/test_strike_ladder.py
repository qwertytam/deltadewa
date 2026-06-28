"""Tests for deltadewa.analysis.strike_ladder."""

from __future__ import annotations

import pytest

from deltadewa.analysis.strike_ladder import (
    LadderRung,
    build_strike_ladder,
    strike_for_delta,
)
from deltadewa.constants import ExerciseStyle
from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMonetization,
    IpsMonetizationStep,
    IpsPricing,
    IpsProgram,
    IpsTriggers,
)
from deltadewa.portfolio.core import OptionPortfolio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spx_portfolio(
    *,
    spot: float = 5000.0,
    qty: float = 100.0,
    vol: float = 0.20,
    rate: float = 0.04,
    div: float = 0.015,
    exercise_style: ExerciseStyle = ExerciseStyle.EUROPEAN,
) -> OptionPortfolio:
    return OptionPortfolio(
        spot_price=spot,
        underlying_quantity=qty,
        volatility=vol,
        risk_free_rate=rate,
        dividend_yield=div,
        default_exercise_style=exercise_style,
    )


def _make_ips(
    *,
    annual_carry_pct: float = 2.0,
    crash_scenario_pct: float = -25.0,
    max_tolerance_pct: float = 20.0,
    target_min_pct: float = 5.0,
    target_max_pct: float = 30.0,
) -> IpsConfig:
    return IpsConfig(
        program=IpsProgram(name="Test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=annual_carry_pct),
        convexity=IpsConvexity(
            crash_scenario_pct=crash_scenario_pct,
            target_min_pct=target_min_pct,
            target_max_pct=target_max_pct,
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=max_tolerance_pct),
        triggers=IpsTriggers(
            delta_drift_warn_pct=5.0,
            delta_drift_action_pct=10.0,
            theta_cost_acceptable_pct=3.0,
            roll_time_months=1.0,
            rally_rebalance_pct=10.0,
            strike_drift_max_otm_pct=15.0,
        ),
        monetization=IpsMonetization(
            schedule=(IpsMonetizationStep(gain_pct=50.0, sell_pct=25.0),),
        ),
    )


# ---------------------------------------------------------------------------
# strike_for_delta
# ---------------------------------------------------------------------------


class TestStrikeForDelta:
    """Tests for strike_for_delta."""

    def test_solved_strike_is_below_spot(self) -> None:
        """A 10-delta put strike must be below spot (OTM)."""
        portfolio = _make_spx_portfolio(spot=5000.0)
        strike = strike_for_delta(
            portfolio, target_delta=0.10, maturity_years=0.25,
        )
        assert strike is not None
        assert strike < portfolio.spot_price

    def test_delta_magnitude_matches_target(self) -> None:
        """|put_delta| at the solved strike ≈ target_delta (within 1e-4)."""
        from deltadewa.analysis.candidate import evaluate_candidate

        portfolio = _make_spx_portfolio(spot=5000.0)
        target = 0.10
        strike = strike_for_delta(
            portfolio, target_delta=target, maturity_years=0.25,
        )
        assert strike is not None
        metrics = evaluate_candidate(
            portfolio,
            strike=strike,
            maturity_years=0.25,
            crash_pct=-25.0,
        )
        assert abs(metrics.put_delta) == pytest.approx(target, abs=1e-4)

    def test_higher_target_delta_gives_higher_strike(self) -> None:
        """Higher target delta (closer to ATM) → strike closer to spot."""
        portfolio = _make_spx_portfolio(spot=5000.0)
        strike_05 = strike_for_delta(
            portfolio, target_delta=0.05, maturity_years=0.25,
        )
        strike_15 = strike_for_delta(
            portfolio, target_delta=0.15, maturity_years=0.25,
        )
        assert strike_05 is not None
        assert strike_15 is not None
        assert strike_15 > strike_05

    def test_vol_override_accepted(self) -> None:
        """vol= override produces a result without error."""
        portfolio = _make_spx_portfolio()
        strike = strike_for_delta(
            portfolio, target_delta=0.10, maturity_years=0.25, vol=0.25,
        )
        assert strike is not None
        assert strike > 0.0

    def test_nonpositive_target_delta_raises(self) -> None:
        """target_delta <= 0 raises ValueError."""
        portfolio = _make_spx_portfolio()
        with pytest.raises(ValueError, match="target_delta must be positive"):
            strike_for_delta(
                portfolio, target_delta=0.0, maturity_years=0.25,
            )

    def test_negative_target_delta_raises(self) -> None:
        """Negative target_delta raises ValueError."""
        portfolio = _make_spx_portfolio()
        with pytest.raises(ValueError, match="target_delta must be positive"):
            strike_for_delta(
                portfolio, target_delta=-0.05, maturity_years=0.25,
            )

    def test_no_solution_returns_none(self) -> None:
        """target_delta >= 0.5 returns None — no OTM solution, no raise."""
        portfolio = _make_spx_portfolio()
        result = strike_for_delta(
            portfolio, target_delta=0.50, maturity_years=0.25,
        )
        assert result is None

    def test_priced_european(self) -> None:
        """Solver uses European exercise (portfolio.default_exercise_style)."""
        portfolio = _make_spx_portfolio(
            exercise_style=ExerciseStyle.EUROPEAN,
        )
        result = strike_for_delta(
            portfolio, target_delta=0.10, maturity_years=0.25,
        )
        assert result is not None
        assert result < portfolio.spot_price


# ---------------------------------------------------------------------------
# build_strike_ladder
# ---------------------------------------------------------------------------


class TestBuildStrikeLadder:
    """Tests for build_strike_ladder."""

    def test_returns_strike_ladder_type(self) -> None:
        """build_strike_ladder returns a list (StrikeLadder)."""
        portfolio = _make_spx_portfolio()
        ips = _make_ips()
        result = build_strike_ladder(
            portfolio,
            ips,
            target_deltas=[0.10],
            maturities_years=[0.25],
        )
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], LadderRung)

    def test_length_equals_product_of_inputs(self) -> None:
        """Result length == len(target_deltas) * len(maturities_years)."""
        portfolio = _make_spx_portfolio()
        ips = _make_ips()
        deltas = [0.05, 0.10, 0.15]
        maturities = [0.25, 0.50]
        result = build_strike_ladder(
            portfolio,
            ips,
            target_deltas=deltas,
            maturities_years=maturities,
        )
        assert len(result) == len(deltas) * len(maturities)

    def test_rung_target_delta_matches_input(self) -> None:
        """Each rung's target_delta matches the requested delta."""
        portfolio = _make_spx_portfolio()
        ips = _make_ips()
        deltas = [0.05, 0.10]
        result = build_strike_ladder(
            portfolio,
            ips,
            target_deltas=deltas,
            maturities_years=[0.25],
        )
        assert result[0].target_delta == pytest.approx(0.05)
        assert result[1].target_delta == pytest.approx(0.10)

    def test_rung_maturity_matches_input(self) -> None:
        """Each rung's maturity_years matches the requested maturity."""
        portfolio = _make_spx_portfolio()
        ips = _make_ips()
        maturities = [0.25, 0.50]
        result = build_strike_ladder(
            portfolio,
            ips,
            target_deltas=[0.10],
            maturities_years=maturities,
        )
        assert result[0].maturity_years == pytest.approx(0.25)
        assert result[1].maturity_years == pytest.approx(0.50)

    def test_rung_delta_approx_target(self) -> None:
        """|put_delta| in each rung ≈ target_delta (within 1e-3)."""
        portfolio = _make_spx_portfolio()
        ips = _make_ips()
        deltas = [0.05, 0.10, 0.15]
        result = build_strike_ladder(
            portfolio,
            ips,
            target_deltas=deltas,
            maturities_years=[0.25],
        )
        for rung in result:
            assert abs(rung.metrics.put_delta) == pytest.approx(
                rung.target_delta, abs=1e-3,
            )

    def test_meets_target_within_budget_compound_flag(self) -> None:
        """meets_target_within_budget == within_budget AND meets_convexity."""
        portfolio = _make_spx_portfolio()
        ips = _make_ips()
        result = build_strike_ladder(
            portfolio,
            ips,
            target_deltas=[0.05, 0.10, 0.15],
            maturities_years=[0.25, 0.50],
        )
        for rung in result:
            expected = rung.within_budget and rung.meets_convexity
            assert rung.meets_target_within_budget == expected

    def test_deterministic_output(self) -> None:
        """Identical inputs produce identical ladder."""
        portfolio = _make_spx_portfolio()
        ips = _make_ips()
        kwargs: dict = {
            "target_deltas": [0.10],
            "maturities_years": [0.25],
        }
        r1 = build_strike_ladder(portfolio, ips, **kwargs)
        r2 = build_strike_ladder(portfolio, ips, **kwargs)
        assert r1[0].metrics.strike == pytest.approx(r2[0].metrics.strike)
        assert r1[0].contracts_needed == r2[0].contracts_needed

    def test_carry_budget_on_each_rung(self) -> None:
        """Carry budget on each rung = annual_carry_pct / 100 * notional."""
        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        ips = _make_ips(annual_carry_pct=2.0)
        result = build_strike_ladder(
            portfolio,
            ips,
            target_deltas=[0.10],
            maturities_years=[0.25],
        )
        expected_budget = 2.0 / 100.0 * (5000.0 * 100.0)
        assert result[0].carry_budget == pytest.approx(expected_budget)

    def test_rung_agrees_with_direct_helpers(self) -> None:
        """Rung fields agree with evaluate_candidate + size_from_unit."""
        from deltadewa.analysis.candidate import evaluate_candidate
        from deltadewa.analysis.sizing import (
            required_crash_offset,
            size_from_unit,
        )

        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        ips = _make_ips(
            annual_carry_pct=2.0,
            crash_scenario_pct=-25.0,
            max_tolerance_pct=20.0,
        )
        result = build_strike_ladder(
            portfolio,
            ips,
            target_deltas=[0.10],
            maturities_years=[0.25],
        )
        assert len(result) == 1
        rung = result[0]

        # Re-derive from shared helpers using the rung's solved strike.
        book_notional = 100.0 * 5000.0
        carry_budget = 2.0 / 100.0 * book_notional
        crash_pct = -25.0
        metrics = evaluate_candidate(
            portfolio,
            strike=rung.metrics.strike,
            maturity_years=0.25,
            crash_pct=crash_pct,
        )
        offset = required_crash_offset(book_notional, crash_pct, 20.0)
        contracts, carry, within, headroom, _max = size_from_unit(
            offset,
            metrics.per_contract_payoff,
            metrics.per_contract_carry,
            carry_budget,
        )

        assert rung.metrics.put_delta == pytest.approx(metrics.put_delta)
        assert rung.metrics.per_contract_carry == pytest.approx(
            metrics.per_contract_carry,
        )
        assert rung.contracts_needed == contracts
        assert rung.implied_annual_carry == pytest.approx(carry)
        assert rung.within_budget == within
        assert rung.carry_headroom == pytest.approx(headroom)

    def test_no_solution_rung_skipped(self) -> None:
        """Unsolvable target_delta produces no rung — no raise."""
        portfolio = _make_spx_portfolio()
        ips = _make_ips()
        result = build_strike_ladder(
            portfolio,
            ips,
            target_deltas=[0.50],
            maturities_years=[0.25],
        )
        assert result == []

    def test_empty_portfolio_no_raise(self) -> None:
        """Portfolio with zero underlying_quantity raises no exception."""
        portfolio = _make_spx_portfolio(qty=0.0)
        ips = _make_ips()
        result = build_strike_ladder(
            portfolio,
            ips,
            target_deltas=[0.10],
            maturities_years=[0.25],
        )
        assert isinstance(result, list)
