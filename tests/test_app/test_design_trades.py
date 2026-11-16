"""The `/design` trade forms: review, confirm, prompt, wiring (#446).

``test_trade_entry.py`` covers what a form means; this covers what the page
does with it: that a review writes nothing, that a confirm records exactly
what was reviewed and only once, that the unsettled-expiry prompt lists what
the next mark would flag, that every id a callback reads exists on the page,
and that a period containing only form-recorded trades reads reconcilable in
digest section 4 while a ``Remove`` of the same lot does not.

Every strike, price, fee and date here is an invented figure.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from dash import no_update
from dash.development.base_component import Component

from deltadewa.analysis.realized_carry import reconcile_book
from deltadewa.app import trade_entry as te
from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages import design
from deltadewa.clock import program_now
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.portfolio.history import FillKind, mark_book
from deltadewa.reporting.program_report import (
    RealizedStatus,
    build_realized_carry_section,
)
from deltadewa.state import ProgramState
from tests.clock_helpers import days_from_today, program_date

from ..test_state_history import _history, _order

if TYPE_CHECKING:
    from deltadewa.portfolio.position import OptionPosition

_EXAMPLE_IPS_YAML = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)  # #245: real config/ips.yaml is gitignored; use the tracked example.

TODAY = program_date().date()
_LATER = days_from_today(540)
_TAG = "tranche-a"


def _app(tmp_path: Path) -> ProgramDashApp:
    state = ProgramState.load(
        tmp_path,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    return create_app(
        state=state,
        market_data=StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0),
        ips_config=state.ips_config,
    )


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


def _roll_raw(
    long_leg: OptionPosition,
    short_leg: OptionPosition,
) -> dict[str, Any]:
    def _leg(position: OptionPosition, **values: Any) -> dict[str, Any]:
        leg: dict[str, Any] = {
            "position_id": position.position_id,
            "close_price": 44.0,
            "close_fees": 7.0,
            "strike": 4400.0,
            "maturity": _LATER.date().isoformat(),
            "quantity": None,
            "price": 61.0,
            "fees": 8.0,
        }
        leg.update(values)
        return leg

    return {
        "legs": [
            _leg(long_leg),
            _leg(
                short_leg,
                close_price=15.0,
                close_fees=5.0,
                strike=4000.0,
                price=24.0,
                fees=6.0,
            ),
        ],
        "reason": "ROUTINE",
        "date": None,
        "tag": "",
        "note": "",
    }


def _ids(node: object) -> set[str]:
    """Every plain string id in a layout tree."""
    found: set[str] = set()
    if isinstance(node, Component):
        component_id = getattr(node, "id", None)
        if isinstance(component_id, str):
            found.add(component_id)
        found |= _ids(getattr(node, "children", None))
    elif isinstance(node, (list, tuple)):
        for child in node:
            found |= _ids(child)
    return found


class TestTheBlockIsOnThePage:
    def test_every_form_control_exists_and_the_toc_lists_the_block(
        self,
        tmp_path: Path,
    ) -> None:
        layout = design.render(_app(tmp_path))
        ids = _ids(layout)

        for prefix in ("close", "settle", "roll"):
            for suffix in (
                "review",
                "confirm",
                "cancel",
                "pending",
                "confirm-row",
                "review-text",
                "fields",
            ):
                assert f"{prefix}-{suffix}" in ids, f"{prefix}-{suffix}"
        assert {
            "section-trades",
            "section-settle",
            "trade-unsettled-prompt",
        } <= ids

    def test_every_id_a_callback_reads_is_on_the_page(
        self,
        tmp_path: Path,
    ) -> None:
        """A dead id silently leaves a form doing nothing; pin them all."""
        app = _app(tmp_path)
        on_page = _ids(design.render(app))
        # Created by callbacks after load, never in the initial layout.
        built_later = {"roll-legs"}
        referenced: set[str] = set()
        for entry in app.callback_map.values():
            for ref in [*entry.get("inputs", []), *entry.get("state", [])]:
                component_id = ref.get("id")
                if not isinstance(component_id, str):
                    continue  # a pattern-matching id; its parts are dicts
                if component_id.startswith(
                    ("close-", "settle-", "roll-", "add-", "trade-"),
                ):
                    referenced.add(component_id)
        assert {"close-lot", "settle-lot", "roll-structure"} <= referenced
        assert referenced - on_page - built_later == set()

    def test_no_ips_page_shows_none_of_it(self, tmp_path: Path) -> None:
        state = ProgramState.load(
            tmp_path,
            ips_path=tmp_path / "missing.yaml",
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        app = create_app(
            state=state,
            market_data=StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0),
            ips_config=state.ips_config,
        )
        assert "close-review" not in _ids(design.render(app))


class TestAReviewWritesNothing:
    def test_a_good_form_shows_the_trade_and_keeps_the_raw_values(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))
        fills_before = len(_history(state).load().fills)
        raw = _close_raw(position)

        pending, hidden, text, status = design.review_trade(
            design.CLOSE,
            raw,
            state,
        )

        # The raw values, plus the day a blank date meant when it was
        # reviewed (see TestAConfirmRecordsTheDateThatWasReviewed).
        assert pending == {**raw, "date": te.program_today(state).isoformat()}
        assert hidden is False
        assert "Close 4 of 10" in str(text)
        assert "Review the trade below" in status.children
        assert len(_history(state).load().fills) == fills_before
        assert int(state.positions_snapshot()[0].quantity) == 10

    def test_a_refused_form_keeps_the_confirm_row_hidden(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))

        pending, hidden, text, status = design.review_trade(
            design.CLOSE,
            _close_raw(position, fees=None),
            state,
        )

        assert pending is None
        assert hidden is True
        assert text == []
        assert "Fees is required" in status.children
        assert "status-message--error" in status.className

    def test_a_backdated_trade_carries_its_warning(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))
        state.history.append_mark(  # type: ignore[union-attr]
            mark_book(
                state.portfolio,
                marked_at=program_now(),
                written_by="test",
                is_opening=True,
            ),
        )
        mark_day = te.last_mark_date(state)
        assert mark_day is not None
        raw = _close_raw(
            position,
            date=(mark_day - timedelta(days=1)).isoformat(),
        )

        _pending, hidden, text, _status = design.review_trade(
            design.CLOSE,
            raw,
            state,
        )

        assert hidden is False
        assert "boundary mark" in str(text)


class TestAConfirmRecordsWhatWasReviewed:
    def test_records_once_and_bumps_the_version(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))
        pending = _close_raw(position)

        version, status, recorded = design.confirm_trade(
            design.CLOSE,
            pending,
            3,
            state,
        )

        assert (version, recorded) == (4, True)
        assert status.children.startswith("Recorded: Close 4 of 10")
        fill = _history(state).load().fills[-1]
        assert fill.kind is FillKind.CLOSE
        assert (fill.price_per_share, fill.fees) == (55.0, 2.6)

    def test_nothing_pending_records_nothing(self, tmp_path: Path) -> None:
        """A second click after the first confirm has nothing to replay."""
        state = _app(tmp_path).program_state
        state.open_position(_order(10))
        fills_before = len(_history(state).load().fills)

        version, status, recorded = design.confirm_trade(
            design.CLOSE,
            None,
            3,
            state,
        )

        assert version is no_update
        assert recorded is False
        assert "Review the trade first" in status.children
        assert len(_history(state).load().fills) == fills_before

    def test_a_lot_removed_since_the_review_fails_cleanly(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))
        pending = _close_raw(position)
        state.remove_position(0, confirm=True)

        version, status, recorded = design.confirm_trade(
            design.CLOSE,
            pending,
            3,
            state,
        )

        assert (version is no_update, recorded) == (True, False)
        assert "no longer in the book" in status.children

    def test_a_write_that_raises_is_contained_and_does_not_bump(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("disk full")

        monkeypatch.setattr(state, "close_position", _boom)

        version, status, recorded = design.confirm_trade(
            design.CLOSE,
            _close_raw(position),
            3,
            state,
        )

        assert (version is no_update, recorded) == (True, False)
        assert "went wrong" in status.children
        assert int(state.positions_snapshot()[0].quantity) == 10

    def test_a_spread_roll_records_both_legs_atomically(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        long_leg, short_leg = _spread(state)

        version, status, recorded = design.confirm_trade(
            design.ROLL,
            _roll_raw(long_leg, short_leg),
            0,
            state,
        )

        assert (version, recorded) == (1, True)
        assert "Roll 2 legs" in status.children
        fills = _history(state).load().fills[-4:]
        assert [f.kind for f in fills] == [
            FillKind.CLOSE,
            FillKind.OPEN,
            FillKind.CLOSE,
            FillKind.OPEN,
        ]
        assert [p.option.strike_price for p in state.positions_snapshot()] == [
            4400.0,
            4000.0,
        ]

    def test_a_refused_roll_leaves_the_whole_spread(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        long_leg, short_leg = _spread(state)
        raw = _roll_raw(long_leg, short_leg)
        raw["legs"][1]["maturity"] = days_from_today(-1).date().isoformat()
        fills_before = len(_history(state).load().fills)

        version, status, recorded = design.confirm_trade(
            design.ROLL,
            raw,
            0,
            state,
        )

        assert (version is no_update, recorded) == (True, False)
        assert "already-expired" in status.children
        assert [p.position_id for p in state.positions_snapshot()] == [
            long_leg.position_id,
            short_leg.position_id,
        ]
        assert len(_history(state).load().fills) == fills_before


class TestTheRollFormsFieldsAreGatheredByLeg:
    """``_roll_raw`` reads Dash's ``states_list``, which a direct call to the
    logic functions never touches; a browser found it reading the wrong key
    for the date pickers (a leg's maturity always arrived blank)."""

    def test_values_are_grouped_by_lot_and_the_date_is_its_value(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from types import SimpleNamespace

        from deltadewa.app.pages.design import trades

        def _field(lot: str, name: str, value: object) -> dict[str, Any]:
            return {
                "id": {"type": "roll-field", "lot": lot, "field": name},
                "property": "value",
                "value": value,
            }

        def _maturity(lot: str, value: object) -> dict[str, Any]:
            return {
                "id": {"type": "roll-maturity", "lot": lot},
                "property": "date",
                "value": value,
            }

        # Dates from the program clock, not literals: a fixture date is a
        # figure that can look real and that goes stale.
        traded = TODAY.isoformat()
        maturity = _LATER.date().isoformat()
        states = [
            {"value": "tag:a"},
            {"value": "ROUTINE"},
            {"value": traded},
            {"value": ""},
            {"value": "a note"},
            [
                _field("L1", "close_price", 44.0),
                _field("L1", "close_fees", 0.0),
                _field("L2", "close_price", 15.0),
            ],
            [_maturity("L1", maturity), _maturity("L2", maturity)],
        ]
        monkeypatch.setattr(
            trades,
            "ctx",
            SimpleNamespace(states_list=states),
        )

        raw = trades._roll_raw(
            ("tag:a", "ROUTINE", traded, "", "a note", [], []),
        )

        assert raw["reason"] == "ROUTINE"
        assert raw["date"] == traded
        assert raw["note"] == "a note"
        first, second = raw["legs"]
        assert first == {
            "position_id": "L1",
            "close_price": 44.0,
            "close_fees": 0.0,
            "maturity": maturity,
        }
        assert second["position_id"] == "L2"
        assert second["maturity"] == maturity


class TestTheCallbacksFailSafely:
    """What the blast-radius audit found outside the happy path."""

    def test_a_form_that_cannot_be_read_says_so(self, tmp_path: Path) -> None:
        state = _app(tmp_path).program_state

        def _unreadable(_values: tuple[object, ...]) -> dict[str, Any]:
            raise RuntimeError("no states_list")

        pending, hidden, text, status = design.review_outputs(
            design.CLOSE,
            _unreadable,
            (),
            state,
        )

        assert (pending, hidden, text) == (None, True, [])
        assert "went wrong" in status.children

    def test_a_rebuild_that_raises_after_a_recorded_trade_strands_nothing(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))

        def _broken() -> Component:
            raise RuntimeError("cannot build the fields")

        version, status, pending, hidden, disabled, fields = (
            design.confirm_outputs(
                design.CLOSE,
                _close_raw(position),
                3,
                state,
                _broken,
            )
        )

        assert version == 4  # the trade is recorded, so the page refreshes
        assert status.children.startswith("Recorded:")
        assert (pending, hidden, disabled) == (None, True, False)
        assert fields is no_update  # the form stays as it was, and re-opens
        assert int(state.positions_snapshot()[0].quantity) == 6

    def test_a_lot_gone_between_review_and_write_reads_as_gone(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))

        def _gone(*_args: object, **_kwargs: object) -> None:
            raise KeyError("no position with id 'x'")

        monkeypatch.setattr(state, "close_position", _gone)

        version, status, recorded = design.confirm_trade(
            design.CLOSE,
            _close_raw(position),
            3,
            state,
        )

        assert (version is no_update, recorded) == (True, False)
        assert "no longer in the book" in status.children
        assert "went wrong" not in status.children

    def test_a_write_that_went_in_unsaved_says_not_to_enter_it_again(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The journal took the fill and the save failed: a re-entry doubles."""
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))

        def _saved_nothing(*_args: object, **_kwargs: object) -> None:
            state._dirty = True  # as _mutate_and_save leaves it on failure
            raise OSError("No space left on device")

        monkeypatch.setattr(state, "close_position", _saved_nothing)

        _version, status, recorded = design.confirm_trade(
            design.CLOSE,
            _close_raw(position),
            3,
            state,
        )

        assert recorded is False
        assert "not saved" in status.children
        assert "check Book changes" in status.children

    def test_a_plain_refusal_does_not_claim_unsaved_changes(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(3))

        _version, status, recorded = design.confirm_trade(
            design.CLOSE,
            _close_raw(position, contracts=4),
            3,
            state,
        )

        assert recorded is False
        assert "Cannot close 4" in status.children
        assert "not saved" not in status.children


class TestAConfirmRecordsTheDateThatWasReviewed:
    """A blank date is resolved when it is reviewed, not when it is confirmed.

    The review says "(today)"; left blank in the pending values, a confirm
    after program midnight would record the next day under a review that
    named the previous one, and could move the trade across a boundary
    mark (clock audit of #446).
    """

    def test_the_review_stores_the_day_it_named(self, tmp_path: Path) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))

        pending, *_ = design.review_trade(
            design.CLOSE,
            _close_raw(position, date=""),
            state,
        )

        assert pending["date"] == te.program_today(state).isoformat()

    def test_a_confirm_after_midnight_records_the_reviewed_day(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = _app(tmp_path).program_state
        position = state.open_position(_order(10))
        reviewed_on = te.program_today(state)
        pending, *_ = design.review_trade(
            design.CLOSE,
            _close_raw(position),
            state,
        )

        # Program midnight passes between the review and the confirm.
        monkeypatch.setattr(
            te,
            "program_today",
            lambda _state: reviewed_on + timedelta(days=1),
        )
        _version, _status, recorded = design.confirm_trade(
            design.CLOSE,
            pending,
            0,
            state,
        )

        assert recorded is True
        assert _history(state).load().fills[-1].trade_date == reviewed_on


def _add(state: ProgramState, **overrides: Any) -> tuple[Any, ...]:
    values: dict[str, Any] = {
        "strike": 4000.0,
        "maturity": _LATER.date().isoformat(),
        "quantity": 3,
        "option_type": OptionType.PUT.value,
        "exercise_style": ExerciseStyle.EUROPEAN.value,
        "entry_premium": 61.0,
        "fees": 8.0,
        "trade_date": None,
        "structure_id": None,
        "version": 0,
        "state": state,
    }
    values.update(overrides)
    return design._add_position_logic(**values)


class TestAMaturityTheProgramDayHasReachedIsNotRecorded:
    """The portfolio's guard reads a date that lags; the forms read the day.

    A process that outlives program midnight keeps ``valuation_date`` at its
    boot day, so ``OptionPortfolio.add_position``'s expired-maturity guard
    accepts a maturity the program day has already reached (Codex review of
    #486; #437's class). Both forms are refused on the program's day.
    """

    @staticmethod
    def _lag(state: ProgramState) -> None:
        state.update_market_conditions(
            valuation_date=program_date() - timedelta(days=3),
        )

    def test_the_stale_date_alone_would_accept_it(
        self,
        tmp_path: Path,
    ) -> None:
        """Control: the guard the forms used to rely on lets it through."""
        state = _app(tmp_path).program_state
        self._lag(state)
        lot = state.portfolio.add_position(
            strike_price=3900.0,
            maturity_date=program_date() - timedelta(days=1),
            quantity=1,
            option_type=OptionType.PUT,
        )
        assert lot in state.portfolio.positions

    def test_add_refuses_it(self, tmp_path: Path) -> None:
        state = _app(tmp_path).program_state
        self._lag(state)
        fills_before = len(_history(state).load().fills)

        version, status, *_rest = _add(
            state,
            maturity=(te.program_today(state) - timedelta(days=1)).isoformat(),
        )

        assert version is no_update
        assert "already-expired" in status.children
        assert state.portfolio.positions == []
        assert len(_history(state).load().fills) == fills_before

    def test_a_roll_refuses_it_and_leaves_the_spread(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        long_leg, short_leg = _spread(state)
        self._lag(state)
        raw = _roll_raw(long_leg, short_leg)
        raw["legs"][0]["maturity"] = (
            te.program_today(state) - timedelta(days=1)
        ).isoformat()
        fills_before = len(_history(state).load().fills)

        version, status, recorded = design.confirm_trade(
            design.ROLL,
            raw,
            0,
            state,
        )

        assert (version is no_update, recorded) == (True, False)
        assert "Leg 1: New maturity" in status.children
        assert "already-expired" in status.children
        assert [p.position_id for p in state.positions_snapshot()] == [
            long_leg.position_id,
            short_leg.position_id,
        ]
        assert len(_history(state).load().fills) == fills_before


class TestAddWarnsWhenItIsBackdated:
    """Add records on submit, so its warning rides beside "Added." (#486)."""

    @staticmethod
    def _mark(state: ProgramState) -> date:
        state.history.append_mark(  # type: ignore[union-attr]
            mark_book(
                state.portfolio,
                marked_at=program_now(),
                written_by="test",
                is_opening=True,
            ),
        )
        mark_day = te.last_mark_date(state)
        assert mark_day is not None
        return mark_day

    def test_a_trade_on_or_before_the_mark_is_recorded_and_warned(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        state.open_position(_order(5))
        mark_day = self._mark(state)

        version, status, *_rest = _add(
            state,
            trade_date=(mark_day - timedelta(days=1)).isoformat(),
        )

        assert version == 1
        assert status.children.startswith("Added. ⚠ ")
        assert "taken without this trade" in status.children
        assert "status-message--success" in status.className
        assert len(state.portfolio.positions) == 2

    def test_a_trade_dated_today_after_the_mark_day_is_not(
        self,
        tmp_path: Path,
    ) -> None:
        """No mark, no warning: the plain message is unchanged."""
        state = _app(tmp_path).program_state

        version, status, *_rest = _add(state)

        assert version == 1
        assert status.children == "Added."

    def test_a_history_that_cannot_be_read_refuses_the_add(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The warning is read before the write: no unwarned fill."""
        state = _app(tmp_path).program_state

        def _broken(_state: ProgramState) -> None:
            msg = "unreadable"
            raise RuntimeError(msg)

        monkeypatch.setattr(te, "last_mark_date", _broken)

        version, status, *_rest = _add(state)

        assert version is no_update
        assert "status-message--error" in status.className
        assert state.portfolio.positions == []


class TestTheUnsettledExpiryPrompt:
    def _book_with_an_expired_lot(self, state: ProgramState) -> OptionPosition:
        state.open_position(_order(5))
        return state.portfolio.add_position(
            strike_price=3900.0,
            maturity_date=days_from_today(-3),
            quantity=2,
            option_type=OptionType.PUT,
            reject_expired=False,
        )

    def test_is_silent_when_nothing_has_expired(self, tmp_path: Path) -> None:
        state = _app(tmp_path).program_state
        state.open_position(_order(5))

        prompt = design.unsettled_prompt(state)

        assert getattr(prompt, "className", None) is None
        assert getattr(prompt, "children", None) in (None, [])

    def test_lists_the_expired_lot_and_links_to_settle(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        expired = self._book_with_an_expired_lot(state)

        prompt = design.unsettled_prompt(state)
        text = str(prompt)

        assert "PUT 3900" in text
        assert "no settlement recorded" in text
        assert "#section-settle" in text
        assert expired.position_id in text
        assert "PUT 4200" not in text

    def test_lists_what_the_next_mark_would_flag(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        expired = self._book_with_an_expired_lot(state)

        flagged = {
            leg.position_id
            for leg in mark_book(
                state.portfolio,
                marked_at=program_now(),
                written_by="test",
            ).expired_unsettled_legs
        }

        assert flagged == {expired.position_id}
        assert expired.position_id in str(design.unsettled_prompt(state))


class TestThePromptAgreesWithTheMarkTheJobTakes:
    """The prompt reads the program's day; so does a freshly loaded job.

    The weekly job loads the book afresh and takes its mark on that load's
    valuation date, which is the program day. The long-running app's own
    ``portfolio.valuation_date`` is seeded once at boot and not advanced, so
    after a midnight it lags: the prompt must not follow it, or a lot that
    expired today would be missing from the prompt and present in the mark
    (clock audit of #446).
    """

    def test_a_lot_expiring_today_is_listed_though_the_app_date_lags(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        state.open_position(_order(5))
        expiring = state.portfolio.add_position(
            strike_price=3900.0,
            maturity_date=program_date(),
            quantity=2,
            option_type=OptionType.PUT,
            reject_expired=False,
        )
        # The running app's date three days behind the program's.
        state.update_market_conditions(
            valuation_date=program_date() - timedelta(days=3),
        )
        assert (
            te.unsettled_lots(
                state.positions_snapshot(),
                valuation_date=state.portfolio.valuation_date,
            )
            == ()
        ), "the stale date alone would hide the lot"

        prompted = expiring.position_id in str(design.unsettled_prompt(state))

        fresh = ProgramState.load(
            tmp_path,
            ips_path=_EXAMPLE_IPS_YAML,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        flagged = {
            leg.position_id
            for leg in mark_book(
                fresh.portfolio,
                marked_at=program_now(),
                written_by="test",
            ).expired_unsettled_legs
        }
        assert prompted
        assert flagged == {expiring.position_id}


class TestTheRollFormsLegBlocks:
    def test_one_block_per_leg_with_a_field_per_term(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        long_leg, short_leg = _spread(state)

        blocks = design.roll_leg_blocks(state, f"tag:{_TAG}")
        text = str(blocks)

        assert text.count("Leg 1:") == 1
        assert text.count("Leg 2:") == 1
        for leg in (long_leg, short_leg):
            for field in (
                "close_price",
                "close_fees",
                "strike",
                "quantity",
                "price",
                "fees",
            ):
                assert (
                    "{'type': 'roll-field', 'lot': "
                    f"'{leg.position_id}', 'field': '{field}'}}"
                ) in text
            assert (
                f"{{'type': 'roll-maturity', 'lot': '{leg.position_id}'}}"
            ) in text
        assert "roll-maturity" in text

    def test_no_choice_asks_for_one(self, tmp_path: Path) -> None:
        state = _app(tmp_path).program_state
        assert "Choose a structure" in str(design.roll_leg_blocks(state, None))

    def test_a_vanished_structure_says_so(self, tmp_path: Path) -> None:
        state = _app(tmp_path).program_state
        blocks = design.roll_leg_blocks(state, "tag:gone")
        assert "no longer in the book" in str(blocks)


class TestDigestSectionFourReconciles:
    """A period of only form-recorded trades must read reconcilable.

    The point of the forms: until now a close meant Remove, which journals a
    ``DELETE`` with no cash, and any period containing one reads "cannot be
    reconciled". Recorded through the forms' own confirm path (the same
    function the Confirm button calls) the same events must not.
    """

    def _book(self, state: ProgramState) -> dict[str, OptionPosition]:
        """A pre-history book: legs already held enter at the opening mark."""
        add = state.portfolio.add_position
        book: dict[str, OptionPosition] = {}
        book["held"] = add(
            strike_price=4200.0,
            maturity_date=days_from_today(365),
            quantity=10,
            option_type=OptionType.PUT,
        )
        book["long"] = add(
            strike_price=4200.0,
            maturity_date=days_from_today(200),
            quantity=10,
            option_type=OptionType.PUT,
            structure_id=_TAG,
        )
        book["short"] = add(
            strike_price=3800.0,
            maturity_date=days_from_today(200),
            quantity=-10,
            option_type=OptionType.PUT,
            structure_id=_TAG,
        )
        book["expiring"] = add(
            strike_price=3500.0,
            maturity_date=days_from_today(7),
            quantity=2,
            option_type=OptionType.PUT,
        )
        return book

    def _mark_on(self, state: ProgramState, *, days_ago: int) -> None:
        """Take a boundary mark as the program stood *days_ago* days back."""
        state.update_market_conditions(
            valuation_date=program_date() - timedelta(days=days_ago),
        )
        assert state.history is not None
        state.history.append_mark(
            mark_book(
                state.portfolio,
                marked_at=program_now(),
                written_by="test",
                is_opening=days_ago == 7,
            ),
        )

    def test_close_settle_and_a_spread_roll_reconcile(
        self,
        tmp_path: Path,
    ) -> None:
        state = _app(tmp_path).program_state
        book = self._book(state)
        self._mark_on(state, days_ago=7)
        # The week passes: the short-dated lot expires today.
        state.update_market_conditions(valuation_date=program_date())
        state.portfolio.positions[3].option.maturity_date = program_date()

        for form, raw in (
            (design.CLOSE, _close_raw(book["held"])),
            (
                design.SETTLE,
                {
                    "position_id": book["expiring"].position_id,
                    "settlement": 0.0,
                    "fees": 0.0,
                    "date": program_date().date().isoformat(),
                    "note": "",
                },
            ),
            (design.ROLL, _roll_raw(book["long"], book["short"])),
        ):
            _version, status, recorded = design.confirm_trade(
                form,
                raw,
                0,
                state,
            )
            assert recorded, status.children
        self._mark_on(state, days_ago=0)

        history = _history(state).load()
        # Every lot the book holds is explained by the fills recorded.
        assert reconcile_book(history, state.positions_snapshot()) == ()
        section = build_realized_carry_section(history)

        assert section.status is RealizedStatus.MEASURED
        assert section.inception is not None
        assert section.inception.breaks == ()
        assert section.inception.reconcilable
        kinds = [f.kind for f in history.fills]
        assert kinds.count(FillKind.CLOSE) == 3  # one close, two roll legs
        assert kinds.count(FillKind.SETTLE) == 1
        assert kinds.count(FillKind.OPEN) == 2
        assert all(f.fees is not None for f in history.fills)

    def test_the_same_close_through_remove_does_not(
        self,
        tmp_path: Path,
    ) -> None:
        """The contrast the forms exist for: Remove books no cash."""
        state = _app(tmp_path).program_state
        book = self._book(state)
        self._mark_on(state, days_ago=7)
        state.update_market_conditions(valuation_date=program_date())

        index = state.portfolio.positions.index(book["held"])
        design._remove_position_logic(index=index, version=0, state=state)
        self._mark_on(state, days_ago=0)

        section = build_realized_carry_section(_history(state).load())

        assert section.inception is not None
        assert not section.inception.reconcilable
        assert any("DELETE" in reason for reason in section.inception.breaks)
