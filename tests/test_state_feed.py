"""ProgramState prices the book on the feed, and saves only what was typed (9b).

The state keeps two books: the **typed** one (what a human typed; the only
one ever saved) and the **priced view** every reader sees. These tests pin
the contract between them: the view carries the feed's values, the file
never does, an edit re-resolves, and a failure anywhere in resolving leaves
the app booting on its typed values.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from deltadewa.analysis.pricing_resolution import InputOrigin, OverrideKind
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.state import ConfirmationRequiredError, ProgramState
from tests.chain_builders import RATE, SPOT, smile
from tests.feed_fixtures import (
    STRIKES,
    TYPED_RATE,
    TYPED_SPOT,
    TYPED_VOL,
    adopting_ips,
    leg_expiry,
    load_state,
    make_provider,
    write_typed_book,
)

if TYPE_CHECKING:
    from pathlib import Path

    from deltadewa.ips_config import IpsConfig
    from deltadewa.marketdata import MarketDataProvider

_TYPED_SPOT = TYPED_SPOT
_TYPED_RATE = TYPED_RATE
_TYPED_VOL = TYPED_VOL
_STRIKES = STRIKES
_expiry = leg_expiry
_provider = make_provider
_typed_book = write_typed_book
_load = load_state


@pytest.fixture
def adopted(tmp_path: Path) -> ProgramState:
    """A typed book, reloaded with every adoptable input adopted."""
    ips = adopting_ips(tmp_path)
    _typed_book(tmp_path, ips)
    return _load(tmp_path, ips, _provider())


def _saved(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / "program_state.json").read_text())


class TestNothingAdopted:
    """No provider, or no adopted input: today's behaviour, exactly."""

    def test_without_a_provider_the_view_is_the_typed_book(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path, ())
        _typed_book(tmp_path, ips)

        state = _load(tmp_path, ips, None)

        assert state.resolution.is_identity
        assert state.portfolio.spot_price == _TYPED_SPOT
        assert state.market_data is None

    def test_an_empty_adopt_list_prices_on_typed_values(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path, ())
        _typed_book(tmp_path, ips)

        state = _load(tmp_path, ips, _provider())

        assert state.resolution.is_identity
        assert state.portfolio.spot_price == _TYPED_SPOT
        assert state.portfolio.risk_free_rate == _TYPED_RATE


class TestThePricedView:
    """Every reader sees the feed's values; the typed book keeps its own."""

    def test_readers_see_the_fetched_spot_rate_and_ivs(
        self,
        adopted: ProgramState,
    ) -> None:
        book = adopted.portfolio

        assert book.spot_price == pytest.approx(SPOT)
        assert book.risk_free_rate == pytest.approx(RATE)
        by_strike = {
            p.option.strike_price: p.option.volatility for p in book.positions
        }
        for strike in _STRIKES:
            assert by_strike[strike] == pytest.approx(smile(strike), abs=2e-3)
        assert by_strike[3500.0] > by_strike[4000.0]

    def test_entered_is_what_a_human_typed(
        self,
        adopted: ProgramState,
    ) -> None:
        entered = adopted.entered

        assert entered.spot == _TYPED_SPOT
        assert entered.risk_free_rate == _TYPED_RATE
        assert set(entered.leg_vols.values()) == {_TYPED_VOL}

    def test_every_input_says_where_it_came_from(
        self,
        adopted: ProgramState,
    ) -> None:
        resolution = adopted.resolution

        assert resolution.spot.origin is InputOrigin.FETCHED
        assert resolution.risk_free_rate.origin is InputOrigin.FETCHED
        assert resolution.dividend_yield.origin is InputOrigin.ENTERED
        assert {leg.origin for leg in resolution.legs.values()} == {
            InputOrigin.FETCHED,
        }

    def test_positions_snapshot_is_the_priced_legs(
        self,
        adopted: ProgramState,
    ) -> None:
        vols = {p.option.volatility for p in adopted.positions_snapshot()}

        assert _TYPED_VOL not in vols

    def test_two_loads_of_one_book_agree(self, tmp_path: Path) -> None:
        """The app and the digest each load: one cache, one answer."""
        ips = adopting_ips(tmp_path)
        _typed_book(tmp_path, ips)

        first = _load(tmp_path, ips, _provider())
        second = _load(tmp_path, ips, _provider())

        assert first.portfolio.spot_price == second.portfolio.spot_price
        assert [p.option.volatility for p in first.portfolio.positions] == [
            p.option.volatility for p in second.portfolio.positions
        ]


