"""App-level smoke suite: the Dash skeleton boots and both pages render.

Unlike ``test_factory.py`` (Flask-level responses) and ``test_chrome.py``
(pure component-tree inspection), this drives a real headless browser
against a real running server — the only layer that can catch a client-side
render/callback exception or a leaked server-side traceback rendered into
the page.

This is the beginning of the app-level replacement for the notebook-
execution CI step (the ``jupyter nbconvert --execute`` steps in
``ci.yml``) — that step is retired in **M2.6**, not this milestone; the
notebooks still execute and still run in CI today.

Deliberately minimal, per M2.2's own scope: the surfaces don't exist until
M2.4/M2.5, so this checks that nothing errors, not what's on the page.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

_PAGE_LOAD_TIMEOUT_MS = 10_000


def _assert_renders_cleanly(page: Page, url: str) -> None:
    """Load ``url`` and assert no client-side error or leaked traceback."""
    js_errors: list[str] = []
    page.on("pageerror", lambda exc: js_errors.append(str(exc)))

    page.goto(url, timeout=_PAGE_LOAD_TIMEOUT_MS)
    page.wait_for_selector("#react-entry-point", timeout=_PAGE_LOAD_TIMEOUT_MS)

    assert js_errors == []
    root_content = page.inner_html("#react-entry-point")
    assert root_content.strip() != ""
    assert "Traceback" not in page.content()


class TestPagesRenderWithoutError:
    """Both routes must boot, render, and raise nothing client-side."""

    def test_monitor_renders_cleanly(
        self, page: Page, live_app_url: str
    ) -> None:
        _assert_renders_cleanly(page, f"{live_app_url}/monitor")

    def test_design_renders_cleanly(
        self, page: Page, live_app_url: str
    ) -> None:
        _assert_renders_cleanly(page, f"{live_app_url}/design")
