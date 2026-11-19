"""Tests for deltadewa.analysis.implied_vol."""

from __future__ import annotations

import math
from datetime import date

import pytest

from deltadewa.analysis.implied_vol import (
    cmt_to_continuous,
    solve_implied_vol,
)
from deltadewa.constants import OptionType
from tests.chain_builders import (
    DECEMBER,
    DIVIDEND,
    RATE,
    SESSION,
    SPOT,
    engine_price,
)


def _solve(price: float, **overrides: object) -> float | None:
    arguments: dict[str, object] = {
        "price": price,
        "strike": 4000.0,
        "expiry": DECEMBER,
        "option_type": OptionType.PUT,
        "spot": SPOT,
        "risk_free_rate": RATE,
        "dividend_yield": DIVIDEND,
        "valuation_date": SESSION,
    }
    arguments.update(overrides)
    return solve_implied_vol(**arguments)  # type: ignore[arg-type]


class TestSolveImpliedVol:
    """The solver inverts the engine."""

    @pytest.mark.parametrize("vol", [0.12, 0.2, 0.27, 0.45, 0.9])
    @pytest.mark.parametrize("option_type", list(OptionType))
    def test_round_trip_to_1e_8(self, vol: float, option_type) -> None:
        """Price at a vol, solve it back, recover the vol."""
        price = engine_price(DECEMBER, option_type, 4800.0, vol=vol)

        solved = _solve(price, strike=4800.0, option_type=option_type)

        assert solved == pytest.approx(vol, abs=1e-8)

    def test_solved_iv_reprices_the_mid_by_construction(self) -> None:
        """The solved IV, priced at the same r and q, returns the mid."""
        mid = 133.7
        solved = _solve(mid, strike=4600.0)

        assert solved is not None
        repriced = engine_price(
            DECEMBER,
            OptionType.PUT,
            4600.0,
            vol=solved,
        )
        assert repriced == pytest.approx(mid, abs=1e-6)

    def test_iv_and_dividend_are_a_pair(self) -> None:
        """A higher q lowers the put's value, so it solves to a higher IV.

        Reading the same mid at a different q gives a different IV (9b.0):
        that is why the IV must be solved at the engine's own (r, q).
        """
        mid = engine_price(DECEMBER, OptionType.PUT, 4600.0, vol=0.25)
        base = _solve(mid, strike=4600.0)
        higher_q = _solve(mid, strike=4600.0, dividend_yield=DIVIDEND + 0.01)

        assert base is not None
        assert higher_q is not None
        assert higher_q < base

    def test_iv_and_rate_are_a_pair(self) -> None:
        """A higher r lowers a put's value, so the same mid needs more vol."""
        mid = engine_price(DECEMBER, OptionType.PUT, 4600.0, vol=0.25)
        base = _solve(mid, strike=4600.0)
        higher_r = _solve(mid, strike=4600.0, risk_free_rate=RATE + 0.01)

        assert base is not None
        assert higher_r is not None
        assert higher_r > base

    @pytest.mark.parametrize("price", [0.0, -1.0])
    def test_non_positive_price_has_no_iv(self, price: float) -> None:
        """A mid of zero is not a price."""
        assert _solve(price) is None

    def test_price_below_the_floor_vol_has_no_iv(self) -> None:
        """A deep ITM put cheaper than its discounted intrinsic: no IV."""
        assert _solve(1.0, strike=7000.0) is None

    def test_price_above_the_ceiling_vol_has_no_iv(self) -> None:
        """A put dearer than its strike (so beyond any volatility)."""
        assert _solve(10000.0, strike=4000.0) is None

    def test_expired_contract_has_no_iv(self) -> None:
        """Nothing to solve on or after expiry."""
        assert _solve(5.0, expiry=SESSION) is None
        assert _solve(5.0, expiry=date(2026, 11, 1)) is None


class TestCmtToContinuous:
    """FRED's bond-equivalent yield becomes a continuous rate."""

    def test_semiannual_to_continuous(self) -> None:
        """4% semi-annual is 2 * ln(1.02) continuous."""
        assert cmt_to_continuous(4.0) == pytest.approx(2 * math.log(1.02))

    def test_continuous_is_a_little_below_the_quoted_yield(self) -> None:
        """Compounding more often lowers the equivalent rate."""
        assert cmt_to_continuous(4.6) < 0.046
        assert cmt_to_continuous(4.6) == pytest.approx(0.046, abs=1e-3)

    def test_zero_yield_is_zero(self) -> None:
        """No yield, no rate."""
        assert cmt_to_continuous(0.0) == pytest.approx(0.0)
