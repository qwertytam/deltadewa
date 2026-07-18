# Appendix — Crash Repricing Methodology

*Belongs at `docs/repricing-methodology.md`; cross-reference it from the handbook's
Part VI crash-convexity definition (≈ line 1628).*

This appendix closes the ambiguity the handbook's Part VI left open: it defines
**exactly** how the crash hedge value is repriced. It is **normative** — the
implementation — the shared `analysis/crash_repricing.py` helper and its consumers
(`analysis/health.py`, `analysis/crash_payoff.py`, `analysis/candidate.py`,
`widgets/summary.py`, and `roll_status.py`) — must follow it, and the worked
example in §4 is the regression anchor. It resolves review findings
**C1, C4, and Mo1**.

---

## 1. Definition (restated precisely)

$$\text{crash convexity} = \frac{V_{\text{crash}} - V_{\text{today}}}{P_{\text{today}}}$$

Three properties the current code violates, now made explicit:

- **Hedge-only.** $V$ is the value of the **option legs only**. The underlying /
  equity position is **excluded** from both terms. *(C1: the metric must not net
  the equity loss into convexity — that produced the chronic "every scenario
  fails" reading.)*
- **Repriced, not intrinsic, not expiry.** $V_{\text{crash}}$ is the legs
  **repriced** at the crash spot and crash vol — full option value including time
  value. It is **not** intrinsic value and **not** value at expiry. *(C1/C4: the
  intrinsic basis zeroes every strike more than the crash-move OTM.)*
- **Instantaneous.** The crash is a jump **at the current valuation date**.
  Time-to-maturity is **unchanged**; the valuation date does **not** advance.

$P_{\text{today}}$ is the protected portfolio value today — the reference the IPS
band (+15% … +25% at −25%) is stated against. The numerator is the change in
**hedge** value; the denominator is the **book**.

---

## 2. The crash state — flat vol-bump convention

From today's state ($S_0$, each leg's $\sigma_i$, $r$, $q$, valuation date $t_0$),
construct the crash state:

| Quantity | Rule | Source |
|---|---|---|
| Crash spot | $S_{\text{crash}} = S_0 (1 + m)$ | `convexity.crash_scenario_pct` (default **−25.0** %, i.e. $m=-0.25$) |
| Crash vol (per leg) | $\sigma_{i,\text{crash}} = \sigma_{i,\text{today}} + \Delta\sigma$ | `convexity.crash_vol_shock` (default **+0.15**, flat & additive) |
| Rate / dividend | held at today's values | — |
| Time to maturity | **unchanged** ($t_0$ fixed) | — |
| Engine | European closed form (QuantLib `AnalyticEuropeanEngine` = Black–Scholes) | README: American forbidden for SPX |

The vol shock is **flat**: the same additive bump is applied to every leg's own
today-vol. This is deliberately the simplest defensible convention (one number, one
IPS knob, fully transparent). Its known limitation — no skew steepening — is
documented in §8 and is *conservative* (it understates convexity on the lowest
strikes).

**`convexity.crash_scenario_pct` is the single source of truth for the crash
scenario** across every panel — the health gauge, the scenario table, the summary
ladder, and the roll-status trigger all read it. This removes the −20% / −25%
split (**Mo1**); no panel carries its own crash constant.

---

## 3. Formula

$$V_{\text{today}} = \sum_i \text{price}\big(S_0,\,K_i,\,\sigma_i,\,r,\,q,\,T_i,\,\text{style}_i\big)\cdot q_i \cdot c_i$$

$$V_{\text{crash}} = \sum_i \text{price}\big(S_{\text{crash}},\,K_i,\,\sigma_i+\Delta\sigma,\,r,\,q,\,T_i,\,\text{style}_i\big)\cdot q_i \cdot c_i$$

where $q_i$ = signed contract quantity, $c_i$ = contract size, $T_i$ unchanged.
Reprice through the **existing** `OptionValuation` engine — do not add a new pricer.

**Shared, depth-parameterized helper.** All crash surfaces reprice through one
module, `analysis/crash_repricing.py`, so they share a single basis:

- `crash_hedge_value(portfolio, *, crash_move, vol_shock, positions=None)` →
  $V_{\text{crash}}$: the hedge-only repriced value at crash spot
  `spot * (1 + crash_move)` with per-leg vol `σ_i + vol_shock`. `positions=None`
  prices the whole book; pass a subset (e.g. a single candidate leg) to value part
  of it.
- `hedge_value(portfolio, *, positions=None)` → $V_{\text{today}}$ — the same
  helper at `crash_move=0, vol_shock=0`.
