"""Tests for deltadewa.analysis.sizing."""

from __future__ import annotations

import datetime
import sys

import pytest

from deltadewa import constants as const
from deltadewa.analysis.sizing import (
    HedgeSizingResult,
    UnitSizingResult,
    beta_adjusted_notional,
    required_crash_offset,
    size_from_unit,
    size_hedge,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMonetization,
    IpsMonetizationStep,
    IpsPricing,
    IpsProgram,
    IpsSizing,
    IpsTriggers,
)
from deltadewa.portfolio.core import OptionPortfolio

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
    portfolio_beta: float = 1.0,
    skew_steepening: float = 0.0,
    skew_reference_delta: float = 0.10,
) -> IpsConfig:
    return IpsConfig(
        program=IpsProgram(name="Test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=annual_carry_pct),
        convexity=IpsConvexity(
            crash_scenario_pct=crash_scenario_pct,
            target_min_pct=target_min_pct,
            target_max_pct=target_max_pct,
            skew_steepening=skew_steepening,
            skew_reference_delta=skew_reference_delta,
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
        sizing=IpsSizing(portfolio_beta=portfolio_beta),
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

    def test_returns_unit_sizing_result(self) -> None:
        """size_from_unit returns a UnitSizingResult instance."""
        result = size_from_unit(
            required_offset=200_000.0,
            per_contract_payoff=2_500.0,
            per_contract_carry=3_000.0,
            carry_budget=500_000.0,
        )
        assert isinstance(result, UnitSizingResult)

    def test_within_budget(self) -> None:
        """Standard case: 80 contracts, carry within budget."""
        r = size_from_unit(
            required_offset=200_000.0,
            per_contract_payoff=2_500.0,
            per_contract_carry=3_000.0,
            carry_budget=500_000.0,
        )
        assert r.contracts_needed == 80  # ceil(200_000 / 2_500)
        assert r.implied_annual_carry == pytest.approx(240_000.0)
        assert r.within_budget is True
        assert r.carry_headroom == pytest.approx(260_000.0)
        assert r.max_affordable_contracts == 166  # floor(500_000 / 3_000)

    def test_over_budget(self) -> None:
        """Large required offset pushes implied carry above budget."""
        r = size_from_unit(
            required_offset=1_000_000.0,
            per_contract_payoff=2_500.0,
            per_contract_carry=3_000.0,
            carry_budget=100_000.0,
        )
        assert r.contracts_needed == 400  # ceil(1_000_000 / 2_500)
        assert r.implied_annual_carry == pytest.approx(1_200_000.0)
        assert r.within_budget is False
        assert r.carry_headroom == pytest.approx(-1_100_000.0)
        assert r.max_affordable_contracts == 33  # floor(100_000 / 3_000)

    def test_zero_payoff_guard(self) -> None:
        """Zero payoff → contracts_needed is 0, no ZeroDivisionError."""
        r = size_from_unit(
            required_offset=100_000.0,
            per_contract_payoff=0.0,
            per_contract_carry=3_000.0,
            carry_budget=500_000.0,
        )
        assert r.contracts_needed == 0
        assert r.implied_annual_carry == pytest.approx(0.0)
        assert r.within_budget is True
        assert r.carry_headroom == pytest.approx(500_000.0)

    def test_zero_carry_guard(self) -> None:
        """Zero carry → max_affordable_contracts is sys.maxsize."""
        r = size_from_unit(
            required_offset=100_000.0,
            per_contract_payoff=2_500.0,
            per_contract_carry=0.0,
            carry_budget=500_000.0,
        )
        assert r.max_affordable_contracts == sys.maxsize

    def test_exact_offset_no_rounding(self) -> None:
        """Required offset exactly divisible by payoff → no rounding up."""
        r = size_from_unit(
            required_offset=250_000.0,
            per_contract_payoff=2_500.0,
            per_contract_carry=3_000.0,
            carry_budget=1_000_000.0,
        )
        assert r.contracts_needed == 100  # exact, no ceil effect


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
            portfolio,
            ips,
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert result.carry_budget == pytest.approx(10_000.0)

    def test_per_contract_intrinsic_floor(self) -> None:
        """per_contract_intrinsic_floor matches hand-computed intrinsic * 100.

        spot=5000, 5% OTM → strike=4750; crash=-25% → crash_spot=3750;
        intrinsic = 4750 - 3750 = 1000; per contract = 1000 * 100 = 100_000.
        The repriced payoff is surfaced as a separate positive dollar value.
        """
        portfolio = _make_spx_portfolio(spot=5000.0)
        ips = _make_ips(crash_scenario_pct=-25.0)
        result = size_hedge(
            portfolio,
            ips,
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert result.per_contract_intrinsic_floor == pytest.approx(100_000.0)
        assert result.per_contract_payoff > 0.0

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
            portfolio,
            ips,
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
            vol=0.15,
        )
        r_high = size_hedge(
            portfolio,
            ips,
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
            vol=0.30,
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
        required_offset=25_000; strike=4750 → repriced payoff ≈ 100_000/
        contract; 1 contract → convexity ≈ 20%, inside the [5, 30] band.
        """
        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        ips = _make_ips(
            crash_scenario_pct=-25.0,
            max_tolerance_pct=20.0,
            target_min_pct=5.0,
            target_max_pct=30.0,
        )
        result = size_hedge(
            portfolio,
            ips,
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        # Achieved convexity lands inside the IPS band → target met.
        assert 5.0 <= result.achieved_convexity_pct <= 30.0
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
            portfolio,
            ips,
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert result.achieved_convexity_pct > 30.0
        assert result.meets_convexity_target is False

    def test_zero_notional_portfolio_raises(self) -> None:
        """No underlying position fails loud — never a fabricated result."""
        portfolio = _make_spx_portfolio(qty=0.0)
        with pytest.raises(ValueError, match="underlying position"):
            size_hedge(
                portfolio,
                _make_ips(),
                candidate_pct_otm=5.0,
                candidate_maturity_years=0.25,
            )


# ---------------------------------------------------------------------------
# beta_adjusted_notional
# ---------------------------------------------------------------------------


class TestBetaAdjustedNotional:
    """The pure beta-adjusted-notional helper (handbook §2499)."""

    def test_beta_one_is_identity(self) -> None:
        """Beta 1.0 leaves the book notional unchanged."""
        assert beta_adjusted_notional(500_000.0, 1.0) == pytest.approx(
            500_000.0,
        )

    def test_beta_below_one_sizes_down(self) -> None:
        """Beta 0.85 sizes the hedge notional down to 85% of book."""
        assert beta_adjusted_notional(500_000.0, 0.85) == pytest.approx(
            425_000.0,
        )

    def test_beta_above_one_sizes_up(self) -> None:
        """Beta 1.3 sizes the hedge notional up to 130% of book."""
        assert beta_adjusted_notional(500_000.0, 1.3) == pytest.approx(
            650_000.0,
        )


# ---------------------------------------------------------------------------
# Beta-adjusted size_hedge
# ---------------------------------------------------------------------------


class TestBetaAdjustedSizing:
    """size_hedge sizes against book_notional * portfolio_beta."""

    def test_beta_one_reproduces_pre_beta_sizing(self) -> None:
        """Beta 1.0: adjusted notional == book; offset unchanged (25_000)."""
        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        result = size_hedge(
            portfolio,
            _make_ips(
                crash_scenario_pct=-25.0,
                max_tolerance_pct=20.0,
                portfolio_beta=1.0,
            ),
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert result.portfolio_beta == pytest.approx(1.0)
        assert result.beta_adjusted_notional == pytest.approx(500_000.0)
        # 500_000 * (25 - 20) / 100 — the pre-beta offset, unchanged.
        assert result.required_crash_offset == pytest.approx(25_000.0)

    def test_beta_scales_notional_and_offset_proportionally(self) -> None:
        """Beta 2.0 doubles the beta-adjusted notional and the crash offset."""
        portfolio = _make_spx_portfolio(spot=5000.0, qty=10_000.0)
        base = size_hedge(
            portfolio,
            _make_ips(portfolio_beta=1.0),
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        scaled = size_hedge(
            portfolio,
            _make_ips(portfolio_beta=2.0),
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert scaled.beta_adjusted_notional == pytest.approx(
            2.0 * base.beta_adjusted_notional,
        )
        assert scaled.required_crash_offset == pytest.approx(
            2.0 * base.required_crash_offset,
        )
        assert scaled.contracts_needed > base.contracts_needed

    def test_carry_budget_not_beta_adjusted(self) -> None:
        """Carry budget stays on the true book value, independent of beta."""
        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        base = size_hedge(
            portfolio,
            _make_ips(portfolio_beta=1.0),
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        scaled = size_hedge(
            portfolio,
            _make_ips(portfolio_beta=1.5),
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert scaled.carry_budget == pytest.approx(base.carry_budget)

    def test_beta_single_sourced_from_ips(self) -> None:
        """The beta used is exactly ips_config.sizing.portfolio_beta."""
        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        ips = _make_ips(portfolio_beta=1.3)
        result = size_hedge(
            portfolio,
            ips,
            candidate_pct_otm=5.0,
            candidate_maturity_years=0.25,
        )
        assert result.portfolio_beta == pytest.approx(1.3)
        assert result.beta_adjusted_notional == pytest.approx(
            result.book_notional * ips.sizing.portfolio_beta,
        )

    def test_sizing_payoff_agrees_with_gauge_at_equal_depth(self) -> None:
        """size_hedge per-contract payoff equals the book gauge at equal depth.

        The M1.7 acceptance criterion: a candidate sized by the workbench and a
        held leg priced by the book gauge run through one skew function, so at
        the same strike/tenor their per-contract crash value is identical — the
        workbench can no longer under-state payoffs relative to the gauge.
        """
        from deltadewa.analysis.crash_repricing import crash_hedge_value

        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        ips = _make_ips(skew_steepening=0.10, crash_scenario_pct=-25.0)
        pct_otm = 30.0
        maturity_years = 1.5

        sized = size_hedge(
            portfolio,
            ips,
            candidate_pct_otm=pct_otm,
            candidate_maturity_years=maturity_years,
        )

        # Book gauge basis: a held leg at the same strike/tenor priced through
        # the same crash_hedge_value with the IPS skew.
        strike = portfolio.spot_price * (1.0 - pct_otm / 100.0)
        maturity_date = portfolio.valuation_date + datetime.timedelta(
            days=round(maturity_years * const.DAYS_PER_YEAR),
        )
        portfolio.add_position(
            strike_price=strike,
            maturity_date=maturity_date,
            quantity=1,
            option_type=OptionType.PUT,
            volatility=portfolio.volatility,
        )
        gauge_per_contract = crash_hedge_value(
            portfolio,
            crash_move=ips.convexity.crash_scenario_pct / 100.0,
            vol_shock=ips.convexity.crash_vol_shock,
            skew_steepening=ips.convexity.skew_steepening,
            skew_reference_delta=ips.convexity.skew_reference_delta,
            positions=[portfolio.positions[0]],
        )
        assert sized.per_contract_payoff == pytest.approx(gauge_per_contract)

    def test_skew_on_raises_payoff_and_not_more_contracts(self) -> None:
        """Skew-on sizing lifts the payoff and needs no more contracts.

        Turning ``skew_steepening`` on raises the per-contract payoff versus the
        flat bump, so covering the same crash offset needs no more contracts —
        the workbench stops over-hedging relative to the gauge (M1.7).
        """
        portfolio = _make_spx_portfolio(spot=5000.0, qty=100.0)
        kwargs = {
            "candidate_pct_otm": 30.0,
            "candidate_maturity_years": 1.5,
        }
        flat = size_hedge(portfolio, _make_ips(skew_steepening=0.0), **kwargs)
        skewed = size_hedge(
            portfolio,
            _make_ips(skew_steepening=0.10),
            **kwargs,
        )
        assert skewed.per_contract_payoff > flat.per_contract_payoff
        assert skewed.contracts_needed <= flat.contracts_needed
