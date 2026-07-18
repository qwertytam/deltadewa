# Dashboard Config Guide

> **Navigation:** [README](../README.md) · [yaml-config-guide.md](yaml-config-guide.md) · [hedging handbook.md](hedging%20handbook.md)

`config/dashboard.yaml` controls the gauge ranges and color thresholds
`HedgeHealthDashboard` (`deltadewa/widgets/health_dashboard.py`) uses for
its seven health metrics. It's presentation-only — it changes how the
dashboard displays health, not the underlying numbers or program policy.
(Carry budget, convexity targets, roll/monetization triggers belong in
`config/ips.yaml` instead; see [yaml-config-guide.md](yaml-config-guide.md).)

## Two top-level sections

```yaml
parameters:
  historical_vol_low: 0.15
  historical_vol_high: 0.35
  convexity_cliff_days: 180

metrics:
  net_carry: { ... }
  crash_convexity: { ... }
  # ...five more
```

### `parameters`

| Key | Meaning |
| --- | --- |
| `historical_vol_low` | 25th-percentile IV — feeds the Volatility Regime metric's "cheap" end |
| `historical_vol_high` | 75th-percentile IV — feeds the Volatility Regime metric's "expensive" end |
| `convexity_cliff_days` | Days-to-maturity threshold for the Time to Convexity Cliff metric's high-gamma warning window |
| `skew_low_pctile` | SKEW-index percentile (0-100) below which skew reads as benign — fed to `assess_market_environment` as `skew_bands[0]` |
| `skew_high_pctile` | SKEW-index percentile (0-100) above which skew reads as stressed/expensive — fed to `assess_market_environment` as `skew_bands[1]` |
| `term_contango_tolerance` | VIX-point gap below which front/3M differences are treated as noise (FLAT) rather than a real slope — fed to `assess_market_environment` as `term_tolerance` |

The three `skew_*` / `term_*` keys configure `assess_market_environment`
(`deltadewa/analysis/market_environment.py`) directly — they are
calculation inputs, not display settings. Any key absent from the file
falls back to the function's own hardcoded default.

### `metrics`

Each of the seven keys takes the same six fields:

| Field | Meaning |
| --- | --- |
| `start` / `end` | The gauge's full displayed range |
| `min_val` | Where the "bad" color zone ends |
| `mid_val` | The neutral/amber point |
| `max_val` | Where the "good" color zone begins |
| `invert_colors` | `false` (default): low=bad/red, high=good/green. `true`: flips it — low=good/green, high=bad/red |

`min_val`/`mid_val`/`max_val` need not be evenly spaced — they just mark
the red→amber→green band edges on the `start`–`end` gauge.

## The seven metrics

| Key | What it measures | Default `start`–`end` | Default bands (`min_val` / `mid_val` / `max_val`) | `invert_colors` |
| --- | --- | --- | --- | --- |
| `net_carry` | Annualized theta as % of underlying value | -10.0 to 10.0 | -5.0 / 0.0 / 2.0 | `false` |
| `crash_convexity` | Hedge P&L at the IPS crash scenario (`convexity.crash_scenario_pct`), as % of underlying | -30.0 to 30.0 | -10.0 / 0.0 / 10.0 | `false` |
| `vega_sufficiency` | Portfolio % change per +10 vol shock | -50.0 to 50.0 | -20.0 / 0.0 / 20.0 | `false` |
| `delta_drift` | Net hedge delta as % of equity delta | -50.0 to 50.0 | -20.0 / 0.0 / 20.0 | `false` |
| `convexity_cliff` | Days until long puts enter the high-gamma region | 0 to 365 | 30 / 90 / 180 | `false` |
| `vol_regime` | Current IV percentile (0=cheap, 100=expensive) | 0 to 100 | 25 / 50 / 75 | **`true`** |
| `hedge_success` | Hedge P&L vs. cumulative carry paid | -200 to 200 | -100 / 0 / 100 | `false` |

`vol_regime` is the one metric that inverts: a **low** IV percentile
(cheap vol, below `min_val`) is good/green, a **high** percentile
(expensive vol, above `max_val`) is bad/red — backwards from every other
metric here, where low is bad and high is good.

Values shown are the shipped defaults
(`HedgeHealthDashboard._get_default_config()`, also reproduced verbatim
and commented in `examples/dashboard/dashboard_config_default.yaml`).

## How it's loaded

`start_session()` (`deltadewa/dashboard/session.py`) reads
`config/dashboard.yaml` automatically. Missing or invalid → a warning and
`ctx.dashboard_config` is `None`; `HedgeHealthDashboard` then falls back to
its built-in defaults, which are identical to the values above.

Separately, `HedgeHealthDashboard.display_config_loader()` renders a
FileUpload widget in the notebook for layering an ad hoc YAML/JSON config
on top at runtime — independent of, and on top of, whatever
`start_session` already loaded.

## Aggressive vs. conservative presets

`examples/dashboard/` ships two alternate presets alongside the default.
Neither is loaded automatically — copy one over `config/dashboard.yaml` to
use it.

- **`dashboard_config_aggressive.yaml`** — every band is widened and
  shifted to tolerate more risk: e.g. `crash_convexity.min_val` relaxes
  from -10.0 to -15.0 (alerts later on a worse crash loss),
  `convexity_cliff_days` drops from 180 to 120 (shorter warning window),
  `vol_regime.max_val` rises from 75 to 80 (tolerates pricier vol before
  flagging red). For market environment: `skew_low_pctile` drops to 20
  and `skew_high_pctile` rises to 80 (wider benign zone before flagging
  stressed skew), `term_contango_tolerance` rises to 1.0 (requires a
  larger front/3M gap before calling the curve CONTANGO or
  BACKWARDATION). Pick this for active trading where you're comfortable
  riding closer to the edge before the dashboard flags it.
- **`dashboard_config_conservative.yaml`** — every band tightens: e.g.
  `crash_convexity.min_val` tightens from -10.0 to -5.0 (alerts sooner),
  `convexity_cliff_days` rises from 180 to 240 (earlier warning),
  `vol_regime.max_val` drops from 75 to 70 (flags red sooner on expensive
  vol). For market environment: `skew_low_pctile` rises to 30 and
  `skew_high_pctile` drops to 70 (flags stressed skew sooner),
  `term_contango_tolerance` drops to 0.25 (detects even small slopes as
  real). Pick this for risk-averse mandates where you want alerts to fire
  earlier and hold the book to a higher bar.

## Tune your own

1. Copy the default as a starting point:

   ```bash
   cp examples/dashboard/dashboard_config_default.yaml config/dashboard.yaml
   ```

2. Edit a band. For example, to alert on crash convexity sooner than the
   default -10.0:

   ```yaml
   metrics:
     crash_convexity:
       min_val: -7.0   # was -10.0
   ```

3. Save, then re-run (or re-open) the dashboard — `start_session()` picks
   up `config/dashboard.yaml` on the next session.
