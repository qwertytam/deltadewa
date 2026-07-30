"""Tests for deltadewa.state — the shared server-side program state."""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from deltadewa import OptionPortfolio, create_empty_portfolio
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.persistence import PortfolioSerializer
from deltadewa.reporting import PortfolioLogger
from deltadewa.state import (
    STATE_FILENAME,
    ConfirmationRequiredError,
    ProgramState,
)

_MATURITY = datetime(2027, 6, 30, tzinfo=UTC)
_MISSING_IPS = Path("does-not-exist-ips.yaml")


def _load(tmp_path: Path) -> ProgramState:
    return ProgramState.load(
        tmp_path,
        ips_path=tmp_path / _MISSING_IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )


def _raise_mid_write(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("simulated crash mid-write")


def _force_autosave_failure(
    state: ProgramState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make one mutation's autosave fail, leaving ``state.dirty`` True.

    Scoped so the failure doesn't leak into the rest of the test.
    """
    with monkeypatch.context() as patch:
        patch.setattr("deltadewa.persistence.json.dump", _raise_mid_write)
        with pytest.raises(RuntimeError, match="simulated crash"):
            state.add_position(
                strike_price=100.0,
                maturity_date=_MATURITY,
                quantity=1,
                option_type=OptionType.PUT,
            )


def _other_portfolio_export(tmp_path: Path, filename: str) -> Path:
    """Write a standalone portfolio export, independent of any ProgramState."""
    portfolio = OptionPortfolio(
        spot_price=200.0,
        volatility=0.25,
        symbol="OTHER",
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=190.0,
        maturity_date=_MATURITY,
        quantity=3,
        option_type=OptionType.CALL,
    )
    other_serializer = PortfolioSerializer(export_dir=tmp_path)
    return other_serializer.export_to_json(
        portfolio,
        PortfolioLogger(),
        filename=filename,
    )


class TestLoad:
    """Startup: read exports/program_state.json, or start clean."""

    def test_no_state_file_starts_empty_and_says_so(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """No fabricated book — an empty start is logged, not silent."""
        with caplog.at_level(logging.INFO):
            state = _load(tmp_path)

        assert state.loaded_from is None
        assert state.portfolio.positions == []
        assert "starting an empty book" in caplog.text

    def test_existing_state_file_round_trips(self, tmp_path: Path) -> None:
        """A prior save is read back faithfully on the next load."""
        first = _load(tmp_path)
        first.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=2,
            option_type=OptionType.PUT,
        )

        second = _load(tmp_path)

        assert second.loaded_from == tmp_path / STATE_FILENAME
        assert len(second.portfolio.positions) == 1
        assert second.portfolio.positions[0].quantity == 2
        assert second.portfolio.positions[
            0
        ].option.strike_price == pytest.approx(100.0)


class TestNonDestructiveMutatorsAutosave:
    """Each mutator marks dirty, then autosaves — dirty is False right after."""

    def test_add_position(self, tmp_path: Path) -> None:
        state = _load(tmp_path)

        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=5,
            option_type=OptionType.CALL,
        )

        assert state.dirty is False
        reloaded = _load(tmp_path)
        assert len(reloaded.portfolio.positions) == 1
        assert reloaded.portfolio.positions[0].quantity == 5

    def test_update_position(self, tmp_path: Path) -> None:
        state = _load(tmp_path)
        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.CALL,
        )

        state.update_position(0, quantity=7)

        assert state.dirty is False
        reloaded = _load(tmp_path)
        assert reloaded.portfolio.positions[0].quantity == 7

    def test_set_volatility(self, tmp_path: Path) -> None:
        state = _load(tmp_path)

        state.set_volatility(0.42)

        assert state.dirty is False
        reloaded = _load(tmp_path)
        assert reloaded.portfolio.volatility == pytest.approx(0.42)

    def test_update_market_conditions(self, tmp_path: Path) -> None:
        state = _load(tmp_path)

        state.update_market_conditions(spot_price=123.0)

        assert state.dirty is False
        reloaded = _load(tmp_path)
        assert reloaded.portfolio.spot_price == pytest.approx(123.0)


class TestDestructiveOpsRequireConfirm:
    """remove_position / clear_positions refuse without confirm=True."""

    def test_remove_position_without_confirm_is_refused(
        self,
        tmp_path: Path,
    ) -> None:
        state = _load(tmp_path)
        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.CALL,
        )

        with pytest.raises(ConfirmationRequiredError):
            state.remove_position(0)

        assert len(state.portfolio.positions) == 1

    def test_remove_position_with_confirm_succeeds(
        self,
        tmp_path: Path,
    ) -> None:
        state = _load(tmp_path)
        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.CALL,
        )

        state.remove_position(0, confirm=True)

        assert state.portfolio.positions == []
        assert state.dirty is False

    def test_clear_positions_without_confirm_is_refused(
        self,
        tmp_path: Path,
    ) -> None:
        state = _load(tmp_path)
        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.CALL,
        )

        with pytest.raises(ConfirmationRequiredError):
            state.clear_positions()

        assert len(state.portfolio.positions) == 1

    def test_clear_positions_with_confirm_succeeds(
        self,
        tmp_path: Path,
    ) -> None:
        state = _load(tmp_path)
        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.CALL,
        )

        state.clear_positions(confirm=True)

        assert state.portfolio.positions == []
        assert state.dirty is False


class TestAtomicAutosave:
    """A failed autosave never leaves a partial file, and dirty stays True."""

    def test_failed_autosave_leaves_no_partial_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = _load(tmp_path)

        _force_autosave_failure(state, monkeypatch)

        assert state.dirty is True
        assert not (tmp_path / STATE_FILENAME).exists()
        assert not (tmp_path / f"{STATE_FILENAME}.tmp").exists()


class TestImportOverUnsavedChanges:
    """import_portfolio refuses to discard unsaved work without confirm=True."""

    def test_import_without_confirm_is_refused_when_dirty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = _load(tmp_path)
        _force_autosave_failure(state, monkeypatch)
        assert state.dirty is True

        with pytest.raises(ConfirmationRequiredError):
            state.import_portfolio(tmp_path / "whatever.json")

    def test_import_with_confirm_succeeds_when_dirty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = _load(tmp_path)
        _force_autosave_failure(state, monkeypatch)
        assert state.dirty is True
        import_source = _other_portfolio_export(tmp_path, "import_me.json")

        state.import_portfolio(import_source, confirm=True)

        assert state.dirty is False
        assert state.portfolio.symbol == "OTHER"

    def test_import_without_confirm_succeeds_when_clean(
        self,
        tmp_path: Path,
    ) -> None:
        state = _load(tmp_path)
        assert state.dirty is False
        import_source = _other_portfolio_export(tmp_path, "import_me.json")

        state.import_portfolio(import_source)

        assert state.portfolio.symbol == "OTHER"


class TestSharedObjectIdentity:
    """Two readers of one ProgramState see the same live portfolio object."""

    def test_repeated_reads_return_the_same_object(
        self,
        tmp_path: Path,
    ) -> None:
        state = _load(tmp_path)

        assert state.portfolio is state.portfolio

    def test_import_replaces_the_object(self, tmp_path: Path) -> None:
        state = _load(tmp_path)
        original = state.portfolio
        import_source = _other_portfolio_export(tmp_path, "import_me.json")

        state.import_portfolio(import_source)

        assert state.portfolio is not original


def test_create_empty_portfolio_used_for_fresh_state(tmp_path: Path) -> None:
    """Sanity check: the empty-book path matches the factory's own shape."""
    baseline = create_empty_portfolio(
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state = _load(tmp_path)

    assert state.portfolio.positions == baseline.positions
    assert state.portfolio.spot_price == pytest.approx(baseline.spot_price)
