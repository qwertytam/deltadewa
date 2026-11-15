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

Deliberately minimal for the no-IPS skeleton, per M2.2's own scope: it checks
that nothing errors, not what's on the page. The IPS-backed app (#476) is
checked for what is on the page, because the roll surfaces are the ones that
read a leg's action, and a smoke suite that boots without an IPS never renders
them: it cannot tell a working roll plan from one that raises.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deltadewa.analysis.roll_planner import leg_action_label
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.constants import CALENDAR_DAYS_PER_MONTH
from deltadewa.ips_config import load_ips_config
from deltadewa.state import ProgramState

from .conftest import EXAMPLE_IPS
from .roll_book import (
    LEGS,
    SPOT,
    expected_label,
    seed_every_roll_action,
)

if TYPE_CHECKING:
    from pathlib import Path

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


def _expected_labels() -> dict[int, str | None]:
    """Each seeded strike's expected action label, from the example IPS."""
    triggers = load_ips_config(EXAMPLE_IPS).triggers
    window = int(triggers.roll_at_months_remaining * CALENDAR_DAYS_PER_MONTH)
    return {
        int(leg.strike): expected_label(leg, roll_window_days=window)
        for leg in LEGS
    }


class TestTheSmokeBookCoversEveryAction:
    """The seeded book really does produce the five actions (no browser).

    The browser tests below read the rendered page against this book. If the
    example IPS moves and a leg slides onto another action, this fails first
    and says which one, rather than the browser tests failing on text.
    """

    def test_every_leg_lands_on_its_action(self, tmp_path: Path) -> None:
        state = ProgramState.load(
            tmp_path,
            ips_path=EXAMPLE_IPS,
            examples_dir=tmp_path / "examples",
        )
        assert state.ips_config is not None
        seed_every_roll_action(state)

        records = evaluate_roll_status(state.portfolio, state.ips_config)
        actual = {
            int(r.position.option.strike_price): leg_action_label(
                r,
                ips_triggers=state.ips_config.triggers,
            )
            for r in records
        }

        assert actual == _expected_labels()

    def test_the_book_sits_inside_the_convexity_band(
        self,
        tmp_path: Path,
    ) -> None:
        """DELAY and CHECKED both need convexity in band; so does this."""
        state = ProgramState.load(
            tmp_path,
            ips_path=EXAMPLE_IPS,
            examples_dir=tmp_path / "examples",
        )
        assert state.ips_config is not None
        seed_every_roll_action(state)

        records = evaluate_roll_status(state.portfolio, state.ips_config)

        assert {r.convexity.grade.value for r in records} == {"WITHIN"}
        assert state.portfolio.spot_price == SPOT


class TestRollSurfacesRenderInTheBrowser:
    """With an IPS, the roll surfaces render and print every action (#476)."""

    def test_monitor_decisions_panel_prints_each_action(
        self,
        page: Page,
        live_app_with_ips_url: str,
    ) -> None:
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(
            f"{live_app_with_ips_url}/monitor",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )
        page.wait_for_selector(".decision-row", timeout=_PAGE_LOAD_TIMEOUT_MS)

        printed = page.locator(".decision-action").all_inner_texts()
        rows = page.locator(".decision-row").all_inner_texts()

        wanted = sorted(
            label for label in _expected_labels().values() if label is not None
        )
        assert sorted(printed) == wanted
        # One row per leg, and the HOLD leg prints no action beside it.
        assert len(rows) == len(LEGS)
        assert errors == []
        assert "Traceback" not in page.content()

    def test_design_roll_plan_prints_each_action(
        self,
        page: Page,
        live_app_with_ips_url: str,
    ) -> None:
        page.goto(
            f"{live_app_with_ips_url}/design",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )
        page.wait_for_selector(
            "#plan-roll-plan-panel .verdict-badge",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        panel = page.locator("#plan-roll-plan-panel")
        badges = panel.locator(".verdict-badge").all_inner_texts()

        # The plan prints HOLD for a leg with no trigger; /monitor and the
        # status table print nothing for it, so it is added here.
        wanted = sorted(
            [
                label
                for label in _expected_labels().values()
                if label is not None
            ]
            + ["HOLD"],
        )
        assert sorted(badges) == wanted
        assert "Traceback" not in page.content()

    def test_design_roll_status_table_prints_each_action(
        self,
        page: Page,
        live_app_with_ips_url: str,
    ) -> None:
        page.goto(
            f"{live_app_with_ips_url}/design",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )
        page.wait_for_selector(
            "#plan-roll-panel .roll-action",
            timeout=_PAGE_LOAD_TIMEOUT_MS,
        )

        printed = page.locator(
            "#plan-roll-panel .roll-action"
        ).all_inner_texts()

        wanted = sorted(
            label for label in _expected_labels().values() if label is not None
        )
        assert sorted(printed) == wanted
        assert "Traceback" not in page.content()

    @pytest.mark.parametrize("route", ["/monitor", "/design"])
    def test_both_pages_render_cleanly_with_an_ips(
        self,
        page: Page,
        live_app_with_ips_url: str,
        route: str,
    ) -> None:
        _assert_renders_cleanly(page, f"{live_app_with_ips_url}{route}")
