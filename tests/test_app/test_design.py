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
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from dash import dcc, no_update
from dash.development.base_component import Component
from werkzeug.serving import make_server

from deltadewa import __version__
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_hedge_value,
    hedge_value,
)
from deltadewa.analysis.market_environment import (
    DataQuality,
    HedgeCostVerdict,
    MarketEnvironment,
    RegimeLabel,
    TermShape,
)
from deltadewa.analysis.position_aging import (
    BUCKET_ORDER,
    ExpiryBoundaries,
    ExpiryBucketLabel,
    expiry_boundaries,
)
from deltadewa.analysis.roll_planner import RollAction, build_roll_plan
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.analysis.sizing import size_hedge
from deltadewa.app import format as fmt
from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages import design
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.persistence import PortfolioSerializer
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.reporting import PortfolioLogger
from deltadewa.state import ProgramState
from tests.clock_helpers import days_from_today

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Page

_PAGE_LOAD_TIMEOUT_MS = 10_000
_EXAMPLE_IPS_YAML = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)  # #245: real config/ips.yaml is gitignored; use the tracked example.
# Seeded off the program clock, not pinned: a fixed literal drifts into
# the past under the clock-shift probe and expires the book (#365 rejects
# an add_position() whose maturity is at/before valuation_date).
_MATURITY = days_from_today(365)
_MATURITY_STR = _MATURITY.strftime("%Y-%m-%d")


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


def _collect_text(node: object) -> str:
    """Recursively concatenate every string leaf under a component tree.

    Used to assert on a PLANNING panel's rendered content without pinning
    to exact markup — a rung's unsolvable reason, a trigger's reason
    string, or a formatted dollar figure just has to appear *somewhere*
    under the returned component.
    """
    if isinstance(node, str):
        return node
    if isinstance(node, Component):
        return _collect_text(getattr(node, "children", None))
    if isinstance(node, (list, tuple)):
        return " ".join(_collect_text(child) for child in node)
    return ""


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


