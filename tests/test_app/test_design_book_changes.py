"""The /design Book changes panel (#262).

Server-side tests of the panel's markup in every state it can be in: empty,
populated, corrupt, with and without a mark, and with a lot the history
cannot explain. The client-side render is covered by
``test_design.py::TestPlanningZoneRendersClientSide``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages.design.planning.book_changes import (
    _render_book_changes_panel_logic,
)
from deltadewa.clock import program_now
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.portfolio.history import CloseReason, OpenOrder, mark_book
from deltadewa.state import ProgramState
from tests.clock_helpers import days_from_today
from tests.test_app.test_design import _collect_text

if TYPE_CHECKING:
    from dash.development.base_component import Component

_EXAMPLE_IPS_YAML = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)


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


def _order(quantity: int = 10, **overrides: object) -> OpenOrder:
    fields: dict[str, object] = {
        "strike_price": 4200.0,
        "maturity_date": days_from_today(365),
        "option_type": OptionType.PUT,
        "quantity": quantity,
        "price_per_share": 50.0,
        "fees": 6.5,
    }
    fields.update(overrides)
    return OpenOrder(**fields)  # type: ignore[arg-type]


def _panel(app: ProgramDashApp) -> Component:
    return _render_book_changes_panel_logic(app=app)


def _text(app: ProgramDashApp) -> str:
    return _collect_text(_panel(app))


def _class_names(node: object) -> list[str]:
    """Every className under *node*, in document order."""
    found: list[str] = []
    cls = getattr(node, "className", None)
    if cls:
        found.append(str(cls))
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            found.extend(_class_names(child))
    elif children is not None and not isinstance(children, str):
        found.extend(_class_names(children))
    return found


class TestEmpty:
    """Nothing recorded, and what the panel says about it."""

    def test_empty_book_says_so_and_how_to_start(self, tmp_path: Path) -> None:
        text = _text(_app(tmp_path))
        assert "No book changes recorded yet." in text
        assert "has not started" in text
        assert "history_cli init" in text

    def test_no_table_when_nothing_is_recorded(self, tmp_path: Path) -> None:
        assert "planning-table" not in _class_names(_panel(_app(tmp_path)))


class TestPopulated:
    """Real trades and edits, through the real ProgramState."""

    def test_trade_rows_show_cash_and_who(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.program_state.open_position(_order(10))
        text = _text(app)
        assert "1 change recorded" in text
        assert "Bought 10 x PUT 4200" in text
        assert "at 50.00, fees 6.50" in text
        # 10 x 50.00 x 100 + 6.50 fees, paid. The sign sits after the "$",
        # the app-wide convention (fmt.currency, test_formatters).
        assert "$-50,006.50" in text
        assert "app" in text  # written_by

    def test_add_position_shows_fees_not_captured(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.program_state.add_position(
            strike_price=4200.0,
            maturity_date=days_from_today(365),
            quantity=10,
            option_type=OptionType.PUT,
            entry_premium=48.5,
        )
        text = _text(app)
        assert "fees not captured" in text
        # Unknown cash is said, not shown as zero.
        assert "not captured" in text
        assert "$0.00" not in text

    def test_edits_show_no_cash(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.program_state.open_position(_order(10))
        app.program_state.update_position(0, quantity=12)
        text = _text(app)
        assert "2 changes recorded" in text
        assert "AMEND" in text
        assert "edited to +12 x PUT 4200" in text

    def test_newest_change_is_listed_first(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.program_state.open_position(_order(10))
        app.program_state.update_position(0, quantity=12)
        text = _text(app)
        assert text.index("AMEND") < text.index("Bought 10")

    def test_a_new_change_appears_on_the_next_render(
        self,
        tmp_path: Path,
    ) -> None:
        """The callback re-renders from the store, so nothing is cached."""
        app = _app(tmp_path)
        first = app.program_state.open_position(_order(10))
        assert "1 change recorded" in _text(app)
        app.program_state.close_position(
            first.position_id,
            contracts=4,
            price_per_share=60.0,
            fees=2.0,
            reason=CloseReason.MONETIZATION,
            confirm=True,
        )
        text = _text(app)
        assert "2 changes recorded" in text
        assert "Sold 4 x PUT 4200" in text
        assert "(monetization)" in text

    def test_window_states_the_total(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from deltadewa.app.pages.design.planning import book_changes

        monkeypatch.setattr(book_changes, "_RECENT_LIMIT", 2)
        app = _app(tmp_path)
        for strike in (4000.0, 4100.0, 4200.0):
            app.program_state.open_position(_order(1, strike_price=strike))
        text = _text(app)
        assert "3 changes recorded; showing the latest 2." in text
        assert "PUT 4200" in text
        assert "PUT 4000" not in text


class TestCorrections:
    """A superseded fill stays visible and is dimmed."""

    def test_superseded_row_is_marked_and_dimmed(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.program_state.add_position(
            strike_price=4200.0,
            maturity_date=days_from_today(365),
            quantity=1,
            option_type=OptionType.PUT,
            entry_premium=10.0,
        )
        store = app.program_state.history
        assert store is not None
        (original,) = store.load().recorded_fills
        store.append_fill(
            dataclasses.replace(
                original,
                event_id="fix",
                fees=0.65,
                supersedes=original.event_id,
                recorded_at=program_now(),
            ),
        )
        panel = _panel(app)
        text = _collect_text(panel)
        assert "OPEN (superseded)" in text
        assert "OPEN (correction)" in text
        assert _class_names(panel).count("plan-row--excluded") == 1


class TestMarksAndReconciliation:
    """The since-last-look count and the lots the history can't explain."""

    def test_since_last_mark_and_explained_lots(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        state = app.program_state
        state.open_position(_order(10))
        assert state.history is not None
        state.history.append_mark(
            mark_book(
                state.portfolio,
                marked_at=program_now(),
                written_by="test",
                is_opening=True,
            ),
        )
        before = _text(app)
        assert "0 since the" in before
        assert "Every lot in the book is explained by the history." in before
        assert "No position history before" in before

        state.update_position(0, quantity=12)
        after = _text(app)
        assert "2 changes recorded, 1 since the" in after
        assert "After last mark" in after

    def test_a_change_that_skipped_the_journal_is_named(
        self,
        tmp_path: Path,
    ) -> None:
        """Mutating the portfolio directly, not via ProgramState, is caught."""
        app = _app(tmp_path)
        state = app.program_state
        state.open_position(_order(10))
        assert state.history is not None
        state.history.append_mark(
            mark_book(
                state.portfolio,
                marked_at=program_now(),
                written_by="test",
                is_opening=True,
            ),
        )
        state.portfolio.add_position(
            strike_price=4000.0,
            maturity_date=days_from_today(365),
            quantity=3,
            option_type=OptionType.PUT,
        )
        text = _text(app)
        assert "Lots the history does not explain:" in text
        assert "the history implies 0 contracts, 3 are held" in text


class TestFailureModes:
    """A broken history degrades this panel and nothing else."""

    def test_corrupt_history_is_reported_not_skipped(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        store = app.program_state.history
        assert store is not None
        store.root.mkdir(parents=True)
        store.events_path.write_text("{broken\n")
        text = _text(app)
        assert "The position history could not be read:" in text
        assert "events.jsonl:1" in text
        assert "Nothing was skipped or repaired" in text

    def test_no_store(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.program_state._history = None  # directly-built state
        assert "no position-history store" in _text(app)

    def test_unexpected_error_is_contained_by_the_panel_guard(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from deltadewa.app.pages.design.planning import book_changes

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated")

        monkeypatch.setattr(book_changes, "build_book_change_log", _boom)
        app = _app(tmp_path)
        app.program_state.open_position(_order(1))
        # The raise is contained and shown on the panel, so a reader can
        # tell this panel broke; it does not escape into the callback.
        assert "Something went wrong" in _text(app)
