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
  also `nbqa ruff` + headless notebook execution. The clock-shift probe (M1.11)
  is deliberately **outside** this list — see there for why.
- Read the sibling module before adding to it; match its style.

---

## Phase 0 — Tooling & memory (do literally first; < 1 session)

**Status: done** — PRs #186, #187, #188.

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

**Gate at close-out:** pytest **1340 passed / 2 xfailed**, mypy clean, ruff check +
format clean, pylint **10.00/10** (the arity gate that blocked the scalar approach).

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

**Gate:** pytest **1343 passed / 2 xfailed**, mypy clean, ruff check + format
clean, pylint **10.00/10**, nbqa ruff clean on both notebooks.

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
| Gate | pytest **1357 / 2 xfailed**, mypy clean, ruff clean, **pylint 10.00/10**, nbqa ruff clean |

Goldens are byte-identical to the pre-M1.8 baseline throughout: M1.8/M1.9/M1.10
changed how parameters travel, never what is computed.

**Ledger — still deferred after this work.**

| Item | Status |
| --- | --- |
| **Crash-shock term structure** — one cross-sectional slope, no tenor dependence | Open (methodology §8) |
| **`default_crash_shock()`** — prices `0.15 / 0.0 / 0.10` when `ips_convexity is None` | Open by decision: a named, documented fallback so the pre-IPS crash panel renders at all. Not a parameter default, so out of the new guard's scope. Removing it would change public behaviour of `crash_scenario_table` and `CrashPayoffDisplay`. |
| **`_shock_to_multiplier`** (`crash_payoff.py`) — defined and tested, called nowhere | ✅ Closed: function and its test deleted in `4ed97bf` |
| **Tier-4 metrics** #12 Liquidity Risk, #13 Delta Drift, #14 Vega Term Exposure | Open: data-blocked (see `part-x-coverage.md`) |

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
| Gate | pytest **1361 / 2 xfailed**, mypy clean, ruff clean, **pylint 10.00/10**, nbqa ruff clean |

**Known gap, not addressed here.** Local runs are on Python **3.14**; both
workflows pin **3.11**. The type-substitution and C-extension import-order
behaviour is version-sensitive, so a green local matrix is not evidence about
3.11 and vice versa. Relevant when reading a red nightly that will not reproduce
locally. (Phase 0's M0.2 listed the 3.14-cache-vs-3.11-pin mismatch as resolved;
`.mypy_cache/3.14/` says otherwise. Left alone rather than reopened here.)

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

## Deferred — blocked on data feeds (backlog, not in this plan)

- **#12 Liquidity Risk** — needs a live options-chain feed (bid/ask, OI per
  strike).
- **#13 Delta Drift series** — needs a net-delta series from position history;
  partly unblocked by `analysis/scenarios.py`'s `scenario_grid`.
- **#14 Vega Term Exposure** — maturity-bucketed vega; `analysis/maturity.py`'s
  bucket logic (already used for theta carry) can extend.

---

## Finding → milestone index (coverage check)

| Finding | Milestone                                    | Finding     | Milestone                                    |
| ------- | -------------------------------------------- | ----------- | -------------------------------------------- |
| C1      | M1.2                                         | Mo5         | M2.3 (Dash; notebook version skipped)        |
| C2      | M1.1 (logic) + M2.3 (editor default)         | Mo6         | M1.5 + M2.1                                  |
| C3      | M1.1                                         | Mo7         | M2.3 (reactive UI; notebook version skipped) |
| C4      | M1.2                                         | Mi1         | M0.1 (`CLAUDE.md`) + Phase 3 (rest)          |
| M1      | M1.3                                         | Mi2         | Phase 3                                      |
| M2      | M2.4                                         | Mi3         | M0.2                                         |
| M3      | M1.3                                         | Mi4         | M1.4                                         |
| M4      | M1.1                                         | Mi5         | M1.3                                         |
| M5      | M2.2 (Dash-native)                           | Mi6         | M1.4                                         |
| M6      | M2.2 (Dash-native; notebook version skipped) | Negligibles | Phase 3 / batch with nearest touch           |
| M7      | Phase 3                                      | #12/#13/#14 | Deferred (data-blocked)                      |
| M8      | M2.5                                         |             |                                              |
| Mo1     | M1.2                                         |             |                                              |
| Mo2     | M1.4                                         |             |                                              |
| Mo3     | M1.4 (logic) + M2.3 (UI inputs)              |             |                                              |
| Mo4     | M1.3                                         |             |                                              |