class TestMarkInputsReviewed:
    """Batch 3d / #367: the /design 'Mark pricing inputs reviewed' control."""

    def test_stamps_every_input_and_persists(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.CALL,
        )
        assert state.portfolio.stamps.spot_as_of is None

        version, _status = design._mark_inputs_reviewed_logic(
            version=0,
            state=state,
        )

        assert version == 1
        assert state.portfolio.stamps.spot_as_of is not None
        assert state.portfolio.stamps.risk_free_rate_as_of is not None
        assert state.portfolio.stamps.dividend_yield_as_of is not None
        assert state.portfolio.positions[0].volatility_as_of is not None
        assert state.dirty is False

    def test_reloaded_book_carries_the_stamps(self, tmp_path: Path) -> None:
        """The stamps survive the same autosave/reload round-trip as any
        other mutation.
        """
        app = _app_with_ips(tmp_path)
        state = app.program_state

        design._mark_inputs_reviewed_logic(version=0, state=state)

        reloaded = ProgramState.load(
            tmp_path,
            ips_path=_EXAMPLE_IPS_YAML,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        assert reloaded.portfolio.stamps.spot_as_of is not None

    def test_panel_and_control_are_present_on_the_page(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)

        layout = design.render(app)

        assert _find_component(layout, "plan-provenance-panel") is not None
        confirm = _find_component(layout, "mark-inputs-reviewed-confirm")
        assert confirm is not None


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


class TestAddPositionRejectsExpiredMaturity:
    """#365: the add-form surfaces add_position()'s new expired-maturity
    guard as a status-message error, without clearing the typed fields.
    """

    def test_expired_maturity_produces_an_error_status(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state

        result = design._add_position_logic(
            strike=100.0,
            maturity="2020-01-01",
            quantity=1,
            option_type=OptionType.CALL.value,
            exercise_style=ExerciseStyle.EUROPEAN.value,
            entry_premium=None,
            version=0,
            state=state,
        )

        version, status, *_rest = result
        assert version is no_update
        assert "already-expired" in status.children
        assert state.portfolio.positions == []

    def test_expired_maturity_does_not_clear_the_typed_fields(
        self,
        tmp_path: Path,
    ) -> None:
        """The existing no-clear-on-failure UX (_guarded_mutation) holds."""
        app = _app_with_ips(tmp_path)
        state = app.program_state

        result = design._add_position_logic(
            strike=100.0,
            maturity="2020-01-01",
            quantity=1,
            option_type=OptionType.CALL.value,
            exercise_style=ExerciseStyle.EUROPEAN.value,
            entry_premium=None,
            version=0,
            state=state,
        )

        _version, _status, *form_fields = result
        assert all(field is no_update for field in form_fields)


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


class TestBasisChip:
    """Main plan mechanism 3: one basis chip, shared by /monitor and design."""

    def test_chip_appears_on_every_planning_panel(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        app.program_state.set_underlying_quantity(1_000.0)

        text = str(design.render(app))

        # Zone header + sizing + ladder + roll plan + roll status +
        # monetization.
        assert text.count(design._BASIS_CRASH_SKEW) == 6


class TestShapeNotice:
    """#261: the shape guard, restored — quiet unless the book is off-shape."""

    def test_conforming_book_is_quiet_on_initial_render(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        app.program_state.set_underlying_quantity(1_000.0)
        _add_starter_position(app.program_state)

        layout = design.render(app)

        notice = _find_component(layout, "shape-notice")
        assert notice is not None
        assert notice.children is None

    def test_empty_book_is_quiet_on_initial_render(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)

        layout = design.render(app)

        notice = _find_component(layout, "shape-notice")
        assert notice is not None
        assert notice.children is None

    def test_non_conforming_book_shows_the_notice_on_initial_render(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        # A long put with no underlying set — non-conforming.
        _add_starter_position(app.program_state)

        layout = design.render(app)

        notice = _find_component(layout, "shape-notice")
        assert notice is not None
        assert "No underlying position to protect" in _collect_text(notice)

    def test_book_version_callback_is_wired(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)

        assert any("shape-notice" in key for key in app.callback_map)


class TestSizingPanel:
    """Sizing: rationale + answer, reacts to input, matches the engine."""

    def test_recomputes_on_input_change(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.set_underlying_quantity(1_000.0)
        ips_config = state.ips_config
        assert ips_config is not None

        narrow = design._render_sizing_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            pct_otm=5.0,
            maturity_years=0.5,
            vol_override=None,
        )
        wide = design._render_sizing_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            pct_otm=30.0,
            maturity_years=0.5,
            vol_override=None,
        )

        assert _collect_text(narrow) != _collect_text(wide)

    def test_blank_inputs_show_incomplete_message_not_zeros(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.set_underlying_quantity(1_000.0)
        ips_config = state.ips_config
        assert ips_config is not None

        panel = design._render_sizing_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            pct_otm=None,
            maturity_years=0.5,
            vol_override=None,
        )

        text = _collect_text(panel)
        assert "enter a strike" in text.lower()
        assert "$0" not in text

    def test_no_underlying_position_shows_engine_message_not_traceback(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        ips_config = state.ips_config
        assert ips_config is not None
        assert state.portfolio.underlying_quantity == pytest.approx(0.0)

        panel = design._render_sizing_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            pct_otm=20.0,
            maturity_years=0.5,
            vol_override=None,
        )

        text = _collect_text(panel).lower()
        assert "underlying position" in text
        assert "traceback" not in text

    def test_matches_engine_values_on_a_fixture(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.set_underlying_quantity(1_000.0)
        ips_config = state.ips_config
        assert ips_config is not None

        panel = design._render_sizing_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            pct_otm=20.0,
            maturity_years=0.5,
            vol_override=None,
        )
        expected = size_hedge(
            state.portfolio,
            ips_config,
            candidate_pct_otm=20.0,
            candidate_maturity_years=0.5,
        )

        text = _collect_text(panel)
        assert f"{expected.contracts_needed:,} contracts needed" in text

    def test_intrinsic_floor_shown_when_the_ips_opts_in(
        self,
        tmp_path: Path,
    ) -> None:
        """#273: ``convexity.crash_floor_reported`` true surfaces the floor."""
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.set_underlying_quantity(1_000.0)
        ips_config = state.ips_config
        assert ips_config is not None
        assert ips_config.convexity.crash_floor_reported is True

        panel = design._render_sizing_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            pct_otm=20.0,
            maturity_years=0.5,
            vol_override=None,
        )
        expected = size_hedge(
            state.portfolio,
            ips_config,
            candidate_pct_otm=20.0,
            candidate_maturity_years=0.5,
        )

        floor = fmt.currency(
            expected.per_contract_intrinsic_floor,
            decimals=2,
        )
        assert f"(intrinsic floor {floor})" in _collect_text(panel)

    def test_intrinsic_floor_hidden_when_the_ips_opts_out(
        self,
        tmp_path: Path,
    ) -> None:
        """#273: setting the key false must actually hide the floor.

        The key was inert before this — it had one reader, in the retired
        Jupyter display layer, so the only live surface rendered the floor
        whatever the IPS said.
        """
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.set_underlying_quantity(1_000.0)
        ips_config = state.ips_config
        assert ips_config is not None
        opted_out = replace(
            ips_config,
            convexity=replace(
                ips_config.convexity,
                crash_floor_reported=False,
            ),
        )

        panel = design._render_sizing_panel_logic(
            portfolio=state.portfolio,
            ips_config=opted_out,
            pct_otm=20.0,
            maturity_years=0.5,
            vol_override=None,
        )
        expected = size_hedge(
            state.portfolio,
            opted_out,
            candidate_pct_otm=20.0,
            candidate_maturity_years=0.5,
        )

        text = _collect_text(panel)
        assert "intrinsic floor" not in text
        # Only the floor goes: the rest of the candidate still renders.
        assert f"{expected.contracts_needed:,} contracts needed" in text
        assert fmt.currency(expected.per_contract_payoff, decimals=2) in text


class TestStrikeLadderPanel:
    """Ladder: unsolvable rungs shown explicitly, reacts to input.

    Not "Mi5" — that finding ID already belongs to the unrelated
    ``include_underlying`` scalar/vectorized default (M1.3/M1.4). The
    unsolvable-rungs gap is M1.4's strike-ladder bullet's third clause,
    which was never given its own number in the finding index.
    """

    def test_unsolvable_rung_reason_is_shown(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.set_underlying_quantity(1_000.0)
        ips_config = state.ips_config
        assert ips_config is not None

        panel = design._render_ladder_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            target_deltas_raw="0.10, 0.60",
            maturities_years_raw="0.5",
        )

        text = _collect_text(panel).lower()
        assert "unsolvable" in text
        assert "0.60" in text
        assert "outside the solvable" in text

    def test_malformed_dial_text_shows_incomplete_message(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.set_underlying_quantity(1_000.0)
        ips_config = state.ips_config
        assert ips_config is not None

        panel = design._render_ladder_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            target_deltas_raw="abc",
            maturities_years_raw="0.5",
        )

        assert "comma-separated" in _collect_text(panel).lower()

    def test_recomputes_on_input_change(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.set_underlying_quantity(1_000.0)
        ips_config = state.ips_config
        assert ips_config is not None

        narrow = design._render_ladder_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            target_deltas_raw="0.05",
            maturities_years_raw="0.25",
        )
        wide = design._render_ladder_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            target_deltas_raw="0.10, 0.20",
            maturities_years_raw="0.5, 1.0",
        )

        assert _collect_text(narrow) != _collect_text(wide)


class TestRollStatusTable:
    """Roll status: all three per-trigger reasons (G3), not the summary.

    The evidence table, distinct from the roll *plan* panel above it
    (see :class:`TestRollPlanPanel`).
    """

    def test_all_three_trigger_reasons_appear(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
        )
        ips_config = state.ips_config
        assert ips_config is not None
        expected = evaluate_roll_status(state.portfolio, ips_config)[0]

        panel = design._render_roll_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
        )

        text = _collect_text(panel)
        assert expected.time_trigger.reason in text
        assert expected.convexity_trigger.reason in text
        assert expected.drift_trigger.reason in text

    def test_crash_valuation_matches_engine_on_mixed_leg_book(
        self,
        tmp_path: Path,
    ) -> None:
        """Roll's crash basis == crash_hedge_value, to the cent, mixed book.

        test_crash_single_source.py's existing pin
        (``TestPlanningZoneAgreesWithMonitor``) uses a single-leg (all-put)
        book, so a leg-selection bug (e.g. dropping the short call, or
        mangling its sign) would pass unnoticed -- there's nothing else to
        select. This mirrors test_monitor.py's
        test_hedge_value_shocked_matches_crash_hedge_value on a book with
        both a long put and a short call, so that failure mode is actually
        reachable. ``evaluate_roll_status`` is the one PLANNING-zone
        computation that reprices every leg (not just a candidate put) via
        ``crash_convexity_pct``'s ``crash_hedge_value(portfolio,
        shock=shock)`` call with no ``positions=`` override -- so its
        ``crash_convexity_pct`` is inverted back to a dollar figure and
        checked against an independent ``crash_hedge_value`` call.
        """
        app = _app_with_ips(tmp_path)
        state = app.program_state
        # Nonzero book notional: crash_convexity_pct short-circuits to 0.0
        # on an empty book, which would make the inversion below vacuously
        # true.
        state.set_underlying_quantity(1_000.0)
        state.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
        )
        state.add_position(
            strike_price=5500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=90),
            quantity=-5,
            option_type=OptionType.CALL,
        )
        ips_config = state.ips_config
        assert ips_config is not None

        # Also exercise the actual PLANNING-zone panel on this book -- this
        # is pinning the zone, not just the bare engine call.
        panel = design._render_roll_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
        )
        assert "traceback" not in _collect_text(panel).lower()

        book_notional = abs(
            state.portfolio.underlying_quantity * state.portfolio.spot_price,
        )
        v_today = hedge_value(state.portfolio)
        expected_v_crash = crash_hedge_value(
            state.portfolio,
            shock=CrashShock.from_ips(ips_config.convexity),
        )

        record = evaluate_roll_status(state.portfolio, ips_config)[0]
        implied_v_crash = (
            record.crash_convexity_pct / 100.0 * book_notional + v_today
        )

        assert implied_v_crash == pytest.approx(expected_v_crash, abs=0.01)

    def test_empty_book_shows_no_positions_message(
        self, tmp_path: Path
    ) -> None:
        app = _app_with_ips(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None

        panel = design._render_roll_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

        assert "no positions in the book yet" in _collect_text(panel).lower()


class TestRollPlanPanel:
    """#258 — the decision layer over the roll status table.

    The table says a tranche is triggered; the plan says what to do
    about it, what to roll to, and what that costs. These pin that the
    three things ``build_roll_plan`` adds actually reach the page, and
    that the panel says how it relates to the table beneath it.
    """

    def _app_with_put(
        self,
        tmp_path: Path,
        *,
        strike_price: float = 4500.0,
        days: int = 180,
    ) -> ProgramDashApp:
        app = _app_with_ips(tmp_path)
        app.program_state.set_underlying_quantity(1_000.0)
        app.program_state.add_position(
            strike_price=strike_price,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=days),
            quantity=10,
            option_type=OptionType.PUT,
        )
        return app

    def _panel(self, app: ProgramDashApp) -> Component:
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        return design._render_roll_plan_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    def test_action_target_strike_and_cost_all_render(
        self,
        tmp_path: Path,
    ) -> None:
        """The three things the roll table cannot show."""
        app = self._app_with_put(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        expected = build_roll_plan(app.program_state.portfolio, ips_config)[0]

        text = _collect_text(self._panel(app))

        assert expected.action.value.replace("_", " ") in text
        assert expected.rationale in text
        if expected.target_strike is not None:
            assert f"{expected.target_strike:,.0f}" in text
        if expected.roll_up_cost is not None:
            assert fmt.signed_currency(expected.roll_up_cost) in text

    def test_states_its_relationship_to_the_roll_table(
        self,
        tmp_path: Path,
    ) -> None:
        """Two adjacent verdict tables must not read as one.

        The plan is a layer *over* the status table's grades, not a
        second opinion on them.
        """
        text = _collect_text(self._panel(self._app_with_put(tmp_path)))

        assert "roll status table below" in text

    def test_no_action_is_a_bare_verdict_word(self, tmp_path: Path) -> None:
        """Every row carries its reasoning — the zone's convention."""
        app = self._app_with_put(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None

        text = _collect_text(self._panel(app))

        for record in build_roll_plan(app.program_state.portfolio, ips_config):
            assert record.rationale in text
            assert len(record.rationale) > len(record.action.value)

    def test_delay_row_renders_its_reasoning_and_own_badge(
        self,
        tmp_path: Path,
    ) -> None:
        """DELAY is a recommendation to sit on a fired trigger.

        Unexplained it is indistinguishable from the tool dropping the
        signal, so the row must carry the rationale text. The badge also
        has to be its own class rather than falling back to the roll
        table's HOLD styling — a deferral is not an all-clear. The
        rationale's *content* is pinned in
        ``tests/test_analysis/test_roll_planner.py``; this pins that the
        view renders it.
        """
        app = self._app_with_put(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        base = build_roll_plan(app.program_state.portfolio, ips_config)[0]
        deferred = replace(
            base,
            action=RollAction.DELAY,
            rationale="Roll warranted (ROLL) but deferring: gaining gamma.",
        )

        row = design._roll_plan_row(deferred)
        markup = str(row)

        assert deferred.rationale in _collect_text(row)
        assert "verdict-badge--delay" in markup
        assert "DELAY" in _collect_text(row)

    def test_empty_book_says_no_long_puts(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)

        text = _collect_text(self._panel(app)).lower()

        assert "no long puts in the book yet" in text

    def test_panel_renders_without_error_on_mixed_book(
        self,
        tmp_path: Path,
    ) -> None:
        """A short call in the book must not break the put-only plan."""
        app = self._app_with_put(tmp_path)
        app.program_state.add_position(
            strike_price=5500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=90),
            quantity=-5,
            option_type=OptionType.CALL,
        )

        text = _collect_text(self._panel(app))

        assert "traceback" not in text.lower()


class TestPositionAgingPanel:
    """#259 — per-leg expiry buckets and the expiration calendar.

    Sits beside the roll planner because it reads the same roll-timing IPS
    keys. The assertions below deliberately pin that the *windows* are
    rendered from the IPS rather than from a literal in the view.
    """

    @staticmethod
    def _panel(app: ProgramDashApp) -> Component:
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        return design._render_position_aging_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    def test_empty_book_shows_incomplete_message(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)

        assert "add a position" in _collect_text(self._panel(app)).lower()

    def test_renders_every_bucket_and_the_calendar(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        app.program_state.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
        )

        text = _collect_text(self._panel(app))

        for label in BUCKET_ORDER:
            assert label.value in text
        assert "Expiration calendar" in text
        assert "Theta/day" in text

    def test_windows_come_from_the_ips_not_a_literal(
        self,
        tmp_path: Path,
    ) -> None:
        """The printed windows must track the loaded IPS's own boundaries."""
        app = _app_with_ips(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        app.program_state.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
        )
        boundaries = expiry_boundaries(ips_config.triggers)

        text = _collect_text(self._panel(app))

        assert f"< {boundaries.urgent_days}d" in text
        assert f"> {boundaries.roll_review_days}d" in text

    def test_collapsed_window_reads_as_unreachable_not_inverted(self) -> None:
        """A degenerate-but-legal IPS must not print an inverted range.

        ``expiry_boundaries`` clamps rather than raising, so a
        ``roll_review_buffer`` of 1.0 leaves ROLL REVIEW with no days in it.
        """
        boundaries = ExpiryBoundaries(
            urgent_days=7,
            soon_days=21,
            roll_due_days=270,
            roll_review_days=270,
        )

        text = design._expiry_window_text(
            ExpiryBucketLabel.ROLL_REVIEW,
            boundaries,
        )

        assert text == "none (IPS windows meet)"

    def test_calendar_groups_legs_sharing_an_expiry(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        maturity = datetime.now(tz=UTC) + timedelta(days=180)
        app.program_state.add_position(
            strike_price=4500.0,
            maturity_date=maturity,
            quantity=10,
            option_type=OptionType.PUT,
        )
        app.program_state.add_position(
            strike_price=4200.0,
            maturity_date=maturity,
            quantity=-4,
            option_type=OptionType.PUT,
        )

        text = _collect_text(self._panel(app))

        assert text.count(maturity.strftime("%Y-%m-%d")) == 1
        assert "+6" in text

    def test_recomputes_after_book_edit(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        app.program_state.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
        )

        before = _collect_text(self._panel(app))

        app.program_state.add_position(
            strike_price=4300.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=400),
            quantity=5,
            option_type=OptionType.PUT,
        )

        assert _collect_text(self._panel(app)) != before


class TestMonetizationPanel:
    """Monetization: entry_premium (B0) flips gain_basis; reacts to the book."""

    def test_unknown_gain_basis_shows_explicit_message(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
        )
        ips_config = state.ips_config
        assert ips_config is not None

        panel = design._render_monetization_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            market_env=None,
        )

        assert "no entry price is recorded" in _collect_text(panel).lower()

    def test_entry_premium_flips_to_paid_gain_basis(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
            entry_premium=50.0,
        )
        ips_config = state.ips_config
        assert ips_config is not None

        panel = design._render_monetization_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            market_env=None,
        )

        text = _collect_text(panel).lower()
        assert "no entry price is recorded" not in text
        assert "current hedge gain" in text


