# deltadewa — Implementation Plan

Derived from the full review (`main @ 5998d5d`, reviewed 2026-07-15). This is a
working document: drive Claude Code through it one milestone at a time.

## Decisions locked

- **End goal:** semi-production.
- **Platform:** interactive `hedge_design` → **Dash**; `monitor` → **live view +
  headless report artifact**.
- **Sequencing:** fix the correctness (engine) layer first, *then* rebuild the UI
  in Dash on a trusted engine.
- **Obviated notebook UX findings** (M6, Mo5, Mo7, parts of M5/M2): skip the
  notebook versions; build them correctly, once, in Dash.
- **Docs:** refresh `CLAUDE.md` now (it misdirects agentic tooling); defer the
  rest of the doc sweep to post-migration.
- No backward/legacy compatibility required — clean changes welcome.

## Working agreement (applies to every milestone)

- **Plan mode first.** Propose file list + function signatures, get approval, then
  edit. (Matches `CLAUDE.md`.)
- **Tests-first** for anything in `analysis/`, `portfolio/`, `valuation/`,
  `persistence/`. New numeric behavior gets a regression test pinned to a
  handbook/IPS reference value.
- **One PR per milestone**, small conventional commits.
- **The gate must be green before "done":** `ruff check .`, `pylint deltadewa`
  (10.00), `mypy deltadewa` (strict), `pytest`. Until the notebooks are retired,
  also `nbqa ruff` + headless notebook execution.
- Read the sibling module before adding to it; match its style.

---

## Phase 0 — Tooling & memory (do literally first; < 1 session)

Highest leverage per line, because it makes every later Claude Code session and
every gate run more reliable.

- **M0.1 — `CLAUDE.md` refresh.** Fix the stale "Work in progress" section (sizing
  / strike-ladder / monetization are done, tested, and wired), the handbook path
  (`examples/` → `docs/`), and the test count (~47 → 70 files / 1,009 tests).
- **M0.2 — Gate hygiene (Mi3, tooling not docs).** Resolve the ruff D203/D211 and
  D212/D213 warnings, the pylint `W0012` from ruff rule names sitting in pylint's
  disable list, the pre-commit ruff pin (`0.14.9`) vs dev-group (`>=0.5.3`), and
  the mypy cache built under 3.14 against a 3.11 pin. *These degrade the gate you
  run every milestone — treating them as tooling, not the deferred doc sweep. Say
  the word if you'd rather defer.*

---

## Phase 1 — Correctness release (platform-independent)

All in `analysis/` / `portfolio/` / `valuation/` / `persistence/`. No UI. Survives
the migration unchanged. Maps onto the review's P0 + P1.

### M1.1 — Stop data loss & silent mispricing (P0)

- **C3** — preserve `entry_spot`, `entry_date`, `entry_premium`, `position_id`
  through `update_market_conditions()` (`core.py:471-496`). ~5 lines.
- **C2 (logic half)** — serialize `exercise_style` in JSON export/import and honor
  it on YAML import; default imports and factory from the IPS style; align
  `default_exercise_style` propagation in the import-apply step
  (`persistence.py:152-178,377-420,466-475`; `export_controls.py:264-280`). *The
  editor-dropdown default (`portfolio_controls.py:175`) is deferred to Dash.*
- **M4** — `set_volatility()` routes through `update_volatility()` so the displayed
  vol updates the QuantLib quote and invalidates the Greek cache
  (`core.py:154-162`).

**Acceptance:** European book → save JSON → reload stays European (no silent
American re-mark); moving the rate/dividend inputs preserves cost basis and
identity; `set_volatility(0.33)` reprices the leg. Round-trip + reprice regression
tests added.

### M1.2 — Crash-metric correctness core (P1, the flagship)

- **C1** — reimplement crash convexity per the handbook (line 1628): hedge-only,
  repriced at the crash spot via `BatchPricer`, with a configurable crash-vol
  shock, anchored at the IPS −25%. Remove the `include_underlying=True` /
  intrinsic path from the metric (`health.py:40-70`, `pnl.py:43-60`).
- **C4** — reprice sizing / strike-ladder candidates at the crash spot
  (`candidate.py:61-68`) with the same vol shock; keep intrinsic as an explicit
  "floor" column only.
- **Mo1** — single-source the crash scenario (−25%) from the IPS; remove the
  −20%/−25% split (`health.py:40` default `0.80`, README, `dashboard.yaml`).

**Acceptance:** regression test reproduces the handbook worked example
($150k → $1.2M on $10M = 10.5%). On the conformant $20M book, convexity lands in
the +15–25% band and the payoff ratio reads in multiples (not 1.05×); scenario
`meets_target` flips true; the `roll_status` convexity trigger stops chronically
firing.