- `crash_convexity_pct(portfolio, *, crash_move, vol_shock)` → the §1 ratio
  `(V_crash − V_today) / P_today × 100`, with `P_today` the protected book
  `abs(underlying_quantity * spot)`.

`crash_move` and `vol_shock` are signed **decimals** (e.g. `-0.25`, `+0.15`); the
IPS stores the move as a **percent** (`crash_scenario_pct = -25.0`) and callers
divide by 100 at the boundary.

**Intrinsic floor** — `crash_intrinsic_floor(portfolio, *, crash_move,
positions=None)`, reported as a separate, clearly-labelled column, *never* the
headline number:

$$V_{\text{crash}}^{\text{floor}} = \sum_i \max\big(\phi_i (K_i - S_{\text{crash}}),\,0\big)\cdot q_i \cdot c_i \quad (\phi=1 \text{ for puts})$$

**This undiscounted intrinsic is *not* a universal lower bound on
$V_{\text{crash}}$.** For a European option the true no-arbitrage floor is
*discounted* intrinsic; a deep-ITM, short-dated European put can reprice slightly
*below* undiscounted intrinsic (measured: repriced 99,894 vs floor 100,000 at
3m / −25%). The floor column is a **conservative reference for the deep-OTM tail
strikes this program actually buys** — where time value dominates and the repriced
value sits far above it (§4: floor ~2.5× vs repriced ~13×) — not a mathematical
bound in every case.

---

## 4. Worked example (reproducible — the regression anchor)

A conformant $20M book: three-rung 20/30/40%-OTM ladder, 18-month tenor,
weighted 35/40/25 by contract count, carry ≈ 1%.

**Inputs:** $S_0 = 6600$, $m = -0.25 \Rightarrow S_{\text{crash}} = 4950$;
today vol $20\%$ (flat, illustrative), $\Delta\sigma = +0.15 \Rightarrow$ crash vol
$35\%$; $r = 4.5\%$, $q = 1.5\%$, $T = 1.5$y, contract size 100, European puts.

| Leg | Strike | Qty | Price today | Price crash | Intrinsic (crash) | Value today | Value crash |
|---|---|---|---|---|---|---|---|
| 20% OTM | 5280 | 23 | 95.39 | 878.08 | 330.00 | \$219,392 | \$2,019,573 |
| 30% OTM | 4620 | 26 | 27.19 | 543.28 | 0.00 | \$70,696 | \$1,412,536 |
| 40% OTM | 3960 | 16 | 4.77 | 289.87 | 0.00 | \$7,627 | \$463,792 |
| **Hedge** | | | | | | **\$297,715** | **\$3,895,901** |

- Hedge value today **\$297,715** — 1.49% of the \$20M book, ≈ **0.99%/yr** carry.
- Hedge value in crash **\$3,895,901** (repriced) — a **13.1×** multiple.
- Intrinsic floor **\$759,000** — only **2.5×**, and it zeroes the 30% and 40% legs.

$$\text{convexity} = \frac{3{,}895{,}901 - 297{,}715}{20{,}000{,}000} = \mathbf{+18.0\%} \;\Rightarrow\; \textbf{inside the IPS +15\%…+25\% band.}$$

**The bug, for contrast:** the intrinsic-only basis gives
$(759{,}000 - 297{,}715)/20{,}000{,}000 = \mathbf{+2.3\%}$ — and the current code
further nets the equity loss on top, which is how a conformant book reads as
*failing* on every row.

> Prices are Black–Scholes European; QuantLib's `AnalyticEuropeanEngine` returns the
> same values. Capture the repo engine's own outputs as golden values on the first
> correct run and confirm they sit within ~0.5% of the table above (small
> differences are day-count / calendar conventions, not errors).

---

## 5. IPS parameters

All three crash knobs live in the **`convexity:`** section of `ips.yaml`,
alongside the existing target band — see `examples/ips/ips_default.yaml`. The
crash *move* was **already** present (`crash_scenario_pct`); M1.2 added only the
two repricing knobs, co-located so the whole crash basis is one block.

| Key (under `convexity:`) | Default | Status | Notes |
|---|---|---|---|
| `crash_scenario_pct` | `-25.0` | pre-existing | Signed **percent**. Single source for every crash panel (Mo1). |
| `crash_vol_shock` | `0.15` | added (M1.2) | Flat additive vol bump (decimal). See calibration note. |
| `crash_floor_reported` | `true` | added (M1.2) | Whether to surface the intrinsic-floor column. |

