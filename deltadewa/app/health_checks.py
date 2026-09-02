"""Boot-wiring assertions composed into ``/health`` (#309).

``/health`` (``app/factory.py``'s ``_health``) previously asserted only
*presence* — ``state_loaded``, a market-data source/as_of. That could not
see #295: ``ips_config`` loaded, ``state.portfolio`` was never ``None``, and
the endpoint read healthy for weeks while ``default_exercise_style`` was
never actually wired from it, dead-panelling two surfaces. This module is
the fix's shape, not a general config auditor: a small, explicit set of
runtime assertions on the objects the *real* boot path already built,
composed once per request.

**Seven checks, not 49.** ``boot-wiring-checker`` inventoried the full IPS —
1 UNWIRED (``pricing.exercise_style``, fixed by #295/#361), 1 ORPHAN
(``triggers.rally_rebalance_pct``, since built and replaced by 5a's four
rally bands, #297), the rest READ-ONLY-CONSUMER. Reporting all of them
from ``/health`` would be noise; the filter applied to pick these six:
*does this key's absence make a rendered surface show nothing, or a number
the operator did not configure?*

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
- ``cache_manifest_matches`` — #377/#378: reads the manifest the refresh
  job writes on every run and compares its recorded ``cache_dir`` against
  what this app process itself resolved. ``default_cache_dir()``'s
  resolution *logic* is shared between ``app`` and ``jobs``, but nothing
  previously verified the two processes' resolved paths actually agree
  at runtime — a silent divergence there would mean the refresh job
  keeps a cache warm that this app never reads. ``compose.yaml``
  hardcodes both ``DELTADEWA_CACHE_DIR`` literals identically today, so
  this is a detector for future drift (#378 is scoped P2), not evidence
  of a divergence happening now.

**Not checked: the rally bands (#297).** The orphan this paragraph used
to name — ``triggers.rally_rebalance_pct`` — is gone: 5a replaced it with
the handbook's four named bands and built the trigger, so the key count is
no longer 1 UNWIRED / 1 ORPHAN / 46 READ-ONLY-CONSUMER but 0 / 0 / 49-plus.

The bands are deliberately still not checked here, for a different reason
than before. They are now ordinary READ-ONLY-CONSUMERs, and the filter
above ("does this key's absence make a rendered surface show nothing, or a
number the operator did not configure?") answers no: all four are required
with no default, so ``load_ips_config`` raises on absence and
``ips_loaded`` already covers them. There is no DEFAULT-MASKED
silent-fallback case to catch, and adding a check would be exactly the
noise "seven checks, not 49" exists to refuse.

The general orphan class still needs static consumer tracing in CI rather
than an endpoint assertion — an orphan key never *fails* at boot, it just
does nothing, so conflating the two would produce either a permanently-red
``/health`` or a check that can never fire.

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

What ``status`` degrades on, and what it stays quiet about (#393)
-----------------------------------------------------------------

``status`` covers two things: the boot wiring above, and data freshness.
``assess_freshness`` below is the second half. The rule, in one sentence:

    ``status`` degrades on a freshness state only when that state means a
    **machine stopped doing its job**, or that **no review has ever
    happened at all**. It stays quiet when the state means a scheduled
    human review is merely *overdue*.

Concretely, over the ``ProvenanceLedger`` (``analysis/provenance.py``)
``/health`` already builds for its ``market_data``/``pricing_inputs``
objects — two channels, two cuts on the one ``FRESH < AGING < UNKNOWN <
MISSING`` ordering:

- **Fetched** (``market_data``) degrades at ``_STALE_OR_WORSE`` —
  ``STALE``/``STATIC``/``UNAVAILABLE``. ``LIVE`` and ``CACHED`` stay
  quiet.
- **Hand-entered** (``pricing_inputs.worst``) degrades at ``UNKNOWN`` or
  worse. ``AGING`` stays quiet. (``MISSING`` is unreachable here — see
  ``Freshness.MISSING``.)

**Why the two channels take different cuts.** They answer different
questions, and only one of them is a fact about the program's health.

The fetched channel's grade is a fact about *the machine*: the refresh
job either ran and got data or it did not, and no human can make the
reading fresher by hand. Anything worse than ``CACHED`` means an
automated thing that should be running isn't — exactly what a
dead-man's switch exists to report, and it clears by itself when the job
recovers. ``CACHED`` is the normal steady state, and #368 is the record
of why a routinely-lagged series (FRED's VIXCLS) must not read as a dead
pipeline.

The hand-entered channel's ``AGING`` is a fact about *the operator's
review calendar*: "a confirmation is overdue against
``ips_config.pricing_inputs``". Note the arithmetic before tightening
this: the shipped policy is ``spot_max_age_days: 1``, so a book
confirmed on Friday is ``AGING`` by Sunday and stays that way every day
nobody logs in — on a program whose review rhythm is a *weekly* digest,
that is most days. Wiring it into ``status`` would leave ``/health``
degraded for the majority of the program's life, and a permanently
degraded dead-man's switch is the same false-green failure arriving from
the other side: the reader stops reading the field. It is the identical
argument ``chrome.py``'s module docstring makes for why the banner never
mounts on a merely ``CACHED`` reading. ``AGING`` already has the right
surface — the banner and the provenance panel, read by the same human
whose review is overdue — and ``/health`` still *renders* it under
``pricing_inputs``; it just isn't in the headline.

``UNKNOWN`` is in, and that is not an inversion of the ordering above —
it is one notch higher on the same scale, for two reasons. It is
categorically different from ``AGING``: ``AGING`` means a review is
late, ``UNKNOWN`` means *there is no review to be late*, i.e. the ledger
has no basis at all for a number the book is priced on (``Freshness``'s
own docstring makes the same argument for ranking it worse — an aging
input's damage is bounded, an unconfirmed one's is not). And it latches
rather than recurs: ``add_position`` stamps ``volatility_as_of`` at
entry and ``update_market_conditions`` stamps on change, so once an
operator clears it with the confirm-gated
``ProgramState.mark_inputs_reviewed`` no routine operation puts it back.
A signal that fires once per book and then stays off is not alarm
fatigue; it is the migration working.

**One definition, not a second.** The fetched half reads the same
``_STALE_OR_WORSE`` set the digest and ``/monitor`` already grade on,
over the same enum and the same channel it was written for. What it
deliberately does *not* read is ``ProvenanceLedger.combined_quality``,
which is that set applied to *both* channels at once: it maps a
hand-entered ``AGING`` to ``DataQuality.STALE``, so a spot stamp one day
past a one-day cadence would become indistinguishable from a dead CBOE
feed. That is precisely the merge #368 removed from this endpoint and
that ``worst_of()`` exists to prevent, and it would import the
``AGING``-fires-daily problem above along with it.

**Still two status words, not three.** A watcher that greps only
``status`` cannot tell a wiring fault from a freshness one, by design:
the field answers one question — *should a human look at this program
now?* — and both answers want the same first action, which is to open
the payload. The distinguishing detail lives in three sibling nullable
fields with one shape: ``provenance_error`` (#381) and
``boot_wiring_error`` (#395) name a *fault in assessing*, and
``freshness_reason`` names a *condition successfully assessed*. Hence
"reason", not "error" — collapsing the two would undo the distinction
#381 drew when it refused to reuse ``DataQuality.UNAVAILABLE`` for a
code fault.

**This endpoint is not the program's dead-man's switch.** The three
heartbeats (refresh, digest, backup) are pinged by the cron jobs
themselves on their own exit-code contracts; nothing pings or polls
``/health``. So the freshness verdict here is a *cross-check* — a second,
independent read from inside the app, whose distinctive value is the
case where the refresh job pings healthy while this process reads a
stale or different cache (the shape ``cache_manifest_matches`` covers).
A dead pipeline is caught earlier and more reliably by the refresh
heartbeat, which is what lets this rule afford to be conservative. Any
"the system is down" promise made to a reader — the digest footer's, for
instance — must stay anchored to the digest's own arrival, which is
pinged only on a confirmed send, never to ``/health`` reading ``ok``
from inside the process that would also be the thing failing.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from deltadewa.analysis.market_environment import DataQuality
from deltadewa.analysis.provenance import Freshness, InputKind
from deltadewa.marketdata import read_cache_manifest

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from deltadewa.analysis.provenance import ProvenanceLedger
    from deltadewa.state import ProgramState

_PROBE_FILENAME = ".health-probe"

# Mirrors program_report._STALE_OR_WORSE locally rather than importing a
# private name — the same convention weekly_snapshot.py, weekly_report.py
# and pages/monitor.py already follow. Held as DataQuality members (not
# their string values, as the reporting copies do) because this compares
# against ProvenanceLedger.market_data_quality, an enum. Pinned equal to
# "every DataQuality that is not Freshness.FRESH" by test, so the two
# spellings of "not fresh" cannot drift apart silently.
_STALE_OR_WORSE: Final[frozenset[DataQuality]] = frozenset(
    {DataQuality.STALE, DataQuality.STATIC, DataQuality.UNAVAILABLE},
)

# The hand-entered channel's own cut, one notch higher on the shared
# Freshness ordering — see the module docstring for why AGING is not in
# it. MISSING is unreachable for a hand-entered entry (Freshness.MISSING)
# and is listed only so the set is the ordering's own tail rather than a
# single hand-picked member.
_UNCONFIRMED_OR_WORSE: Final[frozenset[Freshness]] = frozenset(
    {Freshness.UNKNOWN, Freshness.MISSING},
)

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
    "cache_manifest_matches",
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


def check_cache_manifest_matches(cache_dir: Path) -> CheckResult:
    """#377/#378: confirm the refresh job's manifest matches this resolution.

    One small file read plus one ``Path.exists()`` — no fetch, no
    reprice, O(1) like every other check here (see the module docstring).

    ``default_cache_dir()``'s resolution *logic* is shared between
    ``app`` and ``jobs``, but the two ``compose.yaml`` literals that
    actually feed each process's ``DELTADEWA_CACHE_DIR`` are not verified
    to agree by anything at runtime — this check is that runtime
    cross-check. It reads the manifest ``marketdata.refresh`` writes on
    every run and compares its recorded ``cache_dir`` against what this
    app process itself resolved.

    ``compose.yaml`` hardcodes both literals identically today, so a
    mismatch is not a live failure mode — this is a detector for future
    drift (#378 is scoped P2), not evidence of one happening now.
    """
    manifest = read_cache_manifest(cache_dir)
    if manifest is None:
        return CheckResult(
            name="cache_manifest_matches",
            ok=False,
            detail=(
                f"no refresh manifest found at {cache_dir} — either the "
                "refresh job (#378) has not run against this cache_dir "
                "yet, or it resolved a different DELTADEWA_CACHE_DIR "
                "than this app process did; this check cannot "
                "distinguish the two"
            ),
            value={
                "recorded_cache_dir": None,
                "written_at": None,
                "resolved_cache_dir": str(cache_dir),
            },
        )

    matches = manifest.cache_dir == str(cache_dir)
    if matches:
        detail = (
            "refresh manifest matches this app's resolved cache_dir "
            f"(written_at={manifest.written_at}"
            f"{_age_suffix(manifest.written_at)})"
        )
    else:
        detail = (
            f"refresh manifest recorded cache_dir={manifest.cache_dir!r} "
            f"but this app process resolved cache_dir={str(cache_dir)!r} "
            "— app and jobs may be resolving DELTADEWA_CACHE_DIR "
            "differently"
        )
    return CheckResult(
        name="cache_manifest_matches",
        ok=matches,
        detail=detail,
        value={
            "recorded_cache_dir": manifest.cache_dir,
            "written_at": manifest.written_at,
            "resolved_cache_dir": str(cache_dir),
        },
    )


def _age_suffix(written_at: str) -> str:
    """Render ``", ~Nh ago"`` for a manifest's ``written_at``, or ``""``.

    Wall-clock provenance display — exactly like
    ``cboe_fred_provider.py``'s own ``fetched_at`` staleness math, not a
    ``clock.py`` program-day computation — so ``datetime.now()`` is
    correct here, not a violation of the program-clock rule. Never
    raises: a malformed ``written_at`` (the manifest file itself is only
    tolerantly parsed, not validated) degrades to no age shown rather
    than a broken ``/health``.
    """
    try:
        parsed = datetime.fromisoformat(written_at)
    except ValueError:
        return ""
    age_hours = (datetime.now(tz=UTC) - parsed).total_seconds() / 3600
    return f", ~{age_hours:.1f}h ago"


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
        check_cache_manifest_matches(cache_dir),
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


def assess_freshness(ledger: ProvenanceLedger) -> str | None:
    """Return why freshness degrades ``/health``'s ``status``, or ``None``.

    The rule and the reasoning behind both cuts are in this module's
    docstring — read that before changing either threshold. In short: the
    fetched channel degrades at ``_STALE_OR_WORSE``, the hand-entered one
    at ``UNKNOWN`` or worse, and a merely ``AGING`` hand-entered input is
    deliberately quiet here while still being rendered in full under
    ``pricing_inputs``.

    Deliberately a plain function over an already-built ledger, not part
    of ``summarize()``: that one has no ledger, and giving it one would
    make the boot-wiring checks depend on the provenance layer for the
    sake of a one-line ``or``. ``/health`` combines the two verdicts in
    the route, the same shape #381 used for ``provenance_error``, which
    is also what keeps the two guards there independent.

    Args:
        ledger: The ledger ``/health`` already built for its
            ``market_data``/``pricing_inputs`` objects.

    Returns:
        ``None`` when nothing about freshness degrades ``status``;
        otherwise a one-line reason naming the channel, its grade, and
        the entry — ``/health``'s ``freshness_reason`` field.

    """
    if ledger.market_data_quality in _STALE_OR_WORSE:
        # Named ahead of the hand-entered channel when both degrade: it
        # is the half an operator acts on first (the refresh job, the
        # provider), and the other half is still fully rendered under
        # pricing_inputs. One reason, not one per channel.
        reason = f"market_data {ledger.market_data_quality.value}"
        if ledger.oldest_series is not None:
            reason += f" (oldest series: {ledger.oldest_series})"
        return reason

    worst = ledger.worst_of(InputKind.HAND_ENTERED)
    if worst is not None and worst.freshness in _UNCONFIRMED_OR_WORSE:
        return f"pricing_inputs {worst.freshness.value} ({worst.detail})"
    return None
