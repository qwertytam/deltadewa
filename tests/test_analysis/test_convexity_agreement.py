"""One convexity: sizing, the candidate grid and the strip must agree (#410).

Before #410 the sizing workbench and the candidate grid computed their
"achieved convexity" as ``contracts * gross crash payoff / beta-adjusted
notional``, while the compliance strip and ``/monitor`` read
``(V_crash - V_today) / book notional`` via ``crash_convexity_pct``. Both
were graded against the same IPS band, and nothing asserted they matched
(agreement-auditor, 2026-11). These tests are the referee: the figure a
candidate-side surface reports for N contracts must equal what the strip
reports for a real book holding exactly those N contracts.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from deltadewa import constants as const
from deltadewa.analysis.candidate import evaluate_candidate
from deltadewa.analysis.crash_repricing import CrashShock, crash_convexity_pct
from deltadewa.analysis.sizing import HedgeSizingResult, size_hedge
from deltadewa.analysis.strike_ladder import build_candidate_grid
from deltadewa.app.pages.design.planning.sizing import _convexity_verdict
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

_SPOT = 5000.0
_QTY = 100.0
_MATURITY_YEARS = 1.0


def _portfolio(qty: float = _QTY) -> OptionPortfolio:
    """A hedge-free SPX book: underlying only, European exercise."""
    return OptionPortfolio(
        spot_price=_SPOT,
        underlying_quantity=qty,
        volatility=0.20,
        risk_free_rate=0.04,
        dividend_yield=0.015,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )


def _book_holding(
    *,
    strike: float,
    maturity_years: float,
    contracts: int,
) -> OptionPortfolio:
    """The same book, but actually holding *contracts* long puts.

    Maturity is built exactly as ``evaluate_candidate`` builds it, so the
    held leg and the hypothetical candidate are the same instrument.
    """
    book = _portfolio()
    book.add_position(
        strike_price=strike,
        maturity_date=book.valuation_date
        + timedelta(days=round(maturity_years * const.DAYS_PER_YEAR)),
        quantity=contracts,
        option_type=OptionType.PUT,
    )
    return book


def _ips(
    *,
    portfolio_beta: float = 1.0,
    skew_steepening: float = 0.10,
    target_min_pct: float = 5.0,
    target_max_pct: float = 30.0,
    max_tolerance_pct: float = 20.0,
) -> IpsConfig:
    return IpsConfig(
        program=IpsProgram(name="Test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=target_min_pct,
            target_max_pct=target_max_pct,
            skew_steepening=skew_steepening,
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=max_tolerance_pct),
        triggers=IpsTriggers(
            delta_ratio_deviation_warn_pct=5.0,
            delta_ratio_deviation_action_pct=10.0,
            theta_cost_acceptable_pct=3.0,
            roll_at_months_remaining=1.0,
            rally_monitor_pct=5.0,
            rally_review_pct=10.0,
            rally_action_pct=15.0,
            rally_urgent_pct=20.0,
        ),
        monetization=IpsMonetization(
            schedule=(IpsMonetizationStep(gain_pct=50.0, sell_pct=25.0),),
        ),
        sizing=IpsSizing(portfolio_beta=portfolio_beta),
    )


class TestCandidateAgreesWithStrip:
    """``evaluate_candidate`` is the strip's gauge, one contract at a time."""

    @pytest.mark.parametrize("pct_otm", [10.0, 20.0, 30.0, 40.0])
    @pytest.mark.parametrize("contracts", [1, 7])
    def test_n_contracts_equal_the_strip_on_a_held_book(
        self,
        pct_otm: float,
        contracts: int,
    ) -> None:
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        strike = _SPOT * (1.0 - pct_otm / 100.0)

        metrics = evaluate_candidate(
            _portfolio(),
            strike=strike,
            maturity_years=_MATURITY_YEARS,
            shock=shock,
        )
        held = _book_holding(
            strike=strike,
            maturity_years=_MATURITY_YEARS,
            contracts=contracts,
        )

        assert contracts * metrics.per_contract_convexity_pct == pytest.approx(
            crash_convexity_pct(held, shock=shock),
            rel=1e-9,
        )

    def test_figure_is_gain_not_gross_payoff(self) -> None:
        """Premium is netted: the old gross formula would read higher."""
        ips = _ips()
        shock = CrashShock.from_ips(ips.convexity)
        portfolio = _portfolio()
        metrics = evaluate_candidate(
            portfolio,
            strike=_SPOT * 0.8,
            maturity_years=_MATURITY_YEARS,
            shock=shock,
        )
        gross_pct = metrics.per_contract_payoff / (_SPOT * _QTY) * 100.0

        assert metrics.premium > 0.0
        assert metrics.per_contract_convexity_pct == pytest.approx(
            gross_pct - metrics.premium / (_SPOT * _QTY) * 100.0,
            rel=1e-9,
        )
        assert metrics.per_contract_convexity_pct < gross_pct


