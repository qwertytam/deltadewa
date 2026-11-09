"""Tests for ``python -m deltadewa.history_cli`` and ``take_mark`` (#313).

The history starts once, at the opening mark; at most one mark per program
date; a mark is never stamped with a date other than the one it was priced
on.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.history_cli import main, take_mark
from deltadewa.state import ProgramState
from tests.clock_helpers import days_from_today

if TYPE_CHECKING:
    from pathlib import Path

_IPS = "missing-ips.yaml"


def _load(export_dir: Path) -> ProgramState:
    return ProgramState.load(
        export_dir,
        ips_path=export_dir / _IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        examples_dir=export_dir / "no-examples",
    )


@pytest.fixture
def state(tmp_path: Path) -> ProgramState:
    """A state holding one long put."""
    loaded = _load(tmp_path)
    loaded.add_position(
        strike_price=4200.0,
        maturity_date=days_from_today(365),
        quantity=10,
        option_type=OptionType.PUT,
    )
    return loaded


def _cli(export_dir: Path, command: str) -> int:
    return main(
        [
            command,
            "--export-dir",
            str(export_dir),
            "--ips-path",
            str(export_dir / _IPS),
        ],
    )


class TestTakeMark:
    """One mark per program date; the first one opens the history."""

    def test_first_mark_opens_the_history(self, state: ProgramState) -> None:
        """Nothing recorded yet: this mark is where the history starts."""
        outcome = take_mark(state, written_by="test")
        assert outcome.written
        assert outcome.mark is not None
        assert outcome.mark.is_opening
        assert outcome.mark.written_by == "test"
        assert "starts here" in outcome.message
        assert state.history is not None
        assert state.history.history_start == outcome.mark.mark_date

    def test_same_day_keeps_the_first(self, state: ProgramState) -> None:
        """A boundary is computed once and reused, not recomputed."""
        first = take_mark(state, written_by="test")
        state.update_market_conditions(spot_price=4000.0)
        second = take_mark(state, written_by="test")
        assert not second.written
        assert second.mark == first.mark
        assert "kept the" in second.message

    def test_other_report_date_takes_no_mark(
        self,
        state: ProgramState,
    ) -> None:
        """The book is priced today; it cannot be marked as of last week."""
        book_date = state.portfolio.valuation_date.date()
        outcome = take_mark(
            state,
            written_by="test",
            as_of=book_date - timedelta(days=7),
        )
        assert outcome.mark is None
        assert not outcome.written
        assert f"priced on {book_date}" in outcome.message
        assert state.history is not None
        assert not state.history.exists() or not state.history.load().marks

    def test_no_store_is_an_error(self, state: ProgramState) -> None:
        """A state built without a store cannot be marked silently."""
        state._history = None  # simulate a directly-built state
        with pytest.raises(RuntimeError, match="no history store"):
            take_mark(state, written_by="test")


class TestCli:
    """``init``, ``mark`` and ``status``."""

    def test_status_before_start(
        self,
        state: ProgramState,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Before init, status says how to start rather than inventing data."""
        assert state.history is not None
        assert _cli(tmp_path, "status") == 0
        assert "has not started" in capsys.readouterr().out

    def test_init_once(
        self,
        state: ProgramState,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Init writes the opening mark; a second init is refused."""
        assert state.history is not None
        assert _cli(tmp_path, "init") == 0
        assert "starts here" in capsys.readouterr().out
        assert _cli(tmp_path, "init") == 1
        assert "already started" in capsys.readouterr().err
        assert len(state.history.load().marks) == 1

    def test_status_after_init(
        self,
        state: ProgramState,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """One mark: a start date, and no carry figure yet."""
        assert state.history is not None
        _cli(tmp_path, "init")
        capsys.readouterr()
        assert _cli(tmp_path, "status") == 0
        out = capsys.readouterr().out
        start = state.history.history_start
        assert f"No position history before {start}." in out
        assert "not yet measurable (one mark)" in out
        assert "Lots reconcile with the history." in out

    def test_mark_is_idempotent_per_day(
        self,
        state: ProgramState,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``mark`` twice on one day keeps one mark."""
        assert state.history is not None
        assert _cli(tmp_path, "mark") == 0
        assert _cli(tmp_path, "mark") == 0
        assert "kept the" in capsys.readouterr().out
        assert len(state.history.load().marks) == 1
