# Market data — what is connected, and what is not

The one place that answers *"what market data are we looking to connect
up?"*. Read it before assuming a number on either page is observed: most
of the pricing inputs are not.

Two things are true at once and are easy to conflate:

- The app **observes** six index-level readings, refreshed nightly.
- The app **prices the book** off hand-entered values — per-leg implied
  volatility, the risk-free rate, the dividend yield, and spot.

The provenance banner grades only the first group. A book priced on a
months-old hand-entered volatility still shows a clean banner.

## Observed readings

All six are warmed by the nightly refresh job
(`deltadewa/marketdata/refresh.py`), which runs **daily, seven days a
week** — CBOE and FRED are closed at weekends, so a weekend run
re-observes Friday's close rather than leaving a 72-hour gap for the TTL
to absorb. See RUNBOOK §9 for the crontab line and §11 to run it by hand.

| Reading | Provider method | Source | Cache key | Read by |
| --- | --- | --- | --- | --- |
| VIX | `get_vix` | FRED `VIXCLS` | `vix_fred` | `assess_market_environment`, `analysis/health.py` |
| VIX history (252d) | `get_vix_history` | FRED `VIXCLS` | `vix_fred` (shared) | `analysis/health.py` |
| VIX term structure | `get_vix_term_structure` | CBOE (5 legs) | `spot_VIX9D`, `spot_VIX`, `spot_VIX3M`, `spot_VIX6M`, `spot_VIX1Y` | `assess_market_environment` |
| SKEW index | `get_skew_index` | CBOE | `spot_SKEW` | `assess_market_environment` |
| SKEW percentile | `get_skew_percentile` | CBOE | `skew_percentile_history` | `assess_market_environment` |
| **Spot (SPX)** | `get_spot` | CBOE | `spot_SPX` | `analysis.spot_reading.observe_spot`, `/monitor` (#336) |

Notes on the table:

- **Six readings, nine cache files.** `vix`/`vix_history` deliberately
  share `vix_fred`; the term structure fans out to five.
- **VIX arrives twice, from two sources.** The headline VIX comes from
  FRED (`vix_fred`); the term structure's front leg is CBOE
  (`spot_VIX`). They are the same index and will normally agree, but
  they are separately cached and can disagree on a partial-refresh day.
- **Spot is read by `/monitor`, as a cross-check, not a pricing input.**
  Its original consumer, `dashboard.session`, was deleted in #279 with the
  Jupyter layer, leaving the fetch orphaned. #322 decided to wire it
  rather than retire it, on the grounds of what `/monitor` is for; #336
  built the wiring — `analysis.spot_reading.observe_spot` reads this cache
  key and `/monitor` renders it beside the book's hand-entered spot,
  labelled with its quality (CACHED/STALE/UNAVAILABLE) and age. It still
  never feeds a calculation: every number on the page is computed from the
  book spot, never the observed one.
- Each series is fetched independently — one failure never aborts the run,
  and a failed series' previous cache entry is left untouched, because
  the disk cache only writes on success.

## Hand-entered inputs, which never refresh

These come from the loaded portfolio (or `/design`'s position editor) and
have **no market feed behind them at all** — nothing in the app updates
them. Three of the four are also unflagged: nothing on either page notes
their age.

| Input | Where it is set | Refresh path |
| --- | --- | --- |
| Per-leg implied volatility | Position record | None — hand-entered, unflagged |
| Risk-free rate | `market_parameters` on the book | None — hand-entered, unflagged |
| Dividend yield | `market_parameters` on the book | None — hand-entered, unflagged |
| **Spot price** | `market_parameters` on the book | None — changes only on portfolio import, but see below |

Spot is the one that matters most, because it is the reference point
almost every other number is measured against — crash convexity, roll
OTM%, every drift trigger, hedge value, the monetization gain. A stale
spot biases all of them in the same direction. It is still never
refreshed itself, but as of #336 it is no longer unflagged: `/monitor`
shows it beside the independently observed market spot (see the
"Observed readings" table above), so a divergence past
`market_environment.spot_divergence_warn_pct` in `ips.yaml` is visible
rather than silent. The other three hand-entered inputs have no such
cross-check — nothing observes per-leg IV, the risk-free rate, or the
dividend yield, so those three stay unflagged.

## How freshness is graded

`Observation` carries two timestamps, and they answer different
questions:

- **`as_of`** — the *source series'* observation date. A Saturday run
  fetching Friday's close reports `as_of=Friday`.
- **`fetched_at`** — when this deployment last retrieved it.

**Staleness is measured against `fetched_at`, not `as_of`.** So a Monday
read of Friday's close grades as fresh if the cron wrote recently, even
though the datum itself is three days old. That is intended — the TTL
governs "has our refresh job stopped working?", not "has the market
moved?".

The boundary is policy, not a provider constant: it comes from
`market_environment.data_ttl_minutes` in `ips.yaml`. See
[yaml-config-guide.md](yaml-config-guide.md#disk-cache-and-ttl).

The deployed app is **read-only** by construction (`create_app` rejects a
fetch-capable provider), so it can reach only three of the five grades:

| Grade | Meaning | Banner |
| --- | --- | --- |
| `CACHED` | Cache entry within the TTL | None — the as-of stamp only |
| `STALE` | Cache entry exists but is past the TTL | Yes |
| `UNAVAILABLE` | No cache entry at all — cold start, or a refresh job that has never run against this key | Yes |

`LIVE` is reachable only by the refresh job itself, the one process
permitted to fetch. `STATIC` is the synthetic `StaticProvider` used in
tests and offline runs; it is never constructed by the deployed app.

Two consequences worth knowing:

- `UNAVAILABLE` on a running deployment usually means the cache *key* is
  missing, not that the network is down — the read-only provider prefers
  an arbitrarily stale cache entry over failing. A key that appears only
  after a code change (as `skew_percentile_history` did in #185) will
  read `UNAVAILABLE` until the refresh job that knows about it has run.
  That is exactly the #293 app/jobs image-drift failure mode.
- `assess_market_environment` degrades **all** its readings together: if
  any one of its four fetches raises, the whole environment reports
  `UNAVAILABLE`, with nothing in the app logs naming the failing series.

## What is not connected

There is **no options-chain feed**. The app has no per-strike implied
volatility, no bid/ask, and no open interest. Consequences:

- Every leg is priced on its hand-entered volatility.
- Part X **#12 Liquidity Risk** cannot be built — it needs per-strike
  bid/ask and open interest. See `part-x-coverage.md`.

Connecting a real chain feed is tracked in #156, and is the blocker on
both of the above.

## Where the data lives

- **On disk:** `exports/marketdata-cache/`, one JSON file per cache key,
  each holding `{"value": …, "fetched_at": …}`. Both the `app` and `jobs`
  containers point at it via `DELTADEWA_CACHE_DIR` so a refresh actually
  warms what the app reads.
- **Endpoints and credentials:** see
  [yaml-config-guide.md](yaml-config-guide.md#live-market-data). Both
  endpoints are public; no API key is required for the six readings
  above.
