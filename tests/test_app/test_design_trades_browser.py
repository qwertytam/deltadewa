"""The trade forms in a real browser (#446).

``test_design_trades.py`` calls the forms' logic directly; this drives the
page an operator gets: choosing a lot, reviewing, confirming, and what the
book and the history hold afterwards. A direct call cannot see a dropped
callback id, a confirm row that stays up over stale values, a button that can
be clicked twice, or a form that refuses a second identical entry, which are
what these are for.

The book is invented: a held lot, a two-leg put spread, and a lot already past
expiry. Every price and fee is an invented figure.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from werkzeug.serving import make_server

from deltadewa.app.factory import create_app
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.portfolio.history import FillKind
from deltadewa.state import ProgramState
from tests.clock_helpers import days_from_today, program_date

from .conftest import EXAMPLE_IPS

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from playwright.sync_api import Locator, Page

    from deltadewa.portfolio.position import OptionPosition

_LOAD_MS = 30_000
_TAG = "tranche-a"
_LATER = days_from_today(540).date().isoformat()
_TODAY = program_date().date().isoformat()


@dataclass
class TradeApp:
    """A served app and the state behind it."""

    url: str
    state: ProgramState
    held: OptionPosition
    long_leg: OptionPosition
    short_leg: OptionPosition
    expired: OptionPosition


@pytest.fixture
def trade_app(tmp_path: Path) -> Iterator[TradeApp]:
    """The app as deployed (example IPS), over a book of invented lots."""
    state = ProgramState.load(
        tmp_path,
        ips_path=EXAMPLE_IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    add = state.portfolio.add_position
    held = add(
        strike_price=4500.0,
        maturity_date=days_from_today(365),
        quantity=10,
        option_type=OptionType.PUT,
    )
    long_leg = add(
        strike_price=4200.0,
        maturity_date=days_from_today(200),
        quantity=10,
        option_type=OptionType.PUT,
        structure_id=_TAG,
    )
    short_leg = add(
        strike_price=3800.0,
        maturity_date=days_from_today(200),
        quantity=-10,
        option_type=OptionType.PUT,
        structure_id=_TAG,
    )
    expired = add(
        strike_price=3500.0,
        maturity_date=days_from_today(-3),
        quantity=2,
        option_type=OptionType.PUT,
        reject_expired=False,
    )
    app = create_app(
        state=state,
        market_data=StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0),
        ips_config=state.ips_config,
    )
    server = make_server("127.0.0.1", 0, app.server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield TradeApp(
            url=f"http://127.0.0.1:{server.server_port}",
            state=state,
            held=held,
            long_leg=long_leg,
            short_leg=short_leg,
            expired=expired,
        )
    finally:
        server.shutdown()
        thread.join()


@pytest.fixture(autouse=True)
def _no_page_errors(page: Page) -> Iterator[None]:
    """Fail a test whose page threw an uncaught JavaScript error.

    The smoke suite does this for the page loads; the forms are exercised
    here, and a callback that renders a bad component shows up as a page
    error before it shows up as a wrong value.
    """
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield
    assert errors == []


def _open(page: Page, trade_app: TradeApp) -> None:
    page.goto(f"{trade_app.url}/design", timeout=_LOAD_MS)
    page.wait_for_selector("#close-lot", timeout=_LOAD_MS)
    # The lot lists arrive through callbacks, not the initial layout.
    page.wait_for_function(
        "document.querySelector('#roll-structure') !== null",
        timeout=_LOAD_MS,
    )


def _choose(page: Page, dropdown_id: str, text: str) -> None:
    page.click(f"#{dropdown_id}")
    page.locator(".dash-dropdown-option", has_text=text).first.click()


def _reason(page: Page, form: str, reason: str) -> None:
    page.locator(
        f'label:has(input[name="{form}-reason"]):has-text("{reason}")',
    ).click()


def _date(page: Page, selector: str, iso: str) -> None:
    page.fill(selector, iso)
    page.keyboard.press("Enter")  # commits the typed date


def _status(page: Page) -> str:
    return page.inner_text("#mutation-status")


def _fills(trade_app: TradeApp) -> list[FillKind]:
    assert trade_app.state.history is not None
    return [f.kind for f in trade_app.state.history.load().fills]


def _fill_close(page: Page, *, contracts: str, price: str, fees: str) -> None:
    page.fill("#close-contracts", contracts)
    page.fill("#close-price", price)
    page.fill("#close-fees", fees)
    _reason(page, "close", "ROUTINE")


class TestClose:
    def test_a_partial_close_is_reviewed_then_recorded(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        _choose(page, "close-lot", "PUT 4500")
        _fill_close(page, contracts="4", price="55", fees="2.6")

        page.click("#close-review")
        page.wait_for_selector("#close-confirm-row:not([hidden])")
        review = page.inner_text("#close-review-text")
        assert "Close 4 of 10 contracts of PUT 4500" in review
        assert "6 remain" in review
        # Nothing is written until the confirm.
        assert int(trade_app.held.quantity) == 10
        assert _fills(trade_app) == []

        page.click("#close-confirm")
        page.wait_for_function(
            "document.getElementById('close-confirm-row').hidden === true",
        )

        assert int(trade_app.held.quantity) == 6
        assert _fills(trade_app) == [FillKind.CLOSE]
        assert "Recorded: Close 4 of 10" in _status(page)
        assert page.input_value("#close-fees") == ""

    def test_editing_after_the_review_withdraws_the_confirm(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        _choose(page, "close-lot", "PUT 4500")
        _fill_close(page, contracts="4", price="55", fees="0")
        page.click("#close-review")
        page.wait_for_selector("#close-confirm-row:not([hidden])")

        page.fill("#close-price", "56")

        page.wait_for_function(
            "document.getElementById('close-confirm-row').hidden === true",
        )
        assert _fills(trade_app) == []

    def test_a_blank_fee_is_refused_but_zero_is_not(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        _choose(page, "close-lot", "PUT 4500")
        page.fill("#close-contracts", "4")
        page.fill("#close-price", "55")
        _reason(page, "close", "ROUTINE")

        page.click("#close-review")
        page.wait_for_function(
            "document.getElementById('mutation-status').innerText"
            ".includes('Fees is required')",
        )
        assert page.locator("#close-confirm-row[hidden]").count() == 1

        page.fill("#close-fees", "0")
        page.click("#close-review")
        page.wait_for_selector("#close-confirm-row:not([hidden])")

    def test_two_closes_with_the_same_zero_fees_both_land(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        """A rebuilt form has no memory of the last entry."""
        _open(page, trade_app)
        for _ in range(2):
            _choose(page, "close-lot", "PUT 4500")
            _fill_close(page, contracts="2", price="55", fees="0")
            page.click("#close-review")
            page.wait_for_selector("#close-confirm-row:not([hidden])")
            page.click("#close-confirm")
            page.wait_for_function(
                "document.getElementById('close-confirm-row').hidden === true",
            )

        assert int(trade_app.held.quantity) == 6
        assert _fills(trade_app) == [FillKind.CLOSE, FillKind.CLOSE]

    def test_a_double_click_on_confirm_records_one_close(
        self,
        page: Page,
        trade_app: TradeApp,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original = trade_app.state.close_position

        def _slow(*args: object, **kwargs: object) -> None:
            time.sleep(1.0)
            original(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(trade_app.state, "close_position", _slow)
        _open(page, trade_app)
        _choose(page, "close-lot", "PUT 4500")
        _fill_close(page, contracts="4", price="55", fees="0")
        page.click("#close-review")
        page.wait_for_selector("#close-confirm-row:not([hidden])")

        page.click("#close-confirm")
        page.wait_for_function(
            "document.getElementById('close-confirm').disabled === true",
            timeout=2_000,
        )
        page.locator("#close-confirm").click(force=True, no_wait_after=True)
        page.wait_for_function(
            "document.getElementById('close-confirm-row').hidden === true",
            timeout=8_000,
        )

        assert int(trade_app.held.quantity) == 6
        assert _fills(trade_app) == [FillKind.CLOSE]


class TestSettle:
    def test_the_prompt_leads_to_the_form_and_a_settlement(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        page.wait_for_selector("#trade-unsettled-prompt >> text=PUT 3500")
        prompt = page.inner_text("#trade-unsettled-prompt")
        assert "no settlement recorded" in prompt
        assert "PUT 4500" not in prompt

        page.click("#trade-unsettled-prompt >> text=Settle…")
        page.wait_for_function(
            "document.getElementById('settle-lot-value').innerText"
            ".includes('PUT 3500')",
        )
        page.fill("#settle-value", "0")
        page.fill("#settle-fees", "0")
        _date(page, "#settle-date", _TODAY)
        page.click("#settle-review")
        page.wait_for_selector("#settle-confirm-row:not([hidden])")
        assert "expired worthless" in page.inner_text("#settle-review-text")

        page.click("#settle-confirm")
        page.wait_for_function(
            "document.getElementById('settle-confirm-row').hidden === true",
        )

        assert trade_app.expired not in trade_app.state.positions_snapshot()
        assert _fills(trade_app) == [FillKind.SETTLE]
        # The prompt goes with the lot it was about.
        page.wait_for_function(
            "!document.getElementById('trade-unsettled-prompt')"
            ".innerText.includes('PUT 3500')",
        )

    def test_the_settle_list_offers_only_lots_at_or_past_expiry(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        page.click("#settle-lot")
        page.wait_for_selector(".dash-dropdown-option", timeout=_LOAD_MS)
        options = page.locator(".dash-dropdown-option").all_inner_texts()
        assert len(options) == 1
        assert "PUT 3500" in options[0]

    def test_the_date_has_no_default(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        _choose(page, "settle-lot", "PUT 3500")
        page.fill("#settle-value", "0")
        page.fill("#settle-fees", "0")

        page.click("#settle-review")

        page.wait_for_function(
            "document.getElementById('mutation-status').innerText"
            ".includes('Settlement date')",
        )
        assert _fills(trade_app) == []


class TestRoll:
    def _leg(self, page: Page, number: int) -> Locator:
        return page.locator(".trade-leg").nth(number)

    def _field(self, block: Locator, name: str) -> Locator:
        return block.locator(f'input[id*=\'"field":"{name}"\']')

    def _fill_leg(
        self,
        page: Page,
        number: int,
        *,
        close: tuple[str, str],
        strike: str,
        new: tuple[str, str],
    ) -> None:
        block = self._leg(page, number)
        self._field(block, "close_price").fill(close[0])
        self._field(block, "close_fees").fill(close[1])
        self._field(block, "strike").fill(strike)
        block.locator("input[id*='roll-maturity']").fill(_LATER)
        page.keyboard.press("Enter")
        self._field(block, "price").fill(new[0])
        self._field(block, "fees").fill(new[1])

    def test_a_spread_rolls_as_one_action_two_fills_per_leg(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        _choose(page, "roll-structure", _TAG)
        page.wait_for_selector(".trade-leg")
        assert page.locator(".trade-leg").count() == 2
        self._fill_leg(
            page,
            0,
            close=("44", "7"),
            strike="4400",
            new=("61", "8"),
        )
        self._fill_leg(
            page,
            1,
            close=("15", "5"),
            strike="4000",
            new=("24", "6"),
        )
        _reason(page, "roll", "ROUTINE")

        page.click("#roll-review")
        page.wait_for_selector("#roll-confirm-row:not([hidden])")
        review = page.inner_text("#roll-review-text")
        assert "Roll 2 legs" in review
        assert "Package net" in review
        assert "not stored" in review
        assert len(trade_app.state.positions_snapshot()) == 4

        page.click("#roll-confirm")
        page.wait_for_function(
            "document.getElementById('roll-confirm-row').hidden === true",
        )

        held = trade_app.state.positions_snapshot()
        strikes = sorted(p.option.strike_price for p in held)
        assert strikes == [3500.0, 4000.0, 4400.0, 4500.0]
        rolled = [p for p in held if p.structure_id == _TAG]
        assert sorted(p.option.strike_price for p in rolled) == [4000.0, 4400.0]
        assert trade_app.state.history is not None
        fills = trade_app.state.history.load().fills
        assert [f.kind for f in fills] == [
            FillKind.CLOSE,
            FillKind.OPEN,
            FillKind.CLOSE,
            FillKind.OPEN,
        ]
        assert fills[0].roll_id == fills[1].roll_id
        assert fills[2].roll_id == fills[3].roll_id
        assert fills[0].roll_id != fills[2].roll_id
        assert all(f.fees is not None for f in fills)

    def test_the_book_changes_panel_shows_each_fill_with_its_cash(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        _choose(page, "roll-structure", _TAG)
        page.wait_for_selector(".trade-leg")
        self._fill_leg(
            page,
            0,
            close=("44", "7"),
            strike="4400",
            new=("61", "8"),
        )
        self._fill_leg(
            page,
            1,
            close=("15", "5"),
            strike="4000",
            new=("24", "6"),
        )
        _reason(page, "roll", "ROUTINE")
        page.click("#roll-review")
        page.wait_for_selector("#roll-confirm-row:not([hidden])")
        page.click("#roll-confirm")
        page.wait_for_function(
            "document.getElementById('roll-confirm-row').hidden === true",
        )

        page.wait_for_function(
            "document.getElementById('plan-book-changes-panel')"
            ".innerText.includes('(roll)')",
        )
        panel = page.inner_text("#plan-book-changes-panel")
        assert panel.count("(roll)") == 4
        # The panel's own note mentions "not captured"; no *row* does.
        cells = page.locator("#plan-book-changes-panel td")
        assert cells.filter(has_text="not captured").count() == 0
        assert cells.filter(has_text="$").count() >= 4

    def test_a_leg_left_blank_refuses_the_whole_roll(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        _choose(page, "roll-structure", _TAG)
        page.wait_for_selector(".trade-leg")
        self._fill_leg(
            page,
            0,
            close=("44", "7"),
            strike="4400",
            new=("61", "8"),
        )
        _reason(page, "roll", "ROUTINE")

        page.click("#roll-review")

        page.wait_for_function(
            "document.getElementById('mutation-status').innerText"
            ".includes('Leg 2')",
        )
        assert len(trade_app.state.positions_snapshot()) == 4
        assert _fills(trade_app) == []


class TestAddRecordsAFill:
    def test_a_lot_added_with_its_fees_is_an_open_fill(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        page.fill("#add-strike", "4100")
        page.fill("#add-quantity", "3")
        page.fill("#add-entry-premium", "42")
        page.fill("#add-fees", "0")
        _date(page, "#add-maturity", _LATER)

        page.click("#add-submit")
        page.wait_for_function(
            "document.getElementById('mutation-status').innerText"
            ".includes('Added.')",
        )

        assert trade_app.state.history is not None
        (fill,) = trade_app.state.history.load().fills
        assert fill.kind is FillKind.OPEN
        assert fill.fees is not None
        assert fill.fees == pytest.approx(0.0)
        assert fill.price_per_share == pytest.approx(42.0)

    def test_blank_fees_are_refused_not_recorded_as_zero(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        _open(page, trade_app)
        page.fill("#add-strike", "4100")
        page.fill("#add-quantity", "3")
        page.fill("#add-entry-premium", "42")
        _date(page, "#add-maturity", _LATER)

        page.click("#add-submit")

        page.wait_for_function(
            "document.getElementById('mutation-status').innerText"
            ".includes('Fees is required')",
        )
        assert _fills(trade_app) == []
        assert len(trade_app.state.positions_snapshot()) == 4


class TestRemoveStillCorrectsATypo:
    def test_remove_records_a_deletion_with_no_proceeds(
        self,
        page: Page,
        trade_app: TradeApp,
    ) -> None:
        page.on("dialog", lambda dialog: dialog.accept())
        _open(page, trade_app)
        page.wait_for_selector(".position-table")

        page.locator(".btn-remove").first.click()
        page.wait_for_function(
            "document.getElementById('mutation-status').innerText"
            ".includes('Removed.')",
        )

        assert trade_app.state.history is not None
        history = trade_app.state.history.load()
        assert history.fills == ()
        assert [e.kind.value for e in history.edits] == ["DELETE"]
