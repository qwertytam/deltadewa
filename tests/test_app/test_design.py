"""Tests for the real /design page: gate, editor, and guarded import/export.

Two tiers. Most tests call the module-level ``_..._logic`` functions
directly — no server or browser needed, since ``design.py`` routes every
mutating callback's real behaviour through one of those, keeping the
``@app.callback``-decorated wrapper a thin ``dash.ctx`` reader (see that
module's docstring). Only what genuinely needs a browser — the native
confirm-dialog gate, and a full client-side render — uses the
``werkzeug.serving.make_server`` + Playwright pattern from
``conftest.py``/``test_monitor.py``, via a function-scoped fixture (unlike
``test_monitor.py``'s module-scoped one: `/design`'s callbacks mutate, so
sharing a book across tests in this module would leak state between them).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from dash import no_update
from dash.development.base_component import Component
from werkzeug.serving import make_server

from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages import design
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.persistence import PortfolioSerializer
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.reporting import PortfolioLogger
from deltadewa.state import ProgramState

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Page

_PAGE_LOAD_TIMEOUT_MS = 10_000
_EXAMPLE_IPS_YAML = Path(__file__).parent.parent.parent / "config" / "ips.yaml"
_MATURITY = datetime(2027, 6, 30, tzinfo=UTC)
_MATURITY_STR = "2027-06-30"


def _app_with_ips(tmp_path: Path) -> ProgramDashApp:
    """Boot a /design app against a real IPS config."""
    state = ProgramState.load(
        tmp_path,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    market_data = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    return create_app(
        state=state,
        market_data=market_data,
        ips_config=state.ips_config,
    )


def _app_without_ips(tmp_path: Path) -> ProgramDashApp:
    """Boot a /design app whose IPS path deliberately doesn't resolve."""
    state = ProgramState.load(
        tmp_path,
        ips_path=tmp_path / "does-not-exist-ips.yaml",
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    market_data = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    return create_app(state=state, market_data=market_data)


def _find_component(node: object, component_id: str) -> Component | None:
    """Recursively find a Dash component by *component_id* in a layout tree."""
    if isinstance(node, Component):
        if getattr(node, "id", None) == component_id:
            return node
        return _find_component(getattr(node, "children", None), component_id)
    if isinstance(node, (list, tuple)):
        for child in node:
            found = _find_component(child, component_id)
            if found is not None:
                return found
    return None


def _write_other_export(tmp_path: Path) -> Path:
    """Write a standalone portfolio export, independent of any ProgramState."""
    portfolio = OptionPortfolio(
        spot_price=200.0,
        volatility=0.25,
        symbol="OTHER",
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=190.0,
        maturity_date=_MATURITY,
        quantity=3,
        option_type=OptionType.CALL,
    )
    serializer = PortfolioSerializer(export_dir=tmp_path)
    return serializer.export_to_json(
        portfolio,
        PortfolioLogger(),
        filename="import_me.json",
    )


def _raise_mid_write(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("simulated crash mid-write")


def _force_dirty_via_failed_autosave(
    state: ProgramState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make one mutation's autosave fail, leaving ``state.dirty`` True.

    Mirrors ``tests/test_state.py``'s identically-named helper — the
    dirty-over-import refusal path is otherwise unreachable in normal
    operation (every mutator autosaves itself immediately), so this is
    how that branch is actually exercised.
    """
    with monkeypatch.context() as patch:
        patch.setattr("deltadewa.persistence.json.dump", _raise_mid_write)
        with pytest.raises(RuntimeError, match="simulated crash"):
            state.add_position(
                strike_price=100.0,
                maturity_date=_MATURITY,
                quantity=1,
                option_type=OptionType.PUT,
            )


class TestPageGate:
    """Page-level IPS gate: the whole page, editor included."""

    def test_render_with_no_ips_shows_gate_only(self, tmp_path: Path) -> None:
        app = _app_without_ips(tmp_path)

        layout = design.render(app)

        assert _find_component(layout, "add-submit") is None
        assert _find_component(layout, "position-table") is None
        assert _find_component(layout, "book-version") is None
        assert "no ips policy" in str(layout).lower()

    def test_register_callbacks_with_no_ips_wires_nothing(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_without_ips(tmp_path)

        assert not any("book-version" in key for key in app.callback_map)


class TestMutationsPersist:
    """Unlike /monitor's dials, /design's mutators are supposed to persist."""

    def test_add_position_persists(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state

        version, _status, *_rest = design._add_position_logic(
            strike=100.0,
            maturity=_MATURITY_STR,
            quantity=5,
            option_type=OptionType.CALL.value,
            exercise_style=ExerciseStyle.EUROPEAN.value,
            entry_premium=None,
            version=0,
            state=state,
        )

        assert version == 1
        assert state.dirty is False
        reloaded = ProgramState.load(
            tmp_path,
            ips_path=_EXAMPLE_IPS_YAML,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        assert len(reloaded.portfolio.positions) == 1
        assert reloaded.portfolio.positions[0].quantity == 5

    def test_remove_position_persists(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.CALL,
        )

        version, _status = design._remove_position_logic(
            index=0,
            version=0,
            state=state,
        )

        assert version == 1
        assert state.portfolio.positions == []
        assert state.dirty is False

    def test_set_underlying_quantity_persists(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state

        version, _status = design._set_underlying_quantity_logic(
            value=500.0,
            version=0,
            state=state,
        )

        assert version == 1
        assert state.portfolio.underlying_quantity == pytest.approx(500.0)
        assert state.dirty is False


class TestExerciseStyleDefault:
    """C2: the add-form's exercise style always sources from the IPS."""

    def test_new_position_carries_ips_exercise_style(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        assert state.ips_config is not None
        ips_style = state.ips_config.pricing.exercise_style

        design._add_position_logic(
            strike=100.0,
            maturity=_MATURITY_STR,
            quantity=1,
            option_type=OptionType.PUT.value,
            exercise_style=ips_style.value,
            entry_premium=None,
            version=0,
            state=state,
        )

        assert state.portfolio.positions[-1].exercise_style == ips_style


class TestGuardMechanism:
    """A refused mutation never bumps book-version; a successful one does."""

    def test_successful_add_bumps_book_version(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)

        version, *_rest = design._add_position_logic(
            strike=100.0,
            maturity=_MATURITY_STR,
            quantity=1,
            option_type=OptionType.CALL.value,
            exercise_style=ExerciseStyle.EUROPEAN.value,
            entry_premium=None,
            version=7,
            state=app.program_state,
        )

        assert version == 8

    def test_forced_failure_does_not_bump_book_version(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        monkeypatch.setattr(state, "add_position", _raise_mid_write)

        version, status, *_rest = design._add_position_logic(
            strike=100.0,
            maturity=_MATURITY_STR,
            quantity=1,
            option_type=OptionType.CALL.value,
            exercise_style=ExerciseStyle.EUROPEAN.value,
            entry_premium=None,
            version=7,
            state=state,
        )

        assert version is no_update
        assert "went wrong" in status.children
        assert state.portfolio.positions == []


class TestImportRefusal:
    """import over dirty state without confirm is refused."""

    def test_import_over_dirty_state_is_refused(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        _force_dirty_via_failed_autosave(state, monkeypatch)
        assert state.dirty is True

        version, status, pending, hidden = design._import_logic(
            confirm=False,
            target=str(tmp_path / "whatever.json"),
            version=3,
            state=state,
        )

        assert version is no_update
        assert "confirm" in status.children.lower()
        assert pending == str(tmp_path / "whatever.json")
        assert hidden is False
        # The one position the forced-failure helper added is still
        # there — the refused import didn't touch the live book.
        assert len(state.portfolio.positions) == 1

    def test_import_with_confirm_succeeds_when_dirty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        _force_dirty_via_failed_autosave(state, monkeypatch)
        import_source = _write_other_export(tmp_path)

        version, _status, pending, hidden = design._import_logic(
            confirm=True,
            target=str(import_source),
            version=3,
            state=state,
        )

        assert version == 4
        assert pending is None
        assert hidden is True
        assert state.portfolio.symbol == "OTHER"
        assert state.dirty is False


@dataclass
class DesignAppHandle:
    """Everything a design-page test needs: URL, state, and app handles."""

    url: str
    state: ProgramState
    app: ProgramDashApp
    export_dir: Path


@pytest.fixture
def design_app(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[DesignAppHandle]:
    """Boot a real /design app (real IPS, one starter position).

    Function-scoped, unlike ``test_monitor.py``'s module-scoped
    ``monitor_app`` — `/design`'s callbacks mutate the shared book, so a
    server shared across every test in this module would leak state
    between them.
    """
    export_dir = tmp_path_factory.mktemp("design_app")
    state = ProgramState.load(
        export_dir,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state.add_position(
        strike_price=4500.0,
        maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
        quantity=10,
        option_type=OptionType.PUT,
    )
    market_data = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    app = create_app(
        state=state,
        market_data=market_data,
        ips_config=state.ips_config,
    )

    server = make_server("127.0.0.1", 0, app.server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield DesignAppHandle(
            url=f"http://127.0.0.1:{server.server_port}",
            state=state,
            app=app,
            export_dir=export_dir,
        )
    finally:
        server.shutdown()
        thread.join()


class TestRemoveConfirmDialog:
    """The one assertion that genuinely needs a browser.

    ``submit_n_clicks`` only increments once the browser's native
    confirm dialog is accepted — a direct Python call can't observe a
    dismissed dialog, so this is what "remove without confirm changes
    nothing" actually tests.
    """

    def test_dismissing_dialog_leaves_book_unchanged(
        self,
        page: Page,
        design_app: DesignAppHandle,
    ) -> None:
        page.on("dialog", lambda dialog: dialog.dismiss())

        page.goto(f"{design_app.url}/design", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            ".position-table",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        before_count = len(design_app.state.portfolio.positions)
        page.click(".btn-remove")
        page.wait_for_timeout(500)

        assert len(design_app.state.portfolio.positions) == before_count
        assert page.locator(".position-table tbody tr").count() == before_count


class TestIpsGateRendersClientSide:
    """With no IPS loaded, /design must show the no-policy state only."""

    def test_no_ips_shows_gate_and_no_editor(
        self,
        page: Page,
        live_app_url: str,
    ) -> None:
        page.goto(f"{live_app_url}/design", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "#react-entry-point",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        content = page.content()
        assert "no ips policy" in content.lower()
        assert page.locator("#add-submit").count() == 0
        assert page.locator("#position-table").count() == 0
