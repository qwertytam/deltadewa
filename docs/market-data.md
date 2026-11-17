# Market data — what is connected, and what is not

The one place that answers *"what market data are we looking to connect
up?"*. Read it before assuming a number on either page is observed: most
of the pricing inputs are not.

Two things are true at once and are easy to conflate:

- The app **observes** six index-level readings, refreshed nightly, and,
  when `ips.yaml` has a `pricing_feed` section, the SPX option chain and a
  Treasury yield as well.
- The app **prices the book** off four inputs: per-leg implied volatility,
  the risk-free rate, the dividend yield, and spot. The feed supplies the
  first, second and fourth; the dividend yield is always hand-entered
  (see ["Fetched pricing inputs"](#fetched-pricing-inputs-9b)).

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

- **Two more with a `pricing_feed` section.** `chain` and `rate` join the
  same run with the same rules (fetched independently, `LIVE` only on a real
  fetch, read back through the app's own path). They are described under
  ["Fetched pricing inputs"](#fetched-pricing-inputs-9b). `/health` lists
  them under `market_data.feed`, beside `series` and not in it: `series`
  is the environment's reduction and feeds `oldest_series`, the banner and
  `status`, and nothing is priced on the feed yet.

### The skew percentile's window (#317)

The SKEW percentile is the inclusive rank of the latest SKEW close over a
trailing window of `market_environment.skew_lookback_days` sessions —
**1260 (≈ five years)** by default, the handbook's own window
([The Lookback Window](https://qwertytam.github.io/deltadewa-handbook/part-3/volatility-skew/#the-lookback-window)).
Before 8c it was an unsourced 252 that no caller overrode. The handbook
lets a program choose another window "provided it states the window every
time it quotes a percentile", so every surface does: `/design` reads
"88th percentile (trailing 5y)", and so do both program-report renderers.

- **Coverage.** Cboe publishes SKEW from 1990-01-02 and the provider
  caches the whole file, so any window up to decades costs no extra
  download. A series shorter than the window raises `MarketDataError`
  rather than silently ranking a truncated sample; the refresh job
  fetches at the IPS window, so that failure is logged where an operator
  reads it.
- **What changing it does.** On 2026-11-06 (SKEW 153.55) the reading was
  90.5 on 252 sessions and 87.6 on 1260 — both above the 70 cut, so that
  day's verdict did not move. Over the preceding year the two windows
  labelled 84 of 252 sessions differently, always toward "more expensive"
  on five years: SKEW has drifted upward since 2021, so the five-year
  distribution's cuts sit lower (30th/70th: 134.8/147.0 vs 142.2/148.3
  on one year). The five-year window read LOW — "accumulate
  aggressively" — on 5 of those sessions, where the one-year window read
  LOW on 70.
- **Week over week.** `WeeklySnapshot` persists the window; a snapshot
  written before 8c reads back as 252 (the window every earlier
  percentile was in fact ranked over), and the digest reports a window
  change instead of a percentile move.
- `get_vix_history`'s 252-session window is a **different metric** (the
  vol-regime true percentile in `analysis/health.py`) and is unchanged.

## Fetched pricing inputs (9b)

> **Status.** Built: the nightly fetch and its cache, the daily chain
> record, liquidity from the chain, and `/design`'s read-only **Fetched
> inputs** panel. **Not built yet:** pricing the book on the feed. Until
> that lands, every pricing input is hand-entered and the feed is shown
> beside it, never applied. The rules below are the design the adoption
> follows.

**What is fetched.** With a `pricing_feed:` section in `ips.yaml` the
nightly refresh adds two series to its six. Without the section nothing
below is fetched and every input stays hand-entered.

| Series | Source | Cache key |
| --- | --- | --- |
| `chain` | Cboe delayed-quote SPX option chain (about 13 MB), cached **raw** | `chain_SPX` (last night's copy kept as `chain_SPX.prev`) |
| `rate` | the FRED constant-maturity series the policy names (`pricing_feed.rate_series`) | `rate_<series>` |

Both live in the **cache folder**, `./cache` on the host (`/app/cache` in
the containers), which is **outside `exports/`**: the payload is vendor
data and must never be committed, ride the offsite backup, or become a
test fixture (tests build synthetic chains from the engine). The folder is
gitignored and rebuilt by one run of the refresh job; a restore starts
without it. The one thing the job leaves under `exports/` is
`chain-history/` (below). A payload that downloads but does not parse never
replaces a good cache entry: the parse runs inside the fetch.

**How an input is chosen.** One effective value per input, decided once
when the process starts: the app, and the weekly digest (its own process,
the same function), resolve spot, rate and per-leg IV from the cached feed
and price the in-memory book on them. The book file keeps what a human
typed; a fetched value is never saved into it. There is no live reload
(#355: a book swapped under a render tears it), so the nightly refresh is
followed by a restart of the app, and the app's date rolls forward with it.
Nothing is journaled to the position history when the inputs are resolved:
they move the marks, not the book.

**Per-leg IV** is solved from the close **mid** with this program's own
European engine at the book's effective rate and dividend yield, at the
chain's own index level and session date. A vendor IV is an answer at the
vendor's own rate and yield; adopted beside different ones it misprices a
leg by about 6-8% per point of difference (see the spike, below), whereas the
solved IV reprices the leg to the mid by construction. The vendor's IV is
shown, never priced on. An IV and the (r, q) it was solved with are a
pair: changing the rate or the yield re-solves every IV; overriding spot
does not, and says so.

- *Matching.* The expiry comes from the contract symbol, never a computed
  third Friday. The standard `SPX` monthly is preferred; `SPXW` is used only
  where `SPX` does not list the date; `SPXO` is never matched. Each leg shows
  the contract that priced it.
- *A quote yields no IV* when it has no bid or no ask, is wider than
  `pricing_feed.max_spread_pct` of mid, cannot be solved (the mid is outside
  the no-arbitrage bounds at the book's r and q), or the contract is not
  listed. The vendor's `iv: 0` is irrelevant (the IV is solved), and a bid
  and an IV are tested separately.
- *Stale quotes.* The payload carries no per-contract quote time, so a
  quote's age is the program date minus the chain's trading session
  (NYSE calendar; a payload overnight, at a weekend or on a holiday belongs
  to the last close). Beyond `pricing_feed.max_quote_age_days` it is not
  used.
- *Candidates.* A strike the book does not hold (the strike grid, the
  sizing workbench, the ladder composer, a roll's cost) takes its IV from
  the same chain: the exact listed contract; else between the two listed
  strikes either side; else between the two listed expiries either side, in
  total variance. Nothing is extrapolated: outside the listed range the
  candidate uses the book's flat vol and is labelled so.

**Rate.** One book-level rate from one named FRED series
(`pricing_feed.rate_series`, `DGS1` in the template), converted from a
bond-equivalent yield to a continuous one. Per-leg rates were rejected: the
batch pricer, the crash repricing, the candidates and the Monte Carlo all
broadcast one book rate, so a per-leg rate would disagree with them for
about a percent of price. FRED publishes about a business day late; the
observation date is always shown and a late figure is the normal case, not
an alarm (#368).

**Dividend yield** stays hand-entered and confirmed quarterly
(`pricing_inputs.dividend_yield_max_age_days`). Put-call parity measures the
dividend, funding and timing together and cannot isolate the yield, so
`adopt` may not name it.

**Spot** is the chain's own index level: struck at the same instant as the
quotes the IVs are solved from. The nightly index close is the fallback.
On a weekend or holiday the book prices at the last trading day's close.
`/monitor`'s book-versus-observed cross-check warns only when both figures
are from the same session.

**Provenance.** A fetched input is graded as a fetched one (`DataQuality`,
by `fetched_at` against the data TTL, with the quote's age gating whether
it is used). An override or a fallback is a hand-entered input, graded by
`pricing_inputs`; those ages apply to overrides and fallbacks only. A
fallback in use also shows the feed as unavailable, so a dead feed alarms
through the fetched channel. The two-channel rule (`assess_freshness`) is
unchanged: one rule, applied to every fetched entry.

**Overrides** are set on `/design` (review, then confirm), last until
cleared, and are listed on `/monitor` and in the digest with their age and
the fetched value beside them. `/design` warns when an override is far from
the fetched value: past `market_environment.spot_divergence_warn_pct` for
spot, `pricing_feed.override_warn_vol_points` for an IV.

**When the feed fails**, each input falls down a ladder:

| Rung | Condition | Priced on | What is said |
| --- | --- | --- | --- |
| 1 | Normal | today's fetched value | the session of the quotes |
| 2 | A night's download failed | the last good value, labelled with its date | `STALE` once `fetched_at` passes the TTL: banner, `/health`, and the digest headline by the unchanged #398 rule |
| 3 | Last good value older than `max_quote_age_days` | the typed value, graded by its stamp | the banner: "feed down since <date>; pricing on your value from <date>" |
| - | The resolving code itself raises | typed values for everything | `/health` and the banner say so; the weekly email still sends and pings |

**Realized carry.** An option whose IV source changed between two weekly
marks (the feed failed, or came back) was re-priced with no trade. The
weekly figure flags that week, since part of it is a re-pricing, not carry.

**Daily record.** After a live chain fetch the job appends one session's
rows to `exports/chain-history/SPX-<year>.jsonl`: each held option's close
quote, and about 120 fixed market points (the standard `SPX` expiries 30
days to 3 years out; the listed put nearest 5, 10, 20, 30, 40 and 50% out
of the money; the at-the-money put and call). The rows are raw (bid, ask,
the vendor's IV, open interest), so they can be re-solved at any rate and
yield later. About 5 MB a year, backed up. It is the start of this
program's own IV history: the free feed has none.

## Hand-entered inputs

These come from the loaded portfolio (or `/design`'s position editor). The
dividend yield is always hand-entered; spot, the rate and per-leg IV are
too until `pricing_feed.adopt` names them, and after that they are the
override and the fallback (see
["Fetched pricing inputs"](#fetched-pricing-inputs-9b)). Every one is
flagged, though not all the same way (#367):

| Input | Where it is set | Refresh path | Staleness signal |
| --- | --- | --- | --- |
| Per-leg implied volatility | `OptionPosition.volatility_as_of` | Hand-entered, or the feed | Confirmation age, vs. `pricing_inputs.volatility_max_age_days` |
| Risk-free rate | `MarketParameterStamps.risk_free_rate_as_of` on the book | Hand-entered, or the feed | Confirmation age, vs. `pricing_inputs.risk_free_rate_max_age_days` |
| Dividend yield | `MarketParameterStamps.dividend_yield_as_of` on the book | Hand-entered only | Confirmation age, vs. `pricing_inputs.dividend_yield_max_age_days` |
| **Spot price** | `MarketParameterStamps.spot_as_of` on the book | Hand-entered, or the feed | Confirmation age (above) **and** the #336 observed-spot cross-check (below) |

Spot is the one that matters most, because it is the reference point
almost every other number is measured against — crash convexity, roll
OTM%, every drift trigger, hedge value, the monetization gain. A stale
spot biases all of them in the same direction. A hand-entered spot
carries, as of #336, a second, independent signal
beyond the confirmation age above: `/monitor` shows it beside the
independently observed market spot (see the "Observed readings" table
above), so a divergence past `market_environment.spot_divergence_warn_pct`
in `ips.yaml` is visible rather than silent. The other three hand-entered
inputs have no observed counterpart to cross-check against on `/monitor`,
so for a hand-entered one confirmation age is the only signal available, and
it is a review cadence, not a market fact: it answers "how long since a human
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

That unconditional stamp is also why the button cannot tell CONFIRM from
RE-MARK: a flat per-leg IV surface confirms just as green as a skewed one.
The provenance panel therefore carries a separate, ungraded "really?"
note when every leg sits at one IV across two or more distinct
strike/maturity points (`analysis.provenance.flat_iv_nudge`, N7). The
weekly procedure is in `docs/continuity-annex.md`, "CONFIRM is not
RE-MARK".

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
channel as a `DataQuality` string, so the digest's `data_quality` table
row and `/health`'s vocabulary need no new grade string. This is a
deliberate, lossy mapping (`AGING → STALE`, `UNKNOWN → STATIC`,
`MISSING → UNAVAILABLE`) — see the property's own docstring.

`/health`'s `market_data` and `pricing_inputs` objects are **never
merged**: a stale hand-entered rate must not make `/health` claim the
*fetched* market data feed itself is stale, which would just relocate
the #368 confusion into a new field. Only the chrome banner takes the
ledger's single worst-of unconditionally (`needs_banner`, below); the
digest's own caveat/headline display `combined_quality`'s string but no
longer *gate on* it directly (see the next paragraph — #398).
`/health` and the provenance panel (`/monitor` and `/design`, collapsed
by default) show the full, unmerged breakdown.

`/health`'s `status` grades freshness per channel (#393), and so
**does not read `combined_quality`**: the fetched channel degrades at
STALE-or-worse, the hand-entered one at `UNKNOWN` or worse. A merely
`AGING` hand-entered input — one overdue against its `pricing_inputs`
cadence rather than never confirmed — is reported in full under
`pricing_inputs` but deliberately kept out of the headline, because with
`spot_max_age_days: 1` it is true on most days of a weekly-rhythm
program and a permanently degraded endpoint is a dead-man's switch
nobody reads. `freshness_reason` names the channel and grade when one
does degrade. **This same two-channel rule —
`analysis.provenance.assess_freshness` — now also gates the weekly
digest's `"STALE DATA — "` headline prefix and its `"DATA QUALITY: X"`
caveat (both the digest's own lede and the embedded program report's §3
Market Context section), via `MarketContextSection.needs_alarm` /
`WeeklySnapshot.data_quality_alarm` (#398)**: before #398 those two
surfaces gated on `combined_quality`'s STALE-or-worse membership
directly, which meant the identical AGING-hand-entered-input case that
`/health` already stayed quiet on would falsely alarm the digest every
ordinary week. The rule and its full reasoning live in
`analysis/provenance.py`'s `assess_freshness` docstring (moved there
from `app/health_checks.py`'s module docstring by #398, which still
carries the original argument in full and now also records why the
digest reuses it instead of a second copy).

The banner mounts only when the ledger's worst channel is not `FRESH` —
never for a merely `CACHED` fetched reading, the normal steady state. If
every input #367 added made the banner louder, operators would stop
reading a banner that never turns off; see `analysis/provenance.py`'s
module docstring and `app/chrome.py` for the full reasoning.

## Liquidity

Part X #12 Liquidity Risk needs per-strike bid/ask and open interest.
`/design`'s **Liquidity check** panel grades one quote per held leg against
`ips.yaml`'s optional `liquidity:` section. The quote is the operator's own,
read off their broker and recorded by hand (8c), or, with a `pricing_feed`
section, last night's close quote for that contract, derived from the cached
chain (9b).

- **What is captured.** Per leg, a `LiquidityObservation`
  (`portfolio/liquidity.py`): bid, ask, optional open interest, when it was
  read, and its source (`OPERATOR` or `FETCHED`). Spread is the handbook's
  `(Ask - Bid) / Mid`. An operator quote is persisted with the book (JSON
  and YAML), restored verbatim on import, and discarded if the leg's strike,
  maturity or type is edited: it described a different contract.
- **Fetched quotes are derived, never stored.** At read time each held leg
  is matched on the cached chain; the result is a `FETCHED` observation
  dated to the close of its trading session (never later than the payload
  itself). It puts no nightly write on the book and cannot overwrite an
  operator quote.
- **Which is graded.** The later of the two is graded and the other is shown
  beside it; on a tie the operator's wins. A broker quote taken at roll time
  therefore outranks last night's close until the next close arrives, and a
  leg in its roll window still wants a quote read on the program date: a
  fetched close from yesterday does not satisfy it.
- **When the operator records one.** At the moments the handbook says
  liquidity matters: rolling, monetizing and scaling a position (Tier 4
  §12). The panel flags a leg as needing a fresh quote when it has never
  been checked, when its last quote is older than the review cadence, or
  when the leg's roll status is `ROLL`/`REVIEW`.
- **What grades it.** `ips.yaml`'s optional `liquidity:` section:
  `spread_warn_pct` (a recorded spread wider than this grades WIDE),
  `open_interest_min` (optional; unset records OI ungraded), and
  `observation_max_age_days`. The handbook names "wide bid-ask spreads"
  and "low open interest" as warning signs but gives **no number for
  either**, so there are no code defaults: with no `liquidity:` section
  every quote is shown ungraded and the panel says why. The shipped
  templates use `spread_warn_pct: 10.0` — the top of the handbook's only
  stated range, "5–10% of the mid-price or wider in quiet markets" for
  30–40% OTM ~18-month puts (`part-7/volatility-roll-yield`) — which
  describes a quiet market, not a handbook limit.
- **How it ages.** By the same rule as every other hand-entered input —
  `analysis.provenance.grade_hand_entered` (#367) against
  `observation_max_age_days`. A grade on an overdue quote is shown as of
  the day it was read, never as the current market.
- **Why it is not in the provenance ledger or its alarm.** A leg with no
  quote would grade `UNKNOWN` there, and `assess_freshness` alarms on
  `UNKNOWN`: every never-checked leg would put "STALE DATA" on the digest
  and a permanent banner on both pages — #398's alarm fatigue again. The
  ledger is also "every *pricing* input", and a spread prices nothing. So
  liquidity lives on `/design` only: not the banner, the digest,
  `/health` or `/monitor`.
- **What it does not claim.**
  - **Depth** behind the top of book, and traded **volume**;
  - **intraday and stress-time widening**: a close quote says nothing about
    the bid in a crash, which is when the handbook says liquidity matters
    most. The feed is a once-a-day read after the close;
  - quotes for strikes the book does not hold. The **Fetched inputs**
    panel shows the `strike_ladder` rungs' quotes, but the checklist grades
    held legs only.

## What is not connected

- **Intraday data.** Every feed here is a once-a-day read after the close.
  The 15-minute delay and in-session spreads were never measured and are out
  of scope.
- **A dividend yield.** It cannot be derived from the chain (see
  ["Fetched pricing inputs"](#fetched-pricing-inputs-9b)) and no free source
  publishes one cleanly. It stays hand-entered.
- **Historical chains.** The free endpoint keeps none. What accumulates is
  this program's own `chain-history/` record, from the day the feed was
  turned on. Backtesting over past drawdowns, and a realised vol-surface
  history, remain a paid-data question (#156).
- **Depth and volume** behind a quote, beyond the traded volume the payload
  reports.

## Option-chain spike (9b.0)

A one-off measurement that preceded the feed, and the reference for the
payload's shape and quirks. It was run on 2026-11-16 against Cboe's delayed-quote chain for the
SPX (terms of use are the operator's to settle and are not revisited here),
one payload, fetched once, **after the close** (20:39
New York). The payload was kept outside the repo and is not committed.
No figure from the operator's book is recorded here: a leg is described by
class, and anything derived from the book's own inputs (a per-leg reading, a
compliance grade) stays with the operator. Where a lesson needs a number, it
is measured on listed contracts instead.

### Verdict per input

| Input | Verdict | Why, in one line |
| --- | --- | --- |
| Spot | **GO** | The chain's own `current_price` is struck at the same instant as its quotes and a trading day fresher than the nightly job's CBOE history file. |
| Risk-free rate | **GO** | FRED publishes eleven constant-maturity series, all one business day behind; the provider's own client reaches them. Which tenor stands for a whole book is a decision for 9b, not a data gap. |
| Per-leg IV | **GO, with a condition** | The listed contracts checked all had a two-sided quote and a vendor IV. Adopt the IV **solved from the mid at the same r and q the engine prices with**: on a one-year put, a 1 pp error in either moves the IV by 0.5–0.7 vol points and the price by 6–8% (2b). |
| Dividend yield | **NO-GO** to derive it | Put–call parity gives a number that is negative at 14 days and 0.2–0.5% beyond four months, not the published yield. It cannot separate the dividend from funding and timing. Keep it hand-entered. |
| Liquidity | **GO** for bid, ask and open interest | Present on every listed contract checked. There is **no per-contract quote time** (only the last trade's). The feed is designed as a **once-a-day read after the close**, like the nightly refresh above, so a close snapshot is what it supplies: spreads here are close-of-day spreads, and in-session spreads are out of scope. |

### 2a. The payload

- **URL.** `https://cdn.cboe.com/api/global/delayed_quotes/options/_SPX.json`
  answers `307` to the same path on `cdn-api.cboe.com`; a client must follow
  redirects (the provider's `requests` session does).
- **Size and time.** 13,579,238 bytes (1,827,830 gzipped), 30,424 contracts,
  about one second to download. Fetched 2026-11-17 01:39:03 UTC. The response
  carried `Last-Modified: 01:33:29 GMT` and `Cache-Control: max-age=0,
  s-maxage=5`.
- **Top level.** `timestamp`, `data`, `symbol` (`_SPX`).
- **`data`.** `options` (the contract list) beside the index's own fields:
  `symbol` (`^SPX`), `security_type`, `exchange_id`, `current_price`,
  `price_change`, `price_change_percent`, `bid`, `ask`, `bid_size`,
  `ask_size`, `open`, `high`, `low`, `close`, `prev_day_close`, `volume`,
  `iv30`, `iv30_change`, `iv30_change_percent`, `seqno`, `last_trade_time`,
  `tick`.
- **Per contract (23 fields, present on all).** `option`, `bid`, `bid_size`,
  `ask`, `ask_size`, `iv`, `open_interest`, `volume`, `delta`, `gamma`,
  `vega`, `theta`, `rho`, `theo`, `change`, `open`, `high`, `low`, `tick`,
  `last_trade_price`, `last_trade_time` (null on 6,236 contracts that have not
  traded), `percent_change`, `prev_day_close`.
- **Symbol.** OCC form: root, `YYMMDD`, `C` or `P`, then the strike times
  1000 as eight digits (`SPX261120C00400000` is a 400 call on 2026-11-20).
  Every symbol parsed. Roots: `SPX` 10,022, `SPXW` 19,728, `SPXO` 674.
- **Time zones: two clocks in one payload.** `timestamp` is a naive
  `YYYY-MM-DD HH:MM:SS` in **UTC**: it equals the response's `Last-Modified`
  to within two seconds (01:33:27 against 01:33:29 GMT), and read as New York
  time it would be five hours in the future. `last_trade_time`, on the index
  and on each contract, is naive **New York** time: today's values run
  09:30:02 to 16:14:59.
- **Units.** A contract's `iv` is a decimal fraction (0.2677); the index's
  `iv30` is in vol points (17.977).
- **`iv: 0`.** 1,745 of 30,424 contracts, 1,261 of them with a bid: deep
  in-the-money contracts the vendor does not solve. Among out-of-the-money
  contracts, 263 of 15,212, of which 233 have no bid: 232 inside 30 days, none
  between 31 and 365 days, 31 beyond a year. The reverse also occurs: far-dated
  puts with an IV and no bid (75 of the 94 puts on the December 2030 expiry).
  A flag must test the bid and the IV separately.

### 2b. The book's legs and the roll candidates against the chain

The book's legs were matched against the chain and the per-leg result was
reported to the operator. It is a reading of the operator's own legs and is not
recorded here (see the opening of this section). Everything below was measured
on listed contracts.

- **What was solved.** IV from the mid with `OptionValuation` (European,
  analytic), at the payload's own spot and the program's valuation date. A
  hand-entered book spot is older than the quotes, and solving with it would put
  that age into the IV.
- **An IV and the (r, q) it was solved with are a pair.** At the FRED rate and
  the parity yield for the expiry, the IV solved from the mid lands within 0.15
  vol points of the vendor's on every contract checked: the vendor quotes an IV
  consistent with the market's forward. Move r or q off that forward and the
  same mid gives a different IV, and the vendor IV stops repricing to the mid.
  Measured on three listed one-year puts (20, 30 and 40% out of the money, the
  2027-12-17 expiry):

  | Strike | Solved IV, +1 pp on q | Solved IV, +1 pp on r | Vendor IV priced at q + 1 pp, vs mid | Vendor IV priced at r + 1 pp, vs mid |
  | --- | --- | --- | --- | --- |
  | 20% out | −0.65 vol pts | +0.74 vol pts | +8.1% | −7.1% |
  | 30% out | −0.55 vol pts | +0.64 vol pts | +8.3% | −6.5% |
  | 40% out | −0.49 vol pts | +0.57 vol pts | +8.4% | −5.7% |

  So adopting a vendor IV while the engine keeps a hand-entered r and q that
  differ from the market's forward misprices the leg by about 6–8% per point
  of error; adopting the IV solved at the engine's own r and q reprices it to
  the mid by construction.
- **Quote time.** Among the contracts checked, one carried a two-sided quote
  and open interest in the thousands with a last trade four days before the
  snapshot, so `last_trade_time` says nothing about how old a quote is. The
  only quote time in the payload is `timestamp`.
- **Roll candidates.** Six puts: the three example-ladder rungs (20, 30 and 40%
  out of the money, snapped to the listed strike) on each of the two standard
  expiries a year or more out. All six have a bid, an ask and an IV. Spreads are
  1.9–3.3% of mid on the nearer expiry (open interest 1,126–8,290) and
  3.1–4.7% on the further one (open interest 46–645, thin at the 20% rung).
- **Depth of the chain.** Among the 15 `SPX` expiries 150 days or more out,
  more than 97% of puts carry a bid out to December 2028. It thins beyond:
  December 2030 has a bid on 18 of 94 puts.

### 2c. SPX (AM) and SPXW (PM)

- `SPX` lists 20 standard expiries, 2026-11-20 to 2031-12-19; `SPXW` lists 40,
  2026-11-16 to 2027-09-30, mostly daily and weekly. On a third Friday both
  roots list the date through 2027-03-19. From 2027-04-16 the standard monthly
  lists on `SPX` only; `SPXW` appears at month ends (2027-03-31, 04-30, 06-30,
  09-30).
- **A standard monthly expiry from 2027-04-16 on lists on `SPX` only**, the
  AM-settled monthly; `SPXW` does not list those dates. A leg on one of them
  can only be `SPX`. The book has no field that says which root a leg is; a
  matcher must check both roots and flag a date on which both list.
- A standard monthly moves off the third Friday when that Friday is an exchange
  holiday: the chain lists June 2027's `SPX` expiry on Thursday 2027-06-17
  (Friday 2027-06-18 is the observed Juneteenth holiday), and no `SPX` symbol
  for the 18th. A matcher must take the date from the symbol, not recompute a
  third Friday.
- A third root, `SPXO`, lists two Wednesdays (2026-11-18, 2026-12-16), 674
  contracts. It was not identified; it must not be matched as `SPX`.

### 2d. Dividend yield by put–call parity

Solved per expiry from call and put mids, `q = −ln((C − P + K·e^(−rT)) / S) / T`,
at the five strikes nearest the forward that quote two-sided, with `r` from the
FRED curve (continuously compounded, interpolated to the expiry) and `T` on 365
days. Median over the five strikes, `SPX` root, in percent:

| Expiry | Days | r | q |
| --- | --- | --- | --- |
| 2026-11-30 (`SPXW`) | 14 | 4.06 | −3.02 |
| 2026-12-18 | 32 | 4.06 | −0.75 |
| 2027-01-15 | 60 | 4.16 | −0.58 |
| 2027-02-19 | 95 | 4.28 | −0.09 |
| 2027-03-19 | 123 | 4.31 | +0.18 |
| 2027-05-21 | 186 | 4.38 | +0.21 |
| 2027-07-16 | 242 | 4.45 | +0.26 |
| 2027-09-17 | 305 | 4.52 | +0.34 |
| 2027-11-19 | 368 | 4.60 | +0.37 |
| 2028-06-16 | 578 | 4.73 | +0.45 |
| 2028-12-15 | 760 | 4.82 | +0.53 |
| 2029-12-21 | 1,131 | 4.86 | +0.53 |
| 2031-12-19 | 1,859 | 4.92 | +0.49 |

- From 60 days out to a year the five strikes of an expiry agree to 0.02 pp,
  and to 0.09 pp beyond; inside 30 days they spread by up to 0.14 pp. Where both
  roots list a date they agree to 0.03 pp.
- **Not stable across expiries**, and not close to the published figure: S&P
  Dow Jones Indices puts the trailing 12-month yield at 1.12% (2026-04-30); a
  third party's weighted indicated yield read 1.60% (2026-07-22). Neither was
  taken on the day of the snapshot.
- What a parity solve measures is the carry between the spot print and the
  options' forward: the dividend yield, any funding spread over Treasuries, and
  any timing gap between the spot and the quotes are in it together and cannot
  be separated from one payload. The short end's large negative values are
  what a small gap looks like when divided by a short `T`.

### 2e. FRED

- **Series.** Eleven exist: `DGS1MO`, `DGS3MO`, `DGS6MO`, `DGS1`, `DGS2`,
  `DGS3`, `DGS5`, `DGS7`, `DGS10`, `DGS20`, `DGS30`. `DGS2MO` and `DGS4MO`
  answer `404`.
- **Lag.** Probed on Monday 2026-11-16 at 20:45 New York, every series' newest
  observation was Friday 2026-11-13: one business day behind. One probe is one
  data point; when Monday's value posts was not measured. Each series' last
  ten rows hold one missing marker, on 2026-11-11 (Veterans Day); the
  provider's `dropna` already skips it.
- **Transport.** `curl` over HTTP/2 with a browser-style User-Agent failed on
  all thirteen requests (a stream error, then a timeout); `requests`, the
  provider's client, answered in 0.4 seconds. The cause was not isolated.
- At the same probe, the CBOE history file the nightly job reads for the SPX
  ended at Friday's close, the figure the chain reports as `prev_day_close`;
  the chain's `current_price` is Monday's.

### 2f. What adoption will change on deploy day

The program report was built twice over a copy of the book, by the digest's
own build path: **A**, the hand-entered inputs as they stand; **B**, the
fetched spot, a solved IV per leg (at B's rate and the unchanged dividend
yield), and the one-year FRED rate as the book's single rate. Both variants
were stamped as reviewed, so provenance does not differ, and the market
environment was one fixed provider at `CACHED` quality for both. The first run
used the shipped example IPS; it was then repeated on the live program state
and policy.

**The result is not recorded here.** A grade, a headline or a roll verdict
moved by a change of inputs is a reading of the operator's own book, and it
was reported to the operator directly. What the doc records is the method and
the standing lesson: adopting measured inputs can change the graded verdicts an
operator reads (compliance rows, roll verdicts, the digest headline), so the
comparison should be rerun on the live book, with the live IPS, before a
source change is deployed. `verdict-diff-reporter` is the agent for it.

What the preview cannot show: how adopted inputs would be stamped (both
variants here were stamped as reviewed), the live IPS's bands, and the real
market environment.

### What the switch does to realized carry

Digest section 4's realized carry is an identity over two boundary marks, both
priced on the `MODEL` basis: the engine at the book's hand-entered inputs. A
mark taken after adopting measured inputs prices the same lots differently with
no trade between the two marks, and the identity books that re-pricing as
carry, with no break named. Three facts frame the fix, all in the code today:

- `MarkBasis` says a mid-market basis would be a new member and a period whose
  marks disagree is refused (`realized_carry` raises). Section 4 then degrades
  to a stated error for any period that spans the switch, since-inception
  included.
- A second opening mark is refused by the history store, so the history cannot
  simply be restarted at the switch.
- Each mark already records the spot, rate, dividend yield and per-leg
  volatility it was priced on.

**Decision for 9b:** the switch itself is not marked: nothing is in
production, so no history spans it, and a new `MarkBasis` member (with every
period across it "not comparable") would be machinery for an event that
does not occur. What does recur is a single option's IV source changing
between two weekly marks (the feed failed, or came back), which re-prices
that option with no trade. Each mark records the IV's origin per option, and
a week whose two marks disagree on any option's origin is flagged in section
4: part of that figure is a re-pricing, not carry. The figure is still
printed, with the caveat.

### Limits

One payload, after the close, on a Monday. The feed is designed as a
once-a-day post-close read, so in-session spreads and the 15-minute delay were
not measured and are out of scope; they would need measuring only if an
intraday read were ever wanted. No second fetch, so the payload's regeneration
cadence is unknown. The book copy used for the legs was a book file from the
local exports directory; the verdict preview was then repeated on a copy of the
live program state and policy, and that result also went to the operator.

## Where the data lives

- **On disk:** the cache folder, `./cache` on the host and `/app/cache` in
  the containers, one JSON file per cache key, each holding `{"value": …,
  "fetched_at": …}`. It is **outside `exports/`**, so vendor payloads never
  ride the offsite backup. Both the `app` and `jobs` containers point at it
  via `DELTADEWA_CACHE_DIR` so a refresh actually warms what the app
  reads. Writes are atomic (a temporary file, then a rename). The one
  chain-derived file under `exports/` is `chain-history/`.
- **Endpoints and credentials:** see
  [yaml-config-guide.md](yaml-config-guide.md#live-market-data). Both
  endpoints are public; no API key is required for the six readings
  above.
