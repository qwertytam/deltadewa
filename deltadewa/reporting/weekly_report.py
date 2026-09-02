"""Headless, deterministic weekly digest — the M2.6 report entrypoint.

Usage::

    python -m deltadewa.reporting.weekly_report [--as-of YYYY-MM-DD]
        [--export-dir exports] [--ips-path config/ips.yaml]
        [--period-label "Week of 2026-08-05"]

Assembles the same ``ProgramReport`` the notebook builds, but **leads with
what changed since last week** — verdict crossings, band exits, staleness —
rather than repeating a near-identical report 52 times a year.
``build_weekly_digest`` also enriches the embedded report's own §4 Return
Framing with the week's carry cost alongside the cumulative figure since
the first snapshot (see ``weekly_snapshot.py`` for why that cumulative
figure is carry cost, not premium paid — the latter is a stock, not a
flow, and would double-count or miss cash entirely across a roll), so a
single week of pure theta doesn't read as a loss story on its own — and so
it renders once, in the report, not a second time in this lede (Issue
#171).

Locked policy: **send stamped-stale, never silently skip.** The staleness
banner is always rendered, using ``MarketContextSection.data_quality`` —
already the worst ``Source`` across every live observation this assembly
makes (``Observation.combine`` inside ``assess_market_environment``).

Only ``main()``'s ``--as-of`` default reads the wall clock; everything
downstream is a pure function of its arguments, which is what makes the
golden-file test possible.

With ``--send-email``, the digest is also sent over SMTP
(``deltadewa.reporting.email_smtp``), reading ``SMTP_HOST``,
``SMTP_PORT``, ``SMTP_USERNAME``, ``SMTP_PASSWORD``, ``REPORT_EMAIL_TO``,
``REPORT_EMAIL_FROM`` from the environment — any standard SMTP relay
works, so switching providers is a config change, not a code change.
The optional ``REPORT_EMAIL_FROM_NAME`` (#319, Batch 6) sets a friendlier
display name on the From header without changing the actual sending
address; see :func:`_from_header`. This is opt-in (default off) so
building the digest never requires mail credentials — only the cron line
that actually wants delivery passes the flag. A missing/invalid env var
or a failed send both exit **2**, distinct from the **1** used when the
report itself was refused: at that
point the report files are already written successfully, and a delivery
failure must never look like exit-0 success. On a confirmed send,
``DIGEST_HEARTBEAT_URL`` (``deltadewa.heartbeat``) is pinged — the *only*
path that pings it, per the dead-man's-switch design: a missing weekly
email is exactly the kind of silence that gets rationalised as "quiet
week," so it must alarm rather than ping regardless.

**#364 — the digest build is guarded, start to finish.** Everything from
loading ``ProgramState`` through rendering the markdown/html strings
(:func:`build_and_render`) can raise on an input this module does not
control — a corrupt state file, a provider outage, a malformed pricing
input, a repricing edge case. Before #364 that raise was unguarded: it took
the whole cron job down with an unhandled traceback, which is also silence
from the operator's chair, indistinguishable from the job never having run.
A blast-radius audit (R-a.3) later found that the original guard, though it
covered :func:`build_and_render`, still left ``ProgramState.load()`` ahead
of it exposed — Python's bare default exit on an uncaught exception is
``1``, indistinguishable from ``_EXIT_REFUSED``'s documented meaning of a
clean, expected refusal. ``main()`` now wraps the whole sequence — state
load through render — on failure prints and logs the exception, writes **no
files at all** (not even a partial one — next week's digest must still
compare against last week's real snapshot, not a corrupt or missing one),
sends a plain-language failure alert when ``--send-email`` was requested,
and exits **3**. See :func:`_send_build_failure_alert` and
``heartbeat.py``'s module docstring for why this path never pings the
heartbeat either.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, replace
from datetime import date
from email.utils import formataddr
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Final

from deltadewa import __version__
from deltadewa.analysis import (
    GRADABLE_VERDICTS,
    CrashShock,
    PortfolioAnalyzer,
    RollVerdict,
    assess_market_environment,
    build_monetization_plan,
    build_provenance_ledger,
    compute_crash_convexity,
    evaluate_roll_status,
    verdict_reason,
)
from deltadewa.analysis.hedge_triggers import (
    HedgeTriggerReason,
    HedgeTriggerThresholds,
    TriggerStatus,
    rally_reason,
    worst_rally_from_entry,
)
from deltadewa.analysis.maturity import MaturityBuckets
from deltadewa.clock import program_trading_date
from deltadewa.heartbeat import ping
from deltadewa.marketdata import (
    CboeFredProvider,
    default_cache_dir,
    resolve_data_ttl,
)
from deltadewa.reporting.email_smtp import (
    EmailDeliveryError,
    EmailMessage,
    SmtpConfig,
    send_email,
)
from deltadewa.reporting.program_report import (
    HTML_STYLE,
    IpsComplianceSection,
    ProgramReport,
    build_program_report,
    render_html_body,
    render_markdown,
)
from deltadewa.reporting.weekly_snapshot import (
    SnapshotChange,
    SnapshotDiff,
    StandingBreach,
    WeeklySnapshot,
    diff_snapshots,
    snapshot_from_report,
    standing_breaches,
)
from deltadewa.state import ProgramState

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltadewa.analysis.roll_status import RollStatusRecord
    from deltadewa.ips_config import IpsConfig

_logger = logging.getLogger(__name__)

_DEFAULT_EXPORT_DIR = Path("exports")
_DEFAULT_IPS_PATH = Path("config/ips.yaml")
_WEEKLY_DIR_NAME = "reports/weekly"
_DEFAULT_ELAPSED_DAYS: Final[int] = 7  # nominal week, used only on first run

_ROLL_SEVERITY: Final[dict[str, int]] = {
    "HOLD": 0,
    "MONITOR": 1,
    "REVIEW": 2,
    "ROLL": 3,
}
_NO_POSITIONS_ROLL_VERDICT: Final[str] = "N/A"

_STALE_OR_WORSE: Final[frozenset[str]] = frozenset(
    {"STALE", "STATIC", "UNAVAILABLE"},
)

_EXIT_OK: Final[int] = 0
_EXIT_REFUSED: Final[int] = 1
_EXIT_SEND_FAILED: Final[int] = 2
_EXIT_BUILD_FAILED: Final[int] = 3

_SMTP_HOST_ENV_VAR: Final[str] = "SMTP_HOST"
_SMTP_PORT_ENV_VAR: Final[str] = "SMTP_PORT"
_SMTP_USERNAME_ENV_VAR: Final[str] = "SMTP_USERNAME"
_SMTP_PASSWORD_ENV_VAR: Final[str] = "SMTP_PASSWORD"  # ruff: ignore[hardcoded-password-string] -- var name, not a credential
_REPORT_EMAIL_TO_ENV_VAR: Final[str] = "REPORT_EMAIL_TO"
_REPORT_EMAIL_FROM_ENV_VAR: Final[str] = "REPORT_EMAIL_FROM"
_DIGEST_HEARTBEAT_ENV_VAR: Final[str] = "DIGEST_HEARTBEAT_URL"

# #319 (Batch 6b) — the footer for the non-technical reader.
_REPORT_EMAIL_FROM_NAME_ENV_VAR: Final[str] = "REPORT_EMAIL_FROM_NAME"
_DEFAULT_FROM_DISPLAY_NAME: Final[str] = "Weekly Hedge Digest"
_BIND_ADDR_ENV_VAR: Final[str] = "BIND_ADDR"
# compose.yaml's app service, both `ports:` and DELTADEWA_PORT.
_MONITOR_PORT: Final[int] = 8050
_CONTINUITY_ANNEX_URL: Final[str] = (
    "https://qwertytam.github.io/deltadewa-handbook/part-7/continuity-planning/"
)
# Two or three terms, tied to the sections that render on every digest —
# Cost (theta), Protection (convexity), IPS Compliance (IPS itself) — so
# a definition is never printed for a term this week's reader can't
# actually find above it. See docs/continuity-annex.md for what the
# whole program (not just these three words) can be trusted for.
_GLOSSARY: Final[tuple[tuple[str, str], ...]] = (
    (
        "Theta",
        (
            "the ongoing daily cost of holding this hedge in a normal "
            "market — like an insurance premium (§1 Cost, above)."
        ),
    ),
    (
        "Convexity",
        (
            "how much value the hedge itself gains if a crash happens "
            "— the reason it's held (§2 Protection, above)."
        ),
    ),
    (
        "IPS",
        (
            "Investment Policy Statement — this program's own written "
            "rules behind every PASS/FAIL above (§6 IPS Compliance)."
        ),
    ),
)


@dataclass(frozen=True)
class RollLegRow:
    """One leg's roll standing, ready to render (#374).

    A rendering-ready triple rather than the ``RollStatusRecord`` itself, so
    the two renderers below stay pure string work and the digest never
    reaches back into the analysis layer to format a number.

    Attributes:
        verdict: The leg's ``RollVerdict`` value, ``EXPIRED`` included.
        leg: ``"PUT 4200"`` — the same label ``/monitor`` uses.
        reason: The plain-language reason from
            ``roll_status.verdict_reason``.

    """

    verdict: str
    leg: str
    reason: str


def _roll_leg_rows(
    records: Sequence[RollStatusRecord],
) -> tuple[RollLegRow, ...]:
    """Build one row per leg, in portfolio order.

    Every leg, not just the worst one. The crossing line above reports the
    *change*; this reports the *standing state*, which is the division the
    rest of the digest already uses — and it is what lets a reader act
    without separately opening ``/monitor`` (#374).
    """
    return tuple(
        RollLegRow(
            verdict=record.verdict.value,
            leg=_leg_label(record),
            reason=verdict_reason(record),
        )
        for record in records
    )


def _leg_label(record: RollStatusRecord) -> str:
    """Name one leg the way both dashboards do: ``"PUT 4200"``."""
    option = record.position.option
    return f"{option.option_type.value} {option.strike_price:,.0f}"


def _worst_roll_record(
    records: Sequence[RollStatusRecord],
) -> RollStatusRecord | None:
    """Return the record carrying the worst roll verdict, or ``None``.

    Returns the *record*, not the verdict word (#374): the digest needs
    which leg and why, and everything but the word used to be discarded
    right here.

    Only gradable verdicts are considered. ``EXPIRED`` has no severity by
    design (#373) — an expired leg is gone, not urgent, and ranking it
    would let it dominate the headline over a real roll. Expired legs are
    reported through ``expired_leg_count`` instead, which crosses in its
    own right so a book whose only live leg expires cannot read as though
    the trigger resolved itself.

    Ties break on portfolio order — the first record wins. That has to be
    stable: two legs at ROLL that swapped places week to week would
    manufacture a phantom crossing out of an unchanged book.
    """
    gradable = [
        record for record in records if record.verdict in GRADABLE_VERDICTS
    ]
    if not gradable:
        return None
    return max(
        gradable,
        key=lambda record: _ROLL_SEVERITY[record.verdict.value],
    )


def _worst_roll_verdict(records: Sequence[RollStatusRecord]) -> str:
    """Return the worst gradable RollVerdict, or ``"N/A"``.

    ``"N/A"`` now means "no leg carries a roll grade" — an empty book, or
    one where every leg has expired (#373). Either way no position has a
    roll verdict, which is what the word reports.

    Mirrors ``roll_status._SEVERITY`` locally rather than importing that
    module's private name — the same convention ``weekly_snapshot.py``
    uses for ``program_report._STALE_OR_WORSE``.
    """
    worst = _worst_roll_record(records)
    if worst is None:
        return _NO_POSITIONS_ROLL_VERDICT
    return worst.verdict.value


def _expired_leg_count(records: Sequence[RollStatusRecord]) -> int:
    """Count legs already past maturity (#373)."""
    return sum(1 for record in records if record.verdict is RollVerdict.EXPIRED)


def _ordinal(n: int) -> str:
    """English ordinal for a positive integer (1st, 2nd, 3rd, 4th, 11th...)."""
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ── Pure assembly ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WeeklyDigest:
    """A fully assembled weekly digest: report, baseline, and the diff.

    Attributes:
        report: The underlying Part VII ``ProgramReport``.
        snapshot: This week's ``WeeklySnapshot`` (the new baseline).
        diff: Comparison against the prior snapshot (or the first-run case).
        roll_legs: Every leg's roll standing, in portfolio order (#374) —
            the state behind ``snapshot.worst_roll_verdict``, which is a
            one-word reduction over all of them.
        headline: One-line verdict for a subject line or quick triage —
            ``"BREACH: <metric> out of policy (Nth week)"`` when IPS
            compliance is failing (outranks everything else, #296),
            else ``"NO ACTION"`` or ``"ACTION: <first crossing>"``,
            prefixed ``"STALE DATA — "`` when data quality is worse than
            CACHED.
        weekly_carry_cost: This period's carry (theta) cost in dollars.
        elapsed_days: Days this ``weekly_carry_cost`` was integrated over
            (actual gap to the prior snapshot, or a nominal week on the
            first run).
        backup_heartbeat_warning: Human-readable caveat when
            ``ops/backup-exports.sh``'s last heartbeat ping failed, or
            ``None`` when it's unconfigured, unavailable, or last
            succeeded (#252). See ``_read_backup_heartbeat_warning``.

    """

    report: ProgramReport
    snapshot: WeeklySnapshot
    diff: SnapshotDiff
    headline: str
    weekly_carry_cost: float
    elapsed_days: int
    roll_legs: tuple[RollLegRow, ...] = ()
    backup_heartbeat_warning: str | None = None


def _headline(
    diff: SnapshotDiff,
    snapshot: WeeklySnapshot,
    compliance: IpsComplianceSection,
    breaches: tuple[StandingBreach, ...],
) -> str:
    """Derive the one-line triage verdict for this digest.

    Precedence: an IPS compliance breach outranks a threshold crossing,
    which outranks a quiet week. Branching on
    ``snapshot.ips_compliance_all_pass`` (the authoritative flag) rather
    than on ``breaches`` being non-empty is what makes "NO ACTION requires
    overall PASS" true by construction (#296). The ``"STALE DATA — "``
    prefix is applied identically to all three branches, unchanged from
    before — it's orthogonal to compliance state and must compose with it,
    never replace or gate it.
    """
    if not snapshot.ips_compliance_all_pass:
        failing = [row.metric for row in compliance.rows if not row.passes]
        weeks_by_metric = {b.metric: b.weeks for b in breaches}
        if len(failing) == 1:
            weeks = weeks_by_metric.get(failing[0], 1)
            base = (
                f"BREACH: {failing[0]} out of policy ({_ordinal(weeks)} week)"
            )
        else:
            weeks = min(weeks_by_metric.values(), default=1)
            base = (
                f"BREACH: {len(failing)} IPS metrics out of policy "
                f"({_ordinal(weeks)} week)"
            )
    elif diff.crossings:
        base = f"ACTION: {diff.crossings[0].label}"
    else:
        base = "NO ACTION"
    if snapshot.data_quality in _STALE_OR_WORSE:
        return f"STALE DATA — {base}"
    return base


def build_weekly_digest(
    *,
    report: ProgramReport,
    roll_records: Sequence[RollStatusRecord],
    history: Sequence[WeeklySnapshot] = (),
    as_of: date,
    rally: HedgeTriggerReason | None = None,
    worst_rally_pct: float | None = None,
    backup_heartbeat_warning: str | None = None,
) -> WeeklyDigest:
    """Pure assembly: report + roll records + history -> a WeeklyDigest.

    No I/O, no clock — every input is supplied by the caller, which is what
    makes this deterministic and what the golden-file test calls directly.
    ``rally``/``worst_rally_pct`` are the handbook Rule 2 book-level
    reading (#297), computed by the caller from the portfolio the same way
    ``roll_records`` is — this function never touches a portfolio. Omitting
    them yields ``UNAVAILABLE``, which is honest: a digest assembled
    without the reading has not measured it.

    ``backup_heartbeat_warning`` is no exception: ``main()`` reads it from
    disk (see ``_read_backup_heartbeat_warning``) and passes the resulting
    string (or ``None``) in here — this function still does no I/O of its
    own. Defaults to ``None`` so every existing caller, including the
    golden-file test, is unaffected.

    ``history`` is every prior snapshot, oldest first (see
    ``load_snapshot_history``); the prior snapshot is ``history[-1]`` when
    non-empty. Passing the full history (not just the prior snapshot) is
    what lets ``standing_breaches`` count how many consecutive weeks a
    currently-failing metric has been failing, for the headline (#296).
    Defaults to ``()`` — the first-run case.

    Requires ``report.decision`` to be set — ``build_program_report``
    always populates it, so this is only reachable from a hand-built
    ``ProgramReport`` that skipped it. Raising here, rather than silently
    reading a placeholder verdict, is what makes "the digest always
    carries a real decision verdict" true by construction rather than by
    every caller remembering to set one (#307).

    Also enriches ``report``'s ``ReturnFramingSection`` with the same
    weekly-carry figures computed here (Issue #171): before this, the
    digest's own lede stated the real carry-consumption numbers in prose
    while the embedded ``ProgramReport`` two sections further down still
    rendered ``PENDING`` — a genuine contradiction inside one document.
    Populating the report's own fields instead makes it the single place
    those numbers render; the lede no longer repeats them.
    """
    if report.decision is None:
        msg = (
            "build_weekly_digest requires report.decision to be set — "
            "build_program_report always populates it."
        )
        raise ValueError(msg)

    prior_snapshot = history[-1] if history else None
    worst_roll_record = _worst_roll_record(roll_records)
    worst_roll = (
        worst_roll_record.verdict.value
        if worst_roll_record is not None
        else _NO_POSITIONS_ROLL_VERDICT
    )
    if prior_snapshot is not None:
        elapsed_days = max((as_of - prior_snapshot.as_of).days, 0)
        first_as_of = prior_snapshot.first_as_of
        prior_cumulative = prior_snapshot.cumulative_carry_cost
    else:
        elapsed_days = _DEFAULT_ELAPSED_DAYS
        first_as_of = as_of
        prior_cumulative = 0.0

    weekly_carry_cost = (
        abs(report.cost.total_theta_annual) / 365.0 * elapsed_days
    )
    cumulative_carry_cost = prior_cumulative + weekly_carry_cost

    enriched_report = replace(
        report,
        return_framing=replace(
            report.return_framing,
            weekly_carry_cost=weekly_carry_cost,
            elapsed_days=elapsed_days,
            cumulative_carry_cost=cumulative_carry_cost,
            cumulative_since=first_as_of,
            premium_paid_point_in_time=report.protection.premium_paid,
        ),
    )

    snapshot = snapshot_from_report(
        enriched_report,
        decision_verdict=report.decision.verdict,
        worst_roll_verdict=worst_roll,
        worst_roll_leg=(
            _leg_label(worst_roll_record)
            if worst_roll_record is not None
            else None
        ),
        worst_roll_reason=(
            verdict_reason(worst_roll_record)
            if worst_roll_record is not None
            else None
        ),
        expired_leg_count=_expired_leg_count(roll_records),
        rally_status=(
            rally.status.value
            if rally is not None
            else TriggerStatus.UNAVAILABLE.value
        ),
        worst_rally_pct=worst_rally_pct,
        first_as_of=first_as_of,
        cumulative_carry_cost=cumulative_carry_cost,
    )
    diff = diff_snapshots(prior_snapshot, snapshot)
    breaches = standing_breaches(history, snapshot)

    return WeeklyDigest(
        report=enriched_report,
        snapshot=snapshot,
        diff=diff,
        headline=_headline(
            diff,
            snapshot,
            enriched_report.ips_compliance,
            breaches,
        ),
        roll_legs=_roll_leg_rows(roll_records),
        weekly_carry_cost=weekly_carry_cost,
        elapsed_days=elapsed_days,
        backup_heartbeat_warning=backup_heartbeat_warning,
    )


# ── Rendering ────────────────────────────────────────────────────────────


def _monitor_url() -> str | None:
    """Resolve this deployment's dashboard bookmark, or ``None``.

    Built from ``BIND_ADDR`` (RUNBOOK.md §10) — the only address this
    specific droplet is actually reachable at over Tailscale, and already
    read by the ``jobs`` container via ``env_file: .env`` (compose.yaml),
    so this needs no new configuration. ``None`` (never a loopback guess)
    when unset: a partner clicking a dead ``127.0.0.1`` link is worse
    than the plain-text fallback :func:`_footer_facts` uses instead.
    """
    bind_addr = os.environ.get(_BIND_ADDR_ENV_VAR)
    if not bind_addr:
        return None
    return f"http://{bind_addr}:{_MONITOR_PORT}/monitor"


def _footer_facts() -> tuple[str, ...]:
    """Facts appended to the digest footer, one per line (#319, Batch 6).

    Everything here is either always true (the version) or ties to a
    section (Cost, Protection, IPS Compliance) that renders on every
    digest — see :data:`_GLOSSARY` — so nothing risks describing a term
    or a link the reader in front of a particular week's digest can't
    actually use. A tuple, not a hardcoded string, so a further fact can
    be added without restructuring this function or its callers.
    """
    monitor_url = _monitor_url()
    dashboard_fact = (
        f"Dashboard: {monitor_url}"
        if monitor_url is not None
        else (
            "Dashboard: bookmark this program's own /monitor page — ask "
            "the operator for the address if you don't already have it "
            "saved."
        )
    )
    facts = [
        f"Running v{__version__}",
        dashboard_fact,
        (
            "No digest for two weeks usually means the system itself is "
            "down, not a quiet market — see the continuity annex: "
            f"{_CONTINUITY_ANNEX_URL}"
        ),
    ]
    facts.extend(f"{term}: {definition}" for term, definition in _GLOSSARY)
    return tuple(facts)


_URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"(https?://\S+)")


def _linkify_urls(escaped_text: str) -> str:
    """Wrap bare URLs in an already-``html.escape``d string with ``<a>``.

    Field-tested (#319): a footer fact like ``Dashboard: http://...``
    rendered as plain text is invisible as a link the moment the digest
    is opened as a raw ``.html`` file rather than viewed through a mail
    client's own auto-linkify pass — exactly what happened checking this
    against the deployed app. Applied *after* escaping, not before: a
    bare ``http(s)://`` URL contains no characters ``escape`` would
    touch, so running the regex second is safe and keeps every other
    caller of :func:`_footer_facts` (the markdown renderer, which wants
    plain text, not HTML) untouched.
    """
    return _URL_PATTERN.sub(r'<a href="\1">\1</a>', escaped_text)


def _from_header(from_addr: str) -> str:
    """Format the SMTP From header: *from_addr* with a friendlier name.

    ``REPORT_EMAIL_FROM`` (required, RUNBOOK.md §10) stays the actual
    sending address — it must remain a verified/allowed sender at the
    relay — this only changes what a recipient's inbox shows next to it,
    from a raw address like ``deltadewa-a1c2@relay.example.com`` to
    something a non-technical reader recognises (#319).
    ``REPORT_EMAIL_FROM_NAME`` is optional and read fresh here, not added
    to compose.yaml's required-for-email set: it's a cosmetic override, a
    deploy should never fail loudly for leaving it unset.
    """
    display_name = os.environ.get(
        _REPORT_EMAIL_FROM_NAME_ENV_VAR,
        _DEFAULT_FROM_DISPLAY_NAME,
    )
    return formataddr((display_name, from_addr))


def _changes_markdown(title: str, changes: tuple[SnapshotChange, ...]) -> str:
    if not changes:
        return ""
    lines = [f"**{title}:**", ""]
    lines += [f"- **{c.label}:** {c.detail}" for c in changes]
    lines.append("")
    return "\n".join(lines)


def _roll_legs_markdown(rows: tuple[RollLegRow, ...]) -> list[str]:
    """Render the per-leg roll table (#374), or nothing for an empty book."""
    if not rows:
        return []
    lines = [
        "## Roll status by leg",
        "",
        (
            "Where each leg stands right now. The crossing above reports "
            "what *changed*; this is the standing state behind it."
        ),
        "",
        "| Verdict | Leg | Reason |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {r.verdict} | {r.leg} | {r.reason} |" for r in rows]
    lines.append("")
    return lines


def _roll_legs_html(rows: tuple[RollLegRow, ...]) -> str:
    """HTML counterpart of :func:`_roll_legs_markdown` (#374).

    Every cell is escaped: ``reason`` is engine-built prose today, but it
    interpolates a strike and an expiry date, and this module escapes all
    user-influenced strings on principle (see ``program_report``'s note).
    """
    if not rows:
        return ""
    body = "\n".join(
        f"<tr><td>{escape(r.verdict)}</td><td>{escape(r.leg)}</td>"
        f"<td>{escape(r.reason)}</td></tr>"
        for r in rows
    )
    return (
        "<h2>Roll status by leg</h2>\n"
        "<p>Where each leg stands right now. The crossing above reports "
        "what <em>changed</em>; this is the standing state behind it.</p>\n"
        "<table>\n"
        "<tr><th>Verdict</th><th>Leg</th><th>Reason</th></tr>\n"
        f"{body}\n"
        "</table>"
    )


def render_weekly_digest_markdown(digest: WeeklyDigest) -> str:
    """Render the change-led lede, followed by the full program report."""
    s = digest.snapshot
    diff = digest.diff
    lines: list[str] = [
        f"# Weekly Digest — {digest.headline}",
        "",
        f"**As of:** {s.as_of}",
        "",
    ]

    if s.data_quality in _STALE_OR_WORSE:
        lines += [
            (
                f"> ⚠ **DATA QUALITY: {s.data_quality}** — every figure "
                "below is a reference value, not confirmed live market "
                "data. Sent anyway, stamped, per policy: never silently "
                "price on old data."
            ),
            "",
        ]

    if digest.backup_heartbeat_warning:
        lines += [f"> ⚠ **{digest.backup_heartbeat_warning}**", ""]

    lines += ["## What changed", ""]
    if diff.is_first_run:
        lines += [
            (
                "This is the first snapshot — there is no prior week to "
                "compare against yet. Next week's digest will show real "
                "week-over-week changes."
            ),
            "",
        ]
    else:
        lines.append(f"Compared against the snapshot from {diff.prior_as_of}.")
        lines.append("")
        crossings_md = _changes_markdown(
            "Threshold crossings",
            diff.crossings,
        )
        moves_md = _changes_markdown(
            "Other material moves",
            diff.material_moves,
        )
        if crossings_md:
            lines.append(crossings_md)
        if moves_md:
            lines.append(moves_md)
        if not diff.crossings and not diff.material_moves:
            lines += [
                (
                    "No changes crossed a threshold this week, and no "
                    "material moves either — a quiet week."
                ),
                "",
            ]

    lines += _roll_legs_markdown(digest.roll_legs)

    # Return framing (this week's/cumulative carry cost, point-in-time
    # premium) used to be repeated here in prose — now rendered once, by
    # the embedded report's own §4 (Issue #171: this lede's numbers used
    # to disagree with a PENDING two sections further down the same
    # document; program_report.build_program_report's §4 is now the
    # single source, enriched by build_weekly_digest above).
    lines += ["---", ""]

    footer = "\n".join(["---", *_footer_facts()])
    return (
        "\n".join(lines)
        + "\n"
        + render_markdown(digest.report)
        + "\n\n"
        + footer
        + "\n"
    )


def _changes_html(title: str, changes: tuple[SnapshotChange, ...]) -> str:
    if not changes:
        return ""
    items = "\n".join(
        f"<li><strong>{c.label}:</strong> {c.detail}</li>" for c in changes
    )
    return f"<p><strong>{title}:</strong></p>\n<ul>\n{items}\n</ul>"


def render_weekly_digest_html(digest: WeeklyDigest) -> str:
    """Render the change-led lede plus the full report as one HTML page."""
    s = digest.snapshot
    diff = digest.diff

    caveat_html = ""
    if s.data_quality in _STALE_OR_WORSE:
        caveat_html = (
            f'<div class="caveat">&#9888;&#160;<strong>DATA QUALITY: '
            f"{s.data_quality}</strong> &#8212; every figure below is a "
            "reference value, not confirmed live market data. Sent "
            "anyway, stamped, per policy: never silently price on old "
            "data.</div>"
        )

    backup_heartbeat_html = ""
    if digest.backup_heartbeat_warning:
        backup_heartbeat_html = (
            f'<div class="caveat">&#9888;&#160;<strong>'
            f"{digest.backup_heartbeat_warning}</strong></div>"
        )

    if diff.is_first_run:
        change_html = (
            "<p>This is the first snapshot — there is no prior week to "
            "compare against yet.</p>"
        )
    else:
        crossings_html = _changes_html("Threshold crossings", diff.crossings)
        moves_html = _changes_html(
            "Other material moves",
            diff.material_moves,
        )
        quiet_html = (
            "<p>No changes crossed a threshold this week, and no "
            "material moves either &mdash; a quiet week.</p>"
            if not diff.crossings and not diff.material_moves
            else ""
        )
        change_html = (
            f"<p>Compared against the snapshot from {diff.prior_as_of}.</p>"
            f"{crossings_html}{moves_html}{quiet_html}"
        )

    # Return framing (this week's/cumulative carry cost, point-in-time
    # premium) used to be repeated here in prose — now rendered once, by
    # the embedded report's own §4 (Issue #171; see the markdown
    # renderer's matching comment).
    lede = f"""<h1>Weekly Digest &mdash; {digest.headline}</h1>
<p><strong>As of:</strong> {s.as_of}</p>
{caveat_html}
{backup_heartbeat_html}
<h2>What changed</h2>
{change_html}
{_roll_legs_html(digest.roll_legs)}
<hr>"""

    footer_html = "\n".join(
        f'<p class="note">{_linkify_urls(escape(fact))}</p>'
        for fact in _footer_facts()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Weekly Digest &mdash; {digest.headline}</title>
<style>
{HTML_STYLE}
</style>
</head>
<body>

{lede}

{render_html_body(digest.report)}

<footer>
{footer_html}
</footer>

</body>
</html>"""


# ── Snapshot persistence ────────────────────────────────────────────────


def _snapshot_dir(export_dir: Path) -> Path:
    return export_dir / _WEEKLY_DIR_NAME


def load_snapshot_history(
    export_dir: Path,
    *,
    before: date,
) -> tuple[WeeklySnapshot, ...]:
    """Return every snapshot strictly before *before*, oldest first.

    Reads every snapshot file's own ``as_of`` field rather than trusting
    the filename, so a renamed or hand-copied file is still read
    correctly. ``build_weekly_digest``'s ``history`` parameter takes this
    return value directly; ``history[-1]`` is the prior snapshot.
    """
    weekly_dir = _snapshot_dir(export_dir)
    if not weekly_dir.exists():
        return ()

    candidates: list[WeeklySnapshot] = []
    for path in weekly_dir.glob("snapshot-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            snapshot = WeeklySnapshot.from_json_dict(data)
        except (OSError, ValueError, KeyError) as exc:
            _logger.warning("Skipping unreadable snapshot %s: %s", path, exc)
            continue
        if snapshot.as_of < before:
            candidates.append(snapshot)

    return tuple(sorted(candidates, key=lambda snap: snap.as_of))


def _write_snapshot(export_dir: Path, snapshot: WeeklySnapshot) -> Path:
    weekly_dir = _snapshot_dir(export_dir)
    weekly_dir.mkdir(parents=True, exist_ok=True)
    path = weekly_dir / f"snapshot-{snapshot.as_of.isoformat()}.json"
    path.write_text(json.dumps(snapshot.to_json_dict(), indent=2))
    return path


_BACKUP_HEARTBEAT_STATUS_FILENAME: Final[str] = ".backup-heartbeat-status.json"


def _read_backup_heartbeat_warning(export_dir: Path) -> str | None:
    """Surface ``ops/backup-exports.sh``'s last heartbeat failure (#252).

    That script runs as root, outside this app's Python environment
    entirely, and never fails its own job on a heartbeat-ping failure —
    matching this package's own ``deltadewa.heartbeat.ping()`` contract:
    a monitoring hiccup must not read as a backup outage. That deliberate
    silence would otherwise make a broken ``BACKUP_HEARTBEAT_URL``
    invisible, so the bash script records a small marker on failure
    (cleared on the next successful ping) at *export_dir* — the one
    filesystem path both that root cron and this `jobs` container share
    (``compose.yaml`` bind-mounts only ``exports/``, not the repo root).

    Returns:
        A human-readable caveat string when the marker is present and
        readable; ``None`` otherwise (no failure recorded, or the marker
        itself is missing/corrupt — treated as "nothing to report" rather
        than raised, since this is a best-effort surfacing, not the
        digest's core content).

    """
    status_path = export_dir / _BACKUP_HEARTBEAT_STATUS_FILENAME
    if not status_path.exists():
        return None
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        failed_at = data["failed_at"]
    except (OSError, ValueError, KeyError) as exc:
        _logger.warning(
            "Unreadable backup heartbeat status file %s: %s",
            status_path,
            exc,
        )
        return None
    return (
        f"Offsite backup heartbeat ping failed as of {failed_at} (see "
        "ops/backup-exports.sh, RUNBOOK.md §13) — the nightly exports/ "
        "backup itself may still be fine; only the dead-man's-switch "
        "ping did not go through."
    )


# ── Guarded body build (#364) ───────────────────────────────────────────


@dataclass(frozen=True)
class _RenderedDigest:
    """One week's assembled digest, plus its rendered markdown and HTML.

    Attributes:
        digest: The fully assembled ``WeeklyDigest``.
        markdown: ``render_weekly_digest_markdown(digest)``.
        html: ``render_weekly_digest_html(digest)``.

    """

    digest: WeeklyDigest
    markdown: str
    html: str


def build_and_render(
    *,
    state: ProgramState,
    ips_config: IpsConfig,
    as_of: date,
    period_label: str,
    export_dir: Path,
) -> _RenderedDigest:
    """Assemble and render this week's digest. Performs no writes.

    Every analysis call the digest depends on — the crash reprice, the
    market-environment read, the provenance ledger, carry, monetization,
    roll status, and the ``ProgramReport``/``WeeklyDigest`` assembly and
    render — lives here, unguarded. Raising here (rather than partially
    degrading) is deliberate: ``main()`` writes nothing on a raise, so a
    bad build never corrupts next week's snapshot baseline. See the module
    docstring / #364.

    Args:
        state: The already-loaded ``ProgramState`` (portfolio + IPS state).
        ips_config: The program's policy — ``state.ips_config``, passed
            explicitly since the caller has already confirmed it is not
            ``None``.
        as_of: The report date.
        period_label: Human-readable period label for the report header.
        export_dir: Shared state/export directory — read for market-data
            cache resolution and the prior snapshot history.

    Returns:
        The assembled digest and its rendered markdown/HTML strings.

    """
    portfolio = state.portfolio
    market_data = CboeFredProvider(
        cache_dir=default_cache_dir(),
        ttl=resolve_data_ttl(ips_config),
        read_only=True,
    )

    shock = CrashShock.from_ips(ips_config.convexity)
    crash_result = compute_crash_convexity(
        portfolio,
        shock=shock,
        ips_convexity=ips_config.convexity,
    )
    market_env = assess_market_environment(
        market_data,
        ips_config.market_environment,
    )
    # One ledger, reused rather than re-derived (Batch 3b's rule): the
    # digest's MarketContextSection.data_quality reads this same grade,
    # so a stale hand-entered pricing input turns the digest's caveat
    # exactly as it turns the live pages' banner (#367).
    provenance_ledger = build_provenance_ledger(
        market_env,
        portfolio,
        ips_config.pricing_inputs,
        as_of=as_of,
    )
    carry_metrics = PortfolioAnalyzer(portfolio).calculate_carry_metrics(
        MaturityBuckets.from_ips(ips_config.maturity_buckets),
    )
    monetization_plan = build_monetization_plan(
        portfolio,
        ips_config,
        market_env=market_env,
    )
    roll_records = evaluate_roll_status(portfolio, ips_config)
    # Handbook Rule 2 (#297), book-level: the most-rallied long put, named.
    worst_rally = worst_rally_from_entry(portfolio)
    rally_reading = rally_reason(
        worst_rally,
        HedgeTriggerThresholds.from_ips(ips_config.triggers),
    )

    report = build_program_report(
        portfolio=portfolio,
        ips_config=ips_config,
        crash_result=crash_result,
        carry_metrics=carry_metrics,
        market_env=market_env,
        provenance_ledger=provenance_ledger,
        period_label=period_label,
        as_of=as_of,
        monetization_plan=monetization_plan,
    )

    history = load_snapshot_history(export_dir, before=as_of)
    digest = build_weekly_digest(
        report=report,
        roll_records=roll_records,
        rally=rally_reading,
        worst_rally_pct=worst_rally[0] if worst_rally is not None else None,
        history=history,
        as_of=as_of,
        backup_heartbeat_warning=_read_backup_heartbeat_warning(export_dir),
    )

    return _RenderedDigest(
        digest=digest,
        markdown=render_weekly_digest_markdown(digest),
        html=render_weekly_digest_html(digest),
    )


def _send_build_failure_alert(exc: Exception, *, as_of: date) -> None:
    """Best-effort alert email when :func:`build_and_render` raised (#364).

    Never raises: a failure while trying to report the original build
    failure must not mask it. Missing/invalid SMTP env vars and a failed
    send are both logged and swallowed here — the same posture
    :func:`_send_digest_email` takes on the happy path, except this
    function has no exit code of its own to report through, since
    ``main()`` has already committed to returning ``_EXIT_BUILD_FAILED``
    regardless of whether this alert gets out.

    **Never pings the digest heartbeat.** Only a confirmed send of a real
    digest does that (see ``heartbeat.py``'s module docstring) — a
    build-failed run, like a refused or delivery-failed one, must leave
    the check un-pinged. The heartbeat and this alert are independent
    signals on purpose: if SMTP itself is the fault, this alert never
    arrives either, and the heartbeat must not be traded away for a
    redundant signal that can fail the exact same way.

    Args:
        exc: The exception :func:`build_and_render` raised.
        as_of: The report date the failed build was for.

    """
    try:
        host = os.environ[_SMTP_HOST_ENV_VAR]
        port = int(os.environ[_SMTP_PORT_ENV_VAR])
        username = os.environ[_SMTP_USERNAME_ENV_VAR]
        password = os.environ[_SMTP_PASSWORD_ENV_VAR]
        to_addr = os.environ[_REPORT_EMAIL_TO_ENV_VAR]
        from_addr = os.environ[_REPORT_EMAIL_FROM_ENV_VAR]
    except KeyError as env_exc:
        _logger.warning(
            "weekly_report: cannot send the build-failure alert — %s is "
            "not set",
            env_exc,
        )
        return
    except ValueError:
        _logger.warning(
            "weekly_report: cannot send the build-failure alert — %s is "
            "not a valid integer",
            _SMTP_PORT_ENV_VAR,
        )
        return

    detail = escape(f"{type(exc).__name__}: {exc}")
    footer_html = "\n".join(
        f'<p class="note">{_linkify_urls(escape(fact))}</p>'
        for fact in _footer_facts()
    )
    subject = f"Weekly Hedge Digest — FAILED to build ({as_of})"
    body_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{escape(subject)}</title>
<style>
{HTML_STYLE}
</style>
</head>
<body>

<h1>Weekly Hedge Digest &mdash; FAILED to build</h1>
<p>No digest was produced this week.</p>
<p><strong>No snapshot was written</strong>, so next week's digest will
compare across two weeks instead of one.</p>
<p>For detail, see <code>~/deltadewa/logs/weekly_report.log</code> on the
host, or RUNBOOK.md &sect;9.</p>
<p class="note">technical detail: &ldquo;{detail}&rdquo;</p>

<footer>
{footer_html}
</footer>

</body>
</html>"""

    message = EmailMessage(
        subject=subject,
        html_body=body_html,
        to_addr=to_addr,
        from_addr=_from_header(from_addr),
    )
    config = SmtpConfig(
        host=host,
        port=port,
        username=username,
        password=password,
    )
    try:
        send_email(message, config=config)
    except EmailDeliveryError as send_exc:
        _logger.warning(
            "weekly_report: build-failure alert send FAILED: %s",
            send_exc,
        )
        return

    _logger.info("weekly_report: build-failure alert emailed to %s", to_addr)
    # #364: deliberately no ping(...) call on this path — see this
    # function's docstring and heartbeat.py's module docstring for why.


# ── CLI ──────────────────────────────────────────────────────────────────


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for the weekly digest."""
    parser = argparse.ArgumentParser(
        description=(
            "Build the weekly hedge-program digest: what changed since "
            "last week, then the full Part VII program report."
        ),
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="Report date, YYYY-MM-DD (default: today).",
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=_DEFAULT_EXPORT_DIR,
        help=f"Shared state/export directory (default: {_DEFAULT_EXPORT_DIR}).",
    )
    parser.add_argument(
        "--ips-path",
        type=Path,
        default=_DEFAULT_IPS_PATH,
        help=f"Hedge program policy file (default: {_DEFAULT_IPS_PATH}).",
    )
    parser.add_argument(
        "--period-label",
        default=None,
        help='Human-readable period label (default: "Week of <as-of>").',
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        default=False,
        help=(
            "Send the digest over SMTP after writing it. Reads "
            f"{_SMTP_HOST_ENV_VAR}, {_SMTP_PORT_ENV_VAR}, "
            f"{_SMTP_USERNAME_ENV_VAR}, {_SMTP_PASSWORD_ENV_VAR}, "
            f"{_REPORT_EMAIL_TO_ENV_VAR}, {_REPORT_EMAIL_FROM_ENV_VAR} "
            "from the environment; opt-in so building the digest never "
            "requires mail credentials."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Build and write this week's digest.

    Returns:
        Process exit code: ``0`` on a confirmed send of a real digest (or,
        without ``--send-email``, on a successful build+write); ``1`` if
        refused (no IPS policy, or an empty book — a report built from
        neither is not a degraded report, it isn't a report); ``2`` if the
        digest was built and written but ``--send-email`` was requested and
        delivery failed (missing/invalid env vars, or an SMTP send
        failure) — distinct from ``1`` since the report files did get
        written successfully; ``3`` if state loading or
        :func:`build_and_render` itself raised (#364; the state-load case
        via R-a.3's blast-radius audit) — an input this module does not
        control failed partway through, no files (including the snapshot)
        were written, and — with ``--send-email`` — a best-effort
        plain-language failure alert was sent in place of the digest. The
        digest heartbeat
        (``DIGEST_HEARTBEAT_URL``) is pinged on **outcome 0 only**; ``1``,
        ``2``, and ``3`` all leave it un-pinged.

    """
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)

    try:
        state = ProgramState.load(args.export_dir, ips_path=args.ips_path)
        ips_config = state.ips_config

        # `date.today()` was the last naive clock read in the package: a
        # local date on whatever the host's timezone happened to be, which
        # on the UTC droplet running the cron dated a Sunday-evening digest
        # to Monday (#182). The digest's as-of now follows the same program
        # clock the book is priced on, so the snapshot it writes and the
        # prior snapshot it compares against are on one calendar.
        as_of: date = (
            args.as_of
            if args.as_of is not None
            else program_trading_date(
                ips_config.program.timezone if ips_config is not None else None,
            ).date()
        )
        period_label = args.period_label or f"Week of {as_of}"

        if ips_config is None:
            print(
                f"weekly_report: {args.ips_path} unavailable; refusing to "
                "build a policy-free report.",
                file=sys.stderr,
            )
            return _EXIT_REFUSED

        portfolio = state.portfolio
        if not portfolio.positions:
            print(
                "weekly_report: no positions in the book; load a "
                "portfolio first.",
                file=sys.stderr,
            )
            return _EXIT_REFUSED

        rendered = build_and_render(
            state=state,
            ips_config=ips_config,
            as_of=as_of,
            period_label=period_label,
            export_dir=args.export_dir,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Unanticipated on purpose, and deliberately wraps state loading
        # too, not just build_and_render: a blast-radius audit (R-a.3)
        # found ProgramState.load() sitting ahead of this guard, unguarded
        # — a raise there exited with Python's bare default (1), colliding
        # with _EXIT_REFUSED's documented meaning ("no IPS policy, or an
        # empty book") for what is actually a crash, not a clean refusal.
        # Matches panel_guard.safe_render's precedent (#363): a raise this
        # module did not foresee must not go unreported. No files — not
        # even a partial one — are written below this point. `as_of` may
        # not have been computed yet if state loading itself is what
        # failed, so the alert below falls back to the same default-
        # timezone resolution used when ips_config is None.
        _logger.exception("weekly_report: digest build FAILED")
        print(
            f"weekly_report: could not build the digest — {exc}",
            file=sys.stderr,
        )
        if args.send_email:
            alert_as_of = (
                args.as_of
                if args.as_of is not None
                else program_trading_date(None).date()
            )
            _send_build_failure_alert(exc, as_of=alert_as_of)
        return _EXIT_BUILD_FAILED

    weekly_dir = _snapshot_dir(args.export_dir)
    weekly_dir.mkdir(parents=True, exist_ok=True)
    md_path = weekly_dir / f"digest-{as_of.isoformat()}.md"
    html_path = weekly_dir / f"digest-{as_of.isoformat()}.html"
    md_path.write_text(rendered.markdown, encoding="utf-8")
    html_path.write_text(rendered.html, encoding="utf-8")
    snapshot_path = _write_snapshot(args.export_dir, rendered.digest.snapshot)

    print(rendered.digest.headline)
    print(f"Wrote {md_path}, {html_path}, {snapshot_path}")

    if args.send_email:
        failure_code = _send_digest_email(rendered.digest, rendered.html, as_of)
        if failure_code is not None:
            return failure_code

    return _EXIT_OK


def _send_digest_email(
    digest: WeeklyDigest,
    html_text: str,
    as_of: date,
) -> int | None:
    """Send *digest* over SMTP; ping the digest heartbeat on success.

    Returns:
        ``None`` on a confirmed send; otherwise the exit code ``main()``
        should return (``_EXIT_SEND_FAILED`` — required env vars missing/
        invalid, or the send itself failed).

    """
    try:
        host = os.environ[_SMTP_HOST_ENV_VAR]
        port = int(os.environ[_SMTP_PORT_ENV_VAR])
        username = os.environ[_SMTP_USERNAME_ENV_VAR]
        password = os.environ[_SMTP_PASSWORD_ENV_VAR]
        to_addr = os.environ[_REPORT_EMAIL_TO_ENV_VAR]
        from_addr = os.environ[_REPORT_EMAIL_FROM_ENV_VAR]
    except KeyError as exc:
        print(
            f"weekly_report: --send-email requires {exc} to be set; "
            "the digest was written above but not sent.",
            file=sys.stderr,
        )
        return _EXIT_SEND_FAILED
    except ValueError:
        print(
            f"weekly_report: --send-email requires {_SMTP_PORT_ENV_VAR} "
            "to be an integer; the digest was written above but not sent.",
            file=sys.stderr,
        )
        return _EXIT_SEND_FAILED

    config = SmtpConfig(
        host=host,
        port=port,
        username=username,
        password=password,
    )
    message = EmailMessage(
        subject=f"Weekly Hedge Digest — {digest.headline} ({as_of})",
        html_body=html_text,
        to_addr=to_addr,
        from_addr=_from_header(from_addr),
    )
    try:
        send_email(message, config=config)
    except EmailDeliveryError as exc:
        _logger.error("weekly_report: email delivery FAILED: %s", exc)
        print(f"weekly_report: email delivery FAILED — {exc}", file=sys.stderr)
        return _EXIT_SEND_FAILED

    _logger.info("weekly_report: digest emailed to %s", to_addr)
    ping(os.environ.get(_DIGEST_HEARTBEAT_ENV_VAR), label="digest")
    return None


if __name__ == "__main__":
    raise SystemExit(main())
