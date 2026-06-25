"""Tests for deltadewa.analysis.sizing."""

from __future__ import annotations

import sys

import pytest

from deltadewa.analysis.sizing import (
    HedgeSizingResult,
    required_crash_offset,
    size_from_unit,
    size_hedge,
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

# ruff: noqa: S101


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# required_crash_offset
# ---------------------------------------------------------------------------


class TestRequiredCrashOffset:
    """Tests for required_crash_offset."""

    def test_hand_computed_case(self) -> None:
        """25% crash, 20% tolerance → offset = 5% of notional."""
        result = required_crash_offset(1_000_000.0, -25.0, 20.0)
        assert result == pytest.approx(50_000.0)

    def test_floor_at_zero_crash_less_than_tolerance(self) -> None:
        """Crash smaller than tolerance → no offset required."""
        result = required_crash_offset(1_000_000.0, -10.0, 20.0)
        assert result == pytest.approx(0.0)

    def test_floor_at_zero_exact_boundary(self) -> None:
        """Crash exactly equals tolerance → offset is zero."""
        result = required_crash_offset(1_000_000.0, -20.0, 20.0)
        assert result == pytest.approx(0.0)

    def test_zero_notional(self) -> None:
        """Zero book notional → zero offset regardless of crash."""
        assert required_crash_offset(0.0, -30.0, 10.0) == 0.0

    def test_negative_notional_treated_as_zero(self) -> None:
        """Negative notional (invalid) → zero offset (defensive guard)."""
        assert required_crash_offset(-500_000.0, -25.0, 20.0) == 0.0


# ---------------------------------------------------------------------------
# size_from_unit
# ---------------------------------------------------------------------------


class TestSizeFromUnit:
    """Tests for size_from_unit."""

    def test_within_budget(self) -> None:
        """Standard case: 80 contracts, carry within budget."""
        contracts, carry, within, headroom, max_aff = size_from_unit(
            required_offset=200_000.0,
            per_contract_payoff=2_500.0,
            per_contract_carry=3_000.0,
            carry_budget=500_000.0,
        )
        assert contracts == 80  # ceil(200_000 / 2_500)
        assert carry == pytest.approx(240_000.0)
        assert within is True
        assert headroom == pytest.approx(260_000.0)
        assert max_aff == 166  # floor(500_000 / 3_000)

    def test_over_budget(self) -> None:
        """Large required offset pushes implied carry above budget."""
        contracts, carry, within, headroom, max_aff = size_from_unit(
            required_offset=1_000_000.0,
            per_contract_payoff=2_500.0,
            per_contract_carry=3_000.0,
            carry_budget=100_000.0,
        )
        assert contracts == 400  # ceil(1_000_000 / 2_500)
        assert carry == pytest.approx(1_200_000.0)
        assert within is False
        assert headroom == pytest.approx(-1_100_000.0)
        assert max_aff == 33  # floor(100_000 / 3_000)

    def test_zero_payoff_guard(self) -> None:
        """Zero payoff → contracts_needed is 0, no ZeroDivisionError."""
        contracts, carry, within, headroom, _max_aff = size_from_unit(
            required_offset=100_000.0,
            per_contract_payoff=0.0,
            per_contract_carry=3_000.0,
            carry_budget=500_000.0,
        )
        assert contracts == 0
        assert carry == pytest.approx(0.0)
        assert within is True
        assert headroom == pytest.approx(500_000.0)

    def test_zero_carry_guard(self) -> None:
        """Zero carry → max_affordable is sys.maxsize, no ZeroDivisionError."""
        _, _, _, _, max_aff = size_from_unit(
            required_offset=100_000.0,
            per_contract_payoff=2_500.0,
            per_contract_carry=0.0,
            carry_budget=500_000.0,
        )
        assert max_aff == sys.maxsize

    def test_exact_offset_no_rounding(self) -> None:
        """Required offset exactly divisible by payoff → no rounding up."""
        contracts, *_ = size_from_unit(
            required_offset=250_000.0,
            per_contract_payoff=2_500.0,
            per_contract_carry=3_000.0,
            carry_budget=1_000_000.0,
        )
        assert contracts == 100  # exact, no ceil effect


# ---------------------------------------------------------------------------
# size_hedge integration
# ---------------------------------------------------------------------------


class TestSizeHedge:
    """Integration tests for size_hedge — prices a real OptionValuation."""

    def test_returns_hedgesizingresult(self) -> None:
        """size_hedge returns HedgeSizingResult with correct types."""
        portfolio = _make_spx_portfolio()
        ips = _make_ips()
        result = size_hedge(
            portfolio,
            ips,
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert isinstance(result, HedgeSizingResult)
        assert isinstance(result.contracts_needed, int)

    def test_book_notional_math(self) -> None:
        """book_notional == abs(underlying_quantity) * spot_price."""
        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        result = size_hedge(
            portfolio,
            _make_ips(),
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert result.book_notional == pytest.approx(500_000.0)

    def test_carry_budget_math(self) -> None:
        """carry_budget == annual_carry_pct / 100 * book_notional."""
        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        ips = _make_ips(annual_carry_pct=2.0)
        result = size_hedge(
            portfolio, ips,
            candidate_pct_otm=5.0, candidate_maturity_years=0.25,
        )
        assert result.carry_budget == pytest.approx(10_000.0)

    def test_per_contract_payoff_intrinsic(self) -> None:
        """per_contract_payoff matches hand-computed intrinsic * 100."""
        # spot=5000, 5% OTM → strike=4750; crash=-25% → crash_spot=3750
        # intrinsic = 4750 - 3750 = 1000; per contract = 1000 * 100 = 100_000
        portfolio = _make_spx_portfolio(spot=5000.0)
        ips = _make_ips(crash_scenario_pct=-25.0)
        result = size_hedge(
            portfolio, ips,
            candidate_pct_otm=5.0, candidate_maturity_years=0.25,
        )
        assert result.per_contract_payoff == pytest.approx(100_000.0)

    def test_per_contract_carry_positive(self) -> None:
        """per_contract_carry is a positive dollar cost."""
        portfolio = _make_spx_portfolio()
        result = size_hedge(
            portfolio,
            _make_ips(),
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert result.per_contract_carry > 0.0

    def test_vol_override_changes_carry(self) -> None:
        """vol= override changes per_contract_carry vs portfolio.volatility."""
        portfolio = _make_spx_portfolio(vol=0.20)
        ips = _make_ips()
        r_low = size_hedge(
            portfolio, ips,
            candidate_pct_otm=5.0, candidate_maturity_years=0.25, vol=0.15,
        )
        r_high = size_hedge(
            portfolio, ips,
            candidate_pct_otm=5.0, candidate_maturity_years=0.25, vol=0.30,
        )
        assert r_high.per_contract_carry > r_low.per_contract_carry

    def test_european_exercise_style_used(self) -> None:
        """Candidate uses portfolio.default_exercise_style without error."""
        portfolio = _make_spx_portfolio(exercise_style=ExerciseStyle.EUROPEAN)
        result = size_hedge(
            portfolio,
            _make_ips(),
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert result.per_contract_carry > 0.0

    def test_convexity_in_band(self) -> None:
        """Achieved convexity inside IPS band → meets_convexity_target True.

        spot=5000, qty=100 → notional=500_000; crash=-25%, tol=20% →
        required_offset=25_000; strike=4750, crash_spot=3750 → payoff
        1000*100=100_000/contract; 1 contract → convexity=20% ∈ [5,30].
        """
        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        ips = _make_ips(
            crash_scenario_pct=-25.0,
            max_tolerance_pct=20.0,
            target_min_pct=5.0,
            target_max_pct=30.0,
        )
        result = size_hedge(
            portfolio, ips,
            candidate_pct_otm=5.0, candidate_maturity_years=0.25,
        )
        assert result.achieved_convexity_pct == pytest.approx(20.0)
        assert result.meets_convexity_target is True

    def test_convexity_out_of_band_above(self) -> None:
        """Achieved convexity above target_max → meets_convexity_target False.

        crash=-50%, tol=5% → required_offset=225_000; strike=4750,
        crash_spot=2500 → payoff=225_000/contract; 1 contract → convexity
        =45% > target_max=30%.
        """
        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        ips = _make_ips(
            crash_scenario_pct=-50.0,
            max_tolerance_pct=5.0,
            target_min_pct=5.0,
            target_max_pct=30.0,
        )
        result = size_hedge(
            portfolio, ips,
            candidate_pct_otm=5.0, candidate_maturity_years=0.25,
        )
        assert result.achieved_convexity_pct > 30.0
        assert result.meets_convexity_target is False

    def test_zero_notional_portfolio_no_raise(self) -> None:
        """Portfolio with underlying_quantity=0 → zero notional, no error."""
        portfolio = _make_spx_portfolio(qty=0.0)
        result = size_hedge(
            portfolio,
            _make_ips(),
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert result.book_notional == pytest.approx(0.0)
        assert result.required_crash_offset == pytest.approx(0.0)
        assert result.achieved_convexity_pct == pytest.approx(0.0)
