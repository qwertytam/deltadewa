"""Headless, deterministic weekly digest — the M2.6 report entrypoint.

Usage::

    python -m deltadewa.reporting.weekly_report [--as-of YYYY-MM-DD]
        [--export-dir exports] [--ips-path config/ips.yaml]
        [--period-label "Week of 2026-08-05"]

Assembles the same ``ProgramReport`` the notebook builds, but **leads with
what changed since last week** — verdict crossings, band exits, staleness —
rather than repeating a near-identical report 52 times a year. Return
framing shows the week's own carry cost alongside the cumulative figure
since the first snapshot, so a single week of pure theta doesn't read as a
loss story on its own (see ``weekly_snapshot.py`` for why that cumulative
figure is carry cost, not premium paid — the latter is a stock, not a
flow, and would double-count or miss cash entirely across a roll).

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
This is opt-in (default off) so building the digest never requires mail
credentials — only the cron line that actually wants delivery passes the
flag. A missing/invalid env var or a failed send both exit **2**,
distinct from the **1** used when the report itself was refused: at that
point the report files are already written successfully, and a delivery
failure must never look like exit-0 success. On a confirmed send,
``DIGEST_HEARTBEAT_URL`` (``deltadewa.heartbeat``) is pinged — the *only*
path that pings it, per the dead-man's-switch design: a missing weekly
email is exactly the kind of silence that gets rationalised as "quiet
week," so it must alarm rather than ping regardless.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Final

from deltadewa.analysis import (
    CrashShock,
    PortfolioAnalyzer,
    assess_market_environment,
    build_monetization_plan,
    compute_crash_convexity,
    decision_matrix,
    evaluate_roll_status,
)
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
    ProgramReport,
    build_program_report,
    render_html_body,
    render_markdown,
)
from deltadewa.reporting.weekly_snapshot import (
    SnapshotChange,
    SnapshotDiff,
    WeeklySnapshot,
    diff_snapshots,
    snapshot_from_report,
)
from deltadewa.state import ProgramState

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deltadewa.analysis.roll_status import RollStatusRecord

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

_SMTP_HOST_ENV_VAR: Final[str] = "SMTP_HOST"
_SMTP_PORT_ENV_VAR: Final[str] = "SMTP_PORT"
_SMTP_USERNAME_ENV_VAR: Final[str] = "SMTP_USERNAME"
_SMTP_PASSWORD_ENV_VAR: Final[str] = "SMTP_PASSWORD"  # ruff: ignore[hardcoded-password-string] -- var name, not a credential
_REPORT_EMAIL_TO_ENV_VAR: Final[str] = "REPORT_EMAIL_TO"
_REPORT_EMAIL_FROM_ENV_VAR: Final[str] = "REPORT_EMAIL_FROM"
_DIGEST_HEARTBEAT_ENV_VAR: Final[str] = "DIGEST_HEARTBEAT_URL"


def _worst_roll_verdict(records: Sequence[RollStatusRecord]) -> str:
    """Return the worst RollVerdict across every position's record.

    Mirrors ``roll_status._SEVERITY`` locally rather than importing that
    module's private name — the same convention ``weekly_snapshot.py``
    uses for ``program_report._STALE_OR_WORSE``.
    """
    if not records:
        return _NO_POSITIONS_ROLL_VERDICT
    return max(
        (record.verdict.value for record in records),
        key=lambda v: _ROLL_SEVERITY[v],
    )


# ── Pure assembly ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WeeklyDigest:
    """A fully assembled weekly digest: report, baseline, and the diff.

    Attributes:
        report: The underlying Part VII ``ProgramReport``.
        snapshot: This week's ``WeeklySnapshot`` (the new baseline).
        diff: Comparison against the prior snapshot (or the first-run case).
        headline: One-line verdict for a subject line or quick triage —
            ``"NO ACTION"``, ``"ACTION: <first crossing>"``, prefixed
            ``"STALE DATA — "`` when data quality is worse than CACHED.
        weekly_carry_cost: This period's carry (theta) cost in dollars.
        elapsed_days: Days this ``weekly_carry_cost`` was integrated over
            (actual gap to the prior snapshot, or a nominal week on the
            first run).

    """

    report: ProgramReport
    snapshot: WeeklySnapshot
    diff: SnapshotDiff
    headline: str
    weekly_carry_cost: float
    elapsed_days: int


def _headline(diff: SnapshotDiff, snapshot: WeeklySnapshot) -> str:
    """Derive the one-line triage verdict for this digest."""
    if diff.crossings:
        base = f"ACTION: {diff.crossings[0].label}"
    else:
        base = "NO ACTION"
    if snapshot.data_quality in _STALE_OR_WORSE:
        return f"STALE DATA — {base}"
    return base


def build_weekly_digest(
    *,
    report: ProgramReport,
    decision_verdict: str,
    roll_records: Sequence[RollStatusRecord],
    prior_snapshot: WeeklySnapshot | None,
    as_of: date,
) -> WeeklyDigest:
    """Pure assembly: report + verdicts + prior baseline -> a WeeklyDigest.

    No I/O, no clock — every input is supplied by the caller, which is what
    makes this deterministic and what the golden-file test calls directly.
    """
    worst_roll = _worst_roll_verdict(roll_records)
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

    snapshot = snapshot_from_report(
        report,
        decision_verdict=decision_verdict,
        worst_roll_verdict=worst_roll,
        first_as_of=first_as_of,
        cumulative_carry_cost=cumulative_carry_cost,
    )
    diff = diff_snapshots(prior_snapshot, snapshot)

    return WeeklyDigest(
        report=report,
        snapshot=snapshot,
        diff=diff,
        headline=_headline(diff, snapshot),
        weekly_carry_cost=weekly_carry_cost,
        elapsed_days=elapsed_days,
    )


# ── Rendering ────────────────────────────────────────────────────────────


def _fmt_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def _changes_markdown(title: str, changes: tuple[SnapshotChange, ...]) -> str:
    if not changes:
        return ""
    lines = [f"**{title}:**", ""]
    lines += [f"- **{c.label}:** {c.detail}" for c in changes]
    lines.append("")
    return "\n".join(lines)


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

    lines += [
        "## Return framing",
        "",
        (
            f"This week consumed **{_fmt_money(digest.weekly_carry_cost)}** "
            f"in carry (theta) cost over {digest.elapsed_days} day(s) — "
            "budget consumption, not a return; a tail hedge is priced to "
            "bleed carry on a quiet week."
        ),
        (
            f"**Since {s.first_as_of}:** "
            f"{_fmt_money(s.cumulative_carry_cost)} in cumulative carry "
            "cost consumed."
        ),
        (
            f"Current book's point-in-time premium invested: "
            f"{_fmt_money(s.premium_paid_point_in_time)} "
            "(a snapshot of the current book's cost basis — not summed "
            "across weeks; a roll would otherwise show as a jump, not "
            "an accumulation)."
        ),
        "",
        "---",
        "",
    ]

    return "\n".join(lines) + "\n" + render_markdown(digest.report)


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

    lede = f"""<h1>Weekly Digest &mdash; {digest.headline}</h1>
