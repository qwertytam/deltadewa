# Dashboard Config Guide

`config/dashboard.yaml` controls the gauge ranges `HedgeHealthDashboard`
(`deltadewa/widgets/health_dashboard.py`) uses for its seven health metrics.
It's presentation-only — it changes how the dashboard displays health, not
the underlying numbers. (Program policy — carry budget, convexity targets,
roll/monetization triggers — belongs in `config/ips.yaml` instead; see
[yaml-config-guide.md](yaml-config-guide.md).)

`start_session()` loads `config/dashboard.yaml` automatically. Missing or
invalid → a warning and `ctx.dashboard_config` is `None`; the dashboard
falls back to its built-in defaults, which are identical to the shipped
`config/dashboard.yaml` values below.

## Schema

```yaml
parameters:
  historical_vol_low: 0.15     # 25th percentile IV (low vol = cheap hedges)
  historical_vol_high: 0.35    # 75th percentile IV (high vol = expensive)
  convexity_cliff_days: 180    # alert window before puts enter high-gamma

metrics:
  <metric_name>:
    start: <float>             # gauge start value
    end: <float>                # gauge end value
    min_val: <float>            # red-zone boundary
    mid_val: <float>            # neutral/yellow point
    max_val: <float>            # green-zone boundary
    invert_colors: <bool>       # true: low=green/high=red instead of the default
```

`metrics` keys (all seven required by `_get_default_config()`'s shape,
though `load_config()` will merge a partial file — any metric you omit
keeps its built-in default): `net_carry`, `crash_convexity`,
`vega_sufficiency`, `delta_drift`, `convexity_cliff`, `vol_regime`,
`hedge_success`.

See `examples/dashboard/dashboard_config_default.yaml` for the full,
annotated reference values (also shown via `_get_default_config()` in
`health_dashboard.py`), and `examples/dashboard/dashboard_config_aggressive.yaml`
/ `dashboard_config_conservative.yaml` for alternate presets — copy one
over `config/dashboard.yaml` to use it.

## Ad hoc overrides

Independent of whatever `start_session` loaded, `HedgeHealthDashboard`
also exposes `display_config_loader()` — a FileUpload widget in the
notebook that lets you layer a different YAML/JSON config on top at
runtime, without touching `config/dashboard.yaml`.
