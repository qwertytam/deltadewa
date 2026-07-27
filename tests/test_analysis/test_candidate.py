"""Tests for deltadewa.analysis.candidate."""

from __future__ import annotations

import dataclasses
import datetime

import pytest

from deltadewa import constants as const
from deltadewa.analysis.candidate import (
    CandidateMetrics,
    build_put_valuation,
    evaluate_candidate,
)
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsConvexity
from deltadewa.portfolio.core import OptionPortfolio

# Representative crash vol shock (IpsConvexity default) for the tests that do
# not otherwise care about its exact value.
_CRASH_VOL_SHOCK = 0.15

# Crash skew knobs (IpsConvexity defaults). Since M1.7 the candidate path is
# priced on the same per-leg skew as the book surfaces, so evaluate_candidate
# requires both — no silent flat-bump fallback.
_SKEW_STEEPENING = 0.10
_SKEW_REFERENCE_DELTA = 0.10

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


# Tenor for the build_put_valuation tests, applied to the portfolio's *own*
# valuation date. A hardcoded absolute maturity would age into expiry as the
# calendar moves, silently turning these into assertions about a dead option.
_PUT_VALUATION_TENOR = datetime.timedelta(days=66)


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
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=4750.0,
            maturity_years=0.25,
        )
        assert isinstance(result, CandidateMetrics)

    def test_pct_otm_hand_computed(self) -> None:
        """pct_otm = (spot - strike) / spot * 100 (hand-computed)."""
        # spot=5000, strike=4750 → pct_otm = 250/5000*100 = 5.0
        portfolio = _make_spx_portfolio(spot=5000.0)
        result = evaluate_candidate(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=4750.0,
            maturity_years=0.25,
        )
        assert result.pct_otm == pytest.approx(5.0)

    def test_put_delta_is_negative(self) -> None:
        """put_delta is negative for an OTM put."""
        portfolio = _make_spx_portfolio()
        result = evaluate_candidate(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=4750.0,
            maturity_years=0.25,
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
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=4750.0,
            maturity_years=0.25,
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
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=3000.0,
            maturity_years=0.25,
        )
        assert result.per_contract_intrinsic_floor == pytest.approx(0.0)
        assert result.per_contract_payoff > 0.0

    def test_per_contract_carry_positive(self) -> None:
        """per_contract_carry is a positive dollar cost."""
        portfolio = _make_spx_portfolio()
        result = evaluate_candidate(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=4750.0,
            maturity_years=0.25,
        )
        assert result.per_contract_carry > 0.0

    def test_premium_positive(self) -> None:
        """Premium is a positive dollar cost."""
        portfolio = _make_spx_portfolio()
        result = evaluate_candidate(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=4750.0,
            maturity_years=0.25,
        )
        assert result.premium > 0.0

    def test_strike_field_matches_input(self) -> None:
        """Strike field echoes the input strike."""
        portfolio = _make_spx_portfolio()
        result = evaluate_candidate(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-30.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=4600.0,
            maturity_years=0.50,
        )
        assert result.strike == pytest.approx(4600.0)

    def test_vol_override_changes_premium_and_carry(self) -> None:
        """vol= override changes both premium and per_contract_carry."""
        portfolio = _make_spx_portfolio(vol=0.20)
        r_low = evaluate_candidate(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=4750.0,
            maturity_years=0.25,
            vol=0.15,
        )
        r_high = evaluate_candidate(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=4750.0,
            maturity_years=0.25,
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
        }
        base = CrashShock(
            crash_scenario_pct=-25.0,
            crash_vol_shock=0.05,
            skew_steepening=_SKEW_STEEPENING,
            skew_reference_delta=_SKEW_REFERENCE_DELTA,
        )
        r_low = evaluate_candidate(portfolio, shock=base, **kwargs)
        r_high = evaluate_candidate(
            portfolio,
            shock=dataclasses.replace(base, crash_vol_shock=0.25),
            **kwargs,
        )
        assert r_high.per_contract_payoff > r_low.per_contract_payoff

    def test_european_exercise_no_error(self) -> None:
        """European exercise style runs without error."""
        portfolio = _make_spx_portfolio(exercise_style=ExerciseStyle.EUROPEAN)
        result = evaluate_candidate(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=4750.0,
            maturity_years=0.25,
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
            "shock": CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
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
            "shock": CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
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
            "shock": CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
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
            "shock": CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_CRASH_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
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
                shock=CrashShock(
                    crash_scenario_pct=_APX_CRASH_PCT,
                    crash_vol_shock=_APX_VOL_SHOCK,
                    skew_steepening=_SKEW_STEEPENING,
                    skew_reference_delta=_SKEW_REFERENCE_DELTA,
                ),
                strike=strike,
                maturity_years=_APX_MATURITY_YEARS,
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
            shock=CrashShock(
                crash_scenario_pct=_APX_CRASH_PCT,
                crash_vol_shock=_APX_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=_APX_STRIKE_20_OTM,
            maturity_years=_APX_MATURITY_YEARS,
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
            shock=CrashShock(
                crash_scenario_pct=_APX_CRASH_PCT,
                crash_vol_shock=_APX_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=strike,
            maturity_years=_APX_MATURITY_YEARS,
        )
        ips = IpsConvexity(
            crash_scenario_pct=_APX_CRASH_PCT,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_APX_VOL_SHOCK,
            skew_steepening=_SKEW_STEEPENING,
            skew_reference_delta=_SKEW_REFERENCE_DELTA,
        )
        rows = crash_scenario_table(
            portfolio,
            shocks=[_APX_CRASH_PCT],
            ips_convexity=ips,
        )
        row = next(r for r in rows if r.shock_pct == _APX_CRASH_PCT)
        assert candidate.per_contract_payoff == pytest.approx(row.hedge_pnl)


class TestBookCandidateParity:
    """M1.7 — one skew function drives book legs and standalone candidates."""

    def test_book_equals_candidate_at_equal_depth(self) -> None:
        """A candidate equals the held leg's per-contract crash value.

        The headline guard: evaluating a candidate at a strike/tenor the book
        already holds must reproduce that held leg's repriced per-contract crash
        value exactly.  Both flow through the per-leg skew in crash_hedge_value,
        anchored to the leg's own wing, so book and workbench cannot disagree at
        equal depth.
        """
        from deltadewa.analysis.crash_repricing import crash_hedge_value

        strike = _APX_STRIKE_30_OTM
        quantity = 7  # > 1 so the per-contract division is exercised
        portfolio = _make_appendix_portfolio()
        maturity_date = portfolio.valuation_date + datetime.timedelta(
            days=round(_APX_MATURITY_YEARS * const.DAYS_PER_YEAR),
        )
        portfolio.add_position(
            strike_price=strike,
            maturity_date=maturity_date,
            quantity=quantity,
            option_type=OptionType.PUT,
            volatility=_APX_VOL,
        )
        held_leg = portfolio.positions[0]

        held_total = crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APX_CRASH_PCT,
                crash_vol_shock=_APX_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            positions=[held_leg],
        )
        held_per_contract = held_total / quantity

        candidate = evaluate_candidate(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APX_CRASH_PCT,
                crash_vol_shock=_APX_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
            strike=strike,
            maturity_years=_APX_MATURITY_YEARS,
        )
        assert candidate.per_contract_payoff == pytest.approx(held_per_contract)

    def test_candidate_payoff_rises_vs_flat_bump(self) -> None:
        """Skew-on lifts the candidate payoff above the old flat bump.

        The per-leg steepening adds vol on top of ``crash_vol_shock`` for an OTM
        put, so the repriced payoff is strictly larger than the flat-bump value
        the candidate path produced before M1.7 (the ~23% under-statement is
        gone).
        """
        portfolio = _make_appendix_portfolio()
        common = {
            "strike": _APX_STRIKE_30_OTM,
            "maturity_years": _APX_MATURITY_YEARS,
        }
        flat_shock = CrashShock(
            crash_scenario_pct=_APX_CRASH_PCT,
            crash_vol_shock=_APX_VOL_SHOCK,
            skew_steepening=0.0,
            skew_reference_delta=_SKEW_REFERENCE_DELTA,
        )
        flat = evaluate_candidate(portfolio, shock=flat_shock, **common)
        skewed = evaluate_candidate(
            portfolio,
            shock=dataclasses.replace(
                flat_shock,
                skew_steepening=_SKEW_STEEPENING,
            ),
            **common,
        )
        assert skewed.per_contract_payoff > flat.per_contract_payoff

    def test_candidate_payoff_independent_of_book_composition(self) -> None:
        """A candidate's payoff does not change when the book changes.

        The candidate is priced in isolation on its own wing (no book context),
        so adding a deeper held put to the portfolio must not move its payoff —
        the M1.7 composition-independence guarantee, on the candidate path.
        """
        kwargs = {
            "strike": _APX_STRIKE_20_OTM,
            "maturity_years": _APX_MATURITY_YEARS,
            "shock": CrashShock(
                crash_scenario_pct=_APX_CRASH_PCT,
                crash_vol_shock=_APX_VOL_SHOCK,
                skew_steepening=_SKEW_STEEPENING,
                skew_reference_delta=_SKEW_REFERENCE_DELTA,
            ),
        }
        empty_book = _make_appendix_portfolio()
        before = evaluate_candidate(empty_book, **kwargs)

        with_deeper = _make_appendix_portfolio()
        maturity_date = with_deeper.valuation_date + datetime.timedelta(
            days=round(_APX_MATURITY_YEARS * const.DAYS_PER_YEAR),
        )
        with_deeper.add_position(
            strike_price=_APX_STRIKE_40_OTM,
            maturity_date=maturity_date,
            quantity=50,
            option_type=OptionType.PUT,
            volatility=_APX_VOL,
        )
        after = evaluate_candidate(with_deeper, **kwargs)
        assert after.per_contract_payoff == pytest.approx(
            before.per_contract_payoff,
        )


# ---------------------------------------------------------------------------
# build_put_valuation
# ---------------------------------------------------------------------------


class TestBuildPutValuation:
    """Tests for build_put_valuation."""

    def test_returns_option_valuation(self) -> None:
        """build_put_valuation returns an OptionValuation."""
        from deltadewa.valuation import OptionValuation

        portfolio = _make_spx_portfolio()
        maturity_dt = portfolio.valuation_date + _PUT_VALUATION_TENOR
        v = build_put_valuation(5000.0, 4750.0, maturity_dt, 0.20, portfolio)
        assert isinstance(v, OptionValuation)

    def test_delta_is_negative(self) -> None:
        """Put delta returned by the valuation is negative for an OTM put."""
        portfolio = _make_spx_portfolio()
        maturity_dt = portfolio.valuation_date + _PUT_VALUATION_TENOR
        v = build_put_valuation(5000.0, 4750.0, maturity_dt, 0.20, portfolio)
        assert v.delta() < 0.0

    def test_price_is_positive(self) -> None:
        """Put price is a positive value."""
        portfolio = _make_spx_portfolio()
        maturity_dt = portfolio.valuation_date + _PUT_VALUATION_TENOR
        v = build_put_valuation(5000.0, 4750.0, maturity_dt, 0.20, portfolio)
        assert v.price() > 0.0

    def test_vol_override_changes_price(self) -> None:
        """Higher vol produces a higher put price."""
        portfolio = _make_spx_portfolio()
        maturity_dt = portfolio.valuation_date + _PUT_VALUATION_TENOR
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
        maturity_dt = p_eu.valuation_date + _PUT_VALUATION_TENOR
        # Both must price without error; American ≥ European for a put.
        v_eu = build_put_valuation(5000.0, 4750.0, maturity_dt, 0.20, p_eu)
        v_am = build_put_valuation(5000.0, 4750.0, maturity_dt, 0.20, p_am)
        assert v_am.price() >= v_eu.price()
