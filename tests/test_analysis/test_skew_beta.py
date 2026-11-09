"""Tests for analysis.skew_beta — Part X #9, by composition (8c / N9)."""

from __future__ import annotations

import pytest

from deltadewa.analysis.crash_repricing import crash_skew_vol, hedge_value
from deltadewa.analysis.repricing import MarketShock, reprice_portfolio
from deltadewa.analysis.skew_beta import SKEW_BETA_BUMP_VOL, calculate_skew_beta
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio
from tests.clock_helpers import days_from_today

_ANCHOR = 0.10


def _book(
    *legs: tuple[float, int, OptionType],
    underlying_quantity: float = 1_000.0,
) -> OptionPortfolio:
    portfolio = OptionPortfolio(
        spot_price=100.0,
        volatility=0.20,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.set_underlying_quantity(underlying_quantity)
    for strike, quantity, option_type in legs:
        portfolio.add_position(
            strike_price=strike,
            maturity_date=days_from_today(365),
            quantity=quantity,
            option_type=option_type,
        )
    return portfolio


def test_deep_otm_long_put_has_positive_skew_beta() -> None:
    """A long tail put gains when downside skew steepens."""
    beta = calculate_skew_beta(
        _book((70.0, 10, OptionType.PUT)),
        skew_reference_delta=_ANCHOR,
    )

    assert beta is not None
    assert beta.dollars_per_vol_pt > 0
    assert beta.skew_reference_delta == _ANCHOR
    assert beta.excluded_expired == 0


def test_short_put_has_negative_skew_beta() -> None:
    long_beta = calculate_skew_beta(
        _book((70.0, 10, OptionType.PUT)),
        skew_reference_delta=_ANCHOR,
    )
    short_beta = calculate_skew_beta(
        _book((70.0, -10, OptionType.PUT)),
        skew_reference_delta=_ANCHOR,
    )

    assert long_beta is not None
    assert short_beta is not None
    assert short_beta.dollars_per_vol_pt == pytest.approx(
        -long_beta.dollars_per_vol_pt,
    )


def test_calls_and_atm_puts_carry_no_skew_beta() -> None:
    """The bump is zero at the money and never touches calls."""
    beta = calculate_skew_beta(
        _book((100.0, 10, OptionType.PUT), (110.0, 10, OptionType.CALL)),
        skew_reference_delta=_ANCHOR,
    )

    assert beta is not None
    assert beta.dollars_per_vol_pt == pytest.approx(0.0, abs=1e-9)


def test_deeper_strike_has_more_skew_beta_per_contract() -> None:
    """The handbook's qualitative ordering: deeper OTM, higher skew beta."""
    moderate = calculate_skew_beta(
        _book((90.0, 10, OptionType.PUT)),
        skew_reference_delta=_ANCHOR,
    )
    deep = calculate_skew_beta(
        _book((75.0, 10, OptionType.PUT)),
        skew_reference_delta=_ANCHOR,
    )

    assert moderate is not None
    assert deep is not None
    # Per unit of premium: the deep put reprices by a larger fraction.
    moderate_rel = moderate.dollars_per_vol_pt / hedge_value(
        _book((90.0, 10, OptionType.PUT)),
    )
    deep_rel = deep.dollars_per_vol_pt / hedge_value(
        _book((75.0, 10, OptionType.PUT)),
    )
    assert deep_rel > moderate_rel


def test_is_exactly_the_composition_it_claims() -> None:
    """Bumped minus base, through the crash machinery, nothing else."""
    portfolio = _book((70.0, 10, OptionType.PUT), (85.0, 5, OptionType.PUT))
    expected = reprice_portfolio(
        portfolio,
        shock=MarketShock(spot_shock=0.0, vol_shock=0.0),
        vol_mapping=crash_skew_vol(
            skew_steepening=SKEW_BETA_BUMP_VOL,
            skew_reference_delta=_ANCHOR,
        ),
    ) - hedge_value(portfolio)

    beta = calculate_skew_beta(portfolio, skew_reference_delta=_ANCHOR)

    assert beta is not None
    assert beta.dollars_per_vol_pt == pytest.approx(expected)


def test_a_zero_bump_reproduces_todays_value() -> None:
    """The mapping at zero steepening is the base valuation, bit for bit."""
    portfolio = _book((70.0, 10, OptionType.PUT))

    unbumped = reprice_portfolio(
        portfolio,
        shock=MarketShock(spot_shock=0.0, vol_shock=0.0),
        vol_mapping=crash_skew_vol(
            skew_steepening=0.0,
            skew_reference_delta=_ANCHOR,
        ),
    )

    assert unbumped == pytest.approx(hedge_value(portfolio), rel=1e-12)


def test_wing_anchor_moves_the_number() -> None:
    """A deeper anchor spreads the same point over more strikes."""
    portfolio = _book((80.0, 10, OptionType.PUT))

    at_10 = calculate_skew_beta(portfolio, skew_reference_delta=0.10)
    at_05 = calculate_skew_beta(portfolio, skew_reference_delta=0.05)

    assert at_10 is not None
    assert at_05 is not None
    assert at_10.dollars_per_vol_pt != pytest.approx(at_05.dollars_per_vol_pt)


def test_pct_of_book_normalizes_by_the_protected_book() -> None:
    portfolio = _book((70.0, 10, OptionType.PUT), underlying_quantity=2_000.0)

    beta = calculate_skew_beta(portfolio, skew_reference_delta=_ANCHOR)

    assert beta is not None
    assert beta.pct_of_protected_book == pytest.approx(
        beta.dollars_per_vol_pt / (2_000.0 * 100.0) * 100,
    )


def test_no_underlying_has_no_pct() -> None:
    beta = calculate_skew_beta(
        _book((70.0, 10, OptionType.PUT), underlying_quantity=0.0),
        skew_reference_delta=_ANCHOR,
    )

    assert beta is not None
    assert beta.pct_of_protected_book is None


def test_empty_book_is_none_not_zero() -> None:
    """Nothing to measure is not a measured zero."""
    assert calculate_skew_beta(_book(), skew_reference_delta=_ANCHOR) is None
