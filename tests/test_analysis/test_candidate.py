"""Tests for deltadewa.analysis.candidate."""

from __future__ import annotations

import datetime

import pytest

from deltadewa.analysis.candidate import (
    CandidateMetrics,
    _intrinsic_at_crash,
    build_put_valuation,
    evaluate_candidate,
)
from deltadewa.constants import ExerciseStyle
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


# ---------------------------------------------------------------------------
# _intrinsic_at_crash (moved from test_sizing.py)
# ---------------------------------------------------------------------------


class TestIntrinsicAtCrash:
    """Tests for the _intrinsic_at_crash helper."""

    def test_in_the_money_at_crash(self) -> None:
        """Put is ITM at crash → positive intrinsic."""
        assert _intrinsic_at_crash(4750.0, 3750.0) == pytest.approx(1000.0)

    def test_out_of_money_at_crash(self) -> None:
        """Put is OTM at crash → zero (floors at 0)."""
        assert _intrinsic_at_crash(3000.0, 3750.0) == pytest.approx(0.0)

    def test_at_the_money_at_crash(self) -> None:
        """Put is ATM at crash → zero intrinsic."""
        assert _intrinsic_at_crash(3750.0, 3750.0) == pytest.approx(0.0)


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
        )
        assert result.put_delta < 0.0

    def test_per_contract_payoff_hand_computed(self) -> None:
        """per_contract_payoff matches max(0, strike - crash_spot) * 100.

        spot=5000, strike=4750, crash=-25% → crash_spot=3750
        intrinsic = 4750 - 3750 = 1000; per contract = 1000 * 100 = 100_000
        """
        portfolio = _make_spx_portfolio(spot=5000.0)
        result = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
        )
        assert result.per_contract_payoff == pytest.approx(100_000.0)

    def test_per_contract_payoff_zero_when_otm_at_crash(self) -> None:
        """per_contract_payoff is zero when the put is OTM at the crash spot."""
        # spot=5000, strike=3000, crash=-25% → crash_spot=3750 > strike → OTM
        portfolio = _make_spx_portfolio(spot=5000.0)
        result = evaluate_candidate(
            portfolio,
            strike=3000.0,
            maturity_years=0.25,
            crash_pct=-25.0,
        )
        assert result.per_contract_payoff == pytest.approx(0.0)

    def test_per_contract_carry_positive(self) -> None:
        """per_contract_carry is a positive dollar cost."""
        portfolio = _make_spx_portfolio()
        result = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
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
            vol=0.15,
        )
        r_high = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
            vol=0.30,
        )
        assert r_high.premium > r_low.premium
        assert r_high.per_contract_carry > r_low.per_contract_carry

    def test_european_exercise_no_error(self) -> None:
        """European exercise style runs without error."""
        portfolio = _make_spx_portfolio(exercise_style=ExerciseStyle.EUROPEAN)
        result = evaluate_candidate(
            portfolio,
            strike=4750.0,
            maturity_years=0.25,
            crash_pct=-25.0,
        )
        assert result.per_contract_carry > 0.0


class TestCandidateContractSizeScaling:
    """evaluate_candidate scales dollar outputs with portfolio.contract_size."""

    def test_premium_scales_with_contract_size(self) -> None:
        """Premium halves when contract_size halves."""
        p100 = _make_spx_portfolio(contract_size=100)
        p50 = _make_spx_portfolio(contract_size=50)
        kwargs = {"strike": 4750.0, "maturity_years": 0.25, "crash_pct": -25.0}
        r100 = evaluate_candidate(p100, **kwargs)
        r50 = evaluate_candidate(p50, **kwargs)
        assert r50.premium == pytest.approx(r100.premium / 2)

    def test_payoff_scales_with_contract_size(self) -> None:
        """per_contract_payoff halves when contract_size halves."""
        p100 = _make_spx_portfolio(contract_size=100)
        p50 = _make_spx_portfolio(contract_size=50)
        kwargs = {"strike": 4750.0, "maturity_years": 0.25, "crash_pct": -25.0}
        r100 = evaluate_candidate(p100, **kwargs)
        r50 = evaluate_candidate(p50, **kwargs)
        assert r50.per_contract_payoff == pytest.approx(
            r100.per_contract_payoff / 2,
        )

    def test_carry_scales_with_contract_size(self) -> None:
        """per_contract_carry halves when contract_size halves."""
        p100 = _make_spx_portfolio(contract_size=100)
        p50 = _make_spx_portfolio(contract_size=50)
        kwargs = {"strike": 4750.0, "maturity_years": 0.25, "crash_pct": -25.0}
        r100 = evaluate_candidate(p100, **kwargs)
        r50 = evaluate_candidate(p50, **kwargs)
        assert r50.per_contract_carry == pytest.approx(
            r100.per_contract_carry / 2,
        )

    def test_pct_otm_unaffected_by_contract_size(self) -> None:
        """pct_otm is a pure spot/strike ratio — unchanged by contract_size."""
        p100 = _make_spx_portfolio(contract_size=100)
        p50 = _make_spx_portfolio(contract_size=50)
        kwargs = {"strike": 4750.0, "maturity_years": 0.25, "crash_pct": -25.0}
        assert evaluate_candidate(p100, **kwargs).pct_otm == pytest.approx(
            evaluate_candidate(p50, **kwargs).pct_otm,
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
