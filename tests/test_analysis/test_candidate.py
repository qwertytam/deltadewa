"""Tests for deltadewa.analysis.candidate."""

from __future__ import annotations

import pytest

from deltadewa.analysis.candidate import (
    CandidateMetrics,
    _intrinsic_at_crash,
    evaluate_candidate,
)
from deltadewa.constants import ExerciseStyle
from deltadewa.portfolio.core import OptionPortfolio

# ruff: noqa: S101


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
