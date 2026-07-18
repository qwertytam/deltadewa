# Appendix — Crash Repricing Methodology

*Belongs at `docs/repricing-methodology.md`; cross-reference it from the handbook's
Part VI crash-convexity definition (≈ line 1628).*

This appendix closes the ambiguity the handbook's Part VI left open: it defines
**exactly** how the crash hedge value is repriced. It is **normative** — the
implementation in `analysis/health.py` and `analysis/candidate.py` must follow it,
and the worked example in §4 is the regression anchor. It resolves review findings
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
| Crash spot | $S_{\text{crash}} = S_0 (1 + m)$ | `ips.crash.scenario_move` (default **−0.25**) |
| Crash vol (per leg) | $\sigma_{i,\text{crash}} = \sigma_{i,\text{today}} + \Delta\sigma$ | `ips.crash.vol_shock` (default **+0.15**, flat & additive) |
| Rate / dividend | held at today's values | — |
| Time to maturity | **unchanged** ($t_0$ fixed) | — |
| Engine | European closed form (QuantLib `AnalyticEuropeanEngine` = Black–Scholes) | README: American forbidden for SPX |

The vol shock is **flat**: the same additive bump is applied to every leg's own
today-vol. This is deliberately the simplest defensible convention (one number, one
IPS knob, fully transparent). Its known limitation — no skew steepening — is
documented in §8 and is *conservative* (it understates convexity on the lowest
strikes).

**`ips.crash.scenario_move` is the single source of truth for the crash scenario**
across every panel — the health gauge, the scenario table, and the roll-status
trigger all read it. This removes the −20% / −25% split (**Mo1**); no panel carries
its own crash constant.

---

## 3. Formula

$$V_{\text{today}} = \sum_i \text{price}\big(S_0,\,K_i,\,\sigma_i,\,r,\,q,\,T_i,\,\text{style}_i\big)\cdot q_i \cdot c_i$$

$$V_{\text{crash}} = \sum_i \text{price}\big(S_{\text{crash}},\,K_i,\,\sigma_i+\Delta\sigma,\,r,\,q,\,T_i,\,\text{style}_i\big)\cdot q_i \cdot c_i$$

where $q_i$ = signed contract quantity, $c_i$ = contract size, $T_i$ unchanged.
Reprice via the **existing** `OptionValuation` / `BatchPricer` — do not add a new
pricer.

**Intrinsic floor** (reported as a separate, clearly-labelled column — *never* the
headline number):

$$V_{\text{crash}}^{\text{floor}} = \sum_i \max\big(\phi_i (K_i - S_{\text{crash}}),\,0\big)\cdot q_i \cdot c_i \quad (\phi=1 \text{ for puts})$$

The floor is the conservative lower bound the docstrings intended; §4 shows why it
must not be the headline (it reads 2.5× where the repriced value is 13×).

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

## 5. IPS parameters to add

| Key | Default | Notes |
|---|---|---|
| `ips.crash.scenario_move` | `-0.25` | **Single source** for every crash panel (Mo1). |
| `ips.crash.vol_shock` | `+0.15` | Flat additive bump. See calibration note. |
| `ips.crash.floor_reported` | `true` | Whether to surface the intrinsic-floor column. |

**Calibration note for `vol_shock`.** In 2008 and 2020, index-put implied vols
expanded roughly **+20 to +40 points** at the peak. **+15** is a deliberately
conservative, mid-cycle baseline — set it to your own crash-vol view. It is a
policy input, so it belongs in the IPS, not in presentation config.

---

## 6. Implementation map (what M1.2 changes)

- **`analysis/health.py`** — replace the `include_underlying` / intrinsic crash path
  with §3: hedge-only, repriced, instantaneous. Anchor the scenario at
  `ips.crash.scenario_move`.
- **`analysis/candidate.py`** (sizing + strike ladder) — reprice candidates at the
  crash state per §3 (**C4**); keep intrinsic as the floor column only.
- **`roll_status.py`** convexity trigger — consumes the corrected metric **and**
  must pass the IPS vol shock (`convexity.crash_vol_shock`) so its convexity
  matches the health gauge. `calculate_crash_convexity_pct` makes `crash_vol_shock`
  a **required** argument, so the trigger can no longer fall back to a spot-only
  (`vol_shock=0`) reading — that understated convexity and biased the roll toward
  firing. *(Corrects the earlier "no change needed": it was wrong about the
  vol_shock argument.)*
- **Mo1 single-source** — `health.py` default (`0.80`), the README figure, and
  `dashboard.yaml` all defer to `ips.crash.scenario_move`; delete the local
  constants.

---

## 7. Acceptance tests (normative)

1. **Golden values** — the §4 portfolio reprices to $V_{\text{today}}$ and
   $V_{\text{crash}}$ within tolerance; convexity = **+18.0% ± ε**.
2. **Band** — the canonical example (`examples/portfolios/spx_protective_put.yaml`)
   yields convexity within **+15%…+25%** at −25%; `meets_target` is `True` on every
   scenario row.
3. **Hedge-only invariant** — adding or removing the equity leg does **not** change
   convexity (guards against C1 regressing).
4. **Repriced invariant** — the 30% and 40% OTM legs contribute **> 0** at −25%
   (guards against C4 regressing); the intrinsic-floor column is strictly less than
   the repriced value for any strike beyond the crash move.
5. **Single-source** — changing `ips.crash.scenario_move` moves the health gauge,
   the scenario table, and the roll trigger together.

---

## 8. Known simplifications (documented, not defects)

- **No skew steepening.** A flat bump gives every leg the same +Δσ; in a real crash
  the deep-OTM puts gain *more* IV than ATM. This **understates** convexity on the
  lowest strikes → conservative. A skew-aware shock (`ips.crash.skew_steepening`) is
  the natural next refinement.
- **Rates / dividends held constant.** Rates typically fall in a crash; the effect
  is second-order for long puts and is out of scope for the flat baseline.
- **Single instantaneous horizon.** The crash is modelled as one jump at $t_0$; the
  term structure of a crash path is not modelled here (that is the Monte Carlo
  surface's job — see M3).
