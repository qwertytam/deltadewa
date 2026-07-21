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

## 2. The crash state — skew-aware vol shock

From today's state ($S_0$, each leg's $\sigma_i$, $r$, $q$, valuation date $t_0$),
construct the crash state:

| Quantity | Rule | Source |
|---|---|---|
| Crash spot | $S_{\text{crash}} = S_0 (1 + m)$ | `ips.crash.scenario_move` (default **−0.25**) |
| Crash vol (per leg) | $\sigma_{i,\text{crash}} = \sigma_{i,\text{today}} + \Delta\sigma + \kappa\, w_i$ | `ips.crash.vol_shock` (**+0.15**, flat ATM base) + `ips.crash.skew_steepening` (**+0.10**, deep-OTM tail) |
| Rate / dividend | held at today's values | — |
| Time to maturity | **unchanged** ($t_0$ fixed) | — |
| Engine | European closed form (QuantLib `AnalyticEuropeanEngine` = Black–Scholes) | README: American forbidden for SPX |

**The shock is skew-aware.** Every leg gets the flat additive bump $\Delta\sigma$
(`vol_shock`, +0.15) at its own today-vol; deep-OTM puts get an *additional*
steepening on top, up to $\kappa$ (`skew_steepening`, +0.10) at the deepest tail:

$$\sigma_{i,\text{crash}} = \sigma_{i,\text{today}} + \Delta\sigma + \kappa\, w_i,
\qquad
w_i = \begin{cases}
\min\!\left(1,\; \dfrac{\ln(S_0/K_i)}{\ln(S_0/K_{\text{tail}})}\right) & K_i < S_0 \text{ (OTM put)}\\[1.2em]
0 & \text{calls, ATM/ITM puts}
\end{cases}$$

The weight $w_i$ is **linear in log-moneyness** $\ln(S_0/K_i)$, measured against
*today's* spot: $w = 0$ at ATM (and for calls / ITM puts, which do not steepen)
and $w = 1$ at $K_{\text{tail}}$, the deepest OTM put held. Setting $\kappa = 0$
recovers the flat bump exactly.

**Calibration of $\kappa$.** In a real sell-off deep-OTM index puts gain *more* IV
than ATM — the put wing steepens. In 2008 and 2020 the ≈10-delta wing steepened by
**15+ vol points** over ATM at the peak (CBOE SKEW / index-put surface history).
**+0.10** is a deliberately conservative central estimate (plausible range
+0.05…+0.20): understating the steepening errs toward *less* apparent protection,
the safe direction for a tail program. It is calibrated from the historical
episodes alone, not to any book's target band (see §5, and the M1.6 rationale in
`docs/implementation-plan.md`).

**`ips.crash.scenario_move`, `.vol_shock`, and `.skew_steepening` are each a single
source of truth** across every crash panel — the health gauge, the scenario table,
the summary ladder, and the roll-status trigger all read the same three knobs and
the same book tail, so a crash number is identical across surfaces at equal depth.
This removes the −20% / −25% split (**Mo1**); no panel carries its own constant.

---

## 3. Formula

$$V_{\text{today}} = \sum_i \text{price}\big(S_0,\,K_i,\,\sigma_i,\,r,\,q,\,T_i,\,\text{style}_i\big)\cdot q_i \cdot c_i$$

$$V_{\text{crash}} = \sum_i \text{price}\big(S_{\text{crash}},\,K_i,\,\sigma_i+\Delta\sigma+\kappa\, w_i,\,r,\,q,\,T_i,\,\text{style}_i\big)\cdot q_i \cdot c_i$$

where $q_i$ = signed contract quantity, $c_i$ = contract size, $T_i$ unchanged,
and the per-leg skew weight $w_i$ is defined in §2 ($\kappa = 0$ gives the flat bump).
Reprice via the **existing** `OptionValuation` / `BatchPricer` — do not add a new
pricer.

**Intrinsic floor** (reported as a separate, clearly-labelled column — *never* the
headline number):

$$V_{\text{crash}}^{\text{floor}} = \sum_i \max\big(\phi_i (K_i - S_{\text{crash}}),\,0\big)\cdot q_i \cdot c_i \quad (\phi=1 \text{ for puts})$$

