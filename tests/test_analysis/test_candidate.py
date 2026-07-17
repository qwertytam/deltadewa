"""Tests for deltadewa.analysis.candidate."""

from __future__ import annotations

import datetime

import pytest

from deltadewa import constants as const
from deltadewa.analysis.candidate import (
    CandidateMetrics,
    build_put_valuation,
    evaluate_candidate,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsConvexity
from deltadewa.portfolio.core import OptionPortfolio

# Representative crash vol shock (IpsConvexity default) for the tests that do
# not otherwise care about its exact value.
_CRASH_VOL_SHOCK = 0.15

# §4 worked-example crash state (docs/repricing-methodology.md): spot 6600,
# 18-month European puts, 20% flat today-vol, +15% crash vol shock, -25% crash.
_APX_SPOT = 6600.0
_APX_VOL = 0.20
_APX_VOL_SHOCK = 0.15
_APX_CRASH_PCT = -25.0
_APX_MATURITY_YEARS = 1.5
# 20 / 30 / 40 %-OTM strikes from the worked example.
_APX_STRIKE_20_OTM = 5280.0
_APX_STRIKE_30_OTM = 4620.0
_APX_STRIKE_40_OTM = 3960.0


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
    contract_size: int = 100,
) -> OptionPortfolio:
    return OptionPortfolio(
        spot_price=spot,
        underlying_quantity=qty,
        volatility=vol,
        risk_free_rate=rate,
        dividend_yield=div,
        default_exercise_style=exercise_style,
        contract_size=contract_size,
    )


def _make_appendix_portfolio() -> OptionPortfolio:
    """A §4-style SPX book: spot 6600, 18-month European puts, 20% vol."""
    valuation_date = datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
    return OptionPortfolio(
        spot_price=_APX_SPOT,
        underlying_quantity=_APX_SPOT,  # arbitrary; candidate is hedge-only
        volatility=_APX_VOL,
        risk_free_rate=0.045,
        dividend_yield=0.015,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        valuation_date=valuation_date,
    )


# ---------------------------------------------------------------------------
# evaluate_candidate
# ---------------------------------------------------------------------------


class TestEvaluateCandidate:
    """Tests for evaluate_candidate."""

    def test_returns_candidate_metrics(self) -> None:
        """evaluate_candidate returns a CandidateMetrics instance."""
        portfolio = _make_spx_portfolio()
        result = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
        )
        assert isinstance(result, CandidateMetrics)

    def test_pct_otm_hand_computed(self) -> None:
        """pct_otm = (spot - strike) / spot * 100 (hand-computed)."""
        # spot=5000, strike=4750 → pct_otm = 250/5000*100 = 5.0
        portfolio = _make_spx_portfolio(spot=5000.0)
        result = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
        )
        assert result.pct_otm == pytest.approx(5.0)

    def test_put_delta_is_negative(self) -> None:
        """put_delta is negative for an OTM put."""
        portfolio = _make_spx_portfolio()
        result = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
        )
        assert result.put_delta < 0.0

    def test_intrinsic_floor_hand_computed(self) -> None:
        """per_contract_intrinsic_floor = max(0, strike - crash_spot) * 100.

        spot=5000, strike=4750, crash=-25% → crash_spot=3750;
        intrinsic = 4750 - 3750 = 1000; per contract = 1000 * 100 = 100_000.
        Only the (undiscounted) floor is pinned here: a deep-ITM short-dated
        European put can reprice just *below* it because of discounting, so
        the floor-vs-repriced ordering is exercised separately, where time
        value dominates (see :class:`TestCrashRepricingBasis`).
        """
        portfolio = _make_spx_portfolio(spot=5000.0)
        result = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
        )
        assert result.per_contract_intrinsic_floor == pytest.approx(100_000.0)
        assert result.per_contract_payoff > 0.0

    def test_deep_otm_at_crash_reprices_above_zero_floor(self) -> None:
        """A strike still OTM at the crash spot reprices > 0 (C4 fix).

        spot=5000, strike=3000, crash=-25% → crash_spot=3750 > strike, so the
        put is OTM at the crash spot and its intrinsic floor is 0.  The
        repriced value keeps its (positive) remaining time value — the whole
        point of C4: the intrinsic basis wrongly scored this strike at zero.
        """
        portfolio = _make_spx_portfolio(spot=5000.0)
        result = evaluate_candidate(
            portfolio,
            strike=3000.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
        )
        assert result.per_contract_intrinsic_floor == pytest.approx(0.0)
        assert result.per_contract_payoff > 0.0

    def test_per_contract_carry_positive(self) -> None:
        """per_contract_carry is a positive dollar cost."""
        portfolio = _make_spx_portfolio()
        result = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
        )
        assert result.per_contract_carry > 0.0

    def test_premium_positive(self) -> None:
        """Premium is a positive dollar cost."""
        portfolio = _make_spx_portfolio()
        result = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
        )
        assert result.premium > 0.0

    def test_strike_field_matches_input(self) -> None:
        """Strike field echoes the input strike."""
        portfolio = _make_spx_portfolio()
        result = evaluate_candidate(
            portfolio,
            strike=4600.0,
            maturity_years=0.50,
            crash_pct=-30.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
        )
        assert result.strike == pytest.approx(4600.0)

    def test_vol_override_changes_premium_and_carry(self) -> None:
        """vol= override changes both premium and per_contract_carry."""
        portfolio = _make_spx_portfolio(vol=0.20)
        r_low = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
            vol=0.15,
        )
        r_high = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
            vol=0.30,
        )
        assert r_high.premium > r_low.premium
        assert r_high.per_contract_carry > r_low.per_contract_carry

    def test_higher_crash_vol_shock_raises_payoff(self) -> None:
        """A larger crash vol shock lifts the repriced payoff (more IV).

        Guards the crash_vol_shock plumbing: the payoff is the option
        repriced at ``candidate_vol + crash_vol_shock``, so a bigger shock
        must produce a strictly larger repriced value.
        """
        portfolio = _make_spx_portfolio(spot=5000.0)
        kwargs = {
            "strike": 3500.0,  # OTM at the -25% crash → time value only
            "maturity_years": 0.5,
            "crash_pct": -25.0,
        }
        r_low = evaluate_candidate(portfolio, **kwargs, crash_vol_shock=0.05)
        r_high = evaluate_candidate(portfolio, **kwargs, crash_vol_shock=0.25)
        assert r_high.per_contract_payoff > r_low.per_contract_payoff

    def test_european_exercise_no_error(self) -> None:
        """European exercise style runs without error."""
        portfolio = _make_spx_portfolio(exercise_style=ExerciseStyle.EUROPEAN)
        result = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            crash_vol_shock=_CRASH_VOL_SHOCK,
        )
        assert result.per_contract_carry > 0.0


