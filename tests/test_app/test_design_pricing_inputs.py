"""The /design Pricing inputs panel (9b): what prices the book.

Shows, per input, the value that prices the book, where it came from, what
you typed and what the feed says now; says plainly that prices are read once
when the app starts; and carries the override / clear / dividend-yield
controls, each review then confirm.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from dash import no_update

from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages.design.planning import pricing_inputs
from tests.chain_builders import smile
from tests.clock_helpers import days_from_today
from tests.feed_fixtures import (
    STRIKES,
    TYPED_SPOT,
    TYPED_VOL,
    adopting_ips,
    fed_chain,
    leg_expiry,
    load_state,
    make_provider,
    write_typed_book,
)
from tests.test_app.test_design import _collect_text

if TYPE_CHECKING:
    from pathlib import Path

_STRIKE = 4000.0


def _app(
    tmp_path: Path,
    *,
    adopt: tuple[str, ...] = ("spot", "risk_free_rate", "volatility"),
    with_chain: bool = True,
    rates: bool = True,
    program_day_offset: int = 0,
) -> ProgramDashApp:
    """Two long puts and a cache that lists them, adopted per ``adopt``."""
    ips = adopting_ips(tmp_path, adopt)
    write_typed_book(tmp_path, ips)
    provider = make_provider(with_chain=with_chain)
    if not rates:
        provider.rates = {}
    if with_chain and program_day_offset:
        provider.chains = {
            "SPX": fed_chain(
                leg_expiry().date(),
                STRIKES,
                program_day=days_from_today(program_day_offset),
            ),
        }
    state = load_state(tmp_path, ips, provider)
    return create_app(
        state=state,
        market_data=provider,
        ips_config=state.ips_config,
    )


def _text(app: ProgramDashApp, ips_config: object = None) -> str:
    config = ips_config if ips_config is not None else app.ips_config
    return _collect_text(
        pricing_inputs._render_panel_logic(
            state=app.program_state,
            ips_config=config,  # type: ignore[arg-type]
            market_data=app.market_data,
        ),
    )


class TestThePanel:
    """What the panel shows, and what it refuses to claim."""

    def test_no_policy_section_says_nothing_is_fetched(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        assert app.ips_config is not None
        no_feed = replace(app.ips_config, pricing_feed=None)

        text = _text(app, no_feed)

        assert "no pricing_feed section" in text
        assert "every pricing input is hand-entered" in text
        assert "Held options" not in text

    def test_a_cold_cache_is_a_note_not_a_broken_panel(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path, with_chain=False))

        assert "No option chain is cached yet" in text
        assert "Something went wrong" not in text
        assert "fallback: your value" in text

    def test_the_inputs_table_sets_priced_beside_yours_beside_the_feed(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path))

        assert "Index level (spot)" in text
        assert "5,000.00" in text  # what prices the book
        assert f"{TYPED_SPOT:,.2f}" in text  # what you typed
        assert "fetched — Cboe index level" in text
        assert "DGS1 4.60% as published" in text or "DGS1" in text
        assert "% continuous" in text

    def test_the_dividend_yield_is_never_fetched_and_says_why(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path))

        assert "Dividend yield" in text
        assert "cannot isolate the yield" in text

    def test_a_missing_rate_is_a_note_beside_a_working_chain(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path, rates=False))

        assert "no DGS1 reading cached yet" in text
        assert "Held options" in text

    def test_a_held_option_shows_what_prices_it_and_where_from(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        option = next(
            p.option
            for p in app.program_state.portfolio.positions
            if p.option.strike_price == _STRIKE
        )

        text = _text(app)

        assert f"PUT {_STRIKE:g} exp {option.maturity_date:%Y-%m-%d}" in text
        assert "(SPX)" in text
        assert f"{smile(_STRIKE) * 100:.2f}%" in text  # Cboe's, and ours
        assert "fetched — solved from the" in text
        assert f"{TYPED_VOL * 100:.2f}%" in text  # your IV, beside it
        assert "IV at book r, q" in text

    def test_the_policy_ladder_rungs_are_listed_as_candidates(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path))

        assert "strike_ladder rungs (candidates, not held)" in text
        assert "20% OTM" in text

    def test_an_old_chain_is_flagged_stale(self, tmp_path: Path) -> None:
        text = _text(_app(tmp_path, program_day_offset=-30))

        assert "STALE-QUOTE" in text
        assert "fallback: your value" in text

    def test_nothing_is_written_to_the_book(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        before = app.program_state.portfolio.positions[0].option.volatility

        _text(app)

        assert app.program_state.portfolio.positions[0].option.volatility == (
            pytest.approx(before)
        )
        assert app.program_state.dirty is False


class TestWhatTheAppReadsAndWhen:
    """Prices are read once, at start; the panel says so."""

    def test_the_restart_notice_is_at_the_top(self, tmp_path: Path) -> None:
        text = _text(_app(tmp_path))

        assert "Prices read at" in text
        assert "only when it restarts" in text
        assert "refreshing this page does not update them" in text

    def test_no_notice_when_nothing_is_adopted(self, tmp_path: Path) -> None:
        text = _text(_app(tmp_path, adopt=()))

        assert "Prices read at" not in text
        assert "Policy adopt: nothing." in text
        assert "priced on your typed value" in text

    def test_adopt_is_stated(self, tmp_path: Path) -> None:
        text = _text(_app(tmp_path))

        assert "Policy adopt: spot, risk_free_rate, volatility." in text
        assert "unless you override them" in text

    def test_a_newer_cached_chain_says_to_restart(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path, program_day_offset=-3)
        newer = make_provider()
        app.market_data = newer  # type: ignore[assignment]

        text = _text(app)

        assert "A newer chain is cached" in text
        assert "restart the app to price on it" in text

    def test_no_newer_note_when_the_cache_is_what_was_read(
        self,
        tmp_path: Path,
    ) -> None:
        text = _text(_app(tmp_path))

        assert "A newer chain is cached" not in text

    def test_a_resolver_fault_is_stated(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(**_kwargs: object) -> object:
            raise RuntimeError("resolver fault")

        monkeypatch.setattr("deltadewa.state.resolve_pricing_inputs", boom)

        text = _text(_app(tmp_path))

        assert "could not be resolved" in text
        assert "resolver fault" in text


class TestOverridesInThePanel:
    """An override reads as one, with your value and the feed's."""

    def test_an_overridden_spot_says_so(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        pending, hidden, _text_children, _status = (
            pricing_inputs.review_override(
                {"target": "spot", "action": "set", "value": "4900"},
                app.program_state,
            )
        )
        assert pending is not None
        assert hidden is False
        pricing_inputs.confirm_override(pending, 0, app.program_state)

        text = _text(app)

        assert "your override" in text
        assert "4,900.00" in text


class TestTheControls:
    """The form is a skeleton; its options come from the book."""

    def test_the_form_is_present_with_a_feed_section(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        assert app.ips_config is not None

        layout = pricing_inputs.layout(
            state=app.program_state,
            ips_config=app.ips_config,
            market_data=app.market_data,
        )

        rendered = str(layout)
        for control in (
            "pricing-target",
            "pricing-review",
            "pricing-confirm",
            "pricing-pending",
        ):
            assert control in rendered

    def test_no_form_without_a_feed_section(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        assert app.ips_config is not None
        no_feed = replace(app.ips_config, pricing_feed=None)

        layout = pricing_inputs.layout(
            state=app.program_state,
            ips_config=no_feed,
            market_data=app.market_data,
        )

        assert "pricing-review" not in str(layout)

    def test_the_targets_are_spot_the_yield_and_each_iv(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)

        options = pricing_inputs.target_options(app.program_state)

        values = [option["value"] for option in options]
        assert values[:2] == ["spot", "dividend"]
        assert len(values) == 2 + len(STRIKES)
        assert all(value.startswith("iv:") for value in values[2:])
        assert all(
            option["label"].startswith("IV: PUT ") for option in options[2:]
        )


class TestReviewThenConfirm:
    """Nothing is written until the review is confirmed."""

    def test_review_writes_nothing_and_asks_for_a_confirm(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        state = app.program_state

        pending, hidden, review, status = pricing_inputs.review_override(
            {"target": "spot", "action": "set", "value": "4900"},
            state,
        )

        assert pending is not None
        assert hidden is False
        text = _collect_text(review)
        assert "4,900.00" in text
        assert "until you clear it" in text
        assert "Review the change below" in _collect_text(status)
        assert state.portfolio.spot_price == pytest.approx(5000.0)
        assert state.dirty is False

    def test_a_refused_review_keeps_the_confirm_hidden(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)

        pending, hidden, review, status = pricing_inputs.review_override(
            {"target": "spot", "action": "set", "value": "abc"},
            app.program_state,
        )

        assert pending is None
        assert hidden is True
        assert review == []
        assert "not a number" in _collect_text(status)

    def test_confirm_records_what_was_reviewed_and_bumps_the_version(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        state = app.program_state
        pending, *_ = pricing_inputs.review_override(
            {"target": "spot", "action": "set", "value": "4900"},
            state,
        )

        version, status, recorded = pricing_inputs.confirm_override(
            pending,
            7,
            state,
        )

        assert recorded is True
        assert version == 8
        assert "4,900.00" in _collect_text(status)
        assert state.portfolio.spot_price == pytest.approx(4900.0)

    def test_confirm_without_a_review_is_refused(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)

        version, status, recorded = pricing_inputs.confirm_override(
            None,
            7,
            app.program_state,
        )

        assert recorded is False
        assert version is no_update
        assert "Review the change first" in _collect_text(status)
        assert app.program_state.portfolio.spot_price == pytest.approx(5000.0)

    def test_a_confirm_the_state_refuses_does_not_bump_the_version(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path, adopt=("volatility",))
        state = app.program_state
        pending, *_ = pricing_inputs.review_override(
            {"target": "dividend", "action": "set", "value": "1.5"},
            state,
        )
        # The review passed; the option it named goes before the confirm.
        stale = {"target": "iv:gone", "action": "set", "value": "30"}

        version, status, recorded = pricing_inputs.confirm_override(
            stale,
            7,
            state,
        )

        assert pending is not None
        assert recorded is False
        assert version is no_update
        assert "no longer in the book" in _collect_text(status)

    def test_the_dividend_yield_is_edited_through_the_same_gate(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        state = app.program_state
        pending, hidden, review, _status = pricing_inputs.review_override(
            {"target": "dividend", "action": "set", "value": "1.5"},
            state,
        )
        assert hidden is False
        assert "1.50%" in _collect_text(review)

        pricing_inputs.confirm_override(pending, 0, state)

        assert state.entered.dividend_yield == pytest.approx(0.015)


class TestTheSpotBox:
    """The BOOK box holds what you typed, and says whether it prices."""

    def test_editing_spot_while_the_feed_prices_it_says_so(
        self,
        tmp_path: Path,
    ) -> None:
        from deltadewa.app.pages.design.book import _set_spot_price_logic

        app = _app(tmp_path)

        version, status = _set_spot_price_logic(
            value=4700.0,
            version=3,
            state=app.program_state,
        )

        text = _collect_text(status)
        assert version == 4
        assert "stored as the fallback" in text
        assert "priced on the feed's 5,000.00" in text
        assert "override it under Pricing inputs" in text
        assert app.program_state.entered.spot == pytest.approx(4700.0)
        assert app.program_state.portfolio.spot_price == pytest.approx(5000.0)

    def test_editing_spot_when_it_is_yours_just_updates(
        self,
        tmp_path: Path,
    ) -> None:
        from deltadewa.app.pages.design.book import _set_spot_price_logic

        app = _app(tmp_path, adopt=("risk_free_rate",))

        version, status = _set_spot_price_logic(
            value=4700.0,
            version=3,
            state=app.program_state,
        )

        assert version == 4
        assert "Spot price updated." in _collect_text(status)
        assert app.program_state.portfolio.spot_price == pytest.approx(4700.0)

    def test_the_box_is_prefilled_with_your_value_not_the_feeds(
        self,
        tmp_path: Path,
    ) -> None:
        from deltadewa.app.pages.design import book

        app = _app(tmp_path)

        layout = str(
            book.layout(
                app=app,
                portfolio=app.program_state.portfolio,
                default_style="EUROPEAN",
                trade_forms=pricing_inputs.html.Div(),
            ),
        )

        assert f"value={TYPED_SPOT}" in layout
        assert "the feed prices the book" in layout
