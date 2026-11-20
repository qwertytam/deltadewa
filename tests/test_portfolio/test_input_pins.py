"""Tests for the rebuilt-leg helper and the override pins (9b, D7).

The r/q rebuild in ``update_market_conditions`` used to construct a fresh
``OptionPosition`` that dropped the operator's recorded liquidity quote. It
now goes through :func:`~deltadewa.portfolio.core.rebuilt_position`, which
keeps everything a leg carries, and that helper is also what the priced
view is built from. The pins (``spot_override``, ``volatility_override``)
are the only thing saved about an override; they must round-trip, and a leg
whose contract changes must lose its pin.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.persistence import PortfolioSerializer
from deltadewa.portfolio.core import OptionPortfolio, rebuilt_position
from deltadewa.portfolio.liquidity import LiquidityObservation
from deltadewa.reporting.audit import PortfolioLogger
from tests.clock_helpers import days_from_today

if TYPE_CHECKING:
    from pathlib import Path

_SEEN = datetime(2026, 11, 6, 15, 30, tzinfo=UTC)
_QUOTE = LiquidityObservation(
    bid=2.40,
    ask=2.60,
    open_interest=3_400,
    observed_at=_SEEN,
)


def _book() -> OptionPortfolio:
    portfolio = OptionPortfolio(
        spot_price=100.0,
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.01,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=80.0,
        maturity_date=days_from_today(365),
        quantity=10,
        option_type=OptionType.PUT,
        volatility=0.27,
        entry_premium=3.5,
        structure_id="s1",
    )
    portfolio.positions[0].liquidity = _QUOTE
    return portfolio


class TestRebuiltPosition:
    """Everything a leg carries survives a rebuild."""

    def test_a_rate_change_keeps_the_recorded_liquidity_quote(self) -> None:
        book = _book()

        book.update_market_conditions(risk_free_rate=0.05)

        assert book.positions[0].liquidity == _QUOTE

    def test_an_unchanged_rate_still_keeps_it(self) -> None:
        """The rebuild runs even when the rate is repeated."""
        book = _book()

        book.update_market_conditions(risk_free_rate=0.04)

        assert book.positions[0].liquidity == _QUOTE

    def test_a_dividend_change_keeps_it(self) -> None:
        book = _book()

        book.update_market_conditions(dividend_yield=0.02)

        assert book.positions[0].liquidity == _QUOTE

    def test_the_rebuild_keeps_identity_cost_basis_and_pin(self) -> None:
        book = _book()
        original = book.positions[0]
        original.volatility_override = True

        rebuilt = rebuilt_position(
            original,
            spot_price=105.0,
            volatility=0.31,
            risk_free_rate=0.045,
            dividend_yield=0.012,
            valuation_date=book.valuation_date,
        )

        assert rebuilt is not original
        assert rebuilt.position_id == original.position_id
        assert rebuilt.entry_premium == pytest.approx(3.5)
        assert rebuilt.structure_id == "s1"
        assert rebuilt.volatility_as_of == original.volatility_as_of
        assert rebuilt.liquidity == _QUOTE
        assert rebuilt.volatility_override is True
        assert rebuilt.option.volatility == pytest.approx(0.31)
        assert rebuilt.option.spot_price == pytest.approx(105.0)
        assert rebuilt.option.risk_free_rate == pytest.approx(0.045)

    def test_the_original_is_never_mutated(self) -> None:
        book = _book()
        original = book.positions[0]

        rebuilt_position(
            original,
            spot_price=90.0,
            volatility=0.5,
            risk_free_rate=0.0,
            dividend_yield=0.0,
            valuation_date=book.valuation_date,
        )

        assert original.option.volatility == pytest.approx(0.27)
        assert original.option.spot_price == pytest.approx(100.0)


class TestPins:
    """A pin is saved, restored, and cleared with the contract it described."""

    def test_pins_default_off(self) -> None:
        book = _book()

        assert book.spot_override is False
        assert book.positions[0].volatility_override is False

    def test_pins_round_trip_through_json(self, tmp_path: Path) -> None:
        book = _book()
        book.spot_override = True
        book.positions[0].volatility_override = True
        serializer = PortfolioSerializer(export_dir=tmp_path)
        path = serializer.export_to_json(
            book,
            PortfolioLogger(name="t"),
            filename="book.json",
        )

        restored = serializer.import_from_json(
            path,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )["portfolio"]

        assert restored.spot_override is True
        assert restored.positions[0].volatility_override is True

    def test_a_book_without_the_keys_loads_unpinned(
        self,
        tmp_path: Path,
    ) -> None:
        """Every file saved before the pins existed has neither key."""
        book = _book()
        serializer = PortfolioSerializer(export_dir=tmp_path)
        path = serializer.export_to_json(
            book,
            PortfolioLogger(name="t"),
            filename="book.json",
        )
        data = json.loads(path.read_text())
        del data["market_parameters"]["spot_override"]
        for position in data["positions"]:
            del position["volatility_override"]
        path.write_text(json.dumps(data))

        restored = serializer.import_from_json(
            path,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )["portfolio"]

        assert restored.spot_override is False
        assert restored.positions[0].volatility_override is False

    def test_a_contract_change_clears_the_leg_pin(self) -> None:
        book = _book()
        book.positions[0].volatility_override = True

        book.update_position(0, strike=75.0)

        assert book.positions[0].volatility_override is False

    def test_a_quantity_change_keeps_the_leg_pin(self) -> None:
        book = _book()
        book.positions[0].volatility_override = True

        book.update_position(0, quantity=12)

        assert book.positions[0].volatility_override is True