class TestTheFileIsTyped:
    """A fetched number is never written to the book file."""

    def test_an_unrelated_edit_saves_typed_values(
        self,
        adopted: ProgramState,
        tmp_path: Path,
    ) -> None:
        position_id = adopted.portfolio.positions[0].position_id

        adopted.record_liquidity(
            position_id,
            bid=2.4,
            ask=2.6,
            open_interest=100,
        )

        saved = _saved(tmp_path)
        params = saved["market_parameters"]
        assert isinstance(params, dict)
        assert params["spot_price"] == _TYPED_SPOT
        assert params["risk_free_rate"] == _TYPED_RATE
        positions = saved["positions"]
        assert isinstance(positions, list)
        assert {p["volatility"] for p in positions} == {_TYPED_VOL}

    def test_a_typed_edit_is_stored_and_does_not_change_what_prices(
        self,
        adopted: ProgramState,
        tmp_path: Path,
    ) -> None:
        adopted.update_market_conditions(spot_price=4700.0)

        assert adopted.entered.spot == pytest.approx(4700.0)
        assert adopted.portfolio.spot_price == pytest.approx(SPOT)
        params = _saved(tmp_path)["market_parameters"]
        assert isinstance(params, dict)
        assert params["spot_price"] == pytest.approx(4700.0)

    def test_the_recorded_liquidity_quote_survives_adoption_and_edits(
        self,
        adopted: ProgramState,
    ) -> None:
        position_id = adopted.portfolio.positions[0].position_id

        adopted.record_liquidity(
            position_id,
            bid=2.4,
            ask=2.6,
            open_interest=100,
        )
        adopted.update_market_conditions(risk_free_rate=0.031)

        assert adopted.portfolio.positions[0].liquidity is not None
        assert adopted.portfolio.positions[0].liquidity.bid == pytest.approx(
            2.4
        )


class TestOverrides:
    """A pin is a typed value the feed does not replace, until cleared."""

    def test_a_spot_override_prices_the_book_and_shows_the_fetched(
        self,
        adopted: ProgramState,
    ) -> None:
        adopted.set_input_override(OverrideKind.SPOT, 4900.0, confirm=True)

        assert adopted.portfolio.spot_price == pytest.approx(4900.0)
        spot = adopted.resolution.spot
        assert spot.origin is InputOrigin.OVERRIDE
        assert spot.fetched == pytest.approx(SPOT)

    def test_an_override_is_saved_as_a_pin_on_the_typed_value(
        self,
        adopted: ProgramState,
        tmp_path: Path,
    ) -> None:
        adopted.set_input_override(OverrideKind.SPOT, 4900.0, confirm=True)

        params = _saved(tmp_path)["market_parameters"]
        assert isinstance(params, dict)
        assert params["spot_price"] == pytest.approx(4900.0)
        assert params["spot_override"] is True

    def test_an_override_survives_a_restart(
        self,
        adopted: ProgramState,
        tmp_path: Path,
    ) -> None:
        adopted.set_input_override(OverrideKind.SPOT, 4900.0, confirm=True)

        reloaded = _load(tmp_path, adopting_ips(tmp_path), _provider())

        assert reloaded.portfolio.spot_price == pytest.approx(4900.0)
        assert reloaded.resolution.spot.origin is InputOrigin.OVERRIDE

    def test_clearing_returns_to_the_feed_and_keeps_the_typed_value(
        self,
        adopted: ProgramState,
    ) -> None:
        adopted.set_input_override(OverrideKind.SPOT, 4900.0, confirm=True)

        adopted.clear_input_override(OverrideKind.SPOT, confirm=True)

        assert adopted.portfolio.spot_price == pytest.approx(SPOT)
        assert adopted.entered.spot == pytest.approx(4900.0)
        assert adopted.resolution.spot.origin is InputOrigin.FETCHED

    def test_an_iv_override_prices_one_option(
        self,
        adopted: ProgramState,
    ) -> None:
        position_id = adopted.portfolio.positions[1].position_id

        adopted.set_input_override(
            OverrideKind.VOLATILITY,
            0.40,
            position_id=position_id,
            confirm=True,
        )

        priced = {
            p.position_id: p.option.volatility
            for p in adopted.portfolio.positions
        }
        assert priced[position_id] == pytest.approx(0.40)
        leg = adopted.resolution.legs[position_id]
        assert leg.origin is InputOrigin.OVERRIDE
        assert leg.fetched is not None
        other = adopted.portfolio.positions[0].position_id
        assert adopted.resolution.legs[other].origin is InputOrigin.FETCHED

    def test_an_override_is_stamped_as_confirmed_now(
        self,
        adopted: ProgramState,
    ) -> None:
        assert adopted.portfolio.stamps.spot_as_of is not None
        before = adopted.portfolio.stamps.spot_as_of

        adopted.set_input_override(OverrideKind.SPOT, 4900.0, confirm=True)

        after = adopted.portfolio.stamps.spot_as_of
        assert after is not None
        assert after >= before

    def test_an_override_needs_confirmation(
        self,
        adopted: ProgramState,
    ) -> None:
        with pytest.raises(ConfirmationRequiredError):
            adopted.set_input_override(OverrideKind.SPOT, 4900.0)
        with pytest.raises(ConfirmationRequiredError):
            adopted.clear_input_override(OverrideKind.SPOT)

    def test_an_input_the_policy_does_not_adopt_cannot_be_overridden(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path, ("volatility",))
        _typed_book(tmp_path, ips)
        state = _load(tmp_path, ips, _provider())

        with pytest.raises(ValueError, match="not adopted"):
            state.set_input_override(OverrideKind.SPOT, 4900.0, confirm=True)

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_a_nonsense_override_is_refused(
        self,
        adopted: ProgramState,
        bad: float,
    ) -> None:
        with pytest.raises(ValueError, match="positive number"):
            adopted.set_input_override(OverrideKind.SPOT, bad, confirm=True)

    def test_an_iv_typed_as_a_percentage_is_refused(
        self,
        adopted: ProgramState,
    ) -> None:
        position_id = adopted.portfolio.positions[0].position_id

        with pytest.raises(ValueError, match="fraction"):
            adopted.set_input_override(
                OverrideKind.VOLATILITY,
                25.0,
                position_id=position_id,
                confirm=True,
            )

    def test_an_iv_override_names_an_option_that_exists(
        self,
        adopted: ProgramState,
    ) -> None:
        with pytest.raises(ValueError, match="no longer in the book"):
            adopted.set_input_override(
                OverrideKind.VOLATILITY,
                0.3,
                position_id="gone",
                confirm=True,
            )
        with pytest.raises(ValueError, match="names the option"):
            adopted.set_input_override(
                OverrideKind.VOLATILITY,
                0.3,
                confirm=True,
            )


