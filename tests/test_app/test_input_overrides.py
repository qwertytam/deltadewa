"""Overriding a fetched input, and the dividend-yield box (9b, D5/D7).

Every action is review-then-confirm: ``review_entry`` says what confirming
would do and writes nothing, ``record_entry`` does it. The warnings are the
policy's own thresholds: ``spot_divergence_warn_pct`` for spot and
``pricing_feed.override_warn_vol_points`` for an IV.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deltadewa.analysis.pricing_resolution import InputOrigin
from deltadewa.app.input_overrides import (
    EntryKind,
    InputEntryError,
    origin_text,
    parse_entry,
    record_entry,
    review_entry,
)
from tests.chain_builders import SPOT, smile
from tests.feed_fixtures import (
    TYPED_SPOT,
    adopting_ips,
    load_state,
    make_provider,
    write_typed_book,
)

if TYPE_CHECKING:
    from pathlib import Path

    from deltadewa.state import ProgramState


@pytest.fixture
def state(tmp_path: Path) -> ProgramState:
    """A typed book reloaded with every adoptable input adopted."""
    ips = adopting_ips(tmp_path)
    write_typed_book(tmp_path, ips)
    return load_state(tmp_path, ips, make_provider())


def _leg(state: ProgramState, strike: float) -> str:
    return next(
        p.position_id
        for p in state.portfolio.positions
        if p.option.strike_price == strike
    )


class TestParsing:
    """What was typed becomes one valid entry, or a plain refusal."""

    def test_a_spot_override(self, state: ProgramState) -> None:
        entry = parse_entry(
            {"action": "set", "target": "spot", "value": "4,900"},
            state,
        )

        assert entry.kind is EntryKind.OVERRIDE_SPOT
        assert entry.value == pytest.approx(4900.0)

    def test_an_iv_is_typed_in_percent(self, state: ProgramState) -> None:
        position_id = _leg(state, 4000.0)

        entry = parse_entry(
            {
                "action": "set",
                "target": f"iv:{position_id}",
                "value": "27.5%",
            },
            state,
        )

        assert entry.kind is EntryKind.OVERRIDE_IV
        assert entry.value == pytest.approx(0.275)
        assert entry.position_id == position_id

    def test_the_dividend_yield_is_typed_in_percent(
        self,
        state: ProgramState,
    ) -> None:
        entry = parse_entry(
            {"action": "set", "target": "dividend", "value": "1.3"},
            state,
        )

        assert entry.kind is EntryKind.DIVIDEND
        assert entry.value == pytest.approx(0.013)

    def test_a_clear_needs_no_value(self, state: ProgramState) -> None:
        position_id = _leg(state, 4000.0)

        spot = parse_entry({"action": "clear", "target": "spot"}, state)
        leg = parse_entry(
            {"action": "clear", "target": f"iv:{position_id}"},
            state,
        )

        assert spot.kind is EntryKind.CLEAR_SPOT
        assert leg.kind is EntryKind.CLEAR_IV
        assert spot.value is None

    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            ({"target": ""}, "Pick the input"),
            ({"target": "spot", "value": ""}, "Enter your spot"),
            ({"target": "spot", "value": "abc"}, "not a number"),
            ({"target": "spot", "value": "nan"}, "not a number"),
            ({"target": "spot", "value": "-5"}, "must be positive"),
            ({"target": "dividend", "value": "25"}, "not one"),
            ({"target": "dividend", "value": "-1"}, "not one"),
            ({"target": "nonsense", "value": "1"}, "Pick the input"),
        ],
    )
    def test_nonsense_is_refused(
        self,
        state: ProgramState,
        raw: dict[str, str],
        message: str,
    ) -> None:
        with pytest.raises(InputEntryError, match=message):
            parse_entry({"action": "set", **raw}, state)

    def test_an_iv_typed_as_a_fraction_is_refused(
        self,
        state: ProgramState,
    ) -> None:
        position_id = _leg(state, 4000.0)

        with pytest.raises(InputEntryError, match="entered in percent"):
            parse_entry(
                {
                    "action": "set",
                    "target": f"iv:{position_id}",
                    "value": "0.275",
                },
                state,
            )

    def test_an_option_that_has_gone_is_refused(
        self,
        state: ProgramState,
    ) -> None:
        with pytest.raises(InputEntryError, match="no longer in the book"):
            parse_entry(
                {"action": "set", "target": "iv:gone", "value": "30"},
                state,
            )


class TestReview:
    """Review says what confirming does, writes nothing, and warns."""

    def test_a_spot_override_names_the_feeds_figure(
        self,
        state: ProgramState,
    ) -> None:
        entry = parse_entry(
            {"action": "set", "target": "spot", "value": "4990"},
            state,
        )

        review = review_entry(entry, state)

        assert "4,990.00" in review.summary
        assert any("5,000.00" in line for line in review.lines)
        assert any("not forgotten" in line for line in review.lines)
        assert any("does not re-solve" in line for line in review.lines)
        assert review.warnings == ()
        assert state.portfolio.spot_price == pytest.approx(SPOT)

    def test_a_spot_far_from_the_feed_warns(self, state: ProgramState) -> None:
        ips = state.ips_config
        assert ips is not None
        threshold = ips.market_environment.spot_divergence_warn_pct
        far = SPOT * (1 - 2 * threshold / 100.0)
        entry = parse_entry(
            {"action": "set", "target": "spot", "value": str(far)},
            state,
        )

        review = review_entry(entry, state)

        assert len(review.warnings) == 1
        assert "from the feed's" in review.warnings[0]

    def test_an_iv_override_names_the_feeds_iv(
        self,
        state: ProgramState,
    ) -> None:
        position_id = _leg(state, 4000.0)
        feed_iv = smile(4000.0) * 100.0
        entry = parse_entry(
            {
                "action": "set",
                "target": f"iv:{position_id}",
                "value": f"{feed_iv + 0.5:.2f}",
            },
            state,
        )

        review = review_entry(entry, state)

        assert "PUT 4000" in review.summary
        assert any(
            "solved at the book's rate and yield" in x for x in review.lines
        )
        assert review.warnings == ()

    def test_an_iv_far_from_the_feed_warns(self, state: ProgramState) -> None:
        position_id = _leg(state, 4000.0)
        feed_iv = smile(4000.0) * 100.0
        entry = parse_entry(
            {
                "action": "set",
                "target": f"iv:{position_id}",
                "value": f"{feed_iv + 10.0:.2f}",
            },
            state,
        )

        review = review_entry(entry, state)

        assert len(review.warnings) == 1
        assert "vol points from the feed's" in review.warnings[0]

    def test_a_clear_says_the_feed_prices_it_again(
        self,
        state: ProgramState,
    ) -> None:
        record_entry(
            parse_entry(
                {"action": "set", "target": "spot", "value": "4900"},
                state,
            ),
            state,
        )
        entry = parse_entry({"action": "clear", "target": "spot"}, state)

        review = review_entry(entry, state)

        assert "price spot again" in review.summary
        assert any("fallback" in line for line in review.lines)
        assert any("5,000.00" in line for line in review.lines)

    def test_the_dividend_review_says_it_re_solves_the_ivs(
        self,
        state: ProgramState,
    ) -> None:
        entry = parse_entry(
            {"action": "set", "target": "dividend", "value": "1.5"},
            state,
        )

        review = review_entry(entry, state)

        assert "1.50%" in review.summary
        assert any("re-solves every adopted IV" in x for x in review.lines)
        assert any("never fetched" in x for x in review.lines)

    def test_an_input_the_policy_does_not_adopt_cannot_be_overridden(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path, ("risk_free_rate",))
        write_typed_book(tmp_path, ips)
        state = load_state(tmp_path, ips, make_provider())
        entry = parse_entry(
            {"action": "set", "target": "spot", "value": "4900"},
            state,
        )

        with pytest.raises(InputEntryError, match="not adopted"):
            review_entry(entry, state)


class TestRecord:
    """Confirming writes exactly what was reviewed."""

    def test_an_override_prices_the_book_until_cleared(
        self,
        state: ProgramState,
    ) -> None:
        set_spot = parse_entry(
            {"action": "set", "target": "spot", "value": "4900"},
            state,
        )

        record_entry(set_spot, state)

        assert state.portfolio.spot_price == pytest.approx(4900.0)
        assert state.resolution.spot.origin is InputOrigin.OVERRIDE

        record_entry(
            parse_entry({"action": "clear", "target": "spot"}, state),
            state,
        )

        assert state.portfolio.spot_price == pytest.approx(SPOT)
        assert state.entered.spot == pytest.approx(4900.0)

    def test_an_iv_override_and_its_clear(self, state: ProgramState) -> None:
        position_id = _leg(state, 4000.0)
        target = f"iv:{position_id}"

        record_entry(
            parse_entry(
                {"action": "set", "target": target, "value": "40"},
                state,
            ),
            state,
        )
        assert state.resolution.legs[position_id].origin is (
            InputOrigin.OVERRIDE
        )
        record_entry(
            parse_entry({"action": "clear", "target": target}, state),
            state,
        )

        assert state.resolution.legs[position_id].origin is (
            InputOrigin.FETCHED
        )

    def test_the_dividend_yield_is_a_typed_edit(
        self,
        state: ProgramState,
    ) -> None:
        before = state.portfolio.positions[0].option.volatility

        record_entry(
            parse_entry(
                {"action": "set", "target": "dividend", "value": "2.5"},
                state,
            ),
            state,
        )

        assert state.entered.dividend_yield == pytest.approx(0.025)
        assert state.portfolio.dividend_yield == pytest.approx(0.025)
        # The IV is solved at the new yield, so it moved.
        assert state.portfolio.positions[0].option.volatility != (
            pytest.approx(before, abs=1e-6)
        )


def test_every_origin_has_a_label() -> None:
    for origin in InputOrigin:
        assert origin_text(origin)


def test_the_typed_spot_is_not_the_effective_spot(state: ProgramState) -> None:
    """A guard on the fixture the whole module relies on."""
    assert state.entered.spot == pytest.approx(TYPED_SPOT)
    assert state.portfolio.spot_price == pytest.approx(SPOT)
