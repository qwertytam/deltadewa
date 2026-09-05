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

- **#326** — the strike ladder had three distinct dead ends and one
  undifferentiated paragraph for all of them, so a panel showing only its
  own inputs could mean "you typed something unparseable", "the book has
  no underlying to size against", or "every rung you asked for is
  unsolvable". Each now renders as its own notice, via a new
  `app/panel_guard.panel_notice` with a `NoticeKind` of `INPUT` /
  `BLOCKED` / `EMPTY` / `ERROR`. A panel that *raised* remains
  `safe_render`'s job — unchanged; a panel that *returned an empty
  result* is a different failure and gets the new `EMPTY` state, which
  names every unsolvable rung and its reason and draws no table at all. A
  partial solve keeps its table and lists the rest under "Unsolvable".
  `safe_render` also takes a `blocked_hint`, so the sizing and ladder
  panels can say which zone to go fix.

- **#334** — the expiration calendar and position-aging tables netted a
  long and a short leg in the same row to one figure, so a real offsetting
  pair rendered as `$0`/`$0` — indistinguishable from an empty row. The net
  is still the headline (it is what unwinding the row realises today), but
  a new frozen `analysis.position_aging.SignedTotals` now carries the long
  and short sides separately, `contracts`/`position_value`/`position_theta`
  delegate to it as properties so there is one source of truth for net
  vs gross, and a row mixing sides renders an `L … · S …` line beneath the
  net. A row that both offsets *and* nets to ~zero is flagged amber, so the
  one case the issue was about is the one case that draws the eye.

- **#316** — the sizing workbench and strike ladder seeded their maturity
  dials from a hardcoded `0.5`/`0.5, 1.0, 2.0` rather than from policy, so
  a program that buys 18-month protection opened both panels on tenors it
  does not trade. A new optional `maturity_selection:` IPS section
  (`entry_tenor_years` / `maintain_min_years` / `maintain_max_years`,
  validated `0 < min <= entry <= max`) now owns them. **Additive and
  non-breaking** — omit the section and the built-in 1.5/1.0/2.0 defaults
  apply. The dials stay user-editable; the IPS only decides where they
  start.

- **#330** — the time-x-price stress heatmap sorted its price index
  descending, which on Plotly's bottom-to-top categorical axis put the
  lowest spot at the top, inverted relative to the spot-x-vol heatmap
  beside it. Sorted ascending. Confirmed to be an axis-orientation fix
  only: `matrix`, `text` and `y_labels` all derive from the same
  `pivot.index`, so no cell can be mispaired with its label.

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