The floor is the conservative lower bound the docstrings intended; §4 shows why it
must not be the headline (it reads 2.5× where the repriced value is 16×).

---

## 4. Worked example (reproducible — the regression anchor)

A conformant $20M book: three-rung 20/30/40%-OTM ladder, 18-month tenor,
weighted 35/40/25 by contract count, carry ≈ 1%.

**Inputs:** $S_0 = 6600$, $m = -0.25 \Rightarrow S_{\text{crash}} = 4950$;
today vol $20\%$ (flat, illustrative); $r = 4.5\%$, $q = 1.5\%$, $T = 1.5$y,
contract size 100, European puts. Crash vol is the flat base
$\Delta\sigma = +0.15$ (35% at ATM) **plus** the skew steepening $\kappa = +0.10$
weighted by log-moneyness — the tail anchor is the deepest put (3960), so
$w = \ln(6600/K)/\ln(6600/3960)$ gives crash vols **39.4% / 42.0% / 45.0%** across
the 20/30/40%-OTM rungs.

| Leg | Strike | Qty | $w$ | Crash vol | Price today | Price crash | Intrinsic (crash) | Value today | Value crash |
|---|---|---|---|---|---|---|---|---|---|
| 20% OTM | 5280 | 23 | 0.44 | 39.4% | 95.39 | 979.62 | 330.00 | \$219,392 | \$2,253,133 |
| 30% OTM | 4620 | 26 | 0.70 | 42.0% | 27.19 | 690.56 | 0.00 | \$70,696 | \$1,795,458 |
| 40% OTM | 3960 | 16 | 1.00 | 45.0% | 4.77 | 462.23 | 0.00 | \$7,627 | \$739,575 |
| **Hedge** | | | | | | | | **\$297,715** | **\$4,788,166** |

- Hedge value today **\$297,715** — 1.49% of the \$20M book, ≈ **0.99%/yr** carry
  (skew is a crash-state effect, so $V_{\text{today}}$ is unchanged from the flat
  bump).
- Hedge value in crash **\$4,788,166** (repriced) — a **16.1×** multiple.
- Intrinsic floor **\$759,000** — only **2.5×**, and it zeroes the 30% and 40% legs.

$$\text{convexity} = \frac{4{,}788{,}166 - 297{,}715}{20{,}000{,}000} = \mathbf{+22.5\%} \;\Rightarrow\; \textbf{inside the IPS +15\%…+25\% band.}$$

**Before/after (M1.6).** Under the pre-M1.6 *flat* $+0.15$ bump (every leg at 35%
crash vol) this same book read $V_{\text{crash}} = \$3{,}895{,}901$, a **13.1×**
multiple and **+18.0%** convexity. The skew-aware shock lifts the deep-OTM legs
(where the wing genuinely steepens in a crash), adding ≈4.5 pp of convexity — the
flat bump *understated* it. Both readings sit inside the +15%…+25% band.

**The intrinsic bug, for contrast:** the intrinsic-only basis gives
$(759{,}000 - 297{,}715)/20{,}000{,}000 = \mathbf{+2.3\%}$ — and the pre-M1.2 code
further netted the equity loss on top, which is how a conformant book once read as
*failing* on every row.

> Prices are Black–Scholes European; QuantLib's `AnalyticEuropeanEngine` returns the
> same values. Capture the repo engine's own outputs as golden values on the first
> correct run and confirm they sit within ~0.5% of the table above (small
> differences are day-count / calendar conventions, not errors).

---

## 5. IPS parameters

| Key | Default | Notes |
|---|---|---|
| `ips.crash.scenario_move` | `-0.25` | **Single source** for every crash panel (Mo1). |
| `ips.crash.vol_shock` | `+0.15` | Flat additive bump (ATM base). See calibration note. |
| `ips.crash.skew_steepening` | `+0.10` | Extra vol at the deep-OTM tail over ATM, linear in log-moneyness (M1.6). `0.0` recovers the flat bump. See calibration note. |
| `ips.crash.floor_reported` | `true` | Whether to surface the intrinsic-floor column. |

