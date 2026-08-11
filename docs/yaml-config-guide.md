# YAML Configuration Guide

> **Navigation:** [README](../README.md) · [dashboard-config-guide.md](dashboard-config-guide.md) · [hedging handbook.md](hedging%20handbook.md)

`deltadewa` uses YAML in two unrelated ways. Keeping them straight matters:

- **`config/`** — live files the app reads automatically at startup
  (`config/ips.yaml`, `config/dashboard.yaml`). Edit these in place to
  change behaviour. Both hold this program's *real* policy/presentation
  values and are gitignored, not shipped (#245) — before either exists,
  copy the tracked templates:

  ```bash
  cp config/ips.example.yaml config/ips.yaml
  cp config/dashboard.example.yaml config/dashboard.yaml
  ```

  A missing `config/ips.yaml` isn't silently patched over with the example's
  placeholder numbers — `load_ips_config` raises, naming the file and
  pointing at the `.example`, and every consumer degrades visibly from
  there (see the README's Configuration section).
- **`examples/`** — sample files (`examples/portfolios/`, `examples/ips/`,
  `examples/dashboard/`). Nothing reads these automatically. Portfolios
  are loaded by importing the file through a widget; `ips`/`dashboard`
  presets are loaded by copying them over the corresponding file in
  `config/`. Distinct from `config/*.example.yaml`, which are the
  canonical one-time bootstrap templates: `examples/dashboard/` holds
  alternate presentation postures (aggressive/conservative/default), and
  `examples/ips/ips_default.yaml` is an illustration of the IPS schema
  carrying the *same* placeholder numbers as `config/ips.example.yaml`.

  **Nothing under `examples/` is this program's policy.** It used to be:
  `ips_default.yaml` shipped a byte-for-byte copy of the live
  `config/ips.yaml` until #249. Do not re-sync it against the live file —
  the repo deliberately carries one set of example policy numbers, not
  two that can drift back together.

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
  contract_size: 100             # required; 100 for SPX and SPY, 1 for single-name equities

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
(`deltadewa/persistence.py`) parses — see `examples/portfolios/spx_protective_put.yaml`
for the canonical SPX tail-hedge example, or `examples/portfolios/spy_collar.yaml`
for a multi-leg collar.

**`market_parameters`**: `spot_price`, `volatility`, `risk_free_rate`,
`dividend_yield`, and `contract_size` are required. `underlying_quantity` and
`symbol` are optional.

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

`/design`'s BOOK zone has a guarded **Import portfolio** control
(`deltadewa/app/import_portfolio.py`). This is the only way a portfolio
YAML/JSON file gets into the app — nothing is auto-detected at startup.
The import is confirm-gated, because it replaces the shared `ProgramState`
book rather than opening a private session copy.

The filename field accepts a path, not just a bare name — e.g.
`examples/portfolios/spy_collar.yaml` loads that example directly, relative
to the process working directory, without copying it into the export
directory first. A bare name like `portfolio_book.json` still resolves
against the export directory.

## IPS policy (`config/ips.yaml`)

The Dash app loads `config/ips.yaml` at startup. If the file is missing or
fails validation the loader **raises**, and every consumer degrades visibly
rather than silently: `/monitor` and `/design` render an explicit "No IPS
policy is loaded" screen and the weekly digest refuses to build.

### `program.timezone` — the trading calendar

`program.timezone` (default `America/New_York`) is the market calendar the
program's day follows. It is **policy, not presentation**: QuantLib takes its
valuation date from the calendar fields of a timezone-aware datetime, so this
setting decides which day's close every position is priced against.

Before #182 the program's day was implicitly UTC, which rolled the whole book
forward at 20:00 New York — a US desk reviewing the book after dinner saw a
21-day SPX put drop 7.3% in value from the clock alone, with no market move
behind it. Set this to the exchange your program actually trades on.

An unrecognised zone is a load error, not a silent fallback: pricing the book
on a calendar the policy did not ask for is exactly the quiet wrongness the
loader exists to prevent.

To bootstrap the file, copy the canonical template —
`cp config/ips.example.yaml config/ips.yaml` — then edit every field it
marks `EXAMPLE VALUE`. `examples/ips/ips_default.yaml` is a second copy of
those same placeholder numbers, kept as a standalone illustration of the
schema; it is not a distinct posture and is not this program's policy
(#249). The schema (program identity, pricing style,
budget, convexity targets, drawdown tolerance, roll/rally/monetization
triggers) is defined and validated in `deltadewa/ips_config.py` — see that
module for the authoritative field list and validation rules rather than a
duplicate copy here.

## Dashboard config (`config/dashboard.yaml`)

**Nothing reads this file.** Its only consumer was `HedgeHealthDashboard`
(`widgets/health_dashboard.py`), the Jupyter gauge wall, deleted in Stage
4.3 along with the notebooks. The file, its `.example` template and the
`examples/dashboard/` presets are kept pending a decision on whether the
Dash pages should read banded gauge geometry from config — see
`part-x-coverage.md`, "Stage 4.3". Editing it changes nothing today.

Note that gauge *bands* which turned out to be policy have already been
promoted out of here into `ips.yaml` (#241): the vega sufficiency band and
the convexity-cliff lines. See `part-x-coverage.md`, "Where the vega band
went", before moving any number in the other direction.

See [dashboard-config-guide.md](dashboard-config-guide.md) for the schema.

## Live market data

By default the app uses **static/offline data** seeded from the loaded
portfolio's own values. No network calls are made in this mode and
offline/gated runs are fully deterministic.

Live end-of-day data is enabled per-deployment rather than per-session —
see the RUNBOOK for the market-data refresh cron, which populates the
shared disk cache described below.

### Endpoints

Two public endpoints are used — no API key required:

| Source | Host | Data |
| --- | --- | --- |
| CBOE CDN | `cdn.cboe.com` | SPX, VIX9D/VIX/VIX3M/VIX6M/VIX1Y, SKEW (daily CSV) |
| FRED | `fred.stlouisfed.org` | VIXCLS series (daily CSV) |

Data is delayed/end-of-day, not real-time. Check CBOE's and FRED's own
terms before redistributing pulled values outside this session.

### Disk cache and TTL

`CboeFredProvider` caches each successful response to disk (by default
`~/.cache/deltadewa/marketdata/`, or `DELTADEWA_CACHE_DIR` if set — the
deployed app and its refresh cron both point this at `exports/` so they
share one cache) with a TTL per endpoint. A fresh entry within that window
is served from cache with no HTTP request. On network failure the provider
falls back to the last cached value (regardless of TTL); if no cached value
exists and the network is unreachable, a `MarketDataError` is raised.

The TTL is policy, not a provider constant: it comes from
`market_environment.data_ttl_minutes` in `ips.yaml` — the CACHED/STALE
boundary is "how old may data be before a decision shouldn't rely on it,"
which is a program decision. The provider's own constructor default
(15 minutes) only applies when no `ips.yaml` is available. Set it to
roughly 1.5x your own refresh cadence — a deployment on M2.6's daily
market-data cron wants a TTL comfortably past 24h, so ordinary cron
jitter doesn't flap the banner while one fully-missed refresh still reads
STALE. `config/ips.example.yaml` ships an illustrative value; your own
`config/ips.yaml` is gitignored and not shipped (#245).

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
