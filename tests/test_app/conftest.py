"""Fixtures for the app-level smoke suite: a live server + a browser.

``werkzeug.serving.make_server`` is used (rather than ``Dash.run()``)
because it hands back a server object with a clean ``.shutdown()`` — the
fixture can tear the server down instead of leaking a live thread/socket
past the test module. ``dash.testing``'s own browser/runner fixtures need
``selenium`` and ``multiprocess``, neither of which is a project
dependency; only bare ``dash`` and ``playwright`` are, so this drives
Playwright directly.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from deltadewa.app.factory import create_app
from deltadewa.constants import ExerciseStyle
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Browser, Page


@pytest.fixture(scope="module")
def live_app_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Boot the Dash skeleton on a free local port; yield its base URL."""
    exports_dir = tmp_path_factory.mktemp("app_smoke")
    state = ProgramState.load(
        exports_dir,
        ips_path=exports_dir / "does-not-exist-ips.yaml",
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    market_data = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    app = create_app(state=state, market_data=market_data)

    server = make_server("127.0.0.1", 0, app.server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
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
