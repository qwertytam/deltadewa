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

Nothing yet.

## [0.10.0] - 2026-11-14

**Every convexity PASS/FAIL now comes from one referee and agrees across
`/design`, `/monitor`, the digest and the roll plan.**

### Added

- **#461 — a dated roll action: `ROLL BY <date>`.** A leg in Rule 1's review
  buffer (outside the roll window, inside the 1.5x review band) is due, not
  overdue, so the roll plan no longer tells you to act today: it reads
  `ROLL BY` the date the window opens, and says why. `ROLL NOW` is kept for a
  trigger that has reached ROLL. `CHECKED`, `DELAY` and the in-window
  `ROLL NOW` are unchanged. The action and its date now appear wherever a
  leg's verdict does, from one function so they cannot differ:
  `/design`'s roll plan, the roll status table (under the verdict badge),
  `/monitor`'s Decisions rows, the digest's per-leg table (a new Action
  column) and its worst-roll crossing. The digest still reduces the verdict,
  so a `ROLL BY` leg beside a ROLL leg reports the ROLL. Existing weekly
  snapshot files load unchanged. Named `ROLL BY`, not `ROLL DUE`, because the
  position-aging panel already labels a leg inside the window `ROLL DUE`.

- **N7 — a "really?" note when every leg is marked at one IV.** The
  provenance panel (`/monitor`, `/design`) now says so when a book's legs
  sit at two or more distinct strike/maturity points but share one IV to
  the displayed 0.01% — the flat surface that *Mark pricing inputs
  reviewed* would otherwise confirm green. A nudge only: it changes no
  value and does not move the banner, `/health` or the digest. The weekly
  CONFIRM-vs-RE-MARK procedure is in `docs/continuity-annex.md`.

- **#451 — a written release procedure, and a test that holds it.**
  `docs/RELEASING.md` says when a version is bumped, how a release PR cuts
  `[Unreleased]` into a dated heading, that the annotated tag is pushed from
  `main` before any deploy, and that an ordinary PR adds its own entry under
  `[Unreleased]`. `tests/test_changelog.py` fails if the newest versioned
  heading and `pyproject.toml`'s version disagree, if `[Unreleased]` is not
  first, or if a heading has no link reference. A PR template carries the
  changelog and no-version-bump checklist lines.

### Changed

- **#463 — the time trigger's reason states the rule.** "216d to maturity,
  180d roll window" read as though a leg at 216d were already past the
  window; it was graded REVIEW for being in the buffer. The reason now says
  which side of the window the leg is on and where both edges are:
  "approaching the roll window (opens at 180d; review starts at 270d)",
  "inside the 180d roll window", or "not near the roll window (...)". Both
  numbers are read from the IPS. It shows in the roll status table,
  `/monitor`, the digest and the roll plan's reasoning.
- **#434, #431 — one referee for "is crash convexity inside the IPS band?"**
  The roll status table, the roll plan, the decision matrix, the compliance
  strip, the digest's protection table and compliance row, `/monitor`'s
  efficiency sentence and band bars, and `/design`'s sizing panel, candidate
  table and ladder composer all read one grade
  (`analysis/convexity_band.grade_convexity`) instead of thirteen separate
  comparisons. Bounds are inclusive at both ends, as before, so no verdict
  moves for a measured reading. What an operator will notice: a reading just
  under a band edge is printed with a second decimal ("9.96%", or "<10.00%")
  instead of rounding onto the edge beside its FAIL, and the ladder
  composer's IPS-depth cell now shows the strip's own figure (it printed
  "5.0%" beside a FAIL for a 4.99% reading). Only the crash depth the band is
  stated at is graded; the scenario table's other depths are no longer
  graded, so none can read "outside band".
- **#433 — a book with no underlying is "unmeasured", not a 0.0% breach.**
  Crash convexity has no protected notional to be a percentage of on such a
  book, so it is now unmeasured instead of `0.0`, which every grader read as a
  below-band miss: the roll status table marked every leg ROLL, the decision
  matrix said under-hedged, and the strip said FAIL. Now the roll trigger
  holds with "not measured", the decision is withheld, and the compliance row
  reads "—" with "Unmeasured, not breaching". The IPS compliance verdict has
  a third state, **INCOMPLETE** (nothing breached, but a metric could not be
  measured), in the `/monitor` and `/design` strip, the digest's Overall line
  and its headline (`INCOMPLETE: <metric> could not be measured`, ranked below
  a breach and above a crossing). Vega sufficiency's unmeasured row now reads
  the same way instead of FAIL. A standing-breach count is not started or
  extended by an unmeasured week. Existing weekly snapshot files load
  unchanged.
