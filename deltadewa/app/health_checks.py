"""Boot-wiring assertions composed into ``/health`` (#309).

``/health`` (``app/factory.py``'s ``_health``) previously asserted only
*presence* — ``state_loaded``, a market-data source/as_of. That could not
see #295: ``ips_config`` loaded, ``state.portfolio`` was never ``None``, and
the endpoint read healthy for weeks while ``default_exercise_style`` was
never actually wired from it, dead-panelling two surfaces. This module is
the fix's shape, not a general config auditor: a small, explicit set of
runtime assertions on the objects the *real* boot path already built,
composed once per request.

**Six checks, not 49.** ``boot-wiring-checker`` inventoried the full IPS —
1 UNWIRED (``pricing.exercise_style``, fixed by #295/#361), 1 ORPHAN
(``triggers.rally_rebalance_pct``, #297 — deliberately untouched here), 46
READ-ONLY-CONSUMER. Reporting all 49 from ``/health`` would be noise; the
filter applied to pick these six: *does this key's absence make a rendered
surface show nothing, or a number the operator did not configure?*

- ``ips_loaded`` — ``load_ips_config`` is all-or-nothing (any invalid
  required section raises, caught into ``ips_config=None`` by
  ``ProgramState.load``), so this one boolean covers every *required*
  section at once; there is nothing to gain from checking
  budget/convexity/drawdown/triggers/monetization individually — they
  cannot be individually absent.
- ``ips_sections_configured`` — the three *optional* sections
  (``market_environment``/``sizing``/``vega``) each carry a dataclass
  default, so their absence is silent: the panel renders using
  ``DEFAULT_*`` constants standing in for the operator's own policy.
  **Reported only, never degrades status** — a program content with the
  defaults is a legitimate state, not an outage, and training an operator
  to treat this as red just gets it ignored.
- ``exercise_style_wired`` — #295 itself: ``state.portfolio.
  default_exercise_style`` is object-*materialized*, not merely present.
  ``state.portfolio`` was never ``None`` throughout #295; the gap was one
  field on it never getting set, which a presence check cannot see.
- ``state_persisted`` — ``state.dirty`` should be ``False`` once quiescent;
  ``True`` means an autosave *failed*, so in-memory edits would be lost on
  restart. Free, currently invisible.
- ``state_file_undisturbed`` — #355: whether another process (the CLI
  importer) wrote the shared state file since this worker last loaded or
  saved it.
- ``cache_dir_writable`` — #300: a real write-then-unlink against the
  resolved market-data cache directory, not ``os.access()`` (permission
  bits don't catch a full disk or a remounted-read-only filesystem, both
  live droplet failure modes, and lie under root).

**Not checked: ``triggers.rally_rebalance_pct`` (#297).** Per boot-wiring-
checker's own finding, an orphan key never fails at boot — it just does
nothing — so it is not a runtime-checkable condition. Catching it needs
static consumer tracing in CI, not an endpoint assertion; conflating the
two would either produce a permanently-red ``/health`` or a check that can
never fire.

**Object-materialized, not file-materialized.** None of these checks
re-read ``ips.yaml`` from disk — every one reads an attribute already set
on the objects the real boot path constructed. A check that re-parsed the
file would describe *the file*, possibly edited since boot, while claiming
to describe the *running* config — exactly the false-green shape this
batch exists to remove.

**Every check here is O(1)**: attribute reads, one ``Path.stat()``, or one
``mkdir``+write+unlink. None fetches over the network and none prices the
book — ``/health``'s own existing comment (``factory.py``) forbids both,
since this backs a dead-man's-switch ping, not a page render.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from deltadewa.state import ProgramState

_PROBE_FILENAME = ".health-probe"

# The explicit registry #309's own comment asks for — grows one entry at a
# time as new object-materialized keys are wired, rather than something
# inferred from whatever run_checks() happens to call.
BOOT_WIRING_CHECKS: Final[tuple[str, ...]] = (
    "ips_loaded",
    "ips_sections_configured",
    "exercise_style_wired",
    "state_persisted",
    "state_file_undisturbed",
    "cache_dir_writable",
)


@dataclass(frozen=True)
class CheckResult:
    """One boot-wiring assertion's outcome.

    Attributes:
        name: One of ``BOOT_WIRING_CHECKS``.
        ok: Whether the check passed. ``ips_sections_configured`` is
            always ``True`` here by design — see the module docstring —
            so it can never turn ``/health``'s overall status degraded.
        detail: Human-readable explanation, safe to render as-is.
        value: Optional structured payload (e.g. the list of defaulted
            section names, or the resolved cache directory path).

    """

    name: str
    ok: bool
    detail: str
    value: Any | None = None


def check_ips_loaded(state: ProgramState) -> CheckResult:
    """Whether ``ips.yaml`` loaded at all."""
    loaded = state.ips_config is not None
    detail = (
        "ips.yaml loaded"
        if loaded
        else (
            "ips.yaml did not load — /monitor and /design both render "
            "'No IPS policy is loaded' in place of their real content"
        )
    )
    return CheckResult(name="ips_loaded", ok=loaded, detail=detail)


def check_ips_sections_configured(state: ProgramState) -> CheckResult:
    """Which optional IPS sections are running on code defaults.

    Reported only — see the module docstring for why this must never
    degrade ``/health``'s status.
    """
    if state.ips_config is None:
        return CheckResult(
            name="ips_sections_configured",
            ok=True,
            detail="ips.yaml did not load; see ips_loaded",
        )
    defaulted = sorted(state.ips_config.defaulted_sections)
    detail = (
        "all optional sections present in ips.yaml"
        if not defaulted
        else (
            "running on code defaults, not ips.yaml, for: "
            + ", ".join(defaulted)
        )
    )
    return CheckResult(
        name="ips_sections_configured",
        ok=True,
        detail=detail,
        value=defaulted,
    )


def check_exercise_style_wired(state: ProgramState) -> CheckResult:
    """#295's own class: ``default_exercise_style`` must reach the portfolio.

    ``state.portfolio`` is never ``None``, so a presence check on the
    object alone would have passed throughout #295 — the gap was one
    field on it never getting set. Without this, ``add_position()`` raises
    for any leg with no explicit ``exercise_style`` (``portfolio/core.py``).
    """
    style = state.portfolio.default_exercise_style
    wired = style is not None
    detail = (
        f"default_exercise_style={style.value}"
        if style is not None
        else (
            "default_exercise_style is unset on the live portfolio — "
            "add_position() will raise for any leg with no explicit style"
        )
    )
    return CheckResult(name="exercise_style_wired", ok=wired, detail=detail)


def check_state_persisted(state: ProgramState) -> CheckResult:
    """Whether the last autosave actually succeeded.

    ``ProgramState.dirty`` is normally ``False`` immediately after every
    mutator — it only stays ``True`` when an autosave attempt itself
    failed, meaning an operator's edits would be lost on restart.
    """
    persisted = not state.dirty
    detail = (
        "no unsaved changes"
        if persisted
        else (
            "the last autosave failed — in-memory changes would be lost "
            "on restart"
        )
    )
    return CheckResult(name="state_persisted", ok=persisted, detail=detail)


def check_state_file_undisturbed(state: ProgramState) -> CheckResult:
    """#355: whether another process wrote the shared state file.

    Backed by ``ProgramState.external_write_detected()`` — one unlocked
    ``Path.stat()``, no lock, no reprice. This is a signal for a human to
    decide whether a restart is warranted, not proof anything is wrong:
    the CLI importer writes with ``confirm=True`` by design.
    """
    disturbed = state.external_write_detected()
    detail = (
        "state file matches what this worker last loaded or saved"
        if not disturbed
        else (
            f"{state.state_path} has changed since this worker last read "
            "it (this worker's own last known write: "
            f"written_by={state.written_by!r}, "
            f"loaded_at={state.loaded_at!r}) — this worker has not "
            "reloaded; a restart is required to pick up whatever wrote it"
        )
    )
    return CheckResult(
        name="state_file_undisturbed",
        ok=not disturbed,
        detail=detail,
    )


def check_cache_dir_writable(cache_dir: Path) -> CheckResult:
    """#300: prove the market-data cache directory is actually writable.

    A real write-then-unlink, not ``os.access()`` — permission bits don't
    catch a full disk (``ENOSPC``) or a filesystem remounted read-only,
    both live droplet failure modes and both the "cache existed Sunday,
    gone Thursday" shape #300 describes; ``os.access`` also lies under
    root.

    The app itself runs ``read_only=True`` and never writes this
    directory — this is a proxy for the ``jobs`` service, which runs as
    the same UID against the same bind mount (``compose.yaml``) and does
    write it. The resolved path is reported so a divergence between what
    ``app`` and ``jobs`` each resolve for ``DELTADEWA_CACHE_DIR`` is
    visible by diffing against it directly.

    Fixed probe filename, unlinked in a ``finally``: ``exports/`` is its
    own git repo pushed offsite nightly (``ops/backup-exports.sh``), so a
    randomly named probe left behind on a crash would accumulate commits;
    a fixed name caps the damage at one stray file, committed once.
    """
    probe_path = cache_dir / _PROBE_FILENAME
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        probe_path.write_text("ok", encoding="utf-8")
        entry_count = sum(1 for _ in cache_dir.iterdir())
    except OSError as exc:
        return CheckResult(
            name="cache_dir_writable",
            ok=False,
            detail=f"{cache_dir} is not writable: {exc}",
            value=str(cache_dir),
        )
    finally:
        # missing_ok=True only swallows "the file doesn't exist" — it does
        # not cover a mkdir() that itself failed (e.g. a path component
        # exists as a plain file, not a directory), which raises
        # NotADirectoryError here too. Cleanup must never turn a reported
        # failure into an unhandled 500 on top of it.
        with contextlib.suppress(OSError):
            probe_path.unlink(missing_ok=True)
    return CheckResult(
        name="cache_dir_writable",
        ok=True,
        detail=f"{cache_dir} is writable ({entry_count} cache entries)",
        value=str(cache_dir),
    )


def run_checks(
    state: ProgramState,
    *,
    cache_dir: Path,
) -> tuple[CheckResult, ...]:
    """Run every boot-wiring check, in ``BOOT_WIRING_CHECKS`` order.

    Args:
        state: The app's shared ``ProgramState``.
        cache_dir: The resolved market-data cache directory (the same
            resolution ``wsgi.py`` uses to construct the live provider).

    Returns:
        One ``CheckResult`` per name in ``BOOT_WIRING_CHECKS``.

    """
    return (
        check_ips_loaded(state),
        check_ips_sections_configured(state),
        check_exercise_style_wired(state),
        check_state_persisted(state),
        check_state_file_undisturbed(state),
        check_cache_dir_writable(cache_dir),
    )


def summarize(
    results: Iterable[CheckResult],
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Roll ``CheckResult`` s into ``/health``'s ``status`` + payload.

    ``status`` is ``"degraded"`` if any check failed, ``"ok"`` otherwise —
    HTTP still returns 200 either way (``/health`` stays a liveness probe;
    a policy nit like a defaulted IPS section must never look like a
    reason to restart-loop a working container).

    Returns:
        ``(status, boot_wiring)`` — ``boot_wiring`` is keyed by check
        name, each value a ``{"ok", "detail"}`` mapping plus ``"value"``
        when the check carried one.

    """
    results = tuple(results)
    status = "ok" if all(result.ok for result in results) else "degraded"
    boot_wiring = {
        result.name: {
            "ok": result.ok,
            "detail": result.detail,
            **({"value": result.value} if result.value is not None else {}),
        }
        for result in results
    }
    return status, boot_wiring
