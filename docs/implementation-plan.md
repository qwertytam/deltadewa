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
  (10.00), `mypy deltadewa` (strict), `pytest`. The clock-shift probe (M1.11)
  is deliberately **outside** this list — see there for why. (`nbqa ruff` +
  headless notebook execution were part of this gate until M2.6 retired them
  from CI — the app + report tests now cover both notebook surfaces; see
  M2.6's close-out for the coverage mapping.)
- Read the sibling module before adding to it; match its style.

---

## Phase 0 — Tooling & memory (do literally first; < 1 session)

**Status: done** — PRs #186, #187, #188.

Highest leverage per line, because it makes every later Claude Code session and
every gate run more reliable.

- **M0.1 — `CLAUDE.md` refresh.** Fix the stale "Work in progress" section (sizing
  / strike-ladder / monetization are done, tested, and wired), the handbook path
  (`examples/` → `docs/`), and the test count (~47 → 70 files / 1,009
  tests, as of the 2026-07-15 review). <!-- Every raw test/file count in
  this doc's milestone close-outs is a dated snapshot, not the current
  suite size — deliberately not kept fresh, because a hardcoded number
  here re-drifts by design and no gate step catches it (this exact figure
  did, within the same phase). See #207. Current size:
  `poetry run pytest --co -q | tail -1`. -->
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

**Status: done** — PRs #189, #190.

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

**Status: done** — PRs #192, #193. Spec: `docs/repricing-methodology.md`.

- **C1** — reimplement crash convexity per the handbook (line 1628): hedge-only,
  repriced at the crash spot via `BatchPricer`, with a configurable crash-vol
  shock, anchored at the IPS −25%. Remove the `include_underlying=True` /
  intrinsic path from the metric (`health.py:40-70`, `pnl.py:43-60`).
- **C4** — reprice sizing / strike-ladder candidates at the crash spot
  (`candidate.py:61-68`) with the same vol shock; keep intrinsic as an explicit
  "floor" column only.
- **Mo1** — single-source the crash scenario (−25%) from the IPS; remove the
  −20%/−25% split (`health.py:40` default `0.80`, README, `dashboard.yaml`).

**Acceptance (as shipped):** regression tests pin the methodology §4 worked
example — hedge value today ≈ $297,715, in crash ≈ $3,895,901 (13.1×), convexity
**+18.0%**, intrinsic floor ≈ $759,000 — on the conformant $20M book, which lands
inside the +15–25% band with `meets_target` true; the `roll_status` convexity
trigger stops firing spuriously. The §4 book ships as a loadable example
(`examples/portfolios/spx_tail_20m.yaml`); the band assertion anchors on it, not on
`spx_protective_put.yaml` (invariants only there).

> **Superseded by M1.6.** The skew-aware shock recomputed these §4 anchors to
> crash ≈ $4,788,166 (16.1×), convexity **+22.5%** (still in-band); V_today
> ($297,715) and the intrinsic floor ($759,000) are unchanged. The flat values
> above (+18.0% / 13.1×) are now pinned as the `skew=0.0` no-op proof.

### M1.3 — Decision-layer definitions (P1)

**Status: done** — PR #194.

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

**Status: done** — PR #195.

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

- **Canonical example convexity — measured, decision made (2026-07-19).**
  `examples/portfolios/spx_protective_put.yaml` reads **+14.27%** under the shipped
  flat vol bump — ~0.7pp under the 15% floor. Measured alternative: under a modest
  crash-skew steepening the *same* book reads **+15.4%** (in band). **Signed off:
  refine the shock, do not re-size.** No sizing change made. Full rationale and the
  work itself now live in **M1.6** below.

**Acceptance:** what-if valuation dates move trigger/roll logic; no threshold
defined in two places; the shipped carry default matches its own handbook; a
supplied crash scenario can never be repriced with a spot-only (`0.0`) vol shock,
and a missing IPS disables the crash gauges rather than repricing spot-only.

### M1.5 — Engine test backfill (Mo6, the part that must precede re-skinning)

*Order within Phase 1: FIX 1 (to green) → M1.5a (exercise-style) → European-parity → health.py → stress.py → approx sweep → close-out. Tests are written against the post-M1.5a signatures.*

- Add the European-parity suite (the SPX-critical path has 3 tests vs 17 for the
  American default), direct tests for `health.py` (the gauge brain), and pin every
  C1–C4 / M1 / M3 behavior. Convert the most fragile `float ==` assertions to
  `pytest.approx` where crash-repricing introduces small numerical variation.
- Add characterization tests for `dashboard/stress.py` (~1,440 lines, zero
  coverage) **before** M2.1 extracts it — grid shapes, monotonicity, real time
  value via `BatchPricer`, cache-hit reuse reproducing first-pass values exactly,
  and a small golden grid on `spx_tail_20m.yaml`. These exist to make the
  extraction a provably pure refactor.

- **Residual from M1.4 — last spot-only degradation path (must land before the
  tag).** `crash_payoff.compute_crash_convexity` still takes
  `ips_convexity: IpsConvexity | None = None` and derives
  `vol_shock = ips_convexity.crash_vol_shock if ... else 0.0` (`crash_payoff.py`
  ~L363). When `ips_convexity` is omitted the fallback does **not** merely drop the
  IPS-anchored row: it reprices the **entire curve and every scenario row**
  spot-only, understating all 51 grid points while still looking plausible. It is
  documented in a comment rather than surfaced, and the M1.4 tie closed this at
  `health.calculate_health_metrics` but not here.
  **Resolution — separate the pricing input from the policy target.** Make
  `crash_vol_shock` an **explicit required parameter** of
  `compute_crash_convexity` (and of the `scenario_rows` wrapper at ~L447), so
  every caller must state the shock it is pricing with and no path can reprice
  spot-only by omission. Keep `ips_convexity` optional, but **only** for the
  target-band comparison (`target_min_pct` / `target_max_pct`) — it must no longer
  carry a pricing input. Update the two call sites
  (`crash_payoff.py:447`, `dashboard/crash_payoff_display.py:185`) to source the
  shock from `IpsConvexity.crash_vol_shock`. Same fail-loud-not-degrade discipline
  as `calculate_crash_convexity_pct` (M1.2) and `underlying_quantity` (M1.4).
  **Status: signatures done (commit `33f8fbd`); NOT yet green** — 21 tests still call
  `compute_crash_convexity()` without the required shock. Updating those call sites is
  part of this fix, not a follow-up: the PR merges only once the gate is green. Tests
  that assert a §4 golden must pass the shock that golden was computed with (`0.15`);
  others pass an explicit realistic value.

**Acceptance:** each fix above is guarded by a test that fails on the old
behavior; the `stress.py` characterization suite passes unchanged across the M2.1
extraction; **no crash-repricing entry point retains a defaulted vol shock** —
pinned by a test asserting `compute_crash_convexity` cannot be called without an
explicit `crash_vol_shock`, plus a repo-wide check that no `= 0.0` (or otherwise
defaulted) vol-shock parameter survives in any crash path.

### M1.5a — Remove forbidden American exercise-style defaults (own PR, before the tag)

**Status: signatures drafted, rollout deferred to this milestone.** Surfaced by the
M1.5 audit. This is a genuine correctness defect, not hygiene, so it gates the tag:
`ExerciseStyle.AMERICAN` is the silent default at `valuation.py:64`,
`portfolio/position.py:20`, `portfolio/core.py:40`, `portfolio/factory.py:141`, and
`persistence.py:352,463,568`, while `README:46-51` states the American approximation
overstates SPX puts (+2.3–4.8%) and **must not be used**. Forgetting the argument
selects a forbidden model. M1.1 fixed serialization round-trips but left the
construction path; the review's own C2 note asked to make the constructor default
explicit-only. `test_factory.py` currently rides the American default silently.

**Why it needs a strategy.** ~70–90 call sites across 18–20 files (production +
fixtures). A single giant edit is unreviewable and error-prone. Two design points make
it tractable and correct:

- **Two layers, two treatments.** Low-level *pricing primitives* (`OptionValuation`,
  `OptionPosition`) make `exercise_style` **required — no default**; that is where the
  "impossible to silently get American" guarantee lives. The *config/file boundary*
  (`OptionPortfolio`, `factory.py`, `persistence.py`) must **resolve the default from
  the IPS** `default_exercise_style` when a per-position value is absent, and error if
  neither is present — never fall back to a hardcoded `AMERICAN`. (A portfolio YAML may
  legitimately omit per-leg style and expect the program default, which for SPX is
  European.)
- **Let mypy drive the rollout.** Once a parameter is required, `mypy --strict` names
  every missing call site precisely — turning "find 70–90 sites" into a mechanical,
  tool-guided sweep rather than a manual grep. Fix exactly what mypy flags, per layer.

**Sequenced rollout — one commit per layer, gate green after each (never a giant red PR):**

1. **Primitives required.** `exercise_style` required on `OptionValuation` (`valuation.py:64`)
   and `OptionPosition` (`position.py:20`). Lead with a **fixture sweep**: update the shared
   test fixtures/`conftest` to construct with explicit style so most test call sites inherit
   rather than being hand-edited; in particular re-point `test_valuation.py`'s American
   fixture (~L142) — this dovetails with M1.5's European-parity work below.
   Commit: `fix(valuation): require explicit exercise style on pricing primitives`
2. **Boundary resolves from IPS.** `OptionPortfolio` (`core.py:40`), `factory.py:141`,
   `persistence.py:352,463,568`: replace the hardcoded `AMERICAN` default/fallback with
   resolution from the IPS `default_exercise_style`; error (fail loud) when neither
   per-position nor IPS supplies one. Void the "preserve legacy behaviour" comment — no
   back-compat is required. Commit: `fix(portfolio): resolve exercise style from IPS, no American fallback`
3. **Structural guard.** A test that constructing a primitive without a style is a
   parameter/type error, and a repo-wide check that no `= ExerciseStyle.AMERICAN` default
   survives in any signature. `test_factory.py` and other fixtures now assert the style they
   actually intend. Commit: `test(valuation): guard against forbidden American defaults`

**Acceptance:** no `= ExerciseStyle.AMERICAN` default survives anywhere; constructing a
pricing primitive without a style fails (mypy + runtime); the config/file boundary sources
its default from the IPS and errors when none is available; the full gate is green after
every commit, not just at the end.

> **Ordering:** M1.5a lands **before** the M1.5 test backfill (B–E) so those tests are
> written against final constructor signatures, and **before** the tag. FIX 1's 21-test
> cleanup can land in parallel; M1.5a's fixture sweep and M1.5's European-parity suite
> touch the same fixtures, so do M1.5a first.
>
> **Checkpoint:** at the end of Phase 1 the monitor notebook is unchanged but now
> shows correct numbers. Tag a **"correctness release"** here before touching UI.

### M1.6 — Skew-aware crash shock (deliberately *after* the correctness tag)

**Status: DONE (2026-07-21).** Landed on `feat/skew-aware-crash-shock` in two
commits: `a639199` (mechanism, default off, byte-for-byte no-op proof) and
`b29d750` (adopt `0.10`, wire the four book-convexity surfaces, recompute the §4
goldens + methodology). Sequenced post-tag on purpose: nothing failed beforehand
(the canonical book asserts invariants only; the band test anchors on the §4
fixture), so doing it against a tagged baseline gave a clean before/after on a
stable reference point.

**Resolution (auditable close-out).**

- **Calibration — signed off, from history alone.** `skew_steepening = 0.10`:
  extra vol at the deepest OTM tail over ATM, weight **linear in log-moneyness**
  `ln(S/K)` (0 at ATM → 1 at the deepest held put). Anchored on 2008/2020
  index-put skew, where the ≈10-delta wing steepened **15+ vol points** over ATM at
  the peak; 0.10 is a conservative central estimate (range 0.05–0.20), derived
  before observing where the book lands (condition 1). See
  `docs/repricing-methodology.md` §2/§5.
- **Recomputed §4 goldens (skew-aware):** convexity **+18.0% → +22.5%**, payoff
  **13.1× → 16.1×**, V_crash **$3,895,901 → $4,788,166**. V_today ($297,715) and
  the intrinsic floor ($759,000) are unchanged — skew is a crash-state effect only.
  The flat baseline is still pinned as the `skew=0.0` no-op proof.
- **Canonical book re-measured — NO re-size.** `spx_protective_put.yaml` reads
  **+16.55%** at −25% under the adopted shock (`crash_vol_shock` +0.15,
  `skew_steepening` +0.10), **+1.55 pp above the +15% floor** — vs **+14.27%**
  under the old flat bump (0.73 pp under). The honestly-calibrated shock lifts it
  into band with margin, so the book is conformant and **no sizing change is made**
  (honors the 2026-07-19 sign-off, "refine the shock, do not re-size").
- **Deferred → now tracked as M1.7 below:** sizing / strike-ladder / candidate stay on
  the flat bump — they price *standalone* candidate strikes, where each candidate
  would be its own tail and receive the full steepening (overstating shallow
  payoffs → undersizing the hedge); wiring them needs a per-strike skew anchor.
  Also deferred: the shock's **term structure** (M1.6 ships one cross-sectional
  log-moneyness slope; tenor-dependence not modelled — methodology §8).

