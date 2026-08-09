"""Tests for docker-entrypoint.sh.

Same subprocess-driven-real-script philosophy as
``test_backup_exports.py``: no shell-test framework exists in this repo,
so this runs the actual script rather than reimplementing its logic in
Python.

``id``, ``chown``, ``chgrp``, and ``runuser`` are stubbed via a PATH-
prepended fake-bin directory rather than exercised for real — this
isn't just a test-isolation nicety, it's required to run the script at
all outside a real container: ``runuser``/``appuser`` don't exist on a
dev Mac (``runuser`` is util-linux, Linux-only), and genuinely chowning
to a different uid needs root, which neither a dev machine nor most CI
runners reliably have. The fakes record their invocations to a log
file instead of acting, which is also a stronger regression test for
issue #237 than a real chown would be: it proves the entrypoint never
*attempts* to touch ``.git``, regardless of which uid would have done
it.
"""

from __future__ import annotations

import shutil
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import]
from pathlib import Path

_SCRIPT = Path(__file__).parent.parent.parent / "docker-entrypoint.sh"
_SH = shutil.which("sh") or "/bin/sh"

_FAKE_ID = """#!/bin/sh
echo "{uid}"
"""

_FAKE_LOGGER = """#!/bin/sh
echo "{name} $*" >> "$FAKEBIN_LOG"
"""

_FAKE_RUNUSER = """#!/bin/sh
echo "runuser $*" >> "$FAKEBIN_LOG"
# Real invocation shape is: runuser -u appuser -- <wrapped command...>.
# Drop the "-u appuser --" prefix and actually exec the rest, so a test
# can observe that the wrapped command still ran, not just that
# runuser was called.
shift 3
exec "$@"
"""


def _write_fake_bin(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _fake_bin_dir(tmp_path: Path, *, root: bool) -> Path:
    """A PATH-prependable dir with stubbed id/chown/chgrp/runuser."""
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    _write_fake_bin(fakebin, "id", _FAKE_ID.format(uid="0" if root else "1000"))
    _write_fake_bin(fakebin, "chown", _FAKE_LOGGER.format(name="chown"))
    _write_fake_bin(fakebin, "chgrp", _FAKE_LOGGER.format(name="chgrp"))
    _write_fake_bin(fakebin, "runuser", _FAKE_RUNUSER)
    return fakebin


def _run_entrypoint(
    tmp_path: Path,
    exports_dir: Path,
    *,
    root: bool,
    command: list[str],
) -> tuple[subprocess.CompletedProcess[str], Path]:
    fakebin = _fake_bin_dir(tmp_path, root=root)
    log = tmp_path / "fakebin.log"
    env = {
        "PATH": f"{fakebin}:/usr/bin:/bin",
        "FAKEBIN_LOG": str(log),
        "DELTADEWA_EXPORTS_DIR": str(exports_dir),
    }
    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [_SH, str(_SCRIPT), *command],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result, log


def _seeded_exports_dir(tmp_path: Path) -> Path:
    """A scratch exports/ with a .git and the app's usual data paths."""
    exports = tmp_path / "exports"
    git_dir = exports / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text("[core]\n")
    (exports / "program_state.json").write_text('{"positions": []}')
    marketdata_cache = exports / "marketdata-cache"
    marketdata_cache.mkdir()
    (marketdata_cache / "vix.json").write_text("{}")
    reports = exports / "reports"
    reports.mkdir()
    (reports / "digest-2026-08-05.md").write_text("# Weekly Digest\n")
    return exports


class TestEntrypointOwnershipScope:
    """#237: chown/chgrp must never reach exports/.git or exports/ itself."""

    def test_git_is_never_chowned_or_chgrpped(self, tmp_path: Path) -> None:
        exports = _seeded_exports_dir(tmp_path)
        marker = tmp_path / "ran.marker"

        result, log = _run_entrypoint(
            tmp_path,
            exports,
            root=True,
            command=["sh", "-c", f"echo ran > {marker}"],
        )

        assert result.returncode == 0, result.stderr
        log_text = log.read_text()
        assert ".git" not in log_text

    def test_other_children_are_chowned_recursively(
        self,
        tmp_path: Path,
    ) -> None:
        exports = _seeded_exports_dir(tmp_path)
        marker = tmp_path / "ran.marker"

        result, log = _run_entrypoint(
            tmp_path,
            exports,
            root=True,
            command=["sh", "-c", f"echo ran > {marker}"],
        )

        assert result.returncode == 0, result.stderr
        log_text = log.read_text()
        chown_lines = "\n".join(
            line for line in log_text.splitlines() if line.startswith("chown")
        )
        for name in ("program_state.json", "marketdata-cache", "reports"):
            assert name in chown_lines, chown_lines

    def test_exports_dir_itself_is_chgrpped_not_chowned(
        self,
        tmp_path: Path,
    ) -> None:
        """The worktree top must stay root-owned (git checks it too, not
        just .git/) — appuser gets access via the group bit, never by
        taking ownership.
        """
        exports = _seeded_exports_dir(tmp_path)
        marker = tmp_path / "ran.marker"

        result, log = _run_entrypoint(
            tmp_path,
            exports,
            root=True,
            command=["sh", "-c", f"echo ran > {marker}"],
        )

        assert result.returncode == 0, result.stderr
        log_text = log.read_text()
        chgrp_lines = [
            ln for ln in log_text.splitlines() if ln.startswith("chgrp")
        ]
        chown_lines = [
            ln for ln in log_text.splitlines() if ln.startswith("chown")
        ]
        assert any(str(exports) in ln for ln in chgrp_lines)
        assert not any(
            ln == f"chown -R appuser:appuser {exports}" for ln in chown_lines
        )

    def test_wrapped_command_still_runs(self, tmp_path: Path) -> None:
        exports = _seeded_exports_dir(tmp_path)
        marker = tmp_path / "ran.marker"

        result, log = _run_entrypoint(
            tmp_path,
            exports,
            root=True,
            command=["sh", "-c", f"echo ran > {marker}"],
        )

        assert result.returncode == 0, result.stderr
        assert marker.read_text().strip() == "ran"
        log_text = log.read_text()
        assert "runuser -u appuser --" in log_text


class TestEntrypointNonRootDefensiveBranch:
    """Already-non-root: never chown/chgrp/runuser, just exec directly."""

    def test_no_ownership_calls_and_command_still_runs(
        self,
        tmp_path: Path,
    ) -> None:
        exports = _seeded_exports_dir(tmp_path)
        marker = tmp_path / "ran.marker"

        result, log = _run_entrypoint(
            tmp_path,
            exports,
            root=False,
            command=["sh", "-c", f"echo ran > {marker}"],
        )

        assert result.returncode == 0, result.stderr
        assert marker.read_text().strip() == "ran"
        assert not log.exists()