class TestReviewingInputs:
    """The review button stamps only the typed values that price the book."""

    def test_a_hidden_typed_value_is_not_stamped(
        self,
        adopted: ProgramState,
    ) -> None:
        stamps_before = adopted.portfolio.stamps
        leg_before = adopted.portfolio.positions[0].volatility_as_of

        adopted.mark_inputs_reviewed(confirm=True)

        stamps = adopted.portfolio.stamps
        # The feed prices spot, rate and every IV: only the yield is typed.
        assert stamps.spot_as_of == stamps_before.spot_as_of
        assert stamps.risk_free_rate_as_of == stamps_before.risk_free_rate_as_of
        assert adopted.portfolio.positions[0].volatility_as_of == leg_before
        assert stamps.dividend_yield_as_of is not None
        assert (
            stamps_before.dividend_yield_as_of is None
            or stamps.dividend_yield_as_of >= stamps_before.dividend_yield_as_of
        )

    def test_an_overridden_value_is_stamped(
        self,
        adopted: ProgramState,
    ) -> None:
        adopted.set_input_override(OverrideKind.SPOT, 4900.0, confirm=True)
        stamp = adopted.portfolio.stamps.spot_as_of

        adopted.mark_inputs_reviewed(confirm=True)

        assert adopted.portfolio.stamps.spot_as_of is not None
        assert stamp is not None
        assert adopted.portfolio.stamps.spot_as_of >= stamp

    def test_with_nothing_adopted_it_stamps_everything_as_before(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path, ())
        _typed_book(tmp_path, ips)
        state = _load(tmp_path, ips, _provider())

        state.mark_inputs_reviewed(confirm=True)

        stamps = state.portfolio.stamps
        assert stamps.spot_as_of is not None
        assert stamps.risk_free_rate_as_of is not None
        assert stamps.dividend_yield_as_of is not None
        assert all(
            p.volatility_as_of is not None for p in state.portfolio.positions
        )


class TestNewLegs:
    """A lot opened while the feed prices the book enters at the real spot."""

    def test_entry_spot_is_the_effective_spot(
        self,
        adopted: ProgramState,
    ) -> None:
        position = adopted.add_position(
            strike_price=3500.0,
            maturity_date=_expiry(),
            quantity=1,
            option_type=OptionType.PUT,
        )

        assert position.entry_spot == pytest.approx(SPOT)
        assert adopted.entered.spot == _TYPED_SPOT