**Motivation.** The shipped flat bump (`+0.15` on every leg) is documented-
conservative on the low strikes (methodology §8): crash skew steepening is an
empirical fact — deep-OTM puts reliably gain more IV than ATM in a sell-off.
Measured on `spx_protective_put.yaml`: **+14.27%** flat vs **+15.4%** under a
modest steepening (deep-OTM tail `+0.05` over ATM); `~+0.03` at the tail already
clears the floor (14.97%). *(These were exploratory sensitivities; the calibration
signed off from 2008/2020 history was `+0.10`, under which the book reads **+16.55%**
— see the Resolution block above.)*

**Work.** Add an optional `convexity.skew_steepening` to the IPS, consumed by
`analysis/crash_repricing`, lifting deep-OTM IV more than ATM. Zero steepening is
the default and must reproduce today's numbers **exactly**.

**Three conditions on how it is done:**

1. **Calibrate independently, never to the band.** The steepening parameter must be
   derived from historical crash episodes (2008 / 2020 index skew) with sources
   cited — *then* observe where the canonical book lands. If an honest calibration
   leaves it under the floor, the example gets re-sized after all. Deriving the
   parameter from the desired outcome would convert a correctness fix into
   motivated reasoning — the exact failure mode Phase 1 exists to undo.
2. **Treat it as a methodology change, not a parameter.** It moves *every* crash
   number — gauge, payoff ratio, sizing, strike ladder, roll trigger — and
   invalidates the §4 golden anchors (`+18.0%`, `13.1×`, `$3,895,901`, `$759,000`).
   Recompute the goldens, rewrite methodology §2 / §4 / §8, and update the
   regression fixtures in the same change.
3. **Keep the flat bump shipping until then**, as the documented default.

**Acceptance:** `skew_steepening = 0` reproduces the current §4 goldens exactly
(no-op proof); the calibration is documented with sources; §4 goldens and the
appendix are recomputed together; `spx_protective_put.yaml` is re-measured under
the honest calibration and the re-size decision recorded either way.

---

### M1.7 — Unify the crash-shock skew across book and candidate surfaces

**Status: DONE (closed 2026-07-25).** Per-leg re-anchor, candidate wiring,
methodology re-golden, and the regression guards all landed; the full gate is green
and every acceptance number was re-confirmed from the engine at close-out (table
below). Promoted from M1.6's deferred sub-bullet because it is a cross-surface
inconsistency with a directional bias, not a cosmetic gap — and closed before M2.3
surfaces the sizing workbench in Dash, so book and workbench cannot disagree in
front of a user.

**Resolution.** Landed in two commits, full gate green after each:

- **`b1f4e3d` — per-leg wing re-anchor.** `_leg_crash_vol` anchors each leg's
  steepening to its own ~10-delta wing (`skew_reference_delta`, IPS-configurable,
  default 0.10), capped there; `_tail_log_moneyness` / `_skew_weight` deleted. The
  function takes no book context, so a leg's crash vol is composition-independent.
  §4 re-goldened in place at **+24.64%** (17.5×, `V_crash` ≈ $5.23M); canonical
  **+16.11%**, neither re-sized; `skew = 0.0` still a byte-for-byte no-op.
- **`fix(sizing)` — candidate wiring (this commit).** `evaluate_candidate` takes
  the skew as **required** params; `size_hedge` and `build_strike_ladder` source
  them from `ips_config.convexity`. The flat-bump split is gone: a candidate at a
  held strike reproduces that leg's per-contract crash value exactly, and the
  sizing payoff agrees with the gauge at equal depth.

**Still-deferred follow-ups (tracked; not blocking M1.7 acceptance):**

- ~~**Book surfaces source `skew_reference_delta` from the IPS.**~~ ✅ **RESOLVED
  (M1.8, closed 2026-07-26).** `crash_payoff` / `health` / `roll_status` no longer
  inherit `crash_hedge_value`'s `0.10`; the anchor reaches every book surface and
  the scenario grid. Two points worth recording about *how* it was closed:

  - **Closed with a `CrashShock` pricing object, not by passing `IpsConvexity`
    down.** Handing the pricers the policy object would have been fewer lines and
    would have fixed the anchor just as well — but it would have put
    `target_min_pct` / `target_max_pct` on the pricing path, collapsing the
    separation M1.5 established deliberately. With the band travelling alongside
    the pricing inputs, a caller that omitted policy would silently change *what
    gets priced*, not merely lose the band comparison. `CrashShock` carries the
    four pricing fields and nothing else; `compute_crash_convexity` and
    `build_strike_ladder` still take `ips_convexity` separately, for
    `meets_target` only. Two tests pin the object's field list.
  - **The pylint arity block is gone because one object replaced four scalars.**
    The deferral's stated blocker was `max-args = 8`: `_build_scenario_rows`,
    `_leg_crash_vol`, and `evaluate_candidate` each sat at exactly 8, so a fourth
    scalar was an `R0913` failure. Bundling *reduced* arity everywhere it touched
    — `_leg_crash_vol` 8→6, `_build_scenario_rows` 8→7, `evaluate_candidate` 8→5,
    `crash_hedge_value` 6→3 — so the fix arrives with headroom rather than a
    `# pylint: disable`. pylint stays at 10.00/10.

- **Crash-shock term structure** — one cross-sectional slope, no tenor dependence
  (methodology §8).
- ~~**Notebook crash-panel wiring**~~ ✅ **RESOLVED (M1.9)** — both notebooks now
  pass a `CrashShock` to `NetHedgeSummary` and `compute_crash_convexity`; the
  latter had been raising `TypeError` on a required kwarg since M1.4.

**Resolved since (auditable close-out):**

- **Methodology doc re-golden — RESOLVED** (`feat(crash): re-golden §4 …`).
  `docs/repricing-methodology.md` §2/§4/§5/§7/§8 rewritten under the capped
  per-leg ~10-delta anchor — the numbers `b1f4e3d` moved (the split the policy
  forbids, now closed in one commit): §4 = **+24.64% / 17.5× / $5.23M** (V_today
  and the intrinsic floor unchanged); canonical **asserted in-band at ~+16.1%**
  and not re-sized; §8 marks composition-dependence and the book/candidate split
  resolved, leaving the shock's term structure as the remaining simplification.
- **Structural regression guards — RESOLVED**
  (`test(crash): guard skew consistency, composition invariance, and ceiling
  proximity`). Five load-bearing M1.7 properties are now pinned so a future
  re-calibration can't silently break them: (1) §4 anchored on the **convexity
  value** (+24.64%, riding 0.36pp under the +25% ceiling by design), not the
  `meets_target` boolean; (2) health gauge == roll trigger == summary ladder ==
  crash_payoff scenario table at equal depth under the skew-aware shock; (3)
  **composition invariance** as a first-class byte-for-byte test (no leg's crash
  vol depends on what else the book holds); (4) **no-op** — `skew_steepening=0.0`
  reproduces the flat baseline byte-for-byte at the primitive; (5) **fail-loud** —
  `skew_steepening` is now required (no default) on the health gauge, mirroring
  `crash_vol_shock` (M1.4/M1.5), with source guards confirming the roll trigger and
  scenario table source it from the IPS.

**M1.7 CLOSE-OUT (DONE, 2026-07-25).** Full gate green (pytest 1332 passed /
2 xfailed, mypy clean, ruff check + format clean, pylint 10.00/10) and every
acceptance number re-confirmed from the engine at close-out:

| Property | Confirmed |
| --- | --- |
| §4 book convexity | **+24.64%** (V_crash ≈ $5.23M, 17.5×) — rides 0.36pp under the +25% ceiling |
| Canonical convexity | **+16.10%** (valuation 2026-07-25; ≈+16.1%) — in-band, +1.10pp over the +15% floor, not re-sized |
| Book == candidate at equal depth | per-contract crash payoff identical (K5280: $109,754.31 on both paths) |
| Composition invariance | a held leg's crash vol is byte-identical after adding a deeper put |
| `skew = 0` no-op | V_crash byte-identical to the parameter-omitted call |
| No silent skew default | no production crash path reprices flat by omission (below) |

**Decisions (recorded against the measured numbers, not preference).**

- **D3 — faithful ~10-delta wing anchor, not a %OTM proxy.** The steepening anchors
  to each leg's own ~10-delta wing, solved per leg (`_solve_wing_strike`). A
  fixed-%OTM proxy only preserved §4's band because §4's tail happens to sit at
  40% OTM — a property of *that book*, not of the calibration; on a book whose tail
  sits elsewhere the proxy misplaces the anchor. The delta wing is a market-faithful
  reference that holds for any book.
- **D5 — cap the steepening at the wing, never extrapolate.** No skew calibration
  exists beyond the ~10-delta wing, so extrapolating the slope past it would
  fabricate deep-tail IV; holding it flat under-states it (the conservative direction
  for a tail program). Measured: capping returns §4 from the **uncapped +27.71%**
  (out of band, over the +25% ceiling) to the **in-band +24.64%** — the cap is what
  keeps a faithful anchor in-band.
- **D4 — no canonical re-size.** The canonical reads **+16.10%** under the honest
  per-leg model — **cap-invariant** (its legs are shallower than their own wings, so
  the cap never binds: capped == uncapped == +16.10%), **+1.10pp over the +15%
  floor**. That in-band reading is a property of the honest model, not of M1.6's
  book-relative artifact (which inflated the shallow leg's steepening by tracking the
  *deepest held* put). In-band on the honest number ⇒ no re-size.
- **§4 re-goldened in place at +24.64%**, riding **0.36pp under the +25% ceiling by
  design** (a deliberately deep 20/30/40 ladder), pinned by **value, not the
  `meets_target` boolean** (the Prompt E guard), so any re-calibration surfaces as a
  visible number change rather than a silent flip.

