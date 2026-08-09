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

import http.server
import os
import shutil
import socket
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).parent.parent.parent / "ops" / "backup-exports.sh"
_BASH = shutil.which("bash") or "/bin/bash"
_GIT = shutil.which("git") or "/usr/bin/git"

# Vars the real environment might have set (a developer's own shell, or a
# CI secret) that would silently make a "heartbeat unconfigured" test
# stop being that test. Stripped from every _run() unless a test opts
# in via extra_env.
_HEARTBEAT_ENV_VARS = ("BACKUP_HEARTBEAT_URL",)


def _run(
    repo_dir: Path,
    remote_url: Path | str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DELTADEWA_REPO_DIR": str(repo_dir),
        "DELTADEWA_BACKUP_REMOTE_URL": str(remote_url),
    }
    for var in _HEARTBEAT_ENV_VARS:
        env.pop(var, None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [_BASH, str(_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    """Records the path of every GET it receives; replies 200 empty."""

    received_paths: list[str] = []  # ruff: ignore[mutable-class-default]

    def do_GET(self) -> None:
        self.__class__.received_paths.append(self.path)
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr access log — tests are quiet."""


@pytest.fixture
def heartbeat_server() -> Iterator[tuple[str, list[str]]]:
    """A local HTTP server standing in for healthchecks.io.

    No live network call and no new dependency (``http.server`` is
    stdlib) — binds to an ephemeral loopback port and records the path
    of every request it receives, so a test can assert a ping fired
    without trusting curl's own exit code alone.
    """
    _RecordingHandler.received_paths = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (
            f"http://127.0.0.1:{server.server_port}/ping",
            _RecordingHandler.received_paths,
        )
    finally:
        server.shutdown()
        thread.join()


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


def _closed_local_port_url() -> str:
    """A loopback URL nothing is listening on — a reliable connection-
    refused target, for testing the "ping fails, job doesn't" contract
    without depending on an actual unreachable host (slow, flaky in CI).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}/ping"


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


class TestDubiousOwnershipBreaksThePush:
    """Pins the #237 failure mode directly, independent of the
    entrypoint script: if exports/ or .git/ ever ends up owned by
    something other than the uid running this cron, git's
    dubious-ownership guard (safe.directory, default since git 2.35.2)
    fails every git command on the repo, and this script has no
    fallback — the push just doesn't happen. This is the regression
    trip-wire: if something ever starts re-owning exports/ or .git
    again (the entrypoint or anything else), this is what actually
    breaks, regardless of what caused it.

    ``GIT_TEST_ASSUME_DIFFERENT_OWNER`` is a real git-internal test hook
    (used by git's own test suite for this exact code path) that
    simulates the ownership mismatch without needing to actually chown
    to a different uid — which needs privilege this dev environment and
    most CI runners don't reliably have.
    """

    def test_dubious_ownership_fails_the_push(self, tmp_path: Path) -> None:
        repo_dir, remote = _seeded_exports(tmp_path)
        first = _run(repo_dir, remote)
        assert first.returncode == 0, first.stderr

        (repo_dir / "exports" / "reports").mkdir()
        (repo_dir / "exports" / "reports" / "x.md").write_text("x")

        result = _run(
            repo_dir,
            remote,
            {"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"},
        )

        # The exact message differs by which git subcommand hits the
        # guard first (git-config's is more generic than git-status's),
        # so assert on the shape — a fatal error, non-zero exit — not
        # one specific string.
        assert result.returncode != 0
        assert "fatal:" in result.stderr


class TestBackupHeartbeat:
    """BACKUP_HEARTBEAT_URL: pings on success, never on failure, never
    fails the job it's reporting on — see ops/backup-exports.sh's
    ping_heartbeat() and deltadewa/heartbeat.py's ping() for the same
    contract on the Python side.
    """

    def test_pings_on_a_real_push(
        self,
        tmp_path: Path,
        heartbeat_server: tuple[str, list[str]],
    ) -> None:
        url, received = heartbeat_server
        repo_dir, remote = _seeded_exports(tmp_path)

        result = _run(repo_dir, remote, {"BACKUP_HEARTBEAT_URL": url})

        assert result.returncode == 0, result.stderr
        assert "pushed" in result.stdout
        assert received == ["/ping"]

    def test_pings_on_a_clean_noop(
        self,
        tmp_path: Path,
        heartbeat_server: tuple[str, list[str]],
    ) -> None:
        url, received = heartbeat_server
        repo_dir, remote = _seeded_exports(tmp_path)
        first = _run(repo_dir, remote)
        assert first.returncode == 0, first.stderr
        received.clear()  # only care about the no-op run below

        second = _run(repo_dir, remote, {"BACKUP_HEARTBEAT_URL": url})

        assert second.returncode == 0, second.stderr
        assert "nothing to commit" in second.stdout
        assert received == ["/ping"]

    def test_unconfigured_skips_the_ping_quietly(
        self,
        tmp_path: Path,
    ) -> None:
        repo_dir, remote = _seeded_exports(tmp_path)

        result = _run(repo_dir, remote)

        assert result.returncode == 0, result.stderr
        assert "not configured, skipping heartbeat ping" in result.stdout

    def test_a_failed_ping_does_not_fail_the_job(
        self,
        tmp_path: Path,
    ) -> None:
        """The push still succeeds even when the heartbeat URL refuses
        the connection — a dead-man's switch must never itself become a
        new way for the backup to appear to fail.
        """
        repo_dir, remote = _seeded_exports(tmp_path)
        unreachable = _closed_local_port_url()

        result = _run(repo_dir, remote, {"BACKUP_HEARTBEAT_URL": unreachable})

        assert result.returncode == 0, result.stderr
        assert "pushed" in result.stdout
        assert "heartbeat ping failed" in result.stderr
