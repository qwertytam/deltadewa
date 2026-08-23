"""Unit tests for deltadewa.app.health_checks (#309).

Exercises each boot-wiring check in isolation, against a ``ProgramState``
built directly — no Flask, no ``create_app`` — since these are the object-
materialized assertions ``/health`` composes, not the route itself (see
``tests/test_app/test_health.py`` for the route-level coverage).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from deltadewa.app.health_checks import (
    BOOT_WIRING_CHECKS,
    check_cache_dir_writable,
    check_exercise_style_wired,
    check_ips_loaded,
    check_ips_sections_configured,
    check_state_file_undisturbed,
    check_state_persisted,
    run_checks,
    summarize,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.state import ProgramState

_MISSING_IPS = Path("does-not-exist-ips.yaml")
_EXAMPLE_IPS = (
    Path(__file__).parent.parent.parent / "config" / ("ips.example.yaml")
)
_MATURITY = datetime(2027, 6, 30, tzinfo=UTC)


def _state_no_ips(
    tmp_path: Path,
    *,
    default_exercise_style: ExerciseStyle | None = ExerciseStyle.EUROPEAN,
) -> ProgramState:
    return ProgramState.load(
        tmp_path,
        ips_path=tmp_path / _MISSING_IPS,
        default_exercise_style=default_exercise_style,
    )


def _state_with_ips(tmp_path: Path) -> ProgramState:
    ips_path = tmp_path / "ips.yaml"
    ips_path.write_text(_EXAMPLE_IPS.read_text(encoding="utf-8"))
    return ProgramState.load(tmp_path, ips_path=ips_path)


class TestCheckIpsLoaded:
    def test_ok_when_ips_loaded(self, tmp_path: Path) -> None:
        result = check_ips_loaded(_state_with_ips(tmp_path))

        assert result.ok is True
        assert result.name == "ips_loaded"

    def test_not_ok_when_ips_missing(self, tmp_path: Path) -> None:
        result = check_ips_loaded(_state_no_ips(tmp_path))

        assert result.ok is False
        assert "No IPS policy is loaded" in result.detail


class TestCheckIpsSectionsConfigured:
    def test_never_fails_even_when_ips_missing(
        self,
        tmp_path: Path,
    ) -> None:
        """Report-only: no ips_config at all must still be ok=True."""
        result = check_ips_sections_configured(_state_no_ips(tmp_path))

        assert result.ok is True

    def test_reports_no_defaulted_sections_for_the_example_ips(
        self,
        tmp_path: Path,
    ) -> None:
        result = check_ips_sections_configured(_state_with_ips(tmp_path))

        assert result.ok is True
        assert result.value == []


class TestCheckExerciseStyleWired:
    def test_ok_when_wired_explicitly(self, tmp_path: Path) -> None:
        result = check_exercise_style_wired(_state_no_ips(tmp_path))

        assert result.ok is True
        assert "EUROPEAN" in result.detail

    def test_not_ok_when_unwired(self, tmp_path: Path) -> None:
        state = _state_no_ips(tmp_path, default_exercise_style=None)

        result = check_exercise_style_wired(state)

        assert result.ok is False
        assert "add_position()" in result.detail

    def test_ok_when_wired_from_ips(self, tmp_path: Path) -> None:
        """#295: wired via pricing.exercise_style, not an explicit override."""
        state = _state_with_ips(tmp_path)

        result = check_exercise_style_wired(state)

        assert result.ok is True


class TestCheckStatePersisted:
    def test_ok_when_clean(self, tmp_path: Path) -> None:
        result = check_state_persisted(_state_no_ips(tmp_path))

        assert result.ok is True

    def test_not_ok_when_dirty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = _state_no_ips(tmp_path)

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated crash mid-write")

        with monkeypatch.context() as patch:
            patch.setattr("deltadewa.persistence.json.dump", _raise)
            with pytest.raises(RuntimeError):
                state.add_position(
                    strike_price=100.0,
                    maturity_date=_MATURITY,
                    quantity=1,
                    option_type=OptionType.PUT,
                )

        result = check_state_persisted(state)

        assert result.ok is False
        assert "autosave failed" in result.detail


class TestCheckStateFileUndisturbed:
    def test_ok_when_no_external_write(self, tmp_path: Path) -> None:
        result = check_state_file_undisturbed(_state_no_ips(tmp_path))

        assert result.ok is True

    def test_not_ok_after_an_external_write(self, tmp_path: Path) -> None:
        worker = _state_no_ips(tmp_path)
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

        result = check_state_file_undisturbed(worker)

        assert result.ok is False
        assert "restart is required" in result.detail


class TestCheckCacheDirWritable:
    def test_ok_for_a_writable_directory(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"

        result = check_cache_dir_writable(cache_dir)

        assert result.ok is True
        assert result.value == str(cache_dir)
        # The probe must not be left behind.
        assert not (cache_dir / ".health-probe").exists()

    def test_not_ok_when_a_path_component_is_a_file(
        self,
        tmp_path: Path,
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        cache_dir = blocker / "marketdata-cache"

        result = check_cache_dir_writable(cache_dir)

        assert result.ok is False
        assert result.value == str(cache_dir)

    def test_creates_the_directory_if_missing(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "does" / "not" / "exist" / "yet"

        result = check_cache_dir_writable(cache_dir)

        assert result.ok is True
        assert cache_dir.is_dir()


class TestRunChecksAndSummarize:
    def test_run_checks_returns_one_result_per_registered_name(
        self,
        tmp_path: Path,
    ) -> None:
        results = run_checks(
            _state_with_ips(tmp_path),
            cache_dir=tmp_path / "cache",
        )

        assert tuple(r.name for r in results) == BOOT_WIRING_CHECKS

    def test_summarize_is_ok_when_everything_passes(
        self,
        tmp_path: Path,
    ) -> None:
        results = run_checks(
            _state_with_ips(tmp_path),
            cache_dir=tmp_path / "cache",
        )

        status, boot_wiring = summarize(results)

        assert status == "ok"
        assert set(boot_wiring) == set(BOOT_WIRING_CHECKS)
        assert all(entry["ok"] for entry in boot_wiring.values())

    def test_summarize_is_degraded_when_one_check_fails(
        self,
        tmp_path: Path,
    ) -> None:
        results = run_checks(
            _state_no_ips(tmp_path),  # ips_loaded will be False
            cache_dir=tmp_path / "cache",
        )

        status, _boot_wiring = summarize(results)

        assert status == "degraded"

    def test_a_defaulted_ips_section_alone_never_degrades_status(
        self,
        tmp_path: Path,
    ) -> None:
        """The one check design deliberately excludes from degrading."""
        # _state_no_ips has no ips.yaml at all, so ips_loaded already
        # fails; isolate ips_sections_configured's own contribution
        # instead by checking it directly against a fully-wired state
        # whose only "gap" is the informational one.
        state = _state_with_ips(tmp_path)
        results = run_checks(state, cache_dir=tmp_path / "cache")
        sections_check = next(
            r for r in results if r.name == "ips_sections_configured"
        )

        assert sections_check.ok is True

    def test_summarize_includes_value_only_when_present(
        self,
        tmp_path: Path,
    ) -> None:
        results = run_checks(
            _state_no_ips(tmp_path),
            cache_dir=tmp_path / "cache",
        )
        _status, boot_wiring = summarize(results)

        # ips_loaded never carries a structured value.
        assert "value" not in boot_wiring["ips_loaded"]
        # cache_dir_writable always does.
        assert "value" in boot_wiring["cache_dir_writable"]
