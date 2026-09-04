"""Tests for the real /monitor page: agreement, callbacks, and no-IPS.

Follows the ``live_app_url``/``browser``/``page`` fixture pattern from
``conftest.py`` (``werkzeug.serving.make_server`` + Playwright, not
``dash.testing``'s selenium-based fixtures — see that module's docstring
for why). This module needs its own module-scoped fixture rather than the
shared ``live_app_url`` because it needs a *real* IPS config (the shared
fixture deliberately loads a missing path to get ``ips_config=None``) and
needs to hand back ``state``/``app`` handles the shared fixture doesn't
expose.
"""

from __future__ import annotations

import dataclasses
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from dash.development.base_component import Component
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from deltadewa import __version__
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_hedge_value,
    gross_quantity,
    hedge_value,
)
from deltadewa.analysis.hedge_efficiency import EfficiencyVerdict
from deltadewa.analysis.monitor_scenario import ScenarioResult, build_scenario
from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages import monitor
from deltadewa.clock import days_between
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState
from tests.clock_helpers import days_from_today

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Browser, Page

_PAGE_LOAD_TIMEOUT_MS = 10_000
_EXAMPLE_IPS_YAML = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)  # #245: real config/ips.yaml is gitignored; use the tracked example.
_NUMBER_RE = re.compile(r"[+-]?\$[+-]?[\d,]+(?:\.\d+)?")


@dataclass
class MonitorAppHandle:
    """Everything a monitor-page test needs: URL, state, and app handles."""

    url: str
    state: ProgramState
    app: ProgramDashApp
    export_dir: Path


def _parse_dollar_amount(text: str) -> float:
    """Parse a dollar figure from *text*, sign-order-agnostic.

    Handles both ``fmt.currency``'s ``"$-1,234"`` (sign after ``$``) and
    ``fmt.signed_currency``'s ``"-$12,300"``/``"+$45,000"`` (sign before
    ``$``) — a bare digit-only regex would silently drop the sign on the
    latter, since it puts the minus ahead of the dollar sign.
    """
    match = _NUMBER_RE.search(text)
    if match is None:
        msg = f"No dollar figure found in {text!r}"
        raise AssertionError(msg)
    raw = match.group()
    negative = "-" in raw
    digits = raw.replace("$", "").replace("+", "").replace("-", "")
    value = float(digits.replace(",", ""))
    return -value if negative else value


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