### M1.3 — Decision-layer definitions (P1)

- **M1** — redefine `delta_drift` as drift of the *hedge's* delta versus a stated
  target hedge ratio (new IPS field), not distance from full neutrality
  (`health.py:101-118`, `hedge_triggers.py:165-169`); fix the gauge range/coloring
  assumptions and the unset-`underlying_quantity` degenerate-0 case.
- **M3** — reprice live legs at the horizon via `BatchPricer` in Monte Carlo and
  expiry P&L instead of valuing all legs at intrinsic at the nearest maturity
  (`monte_carlo.py:127-170`, `pnl.py:28-69`); explicitly label the risk-neutral
  drift (stop presenting "probability of profit" as real-world); swap in
  `vectorized_pnl_at_expiry` and correct the perf docstring.
- **Mo4** — compute a true vol-regime percentile from the VIX history the provider
  already downloads, or relabel honestly as min-max normalization
  (`health.py:155-183`).

**Acceptance:** a laddered −30% @ 12m book shows the ~$457k of live 18m/24m value
(not $0) in both MC and crash; delta-drift reads sanely against target on the
conformant book; the regime figure is a real percentile or honestly named.

### M1.4 — Config & trigger hygiene

- **Mo2** — move the `hedge_cost_verdict` thresholds out of `dashboard.yaml` into
  the IPS (policy vs presentation) (`market_environment.py:284-291`); dedup the
  vol band (0.15/0.35, currently in three places) and the skew bands (fractions
  vs percentiles) to one source; delete the validated-but-unused
  `ips.pricing.american_use_closed_form` knob (`ips_config.py:154`).
- **Mo3** — use `portfolio.valuation_date` not `now()`
  (`hedge_triggers.py:160`, `roll_status.py:231`); complete the `from_ips` mapping
  (expiry / gamma / theta-excellent are hardcoded); recalibrate the inert gamma
  bands (10/30 vs measured 0.23) to SPX scale or drive from IPS; add
  beta-adjustment (handbook §2499); make `underlying_quantity` fail loud rather
  than degrade metrics to 0.
- **Mi4 / Mi5 / Mi6** — naive-timestamp DTE (`position_detail.py:48`);
  `include_underlying` default mismatch between scalar and vectorized P&L;
  silently-dropped unsolvable ladder rungs; IPS `annual_carry_pct` default
  `2.0` → `1.0` (align to the handbook family-office ceiling it cites).
- **Crash vol-shock single-source** — tie `crash_vol_shock` to
  `crash_scenario_pct` so the two cannot diverge: when a crash scenario is
  supplied, the vol shock must be sourced from the IPS too. Remove the independent
  `= 0.0` fallback in `health.calculate_health_metrics` and `crash_payoff`
  (`compute_crash_convexity`) so a supplied scenario can never be repriced
  spot-only by omission. M1.2 made the `calculate_crash_convexity_pct` primitive
  require `crash_vol_shock`; this closes the same gap at the metric-assembly
  callers, where the `= 0.0` degradation default still pairs with a non-`None`
  scenario. Absent IPS must **disable** the crash gauges (the
  `crash_scenario_pct is None` path), not silently reprice at a 0.0 shock — same
  fail-loud-not-degrade discipline as `underlying_quantity` above.

**Acceptance:** what-if valuation dates move trigger/roll logic; no threshold
defined in two places; the shipped carry default matches its own handbook; a
supplied crash scenario can never be repriced with a spot-only (`0.0`) vol shock,
and a missing IPS disables the crash gauges rather than repricing spot-only.

### M1.5 — Engine test backfill (Mo6, the part that must precede re-skinning)

- Add the European-parity suite (the SPX-critical path has 3 tests vs 17 for the
  American default), direct tests for `health.py` (the gauge brain), and pin every
  C1–C4 / M1 / M3 behavior. Convert the most fragile `float ==` assertions to
  `pytest.approx` where crash-repricing introduces small numerical variation.

**Acceptance:** each fix above is guarded by a test that fails on the old
behavior.

> **Checkpoint:** at the end of Phase 1 the monitor notebook is unchanged but now
> shows correct numbers. Tag a **"correctness release"** here before touching UI.

---

## Phase 2 — Dash rebuild (build on the trusted engine)

### M2.1 — Split `dashboard/stress.py`

Extract the repricing + heatmap-grid construction (the analytics the review
praises) into `analysis/stress.py` with tests; leave only rendering for the UI
layer. Prereq for both the port and Mo6; fixes the 1,440-line untested-UI smell.

### M2.2 — Dash skeleton + shared layer

