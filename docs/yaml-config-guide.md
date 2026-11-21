# YAML Configuration Guide

> **Navigation:** [README](../README.md) · [part-x-coverage.md](part-x-coverage.md) · [deltadewa-handbook](https://github.com/qwertytam/deltadewa-handbook)

`deltadewa` uses YAML in two unrelated ways. Keeping them straight matters:

- **`config/`** — the live file the app reads automatically at startup
  (`config/ips.yaml`). Edit it in place to change behaviour. It holds this
  program's *real* policy values and is gitignored, not shipped (#245) —
  before it exists, copy the tracked template:

  ```bash
  cp config/ips.example.yaml config/ips.yaml
  ```

  A missing `config/ips.yaml` isn't silently patched over with the example's
  placeholder numbers — `load_ips_config` raises, naming the file and
  pointing at the `.example`, and every consumer degrades visibly from
  there (see the README's Configuration section).
- **`examples/`** — sample files (`examples/portfolios/`, `examples/ips/`).
  Nothing reads these automatically. Portfolios are loaded by importing the
  file through `/design`; IPS presets are loaded by copying them over
  `config/ips.yaml`. Distinct from `config/ips.example.yaml`, which is the
  canonical one-time bootstrap template: `examples/ips/ips_default.yaml` is
  an illustration of the IPS schema carrying the *same* placeholder numbers
  as `config/ips.example.yaml`.

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

## Dashboard config (`config/dashboard.yaml`) — retired

There is no second config file. `config/dashboard.yaml` held gauge
presentation geometry for `HedgeHealthDashboard`
(`widgets/health_dashboard.py`), the Jupyter gauge wall; that widget went in
Stage 4.3, its loader went in #279, and #279 retired the file, its
`.example` template, the `examples/dashboard/` presets and their guide.

The gauge *bands* that turned out to be policy had already been promoted
into `ips.yaml` (#241 and M2.7): the vega sufficiency band and the
convexity-cliff lines. Only geometry was lost, and #259/#260 both declined
to bring it back. See `part-x-coverage.md`,
"`config/dashboard.yaml` had no reader — and then no loader (#279)", and
"Where the vega band went", before adding a second config file.

## Live market data

This section covers the *configuration* surface. For the reading-by-reading
map — which series are observed, from which source, on what cadence, and
which pricing inputs are fetched and which hand-entered — see
[market-data.md](market-data.md).

The deployed app always constructs a `CboeFredProvider` in **read-only**
mode (`deltadewa/app/wsgi.py`): it serves the shared disk cache described
below and never makes a network call of its own. `create_app` enforces
that structurally, rejecting a fetch-capable provider. The market-data
refresh cron is the only process permitted to fetch — see the RUNBOOK for
its crontab line.

`StaticProvider` is a synthetic no-I/O provider for tests and offline
runs. It is not constructed by the deployed app.

### Endpoints

Two public endpoints are used — no API key required:

| Source | Host | Data |
| --- | --- | --- |
| CBOE CDN | `cdn.cboe.com` | SPX, VIX9D/VIX/VIX3M/VIX6M/VIX1Y, SKEW (daily CSV) |
| CBOE CDN (delayed quotes) | `cdn.cboe.com` (redirects to `cdn-api.cboe.com`) | The SPX option chain (JSON, about 13 MB), only with a `pricing_feed` section |
| FRED | `fred.stlouisfed.org` | VIXCLS, and the `pricing_feed.rate_series` Treasury series (daily CSV) |

Data is delayed/end-of-day, not real-time. Check CBOE's and FRED's own
terms before redistributing pulled values outside this session.

### Disk cache and TTL

`CboeFredProvider` caches each successful response to disk (by default
`~/.cache/deltadewa/marketdata/`, or `DELTADEWA_CACHE_DIR` if set — the
deployed app and its refresh cron both point this at the `./cache` bind
mount, outside `exports/`, so they share one cache that never rides the
offsite backup) with a TTL per endpoint. A fresh entry within that window
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

### When a reading is missing

The app never falls back to synthetic data. A cache entry past the TTL is
served as `STALE`; a cache key with no entry at all raises, and the
affected surface reports `UNAVAILABLE`. Both states are shown in the
provenance banner rather than silently substituted. See
[market-data.md](market-data.md#how-freshness-is-graded) for the grades
and what each one means.

### Hand-entered pricing inputs (`pricing_inputs`)

`data_ttl_minutes` above bounds a *fetched* reading's age; it says nothing
about the four inputs a book is actually priced on when they are
hand-entered (per-leg IV, spot, the risk-free rate, the dividend yield —
#367). `pricing_inputs` is the analogous policy for those:
`spot_max_age_days`, `volatility_max_age_days`,
`risk_free_rate_max_age_days`, and `dividend_yield_max_age_days`, each the
maximum number of days a stamped input may go unconfirmed before the
provenance banner and `/health`'s `pricing_inputs` object grade it
`AGING`. Optional — a missing section, like `market_environment`/`sizing`/
`vega`, falls back to the module defaults (1/7/30/90 days). See
[market-data.md](market-data.md#hand-entered-inputs)
for what a confirmation stamp means and when it is set, and
`deltadewa/ips_config.py` for the authoritative field list.

### Fetched pricing inputs (`pricing_feed`)

Optional, and with **no code defaults**: omit the whole section and nothing
is fetched and every pricing input stays hand-entered. If the section is
present, every key is required (a partial section is an error), and
`ips_config --check` lists an absent one under "optional sections that have
NO code defaults". Both shipped templates carry it with `adopt: []` and
`chain_source: none`.

| Key | Meaning |
| --- | --- |
| `adopt` | The inputs a feed may **price** the book on: any of `spot`, `risk_free_rate`, `volatility`; `[]` fetches and shows only. `dividend_yield` is refused: put-call parity cannot isolate it (9b.0). Read at start: the app prices the book on what `adopt` names, once, when it starts (RUNBOOK §4.1: a page reload does not re-read prices, only a restart does). Your typed values stay in the book file as the override and the fallback |
| `rate_series` | The FRED constant-maturity series standing for the book's one rate: `DGS1MO`, `DGS3MO`, `DGS6MO`, `DGS1`, `DGS2`, `DGS3`, `DGS5`, `DGS7`, `DGS10`, `DGS20` or `DGS30`. `DGS1` suits 6-18 month options |
| `chain_source` | Where the option chain comes from: `none` or `cboe`. `none` fetches no chain: `volatility` cannot then be adopted (a validation error), and an adopted `spot` is the index close. `cboe` is Cboe's delayed-quote file, which Cboe has blocked to automated clients since November 2026 ([market-data.md](market-data.md#fetched-pricing-inputs-9b)) |
| `max_quote_age_days` | Calendar days between the program's date and the chain's trading session beyond which a fetched quote is not used (`STALE-QUOTE`). 5 spans a long weekend plus a missed night |
| `max_spread_pct` | Percent of mid. A quote wider than this yields no IV (`WIDE`). The strikes a hedge ladder uses quoted 2-5% wide at the close in the spike |
| `override_warn_vol_points` | Vol points. The Pricing inputs review warns when an IV you override differs from the fetched one by more than this |

See [market-data.md](market-data.md#fetched-pricing-inputs-9b) for the
rules these keys feed.