<p><strong>As of:</strong> {s.as_of}</p>
{caveat_html}
<h2>What changed</h2>
{change_html}
<h2>Return framing</h2>
<p>This week consumed <strong>{_fmt_money(digest.weekly_carry_cost)}</strong>
in carry (theta) cost over {digest.elapsed_days} day(s) &mdash; budget
consumption, not a return.</p>
<p><strong>Since {s.first_as_of}:</strong>
{_fmt_money(s.cumulative_carry_cost)} in cumulative carry cost consumed.</p>
<p>Current book's point-in-time premium invested:
{_fmt_money(s.premium_paid_point_in_time)} (a snapshot, not summed across
weeks).</p>
<hr>"""

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

</body>
</html>"""


# ── Snapshot persistence ────────────────────────────────────────────────


def _snapshot_dir(export_dir: Path) -> Path:
    return export_dir / _WEEKLY_DIR_NAME


def load_prior_snapshot(
    export_dir: Path,
    *,
    before: date,
) -> WeeklySnapshot | None:
    """Return the most recent snapshot strictly before *before*, or None.

    Reads every snapshot file's own ``as_of`` field rather than trusting
    the filename, so a renamed or hand-copied file is still read correctly.
    """
    weekly_dir = _snapshot_dir(export_dir)
    if not weekly_dir.exists():
        return None

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

    if not candidates:
        return None
    return max(candidates, key=lambda snap: snap.as_of)


