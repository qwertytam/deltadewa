# Dashboard Config Guide

> **Navigation:** [README](../README.md) · [yaml-config-guide.md](yaml-config-guide.md) · [hedging handbook.md](hedging%20handbook.md)

⚠️ **This file currently has no reader.** `config/dashboard.yaml`'s only
consumer was `HedgeHealthDashboard` (`widgets/health_dashboard.py`), the
Jupyter gauge wall, deleted in Stage 4.3 with the notebooks. The file, its
`.example` template, the `examples/dashboard/` presets and this guide are kept
pending a decision on whether the Dash pages should read banded gauge geometry
from config — see [part-x-coverage.md](part-x-coverage.md), "Stage 4.3".
**Editing it changes nothing today.** The schema below is documented as-was.

`config/dashboard.yaml` controls the gauge ranges and color thresholds
the Jupyter gauge wall used for its seven health metrics. It's
presentation-only — it changes how the dashboard displays health, not the
underlying numbers or program policy.

**Nothing in this file decides anything.** Every value is gauge geometry:
where an axis starts and ends, and where it changes colour. Any threshold
that answers a mandate question — carry budget, convexity targets, the vega
sufficiency band, when decaying convexity forces a roll, whether vol is
cheap, roll/monetization triggers — is policy and belongs in
`config/ips.yaml`; see [yaml-config-guide.md](yaml-config-guide.md). A policy
number copied into this file is the leak M1.4 closed and #241 closed again.

## Top-level sections

```yaml
metrics:
  net_carry: { ... }
  crash_convexity: { ... }
  # ...five more
```

`metrics` is the only section the shipped file uses. A `parameters` section
is still merged if present, but the shipped `config/dashboard.yaml` carries
none: its keys were all either policy that moved to `ips.yaml` or widget
constructor arguments.

| Former `parameters` key | Where it lives now |
| --- | --- |
| `convexity_cliff_days` | `convexity.cliff_threshold_days` in `ips.yaml` (#241) |
| `skew_low_pctile` / `skew_high_pctile` | `market_environment.skew_low_pctile` / `skew_high_pctile` in `ips.yaml` |
| `term_contango_tolerance` | `market_environment.term_contango_tolerance` in `ips.yaml` |
| `historical_vol_low` / `historical_vol_high` | were `HedgeHealthDashboard(...)` constructor arguments (class deleted in Stage 4.3), defaulted from `ips_config.DEFAULT_VOL_REGIME_LOW` / `_HIGH` — the same constants still backing `market_environment.vol_regime_low` / `_high` |

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
| `delta_drift` | \|deviation\| from the target net-delta ratio, in pp | 0.0 to 30.0 | 5.0 / 7.5 / 10.0 | **`true`** |
| `convexity_cliff` | Days until long puts enter the high-gamma region | 0 to 365 | *(policy — see below)* | `false` |
| `vol_regime` | Current IV percentile (0=cheap, 100=expensive) | 0 to 100 | 25 / 50 / 75 | **`true`** |
| `hedge_success` | Hedge P&L vs. cumulative carry paid | -200 to 200 | -100 / 0 / 100 | `false` |

`vol_regime` and `delta_drift` are the two metrics that invert. For
`vol_regime` a **low** IV percentile (cheap vol, below `min_val`) is
good/green and a **high** percentile (expensive vol, above `max_val`) is
bad/red; for `delta_drift` a small deviation from target is good. Both are
backwards from the rest, where low is bad and high is good.

Two rows deserve a closer look, because both have been mistaken for policy:

- **`convexity_cliff` carries no bands here.** Its grading lines are policy
  and live in `ips.yaml` as `convexity.cliff_urgent_days` (30),
  `cliff_review_days` (90) and `cliff_threshold_days` (180) — the last of
  which also sets where the high-gamma region begins. `#241` removed the
  duplicate copy; the Dash `/design` convexity cliff panel reads the IPS
  values directly, and this gauge falls back to the widget's hardcoded
  defaults, obsolete along with the Jupyter surface (#242).
- **`vega_sufficiency` here is not the vega sufficiency band.** This is a
  signed, symmetric display axis (-50 to +50, green above +20, nothing bad
  above it). The policy band is `vega.sufficiency_min_pct` /
  `sufficiency_max_pct` in `ips.yaml`, is one-sided, and sits on a
  low-single-digit scale — real books read +1.8% to +2.7%, because the
  metric divides by total portfolio value including the equity leg. M2.7
  seeded the IPS band from this gauge's `max_val: 20` and `end: 50`, which
  produced a band no book could reach; #241 recalibrated it. Do not read one
  as the other.

Values shown were the shipped defaults, from the deleted
`HedgeHealthDashboard._get_default_config()`. They are still reproduced and
commented in `examples/dashboard/dashboard_config_default.yaml` — with the
`convexity_cliff` bands omitted there, since they are policy.

## How it's loaded

**It isn't, by anything that runs.** `deltadewa/dashboard/session.py`'s
`_load_dashboard_config` still parses `config/dashboard.yaml` into
`SessionContext.dashboard_config` — and nothing reads that field. The two
consumers this section used to describe, `HedgeHealthDashboard`'s
built-in-default fallback and its `display_config_loader()` FileUpload
widget, were deleted with the class in Stage 4.3. Neither `/monitor` nor
`/design` has ever read this file.

`config/dashboard.yaml` remains gitignored, holding this program's real
presentation values rather than being shipped (#245); `config/dashboard.example.yaml`
is the tracked template. Copying it is harmless and currently inert.

## Aggressive vs. conservative presets

`examples/dashboard/` ships two alternate presets alongside the default.
Nothing loads them — see the note at the top of this guide. Copying one over
`config/dashboard.yaml` changes no rendered output today; they are kept as a
record of the intended postures.

- **`dashboard_config_aggressive.yaml`** — every band is widened and
  shifted to tolerate more risk: e.g. `crash_convexity.min_val` relaxes
  from -10.0 to -15.0 (alerts later on a worse crash loss),
  `vol_regime.max_val` rises from 75 to 80 (tolerates pricier vol before
  flagging red). Pick this for active trading where you're comfortable
  riding closer to the edge before the dashboard flags it.
- **`dashboard_config_conservative.yaml`** — every band tightens: e.g.
  `crash_convexity.min_val` tightens from -10.0 to -5.0 (alerts sooner),
  `vol_regime.max_val` drops from 75 to 70 (flags red sooner on expensive
  vol). Pick this for risk-averse mandates where you want alerts to fire
  earlier and hold the book to a higher bar.

**A preset only changes the display.** An aggressive or conservative
*posture* is a policy choice, so the thresholds that go with it are not in
these files — each preset's header lists the `ips.yaml` keys to set
alongside it (`convexity.cliff_*`, `vega.sufficiency_*`,
`market_environment.*`). Copying a preset over `config/dashboard.yaml`
without setting those changes how the book is drawn, not how it is run.

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
