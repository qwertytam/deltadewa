"""Tests for ops/backup-exports.sh.

No shell-test framework exists in this repo, so this drives the actual
script via ``subprocess`` against a scratch ``DELTADEWA_REPO_DIR`` and a
local **bare** git repo standing in for the offsite backup remote — ``git
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
import json
import os
import shutil
import socket
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import threading
import time
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
    remote_url: Path | str | None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DELTADEWA_REPO_DIR": str(repo_dir),
        # GitHub-hosted Actions runners ship an unconditional
        # `safe.directory = *` in the SYSTEM git config
        # (/etc/gitconfig) — confirmed by inspecting a live runner —
        # which exempts every path from the dubious-ownership guard
        # regardless of real or GIT_TEST_ASSUME_DIFFERENT_OWNER-
        # simulated ownership. git's own ownership check only ever
        # consults system + global config (never repo-local, by
        # design), so blanking both here makes this suite's git
        # behaviour depend on the script under test, not on whatever
        # a given CI image or developer machine happens to have
        # baked into its own config. Without this,
        # TestDubiousOwnershipBreaksThePush is a false negative on
        # any host carrying that exemption.
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "",
    }
    for var in _HEARTBEAT_ENV_VARS:
        env.pop(var, None)
    # Stripped unconditionally (not just via _HEARTBEAT_ENV_VARS' opt-in
    # pattern) so a developer's own shell or a CI secret can never
    # silently supply BACKUP_REMOTE and mask
    # TestBackupRemoteRequired — every test must set it explicitly via
    # remote_url, the one exception being that class itself.
    env.pop("BACKUP_REMOTE", None)
    if remote_url is not None:
        env["BACKUP_REMOTE"] = str(remote_url)
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


def _write_policy(
    repo_dir: Path,
    *,
    content: str = "program:\n  name: test\n",
    version: str | None = "1.2.3",
) -> Path:
    """Seed ``config/ips.yaml`` (and optionally ``pyproject.toml``) under
    a scratch repo_dir, for the #301 policy-snapshot tests below.
    """
    config = repo_dir / "config"
    config.mkdir(parents=True, exist_ok=True)
    policy = config / "ips.yaml"
    policy.write_text(content)
    if version is not None:
        (repo_dir / "pyproject.toml").write_text(
            f'[tool.poetry]\nversion = "{version}"\n',
        )
    return policy


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


class TestCleanTreeHeartbeatVerification:
    """#252: the clean-tree (nothing-to-commit) path must not ping the
    heartbeat on faith alone — it has to confirm the remote actually has
    what the local HEAD thinks it pushed. The four-case matrix:

    1. clean tree, remote reachable, SHA matches -> ping fires, exit 0.
    2. clean tree, remote reachable, SHA mismatch -> no ping, exit != 0.
    3. clean tree, remote unreachable -> no ping, exit != 0.
    4. dirty tree, push succeeds -> ping still fires (unaffected;
       commit-then-push order is untouched by this fix, see lines
       128-131 and the module's push-failure contract).
    """

    def test_reachable_and_equal_pings_and_succeeds(
        self,
        tmp_path: Path,
        heartbeat_server: tuple[str, list[str]],
    ) -> None:
        url, received = heartbeat_server
        repo_dir, remote = _seeded_exports(tmp_path)
        first = _run(repo_dir, remote)
        assert first.returncode == 0, first.stderr

        result = _run(repo_dir, remote, {"BACKUP_HEARTBEAT_URL": url})

        assert result.returncode == 0, result.stderr
        assert "nothing to commit" in result.stdout
        assert received == ["/ping"]

    def test_reachable_but_mismatched_fails_without_pinging(
        self,
        tmp_path: Path,
        heartbeat_server: tuple[str, list[str]],
    ) -> None:
        url, received = heartbeat_server
        repo_dir, remote = _seeded_exports(tmp_path)
        first = _run(repo_dir, remote)
        assert first.returncode == 0, first.stderr

        # Simulate an earlier push that silently didn't land: a local
        # commit exists that the remote never received, while the
        # working tree itself is clean (nothing new to add/commit) —
        # exactly the state a failed `git push` after a successful
        # `git commit` leaves behind.
        exports = repo_dir / "exports"
        _git(
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "phantom: never pushed",
            cwd=exports,
        )

        result = _run(repo_dir, remote, {"BACKUP_HEARTBEAT_URL": url})

        assert result.returncode != 0
        assert "does not match local HEAD" in result.stderr
        assert received == []

    def test_unreachable_remote_fails_without_pinging(
        self,
        tmp_path: Path,
        heartbeat_server: tuple[str, list[str]],
    ) -> None:
        url, received = heartbeat_server
        repo_dir, remote = _seeded_exports(tmp_path)
        first = _run(repo_dir, remote)
        assert first.returncode == 0, first.stderr
        shutil.rmtree(remote)  # the remote is now unreachable

        result = _run(repo_dir, remote, {"BACKUP_HEARTBEAT_URL": url})

        assert result.returncode != 0
        assert "could not reach origin" in result.stderr
        assert received == []

    def test_dirty_tree_push_still_pings_unaffected_by_this_fix(
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


class TestBackupRemoteRequired:
    """BACKUP_REMOTE (#243): no default, no hardcoded fallback — a real
    offsite repo name has no business being a literal in a public script
    (the same leak #245 fixed for ``config/ips.yaml``), so this must fail
    loudly rather than push nowhere or reuse a stale remote.
    """

    def test_unset_fails_loudly(self, tmp_path: Path) -> None:
        repo_dir, _ = _seeded_exports(tmp_path)

        result = _run(repo_dir, None)

        assert result.returncode != 0
        assert "BACKUP_REMOTE" in result.stderr


class TestBackupEnvPrecedence:
    """#253: an explicitly-set environment variable must beat
    ``backup.env`` — a plain ``source`` has no notion of "already set",
    it just assigns, so a bare ``if [ -f ... ]; then source ...; fi``
    used to let the file silently clobber an operator's explicit
    ``BACKUP_REMOTE=... ./backup-exports.sh``. ``DELTADEWA_BACKUP_ENV_FILE``
    (added alongside the fix) points the script at a scratch file instead
    of the real ``/etc/deltadewa/backup.env``, so this doesn't need root
    or touch the real host path.
    """

    def _write_backup_env_file(
        self,
        tmp_path: Path,
        *,
        remote: str | None,
        heartbeat_url: str | None = None,
    ) -> Path:
        env_file = tmp_path / "backup.env"
        lines = []
        if remote is not None:
            lines.append(f"BACKUP_REMOTE={remote}")
        if heartbeat_url is not None:
            lines.append(f"BACKUP_HEARTBEAT_URL={heartbeat_url}")
        env_file.write_text("\n".join(lines) + "\n")
        return env_file

    def test_env_set_and_file_set_env_wins(self, tmp_path: Path) -> None:
        repo_dir, remote = _seeded_exports(tmp_path)
        file_remote = tmp_path / "file-remote-does-not-exist.git"
        env_file = self._write_backup_env_file(
            tmp_path,
            remote=str(file_remote),
        )

        result = _run(
            repo_dir,
            remote,  # the real (env) remote — must be the one used
            {"DELTADEWA_BACKUP_ENV_FILE": str(env_file)},
        )

        assert result.returncode == 0, result.stderr
        assert "pushed" in result.stdout
        assert (
            "BACKUP_REMOTE from environment (overriding backup.env)"
            in result.stdout
        )
        log = _git("log", "--oneline", "main", cwd=remote)
        assert log.stdout.strip() != ""

    def test_env_unset_and_file_set_file_used(self, tmp_path: Path) -> None:
        repo_dir, remote = _seeded_exports(tmp_path)
        env_file = self._write_backup_env_file(tmp_path, remote=str(remote))

        result = _run(
            repo_dir,
            None,  # no BACKUP_REMOTE in the environment
            {"DELTADEWA_BACKUP_ENV_FILE": str(env_file)},
        )

        assert result.returncode == 0, result.stderr
        assert "pushed" in result.stdout
        assert "BACKUP_REMOTE from backup.env" in result.stdout
        log = _git("log", "--oneline", "main", cwd=remote)
        assert log.stdout.strip() != ""

    def test_env_set_and_file_absent_env_used(self, tmp_path: Path) -> None:
        repo_dir, remote = _seeded_exports(tmp_path)
        missing_env_file = tmp_path / "no-such-backup.env"

        result = _run(
            repo_dir,
            remote,
            {"DELTADEWA_BACKUP_ENV_FILE": str(missing_env_file)},
        )

        assert result.returncode == 0, result.stderr
        assert "pushed" in result.stdout
        # No file was sourced, so there's no precedence decision to log.
        assert "overriding backup.env" not in result.stdout
        log = _git("log", "--oneline", "main", cwd=remote)
        assert log.stdout.strip() != ""


class TestBackupRemoteReconciliation:
    """The origin remote is reconciled against BACKUP_REMOTE on every
    run, not just at first init (#243) — a stale origin (e.g. left over
    from a restore that used a different URL form) used to go unnoticed
    and unfixed indefinitely; see RUNBOOK.md §10's Remote-URL note.
    """

    def test_changed_remote_is_corrected_and_pushed_to(
        self,
        tmp_path: Path,
    ) -> None:
        repo_dir, remote_a = _seeded_exports(tmp_path)
        first = _run(repo_dir, remote_a)
        assert first.returncode == 0, first.stderr

        remote_b_dir = tmp_path / "b"
        remote_b_dir.mkdir()
        remote_b = _bare_remote(remote_b_dir)
        (repo_dir / "exports" / "reports").mkdir()
        (repo_dir / "exports" / "reports" / "x.md").write_text("x")

        second = _run(repo_dir, remote_b)

        assert second.returncode == 0, second.stderr
        assert "origin remote changed" in second.stderr
        exports = repo_dir / "exports"
        current_origin = _git(
            "remote",
            "get-url",
            "origin",
            cwd=exports,
        ).stdout.strip()
        assert current_origin == str(remote_b)

        # remote_b never saw this history before, so the push carries the
        # full two-commit log (the first run's commit plus this one) —
        # not just the new commit.
        log_b = _git("log", "--oneline", "main", cwd=remote_b)
        assert len(log_b.stdout.strip().splitlines()) == 2
        # remote_a never receives the second push at all — it's still
        # exactly where the first run left it.
        log_a = _git("log", "--oneline", "main", cwd=remote_a)
        assert len(log_a.stdout.strip().splitlines()) == 1


class TestPolicySnapshot:
    """#301: config/ips.yaml is baked into the image, never bind-mounted,
    so it is otherwise unreachable from the offsite backup — this stages
    a copy under exports/config-backup/ on every run, before it's picked
    up by the same `git add -A`/commit/push this class's siblings above
    already exercise.
    """

    def test_policy_copied_and_manifest_written(
        self,
        tmp_path: Path,
    ) -> None:
        repo_dir, remote = _seeded_exports(tmp_path)
        _write_policy(repo_dir, version="9.9.9")

        result = _run(repo_dir, remote)

        assert result.returncode == 0, result.stderr
        backup_dir = repo_dir / "exports" / "config-backup"
        assert (backup_dir / "ips.yaml").read_text() == (
            (repo_dir / "config" / "ips.yaml").read_text()
        )
        manifest = json.loads((backup_dir / "MANIFEST.json").read_text())
        assert manifest["written_by"] == "backup-exports.sh"
        assert manifest["source"] == "config/ips.yaml"
        assert manifest["app_version"] == "9.9.9"
        assert len(manifest["sha256"]) == 64  # a real hex sha256
        assert manifest["policy_changed_at"]
        # No operational value belongs in a manifest that gets pushed
        # offsite (persistence.py's written_by docstring states the same
        # rule for program_state.json) — pin the key set stays exactly
        # this, not "happens not to contain a remote today."
        assert set(manifest) == {
            "written_by",
            "source",
            "sha256",
            "app_version",
            "policy_changed_at",
        }

    def test_unchanged_policy_across_runs_stays_a_clean_noop(
        self,
        tmp_path: Path,
    ) -> None:
        """The manifest must not churn when the policy hasn't changed —
        an every-run-dirty manifest would defeat #252's clean-tree
        remote-verification path (TestCleanTreeHeartbeatVerification).
        """
        repo_dir, remote = _seeded_exports(tmp_path)
        _write_policy(repo_dir)
        first = _run(repo_dir, remote)
        assert first.returncode == 0, first.stderr
        exports = repo_dir / "exports"
        first_commit = _git("rev-parse", "HEAD", cwd=exports).stdout.strip()
        manifest_path = exports / "config-backup" / "MANIFEST.json"
        first_manifest = manifest_path.read_text()

        second = _run(repo_dir, remote)

        assert second.returncode == 0, second.stderr
        assert "nothing to commit" in second.stdout
        second_commit = _git("rev-parse", "HEAD", cwd=exports).stdout.strip()
        assert second_commit == first_commit
        assert manifest_path.read_text() == first_manifest

    def test_changed_policy_updates_manifest_and_pushes(
        self,
        tmp_path: Path,
    ) -> None:
        repo_dir, remote = _seeded_exports(tmp_path)
        policy = _write_policy(repo_dir, content="program:\n  name: v1\n")
        first = _run(repo_dir, remote)
        assert first.returncode == 0, first.stderr
        manifest_path = repo_dir / "exports" / "config-backup" / "MANIFEST.json"
        first_manifest = json.loads(manifest_path.read_text())
        time.sleep(1.1)  # policy_changed_at has one-second resolution

        policy.write_text("program:\n  name: v2\n")
        second = _run(repo_dir, remote)

        assert second.returncode == 0, second.stderr
        assert "pushed" in second.stdout
        second_manifest = json.loads(manifest_path.read_text())
        assert second_manifest["sha256"] != first_manifest["sha256"]
        assert (
            second_manifest["policy_changed_at"]
            != first_manifest["policy_changed_at"]
        )
        backup_dir = repo_dir / "exports" / "config-backup"
        assert (backup_dir / "ips.yaml").read_text() == "program:\n  name: v2\n"

    def test_missing_policy_warns_and_marks_but_does_not_fail_the_job(
        self,
        tmp_path: Path,
    ) -> None:
        """A fresh checkout with no config/ips.yaml yet must not take
        down the program_state.json backup or the heartbeat — see the
        script's stage_policy_snapshot() comment.
        """
        repo_dir, remote = _seeded_exports(tmp_path)

        result = _run(repo_dir, remote)

        assert result.returncode == 0, result.stderr
        assert "pushed" in result.stdout
        assert "config/ips.yaml" in result.stderr
        assert "not found" in result.stderr
        marker = repo_dir / "exports" / "config-backup" / "POLICY-MISSING.txt"
        assert marker.exists()
        assert "not found on this host" in marker.read_text()

    def test_policy_reappearing_clears_the_missing_marker(
        self,
        tmp_path: Path,
    ) -> None:
        repo_dir, remote = _seeded_exports(tmp_path)
        first = _run(repo_dir, remote)
        assert first.returncode == 0, first.stderr
        marker = repo_dir / "exports" / "config-backup" / "POLICY-MISSING.txt"
        assert marker.exists()

        _write_policy(repo_dir)
        second = _run(repo_dir, remote)

        assert second.returncode == 0, second.stderr
        assert not marker.exists()
        assert (
            repo_dir / "exports" / "config-backup" / "MANIFEST.json"
        ).exists()

    def test_manifest_key_set_carries_no_operational_value(
        self,
        tmp_path: Path,
    ) -> None:
        """Nothing that could identify the remote, host, or credential
        path belongs in an artifact this script itself pushes offsite —
        the same rule persistence.py's writer_label docstring states for
        program_state.json's metadata.written_by.
        """
        repo_dir, remote = _seeded_exports(tmp_path)
        _write_policy(repo_dir)

        result = _run(repo_dir, remote)

        assert result.returncode == 0, result.stderr
        manifest_text = (
            repo_dir / "exports" / "config-backup" / "MANIFEST.json"
        ).read_text()
        assert str(remote) not in manifest_text
        assert "BACKUP_REMOTE" not in manifest_text
