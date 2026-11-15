"""``ProgramState.roll_structure`` rolls a spread as one atomic decision.

A put spread is two lots that trade as one package. Rolling it leg by leg
leaves the book half-rolled between the two submissions, and the roll plan
groups by ``structure_id``, so the new long leg would sit in a structure with
the old short one. ``roll_structure`` closes every old leg and opens every new
one under one lock, or changes nothing, and still records **two linked fills
per leg**: each leg's close and open share that leg's own ``roll_id``, never
one id across legs and never one net figure.

Every strike, price and fee here is an invented figure chosen to be easy to
read; none is a real position.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deltadewa import history_store
from deltadewa.analysis.realized_carry import reconcile_book
from deltadewa.clock import program_now
from deltadewa.portfolio.history import (
    CloseReason,
    FillKind,
    RollLeg,
    mark_book,
)
from deltadewa.state import ConfirmationRequiredError
from tests.clock_helpers import days_from_today, program_date

from .test_state_history import _history, _load, _order

if TYPE_CHECKING:
    from pathlib import Path

    from deltadewa.portfolio.position import OptionPosition
    from deltadewa.state import ProgramState

_LATER = days_from_today(540)
_TAG = "tranche-a"


@pytest.fixture
def state(tmp_path: Path) -> ProgramState:
    """A fresh state whose history lives under its export directory."""
    return _load(tmp_path)


def _spread(state: ProgramState) -> tuple[OptionPosition, OptionPosition]:
    """A long 4200 put and a short 3800 put, tagged as one structure."""
    long_leg = state.open_position(_order(10, structure_id=_TAG))
    short_leg = state.open_position(
        _order(
            -10,
            strike_price=3800.0,
            price_per_share=20.0,
            structure_id=_TAG,
        ),
    )
    return long_leg, short_leg


def _legs(
    long_leg: OptionPosition,
    short_leg: OptionPosition,
) -> list[RollLeg]:
    return [
        RollLeg(
            position_id=long_leg.position_id,
            close_price_per_share=44.0,
            close_fees=7.0,
            into=_order(
                10,
                strike_price=4400.0,
                maturity_date=_LATER,
                price_per_share=61.0,
                fees=8.0,
                structure_id=_TAG,
            ),
        ),
        RollLeg(
            position_id=short_leg.position_id,
            close_price_per_share=15.0,
            close_fees=5.0,
            into=_order(
                -10,
                strike_price=4000.0,
                maturity_date=_LATER,
                price_per_share=24.0,
                fees=6.0,
                structure_id=_TAG,
            ),
        ),
    ]


class TestASpreadRollsAsTwoLinkedFillsPerLeg:
    def test_four_fills_in_leg_order_each_pair_linked(
        self,
        state: ProgramState,
    ) -> None:
        long_leg, short_leg = _spread(state)

        state.roll_structure(
            _legs(long_leg, short_leg),
            reason=CloseReason.ROUTINE,
            confirm=True,
        )

        fills = _history(state).load().fills[-4:]
        assert [f.kind for f in fills] == [
            FillKind.CLOSE,
            FillKind.OPEN,
            FillKind.CLOSE,
            FillKind.OPEN,
        ]
        first_close, first_open, second_close, second_open = fills
        assert first_close.roll_id is not None
        assert first_close.roll_id == first_open.roll_id
        assert second_close.roll_id is not None
        assert second_close.roll_id == second_open.roll_id
        # One id per leg: nothing pairs a close with another leg's open.
        assert first_close.roll_id != second_close.roll_id
        assert first_close.position_id == long_leg.position_id
        assert second_close.position_id == short_leg.position_id

    def test_each_leg_keeps_its_own_price_and_fees(
        self,
        state: ProgramState,
    ) -> None:
        long_leg, short_leg = _spread(state)

        state.roll_structure(
            _legs(long_leg, short_leg),
            reason=CloseReason.ROUTINE,
            confirm=True,
        )

        close_a, open_a, close_b, open_b = _history(state).load().fills[-4:]
        assert (close_a.price_per_share, close_a.fees) == (44.0, 7.0)
        assert (open_a.price_per_share, open_a.fees) == (61.0, 8.0)
        assert (close_b.price_per_share, close_b.fees) == (15.0, 5.0)
        assert (open_b.price_per_share, open_b.fees) == (24.0, 6.0)
        # Closing the long sells it; closing the short buys it back.
        assert (close_a.quantity, close_b.quantity) == (-10, 10)
        assert (open_a.quantity, open_b.quantity) == (10, -10)
        # The cash is per leg, so the package's net is recoverable by
        # summing, and the legs are not recoverable from the net.
        assert close_a.cash_flow() == pytest.approx(10 * 44.0 * 100 - 7.0)
        assert close_b.cash_flow() == pytest.approx(-10 * 15.0 * 100 - 5.0)

    def test_the_book_holds_the_new_legs_only_and_keeps_the_tag(
        self,
        state: ProgramState,
    ) -> None:
        long_leg, short_leg = _spread(state)

        news = state.roll_structure(
            _legs(long_leg, short_leg),
            reason=CloseReason.ROUTINE,
            confirm=True,
        )

        held = state.portfolio.positions
        assert [p.position_id for p in held] == [n.position_id for n in news]
        assert [p.option.strike_price for p in held] == [4400.0, 4000.0]
        assert {p.structure_id for p in held} == {_TAG}
        assert not state.dirty

    def test_reason_and_trade_date_apply_to_every_close(
        self,
        state: ProgramState,
    ) -> None:
        long_leg, short_leg = _spread(state)
        traded = program_date().date()

        state.roll_structure(
            _legs(long_leg, short_leg),
            reason=CloseReason.MONETIZATION,
            trade_date=traded,
            note="rolled the tranche",
            confirm=True,
        )

        fills = _history(state).load().fills[-4:]
        closes = [f for f in fills if f.kind is FillKind.CLOSE]
        assert {f.reason for f in closes} == {CloseReason.MONETIZATION}
        assert {f.trade_date for f in fills} == {traded}
        assert {f.note for f in fills} == {"rolled the tranche"}

    def test_a_single_leg_is_a_structure_of_one(
        self,
        state: ProgramState,
    ) -> None:
        old = state.open_position(_order(10))

        (new,) = state.roll_structure(
            [
                RollLeg(
                    position_id=old.position_id,
                    close_price_per_share=20.0,
                    close_fees=0.0,
                    into=_order(10, strike_price=4400.0, maturity_date=_LATER),
                ),
            ],
            reason=CloseReason.ROUTINE,
            confirm=True,
        )

        close, opened = _history(state).load().fills[-2:]
        assert close.roll_id == opened.roll_id
        assert close.fees is not None
        assert close.fees == pytest.approx(0.0)
        assert [p.position_id for p in state.portfolio.positions] == [
            new.position_id,
        ]


class TestItIsAllOrNothing:
    def test_a_refused_new_leg_leaves_both_old_legs_and_no_fills(
        self,
        state: ProgramState,
    ) -> None:
        """The first new lot is valid; the second is expired. Neither stays."""
        long_leg, short_leg = _spread(state)
        legs = _legs(long_leg, short_leg)
        legs[1] = RollLeg(
            position_id=short_leg.position_id,
            close_price_per_share=15.0,
            close_fees=5.0,
            into=_order(
                -10,
                strike_price=4000.0,
                maturity_date=days_from_today(-1),
            ),
        )
        fills_before = len(_history(state).load().fills)

        with pytest.raises(ValueError, match="already-expired"):
            state.roll_structure(
                legs,
                reason=CloseReason.ROUTINE,
                confirm=True,
            )

        assert [p.position_id for p in state.portfolio.positions] == [
            long_leg.position_id,
            short_leg.position_id,
        ]
        assert len(_history(state).load().fills) == fills_before

    def test_a_journal_failure_rolls_the_whole_spread_back(
        self,
        state: ProgramState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        long_leg, short_leg = _spread(state)
        before = _history(state).events_path.read_text()

        def _disk_full(*_args: object, **_kwargs: object) -> None:
            raise OSError("No space left on device")

        monkeypatch.setattr(history_store, "_append_lines", _disk_full)
        with pytest.raises(OSError, match="No space"):
            state.roll_structure(
                _legs(long_leg, short_leg),
                reason=CloseReason.ROUTINE,
                confirm=True,
            )

        assert _history(state).events_path.read_text() == before
        assert [p.position_id for p in state.portfolio.positions] == [
            long_leg.position_id,
            short_leg.position_id,
        ]

    def test_an_unknown_lot_changes_nothing(
        self,
        state: ProgramState,
    ) -> None:
        long_leg, short_leg = _spread(state)
        legs = _legs(long_leg, short_leg)
        legs[1] = RollLeg(
            position_id="gone",
            close_price_per_share=1.0,
            close_fees=0.0,
            into=legs[1].into,
        )

        with pytest.raises(KeyError, match="no position"):
            state.roll_structure(
                legs,
                reason=CloseReason.ROUTINE,
                confirm=True,
            )

        assert len(state.portfolio.positions) == 2


class TestItRefusesWhatItShould:
    def test_needs_confirmation(self, state: ProgramState) -> None:
        long_leg, short_leg = _spread(state)
        with pytest.raises(ConfirmationRequiredError):
            state.roll_structure(
                _legs(long_leg, short_leg),
                reason=CloseReason.ROUTINE,
            )
        assert len(state.portfolio.positions) == 2

    def test_no_legs(self, state: ProgramState) -> None:
        with pytest.raises(ValueError, match="at least one leg"):
            state.roll_structure(
                [],
                reason=CloseReason.ROUTINE,
                confirm=True,
            )

    def test_a_lot_twice(self, state: ProgramState) -> None:
        long_leg, short_leg = _spread(state)
        legs = _legs(long_leg, short_leg)
        legs.append(legs[0])
        with pytest.raises(ValueError, match="once in one action"):
            state.roll_structure(
                legs,
                reason=CloseReason.ROUTINE,
                confirm=True,
            )
        assert len(state.portfolio.positions) == 2

    @pytest.mark.parametrize("field", ["close_price_per_share", "close_fees"])
    def test_a_negative_close_is_refused_at_construction(
        self,
        field: str,
    ) -> None:
        kwargs = {
            "position_id": "x",
            "close_price_per_share": 1.0,
            "close_fees": 0.0,
            "into": _order(1),
        }
        kwargs[field] = -0.01
        with pytest.raises(ValueError, match="must be >= 0"):
            RollLeg(**kwargs)  # type: ignore[arg-type]


def test_a_rolled_spread_reconciles_against_the_book(
    state: ProgramState,
) -> None:
    """Opening mark plus the rolled spread's four fills explains the book."""
    long_leg, short_leg = _spread(state)
    history = _history(state)
    history.append_mark(
        mark_book(
            state.portfolio,
            marked_at=program_now(),
            written_by="test",
            is_opening=True,
        ),
    )

    state.roll_structure(
        _legs(long_leg, short_leg),
        reason=CloseReason.ROUTINE,
        confirm=True,
    )

    assert reconcile_book(history.load(), state.portfolio.positions) == ()
