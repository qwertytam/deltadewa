"""Tests for deltadewa.app.factory — app construction and state wiring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from dash import dcc, html
from dash.development.base_component import Component

import deltadewa.app.factory as factory_module
from deltadewa.app.factory import (
    FetchCapableProviderError,
    ProgramDashApp,
    create_app,
)
from deltadewa.app.pages import design, monitor
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import CboeFredProvider, StaticProvider
from deltadewa.state import ProgramState

_MISSING_IPS = Path("does-not-exist-ips.yaml")
_EXAMPLE_IPS_YAML = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)  # #245: real config/ips.yaml is gitignored; use the tracked example.


def _state(tmp_path: Path) -> ProgramState:
    return ProgramState.load(
        tmp_path,
        ips_path=tmp_path / _MISSING_IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )


def _app_with_ips(tmp_path: Path) -> ProgramDashApp:
    """Boot an app against a real IPS config — both pages fully live."""
    state = ProgramState.load(
        tmp_path,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    return create_app(
        state=state,
        market_data=_provider(),
        ips_config=state.ips_config,
    )


def _provider() -> StaticProvider:
    return StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)


def _collect_text(node: object) -> str:
    """Recursively concatenate every string leaf under a component tree.

    Mirrors ``test_design.py``'s/``test_monitor.py``'s identically-named
    helper — kept local rather than shared, matching those modules' own
    per-file duplication of it.
    """
    if isinstance(node, str):
        return node
    if isinstance(node, Component):
        return _collect_text(getattr(node, "children", None))
    if isinstance(node, (list, tuple)):
        return " ".join(_collect_text(child) for child in node)
    return ""


class TestCreateApp:
    """create_app() builds a real Dash app over one shared ProgramState."""

    def test_returns_a_program_dash_app(self, tmp_path: Path) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())

        assert isinstance(app, ProgramDashApp)

    def test_wires_the_same_state_instance(self, tmp_path: Path) -> None:
        state = _state(tmp_path)

        app = create_app(state=state, market_data=_provider())

        assert app.program_state is state

    def test_two_apps_carry_distinct_state(self, tmp_path: Path) -> None:
        first_state = _state(tmp_path / "a")
        second_state = _state(tmp_path / "b")

        first_app = create_app(state=first_state, market_data=_provider())
        second_app = create_app(state=second_state, market_data=_provider())

        assert first_app.program_state is not second_app.program_state

    def test_rejects_a_fetch_capable_provider(self, tmp_path: Path) -> None:
        provider = CboeFredProvider(cache_dir=tmp_path)

        with pytest.raises(FetchCapableProviderError):
            create_app(state=_state(tmp_path), market_data=provider)

    def test_suppresses_callback_exceptions(self, tmp_path: Path) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())

        assert app.config.suppress_callback_exceptions is True


class TestRoutes:
    """Both pages must come up over HTTP without a server-side exception."""

    def test_monitor_route_returns_ok(self, tmp_path: Path) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())
        client = app.server.test_client()

        response = client.get("/monitor")

        assert response.status_code == 200

    def test_design_route_returns_ok(self, tmp_path: Path) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())
        client = app.server.test_client()

        response = client.get("/design")

        assert response.status_code == 200


class TestSharedBookAcrossPages:
    """M2.5 close-out: /design and /monitor read the same live book.

    Both pages' ``render()`` pull from ``app.program_state.portfolio``
    fresh on every call rather than from a page-local copy, so a mutation
    made through /design's editor is structurally guaranteed to be visible
    on /monitor's next render — this pins that guarantee directly, rather
    than trusting the two pages' own separate test suites to imply it.
    """

    def test_position_added_via_design_appears_on_monitor(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state

        # The real /design write path (state.add_position), not a
        # portfolio-internal shortcut — this is what the BOOK zone's
        # add-form callback itself calls.
        state.add_position(
            strike_price=4321.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=7,
            option_type=OptionType.PUT,
        )

        design_text = _collect_text(design.render(app))
        monitor_text = _collect_text(monitor.render(app))

        assert "4,321" in design_text
        assert "4,321" in monitor_text

    def test_entry_premium_flips_monitors_gain_basis_to_paid(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        state = app.program_state

        before_text = _collect_text(monitor.render(app)).lower()
        assert "no entry price is recorded" in before_text

        # entry_premium (Mo3/F2/B0) had no write path before this
        # milestone — this is what unblocks /monitor's monetization
        # panel for a hand-entered book, not just /design's own copy.
        state.add_position(
            strike_price=4500.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
            quantity=10,
            option_type=OptionType.PUT,
            entry_premium=50.0,
        )

        after_text = _collect_text(monitor.render(app)).lower()
        assert "no entry price is recorded" not in after_text
        assert "current hedge gain" in after_text

    def test_underlying_quantity_populates_monitors_offset_ratio(
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

        # Offset ratio is undefined (not zero) at the default
        # underlying_quantity=0.0 — the crash-scenario spot move produces
        # no underlying P&L to offset against.
        before_text = _collect_text(monitor.render(app))
        assert "n/a" in before_text

        # underlying_quantity (Mo7/F3/B0) had no guarded mutator before
        # this milestone — /design's BOOK-zone dial is what reaches it.
        state.set_underlying_quantity(500.0)

        after_layout = monitor.render(app)
        offset_span = _find_offset_ratio_span(after_layout)
        assert offset_span is not None
        assert offset_span != "n/a"


def _find_offset_ratio_span(node: object) -> str | None:
    """Find the offset-ratio big-number's own text, not the whole page's.

    A page-wide ``"n/a" in text`` check would pass even if the offset
    figure itself never changed, as long as some *other* panel happened
    to render "n/a" (e.g. an estimated roll-up cost) — this walks the
    tree for ``_scenario_numbers``'s own ``[label, value]`` pair instead.
    Checks each child's own *exact* collected text against "Offset
    ratio" rather than scanning descendants for the substring: a
    descendant scan would match the whole five-figure wrapper `html.Div`
    on its way down (since one of its five children's own text does
    contain "Offset ratio") and return the wrong sibling's value before
    recursion ever reaches the actual label/value pair.
    """
    if isinstance(node, Component):
        children = getattr(node, "children", None)
        if (
            isinstance(children, list)
            and len(children) == 2
            and _collect_text(children[0]) == "Offset ratio"
        ):
            return _collect_text(children[1])
        found = _find_offset_ratio_span(children)
        if found is not None:
            return found
    elif isinstance(node, (list, tuple)):
        for child in node:
            found = _find_offset_ratio_span(child)
            if found is not None:
                return found
    return None


def _hrefs(node: object) -> list[str]:
    """Every link-like component's ``href`` in *node*'s tree, in order.

    Mirrors ``test_section_nav.py``'s identically-named helper — kept
    local rather than shared, matching this file's own per-file
    duplication of ``_collect_text``.
    """
    hrefs: list[str] = []
    if isinstance(node, (dcc.Link, html.A)):
        href = getattr(node, "href", None)
        if isinstance(href, str):
            hrefs.append(href)
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            hrefs.extend(_hrefs(child))
    elif children is not None:
        hrefs.extend(_hrefs(children))
    return hrefs


class TestCrossPageNav:
    """#323: the shared chrome carries a link between /monitor and /design."""

    def test_both_routes_are_linked_from_the_initial_layout(
        self,
        tmp_path: Path,
    ) -> None:
        """Nav is route-blind chrome, not per-page markup — one instance,
        shared by construction, carries both routes' links regardless of
        which page is ultimately requested.
        """
        app = create_app(state=_state(tmp_path), market_data=_provider())

        hrefs = _hrefs(app.layout())

        assert "/monitor" in hrefs
        assert "/design" in hrefs

    def test_nav_survives_a_failed_provenance_assessment(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """#381's isolation, one layer up: a chrome (banner) failure must
        never take navigation down with it — nav is a sibling of
        safe_chrome's guarded call, not nested inside it (see chrome.py's
        module docstring).
        """

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(
            factory_module,
            "assess_market_environment",
            _raise,
        )
        app = create_app(state=_state(tmp_path), market_data=_provider())

        layout = app.layout()

        # The degraded chrome still mounted (#381's own contract)...
        assert "PROVENANCE UNAVAILABLE" in _collect_text(layout)
        # ...and nav, which has no data dependency at all, is untouched.
        hrefs = _hrefs(layout)
        assert "/monitor" in hrefs
        assert "/design" in hrefs