**Calibration note for `vol_shock`.** In 2008 and 2020, index-put implied vols
expanded roughly **+20 to +40 points** at the peak. **+15** is a deliberately
conservative, mid-cycle ATM baseline — set it to your own crash-vol view. It is a
policy input, so it belongs in the IPS, not in presentation config.

**Calibration note for `skew_steepening`.** The flat bump lifts every leg equally;
in a real crash the deep-OTM wing steepens *above* ATM. In 2008/2020 the ≈10-delta
put wing ran **15+ vol points** over ATM at the peak; **+0.10** is a conservative
central estimate (range +0.05…+0.20) derived from those episodes alone — never
tuned to a book's target band (M1.6 condition 1). Understating it errs toward less
apparent protection, the safe direction for a tail program.

---

## 6. Implementation map (what M1.2 changes)

- **`analysis/health.py`** — replace the `include_underlying` / intrinsic crash path
  with §3: hedge-only, repriced, instantaneous. Anchor the scenario at
  `ips.crash.scenario_move`.
- **`analysis/candidate.py`** (sizing + strike ladder) — reprice candidates at the
  crash state per §3 (**C4**); keep intrinsic as the floor column only.
- **`roll_status.py`** convexity trigger — no change needed; it consumes the
  corrected metric and stops firing spuriously once the number is right.
- **Mo1 single-source** — `health.py` default (`0.80`), the README figure, and
  `dashboard.yaml` all defer to `ips.crash.scenario_move`; delete the local
  constants.

---

## 7. Acceptance tests (normative)

1. **Golden values** — the §4 portfolio reprices to $V_{\text{today}} = \$297{,}715$
   and $V_{\text{crash}} = \$4{,}788{,}166$ within tolerance; convexity =
   **+22.5% ± ε** (skew-aware shock). A separate no-op test pins the flat baseline
   at $\kappa = 0$: **+18.0%**, $V_{\text{crash}} = \$3{,}895{,}901$.
2. **Band** — the canonical example (`examples/portfolios/spx_protective_put.yaml`)
   yields convexity within **+15%…+25%** at −25%. Under the flat bump it read
   **+14.27%** (just under the floor); the honestly-calibrated skew shock lifts it
   to **+16.55%**, comfortably in-band — **so no re-size is needed** (the M1.6
   "record the re-size decision either way" outcome).
3. **Hedge-only invariant** — adding or removing the equity leg does **not** change
   convexity (guards against C1 regressing).
4. **Repriced invariant** — the 30% and 40% OTM legs contribute **> 0** at −25%
   (guards against C4 regressing); the intrinsic-floor column is strictly less than
   the repriced value for any strike beyond the crash move.
5. **Single-source** — changing `ips.crash.scenario_move`, `.vol_shock`, or
   `.skew_steepening` moves the health gauge, the scenario table, the summary
   ladder, and the roll trigger together (identical at equal depth).

---

## 8. Known simplifications (documented, not defects)

- **Skew steepening — implemented (M1.6).** The deep-OTM wing now steepens above
  ATM via `ips.crash.skew_steepening` (§2), so the shock no longer understates
  convexity on the lowest strikes. Two limitations remain in the model:
  - **Single-slope, cross-sectional.** The steepening is one linear-in-log-moneyness
    slope $\kappa$ anchored at the deepest held put; it does not model the *term*
    structure of skew (how the slope varies with tenor) — a natural next refinement.
  - **Book-convexity surfaces only.** The gauge, roll trigger, summary ladder, and
    scenario table read the skew shock; the **sizing / strike-ladder / candidate**
    path stays on the flat bump for now, because pricing a *standalone* candidate as
    its own tail would over-apply the steepening and undersize the hedge. Wiring it
    correctly needs a per-strike skew anchor (deferred, tracked follow-up).
- **Rates / dividends held constant.** Rates typically fall in a crash; the effect
  is second-order for long puts and is out of scope for this baseline.
- **Single instantaneous horizon.** The crash is modelled as one jump at $t_0$; the
  term structure of a crash path is not modelled here (that is the Monte Carlo
  surface's job — see M3).
