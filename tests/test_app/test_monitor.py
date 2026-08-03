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

import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from deltadewa.analysis.crash_repricing import CrashShock, crash_hedge_value
from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Browser, Page

_PAGE_LOAD_TIMEOUT_MS = 10_000
_EXAMPLE_IPS_YAML = Path(__file__).parent.parent.parent / "config" / "ips.yaml"
_NUMBER_RE = re.compile(r"\$?-?[\d,]+(?:\.\d+)?")


@dataclass
class MonitorAppHandle:
    """Everything a monitor-page test needs: URL, state, and app handles."""

    url: str
    state: ProgramState
    app: ProgramDashApp
    export_dir: Path


def _parse_dollar_amount(text: str) -> float:
    """Parse a signed dollar figure like '$1,234,567' or '-$500' from *text*."""
    match = _NUMBER_RE.search(text)
    if match is None:
        msg = f"No dollar figure found in {text!r}"
        raise AssertionError(msg)
    return float(match.group().replace("$", "").replace(",", ""))


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

        displayed_text = page.inner_text("#hedge-value-shocked")
        displayed_value = _parse_dollar_amount(displayed_text)

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


class TestNoIpsRender:
    """With no IPS loaded, /monitor must show the no-policy state only."""

    def test_shows_no_ips_message_and_no_dials(
        self,
        page: Page,
        live_app_url: str,
    ) -> None:
        page.goto(f"{live_app_url}/monitor", timeout=_PAGE_LOAD_TIMEOUT_MS)
        page.wait_for_selector(
            "#react-entry-point",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        content = page.content()
        assert "no ips policy" in content.lower()
        assert page.locator("#spot-slider").count() == 0
        assert page.locator("#vol-slider").count() == 0
        assert page.locator("#qty-input").count() == 0
        assert page.locator("#payoff-curve").count() == 0
