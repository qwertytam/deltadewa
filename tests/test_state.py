"""Tests for deltadewa.state — the shared server-side program state."""

import json
import logging
import threading
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
from tests.clock_helpers import days_from_today

# Seeded off the program clock, not pinned: a fixed literal drifts into
# the past under the clock-shift probe and expires the book (#321/#343).
_MATURITY = days_from_today(365)
_MISSING_IPS = Path("does-not-exist-ips.yaml")
_EXAMPLE_IPS = Path(__file__).parent.parent / "config" / "ips.example.yaml"

# Generous — only reached if something actually deadlocks, so it costs
# nothing on a green run and keeps a red one from hanging the suite.
_JOIN_TIMEOUT = 10.0
# How long a thread that *should* be blocked is given to prove otherwise.
# Short, because a wrong answer here shows up as a fast failure, not a
# flake: without the lock the blocked thread finishes in microseconds.
_BLOCKED_PROBE = 0.3
# Seeded off the program clock, not pinned: a fixed literal drifts into
# the past under the clock-shift probe and expires the book (#321/#343).
_CONCURRENCY_MATURITY = days_from_today(365)


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


def _add_leg(state: ProgramState, strike: float) -> None:
    """Add one put — the smallest thing a mutator thread can do."""
    state.add_position(
        strike_price=strike,
        maturity_date=_CONCURRENCY_MATURITY,
        quantity=1,
        option_type=OptionType.PUT,
    )


def _spawn(target: object, *args: object, **kwargs: object) -> threading.Thread:
    """Start a **daemon** thread for a concurrency test.

    Daemon matters here, and not for tidiness: these tests are designed to
    fail by deadlocking, and a non-daemon thread stuck on a lock keeps the
    interpreter alive at shutdown — so a red run hangs the whole suite
    instead of reporting. As daemons they are abandoned at exit, and the
    ``join(timeout=...)`` assertions are what turn a hang into a failure.
    """
    thread = threading.Thread(
        target=target,
        args=args,
        kwargs=kwargs,
        daemon=True,
    )
    thread.start()
    return thread


def _pause_first_write(
    monkeypatch: pytest.MonkeyPatch,
    entered: threading.Event,
    release: threading.Event,
) -> None:
    """Freeze the first autosave *between* its snapshot and its write.

    Patched at the same ``json.dump`` seam ``_force_autosave_failure``
    uses. By the time ``export_to_json`` reaches the dump it has already
    run ``_build_export_data`` — which prices every leg — so the book is
    captured but no bytes are on disk yet. That is exactly the
    lost-update window.

    Only the *first* call pauses; later saves run at full speed, so the
    thread we want to observe racing past the lock is never itself held
    up by this hook.
    """
    real_dump = json.dump
    guard = threading.Lock()
    paused = False

    def _paused_dump(*args: object, **kwargs: object) -> None:
        nonlocal paused
        with guard:
            first = not paused
            paused = True
        if first:
            entered.set()
            release.wait(timeout=_JOIN_TIMEOUT)
        real_dump(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("deltadewa.persistence.json.dump", _paused_dump)


def _pause_import(
    monkeypatch: pytest.MonkeyPatch,
    entered: threading.Event,
    release: threading.Event,
) -> None:
    """Freeze the parse inside ``import_portfolio``, before the swap.

    Holds the import in the window between reading ``dirty`` and
    rebinding ``_portfolio`` — the TOCTOU the lock has to close.
    """
    real_import = PortfolioSerializer.import_portfolio

    def _paused_import(
        self: PortfolioSerializer,
        filepath: str | Path,
        default_exercise_style: ExerciseStyle | None = None,
    ) -> dict[str, object]:
        entered.set()
        release.wait(timeout=_JOIN_TIMEOUT)
        return real_import(
            self,
            filepath,
            default_exercise_style=default_exercise_style,
        )

    monkeypatch.setattr(
        PortfolioSerializer,
        "import_portfolio",
        _paused_import,
    )


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


class TestMarkInputsReviewed:
    """#367: confirm-gated because it erases an existing staleness signal."""

    def test_without_confirm_is_refused(self, tmp_path: Path) -> None:
        state = _load(tmp_path)

        with pytest.raises(ConfirmationRequiredError):
            state.mark_inputs_reviewed()

        assert state.portfolio.stamps.spot_as_of is None

    def test_with_confirm_stamps_every_input(self, tmp_path: Path) -> None:
        state = _load(tmp_path)
        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.CALL,
        )
        fixed_now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)

        state.mark_inputs_reviewed(as_of=fixed_now, confirm=True)

        assert state.portfolio.stamps.spot_as_of == fixed_now
        assert state.portfolio.stamps.risk_free_rate_as_of == fixed_now
        assert state.portfolio.stamps.dividend_yield_as_of == fixed_now
        assert state.portfolio.positions[0].volatility_as_of == fixed_now
        assert state.dirty is False  # the mutation autosaved


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


