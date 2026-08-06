"""Tests for ops/backup-exports.sh.

No shell-test framework exists in this repo, so this drives the actual
script via ``subprocess`` against a scratch ``DELTADEWA_REPO_DIR`` and a
local **bare** git repo standing in for the Codeberg remote — ``git
push`` mechanics don't care that the remote is local rather than SSH, so
this exercises the real success/failure paths with no network involved.

``tests/test_ops/`` is a deliberate mirror-convention deviation: ``ops/``
isn't part of the ``deltadewa`` package, so it has no natural
``tests/test_<pkg>/`` home; naming this directory after ``ops/`` directly
is flagged here rather than silently placed somewhere that doesn't match
its subject — the same flag-rather-than-silently-deviate move used for
this milestone's ``deltadewa/reporting/weekly_report.py`` vs. the
prompt's example ``deltadewa.jobs.weekly_report`` path.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent.parent / "ops" / "backup-exports.sh"
_BASH = shutil.which("bash") or "/bin/bash"
_GIT = shutil.which("git") or "/usr/bin/git"


def _run(
    repo_dir: Path,
    remote_url: Path | str,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DELTADEWA_REPO_DIR": str(repo_dir),
        "DELTADEWA_BACKUP_REMOTE_URL": str(remote_url),
    }
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [_BASH, str(_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [_GIT, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    _git("init", "-q", "--bare", str(remote), cwd=tmp_path)
    return remote


def _seeded_exports(tmp_path: Path) -> tuple[Path, Path]:
    """A scratch app repo dir with a one-file exports/, and a bare remote."""
    repo_dir = tmp_path / "app"
    exports = repo_dir / "exports"
    exports.mkdir(parents=True)
    (exports / "program_state.json").write_text('{"positions": []}')
    return repo_dir, _bare_remote(tmp_path)


class TestBackupExportsScript:
    """ops/backup-exports.sh: commit-and-push exports/, idempotently."""

    def test_dirty_tree_commits_and_pushes(self, tmp_path: Path) -> None:
        repo_dir, remote = _seeded_exports(tmp_path)

        result = _run(repo_dir, remote)

        assert result.returncode == 0, result.stderr
        assert "pushed" in result.stdout
        log = _git("log", "--oneline", "main", cwd=remote)
        assert log.stdout.strip() != ""

    def test_clean_tree_is_a_quiet_no_op(self, tmp_path: Path) -> None:
        repo_dir, remote = _seeded_exports(tmp_path)
        first = _run(repo_dir, remote)
        assert first.returncode == 0, first.stderr
        exports = repo_dir / "exports"
        first_commit = _git("rev-parse", "HEAD", cwd=exports).stdout.strip()

        second = _run(repo_dir, remote)

        assert second.returncode == 0, second.stderr
        assert "nothing to commit" in second.stdout
        second_commit = _git("rev-parse", "HEAD", cwd=exports).stdout.strip()
        assert second_commit == first_commit

    def test_push_failure_exits_nonzero(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "app"
        exports = repo_dir / "exports"
        exports.mkdir(parents=True)
        (exports / "program_state.json").write_text('{"positions": []}')
        nonexistent_remote = tmp_path / "does-not-exist.git"

        result = _run(repo_dir, nonexistent_remote)

        assert result.returncode != 0

    def test_second_dirty_run_adds_a_second_commit(
        self,
        tmp_path: Path,
    ) -> None:
        """A real steady-state cron cycle: content changes, backs up again."""
        repo_dir, remote = _seeded_exports(tmp_path)
        first = _run(repo_dir, remote)
        assert first.returncode == 0, first.stderr

        (repo_dir / "exports" / "reports").mkdir()
        (repo_dir / "exports" / "reports" / "digest-2026-08-05.md").write_text(
            "# Weekly Digest\n",
        )
        second = _run(repo_dir, remote)

        assert second.returncode == 0, second.stderr
        assert "pushed" in second.stdout
        log = _git("log", "--oneline", "main", cwd=remote)
        assert len(log.stdout.strip().splitlines()) == 2
