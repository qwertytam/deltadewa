"""``ProgramState`` journals every book change to the position history (#313).

What each mutator records, that a refused mutation records nothing, that a
failed journal write leaves the book and the history agreeing, and that a
history built only through these methods reconciles against the live book.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from deltadewa import history_store
from deltadewa.analysis.realized_carry import reconcile_book
from deltadewa.clock import program_now
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.history_store import HistoryCorruptError, HistoryStore
from deltadewa.portfolio.history import (
    CloseReason,
    EditKind,
    FillKind,
    OpenOrder,
    mark_book,
)
from deltadewa.state import ConfirmationRequiredError, ProgramState
from tests.clock_helpers import days_from_today, program_date

if TYPE_CHECKING:
    from pathlib import Path

# Seeded off the program clock (#321/#343): a pinned literal would expire.
_MATURITY = days_from_today(365)
_LATER_MATURITY = days_from_today(540)


def _load(tmp_path: Path) -> ProgramState:
    return ProgramState.load(
        tmp_path,
        ips_path=tmp_path / "missing-ips.yaml",
        default_exercise_style=ExerciseStyle.EUROPEAN,
        examples_dir=tmp_path / "no-examples",
    )


def _order(quantity: int = 10, **overrides: object) -> OpenOrder:
    fields: dict[str, object] = {
        "strike_price": 4200.0,
        "maturity_date": _MATURITY,
        "option_type": OptionType.PUT,
        "quantity": quantity,
        "price_per_share": 50.0,
        "fees": 6.5,
    }
    fields.update(overrides)
    return OpenOrder(**fields)  # type: ignore[arg-type]


def _history(state: ProgramState) -> HistoryStore:
    assert state.history is not None
    return state.history


@pytest.fixture
def state(tmp_path: Path) -> ProgramState:
    """A fresh state whose history lives under its export directory."""
    return _load(tmp_path)


def test_history_lives_under_exports(
    state: ProgramState,
    tmp_path: Path,
) -> None:
    """The default location is what the nightly backup already archives."""
    assert _history(state).root == tmp_path / "history"


class TestExistingMutators:
    """The current entry/edit paths journal what they did."""

    def test_add_position_is_an_open_with_fees_not_captured(
        self,
        state: ProgramState,
    ) -> None:
        """The entry form has no fee field, so the fee is unknown, not 0."""
        position = state.add_position(
            strike_price=4200.0,
            maturity_date=_MATURITY,
            quantity=10,
            option_type=OptionType.PUT,
            entry_premium=48.5,
        )
        (fill,) = _history(state).load().fills
        assert fill.kind is FillKind.OPEN
        assert fill.position_id == position.position_id
        assert fill.quantity == 10
        assert fill.price_per_share == pytest.approx(48.5)
        assert fill.fees is None
        assert fill.trade_date == program_date().date()
        assert fill.written_by == "app"

    def test_backdated_entry_keeps_its_trade_date(
        self,
        state: ProgramState,
    ) -> None:
        """A lot entered late is dated when it traded, not when typed."""
        traded = program_date() - timedelta(days=30)
        state.add_position(
            strike_price=4200.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
            entry_date=traded,
        )
        (fill,) = _history(state).load().fills
        assert fill.trade_date == traded.date()

    def test_volatility_only_edit_writes_nothing(
        self,
        state: ProgramState,
    ) -> None:
        """A new volatility moves the marks, not the book."""
        state.add_position(
            strike_price=4200.0,
            maturity_date=_MATURITY,
            quantity=10,
            option_type=OptionType.PUT,
        )
        state.update_position(0, volatility=0.25)
        assert _history(state).load().edits == ()

    def test_quantity_edit_is_an_amend(self, state: ProgramState) -> None:
        """Changing a lot in place is a book edit with before and after."""
        state.add_position(
            strike_price=4200.0,
            maturity_date=_MATURITY,
            quantity=10,
            option_type=OptionType.PUT,
        )
        state.update_position(0, quantity=12, strike=4300.0)
        (amend,) = _history(state).load().edits
        assert amend.kind is EditKind.AMEND
        assert (amend.quantity_before, amend.quantity_after) == (10, 12)
        assert amend.before is not None
        assert amend.after is not None
        assert (amend.before.strike, amend.after.strike) == (4200.0, 4300.0)
        assert "edited to +12 x PUT 4300" in amend.detail

    def test_remove_and_clear_are_deletes(self, state: ProgramState) -> None:
        """Lots leaving with no proceeds are recorded as such."""
        for strike in (4000.0, 4100.0, 4200.0):
            state.add_position(
                strike_price=strike,
                maturity_date=_MATURITY,
                quantity=1,
                option_type=OptionType.PUT,
            )
        state.remove_position(0, confirm=True)
        state.clear_positions(confirm=True)
        edits = _history(state).load().edits
        assert [e.kind for e in edits] == [EditKind.DELETE] * 3
        assert "no proceeds recorded" in edits[0].detail

    def test_import_is_a_replace(
        self,
        state: ProgramState,
        tmp_path: Path,
    ) -> None:
        """A whole-book import is one edit naming the file."""
        state.add_position(
            strike_price=4200.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
        )
        exported = state.export_snapshot("copy.json")
        state.import_portfolio(exported)
        (replace,) = _history(state).load().edits
        assert replace.kind is EditKind.REPLACE
        assert replace.position_id is None
        assert "copy.json" in replace.detail
        assert tmp_path in exported.parents

    def test_market_inputs_write_nothing(self, state: ProgramState) -> None:
        """Spot, volatility and rates are not book changes."""
        state.update_market_conditions(spot_price=5100.0)
        state.set_volatility(0.22)
        state.set_underlying_quantity(1000.0)
        assert not _history(state).exists()

    def test_refused_mutation_records_nothing(
        self,
        state: ProgramState,
    ) -> None:
        """An expired maturity is refused before anything is journaled."""
        with pytest.raises(ValueError, match="already-expired"):
            state.add_position(
                strike_price=4200.0,
                maturity_date=days_from_today(-1),
                quantity=1,
                option_type=OptionType.PUT,
            )
        assert not _history(state).exists()


class TestTrades:
    """The trade methods record the cash."""

    def test_open_records_price_and_fees(self, state: ProgramState) -> None:
        """An order is entered as a fill, fee and all."""
        position = state.open_position(_order())
        (fill,) = _history(state).load().fills
        assert fill.cash_flow() == pytest.approx(-(10 * 50.0 * 100) - 6.5)
        assert position.entry_premium == pytest.approx(50.0)
        assert position.entry_date is not None
        assert position.entry_date.date() == program_date().date()

    def test_partial_close(self, state: ProgramState) -> None:
        """Closing part of a long lot sells and shrinks the lot."""
        position = state.open_position(_order(10))
        state.close_position(
            position.position_id,
            contracts=4,
            price_per_share=60.0,
            fees=2.6,
            reason=CloseReason.MONETIZATION,
            confirm=True,
        )
        assert state.portfolio.positions[0].quantity == 6
        close = _history(state).load().fills[-1]
        assert close.kind is FillKind.CLOSE
        assert close.quantity == -4
        assert close.reason is CloseReason.MONETIZATION
        assert close.cash_flow() == pytest.approx(4 * 60.0 * 100 - 2.6)

    def test_full_close_of_a_short_lot_buys_back(
        self,
        state: ProgramState,
    ) -> None:
        """A short lot closes upward and leaves the book."""
        position = state.open_position(_order(-5))
        state.close_position(
            position.position_id,
            contracts=5,
            price_per_share=1.0,
            fees=0.0,
            reason=CloseReason.ROUTINE,
            confirm=True,
        )
        assert state.portfolio.positions == []
        assert _history(state).load().fills[-1].quantity == 5

    def test_over_close_refused_and_not_journaled(
        self,
        state: ProgramState,
    ) -> None:
        """Closing more than the lot holds changes nothing."""
        position = state.open_position(_order(3))
        with pytest.raises(ValueError, match="cannot close 4"):
            state.close_position(
                position.position_id,
                contracts=4,
                price_per_share=1.0,
                fees=0.0,
                reason=CloseReason.ROUTINE,
                confirm=True,
            )
        assert len(_history(state).load().fills) == 1
        assert state.portfolio.positions[0].quantity == 3

    def test_trades_need_confirmation(self, state: ProgramState) -> None:
        """Every trade that removes contracts is confirm-gated."""
        position = state.open_position(_order())
        with pytest.raises(ConfirmationRequiredError):
            state.close_position(
                position.position_id,
                contracts=1,
                price_per_share=1.0,
                fees=0.0,
                reason=CloseReason.ROUTINE,
            )
        with pytest.raises(ConfirmationRequiredError):
            state.settle_position(
                position.position_id,
                settlement_per_share=0.0,
                fees=0.0,
            )
        with pytest.raises(ConfirmationRequiredError):
            state.roll_position(
                position.position_id,
                close_price_per_share=1.0,
                close_fees=0.0,
                into=_order(),
            )

    def test_unknown_lot(self, state: ProgramState) -> None:
        """A position id the book does not hold is a KeyError."""
        with pytest.raises(KeyError, match="no position"):
            state.close_position(
                "nope",
                contracts=1,
                price_per_share=1.0,
                fees=0.0,
                reason=CloseReason.ROUTINE,
                confirm=True,
            )

    def test_settle_only_at_or_after_expiry(self, state: ProgramState) -> None:
        """Settling before expiry is refused; on expiry the lot leaves."""
        position = state.open_position(_order(2))
        expiry = _MATURITY.date()
        with pytest.raises(ValueError, match="cannot settle"):
            state.settle_position(
                position.position_id,
                settlement_per_share=0.0,
                fees=0.0,
                trade_date=expiry - timedelta(days=1),
                confirm=True,
            )
        state.settle_position(
            position.position_id,
            settlement_per_share=12.5,
            fees=1.0,
            trade_date=expiry,
            confirm=True,
        )
        settle = _history(state).load().fills[-1]
        assert settle.kind is FillKind.SETTLE
        assert settle.quantity == -2
        assert settle.effective_reason is CloseReason.ROUTINE
        assert settle.cash_flow() == pytest.approx(2 * 12.5 * 100 - 1.0)
        assert state.portfolio.positions == []

    def test_roll_is_two_linked_fills(self, state: ProgramState) -> None:
        """Close then open, one roll id, the old lot gone."""
        old = state.open_position(_order(10))
        new = state.roll_position(
            old.position_id,
            close_price_per_share=20.0,
            close_fees=6.5,
            into=_order(
                10,
                strike_price=4400.0,
                maturity_date=_LATER_MATURITY,
            ),
            confirm=True,
        )
        close, opened = _history(state).load().fills[-2:]
        assert (close.kind, opened.kind) == (FillKind.CLOSE, FillKind.OPEN)
        assert close.roll_id is not None
        assert close.roll_id == opened.roll_id
        assert close.position_id == old.position_id
        assert opened.position_id == new.position_id
        assert [p.position_id for p in state.portfolio.positions] == [
            new.position_id,
        ]

    def test_refused_roll_changes_nothing(self, state: ProgramState) -> None:
        """Rolling into an expired contract leaves the old lot and no fills."""
        old = state.open_position(_order(10))
        with pytest.raises(ValueError, match="already-expired"):
            state.roll_position(
                old.position_id,
                close_price_per_share=20.0,
                close_fees=0.0,
                into=_order(10, maturity_date=days_from_today(-1)),
                confirm=True,
            )
        assert [p.position_id for p in state.portfolio.positions] == [
            old.position_id,
        ]
        assert len(_history(state).load().fills) == 1


class TestJournalFailure:
    """The book and the history never silently disagree."""

    def test_corrupt_history_refuses_before_mutating(
        self,
        state: ProgramState,
    ) -> None:
        """A history that cannot be read stops the change at the door."""
        history = _history(state)
        history.root.mkdir(parents=True)
        history.events_path.write_text("{broken\n")
        with pytest.raises(HistoryCorruptError):
            state.open_position(_order())
        assert state.portfolio.positions == []

    def test_failed_append_reverts_to_the_last_save(
        self,
        state: ProgramState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The saved book is the book before the change: reload it."""
        kept = state.open_position(_order(1))

        def _disk_full(*_args: object, **_kwargs: object) -> None:
            raise OSError("No space left on device")

        monkeypatch.setattr(history_store, "_append_lines", _disk_full)
        with pytest.raises(OSError, match="No space"):
            state.open_position(_order(2, strike_price=4000.0))
        assert [p.position_id for p in state.portfolio.positions] == [
            kept.position_id,
        ]
        assert not state.dirty

    def test_failed_append_with_nothing_saved_is_left_dirty(
        self,
        state: ProgramState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No saved book to return to: keep the change, unsaved, and say so."""

        def _disk_full(*_args: object, **_kwargs: object) -> None:
            raise OSError("No space left on device")

        monkeypatch.setattr(history_store, "_append_lines", _disk_full)
        with pytest.raises(OSError, match="No space"):
            state.open_position(_order())
        assert state.dirty
        assert len(state.portfolio.positions) == 1

    def test_a_failed_revert_cannot_mask_the_error_or_skip_the_flag(
        self,
        state: ProgramState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If reloading the last save fails, the book is flagged, not trusted.

        The journal error is what the operator must see, and ``dirty`` is
        what /health reads: a raise from the revert would replace the first
        and skip the second.
        """
        state.open_position(_order(1))

        def _disk_full(*_args: object, **_kwargs: object) -> None:
            raise OSError("No space left on device")

        def _unreadable(*_args: object, **_kwargs: object) -> None:
            raise ValueError("state file is unreadable")

        monkeypatch.setattr(history_store, "_append_lines", _disk_full)
        monkeypatch.setattr(
            state._serializer,
            "import_from_json",
            _unreadable,
        )
        with pytest.raises(OSError, match="No space"):
            state.open_position(_order(2, strike_price=4000.0))
        assert state.dirty
        # The unjournaled change is still in memory, and flagged as unsaved.
        assert len(state.portfolio.positions) == 2

    def test_a_multi_record_change_is_all_or_nothing(
        self,
        state: ProgramState,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A roll that cannot be journaled leaves no half of it behind."""
        old = state.open_position(_order(10))
        before = _history(state).events_path.read_text()

        def _disk_full(*_args: object, **_kwargs: object) -> None:
            raise OSError("No space left on device")

        monkeypatch.setattr(history_store, "_append_lines", _disk_full)
        with pytest.raises(OSError, match="No space"):
            state.roll_position(
                old.position_id,
                close_price_per_share=20.0,
                close_fees=0.0,
                into=_order(10, strike_price=4400.0),
                confirm=True,
            )
        assert _history(state).events_path.read_text() == before
        assert [p.position_id for p in state.portfolio.positions] == [
            old.position_id,
        ]


def test_trades_alone_reconcile_against_the_book(
    state: ProgramState,
) -> None:
    """Opening mark plus every journaled trade explains the live book."""
    history = _history(state)
    first = state.open_position(_order(10))
    history.append_mark(
        mark_book(
            state.portfolio,
            marked_at=program_now(),
            written_by="test",
            is_opening=True,
        ),
    )
    # After the opening mark: every change goes through a journaled path.
    state.close_position(
        first.position_id,
        contracts=4,
        price_per_share=55.0,
        fees=2.6,
        reason=CloseReason.ROUTINE,
        confirm=True,
    )
    state.roll_position(
        first.position_id,
        close_price_per_share=56.0,
        close_fees=3.9,
        into=_order(6, strike_price=4400.0, maturity_date=_LATER_MATURITY),
        confirm=True,
    )
    state.update_position(0, quantity=7)
    assert reconcile_book(history.load(), state.portfolio.positions) == ()