def _make_market_env(**overrides: Any) -> MarketEnvironment:
    """A fully-populated LIVE environment, with per-test overrides.

    Mirrors ``tests/test_analysis/test_decision_matrix.py``'s own builder —
    LIVE by default because that is the only quality the decision matrix
    and the entry-timing tree will produce a verdict on, and both branches
    need exercising here.
    """
    defaults: dict[str, Any] = {
        "vix": 14.0,
        "regime_percentile": 12.0,
        "regime_label": RegimeLabel.LOW,
        "skew_index": 128.0,
        "skew_percentile": 0.22,
        "term_structure": {"VIX": 14.0, "VIX3M": 17.0, "VIX6M": 18.0},
        "term_shape": TermShape.CONTANGO,
        "forward_vol_front_3m": 18.2,
        "hedge_cost_verdict": HedgeCostVerdict.CHEAP,
        "data_quality": DataQuality.LIVE,
        "as_of": datetime(2026, 8, 7, tzinfo=UTC),
    }
    return MarketEnvironment(**{**defaults, **overrides})


class TestMarketEnvironmentPanel:
    """Part X #6/#7/#8 plus the verdict they produce, on /design.

    The three readings are exactly what ``decision_matrix`` takes, so the
    panel shows them together with the verdict rather than leaving the
    operator to read the numbers on one surface and the conclusion on
    another (which is how the Dash rebuild lost them).
    """

    @staticmethod
    def _panel(tmp_path: Path, market_env: MarketEnvironment) -> Component:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        state.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
        )
        ips_config = state.ips_config
        assert ips_config is not None
        return design._render_market_env_panel_logic(
            portfolio=state.portfolio,
            ips_config=ips_config,
            market_env=market_env,
        )

    def test_renders_all_three_readings(self, tmp_path: Path) -> None:
        text = _collect_text(self._panel(tmp_path, _make_market_env()))

        assert "Vol regime" in text
        assert "VIX 14.0" in text
        assert "Skew percentile" in text
        assert "Forward variance" in text
        assert "18.2 vol points" in text

    def test_skew_percentile_is_converted_from_its_fraction(
        self,
        tmp_path: Path,
    ) -> None:
        """MarketEnvironment stores 0-1; the IPS band is stated on 0-100.

        Pinned because rendering the raw fraction would show "0th
        percentile" for a 22nd-percentile reading and band it against
        25/75 as if it were deeply cheap — a wrong verdict, not just a
        wrong label.
        """
        env = _make_market_env(skew_percentile=0.22)

        text = _collect_text(self._panel(tmp_path, env))

        assert "22th percentile" in text
        assert "0th percentile" not in text.replace("22th percentile", "")

    def test_forward_variance_carries_no_band(self, tmp_path: Path) -> None:
        """The IPS states no forward-variance band, so none is invented."""
        panel = self._panel(tmp_path, _make_market_env())
        text = _collect_text(panel)

        assert "no IPS band" in text

    def test_renders_the_decision_verdict_and_entry_timing(
        self,
        tmp_path: Path,
    ) -> None:
        text = _collect_text(self._panel(tmp_path, _make_market_env()))

        assert "Decision:" in text
        assert "Entry timing:" in text
        assert "Hedge cost: CHEAP" in text

    def test_static_data_says_so_rather_than_fabricating_a_verdict(
        self,
        tmp_path: Path,
    ) -> None:
        """StaticProvider is the default here and in the smoke suite.

        Both the matrix and the timing tree decline on non-LIVE quality, so
        this is the ordinary path, not an edge case — and the panel has to
        surface why rather than showing a confident-looking verdict built
        on synthetic numbers.
        """
        env = _make_market_env(data_quality=DataQuality.STATIC)

        text = _collect_text(self._panel(tmp_path, env))

        assert "INSUFFICIENT_DATA" in text
        assert "data_quality" in text

    def test_unavailable_readings_are_stated_not_zeroed(
        self,
        tmp_path: Path,
    ) -> None:
        """A failed fetch must read as absence, never as a zero.

        An omitted row reads as "nothing to report", which is the opposite
        of what a provider failure means.
        """
        env = _make_market_env(
            vix=None,
            regime_label=None,
            regime_percentile=None,
            skew_percentile=None,
            skew_index=None,
            forward_vol_front_3m=None,
            hedge_cost_verdict=None,
            data_quality=DataQuality.UNAVAILABLE,
        )

        text = _collect_text(self._panel(tmp_path, env))

        assert text.count("unavailable") >= 3
        assert "Vol regime" in text
        assert "Skew percentile" in text
        assert "Forward variance" in text
        assert "0.0" not in text

    def test_bands_come_from_the_ips_not_a_literal(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        policy = ips_config.market_environment

        text = _collect_text(self._panel(tmp_path, _make_market_env()))

        assert (
            f"IPS band {policy.vol_regime_low * 100:.0f}-"
            f"{policy.vol_regime_high * 100:.0f} VIX points"
        ) in text
        assert (
            f"IPS band {policy.skew_low_pctile:.0f}-"
            f"{policy.skew_high_pctile:.0f}"
        ) in text


class TestHedgeTriggersPanel:
    """Part X #11's other half — the book-level rebalance triggers.

    Until M2.7 ``evaluate_hedge_triggers`` had no product consumer at all,
    so the delta, expiry, theta and gamma triggers M1.3/M1.4 did
    correctness work on were live nowhere.
    """

    @staticmethod
    def _panel(app: ProgramDashApp) -> Component:
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        return design._render_hedge_triggers_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    @staticmethod
    def _hedged_app(tmp_path: Path) -> ProgramDashApp:
        """A book with an equity leg, so every metric is measurable.

        ``_app_with_ips`` starts with no underlying quantity, which makes
        three of the four triggers UNAVAILABLE — correct behaviour, and
        tested below, but not what the reading tests are about.
        """
        app = _app_with_ips(tmp_path)
        app.program_state.portfolio.underlying_quantity = 1_000.0
        _add_starter_position(app.program_state)
        return app

    def test_renders_all_four_triggers(self, tmp_path: Path) -> None:
        text = _collect_text(self._panel(self._hedged_app(tmp_path)))

        assert "Net delta vs target" in text
        assert "Expiry" in text
        assert "Theta cost" in text
        assert "Gamma drift" in text

    def test_each_trigger_shows_its_reasoning(self, tmp_path: Path) -> None:
        """Same treatment as the roll table: never a bare verdict word."""
        app = self._hedged_app(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None

        text = _collect_text(self._panel(app))

        assert (
            f"{ips_config.triggers.target_delta_ratio_pct:.0f}% target" in text
        )
        assert "to the nearest expiry" in text
        assert "of the book per year" in text
        assert "per 1% spot move" in text

    def test_says_it_is_not_the_roll_planner(self, tmp_path: Path) -> None:
        """It sits beside a panel with overlapping vocabulary.

        Roll status judges each tranche; these judge the book. Without the
        distinction stated, two adjacent tables of verdicts read as one.
        """
        text = _collect_text(self._panel(self._hedged_app(tmp_path)))

        assert "distinct from the roll panels" in text

    def test_empty_book_reads_as_unmeasured_not_healthy(
        self,
        tmp_path: Path,
    ) -> None:
        """No underlying means three metrics are unavailable, not OK."""
        app = _app_with_ips(tmp_path)
        app.program_state.portfolio.underlying_quantity = 0.0

        text = _collect_text(self._panel(app))

        assert text.count("UNAVAILABLE") >= 3
        assert "no underlying quantity set" in text

    def test_fired_triggers_produce_a_ranked_action_list(
        self,
        tmp_path: Path,
    ) -> None:
        """A table of statuses with no "so what" is half an answer.

        This fixture's book is deliberately under-hedged (1,000 shares
        against one put), so the delta and theta triggers both fire.
        """
        text = _collect_text(self._panel(self._hedged_app(tmp_path)))

        assert "URGENT" in text
        assert "Rebalance delta" in text

    def test_quiet_book_says_so_rather_than_showing_an_empty_list(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        # An empty book on a zero equity position fires nothing: the panel
        # must state that rather than rendering a table with no conclusion
        # under it.
        text = _collect_text(self._panel(app))

        assert "No action required" in text


class TestDeltaDriftPanel:
    """`Part X #13
    <https://qwertytam.github.io/deltadewa-handbook/0.1/part-10/tier-4-tactical-optional-trading-metrics/#13-delta-drift>`_
    — hedge delta today vs. the handbook's own -5% shock.

    Sits beside the hedge triggers panel: same "does the book need
    rebalancing" question, asked by how fast the hedge itself responds
    rather than by a policy threshold.

    Pinned to handbook version 0.1, because these assertions rest on the shock
    being the handbook's own -5% rather than a value chosen here. Drop the
    ``/0.1/`` segment for the current page.
    """

    @staticmethod
    def _panel(app: ProgramDashApp) -> Component:
        return design._render_delta_drift_panel_logic(
            portfolio=app.program_state.portfolio,
        )

    def test_renders_drift_and_per_leg_rows(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        text = _collect_text(self._panel(app))

        assert "Delta now" in text
        assert "at -5%" in text
        assert "PUT" in text
        assert "4,500" in text  # starter position's strike, formatted

    def test_empty_book_shows_incomplete_message(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)

        text = _collect_text(self._panel(app)).lower()

        assert "at least one option position" in text

    def test_drift_is_negative_for_a_protective_put(
        self,
        tmp_path: Path,
    ) -> None:
        """A long put's delta becomes more negative as spot falls -5%.

        Struck near the book's own spot (unlike ``_add_starter_position``'s
        deep-ITM starter, whose delta is already saturated at -1 and so
        shows zero drift) so the shock actually moves the reading.
        """
        app = _app_with_ips(tmp_path)
        portfolio = app.program_state.portfolio
        portfolio.add_position(
            strike_price=portfolio.spot_price,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
        )

        drift = PortfolioAnalyzer(portfolio).calculate_delta_drift()

        assert drift.drift < 0.0
        assert len(drift.legs) == 1


class TestConvexityCliffPanel:
    """Part X "Time to Convexity Cliff" — Jupyter-only until this panel.

    The last of the four Jupyter health gauges with no Dash surface, and the
    only one of them that was a real loss rather than a recorded decision.
    """

    @staticmethod
    def _panel(app: ProgramDashApp) -> Component:
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        return design._render_convexity_cliff_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )

    @staticmethod
    def _add_put(state: ProgramState, days: int) -> None:
        state.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=days),
            quantity=10,
            option_type=OptionType.PUT,
        )

    def test_renders_runway_and_verdict(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        # 400 DTE against a 180-day region start leaves ~220 days of runway,
        # comfortably past the review line. Expected value read back from the
        # engine rather than pinned, so the assertion survives the
        # clock-shift probe (`make test-clockshift`) and any date-truncation
        # difference between valuation_date and the maturity timestamp.
        self._add_put(app.program_state, days=400)
        expected = PortfolioAnalyzer(
            app.program_state.portfolio,
        ).calculate_convexity_cliff_days(
            cliff_threshold_days=ips_config.convexity.cliff_threshold_days,
        )

        text = _collect_text(self._panel(app))

        assert expected > ips_config.convexity.cliff_review_days
        assert f"{expected:,} days of runway" in text
        assert "OK" in text

    def test_no_long_puts_reads_unavailable_not_the_sentinel(
        self,
        tmp_path: Path,
    ) -> None:
        """The 999 sentinel must never reach the page as a runway.

        An empty book has no convexity to decay; printing "999 days" would
        read as the safest possible book when it is the opposite.
        """
        app = _app_with_ips(tmp_path)

        text = _collect_text(self._panel(app))

        assert "does not apply" in text
        assert "999" not in text

    def test_urgent_inside_the_urgent_line(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        conv = ips_config.convexity
        # Runway of half the urgent line.
        self._add_put(
            app.program_state,
            days=conv.cliff_threshold_days + conv.cliff_urgent_days // 2,
        )

        text = _collect_text(self._panel(app))

        assert "URGENT" in text

    def test_review_between_the_two_lines(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        conv = ips_config.convexity
        midpoint = (conv.cliff_urgent_days + conv.cliff_review_days) // 2
        self._add_put(
            app.program_state,
            days=conv.cliff_threshold_days + midpoint,
        )

        text = _collect_text(self._panel(app))

        assert "REVIEW" in text

    def test_already_inside_the_region_is_not_reported_as_zero_runway(
        self,
        tmp_path: Path,
    ) -> None:
        """The engine floors runway at 0, so "0 days" is ambiguous.

        A put at 120 DTE and one at 30 DTE both compute 0 against a 180-day
        region start; printing "0 days of runway" for both would imply they
        are the same decision.
        """
        app = _app_with_ips(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        self._add_put(
            app.program_state,
            days=ips_config.convexity.cliff_threshold_days // 2,
        )

        text = _collect_text(self._panel(app))

        assert "already inside" in text
        assert "URGENT" in text
        assert "0 days of runway" not in text
        assert "0 days to the cliff" not in text

    def test_states_the_ips_lines_it_graded_against(
        self,
        tmp_path: Path,
    ) -> None:
        """Both lines are policy, so the panel must name them, not hide them."""
        app = _app_with_ips(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        conv = ips_config.convexity
        self._add_put(app.program_state, days=400)

        text = _collect_text(self._panel(app))

        assert f"{conv.cliff_review_days}d review" in text
        assert f"{conv.cliff_urgent_days}d urgent" in text

    def test_region_start_comes_from_policy_not_the_engine_default(
        self,
        tmp_path: Path,
    ) -> None:
        """The reading must move when policy moves.

        ``calculate_convexity_cliff_days`` carries its own 180-day default;
        if the panel let that default stand, editing ips.yaml would silently
        do nothing — the Mo2-class leak this promotion exists to close.
        """
        app = _app_with_ips(tmp_path)
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        self._add_put(app.program_state, days=400)
        analyzer = PortfolioAnalyzer(app.program_state.portfolio)
        shipped_threshold = ips_config.convexity.cliff_threshold_days
        at_policy = analyzer.calculate_convexity_cliff_days(
            cliff_threshold_days=shipped_threshold,
        )
        tightened = replace(ips_config.convexity, cliff_threshold_days=300)

        text = _collect_text(
            design._render_convexity_cliff_panel_logic(
                portfolio=app.program_state.portfolio,
                ips_config=replace(ips_config, convexity=tightened),
            ),
        )

        # A 300-day region start leaves fewer runway days than the shipped
        # threshold by exactly the gap between the two — computed from the
        # shipped value rather than hardcoded, so this doesn't silently pin
        # a stale number the next time the example's cliff_threshold_days
        # changes (as #338 just did, 180 -> 150).
        runway_gap = 300 - shipped_threshold
        assert f"{at_policy - runway_gap:,} days of runway" in text
        assert "300 days to expiry" in text


class TestVegaSufficiency:
    """Part X #4 on /design — the only Tier-1 item the rebuild dropped."""

    @staticmethod
    def _panel(app: ProgramDashApp, **dials: float | None) -> Component:
        ips_config = app.program_state.ips_config
        assert ips_config is not None
        return design._render_sizing_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            pct_otm=dials.get("pct_otm", 20.0),
            maturity_years=dials.get("maturity_years", 0.5),
            vol_override=None,
        )

    def test_renders_beside_the_sized_candidate(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        text = _collect_text(self._panel(app))

        assert "Vega sufficiency" in text
        assert "per +10 vol points" in text

    def test_bands_against_the_ips_not_dashboard_yaml(
        self,
        tmp_path: Path,
    ) -> None:
        """The band is a mandate question, so it must come from ips.yaml.

        dashboard.yaml used to carry a vega_sufficiency gauge for the
        Jupyter surface (both retired in #279); reading policy from a
        presentation file would recreate the Mo2 leak M1.4 closed.
        """
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)
        ips_config = app.program_state.ips_config
        assert ips_config is not None

        text = _collect_text(self._panel(app))

        assert (
            f"{ips_config.vega.sufficiency_min_pct:.1f}%-"
            f"{ips_config.vega.sufficiency_max_pct:.1f}%"
        ) in text

    def test_names_its_denominator(self, tmp_path: Path) -> None:
        """The metric divides by options *plus* underlying, not the book.

        On a tail hedge the equity leg dominates that denominator, so a
        reader assuming the option book alone would be out by orders of
        magnitude.
        """
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        text = _collect_text(self._panel(app))

        assert "options plus underlying" in text

    def test_says_it_describes_the_book_not_the_candidate(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        text = _collect_text(self._panel(app))

        assert "not the candidate sized above" in text

    def test_survives_an_unfinished_dial(self, tmp_path: Path) -> None:
        """An incomplete candidate must not take #4 off the page.

        The reading depends on neither dial, so losing it with the
        candidate would re-open the regression this commit closes.
        """
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        text = _collect_text(self._panel(app, pct_otm=None))

        assert "Enter a strike" in text
        assert "Vega sufficiency" in text

    def test_survives_a_book_with_no_underlying(
        self,
        tmp_path: Path,
    ) -> None:
        """size_hedge raises without an underlying; this reading doesn't."""
        app = _app_with_ips(tmp_path)
        app.program_state.portfolio.underlying_quantity = 0.0
        _add_starter_position(app.program_state)

        text = _collect_text(self._panel(app))

        assert "Vega sufficiency" in text


class TestNetDeltaReadout:
    """Part X #10's scalar, restored beside the underlying quantity."""

    def test_renders_with_the_underlying_quantity(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        readout = design._net_delta_readout(app.program_state.portfolio)
        text = _collect_text(readout)

        assert "Net delta" in text
        assert (
            f"{app.program_state.portfolio.underlying_quantity:,.0f} shares"
            in text
        )

    def test_moves_when_the_book_changes(self, tmp_path: Path) -> None:
        """It has to track edits, or it silently goes stale after an add."""
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)
        before = _collect_text(
            design._net_delta_readout(app.program_state.portfolio),
        )

        app.program_state.add_position(
            strike_price=4000.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=365),
            quantity=40,
            option_type=OptionType.PUT,
        )
        after = _collect_text(
            design._net_delta_readout(app.program_state.portfolio),
        )

        assert after != before


def _add_starter_position(state: ProgramState) -> None:
    """Add the same one-leg book every EXPLORATION test builds against."""
    state.add_position(
        strike_price=4500.0,
        maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
        quantity=10,
        option_type=OptionType.PUT,
    )


class TestVolatilityProfilePanel:
    """#260 — the book's volatility profile the EXPLORATION grids scale.

    Structural, like the vega term exposure panel, but (unlike it) there
    is no meaningful all-zero reading for an empty book, so it gates the
    same way spot/vol, time/price, and MC do.
    """

    @staticmethod
    def _panel(app: ProgramDashApp) -> Component:
        return design._render_volatility_profile_panel_logic(
            portfolio=app.program_state.portfolio,
        )

    def test_empty_book_shows_incomplete_message(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)

        assert "add a position" in _collect_text(self._panel(app)).lower()

    def test_renders_average_range_and_per_leg_skew(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        portfolio = app.program_state.portfolio
        portfolio.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
            volatility=0.30,
        )
        portfolio.add_position(
            strike_price=4700.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=5,
            option_type=OptionType.CALL,
        )

        text = _collect_text(self._panel(app))

        assert "Vega-weighted average" in text
        assert "% of avg" in text
        assert "(custom)" in text
        assert "PUT 4,500" in text
        assert "CALL 4,700" in text

    def test_recomputes_after_book_edit(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        app.program_state.portfolio.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
            volatility=0.30,
        )

        before = _collect_text(self._panel(app))

        app.program_state.portfolio.add_position(
            strike_price=4700.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=5,
            option_type=OptionType.CALL,
            volatility=0.18,
        )

        after = _collect_text(self._panel(app))

        assert before != after
        assert "CALL 4,700" in after


class TestSpotVolPanel:
    """The spot x vol heatmap panel: proportional-vol basis, reactive."""

    def test_empty_book_shows_incomplete_message(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)

        panel = design._render_spot_vol_panel_logic(
            portfolio=app.program_state.portfolio,
            cache=app.scenario_cache,
            spot_pct=50.0,
            vol_pct=50.0,
            resolution=11,
            days_forward=0,
            metric="pnl",
        )

        assert "add a position" in _collect_text(panel).lower()

    def test_blank_dial_shows_incomplete_not_zeros(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        panel = design._render_spot_vol_panel_logic(
            portfolio=app.program_state.portfolio,
            cache=app.scenario_cache,
            spot_pct=None,
            vol_pct=50.0,
            resolution=11,
            days_forward=0,
            metric="pnl",
        )

        text = _collect_text(panel).lower()
        assert "required" in text

    def test_out_of_range_percent_renders_message_not_traceback(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        panel = design._render_spot_vol_panel_logic(
            portfolio=app.program_state.portfolio,
            cache=app.scenario_cache,
            spot_pct=250.0,  # -> 2.5 as a fraction, rejected by B0's guard
            vol_pct=50.0,
            resolution=11,
            days_forward=0,
            metric="pnl",
        )

        text = _collect_text(panel)
        assert "Traceback" not in text
        assert "fraction" in text.lower()

    def test_recomputes_on_metric_change(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        def _panel(metric: str) -> Component:
            return design._render_spot_vol_panel_logic(
                portfolio=app.program_state.portfolio,
                cache=app.scenario_cache,
                spot_pct=50.0,
                vol_pct=50.0,
                resolution=11,
                days_forward=0,
                metric=metric,
            )

        pnl_panel = _panel("pnl")
        vega_panel = _panel("vega")

        assert isinstance(pnl_panel, dcc.Graph)
        assert isinstance(vega_panel, dcc.Graph)
        assert pnl_panel.figure != vega_panel.figure


class TestTimePricePanel:
    """The time x price heatmap panel: cell annotations, reactive."""

    def test_empty_book_shows_incomplete_message(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)

        panel = design._render_time_price_panel_logic(
            portfolio=app.program_state.portfolio,
            cache=app.scenario_cache,
            spot_pct=50.0,
            num_time_steps=10,
            num_price_steps=13,
            metric="pnl",
        )

        assert "add a position" in _collect_text(panel).lower()

    def test_malformed_dial_shows_incomplete_not_zeros(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        panel = design._render_time_price_panel_logic(
            portfolio=app.program_state.portfolio,
            cache=app.scenario_cache,
            spot_pct=50.0,
            num_time_steps=None,
            num_price_steps=13,
            metric="pnl",
        )

        assert "required" in _collect_text(panel).lower()

    def test_recomputes_on_step_count_change(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        def _panel(num_price_steps: int) -> Component:
            return design._render_time_price_panel_logic(
                portfolio=app.program_state.portfolio,
                cache=app.scenario_cache,
                spot_pct=50.0,
                num_time_steps=10,
                num_price_steps=num_price_steps,
                metric="pnl",
            )

        narrow = _panel(5)
        wide = _panel(13)

        assert isinstance(narrow, dcc.Graph)
        assert isinstance(wide, dcc.Graph)
        assert narrow.figure != wide.figure


class TestMcPanel:
    """The Monte Carlo distribution panel: scenario-local (B0 F6)."""

    def test_empty_book_shows_incomplete_message(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)

        panel = design._render_mc_panel_logic(
            portfolio=app.program_state.portfolio,
            num_paths=1_000,
            horizon_days=None,
            expected_return_pct=None,
            seed=42,
        )

        assert "add a position" in _collect_text(panel).lower()

    def test_renders_graph_and_stats(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        panel = design._render_mc_panel_logic(
            portfolio=app.program_state.portfolio,
            num_paths=2_000,
            horizon_days=None,
            expected_return_pct=None,
            seed=42,
        )

        text = _collect_text(panel).lower()
        assert "simulations" in text
        assert "probability of profit" in text
        assert "risk-neutral" in text


class TestVegaTermPanel:
    """Part X §14 — vega bucketed by maturity, a structural EXPLORATION view.

    Unlike the other EXPLORATION panels it prices nothing — it reads
    today's book Greeks — so an empty book is a real all-zero reading, not
    an incomplete-inputs message.
    """

    @staticmethod
    def _panel(app: ProgramDashApp) -> Component:
        return design._render_vega_term_panel_logic(
            portfolio=app.program_state.portfolio,
        )

    def test_renders_bucketed_vega_for_multi_maturity_book(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        portfolio = app.program_state.portfolio
        portfolio.add_position(
            strike_price=portfolio.spot_price,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=5),
            quantity=1,
            option_type=OptionType.PUT,
        )
        portfolio.add_position(
            strike_price=portfolio.spot_price,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=200),
            quantity=1,
            option_type=OptionType.PUT,
        )

        text = _collect_text(self._panel(app))

        assert "Total vega" in text
        assert "0-7 days (Weekly)" in text
        assert "90+ days (Long-term)" in text

    def test_empty_book_renders_zeros_not_a_raise(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)

        text = _collect_text(self._panel(app))

        assert "Total vega 0.0" in text
        assert "traceback" not in text.lower()


class TestMonteCarloContainment:
    """The MC panel never touches the shared cache or autosave (B0 F6)."""

    def test_exercising_dials_leaves_state_and_cache_untouched(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state
        _add_starter_position(state)
        portfolio = state.portfolio

        before_dirty = state.dirty
        before_files = set(tmp_path.iterdir())
        before_cached = portfolio.monte_carlo_results

        for paths, horizon, expected_return, seed in (
            (1_000, None, None, 42),
            (2_000, 30, None, 7),
            (1_500, 60, 8.0, None),
        ):
            design._render_mc_panel_logic(
                portfolio=portfolio,
                num_paths=paths,
                horizon_days=horizon,
                expected_return_pct=expected_return,
                seed=seed,
            )

        assert state.dirty == before_dirty
        assert set(tmp_path.iterdir()) == before_files
        assert portfolio.monte_carlo_results == before_cached


class TestScenarioCacheReuse:
    """The shared ScenarioGridCache hits on repeat dials, misses on resize.

    Pins the M2.1 cache-key fix directly: a spot/vol grid keys on
    resolution (via the array contents), so a "resize" must miss.
    """

    def test_hits_on_unchanged_dials_misses_after_resize(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)
        portfolio = app.program_state.portfolio

        call_count = {"n": 0}
        original = PortfolioAnalyzer.scenario_grid_spot_vol

        def _counting_scenario_grid_spot_vol(
            self: PortfolioAnalyzer,
            *args: object,
            **kwargs: object,
        ) -> object:
            call_count["n"] += 1
            return original(self, *args, **kwargs)

        monkeypatch.setattr(
            PortfolioAnalyzer,
            "scenario_grid_spot_vol",
            _counting_scenario_grid_spot_vol,
        )

        def _render(resolution: int) -> None:
            design._render_spot_vol_panel_logic(
                portfolio=portfolio,
                cache=app.scenario_cache,
                spot_pct=50.0,
                vol_pct=50.0,
                resolution=resolution,
                days_forward=0,
                metric="pnl",
            )

        _render(11)
        assert call_count["n"] == 1

        _render(11)  # unchanged book, unchanged dials -> cache hit
        assert call_count["n"] == 1

        _render(13)  # a resize -> cache miss
        assert call_count["n"] == 2


class TestExplorationBasisLabelling:
    """The zone header, boundary sentence, and /monitor link are present."""

    def test_zone_states_its_basis_and_links_to_monitor(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        _add_starter_position(app.program_state)

        layout = design.render(app)
        exploration = _find_component(layout, "explore-spotvol-panel")
        assert exploration is not None

        text = _collect_text(layout)
        assert "basis: proportional vol" in text.lower()
        assert "different questions" in text.lower()
        assert "see the policy crash number on /monitor" in text.lower()


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


class TestPlanningZoneRendersClientSide:
    """The PLANNING zone must render with no console error or traceback.

    Mirrors ``test_monitor.py``'s ``TestMonitorRenders.test_renders_cleanly``
    — a green code gate doesn't imply the live page renders.
    """

    def test_planning_zone_renders_cleanly(
        self,
        page: Page,
        design_app: DesignAppHandle,
    ) -> None:
        js_errors: list[str] = []
        page.on("pageerror", lambda exc: js_errors.append(str(exc)))

        page.goto(f"{design_app.url}/design", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(".zone-planning", timeout=_PAGE_LOAD_TIMEOUT_MS)

        assert js_errors == []
        assert "Traceback" not in page.content()
        # 11 PLANNING panels + 5 EXPLORATION panels share the .panel class
        # (Batch 3d added the provenance panel, #367/#368). A count, not a
        # list, so a panel disappearing fails loudly; update it when a
        # panel is deliberately added or removed.
        assert page.locator(".panel").count() == 16
        # Named explicitly because the count alone can't tell a lost panel
        # from a renamed one, and this panel closed a real regression.
        assert page.locator("#plan-convexity-cliff-panel").count() == 1
        # #258 split the roll plan (the decision) from the roll status
        # table (the evidence). Both must be present and distinct — the
        # count alone would be satisfied by either one twice.
        assert page.locator("#plan-roll-plan-panel").count() == 1
        assert page.locator("#plan-roll-panel").count() == 1


class TestExplorationZoneRendersClientSide:
    """The EXPLORATION zone must render with no console error or traceback.

    Mirrors ``TestPlanningZoneRendersClientSide`` above — a green code
    gate doesn't imply the live page (and its 3 Plotly graphs) renders.
    """

    def test_exploration_zone_renders_cleanly(
        self,
        page: Page,
        design_app: DesignAppHandle,
    ) -> None:
        js_errors: list[str] = []
        page.on("pageerror", lambda exc: js_errors.append(str(exc)))

        page.goto(f"{design_app.url}/design", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            ".zone-exploration",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )
        page.wait_for_selector(
            "#explore-mc-panel .js-plotly-plot",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        assert js_errors == []
        assert "Traceback" not in page.content()
        assert page.locator(".zone-exploration .js-plotly-plot").count() == 3


class TestPageFooter:
    """#359, applied here to match: the version stamp is the page's own
    last element.

    Previously nested inside the EXPLORATION zone, after the vega term
    exposure panel, styled identically to the surrounding financial
    prose. Now the true last child of the page, after every zone, in
    the same ``.page-footer`` style /monitor uses.
    """

    def test_footer_is_the_last_top_level_child(
        self,
        design_app: DesignAppHandle,
    ) -> None:
        layout = design.render(design_app.app)

        last_child = layout.children[-1]
        assert getattr(last_child, "className", None) == "page-footer"
        assert f"Running v{__version__}" in str(last_child)

    def test_footer_visible_on_page_load(
        self,
        page: Page,
        design_app: DesignAppHandle,
    ) -> None:
        page.goto(f"{design_app.url}/design", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(".page-footer", timeout=_PAGE_LOAD_TIMEOUT_MS)
        assert page.locator(".page-footer").is_visible()


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
