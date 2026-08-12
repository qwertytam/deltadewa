# Part X coverage audit

Maps every item in [Handbook Part X — Institutional Hedge Dashboards](hedging%20handbook.md#part-x--institutional-hedge-dashboards)
to its implementation in this codebase.

**Updated 2026-08-10**, when planning the notebook retirement traced the four
remaining Jupyter-only health gauges and found one — the convexity cliff — with
no Dash surface and no recorded decision to drop it. It is now on `/design`;
see [The notebook-retirement audit](#the-notebook-retirement-audit) for the
other three, two of which needed nothing.

**Updated 2026-08-07, after M2.8.** The 2026-08-06 re-audit found five
coverage regressions from the M2.4/M2.5 Dash rebuild — panels the notebooks
had that the Dash pages did not, with no decision recorded anywhere to drop
them. M2.7 closed all five, and also surfaced a policy leak of its own
(the entry-timing tree's VIX thresholds, hardcoded rather than sourced
from `ips.yaml`, went from dormant to user-visible the moment M2.7 put the
matrix on a page). M2.8 closed the two remaining surfacing gaps the
re-audit had found (#13, #14) and fixed that leak, leaving #12 as the only
item still genuinely blocked. This document now records the resulting
state, plus the retirements that *were* deliberate, so the next audit can
tell the three (regression, leak, genuine gap) apart.

The regressions themselves are listed in [Closed by M2.7](#closed-by-m27)
rather than deleted: an audit that erases what it found leaves the next one
no way to know whether an item was never built, was dropped on purpose, or
was lost.

## The current surfaces

Three.

**`/monitor`** (`deltadewa/app/pages/monitor.py`) — the partner's read-mostly
book review. Three sections plus a collapsed table:

- *Crash scenario* — the scenario explorer: three dials (spot shock, vol
  shock, underlying quantity), the payoff curve, the scenario numbers
  (`_scenario_numbers`), and the **cost panel** (`_cost_panel`), which since
  M2.7 also carries the hedge-efficiency sentence.
- *Decisions* — per-position roll verdicts with reasons and convexity band
  bars, plus the monetization schedule at the current mark.
- *Position detail* — a collapsed `<details>` per-leg ledger.

**`/design`** (`deltadewa/app/pages/design.py`) — the operator's workbench.
Three zones:

- *BOOK* — position editor, underlying quantity with its **net-delta
  readout**, guarded import/export.
- *PLANNING* — market environment, sizing (with the **vega sufficiency**
  block), strike ladder, roll planner, **hedge rebalance triggers**,
  **delta drift** (M2.8), **convexity cliff**, monetization. Most price the
  crash-skew (IPS anchor) basis; those that do not carry their own basis chip
  (see [Basis chips](#basis-chips)).
- *EXPLORATION* — spot×vol heatmap, time×price heatmap, Monte Carlo
  distribution, **vega term exposure** (M2.8). The three stress surfaces
  are on the proportional-vol (GBM) basis and carry a **metric dropdown**
  built from `visualization.stress_charts_plotly.STRESS_METRICS` (`pnl`,
  `value`, `net_delta`, `delta`, `gamma`, `vega`, `theta`, `rho`); vega term
  exposure is a structural read of today's book instead, so it carries its
  own basis chip rather than the zone's default.

**The weekly digest** (`deltadewa/reporting/weekly_report.py` →
`program_report.py`, shipped in M2.6) — an emailed report, not a page. It
carries the Part VII board/IC report, the decision matrix + entry-timing
verdict, and a `MarketContextSection` holding `vix`, `regime_label`,
`skew_percentile`, and `hedge_cost_verdict`.

Shared **chrome** (`deltadewa/app/chrome.py`) renders the as-of stamp and the
STATIC/STALE/UNAVAILABLE provenance banner above both pages. It reads
`MarketEnvironment.data_quality`/`.as_of` only — never the environment's
metric values.

### Basis chips

PLANNING is no longer uniformly crash-priced, and the zone's intro sentence
says so. Four bases now appear on the page (a fifth, `book Greeks`, also
appears once in EXPLORATION), and every panel that departs from its zone's
default is chipped:

| Chip | Panels | What it means |
| --- | --- | --- |
| `basis: crash-skew (IPS anchor)` | Sizing, strike ladder, roll planner, monetization | Reprices the book at the IPS crash. Agrees with `/monitor` to the cent. |
| `basis: live market data` | Market environment | Reprices nothing — reads the feed. |
| `basis: book Greeks at today's market` | Hedge rebalance triggers (PLANNING); vega term exposure (EXPLORATION) | Reads the book's Greeks unshocked. |
| `basis: spot -5%, flat vol (not the IPS crash)` | Delta drift | Reprices at the handbook's own fixed §13 shock, distinct from the IPS crash anchor every other PLANNING panel prices. |
| `basis: position maturities (nothing priced)` | Convexity cliff | Touches no market input at all — compares each long put's maturity against the valuation date. Cannot honestly carry even the book-Greeks chip. |

## Status legend

| Status | Meaning |
| --- | --- |
| **PRESENT** | On a current dashboard surface, named below. |
| **MOVED** | Surfaced, but on a different surface than the notebooks had it. |
| **PARTIAL** | Some of the item is surfaced; the missing part is named. |
| **RETIRED** | Deliberately removed, with the rationale recorded. |
| **NEVER BUILT** | No implementation has ever existed — not a regression. |
| **OUTSTANDING** | Not built; blocked on data that does not exist. |

## Coverage table

| # | Part X item | Tier | Current surface | Analysis backing | Status |
| --- | --- | --- | --- | --- | --- |
| — | Decision matrix + entry-timing tree | pre-Tier | `/design` PLANNING — *Market environment*; also the weekly digest | `analysis/decision_matrix.py` (`decision_matrix`, `entry_timing_tree`) | **PRESENT** (M2.7; VIX thresholds sourced from policy in M2.8) |
| 1 | Crash Convexity Chart | 1 | `/monitor` — *Crash scenario*, `payoff-curve` | `analysis/monitor_scenario.build_scenario_curve`, `visualization/crash_charts_plotly.plot_scenario_curve` | **PRESENT** |
| 2 | Crash Scenario Table & Payoff Ratio | 1 | `/monitor` — *Crash scenario*, `_scenario_numbers` (offset ratio) | `analysis/monitor_scenario.build_scenario` | **PRESENT** (form changed — see [Conscious retirements](#conscious-retirements)) |
| 3 | Theta Carry (Insurance Cost) | 1 | `/monitor` — *Crash scenario*, `_cost_panel`; also digest `CostSection` | `analysis/carry.carry_vs_budget` via `monitor_scenario` | **PRESENT** |
| 4 | Vega Sufficiency Gauge | 1 | `/design` PLANNING — *Sizing workbench*, `_vega_sufficiency_block` | `analysis/health.HealthMixin.calculate_vega_sufficiency_pct`; band from `IpsVega` | **PRESENT** (M2.7) |
| 5 | Carry vs. Convexity Chart | 1 | `/monitor` — `_cost_panel`, `_efficiency_sentence`. Both axes separately: cost panel and *Decisions* band bars | `analysis/hedge_efficiency.hedge_efficiency`, on `ScenarioResult.efficiency` | **PRESENT** (M2.7) |
| 6 | Volatility Regime Indicator | 2 | `/design` PLANNING — *Market environment*; also the digest | `analysis/market_environment.classify_vix_regime` | **PRESENT** (M2.7) |
| 7 | Skew Percentile Gauge | 2 | `/design` PLANNING — *Market environment*; also the digest | `analysis/market_environment` (`skew_percentile`), `marketdata` `get_skew_percentile` | **PRESENT** (M2.7) |
| 8 | Forward Variance Level | 2 | `/design` PLANNING — *Market environment* | `analysis/market_environment.forward_vol` → `MarketEnvironment.forward_vol_front_3m` | **PRESENT** (M2.7) |
| 9 | Skew Exposure / Beta | 3 | `/design` EXPLORATION — `vega` heatmap metric | `visualization/stress_charts_plotly.STRESS_METRICS["vega"]` | **PARTIAL** — the ∂V/∂skew scalar is **NEVER BUILT**, see below |
| 10 | Net Delta Exposure | 3 | `/design` BOOK — `_net_delta_readout`; grid form via the `net_delta` heatmap metric | `portfolio/greeks.net_delta` via `summary_stats()` | **PRESENT** (M2.7) |
| 11 | Hedge Rebalance Triggers | 3 | `/monitor` — *Decisions*; `/design` PLANNING — *Roll planner*, **Hedge rebalance triggers**, *Monetization* | `analysis/roll_status.evaluate_roll_status`, `analysis/hedge_triggers.evaluate_hedge_trigger_set`, `analysis/monetization`, `analysis/roll_planner` | **PRESENT** — both trigger sets now live (see note) |
| 12 | Liquidity Risk | 4 | none | none — needs per-strike bid/ask and open interest | **OUTSTANDING** — genuinely data-blocked |
| 13 | Delta Drift | 4 | `/design` PLANNING — **Delta drift** | `analysis/scenarios.ScenariosMixin.calculate_delta_drift` | **PRESENT** (M2.8) |
| 14 | Vega Term Exposure | 4 | `/design` EXPLORATION — **Vega term exposure** | `analysis/maturity.MaturityMixin.calculate_vega_by_maturity` | **PRESENT** (M2.8) |
| 15 | Hedge Efficiency Ratio | 4 | `/monitor` `_cost_panel`; digest `ProtectionSection.payoff_ratio` | Same function as #5 — see below | **PRESENT** (M2.7) |
| — | Part VII Board/IC report | — | Weekly digest email | `reporting/program_report.py` | **RETIRED** from the dashboard — see [Conscious retirements](#conscious-retirements) |
| — | Time to Convexity Cliff | — | `/design` PLANNING — **Convexity cliff** | `analysis/health.HealthMixin.calculate_convexity_cliff_days`; lines from `IpsConvexity.cliff_*` | **PRESENT** (notebook-retirement audit) |
| — | Sizing workbench | — | `/design` PLANNING | `analysis/sizing.size_hedge` | **PRESENT** |
| — | Strike ladder builder | — | `/design` PLANNING | `analysis/strike_ladder.build_strike_ladder` | **PRESENT** |
| — | Roll planner | — | `/design` PLANNING — *Roll planner* | `analysis/roll_status.evaluate_roll_status` — **not** `roll_planner` | **PARTIAL** — the panel is the roll *table*; `analysis/roll_planner.build_roll_plan` has no consumer. See [Stage 4.3](#stage-43--the-notebook-retirement) |
| — | Monetization planner | — | `/design` PLANNING + `/monitor` *Decisions* | `analysis/monetization.build_monetization_plan` | **PRESENT** |

**Note on #5 and #15.** These are **one number**, not two. The handbook
states the ratio in dollars at `hedging handbook.md:2032` (#15) and in
percentages at `:4337`/`:2036` (#5); in this codebase `crash_convexity_pct`
and `carry_vs_budget` both normalize by `abs(underlying_quantity * spot)`, so
the normalizer cancels and the two forms are identical. One function,
`analysis/hedge_efficiency.hedge_efficiency`, serves both, and
`tests/test_analysis/test_monitor_scenario.py` pins the identity rather than
leaving it as a docstring claim. The handbook's own example dashboard
(`:4131-4156`) prints 7.5 and 6.3 as if they differed; on a common
normalizer they cannot.

**Note on #11.** Two *distinct* trigger sets are now live and are
deliberately not merged. `roll_status.py` judges each tranche — "should this
position be replaced" (time, convexity, strike drift). `hedge_triggers.py`
judges the book as a whole — "is the book still hedged the way policy says"
(delta drift, expiry, theta cost, gamma drift). They have different
thresholds and answer different questions; a combined table would imply one
verdict where there are two. Both render their per-trigger reasoning.

## Closed by M2.7

The five regressions the 2026-08-06 re-audit found, and what closed each.

| Regression | Was | Now |
| --- | --- | --- |
| **#4 Vega Sufficiency** — the only Tier-1 item with no surface anywhere | `calculate_vega_sufficiency_pct` intact and tested, reachable only via `calculate_health_metrics` → Jupyter | `/design` sizing panel. Band promoted from `dashboard.yaml` to a new `IpsVega` section, then recalibrated by #241 because the promoted numbers were unreachable — see [Where the vega band went](#where-the-vega-band-went) |
| **#8 Forward Variance** — computed every request, then discarded | `MarketEnvironment.forward_vol_front_3m` computed on every `/monitor` and `/design` request and never read | `/design` *Market environment*, as a level with no band |
| **#6 / #7** — weekly and by email only | Digest `MarketContextSection` only | `/design` *Market environment*, banded against the IPS. Still in the digest too |
| **#5 / #15** — the ratio existed nowhere in the codebase | Both axes surfaced separately; the division computed on no surface, in no module | `analysis/hedge_efficiency.py` + `/monitor`'s cost panel |
| **#10** — the scalar readout | Grid form reachable via the heatmap metric dropdown; the notebooks' Net Hedge Summary scalar lost | `/design` BOOK, beside the underlying quantity |

Also closed, though it was tracked separately as engine-code-with-no-consumer
rather than as a regression: **`analysis/hedge_triggers.py` had no functional
consumer at all.** M2.7 extracted a pure `evaluate_hedge_trigger_set` from
the console-printing `evaluate_hedge_triggers` and gave it a `/design` panel.
The console form's signature and output are unchanged.

### Where the vega band went

The band for #4 was the one open question in the re-audit's recommendation:
its thresholds were presentation config (`config/dashboard.yaml`, mirrored at
`widgets/health_dashboard.py`), not IPS policy. M2.7 promoted them, on the
grounds that "is the hedge big enough to answer a vol spike" is a mandate
question of the same class as the convexity band — and that reading policy
from presentation config is the Mo2 leak M1.4 closed.

The promotion was right, but **the numbers it carried over were not** — see
issue #241, which corrected them. The cautionary tale of the whole exercise:

- M2.7 carried the defaults over verbatim from `dashboard.yaml`'s gauge
  (`max_val: 20` → `sufficiency_min_pct`, `end: 50` → `sufficiency_max_pct`)
  so that moving the metric would not silently change what a reading means.
  But that gauge is a **signed, symmetric display axis** (−50…+50, green
  above +20, nothing bad above it), not a band: `end: 50` was the axis bound.
- The resulting 20–50 band was **unreachable**. The metric divides by total
  portfolio value — options *plus* underlying — and on a tail hedge the
  equity leg dominates that denominator, so the shipped books price at
  **+1.8% to +2.7%** (`spx_tail_20m` +2.70%, `spx_protective_put` +2.29%).
  No denominator rescues it: option-book-relative they read ~1200–1800%.
  `/design` therefore said "outside band" for every book in the repo, with
  the `band_bar` needle pinned off the left edge, for the life of M2.7.
- #241 recalibrated the band to **1.5–4.0**, bracketing the canonical book,
  and `tests/test_ips_config.py` now pins the *scale* — retune the values
  freely, but a band the canonical book cannot sit inside is a bug.
- `dashboard.yaml` **keeps** its `vega_sufficiency` block, because the
  Jupyter gauge still reads it — but it is now annotated as an axis, not a
  band. It is also mis-scaled for the metric it plots (a +2.7% reading sits
  on the midpoint of a ±50 axis); rescaling it is a `widgets/` change on the
  surface #242 retires, so it was left alone.

**The lesson for the next promotion.** Gauge geometry and a policy band are
not the same kind of number even when they sit under the same key name.
Before carrying a threshold from presentation to policy, price a real book
and confirm the reading lands inside the band — "verbatim" preserves the
digits, not the meaning.

## Conscious retirements

Decisions, not leftovers. Recorded so they are not re-flagged as regressions.

**Part VII board/IC report — retired from the dashboard, kept as a
deliverable.** It was a `/monitor` notebook panel; M2.6 made it a scheduled,
emailed report (`reporting/weekly_report.py`). *Rationale:* an on-demand copy
on `/monitor` would duplicate a report that now arrives on its own, and the
partner's page is meant to be read, not exported from. The report itself was
not lost — it gained a delivery mechanism.

**#2's discrete scenario table — retired in favour of the curve.** The
handbook shows a six-row SPX-move table; `/monitor` renders a continuous
payoff curve over −50%…+10% with a live marker. *Rationale:* the curve is a
superset of the table, and a second tabular copy of the same information
works against `/monitor` staying legible cold. The tabular engine
(`analysis/crash_payoff.crash_scenario_table`, `crash_payoff_ratio`) is
**kept and still tested**, with no production consumer — kept rather than
restored, and kept rather than deleted, because the digest's payoff ratio
descends from the same code path.

**The hedge-success gauge — omitted, per M2.4 finding M2.** A permanently
neutral gauge is worse than no gauge. *Rationale:* it needs realized-carry
tracking, which needs the position-history layer
[#70](https://github.com/qwertytam/deltadewa/issues/70) owns; until then any
value it shows is a proxy. `analysis/health.py` records this at the function.

**`/monitor` is not a gauge wall.** The principle behind every
`/design`-first placement in M2.7: `/monitor` answers three questions (what
does this cost, what do we get, what are we doing about it) for a
non-technical reader returning after eight weeks. Metrics that are inputs to
an *operator's* decision belong on `/design` even when the handbook files
them under a higher tier. This is why #4, #6, #7, #8 and #10 went to
`/design` and only #5/#15 went to `/monitor` — and why #5/#15 is one
plain-language sentence there, with no big number and no band bar of its
own. A test pins that.

## Never built

**#9's skew-beta scalar.** No `∂V/∂skew` function has ever existed in this
codebase — not in the notebooks, not in `widgets/`, not in `analysis/`. The
2026-06-30 audit marked #9 PARTIAL on the strength of the `vega` heatmap
metric, which is a related but different quantity, and the 2026-08-06
re-audit carried that forward. Stated explicitly here because #9 sits in the
coverage table between two items that *were* real regressions, and "PARTIAL"
alone does not distinguish "we lost half of this" from "half of this was
never written."

Building it is a genuine feature, not a surfacing task: it needs a repricing
pass at a perturbed skew, which `analysis/crash_repricing.crash_skew_vol` can
express but nothing currently drives.

## Outstanding

**#12 Liquidity Risk** — genuinely data-blocked, and now the *only* item in
this state. Needs per-strike bid/ask spreads and open interest from a live
options-chain feed; the free CBOE/FRED provider returns index-level series
only. There is no stub on either Dash page (the notebooks had one), so the
item is currently invisible rather than marked "planned". Tracked in #156
(the options-chain feed), which also unlocks skew-aware pricing and
backtesting — #12 is the Part X piece of that issue's scope, not a
separate effort.

**#13 Delta Drift** and **#14 Vega Term Exposure** were surfacing gaps, not
data gaps — both closed in M2.8. See the coverage table above:
`analysis/scenarios.ScenariosMixin.calculate_delta_drift`
(`/design` PLANNING — **Delta drift**) and
`analysis/maturity.MaturityMixin.calculate_vega_by_maturity`
(`/design` EXPLORATION — **Vega term exposure**). §14 extends
`add_maturity_buckets` rather than a second bucketing scheme, so it and
`carry.py`'s `theta_by_bucket` can never disagree on where a boundary falls.

> Do not wire `health.delta_drift_from_target` /
> `HealthMixin.calculate_delta_drift_pct` for handbook #13. Despite the
> name, it implements a different metric — signed deviation from a target
> net-delta ratio — and it backs the `/design` hedge-trigger panel's delta
> row, not this one.

## Engine code with no live consumer

Shorter than it was. M2.7 removed `hedge_triggers.py` and
`calculate_vega_sufficiency_pct` from this list. All of it is
**unit-tested** — this is about what the product shows, not about untested
code.

**`analysis/health.py` — the module is live; four gauges are not.**
`HealthMixin` is a base of `PortfolioAnalyzer` (`analysis/base.py:39-48`),
which the app instantiates, so the module is on a shipping path:

| Method | Reachable from |
| --- | --- |
| `calculate_crash_convexity_pct` | `crash_payoff`, `roll_status`, `crash_repricing`, `/design`'s market-environment panel — **live** |
| `calculate_vol_regime_percentile` | `market_environment` — **live** |
| `calculate_vega_sufficiency_pct` | `/design` sizing panel — **live since M2.7** |
| `calculate_health_metrics` | **nothing** — its one caller, `widgets/health_dashboard.py`, was deleted in Stage 4.3 |
| `calculate_overall_health_score` | **nothing** — same |
| `calculate_delta_drift_pct` | `calculate_health_metrics` → nothing; the underlying `delta_drift_from_target` also backs `/design`'s hedge-trigger delta row — **live** |
| `calculate_net_carry_pct` | **nothing** — `calculate_health_metrics` only |
| `calculate_convexity_cliff_days` | `/design` convexity cliff panel — **live** |
| `calculate_hedge_success_pct` | **nothing** — `calculate_health_metrics` only (deliberate — M2.4 finding **M2**) |

Stage 4.3 took the last consumer of that entry point rather than merely
un-gating it, and all three orphaned methods were **kept deliberately** — see
[`analysis/health.py`'s three orphans](#analysishealthpys-three-orphans) for
the reasoning. `analysis/health.py` records it at each function.

**`analysis/crash_payoff.crash_scenario_table` / `crash_payoff_ratio`** —
kept deliberately; see [Conscious retirements](#conscious-retirements).

## The notebook-retirement audit

Planning to retire the notebooks forced Open questions #1 below. Each of the
four Jupyter-only health gauges was traced to find whether a Dash surface
already covered it. The answers were not uniform, and the distinction is the
point — only one was a real loss:

| Gauge | Dash equivalent | Outcome |
| --- | --- | --- |
| Vega sufficiency | `/design` sizing panel, since M2.7 | Nothing to do |
| Delta drift (health form) | `/design` hedge-trigger delta row, via `delta_drift_from_target` | Nothing to do. Only the *gauge form* (a needle against bands) is lost; the number and its verdict are on the page. Not to be confused with §13, which has its own panel |
| Convexity cliff | **None** | **Ported** — new `/design` PLANNING panel; see below |
| Hedge success | **None**, deliberately | Stays retired. Not a surfacing gap: it cannot compute a real value without the position-history layer ([#70](https://github.com/qwertytam/deltadewa/issues/70)), so porting it would ship the permanently-neutral gauge M2.4 finding **M2** rejected. Already under [Conscious retirements](#conscious-retirements) |

**The convexity cliff was the one genuine loss** — surfaced nowhere on Dash,
with no decision recorded anywhere to drop it, which is exactly the state this
document exists to make impossible. It is now a `/design` PLANNING panel
reading `calculate_convexity_cliff_days`.

Its thresholds moved from presentation config to policy on the same reasoning
M2.7 used for the vega band: `dashboard.yaml` held both the region boundary
(`parameters.convexity_cliff_days: 180`) and the gauge's grading lines
(`convexity_cliff`'s `mid_val: 90` / `min_val: 30`). All three are now
`IpsConvexity.cliff_threshold_days` / `cliff_review_days` /
`cliff_urgent_days`, **carried over verbatim** so the promotion did not change
what a reading means. Unlike the vega band, the carry-over was sound here:
those three *were* grading lines on a one-sided day-count axis, not a signed
display range, so the digits meant the same thing on both sides of the move.
Issue #241 then removed the presentation copies, making the IPS the sole
owner. A test pins that the panel grades against the IPS value
rather than letting `calculate_convexity_cliff_days`'s own 180-day default
stand — the failure mode where editing `ips.yaml` silently does nothing.

Two things about this panel are deliberately unlike its neighbours:

- **No band bar.** The metric is one-sided — more runway is better without
  limit — so a two-sided good-zone bar would read a very long-dated book as
  "outside band". It gets a verdict sentence instead, in the hedge-trigger
  panel's OK/REVIEW/URGENT vocabulary. `IpsConvexity`'s docstring says so at
  the fields.
- **A fifth basis chip**, `basis: position maturities (nothing priced)`. The
  cliff reads no market input whatsoever — only maturity dates against the
  valuation date — so it cannot honestly carry even the book-Greeks chip.

The no-long-puts case is reported as "does not apply", not as the sentinel's
numeric value: `calculate_convexity_cliff_days` returns 999 there, and a page
printing "999 days" would read an unhedged book as the safest possible one.
That sentinel is now the named `health.NO_LONG_PUTS_CLIFF_DAYS` rather than a
literal at both ends, and a test asserts `999` never reaches the page.

## Stage 4.3 — the notebook retirement

`monitor_dashboard.ipynb`, `hedge_design.ipynb`, `example.py` and
`setup_nbstripout.sh` are gone, along with the `nbstripout` / `nbqa` /
`jupytext` tooling, the `.gitattributes` output filter, and the gate's
notebook-lint step. `deltadewa/widgets/health_dashboard.py` went with them
(closing [#242](https://github.com/qwertytam/deltadewa/issues/242)).

The parity pass that preceded the deletion is below. **Six items had no Dash
equivalent and no recorded decision.** Two were retired here; four became
issues. Nothing was dropped without one or the other — which is the whole
point of doing this before the deletion rather than after.

### Retired here

**The consolidated Greeks chart** (`visualization.plot_greeks_consolidated`,
Monitor cell 28). A matplotlib bar chart of the book's Greeks by position.
*Rationale:* `/design` EXPLORATION already answers the question it was asked
— how each Greek behaves — and answers it better, as a spot×vol surface with
a metric dropdown (`STRESS_METRICS`) rather than a single static snapshot.
The chart function and its tests are kept; only the surface is retired.

**The session change log** (`dashboard/changelog_display.py`, both notebooks).
*Rationale:* the display was a `ConsoleReporter` print of a per-session,
kernel-lifetime log — a form that does not survive the move to a persistent,
shared, server-side `ProgramState`. **The data is not retired.**
`ProgramState` constructs its own `PortfolioLogger` at `state.py:82` and
threads it through mutation and import (`state.py:187`, `:213`), backed by
`reporting/audit.py`'s `PortfolioChangeTracker` — so every edit made through
`/design` is still being recorded. What is retired is the view of it, and
rebuilding that view for the persistent model is
[#262](https://github.com/qwertytam/deltadewa/issues/262).

### Deferred, with an issue

| What | Where it was | Issue |
| --- | --- | --- |
| Roll planner — the `ROLL_NOW`/`DELAY`/`HOLD` action, proposed target strike, and roll-up cost to it | Design cell 21, via `analysis/roll_planner.build_roll_plan` | [#258](https://github.com/qwertytam/deltadewa/issues/258) |
| Position aging & expiration calendar | Monitor cell 41, `dashboard/position_aging.py` | [#259](https://github.com/qwertytam/deltadewa/issues/259) |
| ~~Portfolio volatility profile~~ | Design cell 36, `dashboard/volatility_profile.py` + `analysis/volatility.get_volatility_stats` | [#260](https://github.com/qwertytam/deltadewa/issues/260) — **Restored**, see [below](#the-volatility-profile-is-restored-260) |
| ~~Portfolio shape guard on import~~ | Cell 5 of **both** notebooks, `analysis/portfolio_shape.classify_portfolio_shape` | [#261](https://github.com/qwertytam/deltadewa/issues/261) — **Restored**, see [below](#the-shape-guard-is-restored-261) |

### The volatility profile is restored (#260)

The notebook cell (`dashboard/volatility_profile.VolatilityProfileDisplay`,
Design cell 36) printed the vega-weighted average volatility, the min–max
range across positions, and each leg's own volatility with a `(custom)`
marker. It read `analysis/volatility.get_volatility_stats`, which stayed
intact and tested through Stage 4.3 but had no product consumer —
`VolatilityProfileDisplay` itself is left as-is, read-but-not-built-on
Jupyter-era code, per this file's standing convention for `dashboard/`.

Why this one mattered beyond parity: every EXPLORATION surface on
`/design` (spot/vol heatmap, time/price heatmap, Monte Carlo) reprices with
`analysis/repricing.proportional_vol`, which scales every leg's volatility
by the same factor so the vega-weighted average lands wherever the grid
axis asks — but that average, and the skew it's computed from, was
invisible. Users were reading stress grids whose central assumption they
couldn't see.

`get_volatility_stats` still returns exactly what it always did (unchanged
— `widgets/summary.py` and `dashboard/setup.py` still call it). New in
`analysis/volatility.py`: `build_volatility_profile`, which wraps
`get_volatility_stats`'s summary numbers with a `relative_to_avg` ratio per
position — the same ratio `apply_proportional_volatility_shift` preserves
for every leg when the average moves — and returns `None` for an empty
portfolio (mirroring `get_volatility_stats`'s own empty-dict convention,
rather than the vega-term panel's zero-filled-reading convention: there is
no meaningful average with no positions).

The new "Volatility profile" panel sits **first** in `/design`'s
EXPLORATION zone — above the three stress grids, framed as what feeds them
rather than a standalone statistic — carrying its own basis chip
(`basis: each leg's stored volatility (nothing shocked)`) since, like the
vega term exposure panel, it reads the book structurally and shocks
nothing.

This also answers the open question the
["`config/dashboard.yaml` now has no reader"](#configdashboardyaml-now-has-no-reader)
section left for #259/#260: #260 did not revive the retired
gauge-presentation config. The panel uses the same table/paragraph
presentation every other EXPLORATION/PLANNING panel uses — no gauge
geometry needed.

### The shape guard is restored (#261)

The notebook cell (`_shape = classify_portfolio_shape(portfolio)`, commit
`73cf8da`) ran once per session and printed an amber notice when the book
wasn't a downside-protection structure. It had zero product consumers from
Stage 4.3 until now.

Two surfaces, both driven by `classify_portfolio_shape` directly — no new
conformance criteria invented:

- **The CLI** (`app/import_portfolio.py`, RUNBOOK §5) prints
  `shape.notice` to stderr, in an un-scrollable-past `!`-rule banner, when a
  successful import leaves a non-conforming book. Exit code stays `0` — a
  non-conforming book is a warning, not a failure.
- **Both pages** render a `shape-notice` element right under their `H1`,
  built by the new `app/shape_notice.shape_notice_text`. Quiet (an empty
  `<div>`, hidden by CSS) for a conforming book or an empty pre-load one;
  `/design`'s copy also re-renders on every `book-version` bump, since
  `/design` can change the book's shape (add/remove a position) without a
  re-import (RUNBOOK §6) — the CLI notice alone can't catch that.

### The roll planner was a false PRESENT

Worth recording separately, because it is the failure mode this document
exists to prevent, found *in* this document. The coverage table listed **Roll
planner — `/design` PLANNING — `analysis/roll_planner.build_roll_plan` —
PRESENT**. The panel on `/design` titled "Roll planner" renders
`roll_status.evaluate_roll_status` (`app/pages/design.py:61`, `:1186-1193`);
it has never called `build_roll_plan`, which had no consumer outside the
notebook. A reader checking parity against the table would have concluded the
notebook could be deleted safely, and would have been wrong.

The lesson is narrower than "the table was stale": the row was wrong because a
**panel title matched a module name**. `roll_planner.py` and the "Roll planner"
panel sound like the same thing and are not — the panel is the roll *table*
(`roll_status.py`), and `roll_planner.py` is the proposal layer above it. When
filling in the *Analysis backing* column, read the import, don't match the
name. The row is now PARTIAL, and [#258](https://github.com/qwertytam/deltadewa/issues/258)
restores it.

### What survived unchanged

Verified present at a named `deltadewa/app/**` line, not assumed: crash
convexity curve, scenario numbers, cost of carry and hedge efficiency, market
environment (#6/#7/#8), decision matrix and entry timing, net delta, vega
sufficiency, delta drift, convexity cliff, hedge triggers, position editor,
sizing, strike ladder, monetization, position detail, all three stress
surfaces, Monte Carlo and the P&L distribution.

Already-recorded retirements re-confirmed rather than re-litigated: the Part
VII report (now the digest), the discrete scenario table (now the curve), the
hedge-success gauge, and the delta-drift *gauge form*. All four are under
[Conscious retirements](#conscious-retirements) or the
[notebook-retirement audit](#the-notebook-retirement-audit) above.

Two lower-severity losses are noted without an issue: `build_env_gauges`, the
gauge form of market-environment numbers that are on `/design` in full (the
same gauge-form-only loss recorded for delta drift), and
`MonteCarloStalenessWidget`, which warned that cached MC results predated a
portfolio edit — moot on `/design`, which recomputes in-callback rather than
caching across edits.

### `config/dashboard.yaml` now has no reader

A consequence of deleting `health_dashboard.py`, recorded because it is not
obvious and nothing fails to announce it. That widget was the **only**
consumer of the gauge presentation config. `dashboard/session.py` still loads
it into `SessionContext.dashboard_config`, and nothing reads the result. So
`config/dashboard.yaml`, `config/dashboard.example.yaml`, the three
`examples/dashboard/` presets, and `docs/dashboard-config-guide.md` all now
describe a file the running app never opens. The IPS is the sole config the
Dash app loads.

Left in place rather than deleted, because the decision (delete the config
surface, or give the presets a Dash consumer) belongs with whoever takes
[#259](https://github.com/qwertytam/deltadewa/issues/259) — the remaining
panel that might want banded gauge geometry back.
[#260](https://github.com/qwertytam/deltadewa/issues/260) declined it; see
["The volatility profile is restored"](#the-volatility-profile-is-restored-260).
This also subsumes Open question #2 below.

### `analysis/health.py`'s three orphans

`calculate_net_carry_pct`, `calculate_health_metrics` and
`calculate_overall_health_score` lost their last consumer with the widget.
**All three are kept**, annotated as unconsumed at the function, on the same
reasoning as `crash_payoff.crash_scenario_table`: net carry is a real metric
with no Dash home and re-deriving it later is work, the aggregator is the
expensive part to rebuild if a Dash health surface is ever wanted, and all
three stay unit-tested meanwhile. This resolves Open question #1.

`calculate_overall_health_score` no longer depends on any gauge class — it was
always duck-typed on four attributes (`actual`, `min_val`, `max_val`,
`invert_colors`), and its tests now build that contract directly instead of
importing `HedgeHealthMetric`.

### The Jupyter layer itself

`deltadewa/widgets/` (11 modules) and `deltadewa/dashboard/` (12) survive,
minus `health_dashboard.py`. They have **no product consumer** — the two
notebooks were it — and are annotated as such at `widgets/__init__.py`. They
are still gated: ~245 of the suite's tests cover them. Retiring the layer is a
separate decision from retiring the notebooks and was deliberately not bundled
here.

## Open questions

Not decided by M2.7 or M2.8, and not blocking anything.

1. ~~**The remaining Jupyter-only health gauges.**~~ **Resolved in Stage
   4.3** — all three are kept and annotated as unconsumed. See
   [`analysis/health.py`'s three orphans](#analysishealthpys-three-orphans).
2. **`delta_drift`'s gauge band in `dashboard.yaml`** (`min_val: 5.0` /
   `max_val: 10.0`) exactly duplicates `triggers.delta_drift_warn_pct` /
   `delta_drift_action_pct`. Pre-existing, and the last policy number left in
   presentation config after #241 — which closed the `vega_sufficiency` and
   `convexity_cliff` cases and confirmed `vol_regime`, `net_carry` and
   `crash_convexity` only *look* duplicated (different metrics and sign
   conventions that happen to share a digit).

   **Largely moot since Stage 4.3**: nothing reads `dashboard.yaml` at all now
   (see [above](#configdashboardyaml-now-has-no-reader)), so the duplicate
   cannot mislead a running surface — only a reader. It stays listed because
   the file is still tracked and still documented.

   Whoever takes it should fix a second defect in the same block: all three
   `examples/dashboard/*.yaml` profiles still describe `delta_drift` as a
   **signed symmetric axis** (−50…+50, `invert_colors: false`), which
   `config/dashboard.yaml` has not been since the metric became |deviation
   from target| on a one-sided 0–30 inverted axis. The examples misrepresent
   the metric, not just its band. Do not fix them by copying the shipped
   numbers across — that re-adds the duplication; remove the grading lines
   the way #241 did for `convexity_cliff`.
3. ~~**The widget's hardcoded config fallback.**~~ **Resolved in Stage 4.3** —
   `HedgeHealthDashboard._get_default_config()` held cliff numbers #241 had
   removed from the YAML files, so a removed key fell back to a private copy
   rather than to policy. The widget is deleted, taking the private copy with
   it; `/design` reads the IPS directly.

`entry_timing_tree`'s hardcoded VIX thresholds (item 3 in earlier revisions
of this list) are resolved, not open: M2.8 moved them to
`IpsMarketEnvironment` and made the parameters required, closing the
M1.4-class leak M2.7 had surfaced but not fixed.