def _write_snapshot(export_dir: Path, snapshot: WeeklySnapshot) -> Path:
    weekly_dir = _snapshot_dir(export_dir)
    weekly_dir.mkdir(parents=True, exist_ok=True)
    path = weekly_dir / f"snapshot-{snapshot.as_of.isoformat()}.json"
    path.write_text(json.dumps(snapshot.to_json_dict(), indent=2))
    return path


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
        Process exit code: ``0`` on success; ``1`` if refused (no IPS
        policy, or an empty book — a report built from neither is not a
        degraded report, it isn't a report); ``2`` if the digest was built
        and written but ``--send-email`` was requested and delivery
        failed (missing/invalid env vars, or an SMTP send failure) —
        distinct from ``1`` since the report files did get written
        successfully.

    """
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)
    as_of: date = args.as_of if args.as_of is not None else date.today()
    period_label = args.period_label or f"Week of {as_of}"

    state = ProgramState.load(args.export_dir, ips_path=args.ips_path)
    ips_config = state.ips_config
    if ips_config is None:
        print(
            f"weekly_report: {args.ips_path} unavailable; refusing to "
            "build a policy-free report.",
            file=sys.stderr,
        )
        return 1

    portfolio = state.portfolio
    if not portfolio.positions:
        print(
            "weekly_report: no positions in the book; load a portfolio first.",
            file=sys.stderr,
        )
        return 1

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
    carry_metrics = PortfolioAnalyzer(portfolio).calculate_carry_metrics()
    monetization_plan = build_monetization_plan(
        portfolio,
        ips_config,
        market_env=market_env,
    )
    convexity_now_pct = next(
        (
            row.convexity_pct
            for row in crash_result.scenario_rows
            if row.shock_pct == ips_config.convexity.crash_scenario_pct
        ),
        crash_result.payoff_ratio or 0.0,
    )
    decision_result = decision_matrix(
        market_env,
        convexity_now_pct=convexity_now_pct,
        ips_convexity=ips_config.convexity,
        monetization_plan=monetization_plan,
    )
    roll_records = evaluate_roll_status(portfolio, ips_config)

    report = build_program_report(
        portfolio=portfolio,
        ips_config=ips_config,
        crash_result=crash_result,
        carry_metrics=carry_metrics,
        market_env=market_env,
        period_label=period_label,
        as_of=as_of,
        monetization_plan=monetization_plan,
    )

    prior_snapshot = load_prior_snapshot(args.export_dir, before=as_of)
    digest = build_weekly_digest(
        report=report,
        decision_verdict=decision_result.verdict.value,
        roll_records=roll_records,
        prior_snapshot=prior_snapshot,
        as_of=as_of,
    )

    weekly_dir = _snapshot_dir(args.export_dir)
    weekly_dir.mkdir(parents=True, exist_ok=True)
    md_path = weekly_dir / f"digest-{as_of.isoformat()}.md"
    html_path = weekly_dir / f"digest-{as_of.isoformat()}.html"
    html_text = render_weekly_digest_html(digest)
    md_path.write_text(render_weekly_digest_markdown(digest), encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")
    snapshot_path = _write_snapshot(args.export_dir, digest.snapshot)

    print(digest.headline)
    print(f"Wrote {md_path}, {html_path}, {snapshot_path}")

    if args.send_email:
        failure_code = _send_digest_email(digest, html_text, as_of)
        if failure_code is not None:
            return failure_code

    return 0


def _send_digest_email(
    digest: WeeklyDigest,
    html_text: str,
    as_of: date,
) -> int | None:
    """Send *digest* over SMTP; ping the digest heartbeat on success.

    Returns:
        ``None`` on a confirmed send; otherwise the exit code ``main()``
        should return (``2`` — required env vars missing/invalid, or the
        send itself failed).

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
        return 2
    except ValueError:
        print(
            f"weekly_report: --send-email requires {_SMTP_PORT_ENV_VAR} "
            "to be an integer; the digest was written above but not sent.",
            file=sys.stderr,
        )
        return 2

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
        from_addr=from_addr,
    )
    try:
        send_email(message, config=config)
    except EmailDeliveryError as exc:
        _logger.error("weekly_report: email delivery FAILED: %s", exc)
        print(f"weekly_report: email delivery FAILED — {exc}", file=sys.stderr)
        return 2

    _logger.info("weekly_report: digest emailed to %s", to_addr)
    ping(os.environ.get(_DIGEST_HEARTBEAT_ENV_VAR), label="digest")
    return None


if __name__ == "__main__":
    raise SystemExit(main())
