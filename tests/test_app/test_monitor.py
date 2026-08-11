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

from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_hedge_value,
    hedge_value,
)
from deltadewa.analysis.hedge_efficiency import EfficiencyVerdict
from deltadewa.analysis.monitor_scenario import ScenarioResult, build_scenario
from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages import monitor
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState

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

    def test_states_the_ratio_and_its_verdict(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        result = self._scenario(monitor_app)
        text = monitor._efficiency_sentence(result).children

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
        text = monitor._efficiency_sentence(result).children

        assert "-5.0% scenario" in text

    def test_quotes_the_ips_band_not_a_hardcoded_one(
        self,
        monitor_app: MonitorAppHandle,
    ) -> None:
        result = self._scenario(monitor_app)
        text = monitor._efficiency_sentence(result).children
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

        text = monitor._efficiency_sentence(no_carry).children

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

        text = monitor._efficiency_sentence(losing).children

        assert "loses" in text
        assert "$-" not in text

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
        expected_dte = (
            position.option.maturity_date - portfolio.valuation_date
        ).days
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