class TestExternalWriteDetection:
    """#355: the worker can tell when *another* process wrote its file.

    Each test here constructs two independent ``ProgramState`` instances
    against the same ``export_dir`` — one standing in for the live app
    worker, one for the CLI importer running in its own process — and
    never mutates the "worker" instance directly to produce the file
    change. A test that instead wrote through the same object it then
    reads back would prove nothing about the two-process shape #355 is
    actually about (the same lesson #295's regression test already
    taught).
    """

    def test_no_file_yet_reports_no_external_write(
        self,
        tmp_path: Path,
    ) -> None:
        worker = _load(tmp_path)

        assert worker.external_write_detected() is False

    def test_a_write_from_a_second_process_is_detected(
        self,
        tmp_path: Path,
    ) -> None:
        worker = _load(tmp_path)
        assert worker.external_write_detected() is False

        # Stands in for `docker compose exec app python -m
        # deltadewa.app.import_portfolio ...`: a second, independent
        # ProgramState against the same directory, never touching
        # `worker`.
        cli = ProgramState.load(
            tmp_path,
            ips_path=tmp_path / _MISSING_IPS,
            default_exercise_style=ExerciseStyle.EUROPEAN,
            writer_label="import_portfolio_cli",
        )
        cli.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
        )

        assert worker.external_write_detected() is True

    def test_worker_own_saves_do_not_self_report_as_external(
        self,
        tmp_path: Path,
    ) -> None:
        """The worker's own autosave must not trip its own detector."""
        worker = _load(tmp_path)

        worker.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
        )

        assert worker.external_write_detected() is False

    def test_worker_written_by_and_loaded_at_do_not_change_on_their_own(
        self,
        tmp_path: Path,
    ) -> None:
        """The worker never reloads — its own view of the file is frozen.

        This is the field-test near-miss made concrete: after a second
        process writes the file, the worker's in-memory `written_by` /
        `loaded_at` must keep describing *its own* last load or save, not
        silently pick up the other process's write. Only a fresh `.load()`
        (i.e. a restart) sees the new metadata.
        """
        worker = _load(tmp_path)
        worker.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
        )
        worker_written_by_before = worker.written_by
        worker_loaded_at_before = worker.loaded_at
        assert worker_written_by_before == "app"

        cli = ProgramState.load(
            tmp_path,
            ips_path=tmp_path / _MISSING_IPS,
            default_exercise_style=ExerciseStyle.EUROPEAN,
            writer_label="import_portfolio_cli",
        )
        cli.add_position(
            strike_price=200.0,
            maturity_date=_MATURITY,
            quantity=5,
            option_type=OptionType.CALL,
        )

        # The worker, un-reloaded, still reports its own prior write.
        assert worker.written_by == worker_written_by_before
        assert worker.loaded_at == worker_loaded_at_before
        assert worker.portfolio.positions[0].quantity == 1
        assert worker.external_write_detected() is True

        # Only a fresh load (a restart) sees the CLI's write — the file
        # now holds both positions, since `cli` loaded the worker's prior
        # save before adding its own.
        restarted = _load(tmp_path)
        assert restarted.written_by == "import_portfolio_cli"
        assert len(restarted.portfolio.positions) == 2
        assert restarted.portfolio.positions[1].quantity == 5
        assert restarted.external_write_detected() is False

    def test_writer_label_defaults_to_app(self, tmp_path: Path) -> None:
        state = _load(tmp_path)
        state.add_position(
            strike_price=100.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
        )

        assert state.written_by == "app"

        raw = json.loads((tmp_path / STATE_FILENAME).read_text())
        assert raw["metadata"]["written_by"] == "app"


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


