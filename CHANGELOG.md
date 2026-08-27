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

### Removed

- **#279** — the leftover Jupyter layer is retired: `deltadewa/dashboard/`
  (12 modules), `deltadewa/widgets/` (11), `deltadewa/config.py`, their 253
  tests, the symbols they were the last caller of
  (`formatters/gradients.py` and `formatters/html.py` whole, plus
  `create_diverging_style`, `apply_table_preset`, `update_export_dir`,
  `create_default_portfolio`, `get_days_to_furthest_maturity` and
  `StaticProvider.from_assumptions`), the unread
  `dashboard_config_*.yaml` presentation surface (template, four
  `examples/dashboard/` presets, and `docs/dashboard-config-guide.md`), and
  the entire ipywidgets/Jupyter dependency stack — `poetry.lock` drops from
  166 to 80 packages and IPython is no longer installed at all.

  Stage 4.3 had deleted the notebooks that were this layer's only product
  consumer but deliberately left the layer itself; this closes that. The
  orphaning was verified **import-path-qualified**, because three retired
  modules shared a bare name with a live `analysis/` module
  (`roll_status.py`, `position_aging.py`, `stress.py`). Symbols that lost
  their last caller but were kept are annotated at the function.

  Two findings are recorded rather than acted on: `triggers.rally_rebalance_pct`
  is validated and documented but read by nothing (the handbook's ["Rule 2 —
  Market Rally Rebalance
  Trigger"](https://qwertytam.github.io/deltadewa-handbook/part-7/rolling-rules/#rule-2-market-rally-rebalance-trigger)
  was never built), and the matplotlib half
  of `deltadewa/visualization/` is a second orphan set of the same shape.
  See `docs/part-x-coverage.md`.

  *[Link repointed 2026-08-19: this entry originally cited an anchor inside the
  handbook's `HANDBOOK.md`, which became a stub when the handbook was extracted
  to its own repo (#246). It now points at the same section on the published
  site. The finding recorded above is unchanged.]*

### Fixed

- **#364** — the weekly digest's body build (market-data read through
  rendering the markdown/html strings, `weekly_report.build_and_render`)
  is now guarded: a raise from an input this module doesn't control (a
  provider outage, a repricing edge case) used to take the whole cron job
  down unhandled. `main()` now writes no files at all on a build failure —
  not even a partial one, so next week's digest still compares against
  last week's real snapshot — logs and prints the failure, sends a
  best-effort plain-language alert email when `--send-email` was
  requested, and exits `3` (new, alongside the existing `0`/`1`/`2`). The
  digest heartbeat contract stays exact: `DIGEST_HEARTBEAT_URL` is pinged
  only on a confirmed send of a real digest (outcome `0`) — refused,
  delivery-failed, and build-failed all leave it un-pinged, on purpose.
- **#375** — the crash-convexity figure and the digest's §2 Protection
  section now name any long-put leg they silently excluded for being
  already expired (#362's fix), instead of the exclusion being invisible.
  `CrashConvexityResult.excluded_expired` and
  `ProtectionSection.excluded_expired_legs` carry the dropped legs
  hedge-only — a short leg or expired call was never in the figure and
  never appears in the caveat. Rendered as a caveat line on `/monitor`'s
  compliance strip and as a note block after the digest's §2 table.
- **#365** — `OptionPortfolio.add_position` refuses to add a maturity that
  is already at or before the book's valuation date by default
  (`reject_expired=True`), naming both dates in the error. Restore paths
  (`persistence.py`'s JSON/YAML importers) opt out explicitly — a real
  historical or autosaved book can legitimately hold a leg that expired
  after being added, and refusing the whole file over one such leg is the
  wrong failure mode. The importer CLI and `/design`'s import button both
  surface an advisory naming any already-expired legs found on import.
  `analysis/position_aging.py` gains an `EXPIRED` bucket (sorting ahead of
  `URGENT`) for `days_to_expiry <= 0`, matching the same boundary.
- **#377** — the market-data refresh job's own `LIVE` tally only proved a
  write happened *in that process*; nothing confirmed the app could
  actually read it back, which was #300's original acceptance criterion
  for this job. `refresh_all()` now returns `(live, total)` — `live`
  maps each series that fetched live to the `fetched_at` its write
  recorded — and a new `verify_read_back()` re-reads each of those
  series through a **separate, read-only** `CboeFredProvider` over the
  same resolved `cache_dir`, rather than trusting the writer's own
  tally. A series verifies iff the re-read doesn't raise and its
  `fetched_at` is `>=` (not `==`) what was recorded: `vix`/`vix_history`
  share one on-disk cache key, so the second write legitimately
  overwrites the first's `fetched_at` on every healthy run, and an
  exact-equality check would falsely flag that pair as a
  write-readability failure every time. `main()` gains exit code `3`
  (fetched live, but none of it read back — distinct from exit `2`,
  nothing fetched live at all); exits `2` and `3` both withhold the
  heartbeat ping, same as before.
- **#378** — nothing verified that the read-only Dash app and the
  refresh job actually resolve `DELTADEWA_CACHE_DIR` to the same
  directory at runtime; `default_cache_dir()`'s docstring had overclaimed
  they "agree by construction," true only of the *resolution logic*, not
  of the two `compose.yaml` literals that actually feed it. The refresh
  job now writes a small manifest (`write_cache_manifest`, `_policy.py`)
  into its resolved `cache_dir` on every run, recording that path,
  when it ran, and each series' `fetched_at`, independent of whether
  #377's read-back check passes. A new `/health` boot-wiring check,
  `cache_manifest_matches`, reads that manifest (`read_cache_manifest`)
  and compares its recorded `cache_dir` against what the app process
  itself resolved — a missing or mismatched manifest degrades `status`
  (HTTP stays 200, per #309). `compose.yaml` hardcodes both services'
  `DELTADEWA_CACHE_DIR` identically today, so this is a detector for
  future drift (#378 is scoped P2), not evidence of a divergence
  happening now.

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
