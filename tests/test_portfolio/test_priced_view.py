"""The priced view of a book (9b): the typed book, priced on resolved inputs.

``apply_resolved_inputs`` prices a book on the resolver's values **without
stamping** (a fetched number was confirmed by nobody), and ``priced_view``
does it on a copy, so the book that is saved is never the one holding a
fetched value.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from deltadewa.analysis.pricing_resolution import (
    EnteredInputs,
    InputOrigin,
    ResolvedInputs,
    ResolvedValue,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.liquidity import LiquidityObservation
from deltadewa.portfolio.stamps import MarketParameterStamps
from tests.clock_helpers import days_from_today

_CONFIRMED = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)
_NOW = datetime(2026, 11, 17, 2, 0, tzinfo=UTC)
_QUOTE = LiquidityObservation(
    bid=2.40,
    ask=2.60,
    open_interest=3_400,
    observed_at=_CONFIRMED,
)


def _typed_book() -> OptionPortfolio:
    stamps = MarketParameterStamps(
        spot_as_of=_CONFIRMED,
        risk_free_rate_as_of=_CONFIRMED,
        dividend_yield_as_of=_CONFIRMED,
    )
    book = OptionPortfolio(
        underlying_quantity=1_000.0,
        spot_price=4800.0,
        volatility=0.20,
        risk_free_rate=0.03,
        dividend_yield=0.013,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        stamps=stamps,
    )
    for strike in (3500.0, 4000.0):
        book.add_position(
            strike_price=strike,
            maturity_date=days_from_today(365),
            quantity=10,
            option_type=OptionType.PUT,
            volatility=0.19,
            volatility_as_of=_CONFIRMED,
        )
    book.positions[0].liquidity = _QUOTE
    return book


def _resolved(book: OptionPortfolio) -> ResolvedInputs:
    """Spot, rate and the first leg's IV from the feed; the second typed."""
    base = ResolvedInputs.all_entered(
        EnteredInputs.from_portfolio(book),
        resolved_at=_NOW,
    )
    first, second = (p.position_id for p in book.positions)
    return replace(
        base,
        spot=ResolvedValue(5000.0, InputOrigin.FETCHED, "feed"),
        risk_free_rate=ResolvedValue(0.045, InputOrigin.FETCHED, "feed"),
        legs={
            first: ResolvedValue(0.31, InputOrigin.FETCHED, "feed"),
            second: ResolvedValue(0.19, InputOrigin.FALLBACK, "typed"),
        },
        is_identity=False,
    )


class TestPricedView:
    """A copy priced on the resolution; the typed book is left alone."""

    def test_the_view_is_priced_on_the_resolved_inputs(self) -> None:
        book = _typed_book()
        resolved = _resolved(book)

        view = book.priced_view(resolved)

        assert view.spot_price == pytest.approx(5000.0)
        assert view.risk_free_rate == pytest.approx(0.045)
        assert view.dividend_yield == pytest.approx(0.013)
        assert view.positions[0].option.volatility == pytest.approx(0.31)
        assert view.positions[1].option.volatility == pytest.approx(0.19)
        assert view.positions[0].option.spot_price == pytest.approx(5000.0)
        assert view.positions[0].option.risk_free_rate == pytest.approx(0.045)

    def test_the_typed_book_is_never_touched(self) -> None:
        book = _typed_book()
        before = list(book.positions)

        book.priced_view(_resolved(book))

        assert book.spot_price == pytest.approx(4800.0)
        assert book.risk_free_rate == pytest.approx(0.03)
        assert book.positions == before
        assert book.positions[0].option.volatility == pytest.approx(0.19)
        assert book.positions[0].option.risk_free_rate == pytest.approx(0.03)

    def test_nothing_is_stamped(self) -> None:
        """A fetched value was confirmed by nobody; a typed one is as it was."""
        book = _typed_book()

        view = book.priced_view(_resolved(book))

        assert view.stamps == book.stamps
        assert all(
            position.volatility_as_of == _CONFIRMED
            for position in view.positions
        )

    def test_identity_liquidity_and_pins_survive(self) -> None:
        book = _typed_book()
        book.spot_override = True
        book.positions[1].volatility_override = True

        view = book.priced_view(_resolved(book))

        assert [p.position_id for p in view.positions] == [
            p.position_id for p in book.positions
        ]
        assert view.positions[0].liquidity == _QUOTE
        assert view.spot_override is True
        assert view.positions[1].volatility_override is True

    def test_a_leg_priced_on_the_feed_is_custom_so_a_book_vol_edit_skips_it(
        self,
    ) -> None:
        book = _typed_book()
        book.positions[0].custom_volatility = False

        view = book.priced_view(_resolved(book))
        view.update_market_conditions(volatility=0.5)

        assert view.positions[0].custom_volatility is True
        assert view.positions[0].option.volatility == pytest.approx(0.31)

    def test_market_parameters_the_resolution_does_not_decide_are_copied(
        self,
    ) -> None:
        book = _typed_book()

        view = book.priced_view(_resolved(book))

        assert view.volatility == book.volatility
        assert view.underlying_quantity == book.underlying_quantity
        assert view.valuation_date == book.valuation_date
        assert view.symbol == book.symbol
        assert view.default_exercise_style == book.default_exercise_style
        assert view.contract_size == book.contract_size


class TestApplyResolvedInputs:
    """The in-place form, for a book that is itself a copy."""

    def test_it_prices_the_book_without_stamping(self) -> None:
        book = _typed_book()

        book.apply_resolved_inputs(_resolved(book))

        assert book.spot_price == pytest.approx(5000.0)
        assert book.positions[0].option.volatility == pytest.approx(0.31)
        assert book.stamps.spot_as_of == _CONFIRMED
        assert book.positions[0].volatility_as_of == _CONFIRMED
        assert book.positions[0].liquidity == _QUOTE

    def test_a_leg_the_resolution_does_not_name_keeps_its_own_iv(self) -> None:
        book = _typed_book()
        resolved = _resolved(book)
        only_first = replace(
            resolved,
            legs={
                book.positions[0].position_id: resolved.legs[
                    book.positions[0].position_id
                ]
            },
        )

        book.apply_resolved_inputs(only_first)

        assert book.positions[1].option.volatility == pytest.approx(0.19)