class TestFailuresAreContained:
    """A fault reading or resolving the feed never stops the app booting."""

    def test_a_provider_that_cannot_be_built_leaves_typed_values(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path)
        _typed_book(tmp_path, ips)

        def broken(_ips: IpsConfig | None) -> MarketDataProvider:
            raise RuntimeError("cache directory unreadable")

        state = ProgramState.load(
            tmp_path,
            ips_path=ips,
            default_exercise_style=ExerciseStyle.EUROPEAN,
            examples_dir=tmp_path / "none",
            market_data=broken,
        )

        assert state.portfolio.spot_price == _TYPED_SPOT
        assert state.resolution.error is not None
        assert "cache directory unreadable" in state.resolution.error

    def test_a_resolver_that_raises_leaves_typed_values(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ips = adopting_ips(tmp_path)
        _typed_book(tmp_path, ips)

        def boom(**_kwargs: object) -> object:
            raise RuntimeError("resolver fault")

        monkeypatch.setattr("deltadewa.state.resolve_pricing_inputs", boom)

        state = _load(tmp_path, ips, _provider())

        assert state.portfolio.spot_price == _TYPED_SPOT
        assert state.resolution.error == "resolver fault"
        assert state.resolution.is_identity

    def test_an_edit_still_works_when_the_resolver_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ips = adopting_ips(tmp_path)
        _typed_book(tmp_path, ips)

        def boom(**_kwargs: object) -> object:
            raise RuntimeError("resolver fault")

        monkeypatch.setattr("deltadewa.state.resolve_pricing_inputs", boom)
        state = _load(tmp_path, ips, _provider())

        state.update_market_conditions(spot_price=4750.0)

        assert state.portfolio.spot_price == pytest.approx(4750.0)

    def test_no_chain_cached_falls_back_and_says_so(
        self,
        tmp_path: Path,
    ) -> None:
        ips = adopting_ips(tmp_path)
        _typed_book(tmp_path, ips)

        state = _load(tmp_path, ips, _provider(with_chain=False))

        assert state.portfolio.spot_price == _TYPED_SPOT
        assert state.resolution.spot.origin is InputOrigin.FALLBACK
        assert state.resolution.error is None


class TestReplacingTheBook:
    """An import rebuilds the view for the book that replaced it."""

    def test_import_rebuilds_the_priced_view(
        self,
        adopted: ProgramState,
        tmp_path: Path,
    ) -> None:
        snapshot = adopted.export_snapshot("copy.json")
        adopted.remove_position(0, confirm=True)
        assert len(adopted.portfolio.positions) == len(_STRIKES) - 1

        adopted.import_portfolio(snapshot, confirm=True)

        assert len(adopted.portfolio.positions) == len(_STRIKES)
        assert adopted.portfolio.spot_price == pytest.approx(SPOT)
        assert set(adopted.resolution.legs) == {
            p.position_id for p in adopted.portfolio.positions
        }
        saved = _saved(tmp_path)
        params = saved["market_parameters"]
        assert isinstance(params, dict)
        assert params["spot_price"] == _TYPED_SPOT

    def test_a_snapshot_is_the_typed_book(
        self,
        adopted: ProgramState,
    ) -> None:
        path = adopted.export_snapshot("copy.json")

        data = json.loads(path.read_text())

        assert data["market_parameters"]["spot_price"] == _TYPED_SPOT


class TestWeeklyMarks:
    """A mark records where each option's IV came from (D11)."""

    def test_a_mark_taken_on_a_fed_book_records_the_feed(
        self,
        adopted: ProgramState,
    ) -> None:
        from deltadewa.history_cli import take_mark

        outcome = take_mark(adopted, written_by="test")

        assert outcome.mark is not None
        assert {leg.volatility_origin for leg in outcome.mark.legs} == {
            "FETCHED",
        }
        assert outcome.mark.spot == pytest.approx(SPOT)

    def test_a_mark_on_an_unfed_book_records_typed(
        self,
        tmp_path: Path,
    ) -> None:
        from deltadewa.history_cli import take_mark

        ips = adopting_ips(tmp_path, ())
        _typed_book(tmp_path, ips)
        state = _load(tmp_path, ips, _provider())

        outcome = take_mark(state, written_by="test")

        assert outcome.mark is not None
        assert {leg.volatility_origin for leg in outcome.mark.legs} == {
            "ENTERED",
        }

    def test_an_override_is_recorded_as_typed(
        self,
        adopted: ProgramState,
    ) -> None:
        from deltadewa.history_cli import take_mark

        position_id = adopted.portfolio.positions[0].position_id
        adopted.set_input_override(
            OverrideKind.VOLATILITY,
            0.40,
            position_id=position_id,
            confirm=True,
        )

        outcome = take_mark(adopted, written_by="test")

        assert outcome.mark is not None
        origins = {
            leg.position_id: leg.volatility_origin for leg in outcome.mark.legs
        }
        assert origins[position_id] == "OVERRIDE"
