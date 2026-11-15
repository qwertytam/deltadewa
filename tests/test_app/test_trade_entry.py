"""The trade forms' logic: parse, review, record (#446).

``deltadewa/app/trade_entry.py`` is what the close, settle and roll forms
call, so these drive it with plain values and a real ``ProgramState``. The
points that matter most:

* a blank is never read as zero: ``0.0`` fees are accepted, a blank is
  refused, for every price, fee and settlement field;
* the review sentence's cash is the recorded fill's cash (one formula);
* a roll records two fills per leg, all legs or none, and refuses a form
  built from a structure that has since changed;
* the unsettled-lot list is exactly the legs ``mark_book`` flags.

Every strike, price, fee and date here is an invented figure.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest

from deltadewa.app import trade_entry as te
from deltadewa.clock import program_now
from deltadewa.constants import OptionType
from deltadewa.formatters.values import format_currency
from deltadewa.portfolio.history import (
    CloseReason,
    FillKind,
    mark_book,
)
from tests.clock_helpers import days_from_today, program_date

from ..test_state_history import _history, _load, _order

if TYPE_CHECKING:
    from pathlib import Path

    from deltadewa.portfolio.position import OptionPosition
    from deltadewa.state import ProgramState

TODAY = program_date().date()
_LATER = days_from_today(540)
_TAG = "tranche-a"


@pytest.fixture
def state(tmp_path: Path) -> ProgramState:
    """A fresh state whose history lives under its export directory."""
    return _load(tmp_path)


def _spread(state: ProgramState) -> tuple[OptionPosition, OptionPosition]:
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


def _close_raw(position: OptionPosition, **overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "position_id": position.position_id,
        "contracts": 4,
        "price": 55.0,
        "fees": 2.6,
        "reason": "ROUTINE",
        "date": None,
        "note": "",
    }
    raw.update(overrides)
    return raw


def _leg_raw(position: OptionPosition, **overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "position_id": position.position_id,
        "close_price": 44.0,
        "close_fees": 7.0,
        "strike": 4400.0,
        "maturity": _LATER.date().isoformat(),
        "quantity": None,
        "price": 61.0,
        "fees": 8.0,
    }
    raw.update(overrides)
    return raw


def _roll_raw(*legs: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "legs": list(legs),
        "reason": "ROUTINE",
        "date": None,
        "tag": "",
        "note": "",
    }
    raw.update(overrides)
    return raw


class TestABlankIsNeverZero:
    """``0.0`` is a recorded zero; blank is "not captured" and is refused."""

    @pytest.mark.parametrize("blank", [None, ""])
    def test_close_fees(self, state: ProgramState, blank: object) -> None:
        position = state.open_position(_order(10))
        with pytest.raises(te.TradeEntryError, match="Fees is required"):
            te.parse_close(_close_raw(position, fees=blank), today=TODAY)

    def test_close_accepts_zero_fees_and_a_zero_price(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(10))

        entry = te.parse_close(
            _close_raw(position, fees=0.0, price=0.0),
            today=TODAY,
        )

        assert entry.fees == pytest.approx(0.0)
        assert entry.price_per_share == pytest.approx(0.0)

    @pytest.mark.parametrize("blank", [None, ""])
    def test_close_price(self, state: ProgramState, blank: object) -> None:
        position = state.open_position(_order(10))
        with pytest.raises(te.TradeEntryError, match="Price per share"):
            te.parse_close(_close_raw(position, price=blank), today=TODAY)

    @pytest.mark.parametrize("blank", [None, ""])
    def test_settlement_value_says_to_enter_zero(
        self,
        state: ProgramState,
        blank: object,
    ) -> None:
        position = state.open_position(_order(10))
        raw = {
            "position_id": position.position_id,
            "settlement": blank,
            "fees": 0.0,
            "date": TODAY.isoformat(),
        }
        with pytest.raises(te.TradeEntryError, match="enter 0 if it expired"):
            te.parse_settle(raw, today=TODAY)

    def test_settle_accepts_a_worthless_expiry(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(10))
        raw = {
            "position_id": position.position_id,
            "settlement": 0.0,
            "fees": 0.0,
            "date": TODAY.isoformat(),
        }

        entry = te.parse_settle(raw, today=TODAY)

        assert entry.settlement_per_share == pytest.approx(0.0)
        assert entry.fees == pytest.approx(0.0)

    def test_settlement_date_has_no_default(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(10))
        raw = {
            "position_id": position.position_id,
            "settlement": 0.0,
            "fees": 0.0,
            "date": None,
        }
        with pytest.raises(te.TradeEntryError, match="Settlement date"):
            te.parse_settle(raw, today=TODAY)

    @pytest.mark.parametrize(
        "field",
        ["close_price", "close_fees", "price", "fees", "strike", "maturity"],
    )
    def test_every_roll_field_but_quantity(
        self,
        state: ProgramState,
        field: str,
    ) -> None:
        long_leg, _ = _spread(state)
        raw = _roll_raw(_leg_raw(long_leg, **{field: None}))
        with pytest.raises(te.TradeEntryError, match=r"Leg 1: .*required"):
            te.parse_roll(raw, today=TODAY)


class TestRefusals:
    def test_a_reason_is_required_and_never_inferred(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(10))
        with pytest.raises(te.TradeEntryError, match="Reason is required"):
            te.parse_close(_close_raw(position, reason=None), today=TODAY)

    @pytest.mark.parametrize("contracts", [None, 0, -1, 2.5])
    def test_contracts_are_a_positive_whole_number(
        self,
        state: ProgramState,
        contracts: object,
    ) -> None:
        position = state.open_position(_order(10))
        with pytest.raises(te.TradeEntryError, match="Contracts to close"):
            te.parse_close(
                _close_raw(position, contracts=contracts),
                today=TODAY,
            )

    def test_a_lot_must_be_picked(self) -> None:
        with pytest.raises(te.TradeEntryError, match="Lot is required"):
            te.parse_close(
                {
                    "position_id": None,
                    "contracts": 1,
                    "price": 1.0,
                    "fees": 0.0,
                    "reason": "ROUTINE",
                },
                today=TODAY,
            )

    def test_a_future_trade_date_is_refused(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(10))
        tomorrow = (TODAY + timedelta(days=1)).isoformat()
        with pytest.raises(te.TradeEntryError, match="after today"):
            te.parse_close(_close_raw(position, date=tomorrow), today=TODAY)

    def test_a_blank_trade_date_is_left_for_the_program_clock(
        self,
        state: ProgramState,
    ) -> None:
        """``None`` reaches ProgramState, which resolves it via clock.py."""
        position = state.open_position(_order(10))
        entry = te.parse_close(_close_raw(position, date=""), today=TODAY)
        assert entry.trade_date is None

    def test_a_roll_with_no_legs(self) -> None:
        with pytest.raises(te.TradeEntryError, match="Pick the structure"):
            te.parse_roll(_roll_raw(), today=TODAY)

    @pytest.mark.parametrize("quantity", [0, 1.5])
    def test_a_new_quantity_is_a_non_zero_whole_number(
        self,
        state: ProgramState,
        quantity: float,
    ) -> None:
        long_leg, _ = _spread(state)
        with pytest.raises(te.TradeEntryError, match="New quantity"):
            te.parse_roll(
                _roll_raw(_leg_raw(long_leg, quantity=quantity)),
                today=TODAY,
            )

    def test_a_blank_new_quantity_keeps_the_old_one(
        self,
        state: ProgramState,
    ) -> None:
        long_leg, _ = _spread(state)
        entry = te.parse_roll(_roll_raw(_leg_raw(long_leg)), today=TODAY)
        assert entry.legs[0].quantity is None

    def test_the_second_leg_is_named_in_its_error(
        self,
        state: ProgramState,
    ) -> None:
        long_leg, short_leg = _spread(state)
        raw = _roll_raw(
            _leg_raw(long_leg),
            _leg_raw(short_leg, fees=None),
        )
        with pytest.raises(te.TradeEntryError, match="Leg 2: New fees"):
            te.parse_roll(raw, today=TODAY)


class TestReviewSaysWhatWillBeRecorded:
    def test_a_partial_close_says_how_many_remain(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(10))
        entry = te.parse_close(_close_raw(position), today=TODAY)

        review = te.review_close(
            entry,
            state.positions_snapshot(),
            today=TODAY,
            last_mark=None,
        )

        assert "Close 4 of 10 contracts" in review.summary
        assert "6 remain" in review.summary
        assert "(today)" in review.summary
        assert review.lines[0].startswith("Sell 4 x PUT 4200")

    def test_closing_a_short_lot_buys_it_back(
        self,
        state: ProgramState,
    ) -> None:
        _, short_leg = _spread(state)
        entry = te.parse_close(_close_raw(short_leg), today=TODAY)

        review = te.review_close(
            entry,
            state.positions_snapshot(),
            today=TODAY,
            last_mark=None,
        )

        assert review.lines[0].startswith("Buy back 4 x PUT 3800")

    def test_the_cash_shown_is_the_cash_recorded(
        self,
        state: ProgramState,
    ) -> None:
        """One formula: the preview's figure is the fill's ``cash_flow``."""
        position = state.open_position(_order(10))
        entry = te.parse_close(_close_raw(position), today=TODAY)
        review = te.review_close(
            entry,
            state.positions_snapshot(),
            today=TODAY,
            last_mark=None,
        )

        te.record_close(entry, state)

        recorded = _history(state).load().fills[-1]
        assert recorded.cash_flow() is not None
        shown = format_currency(recorded.cash_flow() or 0.0, show_sign=True)
        assert shown in review.lines[0]

    def test_more_contracts_than_held_is_refused(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(3))
        entry = te.parse_close(_close_raw(position), today=TODAY)
        with pytest.raises(te.TradeEntryError, match="Cannot close 4"):
            te.review_close(
                entry,
                state.positions_snapshot(),
                today=TODAY,
                last_mark=None,
            )

    def test_a_lot_removed_since_the_form_was_filled_is_refused_cleanly(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(10))
        entry = te.parse_close(_close_raw(position), today=TODAY)
        state.remove_position(0, confirm=True)
        with pytest.raises(te.TradeEntryError, match="no longer in the book"):
            te.review_close(
                entry,
                state.positions_snapshot(),
                today=TODAY,
                last_mark=None,
            )

    def test_settling_before_expiry_is_refused(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(10))
        entry = te.parse_settle(
            {
                "position_id": position.position_id,
                "settlement": 0.0,
                "fees": 0.0,
                "date": TODAY.isoformat(),
            },
            today=TODAY,
        )
        with pytest.raises(te.TradeEntryError, match="cannot settle"):
            te.review_settle(
                entry,
                state.positions_snapshot(),
                today=TODAY,
                last_mark=None,
            )


class TestTheBackdatingWarning:
    @pytest.mark.parametrize(
        ("days_after_mark", "warned"),
        [(-3, True), (0, True), (1, False)],
        ids=["before", "on the mark date", "after"],
    )
    def test_a_trade_inside_a_closed_period_is_warned_not_blocked(
        self,
        state: ProgramState,
        days_after_mark: int,
        warned: bool,
    ) -> None:
        position = state.open_position(_order(10))
        last_mark = TODAY - timedelta(days=5)
        traded = last_mark + timedelta(days=days_after_mark)
        entry = te.parse_close(
            _close_raw(position, date=traded.isoformat()),
            today=TODAY,
        )

        review = te.review_close(
            entry,
            state.positions_snapshot(),
            today=TODAY,
            last_mark=last_mark,
        )

        assert bool(review.warnings) is warned
        if warned:
            assert str(last_mark) in review.warnings[0]
            assert "break" in review.warnings[0]

    def test_no_mark_no_warning(self, state: ProgramState) -> None:
        position = state.open_position(_order(10))
        entry = te.parse_close(_close_raw(position), today=TODAY)
        review = te.review_close(
            entry,
            state.positions_snapshot(),
            today=TODAY,
            last_mark=None,
        )
        assert review.warnings == ()


class TestRecordClose:
    def test_a_partial_close_records_a_close_fill(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(10))

        te.record_close(
            te.parse_close(_close_raw(position), today=TODAY),
            state,
        )

        fill = _history(state).load().fills[-1]
        assert fill.kind is FillKind.CLOSE
        assert (fill.quantity, fill.price_per_share, fill.fees) == (
            -4,
            55.0,
            2.6,
        )
        assert fill.reason is CloseReason.ROUTINE
        assert int(state.positions_snapshot()[0].quantity) == 6

    def test_a_zero_fee_close_is_recorded_as_zero_not_uncaptured(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(10))

        te.record_close(
            te.parse_close(_close_raw(position, fees=0.0), today=TODAY),
            state,
        )

        fill = _history(state).load().fills[-1]
        assert fill.fees is not None
        assert fill.fees == pytest.approx(0.0)
        assert fill.cash_flow() is not None


class TestRecordSettle:
    def test_a_settlement_on_expiry_records_a_settle_fill(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(2))
        expiry = position.option.maturity_date.date()
        entry = te.parse_settle(
            {
                "position_id": position.position_id,
                "settlement": 0.0,
                "fees": 0.0,
                "date": expiry.isoformat(),
                "note": "expired worthless",
            },
            today=expiry,
        )
        review = te.review_settle(
            entry,
            state.positions_snapshot(),
            today=expiry,
            last_mark=None,
        )

        te.record_settle(entry, state)

        assert "expired worthless" in review.summary
        fill = _history(state).load().fills[-1]
        assert fill.kind is FillKind.SETTLE
        assert fill.trade_date == expiry
        assert fill.price_per_share == pytest.approx(0.0)
        assert fill.note == "expired worthless"
        assert state.positions_snapshot() == ()


class TestRollingASpread:
    def _entry(
        self,
        state: ProgramState,
        **overrides: Any,
    ) -> te.RollEntry:
        long_leg, short_leg = _spread(state)
        return te.parse_roll(
            _roll_raw(
                _leg_raw(long_leg),
                _leg_raw(
                    short_leg,
                    close_price=15.0,
                    close_fees=5.0,
                    strike=4000.0,
                    price=24.0,
                    fees=6.0,
                ),
                **overrides,
            ),
            today=TODAY,
        )

    def test_records_two_linked_fills_per_leg(
        self,
        state: ProgramState,
    ) -> None:
        entry = self._entry(state)

        te.record_roll(entry, state)

        fills = _history(state).load().fills[-4:]
        assert [f.kind for f in fills] == [
            FillKind.CLOSE,
            FillKind.OPEN,
            FillKind.CLOSE,
            FillKind.OPEN,
        ]
        assert fills[0].roll_id == fills[1].roll_id
        assert fills[2].roll_id == fills[3].roll_id
        assert fills[0].roll_id != fills[2].roll_id

    def test_new_lots_inherit_what_the_form_does_not_ask(
        self,
        state: ProgramState,
    ) -> None:
        entry = self._entry(state)

        te.record_roll(entry, state)

        held = state.positions_snapshot()
        assert [int(p.quantity) for p in held] == [10, -10]
        assert {p.structure_id for p in held} == {_TAG}
        assert {int(p.contract_size) for p in held} == {100}
        assert {p.option.option_type for p in held} == {OptionType.PUT.value}

    def test_a_typed_tag_applies_to_every_new_leg(
        self,
        state: ProgramState,
    ) -> None:
        entry = self._entry(state, tag="tranche-b")

        te.record_roll(entry, state)

        assert {p.structure_id for p in state.positions_snapshot()} == {
            "tranche-b",
        }

    def test_the_package_net_is_the_sum_of_the_recorded_fills(
        self,
        state: ProgramState,
    ) -> None:
        """The net is shown for checking; it is the four fills, summed."""
        entry = self._entry(state)
        review = te.review_roll(
            entry,
            state.positions_snapshot(),
            today=TODAY,
            last_mark=None,
        )

        te.record_roll(entry, state)

        total = sum(
            fill.cash_flow() or 0.0
            for fill in _history(state).load().fills[-4:]
        )
        assert (
            f"Package net {format_currency(total, show_sign=True)}"
            in (review.lines[-1])
        )
        assert "not stored" in review.lines[-1]
        assert len(review.lines) == 5

    def test_a_roll_of_part_of_a_structure_is_refused(
        self,
        state: ProgramState,
    ) -> None:
        long_leg, _ = _spread(state)
        entry = te.parse_roll(_roll_raw(_leg_raw(long_leg)), today=TODAY)
        with pytest.raises(te.TradeEntryError, match="changed since"):
            te.review_roll(
                entry,
                state.positions_snapshot(),
                today=TODAY,
                last_mark=None,
            )
        with pytest.raises(te.TradeEntryError, match="changed since"):
            te.record_roll(entry, state)
        assert len(state.positions_snapshot()) == 2

    def test_lots_from_two_structures_are_refused(
        self,
        state: ProgramState,
    ) -> None:
        first = state.open_position(_order(10, structure_id="a"))
        second = state.open_position(
            _order(10, strike_price=4300.0, structure_id="b"),
        )
        entry = te.parse_roll(
            _roll_raw(_leg_raw(first), _leg_raw(second)),
            today=TODAY,
        )
        with pytest.raises(te.TradeEntryError, match="not one structure"):
            te.record_roll(entry, state)

    def test_a_single_standalone_leg_rolls(self, state: ProgramState) -> None:
        old = state.open_position(_order(10))
        entry = te.parse_roll(_roll_raw(_leg_raw(old)), today=TODAY)

        te.record_roll(entry, state)

        close, opened = _history(state).load().fills[-2:]
        assert close.roll_id == opened.roll_id
        assert [p.option.strike_price for p in state.positions_snapshot()] == [
            4400.0,
        ]


class TestStructureChoices:
    def test_a_tag_groups_its_legs_and_a_lone_lot_stands_alone(
        self,
        state: ProgramState,
    ) -> None:
        long_leg, short_leg = _spread(state)
        alone = state.open_position(_order(5, strike_price=5000.0))

        options = te.structure_options(state.positions_snapshot())

        assert [o["value"] for o in options] == [
            f"tag:{_TAG}",
            f"lot:{alone.position_id}",
        ]
        assert "PUT 4200" in options[0]["label"]
        assert "PUT 3800" in options[0]["label"]
        legs = te.structure_legs(
            state.positions_snapshot(), options[0]["value"]
        )
        assert [leg.position_id for leg in legs] == [
            long_leg.position_id,
            short_leg.position_id,
        ]

    def test_a_vanished_structure_is_refused(self, state: ProgramState) -> None:
        with pytest.raises(te.TradeEntryError, match="no longer in the book"):
            te.structure_legs((), "tag:gone")


class TestUnsettledLotsAreWhatTheMarkFlags:
    def test_agree_with_mark_book(self, state: ProgramState) -> None:
        """One definition of expired: the prompt fires iff the mark flags."""
        live = state.open_position(_order(5))
        expired = state.portfolio.add_position(
            strike_price=3900.0,
            maturity_date=days_from_today(-3),
            quantity=2,
            option_type=OptionType.PUT,
            reject_expired=False,
        )

        flagged = {
            leg.position_id
            for leg in mark_book(
                state.portfolio,
                marked_at=program_now(),
                written_by="test",
            ).expired_unsettled_legs
        }
        prompted = {
            p.position_id
            for p in te.unsettled_lots(
                state.positions_snapshot(),
                valuation_date=state.portfolio.valuation_date,
            )
        }

        assert prompted == flagged == {expired.position_id}
        assert live.position_id not in prompted

    def test_a_lot_expiring_today_is_unsettled(
        self,
        state: ProgramState,
    ) -> None:
        position = state.open_position(_order(1))
        on_expiry = position.option.maturity_date

        assert te.unsettled_lots([position], valuation_date=on_expiry) == (
            position,
        )
        assert (
            te.unsettled_lots(
                [position],
                valuation_date=on_expiry - timedelta(days=1),
            )
            == ()
        )