class TestSizingAgreesWithStrip:
    """``size_hedge``'s achieved convexity is the strip's figure."""

    @pytest.mark.parametrize("beta", [0.8, 1.0, 1.5])
    def test_sized_contracts_read_the_same_on_the_strip(
        self,
        beta: float,
    ) -> None:
        ips = _ips(portfolio_beta=beta)
        result = size_hedge(
            _portfolio(),
            ips,
            candidate_pct_otm=20.0,
            candidate_maturity_years=_MATURITY_YEARS,
        )
        held = _book_holding(
            strike=_SPOT * 0.8,
            maturity_years=_MATURITY_YEARS,
            contracts=result.contracts_needed,
        )

        assert result.contracts_needed > 0
        assert result.achieved_convexity_pct == pytest.approx(
            crash_convexity_pct(
                held,
                shock=CrashShock.from_ips(ips.convexity),
            ),
            rel=1e-9,
        )

    def test_beta_buys_more_contracts_but_not_a_different_yardstick(
        self,
    ) -> None:
        """Beta scales the contracts bought, not the reading itself."""
        # A $50M book, so one contract does not already cover either offset
        # and the rounding cannot hide the beta scaling.
        low = size_hedge(
            _portfolio(10_000.0),
            _ips(portfolio_beta=1.0),
            candidate_pct_otm=20.0,
            candidate_maturity_years=_MATURITY_YEARS,
        )
        high = size_hedge(
            _portfolio(10_000.0),
            _ips(portfolio_beta=1.5),
            candidate_pct_otm=20.0,
            candidate_maturity_years=_MATURITY_YEARS,
        )

        assert high.contracts_needed > low.contracts_needed
        # Per contract, the contribution is identical -- only the count moved.
        assert high.achieved_convexity_pct / high.contracts_needed == (
            pytest.approx(
                low.achieved_convexity_pct / low.contracts_needed,
                rel=1e-9,
            )
        )


class TestGridAgreesWithSizingAndStrip:
    """Every grid cell reads exactly what the same candidate does in sizing."""

    def test_cell_matches_size_hedge_for_the_same_candidate(self) -> None:
        ips = _ips()
        result = build_candidate_grid(
            _portfolio(),
            ips,
            target_deltas=[0.10, 0.15],
            maturities_years=[_MATURITY_YEARS],
        )
        assert result.cells

        for cell in result.cells:
            sized = size_hedge(
                _portfolio(),
                ips,
                candidate_pct_otm=cell.metrics.pct_otm,
                candidate_maturity_years=cell.maturity_years,
            )
            assert cell.contracts_needed == sized.contracts_needed
            assert cell.achieved_convexity_pct == pytest.approx(
                sized.achieved_convexity_pct,
                rel=1e-6,
            )

    def test_cell_matches_the_strip_on_a_held_book(self) -> None:
        ips = _ips()
        result = build_candidate_grid(
            _portfolio(),
            ips,
            target_deltas=[0.10],
            maturities_years=[_MATURITY_YEARS],
        )
        cell = result.cells[0]
        held = _book_holding(
            strike=cell.metrics.strike,
            maturity_years=cell.maturity_years,
            contracts=cell.contracts_needed,
        )

        assert cell.achieved_convexity_pct == pytest.approx(
            crash_convexity_pct(
                held,
                shock=CrashShock.from_ips(ips.convexity),
            ),
            rel=1e-6,
        )


class TestConvexityVerdictNamesTheSide:
    """The sizing panel says *which side* of the band, not just "over"."""

    def _result(
        self,
        *,
        target_min_pct: float,
        target_max_pct: float,
    ) -> tuple[HedgeSizingResult, IpsConvexity]:
        ips = _ips(
            target_min_pct=target_min_pct,
            target_max_pct=target_max_pct,
        )
        result = size_hedge(
            _portfolio(),
            ips,
            candidate_pct_otm=20.0,
            candidate_maturity_years=_MATURITY_YEARS,
        )
        return result, ips.convexity

    def test_below_band_is_below_not_over(self) -> None:
        # Sizing recovers ~|crash| - tolerance (~5%): a 15-25 band is above it.
        result, conv = self._result(target_min_pct=15.0, target_max_pct=25.0)
        assert _convexity_verdict(result, conv) == "below"

    def test_inside_band_is_within(self) -> None:
        result, conv = self._result(target_min_pct=0.0, target_max_pct=100.0)
        assert _convexity_verdict(result, conv) == "within"

    def test_above_band_is_above(self) -> None:
        result, conv = self._result(target_min_pct=0.1, target_max_pct=0.2)
        assert _convexity_verdict(result, conv) == "above"