class TestCandidateContractSizeScaling:
    """evaluate_candidate scales dollar outputs with portfolio.contract_size."""

    def test_premium_scales_with_contract_size(self) -> None:
        """Premium halves when contract_size halves."""
        p100 = _make_spx_portfolio(contract_size=100)
        p50 = _make_spx_portfolio(contract_size=50)
        kwargs = {
            "strike": 4750.0,
            "maturity_years": 0.25,
            "crash_pct": -25.0,
            "crash_vol_shock": _CRASH_VOL_SHOCK,
        }
        r100 = evaluate_candidate(p100, **kwargs)
        r50 = evaluate_candidate(p50, **kwargs)
        assert r50.premium == pytest.approx(r100.premium / 2)

    def test_payoff_scales_with_contract_size(self) -> None:
        """per_contract_payoff halves when contract_size halves."""
        p100 = _make_spx_portfolio(contract_size=100)
        p50 = _make_spx_portfolio(contract_size=50)
        kwargs = {
            "strike": 4750.0,
            "maturity_years": 0.25,
            "crash_pct": -25.0,
            "crash_vol_shock": _CRASH_VOL_SHOCK,
        }
        r100 = evaluate_candidate(p100, **kwargs)
        r50 = evaluate_candidate(p50, **kwargs)
        assert r50.per_contract_payoff == pytest.approx(
            r100.per_contract_payoff / 2,
        )

    def test_carry_scales_with_contract_size(self) -> None:
        """per_contract_carry halves when contract_size halves."""
        p100 = _make_spx_portfolio(contract_size=100)
        p50 = _make_spx_portfolio(contract_size=50)
        kwargs = {
            "strike": 4750.0,
            "maturity_years": 0.25,
            "crash_pct": -25.0,
            "crash_vol_shock": _CRASH_VOL_SHOCK,
        }
        r100 = evaluate_candidate(p100, **kwargs)
        r50 = evaluate_candidate(p50, **kwargs)
        assert r50.per_contract_carry == pytest.approx(
            r100.per_contract_carry / 2,
        )

    def test_pct_otm_unaffected_by_contract_size(self) -> None:
        """pct_otm is a pure spot/strike ratio — unchanged by contract_size."""
        p100 = _make_spx_portfolio(contract_size=100)
        p50 = _make_spx_portfolio(contract_size=50)
        kwargs = {
            "strike": 4750.0,
            "maturity_years": 0.25,
            "crash_pct": -25.0,
            "crash_vol_shock": _CRASH_VOL_SHOCK,
        }
        assert evaluate_candidate(p100, **kwargs).pct_otm == pytest.approx(
            evaluate_candidate(p50, **kwargs).pct_otm,
        )


