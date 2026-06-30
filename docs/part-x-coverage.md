# Part X coverage audit

Maps every item in [Handbook Part X — Institutional Hedge Dashboards](hedging%20handbook.md#part-x--institutional-hedge-dashboards)
to its implementation in this codebase. Produced 2026-06-30; closes [#73](https://github.com/qwertytam/deltadewa/issues/73).

## Coverage table

| # | Part X item | Tier | Monitor cell / Design panel | Analysis / widget backing | Status |
|---|---|---|---|---|---|
| — | Decision matrix + entry-timing tree | pre-Tier | Design — *Decision matrix & entry timing* | `analysis/decision_matrix.py` | done |
| 1 | Crash Convexity Chart | 1 | Monitor — *Crash Payoff & Scenario Table* | `analysis/crash_payoff.py`, `visualization/crash_charts.py`, `dashboard/crash_payoff_display.py` | done |
| 2 | Crash Scenario Table & Payoff Ratio | 1 | Monitor — *Crash Payoff & Scenario Table* | `analysis/crash_payoff.py`, `dashboard/crash_payoff_display.py` | done |
| 3 | Theta Carry (Insurance Cost) | 1 | Monitor — *Cost of Carry* | `analysis/carry.py`, `dashboard/carry_display.py`, `visualization/theta_charts.py` | done |
| 4 | Vega Sufficiency Gauge | 1 | Monitor — *Hedge Health* | `analysis/base.py` (`PortfolioAnalyzer`), `widgets/health_dashboard.py` | done |
| 5 | Carry vs. Convexity Chart | 1 | Monitor — *Crash Payoff & Scenario Table* (carry-convexity scatter) | `analysis/carry.py` (`calculate_carry_metrics`), `analysis/crash_payoff.py` | done |
| 6 | Volatility Regime Indicator | 2 | Monitor — *Market environment* | `analysis/market_environment.py` (`classify_vix_regime`, `regime_percentile`), `widgets/env_gauges.py` | done |
| 7 | Skew Percentile Gauge | 2 | Monitor — *Market environment* | `analysis/market_environment.py` (`skew_percentile`), `marketdata/cboe_fred_provider.py` | done |
| 8 | Forward Variance Level | 2 | Monitor — *Market environment* | `analysis/market_environment.py` (`forward_vol`, `forward_vol_front_3m`) | done |
| 9 | Skew Exposure / Beta | 3 | Monitor — *Consolidated Greeks* | `visualization/convenience.py` (`plot_greeks_consolidated`) shows per-position vega; no explicit ∂V/∂skew scalar | partial |
| 10 | Net Delta Exposure | 3 | Monitor — *Net Hedge Summary* + *Consolidated Greeks* | `portfolio/greeks.py` (`net_delta`), `widgets/summary.py` | done |
| 11 | Hedge Rebalance Triggers | 3 | Monitor — *Hedge Decision Triggers* + *Roll Status* | `analysis/hedge_triggers.py`, `analysis/roll_planner.py`, `dashboard/roll_status.py` | done |
| 12 | Liquidity Risk | 4 | Monitor — *Liquidity* (stub) | none — requires Phase D2 options-chain feed | **outstanding** |
| 13 | Delta Drift | 4 | Monitor — *Delta Drift Detail* (stub) | none — needs delta series from position history; scenario_grid building block exists | **outstanding** |
| 14 | Vega Term Exposure | 4 | not in notebooks | none — only aggregate `total_vega` exists; no maturity-bucketed vega | **outstanding** |
| 15 | Hedge Efficiency Ratio | 4 | Monitor — *Crash Payoff & Scenario Table* (carry-convexity) | handbook §2018 states HER = crash payoff / carry, same formula as #5; no new information beyond Tier-1 | done (via #5) |
| — | Part VII Board/IC report | — | Monitor — *Part VII — Hedge Program Report* | `reporting/program_report.py` | done |
| — | Sizing workbench | — | Design — *Sizing workbench* | `analysis/sizing.py` (`size_hedge`) | done |
| — | Strike ladder builder | — | Design — *Strike ladder builder* | `analysis/strike_ladder.py` (`build_strike_ladder`) | done |
| — | Roll planner | — | Design — *Roll planner* | `analysis/roll_planner.py` (`build_roll_plan`) | done |
| — | Monetization planner | — | Design — *Monetization planner* | `analysis/monetization.py` (`build_monetization_plan`) | done |

## Outstanding Tier-4 items

**#12 Liquidity Risk** — stub in `monitor_dashboard.ipynb` ("Planned (Phase D2)"); requires a live options-chain feed providing bid/ask spreads and open interest per strike.

**#13 Delta Drift** — stub in `monitor_dashboard.ipynb` ("Planned — requires net-delta series from position history"); the underlying scenario machinery (`analysis/scenarios.py` `scenario_grid`) can price at shocked spot levels, but no dedicated metric or widget surfaces the Δ₀ vs Δ₋₅% comparison yet.

**#14 Vega Term Exposure** — not yet in either notebook; `analysis/maturity.py`'s bucket logic (already used for theta carry) could be extended to vega, but no maturity-bucketed vega metric exists yet.