**Resolved.** The **book/candidate split** is closed (a candidate at a held strike
reproduces that leg's per-contract crash value exactly) and **composition-dependence**
is closed (per-leg anchor). The **≈23% sizing over-hedge bias** is gone: M1.6's
flat-bump candidate under-stated the tail payoff, so sizing bought ≈23% more carry
than the skew gauge implied; the candidate now carries the same per-leg skew, so the
bias is eliminated.

**No silent skew default.** The shipped `config/ips.yaml` sets `skew_steepening:
0.10` explicitly (it does not inherit the `0.0` policy default); the health gauge and
`evaluate_candidate` **require** the skew (no default); and every book surface (roll
trigger, health metrics, scenario table, crash-payoff display) **sources** it from
the IPS — guarded by `test_skew_steepening_is_required_on_the_gauge` and the roll /
table source guards. The `= 0.0` defaults that remain are deliberate no-op ergonomics
no crash path relies on: the today-value primitive (`hedge_value`, skew-free by
definition), the payoff entry points (all production callers pass skew), and the
`NetHedgeSummary` widget + the `IpsConvexity` dataclass — the same posture
`crash_vol_shock` carries.

**Remaining deferral.** The shock's **term structure** — one cross-sectional slope;
each leg's wing is already solved at its own tenor, so what remains is how the slope
itself varies *across* tenors (methodology §8).

**The problem, one root.** M1.6 anchors the skew weight to the book's deepest held
put (`_tail_log_moneyness` = `ln(S / min(otm_put_strikes))`). Two consequences:

- **Book vs workbench split.** The four book surfaces price crash convexity with
  skew (§4 book payoff 13.1× → 16.1×); sizing / strike-ladder / candidate stay on
  the flat bump because a standalone candidate has no book tail. Net effect: sizing
  on the lower flat payoffs **over-hedges relative to the skew gauge** — ≈ 23% more
  carry in the §4 case. Conservative (over-protect, not under-protect), but a real
  inconsistency and a real carry cost.
- **Book-composition dependence.** Because the anchor is the deepest *held* put, the
  steepening applied to a fixed leg changes when the book's deepest strike changes —
  market skew at a strike is not a function of what else is held.

**Key design decision (the deeper exploration — resolve before implementing).**
Two shapes:

- **(A) Re-anchor to absolute moneyness** — steepening as a slope in vol-points per
  unit `ln(S/K)` (or anchored to a fixed reference wing, e.g. the N-delta strike),
  calibrated from history. Book legs and candidates then use one identical function
  of their own moneyness: the candidate deferral dissolves and the composition
  dependence goes with it. Requires re-deriving the calibration in slope terms and
  recomputing the §4 goldens again.
- **(B) Per-strike skew anchor on the candidate path only** — keep the book-relative
  model, give the candidate evaluator a fixed reference tail so it stops treating
  each candidate as its own deepest strike. Smaller change; leaves the
  composition-dependence in the book surfaces.
Recommendation: (A) — it fixes both consequences at one root and keeps a single
skew function everywhere. Confirm the calibration can be expressed as an absolute
slope consistent with the signed-off `0.10`-at-the-tail figure before committing.

**Acceptance (all met):** one skew function drives book and candidate surfaces; a
fixed leg's crash vol is independent of book composition; the sizing payoff ratio
and the gauge convexity agree at equal depth on the §4 book; goldens recomputed
(methodology doc re-golden tracked as a follow-up above); `skew = 0` still a
byte-for-byte no-op.

### M1.8 — `CrashShock`: thread the crash pricing basis as one value object

**Status: DONE (closed 2026-07-26).** Closes the first M1.7 deferred follow-up.

**The defect.** `IpsConvexity` carries four crash *pricing* knobs. M1.7 wired all
four into the candidate surfaces but left the book surfaces
(`health.calculate_crash_convexity_pct`, `crash_payoff.*`, `roll_status`) forwarding
only three — `skew_reference_delta` fell to `crash_hedge_value`'s own `0.10`. At the
shipped anchor the two agree, so nothing was visibly wrong; **move the IPS anchor and
the sizing workbench followed while the gauges did not**, silently re-opening the
book-vs-candidate divergence M1.7 closed. Threading it as a fourth scalar was
arity-blocked: `_build_scenario_rows`, `_leg_crash_vol`, and `evaluate_candidate`
each sat at exactly `max-args = 8`.

**Resolution.** A frozen `CrashShock` (`crash_scenario_pct`, `crash_vol_shock`,
`skew_steepening`, `skew_reference_delta`) in `analysis/crash_repricing.py`, with
`from_ips(IpsConvexity)`, a derived `crash_move`, and `at_pct()` for depth sweeps.
It is **required with no default** on `crash_hedge_value`, `crash_convexity_pct`,
the health gauge, and every `crash_payoff` entry point — extending M1.7's fail-loud
rule from `skew_steepening` to the whole basis. Arity cleared everywhere
(`_leg_crash_vol` 8→6, `_build_scenario_rows` 8→7, `crash_hedge_value` 6→3).

**Pricing and policy stay separate (M1.5).** `CrashShock` carries **no** band
fields; `compute_crash_convexity` keeps `ips_convexity` as its own argument for
`meets_target`, and `roll_status` reads `target_min_pct` / `target_max_pct` straight
off `IpsConvexity`. Two tests pin this structurally.

**Decisions.**

- **D1 — the depth is bundled, with `at_pct()` for sweeps.** The alternative (keep
  `crash_move` a separate parameter) leaves the scenario un-single-sourced and lets a
  call site price a depth unrelated to the IPS.
- **D2 — every field required.** `from_ips` is the intended construction path, so no
  surface can half-state the crash and inherit the rest — the precise mechanism by
  which the anchor went missing.
- **D3 — `evaluate_candidate` keeps its scalar signature.** Scoped to the book
  surfaces; it builds a `CrashShock` inline at its `crash_hedge_value` call, leaving
  `sizing.py`, `strike_ladder.py`, and their tests untouched. Converting it (8→5
  args) is a clean follow-up.
- **D4 — `crash_intrinsic_floor` unchanged.** Takes no vol or skew input, so it is
  structurally outside the defect.
- **D5 — `hedge_value` drops through to `_reprice_leg`.** Today's value has no crash
  state; routing it through `crash_hedge_value` would mean fabricating a zero shock
  whose anchor is never read — reintroducing the very default being removed.
  Numerically identical to the old `crash_move=0, vol_shock=0` call.

**Value-neutral by construction — goldens unchanged, not re-goldened.** Verified by
diffing engine output before and after: **byte-identical**.

| Property | Confirmed |
| --- | --- |
| §4 book convexity | **+24.639527%** (V_today $298,098.88 → V_crash **$5,226,004.24**, **17.5311×**) |
| Canonical (`spx_protective_put.yaml`) | **+16.098902%** — in-band, not re-sized (as-of **2026-07-26**; absolute maturity, so the load is pinned) |
| `spx_tail_20m.yaml` | **+24.641991%** (as-of-invariant: relative `maturity_days`) |
| K5280 per-contract | **$109,754.308967** on both book and candidate paths |
| Per-leg crash vols | K5280 `0.4446183769`; K4620/K3960 capped at `0.4500000000` |
| `skew = 0` no-op | V_crash `3897393.1217789161`, unchanged |

**Regression guards (8 new).** The load-bearing ones move the IPS anchor to `0.05`
and require the health gauge, scenario table, and roll trigger to follow, plus
book==candidate parity at that non-default anchor. **Verified to fail against a
reproduced defect** (a plugin pinning the book path's anchor back to `0.10`): 4 of 5
fail, three with byte-identical before/after values — the silent-no-op signature. The
fifth (cross-surface consistency) passes under the defect *by design*, because the
old code dropped the anchor uniformly; its docstring says so, and it guards against a
future **partial** re-threading instead. Also pinned: `from_ips` field round-trip,
`at_pct` preserving the vol basis, `CrashShock` having no field defaults, and its
carrying no band fields.

**Gate at close-out (2026-07-26):** pytest **1340 passed / 2 xfailed**, mypy
clean, ruff check + format clean, pylint **10.00/10** (the arity gate that
blocked the scalar approach).

### M1.9 — One pricing-input object everywhere (candidate path + widget)

**Status: DONE (closed 2026-07-26).** Completes M1.8: after this there is a
single crash pricing-input object and a single construction path
(`CrashShock.from_ips`) across every surface.

M1.8 converted the book surfaces (and, as a forced consequence, all of
`crash_payoff`). Three callers were left threading the scalars:

- **`evaluate_candidate`** took the four scalars and bundled them internally
  (M1.8 decision D3, deliberately deferred). It now takes `shock: CrashShock`
  — **8 args → 5** — and `sizing.size_hedge` / `strike_ladder.build_strike_ladder`
  build it with `CrashShock.from_ips(ips_config.convexity)`, the same call the
  book surfaces make. Both keep a local read of `shock.crash_scenario_pct` for
  `required_crash_offset` (drawdown-tolerance policy maths, not pricing) so the
  depth has one source within each function.
- **`NetHedgeSummary`** carried `crash_vol_shock=0.0`, `skew_steepening=0.0`,
  `skew_reference_delta=0.10` as ctor defaults. Both notebooks passed only the
  first, so **the summary's crash-convexity ladder priced on a flat bump while
  the health gauge priced it skew-aware** — a live divergence, and the last
  `crash_vol_shock` default on a pricing path. Replaced by a required
  `shock: CrashShock`; the rungs use `shock.at_pct(...)`.
- **Notebook crash cells** (both notebooks) now pass the shock. This also
  fixes the pre-existing `TypeError` in the `compute_crash_convexity` cells,
  which had been calling it without its required kwarg since M1.4 — nbqa mypy
  on the notebooks drops **17 → 15** errors (the remaining 15 are unrelated
  and pre-existing).

**Audit (the acceptance criterion).** After the change:

- no caller threads the crash scalars individually — the only remaining
  `crash_vol_shock=` / `skew_steepening=` / `skew_reference_delta=` sites are
  `CrashShock.from_ips` itself, `ips_config`'s YAML parse into `IpsConvexity`,
  and `default_crash_shock()`;
- **no parameter default for any crash pricing scalar survives** outside
  `IpsConvexity`'s own field defaults, where they belong;
- **no `CrashShock` parameter is optional or defaulted** anywhere — an optional
  one would reopen the M1.5 spot-only bug.

Pinned by three new structural guards: no pricing entry point accepts a crash
scalar in its signature; every one requires `shock` with no default; and both
candidate surfaces construct via `CrashShock.from_ips`.

**Pricing and policy still separate.** `compute_crash_convexity` keeps
`ips_convexity` as its own optional argument for `meets_target` only, and
`build_strike_ladder` reads the band off `IpsConvexity` on its own path.

**Value-neutral.** Goldens byte-identical to the pre-M1.8 baseline: §4
**+24.639527%** / V_crash **$5,226,004.24** / **17.5311×**; canonical
**+16.098902%**; K5280 per-contract **$109,754.308967** on both paths;
`skew = 0` V_crash **3897393.1217789161**.

**Gate at close-out (2026-07-26):** pytest **1343 passed / 2 xfailed**, mypy
clean, ruff check + format clean, pylint **10.00/10**, nbqa ruff clean on
both notebooks.

**Still deferred:** see the M1.10 ledger below.

### M1.10 — Close-out: a structural guard against the whole defect class

**Status: DONE (closed 2026-07-26).** Closes the `skew_reference_delta` work
(M1.8 + M1.9) with a guard aimed at the *class*, not the instance.

**Why a repo-wide guard.** Every regression in this area has been the same
shape — a crash-pricing input carrying a default, so a surface that omitted it
inherited a basis nobody chose:

| Milestone | Input | Silent behaviour when omitted |
| --- | --- | --- |
| M1.4/M1.5 | `crash_vol_shock` | repriced **spot-only** |
| M1.7 | `skew_steepening` | repriced a **flat bump** |
| M1.8 | `skew_reference_delta` | ignored the **IPS wing anchor** |
| M1.9 | all three (`NetHedgeSummary`) | ladder priced **flat vs a skewed gauge** |

Each was previously fixed one input at a time, by a guard naming that input.
`tests/test_crash_pricing_contract.py` replaces that pattern with an **AST scan
of the whole package**: no function anywhere may declare a default for any
crash-pricing parameter, under any of its historical spellings, nor for the
`CrashShock` that now carries them. A *new* entry point reintroducing the
defect fails without anyone having to remember this history.

The scan is verified two ways: it was run against a deliberately reintroduced
default (`crash_hedge_value(skew_reference_delta=0.10)`) and reported it with
an exact file:line; and four meta-guards prove the walk is not passing
vacuously — it must reach >200 functions, must visit each of the six
crash-pricing modules by name, and the default-detector itself is unit-tested
in both directions. `IpsConvexity`'s field defaults are out of scope by
construction: they are dataclass fields, not parameters, and are exactly where
policy should declare its fallbacks.

**Also pinned: the wing cap is not a propagation failure.** Tuning the anchor
moves only strikes *inside* the wing; past it the M1.7 cap holds the steepening
flat at `skew_steepening` (D5 — never extrapolate past the calibration). On the
sizing fixture the 0.10 wing sits at ~21.6% OTM and the 0.05 wing at ~28.3%, so
a 40%-OTM candidate is *correctly* anchor-independent. Both sides of that
boundary are now tested, so a future reader checking propagation on a deep
strike does not read the cap as a regression.

**Verification at close-out.**

| Check | Result |
| --- | --- |
| Anchor propagates — book | gauge, scenario table, roll trigger all move (3 tests) |
| Anchor propagates — candidate | `size_hedge` payoff moves at 20% OTM |
| Book == candidate | equal at equal depth, and at a non-default anchor |
| §4 golden | **+24.639527%** (V_crash **$5,226,004.24**, **17.5311×**) |
| Canonical golden | **+16.098902%** — in-band, not re-sized |
| K5280 per-contract | **$109,754.308967** on both paths |
| `skew = 0` no-op | V_crash **3897393.1217789161**, byte-identical |
| Gate (at close-out, 2026-07-26) | pytest **1357 / 2 xfailed**, mypy clean, ruff clean, **pylint 10.00/10**, nbqa ruff clean |

Goldens are byte-identical to the pre-M1.8 baseline throughout: M1.8/M1.9/M1.10
changed how parameters travel, never what is computed.

**Ledger — still deferred after this work.**

| Item | Status |
| --- | --- |
| **Crash-shock term structure** — one cross-sectional slope, no tenor dependence | Open (methodology §8) |
| **`default_crash_shock()`** — prices `0.15 / 0.0 / 0.10` when `ips_convexity is None` | Open by decision: a named, documented fallback so the pre-IPS crash panel renders at all. Not a parameter default, so out of the new guard's scope. Removing it would change public behaviour of `crash_scenario_table` and `CrashPayoffDisplay`. |
| **`_shock_to_multiplier`** (`crash_payoff.py`) — defined and tested, called nowhere | ✅ Closed: function and its test deleted in `4ed97bf` |
| **Tier-4 metrics** #12 Liquidity Risk, #13 Delta Drift, #14 Vega Term Exposure | Open. **Corrected by the 2026-08-06 Part X re-audit:** only #12 is data-blocked. #13 (`Δ(−5%) − Δ(0)`) and #14 (vega by maturity bucket) are surfacing gaps the engine already supports — see `part-x-coverage.md`. |

**Ledger — judgment calls made beyond the brief.** Recorded because each
changed the shape of the fix, not just its wording:

| # | Call | Rationale |
| --- | --- | --- |
| J-1 | `hedge_value` reimplemented on `_reprice_leg` rather than routing through `crash_hedge_value` | Routing it would need a fabricated zero `CrashShock` whose anchor is never read — reintroducing the default being deleted. Byte-identical result. |
| J-2 | `crash_intrinsic_floor` left on `crash_move` | Takes no vol or skew input; structurally outside the defect. |
| J-3 | `NetHedgeSummary` first gained a `skew_reference_delta` kwarg (M1.8) before becoming shock-only (M1.9) | Adapting at the call site would have hardcoded `0.10` in a widget — the same defect class being fixed. |
| J-4 | `crash_payoff_display`'s hardcoded `0.15` folded into `default_crash_shock()` | Was a silent duplicate of `_DEFAULT_CRASH_VOL_SHOCK`; consolidating it is what created the tracked `default_crash_shock()` item above. |
| J-5 | `crash_payoff` converted in M1.8 rather than M1.9 | Forced, not discretionary: it calls both converted primitives. |
| J-6 | Two M1.8 guards rewritten after they passed against a reproduced defect | A guard that cannot fail proves nothing; one compared against the pricing primitive rather than a book surface. |
| J-7 | Canonical golden recorded as **+16.0989** | The brief cited +16.12; the engine reads +16.0989. Originally asserted at `abs=0.1` because the reading was valuation-date sensitive; the load is now pinned to **2026-07-26** (the date that figure was measured) and asserted at `abs=0.001`. Confirmed from the engine rather than pinned to a new literal. |
| J-8 | `sizing` / `strike_ladder` read depth back off `shock.crash_scenario_pct` for `required_crash_offset` | That is drawdown policy maths, not pricing, but it should not re-read the config separately. |
| J-9 | Fixed the adjacent broken `compute_crash_convexity` notebook cells | Same one-line pattern in the same cells being edited; leaving a known `TypeError` two cells away would be strange. Scope extension beyond the brief. |
| J-10 | Added a companion test asserting the cap **is** anchor-independent past the wing | The first draft of the candidate propagation test used a 30%-OTM strike and failed — correctly, because of the cap. Pinning both sides stops that being misread later. |

### M1.11 — Clock-shift determinism probe (last thing before Phase 2)

**Status: DONE (closed 2026-07-27).** Phase 2 rebuilds the UI on top of this
suite, so the suite has to be trustworthy in a way that a green run today does
not by itself demonstrate: a test asserting a wall-clock-dependent value passes
until the calendar reaches it, then fails as mystery breakage on an unrelated
branch months later.

**What it caught.** `tests/clockshift_plugin.py` is a pytest plugin that moves
`datetime.now()` / `today()` by *N* days for the whole suite. It found four such
tests in `TestBuildPutValuation` (#205, fixed in `962010a`) — a hardcoded
`2026-10-01` expiry priced against a `now()` valuation date, which would have
started failing in **October 2026**.

**Three load-bearing invariants**, each discovered by a wrong answer and each
carrying a `DO NOT REMOVE` comment, because all three read like tidy-uppable
noise:

| # | Invariant | What breaks without it |
| --- | --- | --- |
| 1 | `numpy`/`pandas`/`QuantLib` are imported *before* the type swap | pandas caches a pointer to `datetime.datetime` in its C layer at import; importing after the swap segfaults in `nattype.__pyx_tp_traverse` — no traceback, no output |
| 2 | The patch is unconditional, **including at shift 0** | `ShiftedDatetime` subclasses the real `datetime`, so once `datetime.date` is patched `isinstance(a_datetime, datetime.date)` is `False`. A green +0 **control** is the only thing separating that type-identity breakage from real date drift |
| 3 | Loaded via `-p`, never a conftest fixture | `-p` imports before conftest and before any test or `deltadewa` module, so import-time constants bind the shifted clock. Patching after collection shifts the library while leaving the test module feeding it unshifted — that once reported **23** broken tests when only **4** were real |

**Where it runs, and why not in the gate.** The probe substitutes a type that C
extensions hold pointers to, so a dependency bump can crash it in a way that has
nothing to do with the code under review. Blast radius, not runtime, is why it
stays out — the suite is ~8s, so the full matrix is ~30s.

- **Nightly, authoritative** — `.github/workflows/clockshift.yml`, the full
  `+0/+90/+1000/+3000` matrix against `main`, `fail-fast: false` so a `+1000`
  failure cannot cancel the `+0` control.
- **Per-PR, advisory** — `clockshift-advisory` in `ci.yml`, `+0/+1000`, with
  `continue-on-error: true`. The author gets the signal in minutes; a probe
  crash can never block the merge. **It must not become a required check.**
- **Locally** — `make test-clockshift` (override `CLOCK_SHIFT_MATRIX` to scope).

**Honest limit.** A *scheduled* workflow runs against `main` and therefore
cannot be a required check. What the nightly delivers is a red run on `main` and
a failure notification within a day of the commit that introduced the drift —
early enough to be attributed, not early enough to be prevented. The advisory
per-PR job is what closes that window, at the cost of not being able to enforce.

**The probe has its own meta-guard.** Same principle as ledger row **J-6** — a
guard that cannot fail proves nothing. `tests/test_clockshift_canary.py` is two
tests, live at *every* shift including 0, with deliberately no `skipif`, no
inverted exit code and no hardcoded golden (a golden inside a determinism canary
would itself drift). They assert the shift reaches **library** code, and that a
DTE-sensitive price moves under it — self-calibrating against one day of theta
rather than a fixed number. They run in the default gate too, where they pin the
unshifted branch and catch a `CLOCK_SHIFT_DAYS` left set in someone's shell.

**Verification at close-out.**

| Check | Result |
| --- | --- |
| Bites proof — #205 bomb reintroduced | default gate **green** (the bomb is invisible today; that is the point) |
| Bites proof — same bomb under the matrix | **red at +90** on exactly the four `TestBuildPutValuation` tests, **+0 control green** |
| Bites proof — bomb reverted | all four shifts green, `make` exit 0 |
| Canary negative control (probe not loaded, `CLOCK_SHIFT_DAYS=90`) | both tests fail — a probe that stops shifting cannot pass silently |
| Gate (at close-out, 2026-07-27) | pytest **1361 / 2 xfailed**, mypy clean, ruff clean, **pylint 10.00/10**, nbqa ruff clean |

**Verified on the pinned interpreter (2026-07-27).** Everything above was first
measured on local Python **3.14** while both workflows pin **3.11** — and the
probe's mechanism (a `datetime.datetime` subclass swapped in around the
`numpy`/`pandas`/`QuantLib` imports) is exactly the kind of thing that is
version- and wheel-sensitive, so that green was not evidence about the
interpreter CI actually runs. Both legs were therefore re-run **in CI**, on
`ubuntu-latest` + `actions/setup-python@v6` → **CPython 3.11.15** with manylinux
wheels, dispatched at `clockshift.yml`:

| Leg | Ref | Run | Result |
| --- | --- | --- | --- |
| Full matrix, clean env (2026-07-27) | `main` @ `6fb7f61` | [30299949442](https://github.com/qwertytam/deltadewa/actions/runs/30299949442) | **all four shifts green** — `1361 passed, 2 xfailed` at +0, +90, +1000, +3000 |
| Bites proof, #205 bomb restored (2026-07-27) | throwaway branch @ `a147534` | [30300061144](https://github.com/qwertytam/deltadewa/actions/runs/30300061144) | **+0 green** (`1361 passed`); **+90/+1000/+3000 red, exactly 4 failures**, all in `TestBuildPutValuation` |

The four, with the assertion each produced once the option had aged past its
hardcoded `2026-10-01` expiry: `test_delta_is_negative` (`assert 0.0 < 0.0`),
`test_price_is_positive` (`assert 0 > 0.0`), `test_vol_override_changes_price`
(`assert 0 > 0`), and `test_exercise_style_from_portfolio` (`RuntimeError:
earliest > latest exercise date`). The fifth restored call site,
`test_returns_option_valuation`, correctly does **not** fail — it asserts
`isinstance`, which is time-independent. That is the shape of the original #205
finding, reproduced on 3.11.

No segfault, and no silent no-op: a failure at +90 requires
`portfolio.valuation_date` to have genuinely moved 90 days *inside library
code*, and the canary would have failed the matrix leg if the shift had stopped
landing. CI-on-3.11 is also stronger evidence than a locally built 3.11 — the
C-extension hazard lives in the wheels, and a macOS/arm64 build would have
swapped the version variable while introducing a platform one. The bomb branch
was deleted from `origin` as soon as the run was read; `main` is the restored
state, and the matrix leg above *is* that restore.

*Runtime on CI:* ~16.4s per shift, so the matrix is ~65s of test time. The
~8s/~30s figures quoted above are a local machine. Neither is the reason the
probe stays out of the gate.

**Two loose ends, closed 2026-07-28.**

**1. The applied shift now reaches the log — and is enforced, not just
printed.** Every caller runs `pytest -q` (the nightly matrix directly, the
advisory job and local runs via `Makefile:17`), and `-q` suppresses
`pytest_report_header`. So the plugin's `clockshift: +N days` line never
reached a CI log and the step name was the only record of the shift — a label
the run never had to live up to. Worse, that header echoed `CLOCK_SHIFT_DAYS`
back: even visible, it was the shift *requested*, never the shift *applied*.

`pytest_report_header` is therefore replaced by a `trylast` `pytest_configure`
in `tests/clockshift_plugin.py` that (a) **measures** the offset in force —
`datetime.datetime.now()` looked up through the module attribute, the same
lookup library code makes, minus the real clock — and writes it through the
terminal reporter, which is not verbosity-gated; and (b) raises `UsageError`
if the substitution is not live, or if the measured offset is not the
requested one. `trylast` is required: `-p` plugins register after the builtins
and `pytest_configure` runs last-registered-first, so at default order the
terminal reporter does not exist yet.

The fix is in the plugin, not the workflows, deliberately. Dropping `-q` would
have been two edits in two files, and any future `-q` would silently undo it —
the same shape of rot as the hardcoded test count. One plugin edit covers the
nightly, the advisory job and `make test-clockshift` at once.

Confirmed on the pinned interpreter by dispatching the matrix at
`ci/clockshift-applied-shift-in-log`
([30368957981](https://github.com/qwertytam/deltadewa/actions/runs/30368957981)),
all four legs green at `1361 passed, 2 xfailed` (2026-07-28), each logging
its own shift
under `-q`:

```text
+0d     clockshift: requested +0 days,     applied +0 days     (Python 3.11.15)
+90d    clockshift: requested +90 days,    applied +90 days    (Python 3.11.15)
+1000d  clockshift: requested +1000 days,  applied +1000 days  (Python 3.11.15)
+3000d  clockshift: requested +3000 days,  applied +3000 days  (Python 3.11.15)
```

The guard is a **fast fail, not a new claim** —
`test_probe_moves_the_library_clock` already asserted the same property one
hook later. What it adds is a clear message before collection instead of an
assertion failure, and coverage if the canary is ever removed. Both branches
were shown to fire (row **J-6** again — a guard that cannot fail proves
nothing): with the swap deleted, all four legs exit 4 **including the +0
control**, which is why the type-identity check is there and not just the
offset check; with the swap live but `now()` no longer adding `SHIFT`, +1000
exits 4 reporting `requested +1000 days, measured 0:00:00.000184`. At +0 that
second branch is vacuous by construction — a zero offset is the correct answer
there — so the +0 control's guard is the type-identity one.

**2. `.mypy_cache/3.14/` — instruction to delete it recorded as a deliberate
no-op.** It is **not** deleted, and still on disk. The instruction rested on a
false premise, mine: this section once said the directory was stale, and that
was wrong. `[tool.mypy]` sets no `python_version`, so mypy targets the running
interpreter — `3.14/` is simply what a 3.14 venv produces, and it regenerates
on the next run. Pinning `python_version = "3.11"` would be worse, not better:
`mypy --python-version 3.11 deltadewa` dies on `numpy/__init__.pyi:737: Type
statement is only supported in Python 3.12 and greater`, because the numpy
resolved *for a 3.14 venv* ships stubs needing ≥3.12. The only honest way to
type-check against 3.11 is to be on 3.11, which the gate does on every push.
**M0.2 stays closed.**

The invariant that actually matters is the ignore, and it holds:
`.gitignore:186` is `.mypy_cache/` — a **directory-level** entry, so no
version subdir can ever be committed, not merely the one that exists today.

```console
$ git check-ignore -v .mypy_cache/3.11/foo .mypy_cache/3.14/bar .mypy_cache/anything
.gitignore:186:.mypy_cache/   .mypy_cache/3.11/foo
.gitignore:186:.mypy_cache/   .mypy_cache/3.14/bar
.gitignore:186:.mypy_cache/   .mypy_cache/anything
$ git ls-files .mypy_cache | wc -l
0
```

## Phase 2 — Dash rebuild (build on the trusted engine)

**Locked decisions (from the UX/deployment discussion):**

- **Audience & purpose.** The monitor's job is *understanding / shared decisions*
  for a non-technical partner reviewing every month or two — not reassurance, not
  idiot-proofing, and **not** the you're-not-around continuity case (explicitly out
  of scope; if the operator is gone the hedge may lapse). Horizon is **months, not
  years** — bias to the fastest correct path, skip long-durability polish.
- **Monitor content.** Organized around the three questions a person asks —
  *what does it cost / what do we get / what are we doing* — **leading with the
  crash** (the partner's focus). A **two-knob scenario explorer** (spot move, vol
  move) with live repricing is the interactive heart of the "what do we get"
  section. Principle: **legible cold, every time** — re-teach as it shows, because
  the reader returns after weeks with no context loaded.
- **Design tool.** Stays a dense expert workshop (used together, ~monthly). No
  simplification budget spent here — it all goes to the monitor.
- **App shape.** **One Dash app, two pages** (`/monitor`, `/design`) sharing the
  engine and data layer.
- **Deployment.** DigitalOcean **VPS** + **Docker Compose** + **Tailscale** for all
  access (MFA via the tailnet sign-in; no public exposure, no login page to build).
  Deploy the *thin* app early (M2.3) so the surfaces are built against the real
  environment.
- **Report.** Emailed weekly heartbeat. Stale-data policy: **send anyway, stamped
  stale, staleness impossible to miss** — never silently skips, never silently
  prices on old data.
- **Backup.** Cheap version: nightly `git commit && push` of `exports/` to a private
  **offsite** repo (Codeberg — free/private/EU, and *not* DigitalOcean, so a VPS loss
  can't take the backup with it). Optional `age` encryption if desired.
- **Model & sub-agent usage.** See CLAUDE.md's "Model & sub-agent usage" section: tier
  by step (Haiku for orient/verify/sweep, Opus for M2.1 compute-API design and M2.4 the
  monitor, Sonnet for implementation), and delegate to the read-only agents —
  `fast-processor` (orient), `gate-runner` (code gate), `dash-smoke-runner` (app smoke),
  `doc-sync-checker` (doc drift).

**Sequencing note.** Two deliberate choices: deployment sits *in the middle* (M2.3),
not at the end, so the monitor and design surfaces are built against the deployed
environment rather than guessing at it; and the **monitor (M2.4) comes before the
design tool (M2.5)** because it is the harder design problem with the real
(least-expert) reader, so it gets fresh attention rather than Phase-2 fatigue.

### M2.1 — Extract the compute layer

**Status: done** — commits `550d3f1`, `9ba6a54`, `3d2a1df` on
`m2.1-extract-compute-layer` (PR: "M2.1 — extract the compute layer behind a
shock-driven primitive with a pluggable vol mapping").

Pull the repricing + scenario logic out of `dashboard/stress.py` (and wherever else
it's tangled with notebook display) into clean `analysis/` functions with tests —
organized around **what the surfaces need**, not what the notebook cells call today.
The heart is a *"reprice the hedge at spot −X%, vol +Y%"* function that takes an
**arbitrary set of shocks** (so exposing a third dial later is a UI change, not an
engine change); both the monitor's crash story and the design tool consume it.

**Fix-then-extract** the two `stress.py` xfail bugs from M1.5 first (the
`valuation_date` state-leak at `stress.py:897`, and the `get_portfolio_state_hash`
cache-key gap omitting `underlying_quantity`/`contract_size`/`exercise_style`), then
extract — so the extraction is a provably pure refactor. Pure Python, no Dash yet.
Closes **Mo6**'s stress-coverage gap.

**Findings:**

- **(a) The primitive was never the fork — the vol mapping was.** Before this
  milestone three repricing paths had grown independently: the crash gauge
  (`crash_repricing.py`), the 2D spot/vol grid (`scenarios.py::scenario_grid_spot_vol`),
  and the dashboard's heatmap orchestration. Measured on the §4 golden book at the
  crash overlap point, the naive grid knob underreported the crash-repriced hedge
  value by **25.4%**. Spot-only reprices agreed to the cent — the pricing primitive
  itself was already unified. The entire gap was which vol-shock → sigma' rule was
  applied. This is what `analysis/repricing.py` (`MarketState`, `MarketShock`,
  `VolMapping`) and `crash_repricing.py`'s `crash_skew_vol` now share as one
  vocabulary, per their module docstrings.
- **(b) `days_forward` as the third dial designs out the state-leak, rather than
  patching it.** The M1.5 bug (`stress.py:897`) mutated `portfolio.valuation_date`
  to a shocked value and restored it afterward — a window in which a mid-loop read
  or an exception could observe the shocked state. Making the date shift a plain
  field on `MarketShock` (defaulting to `0`, i.e. "absent is unambiguously
  instantaneous") means every reprice derives its shocked date from the shock
  object and prices through a fresh, scratch `OptionValuation` — there is no
  portfolio mutation to forget to restore. Guarded by
  `TestNoMutationSurvivesInTheScenarioPath` (`test_repricing.py`), which AST-checks
  that neither `scenarios.py` nor `_render_spot_vol_heatmap` ever assigns
  `.valuation_date`.
  - **Residual, deliberately not removed:** `scenario_grid()` (the *time/price*
    grid behind the time-heatmap panel — a separate, older function from
    `scenario_grid_spot_vol`) still ends with a restore-only
    `portfolio.update_market_conditions(...)` call. It never sets a shocked value
    (so it doesn't reintroduce the M1.5 hazard), but it is a real, still-present
    mutation: it exists because `BatchPricer` prices via scratch objects whose
    construction writes QuantLib's *global* `Settings.instance().evaluationDate`
    singleton, which would otherwise leak the last-swept `time_point` into
    unrelated later pricing. Documented in place (`scenarios.py`, at the call
    site) rather than removed.
- **(c) Cross-surface vol-mapping decision (binding for M2.4/M2.5).** `/monitor` is
  **crash-skew throughout** — the health gauge, the two-knob scenario explorer, and
  any heatmap on that page all price through `crash_skew_vol`, so everything on one
  screen agrees with everything else on it. `/design` (the workbench,
  `StressDashboard`) uses `proportional_vol`. The two surfaces differ only because
  they answer different questions — "what does the crash story look like" vs. "how
  does this book behave under a generic vol move" — not because of an accidental
  default. `VolMapping` is **required, never defaulted**, at every entry point
  (`scenario_grid_spot_vol`, `get_or_calculate_spot_vol`, `reprice_legs_at`,
  `reprice_portfolio`) specifically so a caller can't silently fall back to the
  wrong surface's model.
- **(d) The unit-mismatch trap.** Grid `vol_scenarios` are *absolute target average
  volatility levels*; `CrashShock.crash_vol_shock` is *additive*. The two only
  disagree once a book has enough skew for the difference between "shift every leg
  to level L" and "bump every leg by δ" to matter — which is invisible on a flat
  book (both collapse to the same number) and is why mapping-agreement tests must
  use a skewed fixture (`TestMappingsDistinguishOnASkewedBook`), not the flat §4
  golden alone.

**Verified at close-out:** both former M1.5 xfails now pass for real
(`TestSpotVolHeatmapGrid::test_valuation_date_and_engines_unaffected_by_spot_vol_render`,
`TestScenarioGridCacheInvalidationGap::test_cache_miss_on_underlying_quantity_change`);
`TestReprisePortfolioAgreesWithCrashHedgeValue::test_agrees_to_the_cent_at_the_ips_crash_point`
(explorer == crash gauge at the IPS point) and
`TestMappingsDistinguishOnASkewedBook::test_three_mappings_give_three_different_values`
both hold; the M1.5 `stress.py` heatmap characterization suite is unchanged; full
gate green (`ruff`, `mypy` strict, `pylint` 10.00/10, `pytest` — 1394
passed at close-out, 2026-07-29).

### M2.2 — Dash skeleton + shared layer (thin app)

**Status: done** — commits `2020cbd`, `1c3ab2f`, `0a9034d`, `c2f8bfe` on
`feat/m2.2a-observation-provenance` (PR: "M2.2 — Dash skeleton and shared
provenance/session layer").

The app shell, thin but real: the two-page structure (`/monitor`, `/design`), a
shared data-provider wrapper that surfaces as-of timestamps and an unmissable
**STATIC / STALE** banner (**M5**), and server-side session/state — real session
persistence, dirty-flag autosave under `exports/`, import-overwrite guard,
confirm-on-remove (**M6**, built once). App-level smoke tests (Dash testing harness /
Playwright — already a dependency) begin replacing the notebook-execution CI gate.
A running app with plumbing, before either surface is fleshed out.

**Findings:**

- **(a) M5 needed a `Protocol` return-type change, not a wrapper.** Every
  `MarketDataProvider` method returns `Observation[T]` rather than a bare
  value with a parallel provenance-only accessor alongside it. A wrapper
  approach would let a caller reach past it and read the unwrapped value
  directly, silently dropping provenance by omission; making
  `Observation[T]` the *only* return type means skipping it is a type
  error, not a quiet choice a caller can make without noticing.
- **(b) One shared `ProgramState`, not per-session.** There is one hedge
  program and one book, so `state.py` builds a single server-side instance
  (constructed once via `ProgramState.load(...)`, threaded through
  `create_app`) rather than a per-browser-session copy. Saves are atomic —
  write to a temp file under `exports/` and rename over the target — so a
  crash mid-write can never leave a half-written file that the next load
  silently trusts.
- **(c) The app is a pure reader.** `CboeFredProvider(read_only=True)`
  (added this milestone) never issues a live fetch: a fresh cache hit is
  still `CACHED`, anything else falls back to the last cached value as
  `STALE`, and only a totally empty cache raises. A cron job (later
  milestone) is what's expected to keep the cache warm — a feed outage
  degrades the chrome banner to an honest STALE rather than taking the
  dashboard down.
- **(d) The app-test path for `dash-smoke-runner`.** Lives at
  `tests/test_app/` — already exactly what the agent's own instructions
  expect, no agent-file change needed. `dash.testing`'s own browser/runner
  fixtures need `selenium` and `multiprocess`, neither a project
  dependency; the harness (`tests/test_app/conftest.py`,
  `test_app_smoke.py`) instead drives Playwright directly against a
  `werkzeug.serving.make_server` instance. This is the *beginning* of the
  app-level replacement for the notebook-execution CI step, not the end of
  it — that step is retired in **M2.6**; the notebooks still execute today.

**Verified at close-out:** `dash-smoke-runner`'s first real invocation
reports **SMOKE PASSED** (both pages boot and render with no client-side
error, no leaked traceback); full gate green (`ruff`, `mypy deltadewa`
strict, `ruff format`, `pylint` 10.00/10, `pytest` — 1473 passed at
close-out, 2026-07-30); both
`monitor_dashboard.ipynb` and `hedge_design.ipynb` still execute cleanly via
`jupyter nbconvert --execute` — confirming M2.6, not M2.2, is what retires
that CI step.

### M2.3 — Deploy the thin app (the "Phase 2.5", brought forward)

**Status: done** — containerization work landed as commits `fb7000a`,
`3ff5c44`, `a1c979c`, squashed into `3b0e58a` (PR #213) and `46b554b`
(PR #215) on `main`; closed out via PR "M2.3 — deploy the thin app to the
VPS behind Tailscale" after live verification on the provisioned droplet.

Stand up the box *now*, while the app is thin, so M2.4/M2.5 are built and tested
against the real runtime. Provision the DigitalOcean VPS; a `Dockerfile` pinning
Python + QuantLib + every wheel and a `compose.yaml` defining the app, the mounted
`exports/` state dir, and restart policy; install Tailscale on the box and each
laptop; bind Dash to the tailnet. Success = the skeleton reachable by **bookmark**
from the partner's laptop over the tailnet, no public port. Write a one-page
**RUNBOOK stub** (fresh-box recovery: install Docker + Tailscale → clone → restore
`exports/` → `docker compose up -d`); finalise it in Phase 3.

**Findings:**

- **(a) The bind-address decision, not UFW, is the security boundary.**
  Inside the container Dash listens on `0.0.0.0:8050` (`DELTADEWA_HOST`,
  set only in the `Dockerfile`'s `ENV` — the code's own default stays
  `127.0.0.1`, per `__main__.py`). That's safe only because
  `compose.yaml` publishes the port to `${BIND_ADDR:-127.0.0.1}` on the
  *host*, not `0.0.0.0` — Docker inserts published ports into the `nat`
  table ahead of any UFW/iptables rule, so a published port bypasses the
  host firewall entirely. `BIND_ADDR` is set to the droplet's Tailscale IP
  via a gitignored `.env` (RUNBOOK §1); an unset `.env` fails
  locked-down (loopback-only) rather than open. RUNBOOK §2's exposure
  check verifies both directions and is mandatory after any `ports:`
  change.
- **(b) gunicorn over the dev server, one worker.** `ProgramState` is one
  shared in-memory instance per the module's own docs ("one hedge
  program, one instance") — a second worker *process* would fork it into
  an independently-drifting portfolio. `gunicorn --workers 1
  --worker-class gthread --threads 4` gets concurrency from threads
  sharing that one process's memory instead; the default sync worker
  class ignores `--threads` entirely, so `gthread` is required, not
  cosmetic. `deltadewa/app/wsgi.py` gives gunicorn and local dev one
  shared app-construction function so the two paths can't drift apart.
- **(c) `/health` is reserved for M2.6's dead-man's switch, not a bare
  liveness probe.** `factory.py`'s `/health` route is cheap (no
  repricing) but reports `state_loaded` (whether `ProgramState` actually
  restored a persisted file, not just "the process is up") and the
  provenance of the freshest market-data reading, reusing the same
  `assess_market_environment` call `_serve_layout` already makes for the
  chrome banner. This is deliberately more than a liveness check because
  M2.6's monitoring needs to distinguish "container is up" from "the data
  pipeline behind it is actually healthy."
- **(d) QuantLib-in-Docker was a non-issue.** `python:3.11-slim` +
  QuantLib installs from a prebuilt manylinux wheel — no build toolchain
  (gcc/cmake/Boost headers) needed in the image, confirmed both locally
  via colima and on the droplet. Image is 1.32 GB; Jupyter/notebook/
  Playwright remain in the main dependency group and are unused at
  container runtime — a follow-up, not addressed here.
- **(e) The deployed app is deliberately content-free.** What's live is
  the M2.2 skeleton plus this milestone's ops plumbing (Dockerfile,
  compose, `/health`, RUNBOOK) — no monitor/design surfaces beyond what
  M2.2 already shipped. M2.4/M2.5 build their real content against this
  already-live environment rather than deploying blind at the end of
  Phase 2.

**Verified at close-out** (2026-08-03, live on the provisioned droplet over
Tailscale): `gate-runner` green (`ruff`, `mypy` strict, `pytest` — 1500
passed at close-out, `pylint` 10.00/10); `dash-smoke-runner` green (24/24 app-level
tests; both pages render; banner logic for all five provenance states —
live, cached, stale, static, unavailable — verified). On the box itself:
`/health` returns `200` with `state_loaded: false` and
`market_data.source: UNAVAILABLE` — the honest, correct response for a
box that has never run a market-data fetch (M2.6's cron doesn't exist
yet), not a bug; `/monitor` and `/design` both return `200`, and the
rendered chrome shows the matching `UNAVAILABLE` banner and "No as-of
date" stamp — confirming the provenance chain is live end-to-end on the
real box, not just in tests. `docker compose restart app` survives
cleanly: the container is back `Up` within seconds and `/health` is
identical before and after, confirmed from off-box over Tailscale, since
`BIND_ADDR` intentionally leaves nothing listening on the host's own
loopback — an unplanned second confirmation that the exposure design
holds even from the host itself.

### M2.4 — The monitor (lead with the crash)

**Status: done** — commits `dc7f70c`, `083b3cd`, `43b12fc`, `6bea05d`, `51689da`,
`84dea56`, `94079e8`, `5dcd068`, `da4db65`, `641d904`, `c03d177`, `24384b1`,
`541a04b`, plus a partner-feedback fix commit, on `feat/m2.4-engine-gaps` (PR:
"M2.4 — the crash-led monitor").

The partner's surface, and the highest-care work in Phase 2. Three sections, each
answering one question:

- **What is this costing us?** — the carry story: why we pay, how much, that it's
  the price of protection, not a loss.
- **What do we get for it?** — the payoff story, and the interactive heart. The
  **two-knob scenario explorer** (spot move, vol move) lives here, **leading with
  the crash**: the first screen is essentially "here's what happens if it crashes,"
  with live repricing and a clear before/after. Engine takes arbitrary shocks
  (M2.1); the monitor **exposes two**, with room for a third later.
- **What are we doing about it, and why?** — the roll/monetization verdicts with
  their **reasoning surfaced** ("holding because convexity is in band and we're
  outside the roll window," not just a green light).

Through-line: **legible cold, every time** — plain-language framing on every panel,
bands drawn so "in range" is obvious without recalling the threshold; optimise for
the smart reader returning after eight weeks, not the daily expert. As-of stamps and
STALE banners everywhere (**M5**). Resolve **M2** (the inert hedge-success gauge):
omit it until realized-carry tracking exists rather than ship a permanently-neutral
gauge.

**Findings:**

- **(a) The quantity dial is scenario-local, with a structural guard, not just a
  convention.** The scenario explorer's three dials (spot, vol, quantity) never
  call a `ProgramState` mutator — `monitor_scenario.build_scenario` takes
  `quantity` as a plain argument and reprices/recomputes carry against it without
  ever touching `portfolio.underlying_quantity` or triggering an autosave.
  `tests/test_app/test_monitor.py::TestScenarioLocalGuard` pins this by
  exercising every dial across its full range and asserting `state.dirty` stays
  `False` and no new file appears under `exports/` — a reader moving the dials
  cannot accidentally mutate the shared book, and the test would fail loudly if
  a future change made that possible.
- **(b) The dials start at the IPS crash-anchor point, so the explorer *is* the
  gauge at first paint, structurally.** `render()` initialises
  `spot_pct`/`vol_points`/`quantity` from
  `ips_config.convexity.crash_scenario_pct`/`.crash_vol_shock`/
  `portfolio.underlying_quantity` — not just numerically equal to the gauge's
  own inputs, but built through the identical `CrashShock.from_ips(...)`
  pathway the gauge itself uses. `TestAgreement` pins the headline number
  against `crash_hedge_value(portfolio, shock=CrashShock.from_ips(...))` to the
  cent, the structural guarantee M2.1 was built to make possible.
- **(c) `crash_skew_vol` is threaded through every /monitor repricing path, not
  just the gauge.** The vol dial is not a flat vol bump: `CrashShock.to_shock()`/
  `.vol_mapping()` — the pair `build_scenario`, `crash_value_curve`, and the
  curve-reshaping callback all call — routes through `crash_skew_vol`'s
  wing-anchored skew mapping internally, the same basis `calculate_crash_convexity_pct`
  (the gauge) uses. The monitor never assembles a raw `MarketShock` anywhere;
  this is what keeps the scenario explorer's curve and headline number
  consistent with the gauge as the dials move, not just at the default position.
- **(d) Explanatory, not actionable — by omission, not restraint.** The monitor
  has no roll/monetize/edit buttons anywhere; DECISIONS shows a verdict badge
  plus `fmt.roll_verdict_reason` text, band bars, and the monetization
  schedule as read-only numbers. `register_callbacks` wires exactly three
  dials and a reset button, none of which reach a `ProgramState` mutator —
  matching CLAUDE.md's framing of `/monitor` as the "read-mostly book review"
  page, distinct from `/design`'s editor. The legibility pass (3-s.f. headline
  numbers with exact values in a `title` tooltip, band bars for in-range-at-a-
  glance, the collapsed per-leg ledger, and a plain-language rewrite assuming
  no program vocabulary) is what makes that read-only page legible cold rather
  than merely inert.
- **(e) Two partner-facing fixes from the first live review.** Showing the
  deployed page cold surfaced two real gaps no test caught: the spot-shock
  slider's tooltip rendered behind the payoff-curve card (the slider handle's
  own `transform` opens a nested stacking context, so the tooltip's `z-index`
  only won locally — fixed by giving `.dial-row` its own explicit
  `position: relative; z-index` so the whole subtree paints above the graph),
  and the page never showed the reference spot price the shock dials move
  from, despite it already being on `portfolio.spot_price` — added as a plain
  sentence under the "Crash scenario" heading. Neither needed new engine code.

**Verified at close-out:** `gate-runner` green (`ruff`, `mypy` strict,
`ruff format`, `pylint` 10.00/10, `pytest` — 1578 passed at close-out,
2026-08-03); `dash-smoke-runner`
green (79/79 app-level tests, both `/monitor` and `/design` render cleanly),
with `TestAgreement` and `TestScenarioLocalGuard` confirmed passing by exact
node ID. Deployed live to the droplet (RUNBOOK §4) with the repo's own golden
SPX tail-hedge fixture (`examples/portfolios/spx_tail_20m.yaml`) loaded as
demo data — reproduced that fixture's own published numbers exactly ($298,099
hedge value today, $5,226,004 in the IPS crash scenario, 17.5x) before
shipping it, so the partner review was against real, checked economics, not
an empty book. `/monitor` confirmed rendering over the tailnet with an honest
`MARKET DATA UNAVAILABLE` banner (no live market-data provider configured on
the droplet yet — an `[M2.6 TODO]`, not a bug). Partner reviewed the live page
cold; both fixes from that review verified fixed on the redeployed droplet
before commit.

### M2.5 — The design workbench

**Status: done** — commits `933ad5d`, `7d06f82`, `aa91ff9`, `86f49d8` (engine
prerequisites: entry_premium's write path, `underlying_quantity`'s guarded
mutator, the percent/fraction validation seam on both grid specs, and the
Monte Carlo `persist_cache` opt-out), `bbe47b4` (BOOK zone: per-request page,
IPS gate, position editor, guarded import/export), `fe9bc1b` (PLANNING zone:
sizing, ladder, roll, monetization), `782d930` (EXPLORATION zone: stress
heatmaps and MC distribution), `2eee9d3` (the cross-page shared-book
regression test below), `b5b7678` (a finding-ID correction caught while
writing this section — see the note under Mi5/Mi6 below), all on
`feat/m2.5-design-exploration`; closed out via PR "M2.5 — the design
workbench" after live verification on the droplet.

The dense expert tool migrated to Dash — sizing / ladder / monetization / roll
planners on the corrected engine, plus the three notebook stress surfaces
(spot-vol heatmap, time-price heatmap, MC distribution), plus the position
editor. Position editor gains the missing **`entry_premium`** and
**`underlying_quantity`** inputs (**Mo3/Mo7**); reactive panels eliminate the
stale-panel / re-run-cells problem (**Mo7**); the C2 editor exercise-style
default (deferred from M1.5a) lands here, defaulting from the IPS. No red
primary buttons; no leaked tracebacks or `DEBUG:` prints. Import/export via
the guarded session layer (supersedes **Mo5**). Less design agonising — the
reader is the operator.

**Findings:**

- **(a) The IPS gate is page-level, not per-panel — because the editor
  needs it too, not just the planners.** `render()`/`register_callbacks()`
  both short-circuit on `app.ips_config is None` before building anything.
  The planners obviously need policy (sizing targets, ladder bands, roll
  thresholds are all IPS-derived) — but so does the BOOK zone's add-form:
  its exercise-style default has no other source (C2), and without a
  policy to plan against, a bare editor with no planning context isn't a
  useful degraded state, it's just a different kind of broken page. One
  gate, one `_no_ips_layout()`, matching `/monitor`'s own discipline
  (M2.4) rather than inventing a second no-IPS story.
- **(b) Add/remove only — `update_position` exists and stays deliberately
  unwired.** Changing a position on `/design` is remove + add, not an
  in-place edit; there is no "update" form anywhere in `pages/design.py`,
  and no test references `ProgramState.update_position` from this page.
  The reasons: an in-place edit UI has to reconcile *which* fields changed
  against `entry_spot`/`entry_date`/`entry_premium`'s cost-basis semantics
  (a changed strike isn't "the same position, different strike," it's
  economically a different position), and remove+add reuses the exact
  guarded mutators and confirm-dialog discipline the rest of the page
  already has — no new mutation shape to review or misuse.
  `update_position` isn't deleted (other callers may still want it), it's
  just not this page's editing model.
- **(c) Both bases render on one page now, so both are labelled, not just
  the one that might surprise a reader.** PLANNING prices **crash-skew**
  (`CrashShock.from_ips(ips_config.convexity)`, identical to `/monitor`'s
  gauge) and EXPLORATION prices **proportional vol** (every leg scaled so
  the vega-weighted average reaches the dial's level, via
  `proportional_vol` — always passed explicitly to `ScenarioGridCache`,
  never defaulted, M2.1 finding (c)). Four mechanisms carry that split so
  a reader meets it as a design fact, not a bug: a zone header naming the
  basis on both zones; a boundary sentence between them stating the
  expected discrepancy *in advance*; a `basis_chip(...)` on every
  repricing panel (now shared with `/monitor`'s own crash-scenario header,
  so the vocabulary is one program-wide vocabulary, not `/design`-local);
  and honest units — EXPLORATION's spot-vol y-axis is labelled an
  *absolute IV level*, `/monitor`'s dial is labelled an *additive bump* —
  the exact unit mismatch that hid M2.1's −25.4% gap. EXPLORATION
  cross-references `/monitor` by link only; it never re-renders a crash
  number itself, so there is exactly one place either basis's number is
  computed.
- **(d) The grid compute is live-reactive with no Recompute button,
  because the numbers said the button was solving a problem that doesn't
  exist.** Measured on `examples/portfolios/spx_tail_20m.yaml` (3 legs) on
  the corrected engine: spot-vol grid 21×21 (the default resolution)
  **0.061 s**, 41×41 (the slider's max) **0.217 s**, time-price grid
  10×13 **0.003 s**, Monte Carlo 100,000 paths **0.019 s** — all well
  under the threshold where a reader would perceive "frozen" rather than
  "updating." Every dial uses `dcc.Input(..., debounce=True)` or
  `dcc.Slider(..., updatemode="mouseup")` so a drag or keystroke run
  commits once, not per pixel/character; one `ScenarioGridCache` lives on
  `ProgramDashApp` for the app's lifetime (not per-callback), so a dial
  moved back to a value already seen is free; each panel's output is
  wrapped in `dcc.Loading` so the sub-quarter-second case still reads as
  "working." A button would have added a click to every interaction to
  save a cost nobody can perceive, and would have reintroduced exactly
  the stale-panel problem (Mo7) this milestone exists to remove.
- **(e) A finding-ID mislabel, caught and corrected while writing this
  section.** The unsolvable-ladder-rungs surfacing (M1.4's strike-ladder
  bullet, third clause — "silently-dropped unsolvable ladder rungs") had
  been cited in this milestone's own code and tests as finding **"Mi5."**
  That ID already belongs to a different, unrelated, already-closed
  finding — the `include_underlying` scalar/vectorized P&L default
  mismatch, pinned in `tests/test_portfolio/test_pnl.py` and confirmed by
  `tests/test_ips_config.py`'s own `Mi6` comment on the neighbouring
  carry-ceiling fix. The unsolvable-rungs gap was never given its own
  number in the finding index at all — commit `b5b7678` removes the wrong
  ID from `design.py`/`test_design.py` rather than inventing a right one.
  Recorded here so the mistake doesn't get re-copied from this file the
  way it was copied *into* the code from an earlier planning draft.
- **(f) A live-observed, deliberately-deferred gap: `wsgi.py`'s production
  entrypoint still doesn't set `default_exercise_style`.** Confirmed live
  on the droplet, not hypothetically: the sizing panel degrades to its
  own engine-level message ("`portfolio.default_exercise_style` must be
  set before evaluating candidates...") — via `_safe_render`, not a
  traceback — for the box's currently-loaded book, because
  `ProgramState.load(Path("exports"))` in `wsgi.py` never passes
  `default_exercise_style`. This is the exact entrypoint-level gap flagged
  as explicitly out of scope when the BOOK zone landed (`/design`'s own
  add-form always supplies an explicit style per leg, C2, so it never hits
  this path) — live review just confirms the gap is real for any book
  whose portfolio-level default was never set some other way. Not fixed
  here (it's a one-line, already-scoped-out entrypoint change, not a
  `/design` change); worth a small follow-up PR passing
  `default_exercise_style=ips_config.pricing.exercise_style` once the IPS
  config is available at `wsgi.py`'s call site.

**Verified at close-out:** `gate-runner` green (`ruff`, `mypy deltadewa`
strict, `ruff format`, `pylint` 10.00/10, `pytest` — 1669 passed at
close-out, 2026-08-04; one
timing-sensitive perf test, `test_vol_update_faster_than_rebuild`,
flaked once under load and passed cleanly on three immediate reruns —
untouched by this milestone's changes, not a regression); `dash-smoke-runner`
green (124/124 app-level tests, both pages render with no client-side error
and no leaked traceback). `TestSharedBookAcrossPages` (new this milestone)
pins the cross-page guarantee directly: a position added through
`state.add_position` — the real BOOK-zone write path — appears on
`/monitor`'s next render; `entry_premium` flips `/monitor`'s monetization
panel from "no entry price is recorded" to a real gain percentage;
`underlying_quantity` flips `/monitor`'s offset-ratio figure from "n/a" to a
real ratio.

Deployed live to the droplet (`git fetch && git checkout
feat/m2.5-design-exploration && docker compose build && docker compose up
-d`, RUNBOOK §4) and confirmed over Tailscale with a real headless-browser
check (not just `curl`, since Dash's initial HTML response is a client-side
shell — the served `assets/deltadewa.css` was checked first to confirm the
new build, not a stale image, was actually running): both `/monitor` and
`/design` render client-side with zero console/page errors and no leaked
traceback; `/design` shows all three zones (`.zone-book`, `.zone-planning`,
`.zone-exploration`) and 9 basis chips (1 PLANNING header, 4 PLANNING panels,
1 EXPLORATION header, 3 EXPLORATION panels); the MC panel's Plotly graph
renders. Against the box's live 5-position book, `/monitor` and `/design`'s
monetization panels agree on the current hedge gain (**−88.1%**) to one
decimal place — the crash-skew single-source claim (finding (c)), confirmed
live, not just in `TestPlanningZoneAgreesWithMonitor`.

### M2.6 — Headless report + cron + backup (the heartbeat)

**Status: done** — code, docs, and the live droplet deploy all verified
(see close-out below).

The Part VII board report as a parametrised, schedulable entrypoint rendering
deterministic HTML/PDF, with **M8** content: return framing from tracked start/end
book values, realized monetization, and an as-of stamp. Golden-file regression test.
**Stale-data policy: send stamped-stale, impossible to miss.** Host cron drives three
jobs: market-data refresh, the weekly report email, and the `exports/` backup
push. Backup goes to a private **offsite** repo (Codeberg; optional `age`
encryption, deliberately deferred — a backup you can't decrypt is worse than one
you can). The **email-delivery mechanism** is SendGrid's v3 REST API, called
directly via `requests` rather than adding its SDK as a dependency. The
notebook-execution CI steps are retired now that app + report tests cover both
surfaces.

- **Weekly-digest-leads-with-change.** The digest leads with what changed since
  last week — verdict crossings, band exits, staleness — rather than repeating a
  near-identical report 52×/year. Return framing shows the week's own carry cost
  alongside the cumulative figure since the first snapshot, so one week of pure
  theta doesn't read as a loss story on its own (`weekly_snapshot.py`: that
  cumulative figure is carry cost, a flow, not premium paid, a stock — the
  latter would double-count or miss cash entirely across a roll).
- **Stamped-stale policy, concretely.** The staleness banner always renders,
  driven by `MarketContextSection.data_quality` — already the worst `Source`
  across every live observation `assess_market_environment` makes
  (`Observation.combine`). The digest is never silently skipped for stale data.
- **Refresh job's partial-failure semantics.** Each of the six series the app
  depends on is fetched independently; one failure never aborts the run and
  never blanks a prior cache entry (the disk cache only writes on success).
  Exit 0 = every series refreshed live; 1 = partial (the normal early-morning
  state — FRED's VIXCLS publishes with a lag); 2 = total failure. Callers
  should treat 0/1 alike and escalate only on sustained 1s or any 2.
- **Dead-man's-switch model.** Two independent healthchecks.io-style checks,
  because the two jobs fail independently: REFRESH pings on exit 0 and 1, not
  2 (so a routine partial morning doesn't page); DIGEST pings only on a
  confirmed send — the one path where silence is dangerous, since a missing
  weekly email reads exactly like "a quiet week."

**Findings closed:**

- **M8 (partial — corrected post-close-out, see #171)** — the as-of stamp
  shipped (`ReportHeader.as_of`, both renderers). Return framing did
  *not* ship as originally claimed here: start/end book values are still
  untracked, and §4 rendered a literal `PENDING` inside every digest even
  though the digest's own lede stated real carry-cost numbers above it —
  a contradiction fixed in a follow-up PR by rewiring §4 to that same
  carry-cost framing (not book-value return) instead of duplicating it in
  the lede. Realized monetization remains an honest placeholder, now
  citing #70 (the issue it's actually blocked on) instead of a stale,
  unrelated finding ID. M8 stays open until #70 lands.
- **M5** — chain now complete end to end. The Dash-native STALE/STATIC banner
  itself shipped in M2.2, but until this milestone's refresh cron actually runs
  on the droplet, production could only ever show `UNAVAILABLE` (confirmed at
  the M2.3 close-out) — never the `CACHED` state the banner logic was built
  for. The droplet verification below is what finally exercises that state for
  real.

> **Checkpoint:** notebooks retired; the app is live on the VPS behind Tailscale,
> reachable by the partner without the operator; the weekly report emails; CI green
> on the new (app + report) gate.

**Verified at close-out (code):** `gate-runner` green (`ruff`, `ruff format`,
`mypy` strict — 120 files, `pylint` 10.00/10, `pytest` — 1753 passed at
close-out, 2026-08-06) against
the full (`dev`+`test` groups) install; `dash-smoke-runner` green (129/129
app-level tests). `poetry install --only main` in a scratch venv, then
importing `deltadewa.app.wsgi`, `marketdata.refresh`, `reporting.weekly_report`,
`reporting.email_sendgrid`, and `heartbeat` all succeed with matplotlib,
seaborn, ipywidgets, ipyfilechooser, the whole Jupyter/notebook stack,
Playwright, and IPython genuinely absent — confirming the `dev`/`test` group
split (image-slimming work below) didn't silently break the production import
graph. `docker build`: **758 MB**, down from the M2.3 close-out's recorded
1.32 GB (a ~43% reduction); the built image runs and `/health` responds
correctly.

**Verified live (2026-08-09):** the droplet deploy + manual job run +
email/backup verification (RUNBOOK §4/§11/§12) all confirmed on the
provisioned box — the Phase 2 checkpoint above is met, not aspirational.
Refresh cron running (6/6 series fetched); `/health` reads `CACHED` with a
real `as_of` — the state M2.2's banner logic was built for but the M2.3
close-out could only ever show `UNAVAILABLE` (no cron had run yet); weekly
digest delivering via Brevo; Codeberg offsite backup pushing; both
`REFRESH_HEARTBEAT_URL`/`DIGEST_HEARTBEAT_URL` heartbeats green.

Three deploy findings surfaced during this verification, undocumented
anywhere until now (full detail in RUNBOOK):

- DigitalOcean blocks outbound SMTP on 25/465/587; port 2525 is open and
  is what this deployment's `SMTP_PORT` uses (RUNBOOK §10).
- Brevo requires the sending IP allowlisted — a rebuilt droplet silently
  fails to send until its new IP is added there (RUNBOOK §7).
- `ops/backup-exports.sh` only sets the git remote on first init; an
  `exports/.git` restored with an HTTPS remote instead of the SSH alias
  makes the cron push hang on a credential prompt with no TTY to answer
  it (RUNBOOK §10).

---

### M2.7 — Restore the Part X coverage the Dash rebuild dropped

**Shipped.** A surfacing milestone, not a rebuild: every engine function
already existed and was unit-tested. Driven by `docs/part-x-coverage.md`'s
2026-08-06 re-audit, which found five handbook items the M2.4/M2.5 Dash
rebuild silently stopped surfacing, with no decision recorded anywhere to
drop them.

Six commits:

1. **`analysis/hedge_efficiency.py`** — the convexity÷carry ratio (Part X
   **#5**/**#15**), which existed nowhere in the codebase. Both handbook
   worked examples are pinned as tests. Band from a new
   `convexity.efficiency_min_ratio`/`_max_ratio` IPS pair (the handbook's
   3/6 reading), not a module literal.
2. **`/monitor`** — the ratio in the cost panel, as one plain-language
   sentence. No big number, no band bar: the page already carries five and
   two, and M2.4's "legible cold" through-line rules out a sixth headline.
   A test pins that.
3. **`/design`** — a market-environment panel carrying **#6**, **#7**, **#8**
   *and* the decision matrix + entry-timing tree. Those three readings are
   exactly the matrix's inputs; splitting them from the verdict across
   surfaces is what lost them.
4. **`/design`** — **#4** vega sufficiency in the sizing panel and **#10**'s
   net-delta scalar in BOOK. The vega band moved from `dashboard.yaml`
   (presentation) to a new `vega:` IPS section, with the existing values
   carried over verbatim so no reading changed meaning.
5. **`/design`** — the hedge-trigger set (**#11**'s other half).
   `analysis/hedge_triggers.py` had no functional consumer at all; a pure
   `evaluate_hedge_trigger_set` was extracted from the console-printing
   `evaluate_hedge_triggers`, whose signature and output are unchanged and
   whose test suite passed with no edits — the contract that no firing point
   moved.
6. **Docs** — `part-x-coverage.md` rewritten to the post-M2.7 state, with the
   conscious retirements (Part VII report → emailed deliverable; #2's
   discrete table → the curve) recorded as decisions rather than leftovers,
   and **#9**'s skew-beta scalar stated as never built rather than lost.

**Left open, deliberately:** #12 (data-blocked), #13/#14 (surfacing gaps not
in this milestone's brief), #9's scalar (a genuine feature — it needs a
repricing pass at a perturbed skew), the four remaining Jupyter-only health
gauges, `dashboard.yaml`'s now-duplicated `vega_sufficiency` block, and
`entry_timing_tree`'s hardcoded VIX thresholds (a pre-existing policy leak of
the M1.4 class, surfaced but not fixed here). All six are listed in
`part-x-coverage.md`.

**Verified at close-out:** `gate-runner` green (`pytest` — 1847 passed at
close-out, 2026-08-07 — M2.8's number; M2.7 has no close-out figure
recorded separately, since M2.8 merged 12 minutes later the same day);
`mypy` strict, `ruff check` clean, `pylint` 10.00/10.

- **#5/#15 reduce to one function.** `hedge_efficiency()`
  (`analysis/hedge_efficiency.py:104`) computes
  `crash_payoff / abs(annual_carry)` (`:152`) — the dollar form. Its
  docstring (`:19-26`) shows why that's also the percentage form: both
  `crash_repricing.crash_convexity_pct` and `carry.carry_vs_budget`
  already normalize by the same protected book —
  `abs(underlying_quantity * spot)` — before `hedge_efficiency` ever sees
  the inputs, so the normalizer cancels and no second function is
  needed. `tests/test_analysis/test_hedge_efficiency.py`'s
  `TestHandbookWorkedExamples` pins both handbook worked examples
  verbatim (`1.5M / 300k = 5x`, `22% / 3% = 7.3`).
- **Vega band moved, values unchanged.** `config/ips.yaml`'s new `vega:`
  section (`sufficiency_min_pct: 20.0`, `sufficiency_max_pct: 50.0`)
  carries `dashboard.yaml`'s `vega_sufficiency` gauge values over
  verbatim (`max_val: 20` → `sufficiency_min_pct`, `end: 50` →
  `sufficiency_max_pct`) — moving the metric onto a policy surface
  didn't silently change what a reading means. `dashboard.yaml` keeps
  its own copy since the Jupyter gauge still reads it; retiring that
  copy was left out on purpose (see `part-x-coverage.md`).
- **`/monitor` stays a sentence, not a sixth headline.**
  `_efficiency_sentence()` (`app/pages/monitor.py:146`) is a deliberate
  `html.P`, never a `band_bar`/`big-number` — the page already carries
  five big numbers and two band bars. Pinned by
  `test_app/test_monitor.py::TestHedgeEfficiencySentence::test_stays_a_sentence_not_a_sixth_headline`,
  which asserts zero `.big-number`/`.band-bar` descendants on the
  rendered paragraph.

---

### M2.8 — Delta Drift, Vega Term Exposure, and the entry-timing VIX policy leak

**Status: done** — PR #232, merged 2026-08-07.

Closes the last two Part X items the 2026-08-06 re-audit left as
data-blocked (they were surfacing gaps, not data gaps) and the policy leak
M2.7 surfaced when it put the entry-timing tree on a page for the first
time.

- **§13 Delta Drift** —
  `analysis/scenarios.ScenariosMixin.calculate_delta_drift`
  (`scenarios.py:212`), the handbook's `Δ(−5%) − Δ(0)` (hedge-only,
  signed; `DELTA_DRIFT_SHOCK_PCT = -5.0`, `scenarios.py:58`), summed over
  option legs. `/design` PLANNING panel beside hedge rebalance triggers.
- **§14 Vega Term Exposure** —
  `analysis/maturity.MaturityMixin.calculate_vega_by_maturity`
  (`maturity.py:114`), reusing `classify_maturity_bucket`
  (`maturity.py:60`) via the same `add_maturity_buckets` helper
  `carry.py:106` already applies to theta — one bucketing scheme, so the
  theta panel (`monitor_dashboard.ipynb`, `carry_display.py`) and the new
  vega panel (`/design` EXPLORATION) cannot disagree on bucket
  boundaries.
- **Policy leak.** `entry_timing_tree`'s three VIX thresholds
  (`vix_very_high`/`vix_caution`/`vix_low`) were Python defaults;
  `design.py` called it supplying none of them, so the rendered verdict
  was driven by hardcoded numbers invisible to `ips.yaml`. Moved to
  `IpsMarketEnvironment` (`ips_config.py:169-171`) and made required
  keyword-only params with no default (`decision_matrix.py:302-310`, the
  M1.4/M1.5 fail-loud pattern) — the function can no longer be called
  without them. `config/ips.yaml`'s `market_environment:` section now
  carries the three stops; `design.py:814-819` is the fixed call site.
- **Docs.** `part-x-coverage.md` updated: §13/§14 → **PRESENT**, §12
  (liquidity) is now the only genuinely data-blocked Part X item, tracked
  in #156 (the options-chain feed — Tier-4 liquidity, skew-aware pricing,
  backtesting). #9's skew-beta scalar stays explicitly "never built" —
  not part of this milestone's brief.

**Verified at close-out:** `gate-runner` green (`ruff`, `mypy` strict,
`pylint` 10.00/10, `pytest` — 1847 passed at close-out, 2026-08-07);
`dash-smoke-runner` green (headless `/design`, both new panels).

### Fix — refresh job's silent no-op (post-M2.8, pre-Phase 3)

**Status: done** — branch `fix/refresh-job-silent-noop`.

`refresh.py`'s cron built its `CboeFredProvider` with the same TTL the
read-only app reads with, so `_request_with_fallback` returned a within-TTL
disk-cache hit before ever attempting a live fetch — the job still logged
"Refreshed N/N series" and exited 0 with `fetched_at` frozen. Fixed with an
explicit `force_fetch` constructor flag (bypasses the fresh-cache
short-circuit; decoupled from the app's read-side TTL, which is untouched)
and a corrected `refresh_all()` counting rule: only `Source.LIVE` counts as
refreshed, so a `CACHED`/`STALE` result logs as "NOT refreshed" and can no
longer stand in for a real observation. **Exit 0 now means what it always
should have** — all six series fetched live — so partial (exit 1) is a more
frequent, and more honest, reading than before; the heartbeat still pings on
0 and 1, so this doesn't change alerting, only what the log shows.

**A fourth instance of the same defect shape.** Every occurrence below is a
policy or config value that kept the surface reporting normally while
silently not doing what that surface implied:

| Where | Value | Silent behaviour |
| --- | --- | --- |
| M1.4/M1.5 | `crash_vol_shock` | repriced **spot-only** |
| M1.8 | `skew_reference_delta` | ignored the **IPS wing anchor** |
| M2.1 | vol mapping (implicit per repricing path, pre-`VolMapping`) | **25.4%** underreport on the grid knob vs. the crash gauge |
| this fix | refresh job's fetch | a cache hit stood in for a live observation; `fetched_at` stopped advancing behind a green exit code |

M1.10 closed the pricing-side occurrences with a structural, package-wide
guard (`test_crash_pricing_contract.py`'s AST scan against any
crash-pricing-parameter default, anywhere in the package). This fix has no
equivalent — `force_fetch` is one flag at one call site, not a scanned class
of parameters, so the mitigation here is narrower than M1.10's. Four
occurrences across two unrelated subsystems (the pricing engine, the
market-data refresh job) is enough evidence to treat "a value that silently
degrades while the surface still reports success" as a defect class worth
checking for deliberately during review — not discovering a fifth time.

---

## Phase 3 — Docs & handbook (post-migration, per your call)

- README (chart stack, feature status, `__version__` 0.4.2 → 0.5.0 — this
  line originally targeted 0.1.0 → 0.2.0 and had already drifted three
  releases behind by M2.6; re-check the actual current version in
  `pyproject.toml` before using this figure rather than trusting it again)
  and a
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
  - **Concentrated single-name crash-beta gap (opened by the §2499 beta
    multiplier).** M1.4 shipped `IpsSizing.portfolio_beta` — the handbook's
    beta-adjusted sizing (`hedge notional = book × β`) — but the handbook only
    covers a *diversified* book with a stable β near 1.0. It gives **no
    process** for (a) estimating a *crash* beta for a concentrated,
    single-name-heavy book (betas fan out and rise in a sell-off), nor (b)
    deciding **when single-name (idiosyncratic) put overlays are warranted**
    versus index puts alone. The shipped multiplier deliberately does not
    invent this; index puts under-protect idiosyncratic risk, and this section
    must supply the missing methodology before that book type is sized here.
- Add CHANGELOG / CONTRIBUTING / SECURITY; fix the LICENSE author vs repo-owner
  mismatch.

---

## Deferred — backlog, not in this plan

Only the first is genuinely blocked. The 2026-08-06 re-audit reclassified
the other two against the handbook's own definitions; M2.7 did not take
them, but nothing is stopping them.

- **#12 Liquidity Risk** — **data-blocked.** Needs a live options-chain feed
  (bid/ask, OI per strike); the free CBOE/FRED provider returns index-level
  series only.
- **#13 Delta Drift** — **a surfacing gap, not a data gap.** Handbook §13
  defines it as `Δ(−5%) − Δ(0)` — two shocked deltas at one valuation date,
  not a series from position history. `analysis/scenarios.py` already prices
  `metric="net_delta"` at arbitrary shocked spots. Needs the scalar and a
  panel. Do **not** wire `health.delta_drift_from_target` for this: despite
  the name it is deviation from a target net-delta ratio, and since M2.7 it
  backs `/design`'s hedge-trigger panel.
- **#14 Vega Term Exposure** — **a surfacing gap.** Maturity-bucketed vega;
  `analysis/maturity.py`'s bucket logic (already used for theta carry)
  extends directly.
- **#9 Skew Exposure / Beta** — **never built**, as distinct from lost. No
  `∂V/∂skew` scalar has ever existed here; the coverage table's PARTIAL rests
  on the `vega` heatmap metric, which is a related but different quantity.
  This one is a genuine feature — it needs a repricing pass at a perturbed
  skew, which `crash_repricing.crash_skew_vol` can express but nothing
  drives.

---

## Finding → milestone index (coverage check)

| Finding | Milestone                                    | Finding     | Milestone                                    |
| ------- | -------------------------------------------- | ----------- | -------------------------------------------- |
| C1      | M1.2                                         | Mo5         | M2.5 (Dash; notebook version skipped)        |
| C2      | M1.1 (logic) + M2.5 (editor default)         | Mo6         | M1.5 + M2.1                                  |
| C3      | M1.1                                         | Mo7         | M2.5 (reactive UI; notebook version skipped) |
| C4      | M1.2                                         | Mi1         | M0.1 (`CLAUDE.md`) + Phase 3 (rest)          |
| M1      | M1.3                                         | Mi2         | Phase 3                                      |
| M2      | M2.4                                         | Mi3         | M0.2                                         |
| M3      | M1.3                                         | Mi4         | M1.4                                         |
| M4      | M1.1                                         | Mi5         | M1.3                                         |
| M5      | M2.2 (Dash-native)                           | Mi6         | M1.4                                         |
| M6      | M2.2 (Dash-native; notebook version skipped) | Negligibles | Phase 3 / batch with nearest touch           |
| M7      | Phase 3                                      | #12/#13/#14 | #12 data-blocked; #13/#14 surfacing gaps     |
| M8      | M2.6                                         |             |                                              |
| Mo1     | M1.2                                         |             |                                              |
| Mo2     | M1.4                                         |             |                                              |
| Mo3     | M1.4 (logic) + M2.5 (UI inputs)              |             |                                              |
| Mo4     | M1.3                                         |             |                                              |
