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
    exercise_style: "EUROPEAN"   # optional: "EUROPEAN" or omit (defaults to American)
    entry_spot: 100.0            # optional: spot at entry (enables roll-status drift)
    entry_premium: 3.50          # optional: cost basis (enables payoff ratio)
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

Three more optional per-position fields support tracking and exercise style:

- `entry_spot` and `entry_date` record the spot price and date the position
  was opened.  They round-trip through export/import but aren't required to
  author a file by hand.  Without them, Roll Status's moneyness-drift column
  shows `n/a` and the monetisation panel cannot compute an unrealised gain.
- `entry_premium` records the premium paid (or received) per index unit.
  Without it, the payoff-ratio column also shows `n/a`.
- `exercise_style` sets the pricing engine for that position: `"EUROPEAN"`
  uses the analytic Black–Scholes engine; omitting it (or any other value)
  falls back to the American approximation.  **SPX positions must set
  `exercise_style: "EUROPEAN"`** — SPX options are cash-settled European and
  the American approximation overstates put values.

See `examples/portfolios/spx_protective_put.yaml` for a canonical SPX
tail-hedge example with all three fields populated so every analytics
panel — roll status, payoff ratio, crash convexity, and monetisation —
produces non-degenerate output on first import.

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

## Live market data

By default both notebooks use **static/offline data** seeded from the
loaded portfolio's own values. No network calls are made in this mode and
offline/gated runs are fully deterministic.

To pull live end-of-day data, set the toggle near the top of the setup
cell before running `start_session`:

```python
_USE_LIVE = True   # set True for live CBOE/FRED market data (needs internet)
```

### Endpoints

Two public endpoints are used — no API key required:

| Source | Host | Data |
| --- | --- | --- |
| CBOE CDN | `cdn.cboe.com` | SPX, VIX9D/VIX/VIX3M/VIX6M/VIX1Y, SKEW (daily CSV) |
| FRED | `fred.stlouisfed.org` | VIXCLS series (daily CSV) |

Data is delayed/end-of-day, not real-time. Check CBOE's and FRED's own
terms before redistributing pulled values outside this session.

### Disk cache and TTL

`CboeFredProvider` caches each successful response to disk
(`~/.cache/deltadewa/marketdata/` by default) with a **15-minute TTL**
per endpoint. A fresh entry within that window is served from cache with
no HTTP request. On network failure the provider falls back to the last
cached value (regardless of TTL); if no cached value exists and the
network is unreachable, a `MarketDataError` is raised.

### Offline fallback

`start_session` catches `MarketDataError` automatically: it warns via the
reporter and falls back to `StaticProvider` (seeded from the portfolio's
own values), so the session always starts. The effective source is
recorded in `ctx.market_data_source` and displayed in the **Market
Context** (`Data:` line) and **Market Environment** panels:

| `ctx.market_data_source` | Meaning |
| --- | --- |
| `"live"` | `CboeFredProvider` is connected; data is live |
| `"static"` | `_USE_LIVE = False` (deliberate offline mode) |
| `"static (live unavailable)"` | `_USE_LIVE = True` but network unreachable; fell back to static |