Multi-page Dash (`/design`, `/monitor`). Server-side session/state store — **this
is where M6 lands:** real session persistence, dirty-flag autosave under
`exports/`, import-overwrite guard, confirm-on-remove, built once. Shared
data-provider wrapper that surfaces as-of timestamps and an unmissable
**STATIC / STALE** banner (**M5**). App-level smoke tests (Dash testing harness /
Playwright — already a dependency) to replace the notebook-execution CI gate for
migrated surfaces.

### M2.3 — `hedge_design` → Dash workbench

Position editor gains the missing **`entry_premium`** and **`underlying_quantity`**
inputs (Mo3/Mo7). Reactive panels eliminate the Mo7 stale-panel / re-run-cells
problem entirely. Sizing / ladder / monetization / roll planners run on the
corrected engine. No red primary buttons; no leaked tracebacks or `DEBUG:` prints
(`stress.py:628-632`, `export_controls.py:541`). Import/export via the guarded
session layer (supersedes **Mo5**).

### M2.4 — `monitor` → live view

Read-mostly Tiers 1–4 on the corrected engine, with as-of stamps and staleness
banners everywhere. Resolve **M2**: wire hedge-success from the audit trail / entry
data, or omit it — recommend omit until realized tracking exists rather than ship a
permanently-inert gauge.

### M2.5 — Headless report artifact

Part VII board report as a parametrized, schedulable entrypoint (papermill or a
plain Python module) rendering deterministic PDF/HTML. **M8** content: return
framing from tracked start/end book values, realized monetization, and an as-of
stamp. Golden-file regression test. Retire the notebook-execution CI steps once
both surfaces are covered by app + report tests.

> **Checkpoint:** notebooks retired; CI green on the new (app + report) gate.

---

## Phase 3 — Docs & handbook (post-migration, per your call)

- README (chart stack, feature status, `__version__` 0.1.0 → 0.2.0) and a
  **QUICKSTART rewrite against the real API** (**M7** — Example 1 imports a
  nonexistent `AmericanOption`) — now stable against Dash, not thrown away.
- Mi1 residual drift: "Section 6/7" / "MODE 0" output references, "American
  options" comments (`core.py:537`, `valuation.py:1`).
- Mi2: correct the `batch_pricer.py:55` threading/`evaluationDate` claims and add
  a real safety test.
- Handbook additions the review flagged: a **repricing-methodology appendix**
  (the ambiguity that let C1/C4 happen — a "reprice at −25% with +X vol points"
  worked example), an SPX deep-OTM **execution** section, concentrated
  single-name **basis/beta** guidance, the §1256 **wash-sale** correction, a
  **cash/margin** section, and quantified **put-spread vs outright** economics.
  Reconcile the Quick Start "1–2%" vs benchmark "0.5–1.5% / 1% ceiling" tension.
- Add CHANGELOG / CONTRIBUTING / SECURITY; fix the LICENSE author vs repo-owner
  mismatch.

---

## Deferred — blocked on data feeds (backlog, not in this plan)

- **#12 Liquidity Risk** — needs a live options-chain feed (bid/ask, OI per
  strike).
- **#13 Delta Drift series** — needs a net-delta series from position history;
  partly unblocked by `analysis/scenarios.py`'s `scenario_grid`.
- **#14 Vega Term Exposure** — maturity-bucketed vega; `analysis/maturity.py`'s
  bucket logic (already used for theta carry) can extend.

---

## Finding → milestone index (coverage check)

| Finding | Milestone | Finding | Milestone |
|---|---|---|---|
| C1 | M1.2 | Mo5 | M2.3 (Dash; notebook version skipped) |
| C2 | M1.1 (logic) + M2.3 (editor default) | Mo6 | M1.5 + M2.1 |
| C3 | M1.1 | Mo7 | M2.3 (reactive UI; notebook version skipped) |
| C4 | M1.2 | Mi1 | M0.1 (`CLAUDE.md`) + Phase 3 (rest) |
| M1 | M1.3 | Mi2 | Phase 3 |
| M2 | M2.4 | Mi3 | M0.2 |
| M3 | M1.3 | Mi4 | M1.4 |
| M4 | M1.1 | Mi5 | M1.4 |
| M5 | M2.2 (Dash-native) | Mi6 | M1.4 |
| M6 | M2.2 (Dash-native; notebook version skipped) | Negligibles | Phase 3 / batch with nearest touch |
| M7 | Phase 3 | #12/#13/#14 | Deferred (data-blocked) |
| M8 | M2.5 | | |
| Mo1 | M1.2 | | |
| Mo2 | M1.4 | | |
| Mo3 | M1.4 (logic) + M2.3 (UI inputs) | | |
| Mo4 | M1.3 | | |
