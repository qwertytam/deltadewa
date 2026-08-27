# Market data — what is connected, and what is not

The one place that answers *"what market data are we looking to connect
up?"*. Read it before assuming a number on either page is observed: most
of the pricing inputs are not.

Two things are true at once and are easy to conflate:

- The app **observes** six index-level readings, refreshed nightly.
- The app **prices the book** off hand-entered values — per-leg implied
  volatility, the risk-free rate, the dividend yield, and spot.

Batch 3d (#367/#368) closed the gap this section used to describe: the
provenance banner used to grade only the first group, so a book priced
on a months-old hand-entered volatility still showed a clean banner.
It now grades both, through one `ProvenanceLedger` — see
["How freshness is graded"](#how-freshness-is-graded) below for the two
distinct freshness models this actually requires, since a hand-entered
value has no feed to compare against.

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
them automatically. Every one of the four is now flagged, though not all
the same way (#367):

| Input | Where it is set | Refresh path | Staleness signal |
| --- | --- | --- | --- |
| Per-leg implied volatility | `OptionPosition.volatility_as_of` | None — hand-entered | Confirmation age, vs. `pricing_inputs.volatility_max_age_days` |
| Risk-free rate | `MarketParameterStamps.risk_free_rate_as_of` on the book | None — hand-entered | Confirmation age, vs. `pricing_inputs.risk_free_rate_max_age_days` |
| Dividend yield | `MarketParameterStamps.dividend_yield_as_of` on the book | None — hand-entered | Confirmation age, vs. `pricing_inputs.dividend_yield_max_age_days` |
| **Spot price** | `MarketParameterStamps.spot_as_of` on the book | None — changes only on portfolio import, but see below | Confirmation age (above) **and** the #336 observed-spot cross-check (below) |

Spot is the one that matters most, because it is the reference point
almost every other number is measured against — crash convexity, roll
OTM%, every drift trigger, hedge value, the monetization gain. A stale
spot biases all of them in the same direction. It is still never
refreshed itself, but as of #336 it carries a second, independent signal
beyond the confirmation age above: `/monitor` shows it beside the
independently observed market spot (see the "Observed readings" table
above), so a divergence past `market_environment.spot_divergence_warn_pct`
in `ips.yaml` is visible rather than silent. The other three hand-entered
inputs have no observed counterpart to cross-check against — nothing
fetches per-leg IV, the risk-free rate, or the dividend yield — so
confirmation age is the only signal available for them, and it is a
review cadence, not a market fact: it answers "how long since a human
last confirmed this number," not "has the market moved."

### Confirmation stamps: what they mean, and what they don't

A stamp (`deltadewa.portfolio.stamps.MarketParameterStamps`, and
`OptionPosition.volatility_as_of` for the per-leg case) records **when a
human last confirmed this value**, not when the underlying datum was
observed — there is no feed to observe it from. An operator who types a
rate on 2026-08-26 from a note written in June stamps 2026-08-26; the
program cannot tell that apart from a rate confirmed against a live
source that same day. This is the honest limit of a hand-entered input,
not a bug.

Stamping is a side effect of a mutator actually **changing** the value it
stamps (`OptionPortfolioBase.update_market_conditions`/`set_volatility`/
`update_position`) — never of a no-op call, so re-saving or re-importing
an unchanged file cannot launder a stale input into looking freshly
confirmed. The one deliberate exception is
`OptionPortfolioBase.confirm_current_inputs` (wired to
`ProgramState.mark_inputs_reviewed`, confirm-gated, and to /design's
"Mark pricing inputs reviewed" control): reviewing a book and finding
every number still correct is itself a confirmation, so this stamps
unconditionally.

A book or position that predates this feature — or one whose inputs have
simply never been (re-)confirmed — carries `None` stamps. That reads as
`Freshness.UNKNOWN`, a distinct and *worse* grade than a stamped-but-old
value (`AGING`): an unconfirmed input's damage is unbounded (it could be
five minutes or five years out of date), while an aging one's is at
least bounded by its known age. `None` never defaults to "now" — that
would launder every pre-existing stale input into a clean banner the
first time this code ran, the exact failure #367 exists to close.

## How freshness is graded

Two different models, for two different kinds of input — there is no
single scale that covers both honestly, which is why `analysis.provenance`
keeps them as a distinct `Freshness` vocabulary (`FRESH`/`AGING`/
`UNKNOWN`/`MISSING`) rather than forcing hand-entered inputs onto
`DataQuality`.

### Fetched readings

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
- `assess_market_environment` still degrades **all** its readings
  together for the combined grade: if any one of its four fetches
  raises, the whole environment reports `UNAVAILABLE`. That reduction
  is deliberately conservative and #368 does not loosen it — what #368
  changed is that the four readings' individual provenance
  (`MarketEnvironment.series`, plus `fetched_at`/`oldest_series` for the
  combined reading) is now *kept* rather than discarded once combined,
  and surfaced on `/health`. A 2026-08-25 field test could not tell "VIX
  is on its normal, expected FRED lag" apart from "the pipeline
  stopped": `/health` read 08-21, the banner 08-20, `/monitor`'s spot
  08-23, with nothing distinguishing an expected per-series lag from a
  dead cron. `/health`'s `market_data.series` (per-reading
  quality/as_of/fetched_at) and `market_data.oldest_series` are that
  breakdown; the chrome stamp shows the same `fetched_at`/laggard pair
  inline: `Data as of 2026-08-20 20:00 EDT (CACHED · refreshed
  2026-08-25 02:30 EDT · oldest series: vix)`.

### Hand-entered inputs

There is no feed to grade a hand-entered input's staleness against, so
"stale" here means something different: how long since a human last
confirmed the value, measured against a per-input policy age in
`ips_config.pricing_inputs` (`spot_max_age_days`,
`volatility_max_age_days`, `risk_free_rate_max_age_days`,
`dividend_yield_max_age_days` — see
[yaml-config-guide.md](yaml-config-guide.md)). See "Confirmation stamps"
above for what a stamp means and when it is (and is not) set.

| Freshness | Meaning |
| --- | --- |
| `FRESH` | Stamped, within its policy max age |
| `AGING` | Stamped, past its policy max age |
| `UNKNOWN` | Never stamped — confirmation age indeterminate, worse than `AGING` |

`MISSING` (the fourth `Freshness` value) never applies to a hand-entered
input — a book always carries *some* value for spot, rate, dividend
yield, and per-leg IV; only its confirmation age can be unknown. It
exists for the fetched side, where a channel can have no cached reading
at all.

### The combined ledger

`analysis.provenance.build_provenance_ledger` builds one
`ProvenanceLedger` covering the fetched market-data channel and every
hand-entered input side by side. `ProvenanceLedger.worst` is the single
worst channel across both; `.combined_quality` re-expresses that worst
channel as a `DataQuality` string, so the digest's existing
STALE-or-worse gate and `/health`'s vocabulary need no new grade. This
is a deliberate, lossy mapping (`AGING → STALE`, `UNKNOWN → STATIC`,
`MISSING → UNAVAILABLE`) — see the property's own docstring.

`/health`'s `market_data` and `pricing_inputs` objects are **never
merged**: a stale hand-entered rate must not make `/health` claim the
*fetched* market data feed itself is stale, which would just relocate
the #368 confusion into a new field. Only the chrome banner and the
digest's `data_quality` caveat take the ledger's single worst-of;
`/health` and the provenance panel (`/monitor` and `/design`, collapsed
by default) show the full, unmerged breakdown.

The banner mounts only when the ledger's worst channel is not `FRESH` —
never for a merely `CACHED` fetched reading, the normal steady state. If
every input #367 added made the banner louder, operators would stop
reading a banner that never turns off; see `analysis/provenance.py`'s
module docstring and `app/chrome.py` for the full reasoning.

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
