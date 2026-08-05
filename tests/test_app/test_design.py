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
from dash import dcc, no_update
from dash.development.base_component import Component
from werkzeug.serving import make_server

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_hedge_value,
    hedge_value,
)
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.analysis.sizing import size_hedge
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


class TestBasisChip:
    """Main plan mechanism 3: one basis chip, shared by /monitor and design."""

    def test_chip_appears_on_every_planning_panel(self, tmp_path: Path) -> None:
        app = _app_with_ips(tmp_path)
        app.program_state.set_underlying_quantity(1_000.0)

        text = str(design.render(app))

        # Zone header + sizing + ladder + roll + monetization.
        assert text.count(design._BASIS_CRASH_SKEW) == 5


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


class TestRollPlanner:
    """Roll: all three per-trigger reasons (G3), not just the summary."""

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


def _add_starter_position(state: ProgramState) -> None:
    """Add the same one-leg book every EXPLORATION test builds against."""
    state.add_position(
        strike_price=4500.0,
        maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
        quantity=10,
        option_type=OptionType.PUT,
    )


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
        # 4 PLANNING panels + 3 EXPLORATION panels share the .panel class.
        assert page.locator(".panel").count() == 7


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
