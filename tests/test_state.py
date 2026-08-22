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
_EXAMPLE_IPS = Path(__file__).parent.parent / "config" / "ips.example.yaml"


def _load(tmp_path: Path) -> ProgramState:
    return ProgramState.load(
        tmp_path,
        ips_path=tmp_path / _MISSING_IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )


def _write_ips_fixture(tmp_path: Path) -> Path:
    """Copy the real example IPS to *tmp_path*, valid and self-contained.

    ``pricing.exercise_style: EUROPEAN`` in this file is what #295's
    regression test relies on the boot path to pick up on its own —
    unlike ``_load()`` above, nothing here passes
    ``default_exercise_style=`` explicitly.
    """
    fixture_path = tmp_path / "ips.yaml"
    fixture_path.write_text(
        _EXAMPLE_IPS.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return fixture_path


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


class TestBootWiresExerciseStyleFromIps:
    """#295: pricing.exercise_style must reach the portfolio at boot.

    Every case here calls ``ProgramState.load()`` — the same classmethod
    ``wsgi.py``, ``weekly_report.py`` and ``import_portfolio.py`` call to
    boot — without passing ``default_exercise_style=``, so a green test
    here means the real boot path wires it, not that a test double does.
    A test that built an ``OptionPortfolio`` directly and set the style
    itself would pass even with the bug present (#295's own postmortem:
    that is exactly the blind spot that let it ship).
    """

    def test_empty_start_wires_style_from_ips(self, tmp_path: Path) -> None:
        """No prior state file — the empty-portfolio branch still wires it."""
        ips_path = _write_ips_fixture(tmp_path)

        state = ProgramState.load(tmp_path, ips_path=ips_path)

        assert state.loaded_from is None
        assert state.portfolio.default_exercise_style is ExerciseStyle.EUROPEAN

    def test_reload_from_existing_state_file_wires_style_from_ips(
        self,
        tmp_path: Path,
    ) -> None:
        """A restart re-reading program_state.json still wires it.

        Regression-specific: this is the branch a deployed app actually
        takes on every restart once a book has been imported once — the
        one #295 left broken, since ``import_from_json`` received
        whatever ``default_exercise_style`` its caller passed, and no
        real caller passed anything.
        """
        ips_path = _write_ips_fixture(tmp_path)
        first = ProgramState.load(tmp_path, ips_path=ips_path)
        first.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
            exercise_style=ExerciseStyle.EUROPEAN,
        )

        second = ProgramState.load(tmp_path, ips_path=ips_path)

        assert second.loaded_from == tmp_path / STATE_FILENAME
        assert second.portfolio.default_exercise_style is ExerciseStyle.EUROPEAN

    def test_explicit_override_still_wins_over_ips(
        self,
        tmp_path: Path,
    ) -> None:
        """A caller-supplied style is not overwritten by the IPS default."""
        ips_path = _write_ips_fixture(tmp_path)

        state = ProgramState.load(
            tmp_path,
            ips_path=ips_path,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        assert state.portfolio.default_exercise_style is ExerciseStyle.AMERICAN

    def test_missing_ips_leaves_style_none_as_before(
        self,
        tmp_path: Path,
    ) -> None:
        """No IPS to read from — unchanged pre-#295 behaviour, not a crash."""
        state = ProgramState.load(
            tmp_path,
            ips_path=tmp_path / _MISSING_IPS,
        )

        assert state.portfolio.default_exercise_style is None


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

    def test_add_position_entry_premium(self, tmp_path: Path) -> None:
        """entry_premium round-trips through the real save/load path."""
        state = _load(tmp_path)

        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=5,
            option_type=OptionType.CALL,
            entry_premium=12.34,
        )

        assert state.dirty is False
        reloaded = _load(tmp_path)
        assert reloaded.portfolio.positions[0].entry_premium == pytest.approx(
            12.34
        )

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

    def test_set_underlying_quantity(self, tmp_path: Path) -> None:
        state = _load(tmp_path)

        state.set_underlying_quantity(500.0)

        assert state.dirty is False
        reloaded = _load(tmp_path)
        assert reloaded.portfolio.underlying_quantity == pytest.approx(500.0)

    def test_update_market_conditions(self, tmp_path: Path) -> None:
        state = _load(tmp_path)

        state.update_market_conditions(spot_price=123.0)

        assert state.dirty is False
        reloaded = _load(tmp_path)
        assert reloaded.portfolio.spot_price == pytest.approx(123.0)


class TestExportSnapshot:
    """export_snapshot: a read-only, non-autosave copy of the live book."""

    def test_writes_a_distinct_file_without_touching_dirty(
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
        assert state.dirty is False

        written = state.export_snapshot("snapshot.json")

        assert written == tmp_path / "snapshot.json"
        assert written.exists()
        assert written != tmp_path / STATE_FILENAME
        assert state.dirty is False

        # The snapshot round-trips through the same importer as any
        # other export, independent of this ProgramState.
        reimported = PortfolioSerializer(
            export_dir=tmp_path,
        ).import_from_json(written)
        assert len(reimported["portfolio"].positions) == 1


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


class TestMonteCarloScenarioLocalGuard:
    """A scenario-local Monte Carlo run must not dirty or autosave state.

    Mirrors tests/test_app/test_monitor.py::TestScenarioLocalGuard's
    guarantee for the monitor's quantity dial, applied here to the
    Monte Carlo cache (F6): a what-if run reached via
    ``state.portfolio.run_monte_carlo_simulation(..., persist_cache=False)``
    must never touch ``ProgramState``'s dirty flag or write to ``exports/``.
    """

    def test_scenario_local_run_leaves_state_untouched(
        self,
        tmp_path: Path,
    ) -> None:
        state = _load(tmp_path)
        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
        )
        assert state.dirty is False
        before_files = set(tmp_path.iterdir())

        state.portfolio.run_monte_carlo_simulation(
            num_simulations=1000,
            expected_return=0.15,
            persist_cache=False,
        )

        assert state.dirty is False
        after_files = set(tmp_path.iterdir())
        assert after_files == before_files


def test_create_empty_portfolio_used_for_fresh_state(tmp_path: Path) -> None:
    """Sanity check: the empty-book path matches the factory's own shape."""
    baseline = create_empty_portfolio(
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state = _load(tmp_path)

    assert state.portfolio.positions == baseline.positions
    assert state.portfolio.spot_price == pytest.approx(baseline.spot_price)
