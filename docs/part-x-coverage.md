# Part X coverage audit

Maps every item in [Handbook Part X — Institutional Hedge Dashboards](hedging%20handbook.md#part-x--institutional-hedge-dashboards)
to its implementation in this codebase.

**Re-audited 2026-08-06 against the Dash surfaces.** This supersedes the
2026-06-30 audit (which closed [#73](https://github.com/qwertytam/deltadewa/issues/73)).
That version mapped all 15 items to notebook surfaces — `widgets/health_dashboard.py`,
`widgets/env_gauges.py`, `widgets/summary.py`, `dashboard/carry_display.py`,
`dashboard/crash_payoff_display.py` — every one of which stopped being the
shipping UI when M2.4/M2.5 rebuilt the dashboards in Dash. It therefore
asserted coverage the live product does not have. The rebuild's coverage
regressions are named in [Coverage regressions](#coverage-regressions-from-the-dash-rebuild)
below; that section is the point of this document.

## The current surfaces

Three, not two. The 2026-06-30 audit predates the third.

**`/monitor`** (`deltadewa/app/pages/monitor.py`) — the partner's read-mostly
book review. Three sections plus a collapsed table:

- *Crash scenario* — the scenario explorer: three dials (spot shock, vol
  shock, underlying quantity), the payoff curve, the scenario numbers
  (`_scenario_numbers`), and the **cost panel** (`_cost_panel`).
- *Decisions* — per-position roll verdicts with reasons and convexity band
  bars, plus the monetization schedule at the current mark.
- *Position detail* — a collapsed `<details>` per-leg ledger.

**`/design`** (`deltadewa/app/pages/design.py`) — the operator's workbench.
Three zones:

- *BOOK* — position editor, underlying quantity, guarded import/export.
- *PLANNING* — sizing, strike ladder, roll planner, monetization; all on the
  crash-skew (IPS anchor) basis.
- *EXPLORATION* — spot×vol heatmap, time×price heatmap, Monte Carlo
  distribution; all on the proportional-vol (GBM) basis. Both heatmaps carry
  a **metric dropdown** built from `visualization.stress_charts_plotly.STRESS_METRICS`,
  which offers `pnl`, `value`, `net_delta`, `delta`, `gamma`, `vega`,
  `theta`, `rho`.

**The weekly digest** (`deltadewa/reporting/weekly_report.py` →
`program_report.py`, shipped in M2.6) — an emailed report, not a page. It
carries the Part VII board/IC report, the decision matrix + entry-timing
verdict, and a `MarketContextSection` holding `vix`, `regime_label`,
`skew_percentile`, and `hedge_cost_verdict`. Several Tier-2 items live only
here.

Shared **chrome** (`deltadewa/app/chrome.py`) renders the as-of stamp and the
STATIC/STALE/UNAVAILABLE provenance banner above both pages. It reads
`MarketEnvironment.data_quality`/`.as_of` only — never the environment's
metric values.

## Status legend

| Status | Meaning |
| --- | --- |
| **PRESENT** | On a current dashboard surface, named below. |
| **MOVED** | Surfaced, but on a different surface than the notebooks had it. |
| **PARTIAL** | Some of the item is surfaced; the missing part is named. |
| **DROPPED BY DESIGN** | Deliberately excluded, with the rationale recorded. |
| **DROPPED UNINTENTIONALLY** | A coverage regression from the Dash rebuild. |
| **OUTSTANDING** | Not built; blocked on data that does not exist. |

## Coverage table

| # | Part X item | Tier | Current surface | Analysis backing | Status |
| --- | --- | --- | --- | --- | --- |
| — | Decision matrix + entry-timing tree | pre-Tier | Weekly digest only | `analysis/decision_matrix.py` (`decision_matrix`) | **MOVED** — off both pages |
| 1 | Crash Convexity Chart | 1 | `/monitor` — *Crash scenario*, `payoff-curve` | `analysis/monitor_scenario.build_scenario_curve`, `visualization/crash_charts_plotly.plot_scenario_curve` | **PRESENT** |
| 2 | Crash Scenario Table & Payoff Ratio | 1 | `/monitor` — *Crash scenario*, `_scenario_numbers` (offset ratio) | `analysis/monitor_scenario.build_scenario` | **PRESENT** (form changed — see [Deliberate exclusions](#deliberate-exclusions)) |
| 3 | Theta Carry (Insurance Cost) | 1 | `/monitor` — *Crash scenario*, `_cost_panel`; also digest `CostSection` | `analysis/carry.carry_vs_budget` via `monitor_scenario` | **PRESENT** |
| 4 | **Vega Sufficiency Gauge** | **1** | **none** | `analysis/health.HealthMixin.calculate_vega_sufficiency_pct` — intact, tested, no live consumer | **DROPPED UNINTENTIONALLY** |
| 5 | Carry vs. Convexity Chart | 1 | Carry: `/monitor` cost panel. Convexity: `/monitor` *Decisions* band bars. Both together: `/design` PLANNING — *Sizing workbench* | `analysis/carry.py`, `analysis/crash_repricing.crash_convexity_pct`, `analysis/sizing.size_hedge` | **PARTIAL** — both axes present, **the ratio itself is computed nowhere** |
| 6 | Volatility Regime Indicator | 2 | Weekly digest `MarketContextSection` only | `analysis/market_environment.classify_vix_regime`, `analysis/health.compute_vol_regime` | **MOVED** — off both pages |
| 7 | Skew Percentile Gauge | 2 | Weekly digest `MarketContextSection` only | `analysis/market_environment` (`skew_percentile`), `marketdata` `get_skew_percentile` | **MOVED** — off both pages |
| 8 | **Forward Variance Level** | **2** | **none** | `analysis/market_environment.forward_vol` → `MarketEnvironment.forward_vol_front_3m` — computed on every page request, never rendered | **DROPPED UNINTENTIONALLY** |
| 9 | Skew Exposure / Beta | 3 | `/design` EXPLORATION — `vega` heatmap metric | `visualization/stress_charts_plotly.STRESS_METRICS["vega"]`; no explicit ∂V/∂skew scalar exists | **PARTIAL** (unchanged in substance since 2026-06-30) |
| 10 | Net Delta Exposure | 3 | `/design` EXPLORATION — `net_delta` heatmap metric | `portfolio/greeks.net_delta`, `analysis/scenarios.py` (`"net_delta"` → delta at shocked spot) | **PARTIAL** — grid present, **scalar readout dropped** |
| 11 | Hedge Rebalance Triggers | 3 | `/monitor` — *Decisions*; `/design` PLANNING — *Roll planner*, *Monetization* | `analysis/roll_status.evaluate_roll_status`, `analysis/monetization.build_monetization_plan`, `analysis/roll_planner.build_roll_plan` | **PRESENT** — re-based (see note below) |
| 12 | Liquidity Risk | 4 | none | none — needs per-strike bid/ask and open interest | **OUTSTANDING** — genuinely data-blocked |
| 13 | Delta Drift | 4 | Readable off `/design`'s `net_delta` heatmap; no drift scalar | `analysis/scenarios.py` already prices delta at shocked spot | **RECLASSIFIED** — surfacing gap, not data-blocked |
| 14 | Vega Term Exposure | 4 | none | `analysis/maturity.MaturityMixin.add_maturity_buckets` already does this grouping for theta | **RECLASSIFIED** — surfacing gap, not data-blocked |
| 15 | Hedge Efficiency Ratio | 4 | Digest `ProtectionSection.payoff_ratio`; not on either page | Same division as #5, different units | **PARTIAL** — the ratio is missing from both pages, as in #5 |
| — | Part VII Board/IC report | — | Weekly digest email | `reporting/program_report.py` | **MOVED** — see [Deliberate exclusions](#deliberate-exclusions) |
| — | Sizing workbench | — | `/design` PLANNING | `analysis/sizing.size_hedge` | **PRESENT** |
| — | Strike ladder builder | — | `/design` PLANNING | `analysis/strike_ladder.build_strike_ladder` | **PRESENT** |
| — | Roll planner | — | `/design` PLANNING | `analysis/roll_planner.build_roll_plan` | **PRESENT** |
| — | Monetization planner | — | `/design` PLANNING + `/monitor` *Decisions* | `analysis/monetization.build_monetization_plan` | **PRESENT** |

**Note on #11.** The handbook's four trigger types are all covered — time-based
roll, strike drift, crash monetization, and the convexity threshold — but by
`analysis/roll_status.py` and `analysis/monetization.py`, **not** by
`analysis/hedge_triggers.py`, which the 2026-06-30 audit named as the backing.
See [Engine code with no live consumer](#engine-code-with-no-live-consumer).

## Coverage regressions from the Dash rebuild

These are surfacing gaps, not engine gaps. In every case the analysis function
exists and is tested; what is missing is a panel. `deltadewa/app/bands.py`
(`band_bar`) is the existing gauge primitive, and for #6/#7/#8 the value is
already in scope on the page that would render it.

No decision to drop any of these was recorded. `docs/implementation-plan.md`
contains no mention of the health gauges, the environment gauges, or Part X at
all; M2.4's one deliberate gauge omission is finding **M2**, the inert
*hedge-success* gauge, which is a different metric.

### 1. #4 Vega Sufficiency (Tier 1) — no surface anywhere

The only Tier-1 item with no current surface, and one of the six metrics the
handbook's own short list names. `HealthMixin.calculate_vega_sufficiency_pct`
is intact and unit-tested (`tests/test_analysis/test_health.py`), but nothing
outside `health.py` calls it — its one reader is `calculate_health_metrics`,
which in turn is called only by `widgets/health_dashboard.py` (Jupyter). It is
not in the weekly digest either.

**Recommendation: restore to `/design`,** in or beside the *Sizing workbench*
panel. It answers "is the book big enough to respond to a vol spike", which is
actionable only for the operator, and M2.4's documented through-line
("legible cold", three questions, no gauge wall) argues against adding a
fourth number to `/monitor`. If you'd rather it lead the partner's page, the
alternative home is `/monitor`'s cost panel.

**Cost:** one `band_bar` row. One decision first — unlike #6/#7, its bands are
presentation config (`dashboard_config_*.yaml`, mirrored at
`widgets/health_dashboard.py`), not IPS policy, so restoring it means either
reading that config from the Dash page or promoting the bands to `ips.yaml`.

### 2. #8 Forward Variance (Tier 2) — no surface anywhere

`MarketEnvironment.forward_vol_front_3m` is computed on **every** `/monitor`
and `/design` request (`assess_market_environment` is called at
`monitor.py:401`, `design.py:1404`, `design.py:1926`) and then discarded —
the pages consume the environment only as an input to
`build_monetization_plan` and for chrome's `data_quality`/`as_of`. It is also
absent from the weekly digest's `MarketContextSection`, so unlike #6/#7 it has
no surface at all.

**Recommendation: restore to `/design`** — see regression 3, which it belongs
with.

### 3. #6 Volatility Regime + #7 Skew Percentile — moved off the dashboard

Both are still surfaced, in the weekly digest's `MarketContextSection`, so
these are not silent losses. But they are only available weekly and only by
email; neither page shows them, despite both already holding the values.

Together with #8 they are the **three inputs the decision matrix takes** — and
the decision matrix itself also moved to the digest only. So the operator can
read the digest's entry-timing verdict but cannot, on either page, see the
three numbers that produced it or ask the question on any day but Sunday.

**Recommendation: restore #6, #7, #8, and the decision matrix to `/design`
PLANNING as one "Market environment / entry timing" panel.** Splitting them
across surfaces is what lost them. `/design` is the right home: "should I buy
today" is the operator's question, and keeping it off `/monitor` preserves
that page's legibility.

**Cost:** one panel. `market_env` is already in scope at `design.py:1404`;
`decision_matrix()` already takes exactly these three inputs; IPS bands
(`IpsMarketEnvironment.vol_regime_low`/`vol_regime_high`,
`skew_low_pctile`/`skew_high_pctile`) already exist for #6 and #7. #8 has no
IPS band, so render it as a level plus the `hedge_cost_verdict` label rather
than a banded gauge.

### 4. #5 / #15 — the convexity-carry ratio is computed nowhere

Both axes are surfaced separately, and `/design`'s sizing panel evaluates them
jointly for one candidate (carry vs budget band, achieved convexity vs target
band). But the handbook's headline ratio — convexity ÷ carry, with its
`< 3` poor / `3–6` acceptable / `> 6` attractive reading — does not exist in
the codebase, on any surface. #15 (Hedge Efficiency Ratio) is the same
division in dollar rather than percentage terms, so both items miss for the
same reason. The 2026-06-30 audit marked #15 "done (via #5)"; with #5 now
partial, that no longer holds.

**Recommendation: restore to `/monitor`,** one number beside the cost panel.
It is the single "is this hedge worth the money" figure, and it is the
partner's question, not the operator's. Both inputs are already on
`ScenarioResult`.

**Cost:** a small `analysis/` addition — this ratio has no home function
today, so it needs one (with a test) rather than just a panel.

### 5. #10 Net Delta — the scalar readout

Worth stating precisely, because a naive grep says this is missing entirely:
`net_delta` does not appear anywhere in `deltadewa/app/` as a string, but the
metric **is** reachable. `_METRIC_OPTIONS` (`design.py:133`) is derived from
`STRESS_METRICS`, which includes `net_delta`, so both EXPLORATION heatmaps can
plot portfolio delta across the spot×vol and time×price grids.

What was lost is the *scalar* — "net delta right now", which the notebooks'
Net Hedge Summary showed — along with the delta-rebalance trigger
(`hedge_triggers.evaluate_hedge_triggers`, `health.delta_drift_from_target`).

**Recommendation: restore to `/design` BOOK,** one line beside the underlying
quantity input. Low value on `/monitor`, where the partner reads the offset
ratio rather than raw delta.

**Cost:** one line from `portfolio.summary_stats()["net_delta"]`.

## Deliberate exclusions

Recorded here so they don't get re-flagged as regressions on the next audit.

**Part VII board/IC report — retired from the dashboard.** It was a `/monitor`
notebook panel; M2.6 made it a scheduled, emailed deliverable
(`reporting/weekly_report.py`). An on-demand copy on `/monitor` would
duplicate a report that now arrives on its own, and the partner's page is
meant to be read, not exported from.

**#2's discrete scenario table — retired in favour of the curve.** The
handbook shows a six-row SPX-move table; `/monitor` renders a continuous
payoff curve over −50%…+10% with a live marker, which is a superset. The
engine for the tabular form still exists (`analysis/crash_payoff.crash_scenario_table`,
`crash_payoff_ratio`) and remains tested, but has no production consumer —
kept, not restored, because a second tabular copy of the curve would work
against `/monitor` staying legible cold.

**The hedge-success gauge — omitted, per M2.4 finding M2.** A permanently
neutral gauge is worse than no gauge; it returns when realized-carry tracking
exists. This is the one gauge omission the implementation plan does record.

**`/monitor` is not a gauge wall.** The general principle behind the
`/design`-first recommendations above: `/monitor` answers three questions
(what does this cost, what do we get, what are we doing about it) for a
non-technical reader returning after eight weeks. Metrics that are inputs to
an operator's decision belong on `/design` even when the handbook files them
under a higher tier.

## Outstanding

**#12 Liquidity Risk** — genuinely data-blocked. Needs per-strike bid/ask
spreads and open interest from a live options-chain feed; the free CBOE/FRED
provider returns index-level series only. There is no stub on either Dash page
(the notebooks had one), so the item is currently invisible rather than marked
"planned".

### Reclassified out of "outstanding"

The 2026-06-30 audit listed #13 and #14 alongside #12 as data-blocked. Read
against the handbook's own definitions, neither is.

**#13 Delta Drift** is defined in handbook §13 as `Δ(−5%) − Δ(0)` — two
shocked deltas at a single valuation date, not a series from position history.
`analysis/scenarios.py` already prices `metric="net_delta"` at arbitrary
shocked spots, which is exactly the input required; `/design`'s spot×vol
heatmap with `net_delta` selected already *displays* Δ at −5%. What is missing
is the drift scalar and a panel to hold it.

> Do not wire `health.delta_drift_from_target` /
> `HealthMixin.calculate_delta_drift_pct` for this. Despite the name, it
> implements a different metric — signed deviation from a target net-delta
> ratio — and is the backing for the health gauge and the delta trigger, not
> for handbook #13.

**#14 Vega Term Exposure** is defined in handbook §14 as vega aggregated by
maturity bucket. `MaturityMixin.add_maturity_buckets` (`analysis/maturity.py`)
already produces that grouping, and `analysis/carry.py` already applies it to
theta (`df.groupby("maturity_bucket")["position_theta"].sum()`). Extending the
same pattern to `position_vega` needs no new data.

Both are therefore surfacing gaps of the same shape as the regressions above:
a small `analysis/` function plus a panel, not a feed.

## Engine code with no live consumer

Surfaced by this audit and worth tracking separately, because it shares a root
cause with regression 1. All of it is **unit-tested** — this is about what the
product shows, not about untested code.

**`analysis/hedge_triggers.py` — no functional consumer at all.** Its only
importers are `analysis/__init__.py` (a re-export) and
`tests/test_analysis/test_hedge_triggers.py`. `analysis/health.py` names
`evaluate_hedge_triggers` in a docstring but does not call it. Its delta,
theta, and gamma triggers are therefore live nowhere; the handbook's trigger
coverage (#11) comes entirely from `roll_status.py` and `monetization.py`.

**`analysis/health.py` — the module is live, the gauge set is not.**
`HealthMixin` is a base of `PortfolioAnalyzer` (`analysis/base.py:39-48`),
which the app instantiates (`design.py:929`, `:987`; `monitor_scenario.py:127`),
so the module itself is on a shipping path — and two of its methods have real
callers:

| Method | Reachable from |
| --- | --- |
| `calculate_crash_convexity_pct` | `crash_payoff`, `roll_status`, `crash_repricing` — **live** |
| `calculate_vol_regime_percentile` | `market_environment` — **live** |
| `calculate_health_metrics` | `widgets/health_dashboard.py` (Jupyter) only |
| `calculate_overall_health_score` | `widgets/health_dashboard.py` (Jupyter) only |
| `calculate_vega_sufficiency_pct` | `calculate_health_metrics` only → Jupyter (this is regression 1, #4) |
| `calculate_delta_drift_pct` | `calculate_health_metrics` only → Jupyter |
| `calculate_net_carry_pct` | `calculate_health_metrics` only → Jupyter |
| `calculate_convexity_cliff_days` | `calculate_health_metrics` only → Jupyter |
| `calculate_hedge_success_pct` | `calculate_health_metrics` only → Jupyter (deliberate — M2.4 finding **M2**) |

So the whole gauge set funnels through one Jupyter-only entry point. Since M2.6
retired the notebook-execution and `nbqa` CI steps, `widgets/` is no longer
gated, which makes `calculate_health_metrics` a bridge to a surface CI no
longer builds. Restoring #4 (regression 1) puts
`calculate_vega_sufficiency_pct` back on a live path. The rest are a standing
question: revive, fold into `roll_status.py`, or delete — not decided here.