class TestCrashRepricingBasis:
    """C4 — candidates are repriced via the shared crash_hedge_value helper."""

    def test_appendix_deep_otm_legs_reprice_above_zero(self) -> None:
        """§4's 30% and 40% OTM legs reprice > 0 at -25% (C4 regression).

        On the intrinsic basis both legs scored exactly zero (they are OTM at
        the crash spot); the repriced basis gives each a positive value while
        the intrinsic floor stays at zero.
        """
        portfolio = _make_appendix_portfolio()
        for strike in (_APX_STRIKE_30_OTM, _APX_STRIKE_40_OTM):
            result = evaluate_candidate(
                portfolio,
                strike=strike,
                maturity_years=_APX_MATURITY_YEARS,
                crash_pct=_APX_CRASH_PCT,
                crash_vol_shock=_APX_VOL_SHOCK,
            )
            assert result.per_contract_payoff > 0.0
            assert result.per_contract_intrinsic_floor == pytest.approx(0.0)
            assert (
                result.per_contract_intrinsic_floor < result.per_contract_payoff
            )

    def test_floor_below_repriced_for_in_the_money_leg(self) -> None:
        """Intrinsic floor is strictly below the repriced value (time value).

        The 20% OTM leg is ITM at the -25% crash: crash_spot = 6600*0.75 =
        4950, so intrinsic = (5280 - 4950) * 100 = 33_000; the repriced value
        adds the remaining time value.
        """
        portfolio = _make_appendix_portfolio()
        result = evaluate_candidate(
            portfolio,
            strike=_APX_STRIKE_20_OTM,
            maturity_years=_APX_MATURITY_YEARS,
            crash_pct=_APX_CRASH_PCT,
            crash_vol_shock=_APX_VOL_SHOCK,
        )
        assert result.per_contract_intrinsic_floor == pytest.approx(33_000.0)
        assert result.per_contract_intrinsic_floor < result.per_contract_payoff

    def test_payoff_consistent_with_crash_payoff_headline(self) -> None:
        """Candidate payoff == the crash_payoff headline for the same strike.

        Both surfaces reprice one contract through the shared
        crash_hedge_value helper, so a single-contract long-put book's
        repriced hedge value at the policy depth (the crash_payoff row's
        ``hedge_pnl``) must equal evaluate_candidate's per_contract_payoff.
        """
        from deltadewa.analysis.crash_payoff import crash_scenario_table

        strike = _APX_STRIKE_30_OTM
        portfolio = _make_appendix_portfolio()
        maturity_date = portfolio.valuation_date + datetime.timedelta(
            days=round(_APX_MATURITY_YEARS * const.DAYS_PER_YEAR),
        )
        portfolio.add_position(
            strike_price=strike,
            maturity_date=maturity_date,
            quantity=1,
            option_type=OptionType.PUT,
            volatility=_APX_VOL,
        )

        candidate = evaluate_candidate(
            portfolio,
            strike=strike,
            maturity_years=_APX_MATURITY_YEARS,
            crash_pct=_APX_CRASH_PCT,
            crash_vol_shock=_APX_VOL_SHOCK,
        )
        ips = IpsConvexity(
            crash_scenario_pct=_APX_CRASH_PCT,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_APX_VOL_SHOCK,
        )
        rows = crash_scenario_table(
            portfolio,
            shocks=[_APX_CRASH_PCT],
            ips_convexity=ips,
        )
        row = next(r for r in rows if r.shock_pct == _APX_CRASH_PCT)
        assert candidate.per_contract_payoff == pytest.approx(row.hedge_pnl)


# ---------------------------------------------------------------------------
# build_put_valuation
# ---------------------------------------------------------------------------


class TestBuildPutValuation:
    """Tests for build_put_valuation."""

    def test_returns_option_valuation(self) -> None:
        """build_put_valuation returns an OptionValuation."""
        from deltadewa.valuation import OptionValuation

        portfolio = _make_spx_portfolio()
        maturity_dt = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
        v = build_put_valuation(5000.0, 4750.0, maturity_dt, 0.20, portfolio)
        assert isinstance(v, OptionValuation)

    def test_delta_is_negative(self) -> None:
        """Put delta returned by the valuation is negative for an OTM put."""
        portfolio = _make_spx_portfolio()
        maturity_dt = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
        v = build_put_valuation(5000.0, 4750.0, maturity_dt, 0.20, portfolio)
        assert v.delta() < 0.0

    def test_price_is_positive(self) -> None:
        """Put price is a positive value."""
        portfolio = _make_spx_portfolio()
        maturity_dt = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
        v = build_put_valuation(5000.0, 4750.0, maturity_dt, 0.20, portfolio)
        assert v.price() > 0.0

    def test_vol_override_changes_price(self) -> None:
        """Higher vol produces a higher put price."""
        portfolio = _make_spx_portfolio()
        maturity_dt = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
        v_low = build_put_valuation(
            5000.0, 4750.0, maturity_dt, 0.15, portfolio
        )
        v_high = build_put_valuation(
            5000.0, 4750.0, maturity_dt, 0.30, portfolio
        )
        assert v_high.price() > v_low.price()

    def test_exercise_style_from_portfolio(self) -> None:
        """build_put_valuation wires exercise_style from portfolio."""
        from deltadewa.constants import ExerciseStyle

        p_eu = _make_spx_portfolio(exercise_style=ExerciseStyle.EUROPEAN)
        p_am = _make_spx_portfolio(exercise_style=ExerciseStyle.AMERICAN)
        maturity_dt = datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC)
        # Both must price without error; American ≥ European for a put.
        v_eu = build_put_valuation(5000.0, 4750.0, maturity_dt, 0.20, p_eu)
        v_am = build_put_valuation(5000.0, 4750.0, maturity_dt, 0.20, p_am)
        assert v_am.price() >= v_eu.price()