class TestConcurrency:
    """#299: one RLock over mutate+save, snapshots, and the import swap.

    Every case here forces its interleaving with ``threading.Event``\\ s
    rather than sleeping, so each one genuinely fails with the lock
    removed rather than passing by construction.

    What they deliberately do *not* cover, because no assertion could:
    the reader path (``ProgramState.portfolio`` is unlocked on purpose, so
    a reader seeing a mid-flight book is permitted by the design, not a
    bug) and the process-global QuantLib evaluation date. Both are
    field-test territory — see the ``deltadewa.state`` module docstring.
    """

    def test_a_second_mutator_waits_for_an_in_flight_save(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The lock is actually held across the save, not just the flag."""
        state = _load(tmp_path)
        entered, release = threading.Event(), threading.Event()
        _pause_first_write(monkeypatch, entered, release)

        first = _spawn(_add_leg, state, 100.0)
        assert entered.wait(timeout=_JOIN_TIMEOUT), "save never started"

        second = _spawn(_add_leg, state, 110.0)
        # The whole point: while the first save holds the lock, the second
        # mutator must not get in. Without the lock it sails straight
        # through and this assertion fails.
        second.join(timeout=_BLOCKED_PROBE)
        assert second.is_alive(), "second mutator was not blocked by the lock"

        release.set()
        first.join(timeout=_JOIN_TIMEOUT)
        second.join(timeout=_JOIN_TIMEOUT)
        assert not first.is_alive()
        assert not second.is_alive()
        assert len(state.portfolio.positions) == 2

    def test_a_slow_save_cannot_revert_a_newer_one(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The lost update #299 is really about — not a torn file.

        Both writes are individually atomic (tmp-then-rename), so the file
        is never corrupt either way. The bug is ordering: an older
        snapshot landing on top of a newer one and then clearing ``dirty``,
        so the newer change is gone and nothing will re-save it. Unlocked,
        the reloaded book here holds one position; locked, it holds both.
        """
        state = _load(tmp_path)
        entered, release = threading.Event(), threading.Event()
        _pause_first_write(monkeypatch, entered, release)

        slow = _spawn(_add_leg, state, 100.0)
        assert entered.wait(timeout=_JOIN_TIMEOUT), "save never started"

        newer = _spawn(_add_leg, state, 110.0)
        newer.join(timeout=_BLOCKED_PROBE)

        release.set()
        slow.join(timeout=_JOIN_TIMEOUT)
        newer.join(timeout=_JOIN_TIMEOUT)

        assert state.dirty is False
        reloaded = _load(tmp_path)
        assert len(reloaded.portfolio.positions) == 2

    def test_a_mutator_cannot_interleave_into_an_in_flight_import(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The dirty-check and the portfolio swap are one atomic unit.

        Unlocked, ``import_portfolio`` reads ``dirty``, then parses, then
        rebinds ``_portfolio`` — a mutation landing in that gap is applied
        to the book the import is about to throw away, and disappears with
        no error. The lock closes the gap by holding it across the parse.
        """
        state = _load(tmp_path)
        source = _other_portfolio_export(tmp_path, "to-import.json")
        entered, release = threading.Event(), threading.Event()
        _pause_import(monkeypatch, entered, release)

        importer = _spawn(state.import_portfolio, source, confirm=True)
        assert entered.wait(timeout=_JOIN_TIMEOUT), "import never started"

        mutator = _spawn(_add_leg, state, 100.0)
        mutator.join(timeout=_BLOCKED_PROBE)
        assert mutator.is_alive(), "mutation slipped into the import window"

        release.set()
        importer.join(timeout=_JOIN_TIMEOUT)
        mutator.join(timeout=_JOIN_TIMEOUT)

        # The imported book (1 leg) plus the mutation that waited its
        # turn — the mutation is applied after the swap, not silently
        # dropped onto the discarded portfolio.
        assert len(state.portfolio.positions) == 2
        assert state.portfolio.get_symbol() == "OTHER"

    def test_nested_mutate_and_save_does_not_deadlock(
        self,
        tmp_path: Path,
    ) -> None:
        """RLock, not Lock — the call graph nests three deep.

        ``import_portfolio`` -> ``_mutate_and_save`` -> ``save_if_dirty``
        all take the same lock. With a non-reentrant ``Lock`` this hangs
        on the first mutation, so this is the test that catches anyone
        later "simplifying" the RLock away.
        """
        state = _load(tmp_path)
        source = _other_portfolio_export(tmp_path, "nested.json")

        done = threading.Event()

        def _exercise_the_nesting() -> None:
            _add_leg(state, 100.0)
            state.import_portfolio(source, confirm=True)
            state.save_if_dirty()
            state.export_snapshot("nested-snapshot.json")
            done.set()

        worker = _spawn(_exercise_the_nesting)
        worker.join(timeout=_JOIN_TIMEOUT)

        assert done.is_set(), "re-entrant acquisition deadlocked"

    def test_concurrent_adds_leave_memory_and_file_agreeing(
        self,
        tmp_path: Path,
    ) -> None:
        """Bounded stress net — deliberately weak, and labelled as such.

        Unlike the four tests above, **this one can pass with the bug
        present**: it depends on thread timing rather than forcing an
        interleaving. It is here to catch the crash-shaped failures (a
        ``RuntimeError`` from iterating a list mid-append, a torn file
        that won't parse), not to prove the lock exists. Kept small so it
        stays in the gate.
        """
        state = _load(tmp_path)
        threads_count, per_thread = 4, 15
        errors: list[BaseException] = []
        errors_lock = threading.Lock()

        def _worker(worker_id: int) -> None:
            try:
                for n in range(per_thread):
                    state.add_position(
                        strike_price=100.0 + worker_id * 100 + n,
                        maturity_date=_CONCURRENCY_MATURITY,
                        quantity=1,
                        option_type=OptionType.PUT,
                    )
                    # Interleave the locked reader too: this is the path
                    # that used to raise "list changed size during
                    # iteration" against a concurrent append.
                    assert isinstance(state.positions_snapshot(), tuple)
            except BaseException as exc:  # pylint: disable=broad-exception-caught
                with errors_lock:
                    errors.append(exc)

        workers = [_spawn(_worker, i) for i in range(threads_count)]
        for worker in workers:
            worker.join(timeout=_JOIN_TIMEOUT)

        assert not errors, f"concurrent mutation raised: {errors!r}"
        expected = threads_count * per_thread
        assert len(state.portfolio.positions) == expected
        assert state.dirty is False

        reloaded = _load(tmp_path)
        assert len(reloaded.portfolio.positions) == expected


def test_create_empty_portfolio_used_for_fresh_state(tmp_path: Path) -> None:
    """Sanity check: the empty-book path matches the factory's own shape."""
    baseline = create_empty_portfolio(
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state = _load(tmp_path)

    assert state.portfolio.positions == baseline.positions
    assert state.portfolio.spot_price == pytest.approx(baseline.spot_price)