def _app_with_spot(
    tmp_path: Path,
    *,
    book_spot: float,
    market_spot: float | None,
) -> ProgramDashApp:
    """Build a minimal /monitor app with a real IPS and a chosen spot pair.

    *market_spot* of ``None`` builds a ``StaticProvider`` carrying no SPX
    entry at all, so ``observe_spot`` degrades to ``UNAVAILABLE`` — the
    same shape a missing cache key produces in the deployed app (#293).
    """
    state = ProgramState.load(
        tmp_path,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    # An empty book defaults to symbol="UNKNOWN" (OptionPortfolio's own
    # default) — a real deployment's imported portfolio YAML sets its own
    # symbol (e.g. examples/portfolios/spx_protective_put.yaml), which is
    # what observe_spot's cache-key lookup keys off. Set it explicitly so
    # market_spot below is actually reachable.
    state.portfolio.symbol = "SPX"
    state.portfolio.spot_price = book_spot
    state.add_position(
        strike_price=book_spot * 0.9,
        maturity_date=days_from_today(180),
        quantity=10,
        option_type=OptionType.PUT,
    )
    spot_prices = {} if market_spot is None else {"SPX": market_spot}
    market_data = StaticProvider(spot_prices=spot_prices, vix=18.0)
    return create_app(
        state=state,
        market_data=market_data,
        ips_config=state.ips_config,
    )


def _app_with_convexity_band(
    tmp_path: Path,
    *,
    band: str,
) -> ProgramDashApp:
    """Build a /monitor app whose IPS convexity band is forced pass/fail.

    Measures the book's *own* crash convexity first, then places the IPS
    band above it (``band="above"`` — the book is under-hedged, forcing a
    FAIL) or straddling it (``band="around"`` — forcing a PASS). Deriving
    the band from the measured value, rather than asserting against the
    IPS example's own 10-20% band, is what keeps this fixture correct
    however Batch 4 (or any future change) moves that band — see
    CLAUDE.md's clock/fixture notes on not pinning a test to a policy
    value that is itself expected to move.
    """
    state = ProgramState.load(
        tmp_path,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state.portfolio.spot_price = 5000.0
    # 5,000 shares against 10 puts keeps carry comfortably within the
    # example IPS's 1% budget (~0.5%) regardless of which way the
    # convexity band is forced below — otherwise a forced-PASS convexity
    # band could still read overall FAIL on the carry row alone.
    state.set_underlying_quantity(5_000.0)
    state.add_position(
        strike_price=4500.0,
        maturity_date=days_from_today(180),
        quantity=10,
        option_type=OptionType.PUT,
    )
    market_data = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    ips_config = state.ips_config
    assert ips_config is not None
    measured_pct = PortfolioAnalyzer(
        state.portfolio,
    ).calculate_crash_convexity_pct(CrashShock.from_ips(ips_config.convexity))
    if band == "above":
        target_min_pct = measured_pct + 5.0
        target_max_pct = measured_pct + 10.0
    else:
        target_min_pct = measured_pct - 5.0
        target_max_pct = measured_pct + 5.0
    forced_ips_config = dataclasses.replace(
        ips_config,
        convexity=dataclasses.replace(
            ips_config.convexity,
            target_min_pct=target_min_pct,
            target_max_pct=target_max_pct,
        ),
    )
    return create_app(
        state=state,
        market_data=market_data,
        ips_config=forced_ips_config,
    )


def _app_with_expired_long_put(tmp_path: Path) -> ProgramDashApp:
    """Build a /monitor app whose book holds one already-expired long put.

    Mirrors ``_app_with_convexity_band``'s carry-budget headroom (5,000
    shares vs. the live put) so the compliance verdict stays legible, plus
    a second long put already past its maturity — the #375 fixture for
    the compliance strip's expired-leg caveat.
    """
    state = ProgramState.load(
        tmp_path,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state.portfolio.spot_price = 5000.0
    state.set_underlying_quantity(5_000.0)
    state.add_position(
        strike_price=4500.0,
        maturity_date=days_from_today(180),
        quantity=10,
        option_type=OptionType.PUT,
    )
    state.portfolio.add_position(
        strike_price=4000.0,
        maturity_date=days_from_today(-5),
        quantity=5,
        option_type=OptionType.PUT,
        # #365: this fixture deliberately wants an already-expired leg.
        reject_expired=False,
    )
    market_data = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    return create_app(
        state=state,
        market_data=market_data,
        ips_config=state.ips_config,
    )


def _assert_renders_cleanly(page: Page, url: str) -> None:
    """Load *url* and assert no client-side error or leaked traceback."""
    js_errors: list[str] = []
    page.on("pageerror", lambda exc: js_errors.append(str(exc)))

    page.goto(url, timeout=_PAGE_LOAD_TIMEOUT_MS)
    page.wait_for_selector("#react-entry-point", timeout=_PAGE_LOAD_TIMEOUT_MS)

    assert js_errors == []
    root_content = page.inner_html("#react-entry-point")
    assert root_content.strip() != ""
    assert "Traceback" not in page.content()


@pytest.fixture(scope="module")
def monitor_app(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[MonitorAppHandle]:
    """Boot a real /monitor app (with a real IPS + a mixed-leg book)."""
    export_dir = tmp_path_factory.mktemp("monitor_app")
    state = ProgramState.load(
        export_dir,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state.portfolio.spot_price = 5000.0
    # Mixed legs: long puts plus a covered call, so the all-legs-vs-
    # long-puts-only distinction between crash_value_curve and
    # compute_crash_convexity is actually exercised.
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
        yield MonitorAppHandle(
            url=f"http://127.0.0.1:{server.server_port}",
            state=state,
            app=app,
            export_dir=export_dir,
        )
    finally:
        server.shutdown()
        thread.join()


@pytest.fixture(scope="module")
def monitor_app_paid_gain(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[MonitorAppHandle]:
    """Boot a real /monitor app whose long put has an entry_premium set.

    ``ProgramState.add_position``/``OptionPortfolio.add_position`` don't
    expose ``entry_premium`` as a kwarg, so — matching the pattern used
    elsewhere in the suite (e.g. ``tests/test_persistence.py``) — it's set
    directly on the position after creation. This gives ``gain_basis`` a
    ``"paid"`` value, exercising the branch ``monitor_app``'s fixture
    (whose long put has no ``entry_premium``, hence always ``"unknown"``)
    cannot reach.
    """
    export_dir = tmp_path_factory.mktemp("monitor_app_paid_gain")
    state = ProgramState.load(
        export_dir,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state.portfolio.spot_price = 5000.0
    state.add_position(
        strike_price=4500.0,
        maturity_date=datetime.now(tz=UTC) + timedelta(days=180),
        quantity=10,
        option_type=OptionType.PUT,
    )
    state.portfolio.positions[-1].entry_premium = 100.0
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
        yield MonitorAppHandle(
            url=f"http://127.0.0.1:{server.server_port}",
            state=state,
            app=app,
            export_dir=export_dir,
        )
    finally:
        server.shutdown()
        thread.join()


@pytest.fixture(scope="module")
def monitor_app_conforming(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[MonitorAppHandle]:
    """Boot a real /monitor app whose book is a conforming protective put.

    Unlike ``monitor_app`` (puts + a short call, no underlying set — off
    -shape by construction), this sets an underlying quantity, so #261's
    shape notice has a quiet case to be tested against too.
    """
    export_dir = tmp_path_factory.mktemp("monitor_app_conforming")
    state = ProgramState.load(
        export_dir,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state.portfolio.spot_price = 5000.0
    state.set_underlying_quantity(1_000.0)
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
        yield MonitorAppHandle(
            url=f"http://127.0.0.1:{server.server_port}",
            state=state,
            app=app,
            export_dir=export_dir,
        )
    finally:
        server.shutdown()
        thread.join()


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    """A headless Chromium instance shared across this module's tests."""
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(headless=True)
        try:
            yield chromium
        finally:
            chromium.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    """A fresh page/tab for each test."""
    browser_page = browser.new_page()
    try:
        yield browser_page
    finally:
        browser_page.close()


class TestMonitorRenders:
    """The real /monitor page must boot and render without error."""

    def test_renders_cleanly(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        _assert_renders_cleanly(page, f"{monitor_app.url}/monitor")


class TestSliderTooltips:
    """Slider values must stay visible while dragging, not just on hover.

    A structural (non-Playwright) check on ``render()``'s own component
    tree — no browser needed to confirm the tooltip config is set.
    """

    def test_spot_and_vol_sliders_report_always_visible(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        layout = monitor.render(monitor_app.app)

        for slider_id in ("spot-slider", "vol-slider"):
            slider = _find_component(layout, slider_id)
            assert slider is not None, f"{slider_id} not found in layout"
            assert slider.tooltip["always_visible"] is True


class TestBasisChip:
    """Main plan mechanism 3: /monitor names its basis, shared with PLANNING."""

    def test_crash_scenario_header_shows_the_basis_chip(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        layout = monitor.render(monitor_app.app)

        assert "basis: crash-skew (IPS anchor)" in str(layout)


class TestProvenancePanel:
    """Batch 3d / #367: the full pricing-input breakdown, on /monitor."""

    def test_provenance_panel_is_present(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        layout = monitor.render(monitor_app.app)

        assert _find_component(layout, "provenance-panel") is not None


class TestComplianceStrip:
    """#298: /monitor's one-line IPS compliance strip.

    Structural checks on ``render()``'s own component tree — a FAIL book
    must not be able to render the page without ``id="compliance-strip"``
    present, per the issue's acceptance criterion, which this asserts
    structurally rather than by pinning a rendered string.
    """

    def test_a_failing_book_cannot_render_monitor_without_the_strip(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_convexity_band(tmp_path, band="above")

        layout = monitor.render(app)

        strip = _find_component(layout, "compliance-strip")
        assert strip is not None
        text = str(strip)
        assert "FAIL" in text
        assert "Crash convexity" in text

    def test_a_passing_book_renders_a_pass_strip(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_convexity_band(tmp_path, band="around")

        layout = monitor.render(app)

        strip = _find_component(layout, "compliance-strip")
        assert strip is not None
        text = str(strip)
        assert "PASS" in text
        assert "FAIL" not in text

    def test_expired_leg_caveat_present_when_book_has_one(
        self,
        tmp_path: Path,
    ) -> None:
        """#375: the strip names an expired long put excluded from convexity."""
        app = _app_with_expired_long_put(tmp_path)

        layout = monitor.render(app)

        strip = _find_component(layout, "compliance-strip")
        assert strip is not None
        text = str(strip)
        assert "Convexity excludes 1 expired leg" in text
        assert "4,000 PUT" in text

    def test_expired_leg_caveat_absent_when_book_has_none(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """The other direction: no caveat when nothing was excluded."""
        layout = monitor.render(monitor_app.app)

        strip = _find_component(layout, "compliance-strip")
        assert strip is not None
        assert "Convexity excludes" not in str(strip)

    def test_strip_is_present_before_the_scenario_explorer(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """The strip must not be scrollable-past before the rest loads."""
        layout = monitor.render(monitor_app.app)
        classes_in_order = [
            getattr(child, "className", None) for child in layout.children
        ]

        assert "compliance-strip" in classes_in_order
        assert "scenario-explorer" in classes_in_order
        assert classes_in_order.index(
            "compliance-strip",
        ) < classes_in_order.index("scenario-explorer")

    def test_dials_never_change_the_compliance_strip(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "#compliance-strip",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        before_strip = page.inner_text("#compliance-strip")
        before_numbers = page.inner_text("#scenario-numbers")

        spot_slider = page.locator('#spot-slider [role="slider"]')
        spot_slider.focus()
        for _ in range(5):
            page.keyboard.press("ArrowLeft")
        page.wait_for_function(
            "(before) => document.getElementById('scenario-numbers')"
            ".innerText !== before",
            arg=before_numbers,
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        assert page.inner_text("#compliance-strip") == before_strip


class TestPanelIsolation:
    """#363: a raise in one panel's analysis calls must not blank the page.

    Structural checks on ``render()``'s own component tree, per the
    issue's acceptance criterion ("a structural test — not a string
    match"): each check monkeypatches one of ``monitor.py``'s own
    module-level names — the same names its panel-builder closures call
    — to raise, then confirms the failing panel's known component ids
    are gone while every other panel's ids are still present.
    """

    def test_scenario_explorer_failure_leaves_other_panels_intact(
        self,
        monkeypatch: pytest.MonkeyPatch,
        monitor_app: MonitorAppHandle,
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> ScenarioResult:
            msg = "synthetic scenario failure"
            raise RuntimeError(msg)

        monkeypatch.setattr(monitor, "build_scenario", _raise)

        layout = monitor.render(monitor_app.app)

        # The failing panel's own components are gone...
        assert _find_component(layout, "spot-slider") is None
        assert _find_component(layout, "payoff-curve") is None
        assert _find_component(layout, "cost-panel") is None
        # ...every other panel is still present...
        assert _find_component(layout, "shape-notice") is not None
        assert _find_component(layout, "compliance-strip") is not None
        assert "Decisions" in str(layout)
        assert "Position detail" in str(layout)
        # ...and the failure is visible on the page, not only in the log.
        assert "Something went wrong" in str(layout)

    def test_decisions_panel_failure_leaves_other_panels_intact(
        self,
        monkeypatch: pytest.MonkeyPatch,
        monitor_app: MonitorAppHandle,
    ) -> None:
        def _raise(*_args: object, **_kwargs: object) -> None:
            msg = "synthetic monetization failure"
            raise RuntimeError(msg)

        monkeypatch.setattr(monitor, "build_monetization_plan", _raise)

        layout = monitor.render(monitor_app.app)

        assert _find_component(layout, "monetization-panel") is None
        assert _find_component(layout, "compliance-strip") is not None
        assert _find_component(layout, "spot-slider") is not None
        assert "Position detail" in str(layout)
        assert "Something went wrong" in str(layout)

    def test_shared_crash_convexity_call_degrades_both_its_panels(
        self,
        monkeypatch: pytest.MonkeyPatch,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """The #362 shape: the crash-convexity call itself raises.

        ``compute_crash_convexity`` (via ``_cost_and_protection``) is
        called independently by both the compliance strip and the
        scenario explorer's cost panel — each inside its own
        ``safe_render`` closure — so *both* degrade here, and correctly
        so: neither panel has a real convexity figure to show. Decisions
        and position detail don't touch this call and stay intact.
        """

        def _raise(*_args: object, **_kwargs: object) -> None:
            msg = "synthetic crash convexity failure"
            raise RuntimeError(msg)

        monkeypatch.setattr(monitor, "compute_crash_convexity", _raise)

        layout = monitor.render(monitor_app.app)

        assert _find_component(layout, "compliance-strip") is None
        assert _find_component(layout, "spot-slider") is None
        assert _find_component(layout, "shape-notice") is not None
        assert "Decisions" in str(layout)
        assert "Position detail" in str(layout)
        assert "Something went wrong" in str(layout)

    def test_shared_call_failing_degrades_only_its_own_panels(
        self,
        monkeypatch: pytest.MonkeyPatch,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """assess_market_environment is called independently by two panels.

        Each panel's own call sits inside its own ``safe_render`` closure
        (#363's isolation), so both the compliance strip and the
        decisions section degrade independently — but the scenario
        explorer, shape notice, and position table, none of which call
        ``assess_market_environment``, are unaffected.
        """

        def _raise(*_args: object, **_kwargs: object) -> None:
            msg = "synthetic market-data failure"
            raise RuntimeError(msg)

        monkeypatch.setattr(monitor, "assess_market_environment", _raise)

        layout = monitor.render(monitor_app.app)

        assert _find_component(layout, "compliance-strip") is None
        assert _find_component(layout, "monetization-panel") is None
        assert _find_component(layout, "shape-notice") is not None
        assert _find_component(layout, "spot-slider") is not None
        assert "Position detail" in str(layout)

    def test_value_error_renders_incomplete_text_not_a_traceback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """A structural ValueError degrades to plain text, per panel_guard."""

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise ValueError("crash skew anchor delta is not bracketed")

        monkeypatch.setattr(monitor, "evaluate_roll_status", _raise)

        layout = monitor.render(monitor_app.app)

        assert "crash skew anchor delta is not bracketed" in str(layout)
        assert "Traceback" not in str(layout)
        assert _find_component(layout, "spot-slider") is not None


class TestExpiredLegDoesNotBreakMonitor:
    """#362 + #363 together: the live-droplet incident, reproduced and fixed.

    An expired leg used to take out the compliance strip, the scenario
    explorer, and the weekly digest with one ``ValueError`` from the
    crash-skew wing solve. #362 fixes the root cause — the wing solve no
    longer raises for a non-positive tenor — so this confirms /monitor
    renders every panel *normally* with an expired leg in the book: not
    merely that a degraded panel is visible (that's ``TestPanelIsolation``
    above), but that no panel needs to degrade at all.
    """

    def test_book_with_an_expired_leg_renders_every_panel(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_spot(tmp_path, book_spot=5000.0, market_spot=5000.0)
        # Mirrors the reported incident's shape: a strike/expiry pair that
        # reads as a stale scratch value, 27 days past its own expiry.
        app.program_state.portfolio.add_position(
            strike_price=234.0,
            maturity_date=days_from_today(-27),
            quantity=3,
            option_type=OptionType.PUT,
            # #365: this fixture deliberately reproduces an expired leg.
            reject_expired=False,
        )

        layout = monitor.render(app)

        assert "Something went wrong" not in str(layout)
        assert _find_component(layout, "compliance-strip") is not None
        assert _find_component(layout, "spot-slider") is not None
        assert "Decisions" in str(layout)
        assert "Position detail" in str(layout)


class TestSpotCrossCheck:
    """#336: /monitor cross-checks the book spot against the observed one.

    Structural checks on ``render()``'s own component tree, matching
    ``TestSliderTooltips``/``TestBasisChip``'s style — no browser needed to
    confirm which sentence a given ``SpotReading`` quality produces.
    """

    def test_book_spot_line_always_present(self, tmp_path: Path) -> None:
        """The hand-entered book spot renders regardless of the feed."""
        app = _app_with_spot(tmp_path, book_spot=5000.0, market_spot=None)

        layout_text = str(monitor.render(app))

        assert "Book SPX spot: $5,000.00" in layout_text

    def test_unavailable_reading_says_so_plainly(
        self,
        tmp_path: Path,
    ) -> None:
        """A missing cache key (the #293 drift mode) reads UNAVAILABLE."""
        app = _app_with_spot(tmp_path, book_spot=5000.0, market_spot=None)

        layout_text = str(monitor.render(app))

        assert "No market spot reading is available" in layout_text
        assert "spot-crosscheck--unavailable" in layout_text

    def test_static_provider_reads_synthetic_not_unavailable(
        self,
        tmp_path: Path,
    ) -> None:
        """StaticProvider's STATIC quality must not collapse to UNAVAILABLE.

        ``Observation.static`` carries a real value with no ``as_of``,
        which is exactly the shape ``_spot_headline`` must not mistake for
        a missing cache entry.
        """
        app = _app_with_spot(
            tmp_path,
            book_spot=5000.0,
            market_spot=5000.0,
        )

        layout_text = str(monitor.render(app))

        assert "SYNTHETIC" in layout_text
        assert "No market spot reading is available" not in layout_text

    def test_divergence_within_threshold_is_not_flagged(
        self,
        tmp_path: Path,
    ) -> None:
        """A 1% divergence, under the 2% default, gets no --diverged class."""
        app = _app_with_spot(tmp_path, book_spot=5000.0, market_spot=5050.0)

        layout_text = str(monitor.render(app))

        assert "+1.0% vs book" in layout_text
        assert "spot-crosscheck--diverged" not in layout_text

    def test_divergence_past_threshold_is_flagged(
        self,
        tmp_path: Path,
    ) -> None:
        """A 5% divergence, past the 2% default, gets the --diverged class."""
        app = _app_with_spot(tmp_path, book_spot=5000.0, market_spot=5250.0)

        layout_text = str(monitor.render(app))

        assert "+5.0% vs book" in layout_text
        assert "spot-crosscheck--diverged" in layout_text

    def test_observed_below_book_reads_negative(self, tmp_path: Path) -> None:
        """A lower observed spot than book renders a signed negative."""
        app = _app_with_spot(tmp_path, book_spot=5000.0, market_spot=4900.0)

        layout_text = str(monitor.render(app))

        assert "-2.0% vs book" in layout_text


class TestAgreement:
    """The rendered hedge value must match crash_hedge_value exactly."""

    def test_hedge_value_shocked_matches_crash_hedge_value(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "#hedge-value-shocked",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        # Visible text is now a 3-s.f. compact figure; the exact value
        # (what used to be the visible inner_text) lives in the ``title``
        # tooltip attribute — see Prompt E decision 1.
        title_text = page.get_attribute("#hedge-value-shocked", "title")
        assert title_text is not None
        displayed_value = _parse_dollar_amount(title_text)

        ips_config = monitor_app.state.ips_config
        assert ips_config is not None
        expected = crash_hedge_value(
            monitor_app.state.portfolio,
            shock=CrashShock.from_ips(ips_config.convexity),
        )

        assert displayed_value == pytest.approx(expected, abs=0.01)


class TestCallbacksFireAndReturnValues:
    """Each dial must actually change what's rendered, not just re-render."""

    def test_vol_slider_reshapes_curve_and_updates_numbers(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector("#payoff-curve", timeout=_PAGE_LOAD_TIMEOUT_MS)

        before_numbers = page.inner_text("#scenario-numbers")
        before_curve = page.evaluate(
            "() => document.querySelector("
            "'#payoff-curve .js-plotly-plot').data[0].y",
        )

        slider = page.locator('#vol-slider [role="slider"]')
        slider.focus()
        for _ in range(5):
            page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "(before) => document.getElementById('scenario-numbers')"
            ".innerText !== before",
            arg=before_numbers,
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        after_numbers = page.inner_text("#scenario-numbers")
        after_curve = page.evaluate(
            "() => document.querySelector("
            "'#payoff-curve .js-plotly-plot').data[0].y",
        )

        assert after_numbers != before_numbers
        assert after_curve != before_curve

    def test_qty_input_changes_curve_not_just_numbers(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """Regression: underlying_loss/net now scale with quantity (item c).

        Before this change the curve only depended on the vol dial (hedge
        value alone doesn't scale with quantity); now net/underlying_loss
        do, so the curve must reshape when only the quantity dial moves.
        """
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector("#payoff-curve", timeout=_PAGE_LOAD_TIMEOUT_MS)

        before_curve = page.evaluate(
            "() => document.querySelector("
            "'#payoff-curve .js-plotly-plot').data[0].y",
        )

        qty_input = page.locator("#qty-input")
        qty_input.fill("500")
        qty_input.press("Tab")
        page.wait_for_function(
            "(before) => JSON.stringify(document.querySelector("
            "'#payoff-curve .js-plotly-plot').data[0].y) !== "
            "JSON.stringify(before)",
            arg=before_curve,
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        after_curve = page.evaluate(
            "() => document.querySelector("
            "'#payoff-curve .js-plotly-plot').data[0].y",
        )

        assert after_curve != before_curve

    def test_spot_slider_updates_scenario_numbers(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector("#payoff-curve", timeout=_PAGE_LOAD_TIMEOUT_MS)

        before = page.inner_text("#scenario-numbers")

        slider = page.locator('#spot-slider [role="slider"]')
        slider.focus()
        for _ in range(5):
            page.keyboard.press("ArrowLeft")
        page.wait_for_function(
            "(before) => document.getElementById('scenario-numbers')"
            ".innerText !== before",
            arg=before,
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        after = page.inner_text("#scenario-numbers")
        assert after != before

    def test_qty_input_updates_scenario_numbers(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector("#payoff-curve", timeout=_PAGE_LOAD_TIMEOUT_MS)

        before = page.inner_text("#scenario-numbers")

        qty_input = page.locator("#qty-input")
        qty_input.fill("500")
        qty_input.press("Tab")
        page.wait_for_function(
            "(before) => document.getElementById('scenario-numbers')"
            ".innerText !== before",
            arg=before,
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        after = page.inner_text("#scenario-numbers")
        assert after != before


class TestCostSection:
    """The dollar annual-carry figure must be correct and dial-invariant."""

    def test_carry_theta_annual_matches_build_scenario(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "#carry-theta-annual",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        # Visible text is now a 3-s.f. compact figure; the exact value
        # lives in the ``title`` tooltip attribute — see Prompt E
        # decision 1.
        title_text = page.get_attribute("#carry-theta-annual", "title")
        assert title_text is not None
        displayed_value = _parse_dollar_amount(title_text)

        ips_config = monitor_app.state.ips_config
        assert ips_config is not None
        result = build_scenario(
            monitor_app.state.portfolio,
            ips_config,
            spot_pct=ips_config.convexity.crash_scenario_pct,
            vol_points=ips_config.convexity.crash_vol_shock,
            quantity=monitor_app.state.portfolio.underlying_quantity,
        )

        # signed_currency rounds to the nearest whole dollar.
        assert displayed_value == pytest.approx(
            result.carry.theta_annual,
            abs=1.0,
        )

    def test_cost_panel_band_bar_matches_within_budget(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector("#cost-panel", timeout=_PAGE_LOAD_TIMEOUT_MS)

        ips_config = monitor_app.state.ips_config
        assert ips_config is not None
        result = build_scenario(
            monitor_app.state.portfolio,
            ips_config,
            spot_pct=ips_config.convexity.crash_scenario_pct,
            vol_points=ips_config.convexity.crash_vol_shock,
            quantity=monitor_app.state.portfolio.underlying_quantity,
        )

        marker_class = page.get_attribute(
            "#cost-panel .band-marker",
            "class",
        )
        assert marker_class is not None
        expected_modifier = (
            "band-marker--within"
            if result.carry.within_budget
            else "band-marker--outside"
        )
        assert expected_modifier in marker_class

    def test_qty_dial_changes_cost_panel_but_not_dollar_carry(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "#carry-theta-annual",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        before_theta = page.inner_text("#carry-theta-annual")
        before_cost_panel = page.inner_text("#cost-panel")

        qty_input = page.locator("#qty-input")
        qty_input.fill("500")
        qty_input.press("Tab")
        page.wait_for_function(
            "(before) => document.getElementById('cost-panel')"
            ".innerText !== before",
            arg=before_cost_panel,
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        after_theta = page.inner_text("#carry-theta-annual")
        after_cost_panel = page.inner_text("#cost-panel")

        # The dollar figure is byte-identical; the percent-of-notional
        # line (part of the same panel) is what actually moved.
        assert after_theta == before_theta
        assert after_cost_panel != before_cost_panel

    def test_spot_and_vol_dials_never_change_dollar_carry(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "#carry-theta-annual",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        before_theta = page.inner_text("#carry-theta-annual")

        before_numbers = page.inner_text("#scenario-numbers")
        spot_slider = page.locator('#spot-slider [role="slider"]')
        spot_slider.focus()
        for _ in range(5):
            page.keyboard.press("ArrowLeft")
        page.wait_for_function(
            "(before) => document.getElementById('scenario-numbers')"
            ".innerText !== before",
            arg=before_numbers,
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )
        assert page.inner_text("#carry-theta-annual") == before_theta

        before_numbers = page.inner_text("#scenario-numbers")
        vol_slider = page.locator('#vol-slider [role="slider"]')
        vol_slider.focus()
        for _ in range(5):
            page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "(before) => document.getElementById('scenario-numbers')"
            ".innerText !== before",
            arg=before_numbers,
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )
        assert page.inner_text("#carry-theta-annual") == before_theta


class TestHedgeEfficiencySentence:
    """Part X #5/#15 on /monitor: one sentence, not a sixth headline.

    Driven by calling ``_efficiency_sentence`` directly rather than through
    a browser — it is a pure function of a ``ScenarioResult``, so a live
    page would only slow down what it can already prove. The one thing that
    genuinely needs the page (that the sentence is *in* the cost panel and
    moves with the dials) is the last test in this class.
    """

    @staticmethod
    def _scenario(
        handle: MonitorAppHandle,
        *,
        spot_pct: float | None = None,
    ) -> ScenarioResult:
        ips_config = handle.state.ips_config
        assert ips_config is not None
        return build_scenario(
            handle.state.portfolio,
            ips_config,
            spot_pct=(
                ips_config.convexity.crash_scenario_pct
                if spot_pct is None
                else spot_pct
            ),
            vol_points=ips_config.convexity.crash_vol_shock,
            quantity=handle.state.portfolio.underlying_quantity,
        )

    @staticmethod
    def _sentence(
        result: ScenarioResult,
        *,
        convexity_pct: float | None = 100.0,
        convexity_target_min_pct: float | None = 0.0,
        vega_sufficiency_pct: float | None = 100.0,
        vega_sufficiency_min_pct: float = 0.0,
    ) -> str:
        """Call ``_efficiency_sentence`` with safely in-band book facts.

        Defaults keep convexity/vega well clear of their floors, so a
        test that isn't exercising the "cheap but too small" combination
        (#304) never accidentally triggers its caveat text. Returns the
        rendered ``<p>``'s text content directly, since it is always a
        single paragraph (the caveat is appended into the same sentence,
        never a second ``<p>`` — see that function's docstring).
        """
        return str(
            monitor._efficiency_sentence(
                result,
                convexity_pct=convexity_pct,
                convexity_target_min_pct=convexity_target_min_pct,
                vega_sufficiency_pct=vega_sufficiency_pct,
                vega_sufficiency_min_pct=vega_sufficiency_min_pct,
            ).children,
        )

    def test_states_the_ratio_and_its_verdict(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        result = self._scenario(monitor_app)
        text = self._sentence(result)

        assert "of hedge payoff" in text
        assert result.efficiency.verdict.value.lower() in text

    def test_names_the_scenario_not_just_the_ratio(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """The figure is scenario-local, so the sentence has to say so.

        Otherwise a reader who has moved the spot dial to -5% reads a much
        smaller ratio as if it were the program's headline efficiency.
        """
        result = self._scenario(monitor_app, spot_pct=-5.0)
        text = self._sentence(result)

        assert "-5.0% scenario" in text

    def test_quotes_the_ips_band_not_a_hardcoded_one(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        result = self._scenario(monitor_app)
        text = self._sentence(result)
        ips_config = monitor_app.state.ips_config
        assert ips_config is not None

        assert (
            f"{ips_config.convexity.efficiency_min_ratio:g}-"
            f"{ips_config.convexity.efficiency_max_ratio:g}x band"
        ) in text

    def test_zero_carry_says_why_rather_than_printing_a_number(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """An undefined ratio must never render as 0.00x or n/a."""
        result = self._scenario(monitor_app)
        no_carry = dataclasses.replace(
            result,
            efficiency=dataclasses.replace(
                result.efficiency,
                ratio=None,
                verdict=None,
            ),
        )

        text = self._sentence(no_carry)

        assert "no denominator" in text
        assert "x band" not in text

    def test_negative_payoff_is_not_dressed_up_as_a_small_ratio(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """A hedge that loses in the crash reads as that, not as "poor"."""
        result = self._scenario(monitor_app)
        losing = dataclasses.replace(
            result,
            efficiency=dataclasses.replace(
                result.efficiency,
                ratio=-0.5,
                crash_payoff=-50_000.0,
                verdict=EfficiencyVerdict.POOR,
            ),
        )

        text = self._sentence(losing)

        assert "loses" in text
        assert "$-" not in text

    def test_below_band_says_below_not_against(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """#304: a POOR reading must say which side of the band it's on."""
        result = self._scenario(monitor_app)
        poor = dataclasses.replace(
            result,
            efficiency=dataclasses.replace(
                result.efficiency,
                ratio=1.0,
                verdict=EfficiencyVerdict.POOR,
                band_min_ratio=3.0,
                band_max_ratio=6.0,
            ),
        )

        text = self._sentence(poor)

        assert "below the IPS 3-6x band" in text
        assert "against" not in text

    def test_in_band_says_within_not_against(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """#304: an ACCEPTABLE reading genuinely is "against" the band."""
        result = self._scenario(monitor_app)
        acceptable = dataclasses.replace(
            result,
            efficiency=dataclasses.replace(
                result.efficiency,
                ratio=4.5,
                verdict=EfficiencyVerdict.ACCEPTABLE,
                band_min_ratio=3.0,
                band_max_ratio=6.0,
            ),
        )

        text = self._sentence(acceptable)

        assert "within the IPS 3-6x band" in text
        assert "against" not in text

    def test_above_band_states_the_multiple_not_against(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """#304's original finding: 20.7 read as "against" a 3-6x band.

        "Against" implies in-band. The sentence must instead say how far
        above the ceiling the reading is.
        """
        result = self._scenario(monitor_app)
        attractive = dataclasses.replace(
            result,
            efficiency=dataclasses.replace(
                result.efficiency,
                ratio=20.69,
                verdict=EfficiencyVerdict.ATTRACTIVE,
                band_min_ratio=3.0,
                band_max_ratio=6.0,
            ),
        )

        text = self._sentence(attractive)

        assert "against" not in text
        assert "3.4x above the IPS 3-6x band's ceiling" in text

    def test_cheap_but_too_small_when_convexity_is_short(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """#304: an extreme ratio from a tiny, under-hedged book."""
        result = self._scenario(monitor_app)
        attractive = dataclasses.replace(
            result,
            efficiency=dataclasses.replace(
                result.efficiency,
                ratio=20.69,
                verdict=EfficiencyVerdict.ATTRACTIVE,
                band_min_ratio=3.0,
                band_max_ratio=6.0,
            ),
        )

        text = self._sentence(
            attractive,
            convexity_pct=8.0,
            convexity_target_min_pct=10.0,
        )

        assert "cheap because the book is small" in text
        assert "crash convexity is below its target band" in text
        assert "Cheap, but too small" in text

    def test_cheap_but_too_small_when_vega_is_short(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        result = self._scenario(monitor_app)
        attractive = dataclasses.replace(
            result,
            efficiency=dataclasses.replace(
                result.efficiency,
                ratio=20.69,
                verdict=EfficiencyVerdict.ATTRACTIVE,
                band_min_ratio=3.0,
                band_max_ratio=6.0,
            ),
        )

        text = self._sentence(
            attractive,
            vega_sufficiency_pct=0.9,
            vega_sufficiency_min_pct=1.5,
        )

        assert "cheap because the book is small" in text
        assert "vega sufficiency is below its floor" in text

    def test_no_caveat_when_attractive_and_everything_in_band(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        result = self._scenario(monitor_app)
        attractive = dataclasses.replace(
            result,
            efficiency=dataclasses.replace(
                result.efficiency,
                ratio=20.69,
                verdict=EfficiencyVerdict.ATTRACTIVE,
                band_min_ratio=3.0,
                band_max_ratio=6.0,
            ),
        )

        text = self._sentence(attractive)

        assert "cheap because the book is small" not in text

    def test_no_caveat_when_short_but_not_attractive(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """The caveat is specific to ATTRACTIVE — POOR is already the flag."""
        result = self._scenario(monitor_app)
        acceptable = dataclasses.replace(
            result,
            efficiency=dataclasses.replace(
                result.efficiency,
                ratio=4.5,
                verdict=EfficiencyVerdict.ACCEPTABLE,
                band_min_ratio=3.0,
                band_max_ratio=6.0,
            ),
        )

        text = self._sentence(
            acceptable,
            convexity_pct=8.0,
            convexity_target_min_pct=10.0,
        )

        assert "cheap because the book is small" not in text

    def test_sentence_is_in_the_cost_panel_and_moves_with_the_spot_dial(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector("#cost-panel", timeout=_PAGE_LOAD_TIMEOUT_MS)

        before = page.inner_text("#cost-panel")
        assert "of hedge payoff" in before

        spot_slider = page.locator('#spot-slider [role="slider"]')
        spot_slider.focus()
        for _ in range(5):
            page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "(before) => document.getElementById('cost-panel')"
            ".innerText !== before",
            arg=before,
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        assert page.inner_text("#cost-panel") != before

    def test_stays_a_sentence_not_a_sixth_headline(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """M2.4's through-line: /monitor must read legibly cold.

        The ratio is a bridge between the cost and payoff sections, not a
        competing headline — so it gets no ``big-number`` and no band bar of
        its own. Pinned because "just make it a gauge" is the natural drift.
        """
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector("#cost-panel", timeout=_PAGE_LOAD_TIMEOUT_MS)

        efficiency_line = page.locator(
            "#cost-panel p", has_text="of hedge payoff"
        )
        assert efficiency_line.count() == 1
        assert efficiency_line.locator(".big-number").count() == 0
        assert efficiency_line.locator(".band-bar").count() == 0
        # The carry bar is the panel's only band bar, before and after.
        assert page.locator("#cost-panel .band-bar").count() == 1


class TestMonetizationUnavailableState:
    """The monetization panel must say "unknown", never a fake "0%"."""

    def test_unknown_gain_basis_shows_explicit_sentence_not_na(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """monitor_app's long put has no entry_premium -> gain_basis is
        "unknown", so the panel must name that explicitly, never "n/a".
        """
        long_puts = [
            p for p in monitor_app.state.portfolio.positions if p.quantity > 0
        ]
        assert long_puts
        assert all(p.entry_premium is None for p in long_puts)

        _assert_renders_cleanly(page, f"{monitor_app.url}/monitor")
        page.wait_for_selector(
            "#monetization-panel",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        panel_text = page.inner_text("#monetization-panel")
        assert "n/a" not in panel_text
        assert "can't be evaluated" in panel_text

    def test_paid_gain_basis_shows_real_percentages(
        self,
        page: Page,
        monitor_app_paid_gain: MonitorAppHandle,
    ) -> None:
        """With entry_premium set, gain_basis is "paid" and real numbers
        (not the unavailable sentence) render.
        """
        long_puts = [
            p
            for p in monitor_app_paid_gain.state.portfolio.positions
            if p.quantity > 0
        ]
        assert long_puts
        assert all(p.entry_premium is not None for p in long_puts)

        _assert_renders_cleanly(page, f"{monitor_app_paid_gain.url}/monitor")
        page.wait_for_selector(
            "#monetization-panel",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        panel_text = page.inner_text("#monetization-panel")
        assert "can't be evaluated" not in panel_text
        assert "Current hedge gain" in panel_text
        assert "%" in panel_text


class TestScenarioLocalGuard:
    """No dial may reach a ProgramState mutator."""

    def test_dials_never_mutate_state_or_write_exports(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        before_dirty = monitor_app.state.dirty
        before_files = set(monitor_app.export_dir.iterdir())

        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector("#payoff-curve", timeout=_PAGE_LOAD_TIMEOUT_MS)

        vol_slider = page.locator('#vol-slider [role="slider"]')
        vol_slider.focus()
        for _ in range(4):
            page.keyboard.press("ArrowRight")

        spot_slider = page.locator('#spot-slider [role="slider"]')
        spot_slider.focus()
        for _ in range(4):
            page.keyboard.press("ArrowLeft")

        qty_input = page.locator("#qty-input")
        qty_input.fill("1234")
        qty_input.press("Tab")

        page.wait_for_timeout(500)

        assert monitor_app.state.dirty == before_dirty
        after_files = set(monitor_app.export_dir.iterdir())
        assert after_files == before_files


class TestCollapsedPositionTable:
    """The position-detail table: collapsed by default, a plain ledger."""

    def test_starts_collapsed(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "details.position-detail",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        assert page.get_attribute("details.position-detail", "open") is None

    def test_expands_on_summary_click(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "details.position-detail summary",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        page.click("details.position-detail summary")

        assert page.get_attribute("details.position-detail", "open") is not None

    def test_row_matches_portfolio_position(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "details.position-detail summary",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )
        page.click("details.position-detail summary")
        page.wait_for_selector(
            ".position-detail-table tbody tr",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        portfolio = monitor_app.state.portfolio
        position = portfolio.positions[0]
        row = page.locator(".position-detail-table tbody tr").first
        cells = row.locator("td")

        assert (
            cells.nth(0).inner_text() == f"{position.option.strike_price:,.0f}"
        )
        assert cells.nth(1).inner_text() == position.option.option_type.value
        assert cells.nth(2).inner_text() == (
            position.option.maturity_date.strftime("%Y-%m-%d")
        )
        # days_between(), not raw subtraction (#267): the fixture's
        # maturity_date carries today's time-of-day, and subtracting it
        # from the midnight valuation_date floors a day short exactly
        # like the bug #182 fixed in the app itself — the panel renders
        # DTE via days_between(), so the test must compute it the same
        # way to avoid a time-of-day-dependent flake.
        expected_dte = days_between(
            portfolio.valuation_date,
            position.option.maturity_date,
        )
        assert cells.nth(3).inner_text() == f"{expected_dte}d"
        assert cells.nth(4).inner_text() == f"{position.quantity:,.0f}"

        expected_value = hedge_value(portfolio, positions=[position])
        title = cells.nth(5).get_attribute("title")
        assert title is not None
        # signed_currency rounds to the nearest whole dollar.
        assert _parse_dollar_amount(title) == pytest.approx(
            expected_value,
            abs=1.0,
        )

    def test_footer_totals_reconcile_with_hedge_value(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """#337: the total row, not a sum of the rendered row strings."""
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "details.position-detail summary",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )
        page.click("details.position-detail summary")
        page.wait_for_selector(
            ".position-detail-table tfoot tr",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        portfolio = monitor_app.state.portfolio
        footer_cells = page.locator(
            ".position-detail-table tfoot tr td",
        )

        # monitor_app's book is long 10 puts and short 5 calls (#334-style
        # mixed leg fixture) -- a real long/short mix, not a coincidental
        # net that would pass even if the sides were silently netted.
        long_contracts, short_contracts = gross_quantity(
            portfolio.positions,
        )
        assert long_contracts == 10
        assert short_contracts == -5
        quantity_text = footer_cells.nth(1).inner_text()
        assert f"L {long_contracts:,.0f}" in quantity_text
        assert f"S {short_contracts:,.0f}" in quantity_text

        expected_total = hedge_value(portfolio)
        title = footer_cells.nth(2).get_attribute("title")
        assert title is not None
        assert _parse_dollar_amount(title) == pytest.approx(
            expected_total,
            abs=1.0,
        )


class TestPageFooter:
    """#359: the version stamp is the page's own last element.

    Previously nested inside scenario_explorer, styled identically to
    the surrounding financial prose — easy to render correctly and still
    be missed by a human scanning the page. Now the true last child of
    the page, after Position detail, in its own footer style.
    """

    def test_footer_is_the_last_top_level_child(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        layout = monitor.render(monitor_app.app)

        last_child = layout.children[-1]
        assert getattr(last_child, "className", None) == "page-footer"
        assert f"Running v{__version__}" in str(last_child)

    def test_footer_visible_regardless_of_position_detail_state(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(".page-footer", timeout=_PAGE_LOAD_TIMEOUT_MS)
        assert page.locator(".page-footer").is_visible()

        page.click("details.position-detail summary")

        assert page.locator(".page-footer").is_visible()


class TestShapeNotice:
    """#261: the shape guard, restored — quiet unless the book is off-shape."""

    def test_non_conforming_book_shows_the_notice(
        self,
        page: Page,
        monitor_app: MonitorAppHandle,
    ) -> None:
        """``monitor_app``'s book has puts but no underlying set."""
        page.goto(f"{monitor_app.url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            ".shape-notice",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        text = page.locator(".shape-notice").inner_text()
        assert "No underlying position to protect" in text

    def test_conforming_book_is_quiet(
        self,
        page: Page,
        monitor_app_conforming: MonitorAppHandle,
    ) -> None:
        page.goto(
            f"{monitor_app_conforming.url}/monitor",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )
        # #react-entry-point is the pre-render mount point — it exists in
        # the raw HTML shell before the pathname callback populates the
        # page, so waiting on it alone races the client-side render (the
        # same trap TestNoIpsRender's comment above documents, and the one
        # the clock-shift-probe memory flags). The notice div is empty
        # here (CSS hides it via .shape-notice:empty), so the default
        # visible-wait would time out — wait for it merely attached
        # instead, which is what "the route callback has actually run"
        # means for a div with no visible content.
        page.wait_for_selector(
            ".shape-notice",
            state="attached",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        # An empty <div> is still in the DOM (a fixed id for the
        # book-version-driven callback on /design; harmless here) — CSS
        # hides it via .shape-notice:empty, so it must not be visible.
        assert page.locator(".shape-notice").count() == 1
        assert not page.locator(".shape-notice").is_visible()
        assert "Portfolio shape:" not in page.content()


class TestNoIpsRender:
    """With no IPS loaded, /monitor must show the no-policy state only."""

    def test_shows_no_ips_message_and_no_dials(
        self,
        page: Page,
        live_app_url: str,
    ) -> None:
        page.goto(f"{live_app_url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        # Wait for the actual rendered message, not just the mount point:
        # #react-entry-point exists in the raw HTML shell before React
        # hydrates, so waiting on it alone races the client-side render
        # (this is what let this test flake under load — see the
        # clock-shift-probe memory).
        page.wait_for_selector(
            ".no-ips-message",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        content = page.content()
        assert "no ips policy" in content.lower()
        assert page.locator("#spot-slider").count() == 0
        assert page.locator("#vol-slider").count() == 0
        assert page.locator("#qty-input").count() == 0
        assert page.locator("#payoff-curve").count() == 0
