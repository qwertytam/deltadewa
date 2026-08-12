# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project uses [Semantic Versioning](https://semver.org/).

Entries are grouped by the milestone they actually shipped under
(`docs/implementation-plan.md`'s `M1.x`/`M2.x` numbering), not just by
conventional-commit type, since that's how the work happened and how a
milestone-level "what changed" question gets answered fastest. Each entry
cites the PR(s) it shipped in. Reconstructed from `git log` against the
`v0.4.0`–`v0.7.0` tags and `docs/implementation-plan.md`; pre-`v0.4.0`
history (`v0.3.0-correctness` and earlier — most of Phase 1, `M1.1`–`M1.5`)
predates this file and is not backfilled, to avoid a reconstruction that
drifts from what actually happened. See the `v*` git tags and their PR
history for that record instead.

## [Unreleased]

No changes merged to `main` since the `v0.7.0` tag yet.

## [0.7.0] - 2026-08-11

Phase 3 close-out work merged since `v0.6.0` — clock/day-count
correctness, the notebook retirement, and the defect-driven docs pass:

- **#182** — `deltadewa/clock.py`, a single program trading-day source
  (`program_trading_date`, `days_between`) replacing ad hoc
  `datetime.now()`/timestamp-subtraction day counts across the package —
  fixes a day-count floor that crossed roll/expiry triggers a day early
  and a UTC clock that rolled the book's valuation date at 20:00 ET (#265).
- **Stage 4.3** — both Jupyter notebooks, `example.py`,
  `deltadewa/widgets/health_dashboard.py` (the gauge wall), and the
  `nbstripout`/`nbqa`/`jupytext` toolchain retired — `/monitor` and
  `/design` cover what they used to (#242, #263).
- **#247** — convexity-cliff panel ported to `/design`.
- **#245/#249** — `config/ips.yaml` and `config/dashboard.yaml` gitignored
  in favor of tracked `.example.yaml` templates (#248);
  `examples/ips/ips_default.yaml` sanitized of the live-looking values it
  had mirrored since the first IPS commit, closing the gap #245's own
  audit missed (#257). #245 itself stays open — the current-state fix is
  complete, but the exposed git history still needs a remediation
  decision; see `SECURITY.md`.
- **#243/#244** — ops hardening: `BACKUP_REMOTE` required with no
  hardcoded fallback and self-healing on every run (not just first init),
  log rotation for the deploy-owned log stanza, `docs/RUNBOOK.md` scrubbed
  of the real backup-repo host/alias and SMTP provider specifics (#250).
  Follow-up hardening: `su` directive fix for the logrotate deploy stanza
  (#254), environment beating `backup.env` for `BACKUP_REMOTE`/
  `HEARTBEAT_URL` precedence (#255), and verifying the remote before
  pinging the heartbeat on a clean-tree backup run (#256).
- **Stage 4.5 — Phase 3 defect-driven docs** (#170, #179, #180, #185, #268)
  — `QUICKSTART.md`'s examples rewritten against the real API (every one
  crashed on import; #170); stale American-only/notebook-era references
  corrected in `valuation.py`, `OptionPortfolio`, and the dead `dashboard/`
  layer (#179); `BatchPricer`'s false thread-safety claim corrected — safe
  today because concurrent workers share one valuation date, not because
  the global `evaluationDate` goes untouched, and `OptionValuation`'s
  numeric theta fallback additionally mutating it mid-computation was
  flagged, not fixed (#180, tracked separately as #266); four `#185`
  negligible-nits items (cache-key collision between VIX and SKEW spot
  reads, a relative rather than absolute spot bump, a proof the
  double-fallback-returns-0 gamma path is unreachable) plus the flaky
  `test_monitor.py` DTE assertion found by `gate-runner` mid-verification
  (#267, now closed).
- `CHANGELOG.md` (this file), `CONTRIBUTING.md`, `SECURITY.md` added —
  none existed before (#185 item 5, #269). `SECURITY.md` names #245 as
  the still-open git-history remediation decision rather than presupposing
  it resolved.

## [0.6.0] - 2026-08-10

Bug fixes on top of the `M2.6`/`M2.7`/`M2.8` work below — no new milestone
content, just loose ends (#234–#239):

- `reporting/weekly_report.py`: stop the report contradicting the digest
  it's embedded in (#234).
- Docker: non-root container user with self-healing `exports/` ownership
  (#235), and the entrypoint ownership + backup dead-man's-switch fix
  (#237/#238).
- Market-data refresh job: always fetch live and stop counting cache hits
  as refreshes (#239).

## [0.5.0] - 2026-08-07

- **M2.5 — The design workbench** (#223, #226) — the `/design` page:
  position editor, roll planning, stress testing, exploration panels.
  Pinned the planning zone's crash basis against the engine (#225).
- **M2.6 — Headless report, cron, and backup (the heartbeat)** (#227) —
  the weekly digest, market-data refresh job, offsite `exports/` backup,
  and a two-check dead-man's-switch; closes Phase 2. Refactored the
  digest's email delivery to a provider-agnostic SMTP transport (#229).
- **M2.7 — Restore the Part X coverage the Dash rebuild dropped** (#231)
  — five surfacing-gap regressions found by a Part X re-audit (#230):
  Vega Sufficiency, the net-delta scalar, a new `/design`
  market-environment panel (carrying the decision matrix), and the
  convexity÷carry ratio (`analysis/hedge_efficiency.py`, new).
- **M2.8 — Delta Drift, Vega Term Exposure, and the entry-timing VIX
  policy leak** (#232).

## [0.4.2] - 2026-08-04

- Monitor scenario curve panel (#221).

## [0.4.1] - 2026-08-04

- **M2.3 — Deploy the thin app** (#216) — close-out; the Dash skeleton
  verified live.
- **M2.4 — The monitor (lead with the crash)** (#217) — the crash-led
  `/monitor` page: book review, IC/board reporting. `docs/RUNBOOK.md` §5
  updated for the now-live monitor (#219).
- CLI portfolio import (#218).

## [0.4.0] - 2026-08-03

Phase 1 close-out and the start of Phase 2, tagged together:

- **M1.6 — Skew-aware crash shock** (#199, #200).
- **M1.7 — Unify the crash-shock skew across book and candidate
  surfaces** (#201, #203).
- **M1.8 — `CrashShock`: thread the crash pricing basis as one value
  object** (#204, #205).
- **M1.11 — Clock-shift determinism probe** (#206–#208) — the
  `make test-clockshift` matrix; see `CLAUDE.md`'s "Environment &
  commands" for why it's advisory, not gating.
- Security dependency updates (#202).
- **M2.1 — Extract the compute layer** (#210, #211) — a shock-driven
  pricing primitive with a pluggable vol mapping, behind the widgets.
- **M2.2 — Dash skeleton + shared layer** (#212) — the two-page app
  scaffold and `state.ProgramState`. Observation provenance (#213).

[Unreleased]: https://github.com/qwertytam/deltadewa/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/qwertytam/deltadewa/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/qwertytam/deltadewa/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/qwertytam/deltadewa/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/qwertytam/deltadewa/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/qwertytam/deltadewa/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/qwertytam/deltadewa/releases/tag/v0.4.0