**Calibration note for `crash_vol_shock`.** In 2008 and 2020, index-put implied vols
expanded roughly **+20 to +40 points** at the peak. **+15** is a deliberately
conservative, mid-cycle baseline — set it to your own crash-vol view. It is a
policy input, so it belongs in the IPS, not in presentation config.

---

## 6. Implementation map (what M1.2 changed)

- **`analysis/crash_repricing.py`** (new) — the shared, depth-parameterized helper
  (§3): `crash_hedge_value` / `hedge_value` / `crash_convexity_pct` /
  `crash_intrinsic_floor`. Every crash surface below reprices through it, so they
  all share one basis.
- **`analysis/health.py`** — `calculate_crash_convexity_pct` replaced the
  `include_underlying` / intrinsic crash path with §3 (hedge-only, repriced,
  instantaneous), delegating to `crash_repricing`. Anchored at
  `convexity.crash_scenario_pct`.
- **`analysis/crash_payoff.py`** — the headline **payoff ratio** now divides the
  repriced $V_{\text{crash}}$ (via `crash_hedge_value`) rather than intrinsic;
  intrinsic is kept only as a separate labelled floor, and the scenario table's
  `meets_target` reads the repriced convexity.
- **`widgets/summary.py`** — the Tier-1 **crash-convexity ladder**
  (`NetHedgeSummary`) reprices through the shared helper, so the summary ladder
  agrees with the health gauge at the policy depth.
- **`analysis/candidate.py`** (sizing + strike ladder) — reprice candidates at the
  crash state per §3 (**C4**); keep intrinsic as the floor column only.
- **`roll_status.py`** convexity trigger — consumes the corrected metric **and**
  must pass the IPS vol shock (`convexity.crash_vol_shock`) so its convexity
  matches the health gauge. `calculate_crash_convexity_pct` makes `crash_vol_shock`
  a **required** argument, so the trigger can no longer fall back to a spot-only
  (`vol_shock=0`) reading — that understated convexity and biased the roll toward
  firing. *(Corrects the earlier "no change needed": it was wrong about the
  vol_shock argument.)*
- **Mo1 single-source** — the old per-panel crash constants (`health.py`'s local
  default, the README figure, `dashboard.yaml`) all defer to
  `convexity.crash_scenario_pct`; the local constants are deleted.

---

## 7. Acceptance tests (normative)

1. **Golden values** — the §4 portfolio reprices to $V_{\text{today}}$ and
   $V_{\text{crash}}$ within tolerance; convexity = **+18.0% ± ε**.
2. **Band** — the **§4 \$20M golden fixture** yields convexity within
   **+15%…+25%** at −25% with `meets_target = True`; the hard band assertion lives
   there. The shipped example book
   (`examples/portfolios/spx_protective_put.yaml`) is **not** band-asserted — it
   measures **+14.28%** (~0.7pp under the +15% floor, a sizing item tracked as
   M1.4/Mo3) and carries **invariant** checks only (hedge-only, repriced,
   ladder == gauge, roll == gauge).
3. **Hedge-only invariant** — adding or removing the equity leg does **not** change
   convexity (guards against C1 regressing).
4. **Repriced invariant** — the 30% and 40% OTM legs contribute **> 0** at −25%
   (guards against C4 regressing); the intrinsic-floor column is strictly less than
   the repriced value for any strike beyond the crash move.
5. **Single-source** — changing `convexity.crash_scenario_pct` moves the health
   gauge, the scenario table, the summary ladder, and the roll trigger together.

---

## 8. Known simplifications (documented, not defects)

- **No skew steepening.** A flat bump gives every leg the same +Δσ; in a real crash
  the deep-OTM puts gain *more* IV than ATM. This **understates** convexity on the
  lowest strikes → conservative. A skew-aware shock (`convexity.skew_steepening`) is
  the natural next refinement.
- **Intrinsic floor is a conservative reference, not a strict bound.** The floor
  column uses *undiscounted* intrinsic, which is **not** a no-arbitrage lower bound
  for European options — the true floor is *discounted* intrinsic, and a deep-ITM
  short-dated European put can reprice just below undiscounted intrinsic (measured:
  99,894 vs 100,000 at 3m / −25%). For the deep-OTM tail strikes this program buys
  the gap is immaterial (repriced sits far above intrinsic), so the column remains a
  useful conservative reference; see §3.
- **Rates / dividends held constant.** Rates typically fall in a crash; the effect
  is second-order for long puts and is out of scope for the flat baseline.
- **Single instantaneous horizon.** The crash is modelled as one jump at $t_0$; the
  term structure of a crash path is not modelled here (that is the Monte Carlo
  surface's job — see M3).
