# Part X coverage audit

Maps every item in [Handbook Part X — Institutional Hedge Dashboards](hedging%20handbook.md#part-x--institutional-hedge-dashboards)
to its implementation in this codebase.

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
  **delta drift** (M2.8), monetization. Most price the crash-skew (IPS
  anchor) basis; the three that do not carry their own basis chip (see
  [Basis chips](#basis-chips)).
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
| — | Sizing workbench | — | `/design` PLANNING | `analysis/sizing.size_hedge` | **PRESENT** |
| — | Strike ladder builder | — | `/design` PLANNING | `analysis/strike_ladder.build_strike_ladder` | **PRESENT** |
| — | Roll planner | — | `/design` PLANNING | `analysis/roll_planner.build_roll_plan` | **PRESENT** |
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
| **#4 Vega Sufficiency** — the only Tier-1 item with no surface anywhere | `calculate_vega_sufficiency_pct` intact and tested, reachable only via `calculate_health_metrics` → Jupyter | `/design` sizing panel. Band promoted from `dashboard.yaml` to a new `IpsVega` section — see [Where the vega band went](#where-the-vega-band-went) |
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

Two consequences worth knowing:

- The defaults in the new `vega:` section are **carried over verbatim** from
  `dashboard.yaml`'s gauge (`max_val: 20` → `sufficiency_min_pct`, `end: 50`
  → `sufficiency_max_pct`), so moving the metric did not silently change what
  a reading means. They are a starting point, not a derived constant.
- `dashboard.yaml` **keeps** its `vega_sufficiency` block, because the
  Jupyter gauge still reads it. The two now coexist. Retiring the
  presentation copy is a `widgets/` change and was left out of M2.7
  deliberately; see [Open questions](#open-questions).

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
| `calculate_health_metrics` | `widgets/health_dashboard.py` (Jupyter) only |
| `calculate_overall_health_score` | `widgets/health_dashboard.py` (Jupyter) only |
| `calculate_delta_drift_pct` | `calculate_health_metrics` only → Jupyter |
| `calculate_net_carry_pct` | `calculate_health_metrics` only → Jupyter |
| `calculate_convexity_cliff_days` | `calculate_health_metrics` only → Jupyter |
| `calculate_hedge_success_pct` | `calculate_health_metrics` only → Jupyter (deliberate — M2.4 finding **M2**) |

`calculate_health_metrics` is a **historical** consumer path: `widgets/` is
Jupyter-only, and M2.6 retired the notebook-execution and `nbqa` CI steps, so
nothing behind that entry point is gated any more. `analysis/health.py`
records this at the function.

**`analysis/crash_payoff.crash_scenario_table` / `crash_payoff_ratio`** —
kept deliberately; see [Conscious retirements](#conscious-retirements).

## Open questions

Not decided by M2.7 or M2.8, and not blocking anything.

1. **The four remaining Jupyter-only health gauges** — revive on a Dash page,
   fold into `roll_status.py`, or delete. They are ungated as things stand,
   which is the part that will eventually force the question.
2. **`dashboard.yaml`'s `vega_sufficiency` block**, now duplicated by
   `IpsVega`. Retiring it means changing `widgets/health_dashboard.py` to
   read the IPS, which is a `widgets/` change.

`entry_timing_tree`'s hardcoded VIX thresholds (item 3 in earlier revisions
of this list) are resolved, not open: M2.8 moved them to
`IpsMarketEnvironment` and made the parameters required, closing the
M1.4-class leak M2.7 had surfaced but not fixed.