- **#386** — RUNBOOK §4's routine deploy steps rebuilt the image and cut
  over in the same breath, so a breaking IPS schema change (config baked
  in at build time) only surfaced as a live 500 after cutover, with no
  step in between to catch it. §4 now runs
  `docker compose run --rm app python -c "..."` against the freshly built
  image before cutover — `run --rm` reaches the new image in a throwaway
  container; `exec` would only reach the old one still running — and
  states the "config is baked in at build time" fact once, in §4, instead
  of only in §5. §5's own policy-edit procedure had the same gap (a single
  rebuild instruction with no explicit cutover step) plus a verify `curl`
  that didn't mention `boot_wiring.ips_loaded`; `/health` is 200 even when
  degraded by design (#309), so a bare 200 there doesn't catch a policy
  that failed to load or a rebuild that was never cut over. Both fixed the
  same way: an explicit rebuild-then-cutover pair, and a verify step that
  names the boot-wiring check to look at instead of just the status code.

- **#381** — `_serve_layout()`'s chrome build and the `/health` route both
  called `assess_market_environment`/`build_provenance_ledger` outside any
  guard; `panel_guard.safe_render` (#363) covers every panel below them,
  but a raise one layer up took the whole page, or the endpoint the
  dead-man's-switch reads, with it. A new `panel_guard.safe_chrome`
  (reusing the existing `NoticeKind` vocabulary rather than a second
  notice idiom) now wraps the chrome build, degrading to a banner louder
  than any real freshness warning — silence there would otherwise read as
  "all inputs fresh." `/health` gets its own independent try/except around
  a freshly-called `_assess_provenance()`, never a value shared with the
  page render (the isolation `panel_guard`'s own docstring warns a shared
  precomputed value would defeat, #376), and reports `status: "degraded"`
  plus a named `provenance_error` at HTTP 200 rather than a 500 — so the
  dead-man's-switch stays alive and diagnosable instead of dying with the
  fault it exists to report (#364's shape, one layer up).

- **#385** — an unloadable `ips.yaml` was logged and dropped
  (`state.py`'s `except IpsConfigError`), so both `/monitor` and `/design`
  could only say "see the server log at startup" for a message that was
  one `str(exc)` away. `ProgramState.ips_load_error`/`ips_path` now carry
  the parse error and the attempted path forward from `load()`'s except
  block; a new `app/ips_notice.build_no_ips_layout` renders the exact
  message on both pages, plus the container-vs-host caveat — the file
  named is the one baked into the running container at its last build,
  not necessarily the host's current copy, which is #386's subject and
  exactly where the two can differ.

- **#323/#357** — there was no in-app navigation at all: switching pages
  meant editing the URL by hand, and a long single-scroll `/design` had
  no way to jump to a section. Cross-page nav (`chrome.py`'s
  `build_page_nav`/`nav_items`) sits in the shared chrome as a sibling of
  `safe_chrome`'s guarded provenance banner, not inside it — nav has no
  data dependency and must survive a banner failure. In-page nav is a
  derived "jump to" TOC (new module `app/section_nav.py`), not a
  scroll-tracking rail — a scroll-spy needs either a real `assets/*.js`
  file (the one class of product code this repo's gate cannot see) or
  constant `dcc.Interval` polling, and #358 had already declined
  client-side machinery for the same reason. Every panel under
  `pages/design/` gets one `SECTION: SectionSpec` constant driving both
  its heading and its TOC entry, so the TOC cannot drift from the
  rendered page without a test catching it.

- **#358** — the strike ladder's results table had no way to sort by any
  column (e.g. cheapest by Premium, highest Achieved convexity). A small
  server-side sort over the domain objects (`ladder.py`'s
  `_sort_rungs`/`_toggle_sort_state`), per #390's decision — not a
  `dash_table.DataTable` migration, since DataTable cells are data, not
  the `verdict-badge` components this table renders. Every comparator
  normalizes to `float` so there's one numeric ordering, not a mixed
  `float | int | bool` union; the sort is stable, so tied rows keep their
  original order across re-renders.

- **#388** — no `@media print` block existed at all, so a Chromium
  print-to-PDF of either page split table rows and panel headers across
  page boundaries wherever the page height happened to land.
  `break-inside: avoid` (plus the legacy `page-break-inside` fallback) on
  `/design`'s `.panel` wrapper and `/monitor`'s five per-section wrappers,
  and on every `<tr>` across all four table classes in the app; no
  on-screen change, since every rule is scoped inside `@media print`.
  `table-header-group` on `<thead>` (so a table spanning a break repeats
  its header) does not actually take effect under Chromium's headless
  print-to-PDF path — a confirmed engine limitation, not an app defect —
  recorded separately as #404 rather than reopening this issue.

- **#315** — the five scenario-numbers headline figures on `/monitor`
  (Hedge value shocked, Hedge gain, Underlying loss, Net, Offset ratio)
  had no hover definition, unlike Offset ratio's own pre-existing one; a
  returning operator or partner had to re-derive what each meant from
  memory. Each label now carries a native `title=` tooltip naming the
  exact field it reads (`monitor_scenario.ScenarioResult`'s own
  docstring), so the tooltip can't drift from the engine; Hedge gain's
  also names the roll plan, not the number itself, as what decides
  whether a large loss away from the crash scenario is worth acting on.

- **#320** — the nightly offsite backup (`ops/backup-exports.sh`) was
  unencrypted, plaintext at the remote and in every clone of it. The push
  is now `age`-encrypted to two independent recipients — the operator's
  own key and a second key deliberately escrowed for the continuity
  scenario (`docs/continuity-annex.md`); either alone decrypts a backup.
  What the nested `exports/.git` repo tracks changed shape from the raw
  files directly to a single encrypted archive, rebuilt only when content
  actually changes — `age`'s ciphertext is non-deterministic even for
  identical input, so a naive diff-the-ciphertext check would re-commit
  every single night regardless of whether anything did.
  `SECURITY.md`/`docs/RUNBOOK.md`/`docs/continuity-annex.md` were all
  updated in the same change. `.env` still never rides this channel,
  encrypted or not — that exclusion was always architectural (host-only,
  never through a container's `env_file`), not a plaintext-vs-encrypted
  trade this closes.

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
