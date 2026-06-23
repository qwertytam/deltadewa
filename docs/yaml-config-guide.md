# YAML Configuration Guide

`deltadewa` uses YAML in two unrelated ways. Keeping them straight matters:

- **`config/`** — live files the app reads automatically at startup
  (`config/ips.yaml`, `config/dashboard.yaml`). Edit these in place to
  change behaviour.
- **`examples/`** — sample files (`examples/portfolios/`, `examples/ips/`,
  `examples/dashboard/`). Nothing reads these automatically. Portfolios
  are loaded by importing the file through a widget; `ips`/`dashboard`
  presets are loaded by copying them over the corresponding file in
  `config/`.

## Portfolios

A portfolio YAML file has two top-level sections:

```yaml
market_parameters:
  spot_price: 100.0
  volatility: 0.20
  risk_free_rate: 0.04
  dividend_yield: 0.015
  underlying_quantity: 5000.0    # optional, default 0.0
  symbol: "SPY"                  # optional, default "UNKNOWN"

positions:
  - option_type: "put"
    strike_price: 95.0
    maturity_days: 30            # or: maturity_date: "2026-07-20"
    quantity: 50                 # positive = long, negative = short

  - option_type: "call"
    strike_price: 105.0
    maturity_days: 30
    quantity: -50
    volatility: 0.18             # optional, overrides market_parameters
```

This is the actual shape `PortfolioSerializer.import_from_yaml()`
(`deltadewa/persistence.py`) parses — see `examples/portfolios/spy_collar.yaml`
for a complete worked example.

**`market_parameters`**: `spot_price`, `volatility`, `risk_free_rate`, and
`dividend_yield` are required. `underlying_quantity` and `symbol` are
optional.

**Each position** needs `option_type` ("call" or "put"), `strike_price`,
`quantity`, and **either** `maturity_date` (an ISO date string) **or**
`maturity_days` (an integer, relative to today) — not both, but either
works. `volatility` is optional and overrides `market_parameters.volatility`
for that position only.

Two more optional per-position fields, `entry_spot` and `entry_date`, record
the spot price and date the position was opened. They round-trip through
export/import but aren't required to author a file by hand. **None of the
files under `examples/portfolios/` set them** — importing one leaves
`entry_spot` as `None`, which means Roll Status's moneyness-drift column
shows `n/a` for that tranche until you re-enter the position with a real
`entry_spot` (or set it directly on the position after import).

Files you export from the dashboard also include `greeks`, `price`,
`position_value`, `contract_size`, and a `metadata` block. These are
written for inspection but ignored on import — they get recomputed fresh
from the option's market parameters, so you don't need them in a
hand-written file.

There's no per-position `symbol` override — every position uses
`market_parameters.symbol`.

### Loading a portfolio

Both `monitor_dashboard.ipynb` and `hedge_design.ipynb` have an **Import
Portfolio** cell (a file-upload + filename-entry widget,
`PortfolioWidgets.display_import()` in `deltadewa/widgets/export_controls.py`).
This is the only way a portfolio YAML/JSON file gets into a session —
nothing is auto-detected at startup. If you don't import anything, Monitor
starts with an empty book and Design falls back to a small built-in demo
portfolio.

The filename field accepts a path, not just a bare name — e.g.
`examples/portfolios/spy_collar.yaml` loads that example directly, relative
to the notebook's working directory, without copying it into the export
directory first. A bare name like `portfolio_book.json` still resolves
against the export directory, as before.

## IPS policy (`config/ips.yaml`)

`start_session()` (`deltadewa/dashboard/session.py`) loads
`config/ips.yaml` by default (`ips_path` parameter). If the file is
missing or fails validation, the session still starts — `ctx.ips_config`
is `None` and a warning is logged; nothing raises.

Presets live in `examples/ips/` (e.g. `ips_default.yaml`) — copy one over
`config/ips.yaml` to use it. The schema (program identity, pricing style,
budget, convexity targets, drawdown tolerance, roll/rally/monetization
triggers) is defined and validated in `deltadewa/ips_config.py` — see that
module for the authoritative field list and validation rules rather than a
duplicate copy here.

## Dashboard config (`config/dashboard.yaml`)

`start_session()` also loads `config/dashboard.yaml` by default
(`dashboard_path` parameter), the same way: missing or invalid → a warning
and `ctx.dashboard_config` is `None`, never a hard failure. This config
feeds `HedgeHealthDashboard`'s gauge ranges (crash convexity, vega
sufficiency, delta drift, etc.).

Presets live in `examples/dashboard/`. See
[dashboard-config-guide.md](dashboard-config-guide.md) for the schema.