- **#436 — gross sizing is kept, and said so.** Sizing covers the crash offset
  on gross payoff while convexity is the gain over the hedge's value today,
  so a hedge sized
  exactly to the offset can land 0.1pp under the band floor. The decision is
  gross; no contract count changes. The sizing panel, the strike-candidate
  table and the ladder composer now say it beside "covers the offset", and a
  candidate that needs no contracts no longer reads "below target".

### Removed

- **#435 — `HealthMixin.calculate_health_metrics`.** An aggregator of nine
  "health" gauges that nothing had called since the Jupyter gauge wall went
  in Stage 4.3 (#279), kept only by its tests. It reported a crash convexity of
  `0.0` for a book with no underlying, the figure #433 retired. Nothing an
  operator sees changes. The individual methods it called stay (the live
  convexity gauge, `calculate_crash_convexity_pct`, is read by roll status,
  `/monitor`, `/design` and the digest); the tests that exercised the
  dictionary now call them directly.

### Fixed

- **#461 — the roll plan no longer shows `ROLL NOW` beside "no roll".** PUT
  5,600 (219d: time REVIEW, rally REVIEW, convexity in band) showed `ROLL NOW`
  with the rally trigger's "calls for no roll" as its reason, because two
  REVIEWs compared equal and the rationale quoted whichever it tested first.
  A leg's action is now the most urgent of what each trigger resolves to, and
  the reasoning names the trigger that produced it (ties: time, then
  convexity, then rally, the order the roll status table's reason uses).
- **#432 — the report's convexity row is labelled for what it measures.** The
  protection table, and so the weekly digest that embeds it, read "Convexity
  (net P&L % of book)". The figure is the hedge's own gain, which leaves out
  the underlying's loss; "net" means hedge plus underlying everywhere else.
  It now reads "Crash convexity (hedge gain % of book)".
- **#462 — the digest's data-quality line names the alarm.** It could read
  "STALE -> STALE", printing the merged grade on both sides of an alarm that
  flipped. It now says what crossed, "alarm raised (data quality STALE)", and
  shows the grade as an arrow only when it moved.
- **N8a — "Pricing input provenance" no longer renders as a duplicated
  heading pair.** The panel's collapsible `<summary>` repeated the
  section title; it now reads "Show all N inputs", and `/monitor` carries
  the section heading itself (outside the panel's error boundary).
- **W2/W3 — install docs match Poetry 2.** `QUICKSTART.md` and `README.md`
  no longer tell readers to run `poetry shell` (removed in Poetry 2.0), and
  `QUICKSTART.md` uses plain `poetry install` instead of Poetry-1's
  `--with dev`; both point at `poetry run`.


## [0.9.3] - 2026-11-10

> **One block, not one release.** This section is everything since `v0.7.0`.
> Versioned headings stopped at 0.7.0, so the tags `v0.8.0`–`v0.8.6`,
> `v0.9.0` and `v0.9.1` never got entries and `0.9.2` was never tagged.
> Entries were grouped by kind (Added/Changed/Removed/Fixed), not by
> release, and are not split back out here: use the PR numbers and the
> `v*` tags to place an entry. From this point each release gets its own
> heading, cut as `docs/RELEASING.md` describes. `v0.9.3` is tagged on `main`
> at the commit that merged #452.

### Added

- **#262 — `/design` Book changes panel.** A readable log of every change to
  the book, newest first: trades with their cash (fees shown as "not
  captured", never zero when unknown), edits that moved no cash, and
  corrections beside the fills they supersede. The headline counts changes
  since the latest boundary mark, and the panel names any lot the history
  cannot explain. It reads the position history (#313) rather than
  `ProgramState`'s change log, which was never written. New
  `analysis/book_changes.py`.

- **#313/#70 — the position history, and digest §4 without `PENDING`.**
  `exports/history/` records fills and boundary marks; digest §4 now reports
  realized carry (gross and net of monetization), the latest period and
  before/after-hedge return, and names every reason a period cannot be
  reconciled. `python -m deltadewa.history_cli init|mark|status`. Run
  `init` once after deploy (RUNBOOK §5.1). See `docs/part-x-coverage.md`,
  "The position history (8e.1)".

- **8d.2 (#410) — a ladder, as an object: the `/design` Ladder composer.**
  Compose strikes and weights (35/40/25 across 20/30/40% OTM is the
  handbook's example), size them as one ladder on the sizing workbench's own
  target, and score the blend beside the live book: carry vs budget, crash
  convexity at the IPS depth vs band, vega sufficiency, hedge efficiency, and
  crash gain by depth per rung and combined (-10/-20/-30/-40 plus the IPS
  depth; only the IPS depth is compared with the band). Seeds from the IPS
  ladder, else the book's own shape; "Add" buttons on the Strike candidates
  table feed it. New `analysis/ladder.py`; grading is
  `app/compliance.scorecard` (the strip's rows plus hedge efficiency), on a
  shadow book, so there is no second grader.
  **Operator note: new optional IPS section `strike_ladder:`** (`rungs:` of
  `{pct_otm, weight_pct[, maturity_years]}`, weights sum to 100, no code
  defaults, **not** a breaking change). Template entries with the handbook's
  example are in `config/ips.example.yaml` and `examples/ips/ips_default.yaml`;
  the live, gitignored `config/ips.yaml` needs an edit only to opt in. Run
  `python -m deltadewa.ips_config --check` to see it listed as unset.
- **N9 (8c, #415) — skew beta, Part X #9.** `analysis/skew_beta.py`
  measures the book's ∂V/∂Skew by repricing with one vol point of extra
  downside skew at the IPS wing anchor (the crash machinery's
  `crash_skew_vol`, no spot move, no flat bump) against today's value.
  `/design` gains a **Skew exposure (skew beta)** panel: one number, one
  chip. Ungraded — the handbook gives no band, and the panel says so.
- **N10 (8c, #416) — a hand-entered liquidity checklist, Part X #12.** The
  operator can record a bid/ask (and open interest) per held leg on
  `/design`'s new **Liquidity check (hand-entered)** panel. Spreads are
  graded against an optional `liquidity:` section in `ips.yaml`; each
  quote's age by the same rule as other hand-entered inputs; legs in a
  roll window are flagged for a fresh quote. Not a liquidity feed, and the
  panel says what #156's chain would add. Kept off the banner, the digest
  and `/health` deliberately.

  **Operator action (optional):** add a `liquidity:` section to the live
  `config/ips.yaml` to grade quotes — see `config/ips.example.yaml`. The
  handbook gives no number for a wide spread or low open interest, so
  there are no code defaults; without the section, quotes are recorded and
  shown ungraded.

### Fixed

- **#450 — the restore drill could name a version that was never tagged.**
  `config-backup/MANIFEST.json` recorded only `pyproject.toml`'s version,
  and RUNBOOK §7 does `git checkout v<app_version>`; `0.9.2` was deployed
  from `main` and never tagged, so that checkout had nothing to resolve.
  The manifest now also records `git_commit`, read out of the app
  checkout's `.git` as plain files (never by running git there, per #237),
  and `unknown` when it cannot be resolved. RUNBOOK §7 / §7.1 / §7.2
  prefer the commit and fall back to the tag. Manifests written before
  this change have no `git_commit` and use the tag path as before.

- **N5 (8c, #411) — `/design`'s market-environment panel leaked
  internals.** Entry-timing step 2 read `skew_percentile:
  0.876984126984127`; it now reads "2. Skew: 88th percentile (trailing
  5y) — …". Data-quality notes are operator prose ("Market data is STATIC:
  these are fixed reference values…") instead of
  `MarketEnvironment.vix is None with LIVE data_quality`; verdicts read
  "INSUFFICIENT DATA"; the skew row's "22th" is "22nd".
- **N5 (8c) — the "regime percentile" was not a percentile.** It is VIX's
  clamped position inside the IPS 15–35 band, not a rank against history
  — #175's mislabel on a path #175's fix never reached. It read "0" on
  days VIX ranked 7.5th over the trailing year and "53" on a day it ranked
  95th. Renamed `regime_band_position_pct`; the panel says "53% of the way
  up the band" or names the band edge it is past. No verdict changes.
- **N11 (8c, #417) — forward variance said "read against the hedge-cost
  verdict", which never reads it.** The row now states that the handbook
  gives no band and that the term-structure shape — what the verdict
  actually uses — stands in for one.

### Changed

- **#410 (8d.1) — one convexity, honest names.** The sizing workbench's
  and the candidate grid's "achieved convexity" is now the compliance
  strip's figure: crash **gain** (`V_crash - V_today`) over the
  *unadjusted* book notional, via `crash_convexity_pct` (which gains a
  `positions=` argument) and a new `CandidateMetrics.per_contract_convexity_pct`.
  It was `contracts x gross payoff / beta-adjusted notional`, graded
  against the same IPS band as the strip with nothing asserting the two
  matched. **Readings move**: lower by about premium / notional on every
  book, and no longer divided by beta when beta is not 1.0. Contracts
  sized, carry and the offset are unchanged. Pinned by
  `tests/test_analysis/test_convexity_agreement.py`.
- **#410 — `/design`'s "Strike ladder" panel is now "Strike candidates".**
  Each row was always a standalone single-strike candidate, sized to meet
  the whole crash offset alone, not a share of a ladder; its sizing
  columns now read "(alone)". `build_strike_ladder` / `LadderRung` /
  `StrikeLadderResult` / `StrikeLadder` are now `build_candidate_grid` /
  `GridCell` / `CandidateGridResult` / `CandidateGrid`, and the result's
  `.rungs` is `.cells`. The panel's anchor id (`section-strike-ladder`)
  is unchanged. The handbook's weighted ladder is the next piece (8d).
- **#410 — the sizing panel names which side of the band it is on.** A
  below-band convexity reading used to render "over target"; it now reads
  "below target" (or "above target").
- **#317 (8c) — the skew percentile is ranked over the handbook's trailing
  five years (1260 sessions), not an unsourced 252.** The window is now IPS
  policy, `market_environment.skew_lookback_days`, and is stated beside
  every skew percentile the program quotes ("88th percentile (trailing
  5y)") — the handbook's condition for ranking over any window at all.
  **This moves every reported skew percentile.** On 2026-11-06 the reading
  was 90.5 on 252 sessions and 87.6 on 1260: both above the 70 cut, so that
  day's "defer — skew expensive" verdict did not move. But over the
  preceding year the two windows labelled 84 of 252 sessions differently,
  and always in the same direction — the five-year window read LOW
  (accumulate) on 5 sessions where the one-year window read LOW on 70, a
  consequence of SKEW's upward drift since 2021. Expect fewer "accumulate
  aggressively" readings. Cboe's SKEW history runs back to 1990, so the
  window is fully covered; a series shorter than the window now raises
  rather than silently ranking a truncated sample, and the refresh job
  logs it.

  **Operator action:** the live, gitignored `config/ips.yaml` inherits the
  new 1260 default unless it says otherwise. Add
  `skew_lookback_days: 1260` under `market_environment:` to take the
  handbook window deliberately, or `252` to keep the old one (the handbook
  permits it, provided the window is stated — which every surface now
  does). `python -m deltadewa.ips_config --check` lists the key as missing
  until then. The first weekly digest after the switch reports the window
  change instead of a SKEW-percentile move.

### Removed

- **#312** — the matplotlib half of `deltadewa/visualization/` is retired:
  `base.py` (`OptionCharts`), its five mixins (`crash_charts`,
  `greeks_charts`, `pnl_charts`, `scenarios`, `theta_charts`),
  `convenience.py` and `_protocols.py`, with the 7 test files that exercised
  only them (51 tests; the suite goes 2774 → 2723, no surviving test edited).
  Also removed: the five `Styler.background_gradient` functions in
  `formatters/dataframes.py` (they imported matplotlib lazily, had no caller
  and no test) and the matplotlib axis-formatter factories in
  `formatters/values.py`. `matplotlib`, `pillow` and their five transitives
  leave `poetry.lock` (78 → 71 packages).

  The two halves had zero import edges between them, verified before
  anything was deleted. The production image is unchanged: both packages
  were `dev`-group only. Recorded rather than acted on: nothing reads
  `OptionPortfolio.monte_carlo_results` back any more. See
  `docs/part-x-coverage.md`.

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

[Unreleased]: https://github.com/qwertytam/deltadewa/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/qwertytam/deltadewa/compare/v0.9.3...v0.10.0
[0.9.3]: https://github.com/qwertytam/deltadewa/compare/v0.7.0...v0.9.3
[0.7.0]: https://github.com/qwertytam/deltadewa/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/qwertytam/deltadewa/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/qwertytam/deltadewa/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/qwertytam/deltadewa/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/qwertytam/deltadewa/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/qwertytam/deltadewa/releases/tag/v0.4.0
