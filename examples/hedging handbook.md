# An Options & Downside Hedging Handbook

Updated: 2026-03-09

---

## Table of Contents

- [Table of Contents](#table-of-contents)
- [Preface](#preface)
- [PART I — Options Fundamentals](#part-i--options-fundamentals)
  - [The Basics](#the-basics)
  - [Pricing \& Carry](#pricing--carry)
  - [Moneyness](#moneyness)
  - [Position Types](#position-types)
  - [Exercise \& Settlement](#exercise--settlement)
- [PART II — The Greeks](#part-ii--the-greeks)
  - [Delta (Δ)](#delta-δ)
  - [Gamma (Γ)](#gamma-γ)
  - [Vega (ν)](#vega-ν)
  - [Theta (Θ)](#theta-θ)
  - [Rho (ρ)](#rho-ρ)
  - [Volatility of Volatility (Vol-of-Vol)](#volatility-of-volatility-vol-of-vol)
  - [Vanna](#vanna)
  - [Charm](#charm)
  - [Vomma](#vomma)
- [PART III — Volatility and the Vol Surface](#part-iii--volatility-and-the-vol-surface)
  - [Volatility Smile](#volatility-smile)
  - [Volatility Skew](#volatility-skew)
  - [Term Structure of Volatility](#term-structure-of-volatility)
  - [Volatility Crush](#volatility-crush)
- [PART IV — Trading Terminology](#part-iv--trading-terminology)
  - [Convexity](#convexity)
  - [Optionality](#optionality)
  - [Pin Risk](#pin-risk)
  - [Open Interest (OI)](#open-interest-oi)
  - [Liquidity / Spread](#liquidity--spread)
  - [Gamma Scalping](#gamma-scalping)
  - [Volatility Risk Premium](#volatility-risk-premium)
- [PART V — Portfolio Tail Hedging Concepts](#part-v--portfolio-tail-hedging-concepts)
  - [Structure 1 — Long OTM Puts (Pure Tail Hedge)](#structure-1--long-otm-puts-pure-tail-hedge)
  - [Structure 2 — Put Spread Tail Hedge](#structure-2--put-spread-tail-hedge)
  - [Structure 3 — Option Carry + Tail Hedge](#structure-3--option-carry--tail-hedge)
  - [Structure 4 — Volatility Instrument Hedge](#structure-4--volatility-instrument-hedge)
  - [Structure Selection](#structure-selection)
  - [A Typical Institutional Hedge Example](#a-typical-institutional-hedge-example)
- [PART VII — Institutional Hedge Dashboards](#part-vii--institutional-hedge-dashboards)
  - [Introduction](#introduction)
  - [1. Carry vs. Convexity Chart](#1-carry-vs-convexity-chart)
  - [2. Crash Scenario Table \& Payoff Ratio](#2-crash-scenario-table--payoff-ratio)
  - [3. Vega Sufficiency Gauge](#3-vega-sufficiency-gauge)
  - [4. Skew Exposure Meter](#4-skew-exposure-meter)
  - [5. Volatility Regime Indicator](#5-volatility-regime-indicator)
  - [6. Hedge Efficiency Ratio](#6-hedge-efficiency-ratio)
  - [7. Net Delta Exposure](#7-net-delta-exposure)
  - [8. Theta Carry (Insurance Cost)](#8-theta-carry-insurance-cost)
  - [9. Gamma Liquidity Risk](#9-gamma-liquidity-risk)
  - [10. Forward Variance Level](#10-forward-variance-level)
- [PART VIII — Designing a Tail Hedge Program](#part-viii--designing-a-tail-hedge-program)
  - [Strike Selection](#strike-selection)
  - [Maturity Selection](#maturity-selection)
  - [Rolling Rules](#rolling-rules)
- [PART IX — Monetization \& Re-Risk Rules](#part-ix--monetization--re-risk-rules)
  - [Monetizing crashes](#monetizing-crashes)
- [PART X — Common Structural Mistakes](#part-x--common-structural-mistakes)
  - [Buying protection when volatility is already high](#buying-protection-when-volatility-is-already-high)
  - [Buying puts that are not far enough OTM](#buying-puts-that-are-not-far-enough-otm)
  - [Holding hedges passively instead of rolling them](#holding-hedges-passively-instead-of-rolling-them)
- [PART XI — Educational Resources](#part-xi--educational-resources)
  - [Books](#books)
  - [Research Papers on Tail Hedging](#research-papers-on-tail-hedging)
  - [Online Courses](#online-courses)
  - [Youtube](#youtube)
  - [Best Websites for Data](#best-websites-for-data)

---

## Preface

This document consolidates multiple source files into a single structured reference.
Duplicate material has been removed, but explanations and examples have been preserved.

## PART I — Options Fundamentals

### The Basics

#### Option

A contract giving the right (not obligation) to buy or sell an asset at a fixed price before expiry.

*Example:* “I bought SPX put options as downside protection.”

#### Call Option

Right to **buy** the underlying.

*Example:* “A 5000 call profits if SPX rises above 5000.”

#### Put Option

Right to **sell** the underlying.

*Example:* “Long puts hedge my equity portfolio.”

#### Strike Price ($K$)

Price at which exercise occurs.

*Example:* “The 4500 strike put is slightly OTM.”

#### Expiration / Maturity ($T$)

Date the option expires.

*Example:* “I prefer LEAPS with 1–2 year maturity.”

#### Premium

Price paid for the option.

*Example:* “Vol spiked and premiums doubled.”

### Pricing & Carry

#### Spot Price ($S$)

Current underlying price.

*Example:* “Model uses spot = 5235.”

#### Forward Price ($F$)

Future implied price including carry.

*Example:* “SPX forwards embed rates minus dividends.”

#### Risk-Free Rate ($r$)

Discounting rate used in pricing.

*Example:* “Long-dated calls are sensitive to rates.”

#### Dividend Yield ($q$)

Expected dividends (or index carry).

*Example:* “Higher dividends lower call value.”

#### Implied Volatility (IV)

Volatility implied by market price.

*Example:* “I buy when IV feels cheap.”

#### Realized (Historical) Volatility

Actual past price movement.

*Example:* “Realized vol came in below IV.”

### Moneyness

#### ITM (In the Money)

Option already has intrinsic value.

*Example:* SPX at 5200 → 5000 call is ITM.

#### ATM (At the Money)

Strike ≈ current spot price.

*Example:* “ATM options have highest gamma.”

#### OTM (Out of the Money)

No intrinsic value yet.

*Example:* “OTM puts are cheaper tail hedges.”

#### Intrinsic Value

Immediate exercise value.

*Example:* Put intrinsic = max($K$ − $S$, 0).

#### Extrinsic (Time Value)

Premium beyond intrinsic value.

*Example:* “Even ITM options lose extrinsic over time.”

### Position Types

#### Long Option

You bought optionality.

*Example:* “Long puts = convex protection.”

#### Short Option

You sold optionality.

*Example:* “Covered calls harvest premium.”

#### Covered Call

Short call against long stock.

*Example:* “Generate income while holding shares.”

#### Protective Put

Long stock + long put.

*Example:* “Portfolio insurance strategy.”

#### Spread

Buying and selling options together.

*Example:* “Put spread reduces hedge cost.”

#### Vertical Spread

Same expiry, different strikes.

*Example:* Buy 4500 put, sell 4200 put.

#### Calendar Spread

Same strike, different expiries.

*Example:* Sell front-month, buy longer-dated.

#### Straddle

Buy call + put same strike.

*Example:* “Bet on big move either direction.”

#### Strangle

OTM call + OTM put.

*Example:* “Cheaper volatility bet.”

### Exercise & Settlement

#### American Option

Can exercise anytime.

*Example:* Most US equity options.

#### European Option

Exercise only at expiry.

*Example:* SPX index options.

#### Assignment

Short option exercised against you.

*Example:* “Covered call got assigned.”

#### Cash Settled

No shares exchanged — only cash difference.

*Example:* SPX options are cash settled.

## PART II — The Greeks

The Greeks are partial derivatives of the option price with respect to different inputs in an option pricing model (typically Black-Scholes or a related model).

If the option price is written as:

$V = V(S, K, T, \sigma, r, q)$

Where:

- $ S $ = underlying price
- $ K $ = strike price
- $ T $ = time to maturity
- $ \sigma $ = volatility
- $ r $ = risk-free rate
- $ q $ = dividend yield

Greeks are derivatives of (V) with respect to these variables. ([Wikipedia][wiki-greeks]) They measure **how $V$ changes when one of these variables changes**.

### Delta (Δ)

Delta is the sensitivity of the option price to changes in the underlying price.

*Example:* “A 0.30 delta call moves ~$0.30 per $1 move in underlying.”

If the stock rises **$1**, the option price increases **$0.30**.

If the stock falls **$1**, the option price decreases **$0.30**.

| Underlying | Option price |
| ---------- | ------------ |
| $100       | $5.00        |
| $101       | $5.30        |

#### Algebraic definition

$\Delta = \frac{\partial V}{\partial S}$

#### Meaning

> The partial derivative of the option price with respect to the underlying price.

#### Black-Scholes expressions

Call option:  $\Delta_{call} = e^{-qT} N(d_1)$

Put option: $\Delta_{put} = -e^{-qT} N(-d_1)$

Where $N(\cdot)$ is the standard normal cumulative distribution function.

#### Practical interpretation

- Approximate probability of finishing ITM (for short maturities, with low interest regions, in the ATM region)
- Effective exposure to the underlying

Portfolio:

```text
100 calls
delta = 0.40
```

Total delta exposure: $100 \times 0.40 = 40$

Equivalent to owning 40 shares of the underlying.

### Gamma (Γ)

Gamma measures how delta changes when the underlying price changes.

It captures the curvature of the option price with respect to the underlying.

*Example:* “ATM options have high gamma risk.”

Suppose:

```text
Initial delta = 0.30
Gamma = 0.05
```

If the stock rises by $1:

```text
New delta = 0.35
```

If the stock rises again:

```text
New delta = 0.40
```

#### Algebraic definition for Gamma

$\Gamma = \frac{\partial^2 V}{\partial S^2}$

or equivalently

$\Gamma = \frac{\partial \Delta}{\partial S}$

#### Black-Scholes expression

$\Gamma = \frac{e^{-qT} N'(d_1)}{S \sigma \sqrt{T}}$

Where:

- $N'(d_1)$ is the normal probability density function.

#### Practical interpretation for Gamma

Gamma describes **convexity**.

High gamma means:

- delta changes quickly
- option responds strongly to large moves

Properties:

- Highest ATM
- Highest short maturity

### Vega (ν)

Vega measures sensitivity of the option price to volatility.

It tells you how much the option price changes if implied volatility changes by 1 percentage point.

*Example:* “Long puts gain when vol spikes.”

If:

```text
vega = 0.50
```

Then:

```text
IV increases from 20% → 21%
```

Option price increases:

```text
$0.50
```

Note: The definition above assumes 1 vol point = 1%. However, in many models it is per 0.01 change in $\sigma$

#### Algebraic definition for Vega

$\nu = \frac{\partial V}{\partial \sigma}$

#### Black-Scholes expression for Vega

$\nu = S e^{-qT} \sqrt{T} N'(d_1)$

#### Practical interpretation for Vega

Vega measures exposure to volatility.

Long options:
> positive vega

Short options:
> negative vega

Important properties:

- larger for long maturity
- larger ATM

High vega:

```text
benefits strongly from panic
```

Low vega:

```text
price move helps but vol spike doesn't
```

### Theta (Θ)

Theta measures how option price changes as time passes.

It captures time decay.

*Example:* “Short options collect theta.”

If:

```text
theta = −0.05
```

Then the option loses:

```text
$0.05 per day
```

assuming other inputs remain constant.

#### Algebraic definition Theta

$\Theta = \frac{\partial V}{\partial T}$

However traders usually quote:

$\Theta = -\frac{\partial V}{\partial t}$

where $t$ is calendar time.

$\text{Annual Carry} = \frac{-\Theta_{daily} \times 252}{Portfolio}$

#### Practical interpretation of Theta

- Long options → negative theta
- Short options → positive theta

Time decay **accelerates** as expiration approaches.

### Rho (ρ)

Rho measures sensitivity of the option price to interest rates.

*Example:* “LEAPS calls have meaningful rho.”

If:

```text
rho = 0.20
```

Then:

```text
rates increase by 1%
```

Option value increases:

```text
$0.20
```

#### Algebraic definition Rho

$\rho = \frac{\partial V}{\partial r}$

#### Practical interpretation of Rho

Rho matters most for:

- Long-dated options
- Deep ITM calls

### Volatility of Volatility (Vol-of-Vol)

Vol-of-vol measures **how much implied volatility itself fluctuates**. Volatility of implied volatility.

*Example:* “VIX options trade vol-of-vol.”

$\sigma_t$ represents implied volatility

Vol-of-Vol is variance of changes in implied variability, or algebraiclly:

$\text{Var}(d\sigma_t)$

VIX may move:

```text
20 → 35
```

This reflects high vol-of-vol.

Note: VIX options do not directly trade vol-of-vol; they trade volatility of variance expectations.

### Vanna

Vanna measures how delta changes when volatility changes.

$\text{Vanna} = \frac{\partial^2 V}{\partial S \partial \sigma}$

Interpretation:

- When vol rises
- Delta of options changes

### Charm

Charm measures how delta changes as time passes.

$\text{Charm} = \frac{\partial^2 V}{\partial S \partial t}$

Interpretation:

Even if price does not move:

- Delta drifts over time.

### Vomma

Vomma measures how vega changes when volatility changes.

$\text{Vomma} = \frac{\partial^2 V}{\partial \sigma^2}$

#### Interpretation

It captures convexity with respect to volatility.

## PART III — Volatility and the Vol Surface

Options markets quote implied volatility instead of price.

But volatility is not constant across strikes or maturities.

This produces the volatility surface.

The volatility surface is a function:

$\sigma = \sigma(K, T)$

Meaning volatility depends on:

- strike $K$
- maturity $T$

Graphically it is a **3-dimensional surface**:

```text
volatility
   ^
   |
   |       surface
   |
   +-----------------> strike
        maturity
```

### Volatility Smile

A volatility smile occurs when implied volatility increases for both:

- deep OTM calls
- deep OTM puts

relative to ATM.

Graph shape:

```text
vol
 ^
 |  \      /
 |   \____/
 |
 +--------- strike
```

*Example:* “Equity puts have downside skew.”

#### Interpretation of Volatility Smile

Markets assign higher probability to **extreme outcomes** than predicted by Black-Scholes.

### Volatility Skew

In equity markets, volatility usually **increases for lower strikes**. This is put or downside skew. OTM puts are more expensive than calls.

```text
OTM puts > ATM > OTM calls
```

Graph:

```text
vol
 ^
 |\
 | \
 |  \
 |
 +------ strike
```

#### Interpretation of Volatility Skew

Investors pay more for **downside protection**.

### Term Structure of Volatility

Implied volatility varies across maturities:

$\sigma = \sigma(T)$

*Example:* “Near-term vol elevated vs LEAPS.”

```text
1-month vol = 25%
6-month vol = 22%
2-year vol = 20%
```

This is **downward sloping**.

#### Interpretation of Term Structure

Short-term uncertainty may be higher.

### Volatility Crush

Volatility crush occurs when **implied volatility drops suddenly** after an event.

*Example:* “Earnings caused a vol crush.”

```text
earnings announcement
```

Before event:

```text
IV = 60%
```

After event:

```text
IV = 30%
```

Option prices drop sharply.

## PART IV — Trading Terminology

These terms describe **portfolio behaviour**, not individual option parameters.

### Convexity

Convexity means **the payoff accelerates as the underlying moves**.

*Example:* “Long puts add convexity to portfolio.”

Mathematically:

$\Gamma + \text{Vega} + \text{Skew Exposure}$

Example payoff:

```text
long put
```

Losses are limited but gains accelerate during large moves.

Underlying drops:

```text
-5%
-10%
-20%
```

Put gains accelerate.

### Optionality

Optionality refers to **asymmetric payoff structures**.

Definition:

> limited downside, unlimited or large upside.

Example:

```text
buying a call
```

Loss limited to premium, but upside potentially unlimited.

*Example:* “Buying downside optionality.”

### Pin Risk

Pin risk occurs when the underlying closes **very close to a strike price at expiration**.

*Example:* “Avoid pin risk into expiration.”

```text
stock = 100
strike = 100
```

### Open Interest (OI)

Number of outstanding contracts.

*Example:* “High OI at 5000 strike.”

### Liquidity / Spread

Liquidity measures **how easily options can be traded**.

*Example:* “Wide spreads make hedging expensive.”

Common proxy:

```text
Bid–ask spread
```

```text
Bid = 2.40
Ask = 2.60
```

Spread:

```text
0.20
```

### Gamma Scalping

Gamma scalping is a trading strategy that profits from volatility.

1. buy options (long gamma)
2. hedge delta dynamically

When price moves:

```text
buy low
sell high
```

This captures realized volatility.

### Volatility Risk Premium

Markets tend to price **implied volatility higher than realized volatility**.

Formally:

$VRP = IV - RV$

Where:

- $IV$ = implied volatility
- $RV$ = realized volatility

*Example:*

```text
IV = 22%
RV = 18%
```

Premium:

```text
4%
```

Option sellers capture this on average.

## PART V — Portfolio Tail Hedging Concepts

The goal of tail hedging is **not to offset small drawdowns**.

```text
small losses tolerated
large crashes offset
```

It is to provide:

```text
liquidity during crises
```

This liquidity lets investors:

```text
rebalance
buy assets cheaply
avoid forced selling
```

For a hedged equity portfolio, key metrics to track are:

| Metric                                              | What it answers                        |
| --------------------------------------------------- | -------------------------------------- |
| [Crash convexity](#1-carry-vs-convexity-chart)      | How much protection in a crash         |
| [Vega sufficiency](#3-vega-sufficiency-gauge)       | Do we benefit from vol spikes          |
| [Theta carry](#1-carry-vs-convexity-chart)          | Cost of holding hedge                  |
| [Skew Beta / Skew Exposure](#4-skew-exposure-meter) | Sensitivity to downside skew           |
| [Volatility regime](#5-volatility-regime-indicator) | Whether options are expensive or cheap |

Professional hedge design is essentially optimizing:

```text
maximize crash convexity
maximize vega sufficiency
maximize skew beta
minimize theta carry
```

given the current volatility regime.

Volatility funds tend to use four broad architectures.

### Structure 1 — Long OTM Puts (Pure Tail Hedge)

This is the **simplest design**.

Structure:

```text
long deep OTM puts
long maturities
rolled systematically
```

Example:

```text
SPX = 5000
Buy 3500 puts
18 months maturity
```

#### Characteristics

| Feature      | Value    |
| ------------ | -------- |
| Crash payoff | huge     |
| Carry cost   | moderate |
| Complexity   | low      |

#### Typical users

```text
Universities
many institutional tail funds
```

### Structure 2 — Put Spread Tail Hedge

Structure

```text
buy deep OTM put
sell further OTM put
```

Example:

```text
buy 3500 put
sell 2500 put
```

#### Purpose

Reduce cost. Carry becomes:

```text
1–2% instead of 3–5%
```

Trade-off:

```text
cap extreme crash payoff
```

### Structure 3 — Option Carry + Tail Hedge

Some funds combine:

```text
short volatility income
+
long crash hedge
```

Example:

```text
sell short-dated options
buy long-dated puts
```

This attempts to **finance the hedge with volatility risk premium**.

Risks:

```text
timing mismatch
```

### Structure 4 — Volatility Instrument Hedge

Instead of SPX puts, funds may use:

```text
VIX futures
VIX options
variance swaps
```

Reason: Volatility spikes faster than price drops.

Example:

```text
SPX -20%
VIX 20 → 70
```

These strategies require **more active management**.

### Structure Selection

For simplicity, Structure 1 is usually a good fit for many investors.

Typical improvements to be considered are

- strike layering:

Example:

```text
20% OTM
30% OTM
40% OTM
```

- roll annually
- tracking convexity vs. carry

### A Typical Institutional Hedge Example

Portfolio:

```text
$10M equity
```

Hedge allocation:

```text
1.5-2.5% per year
```

Put portfolio

| Strike | Weight | Maturity  |
| ------ | ------ | --------- |
| 4000   | 40%    | 18 months |
| 3500   | 40%    | 18 months |
| 3000   | 20%    | 18 months |

Crash scenario:

| Market move | Hedge payoff |
| ----------- | ------------ |
| -10%        | small        |
| -20%        | moderate     |
| -40%        | very large   |

## PART VII — Institutional Hedge Dashboards

### Introduction

These are the kinds of metrics volatility funds and institutional portfolio hedgers monitor daily. They combine the Greeks with **portfolio-level normalization**.

These metrics help investors maintain **constant protection while controlling cost**, since tail-risk hedging aims to cushion severe drawdowns while preserving long-term portfolio growth. ([resonanzcapital.com][resonanzcapital])

#### Initial List of Six

1. Carry vs Convexity
2. Crash Scenario Table
3. Vega Sufficiency
4. Skew Exposure
5. Volatility Regime
6. Hedge Efficiency

#### Example of a Full Dashboard

```text
TAIL HEDGE DASHBOARD

Portfolio value: $10M

Carry cost:             2.1% / year
Crash convexity:        28% @ -25% SPX
Convexity/carry ratio:  7.5
Vega exposure:          $18k / vol point
Skew exposure:          High
Skew percentile:        22%  (cheap)
Vol regime:             Low (VIX 14)
Forward variance:       cheap
Dealer gamma:           negative
Hedge efficiency:       6.3x
```

Conclusion:

```text
increase hedge allocation
```

#### Key Driver of the Dashboard

The **best opportunities to buy crash protection** typically occur when:

```text
market calm
volatility low
skew moderate
dealer gamma positive
```

Investors instinct is to hedge **after markets fall**, but that is when hedges are **most expensive**.

### 1. Carry vs. Convexity Chart

This is the **core trade-off in tail hedging**. It determines **whether the hedge economics are attractive**.

```text
maximize convexity
minimize carry
```

#### Definition of Carry vs. Convexity

- **Carry (Theta)** = cost of holding the hedge
- **Convexity** = payoff in large crashes

Crash convexity measures how much the hedge pays during a large market decline. Convex strategies benefit from extreme moves in the benchmark index. ([Informa Connect][informaconnect])

#### Metrics

Annual carry:

<!-- TODO: **CHECK DAY CONVENTION!!** -->
$\text{Carry} = \frac{-\Theta_{daily} \times 252}{Portfolio}$

Crash convexity:

$\text{Crash Convexity} = \frac{V_{x} - V_{today}}{Portfolio\ Value}$

Where $x$ = crash size e.g., -25%.

- $V_{crash} = V(S \times (1 - x))$

Example:

| Scenario | Hedge value |
| -------- | ----------- |
| Today    | $200k       |
| SPX −25% | $2.2M       |

Portfolio size:

```text
Equity = $10M
```

Hedge payoff:

```text
2.0M / 10M = 20%
```

#### Ratio

$\text{Carry-Convexity Ratio} = \frac{\text{Convexity}}{\text{Carry}}$

So, say annual carry is `3%`, then the ratio is:

```text
22% / 3% = 7.3
```

#### Interpretation of the Ratio

| Ratio | Meaning    |
| ----- | ---------- |
| <3    | poor hedge |
| 3–6   | acceptable |
| >6    | attractive |

Tail funds prefer **high convexity relative to cost**.

Typical values:

| Metric          | Typical hedge |
| --------------- | ------------- |
| Carry           | 1–3% per year |
| Crash convexity | 15–40%        |

#### Dashboard Visualization

```text
Convexity
   ^
   |
   |      GOOD
   |
   |
   | BAD
   +------------------> Carry
```

Best hedges sit **top-left**.

### 2. Crash Scenario Table & Payoff Ratio

The table simulates portfolio performance under market crashes.

#### Table Structure

| SPX Move | Portfolio P&L | Hedge P&L | Net P&L |
| -------- | ------------- | --------- | ------- |
| -5%      | -$500k        | +$30k     | -$470k  |
| -10%     | -$1M          | +$120k    | -$880k  |
| -20%     | -$2M          | +$650k    | -$1.35M |
| -35%     | -$3.5M        | +$2M      | -$1.5M  |

#### Key Insight

Options produce convex payoffs:

- small moves → small protection
- crashes → exponential hedge payoff

This convex structure is the foundation of tail hedging. ([Gateway Investment Advisers][gateway])

#### Payoff Ratio

Measures how much a hedging position gains if the underlying experiences a large downward move. it measures convexity with respect to price moves. It captures the **nonlinear payoff** from options during a market crash.

In simple terms:
> how much protection you get in a large drawdown.

Another way to think about it is using **gamma exposure**: Large positive gamma → strong convex crash protection.

Also known as:

- Tail hedge effectiveness
- Downside hedge ratio

#### Algebraic framing

Masure the **second-order payoff sensitivity** to large negative moves.

A practical approximation:

$\Gamma = \frac{\partial^2 V}{\partial S^2}$

where:

- $\partial^2 V$ = is estimated for the crash size (e.g., 20%)

*Example:*

```text
$10M long equity
```

```text
long 18-month OTM puts
```

If market falls:

| Market move | Portfolio loss | Hedge gain |
| ----------- | -------------- | ---------- |
| -5%         | -$500k         | +$40k      |
| -20%        | -$2M           | +$600k     |
| -35%        | -$3.5M         | +$1.8M     |

The **accelerating gains** reflect crash convexity.

#### Portfolio interpretation

Answers:

> “How much does my hedge help during a real crisis?”

Typical target institutional hedge:

```text
10–30% crash convexity
```

```text
-20% market → hedge offsets 10–30% of loss
```

### 3. Vega Sufficiency Gauge

Measures whether the hedge has **enough volatility exposure** to benefit from rom the **volatility spike that usually accompanies a market crash**.

#### Portfolio Metric Definition

In equity markets:

```text
market down → volatility up
```

So good hedges should benefit from both:

1. price drop
2. volatility spike

Let:

$\nu = \frac{\partial V}{\partial \sigma}$ be vega

Define:

$\text{Vega Sufficiency} = \frac{\text{Portfolio Vega}}{\text{Underlying Value}}$

Some managers scale it relative to expected vol spike:

$\text{Expected Vega Gain} = \nu \times \Delta \sigma$

Institutional programs usually normalize vega by:

```text
portfolio notional
or
1% market move
```

#### Common Metrics for Vega Sufficiency

```text
vega / portfolio value
vega / delta
vega / variance exposure
```

*Example:*

Portfolio:

```text
$10M equities
```

Hedge:

```text
vega = $15,000 per 1 vol point
```

If volatility rises:

```text
20% → 40%
```

Change:

```text
Δσ = 20 vol points
```

Profit:

```text
$15,000 × 20 = $300,000
```

In March 2020, the SPX moved down ~34% and the IV moved up from ~16 to ~82.

#### Portfolio Interpretation of Vega Sufficiency

If vega is too small:

```text
price drop helps
vol spike doesn't
```

Good crash hedges often rely heavily on vega.

Long-dated options typically provide stronger vega.

#### Dashboard Display

```text
VEGA SUFFICIENCY

Low <-----|-----> High
          ^
        current
```

### 4. Skew Exposure Meter

#### Definition of Skew Beta

Skew beta measures **how sensitive a hedge is to changes in the volatility skew**. Skew reflects the higher implied volatility typically seen in OTM puts. ([Wikipedia][wiki-skew])

Equity markets exhibit volatility skew, meaning:

$\sigma_{OTM\ put} > \sigma_{ATM}$

This reflects demand for crash protection.

So we can also measure Skew Exposure, and also Skew Percentile. Skew Percentile measures how expensive **downside protection** is relative to history.

Volatility skew describes how:

```text
OTM put volatility > ATM volatility
```

During market stress:

```text
skew steepens dramatically
```

Deep OTM puts become much more expensive.

Equity markets have downside skew:

```text
OTM puts IV > ATM IV
```

In crashes, this steepens dramatically.

#### Algebraic Framing

Let $\sigma(K)$ represent implied volatility at strike (K).

Skew is approximately:

$\frac{\partial \sigma}{\partial K}$

With traders in practice measure using:

$\text{Skew} = \frac{\partial \sigma}{\partial log(K)}$

or using delta-based metrics.

Most traders measure skew using 25-delta options:

$\text{Skew} = \sigma_{25\Delta\ put} - \sigma_{ATM}$

Skew beta measures the hedge sensitivity to changes in that slope.

So a simplified hedge sensitivity metric:

$\text{Skew Beta} = \frac{\partial V}{\partial \text{Skew}}$

*Example:*

OTM puts:

```text
25% IV
```

During crisis:

```text
prices drop + skew steepens → OTM puts explode
>40% IV
```

ATM volatility may rise less:

```text
20% → 30%
```

OTM puts gain disproportionately. Many tail-risk strategies rely heavily on skew beta, using far OTM strikes.

The gain in OTM put value is fully true because of:

```text
delta + vega + skew + convexity
```

Not only due to skew.

#### Simple Skew Metric

Most traders measure skew using 25-delta options:

$Skew = \sigma_{25\Delta put} - \sigma_{50\Delta}$

Where:

- $25\Delta_{put} \approx \sim10-15\% \text{ OTM}$
- $40\Delta_{put} \approx \text{ATM}$

Note: $50\Delta$ is only exactly for ATM for calls. For puts $~40\Delta \approx \text{ATM}$

Example:

| Strike  | IV  |
| ------- | --- |
| ATM     | 20% |
| 25Δ put | 27% |

Skew

```text
27 − 20 = 7 vol points
```

#### Percentile calculation

Funds usually track:

```python
Skew percentile = current skew vs last 5–10 years
```

Example:

| Percentile | Meaning          |
| ---------- | ---------------- |
| 10%        | cheap protection |
| 50%        | normal           |
| 90%        | panic pricing    |

#### Hedge decision rule

Typical logic:

| Skew Percentile | Action          |
| --------------- | --------------- |
| <30%            | add tail hedges |
| 30-70%          | neutral         |
| >70%            | avoid buying    |

When skew is high, **deep OTM puts become extremely expensive**.

### 5. Volatility Regime Indicator

Volatility regime refers to the **general level and behavior of volatility in the market environment**. Markets cycle between low-volatility and high-volatility environments.

#### Algebraic Framing of Vol Regime

Often measured using:

$\sigma_t$

realized or implied volatility.

Regime detection may use:

```text
moving averages
GARCH models
volatility percentiles
```

Example rule:

```text
Low vol regime: VIX < 15
Normal regime: VIX 15–25
High vol regime: VIX > 25
```

*Example:*

| Period     | Regime    | VIX |
| ---------- | --------- | --- |
| 2017       | ultra low | 10  |
| 2020 crash | extreme   | 80  |
| 2022       | elevated  | 30  |

#### Portfolio Interpretation of Vol Regime

Volatility regimes influence:

```text
option prices
skew
carry cost
hedging effectiveness
```

In low-vol regimes:

```text
options cheap
good time to buy hedges
```

In high-vol regimes:

```text
options expensive
carry high
```

#### Dashboard Logic

Common indicators:

```text
VIX level
realized volatility
volatility percentile
```

```text
Volatility Regime: LOW
Recommendation: accumulate hedges
```

Low-volatility environments are often the best time to buy protection.

##### VIX Level

Most common regime indicator.

Example ranges:

| VIX   | Regime   |
| ----- | -------- |
| <15   | low vol  |
| 15–25 | normal   |
| >25   | stressed |
| >40   | crisis   |

##### Realized vs implied volatility

Another useful signal:

$VRP = IV - RV$

Where:

- $IV$ = implied volatility
- $RV$ = realized volatility

| Metric | Value |
| ------ | ----- |
| IV     | 22%   |
| RV     | 16%   |

Volatility risk premium

```text
6%
```

#### Hedge decision rule for VIX

Volatility funds prefer to **buy protection when volatility is cheap**.

Typical rule:

| VIX   | Hedge action       |
| ----- | ------------------ |
| <15   | accumulate         |
| 15-25 | maintain           |
| >30   | reduce or monetize |

### 6. Hedge Efficiency Ratio

Measures how much downside risk the hedge offsets relative to cost.

#### HER Metric

$\text{Hedge Efficiency} = \frac{\text{Crash payoff}}{\text{Annual carry}}$

or using percentage terms

$\text{Hedge Efficiency} = \frac{\text{Crash payoff \%}}{\text{Annual carry \%}}$

*Example:*

Crash payoff:

```text
$1.5M
```

```text
$300k
```

Efficiency:

```text
5
```

```text
5× payoff relative to cost
```

### 7. Net Delta Exposure

Delta represents the first derivative of option value with respect to the underlying price. ([Wikipedia][wiki-greeks])

$\Delta = \frac{\partial V}{\partial S}$

**Net Delta** measures directional exposure of the entire portfolio to the underlying.

#### Portfolio Metric

$\text{Net Delta} = \sum_i \Delta_i \times N_i$

Where:

- $N_i$ = number of contracts

*Example:*

```text
Equities: $10M
Put hedge delta: -0.20
```

Effective exposure:

```text
$10M × (1 − 0.20) = $8M
```

#### Interpretation of Net Delta

| Value | Meaning        |
| ----- | -------------- |
| 1.0   | fully exposed  |
| 0.8   | 20% hedge      |
| 0.0   | market neutral |

### 8. Theta Carry (Insurance Cost)

Theta carry measures how much money the hedge costs to hold over time due to time decay. It is essentially the insurance premium paid to maintain protection.

#### Algebraic framing of Theta Carry

Theta:

$\Theta = \frac{\partial V}{\partial T}$

Theta carry is usually expressed relative to portfolio size:

<!-- TODO: **CHECK DAY CONVENTION!!** -->
$\text{Theta Carry} = \frac{-\Theta \times 252}{\text{Portfolio Value}}$

*Example:*

Portfolio:

```text
$10M
```

Hedge theta:

```text
-$2,500 per day
```

<!-- TODO: **CHECK DAY CONVENTION!!** -->
Annualized:

```text
$2,500 × 252 ≈ $630k
```

Cost:

```text
6.3% per year
```

#### Portfolio Interpretation

Good hedges try to balance:

```text
maximize crash convexity
minimize theta carry
```

Typical institutional targets:

```text
1-3% annual carry
```

### 9. Gamma Liquidity Risk

Gamma measures how much delta changes when the market moves. Dealer positioning can strongly influence short-term market dynamics.

Dealer gamma is mostly a **short-dated flow indicator**, not a structural tail-hedging signal.

#### Concept

Market makers hedge option exposure.

If dealers are ***long gamma***, they hedge by:

```text
buy rallies
sell dips
```

Result:

```text
stable markets
low realized volatility
```

If they are **short gamma**, dealers hedge by:

```text
sell rallies
buy dips
```

Result:

```text
amplified volatility
```

#### Portfolio Metric Definition of Gamma Exposure

$\text{Gamma Exposure} = \sum_i \Gamma_i N_i$

Alternatively:

$GEX = \sum (\Gamma \times OpenInterest)$

Many sites publish estimates.

#### Interpretation of Results

High gamma means:

```text
large moves → big hedge gains
```

But also:

```text
requires rebalancing
```

| Dealer gamma | Market behavior       |
| ------------ | --------------------- |
| positive     | suppressed volatility |
| negative     | unstable market       |

#### Hedge Decision Rule on Results

Tail funds tend to add hedges when:

```text
dealer gamma negative
```

Because this increases crash probability.

Note: Tail hedges depend more on vol regime + skew + term structure than Gamma liquidity risk.

### 10. Forward Variance Level

Forward variance measures **expected volatility in the future**. This is crucial for long-dated hedges.

#### Concept of Forward Variance

Variance is volatility squared:

$Variance = \sigma^2$

Forward variance is implied volatility for a **future time window**.

| Option  | IV  |
| ------- | --- |
| 6-month | 22% |
| 2-year  | 19% |

This implies **lower expected volatility long term**.

#### Approximation

You can estimate forward variance between maturities.

Example:

$\sigma_{fwd}^2 = \frac{T_2\sigma_2^2 - T_1\sigma_1^2}{T_2 - T_1}$

#### Interpretation of Forward Variance Level

If long-dated volatility is unusually cheap:

```text
forward variance low
```

Long-dated puts become attractive.

#### Hedge Decision Rule

Tail funds often prefer buying:

```text
cheap long-dated vol
```

Because crashes often **inflate long-dated volatility suddenly**.

## PART VIII — Designing a Tail Hedge Program

A typical tail hedge fund uses three design layers of strike, maturity and roll.

### Strike Selection

Most funds target **20–40% OTM puts**.

Example:

```text
SPX = 5000
```

Typical strikes:

| Strike | Distance |
| ------ | -------- |
| 4000   | 20% OTM  |
| 3500   | 30% OTM  |
| 3000   | 40% OTM  |

Rationale:

- lower carry cost
- stronger skew beta
- massive convex payoff in crashes

### Maturity Selection

Tail funds prefer **long-dated options**.

Typical maturities:

| Maturity     | Reason            |
| ------------ | ----------------- |
| 6–12 months  | tactical hedging  |
| 12–24 months | strategic hedging |

Long maturities provide:

```text
high vega
low theta (on a relative basis)
stable convexity
```

This is why **LEAPS are common** in institutional programs.

Long maturities have low theta on a relative or % basis, but the total premium paid may be larger.

### Rolling Rules

Most programs roll on **time or moneyness triggers**.

#### Rule 1 — time-based roll

Example:

```text
buy 18-month puts
roll at 9–12 months
```

This avoids rolling just before theta acceleration in the final weeks of option life.

#### Rule 2 — strike rebalancing

If market rallies:

```text
puts become deeper OTM
```

Funds may:

```text
sell old hedge
buy new hedge closer to spot
```

## PART IX — Monetization & Re-Risk Rules

### Monetizing crashes

If crash occurs:

```text
puts explode in value
```

Funds typically:

```text
sell part of hedge
lock in gains
re-establish later
```

This is critical — otherwise hedges can **round-trip gains**.

## PART X — Common Structural Mistakes

The biggest mistake retail hedgers make is:

```text
buying protection too late
```

Professional programs instead:

```text
1. buy protection systematically
2. roll hedges regularly
3. monetize gains during crashes
```

This **systematic approach** is what turns tail hedging from an expensive insurance policy into a **long-term portfolio stabilizer**.

### Buying protection when volatility is already high

Most investors buy puts after markets start falling, when fear is high and options are expensive.

#### Why this is a problem

When implied volatility $\sigma$ is high:

- option premiums are inflated
- skew is already steep
- carry cost explodes

Example:

| Market state | 1-yr 30% OTM put IV |
| ------------ | ------------------- |
| Calm market  | 18%                 |
| Correction   | 30%                 |
| Crash        | 60%                 |

Buying during stress locks in terrible carry.

#### Professional approach

Tail funds prefer to buy when:

```text
VIX < ~15–18
skew moderate
```

Low-vol regimes historically provide the best hedge economics.

### Buying puts that are not far enough OTM

Investors often buy ATM or slightly OTM puts.

Example:

```text
SPX = 5000
Put strike = 4700
```

These options have:

- high theta
- moderate convexity
- weaker skew exposure

#### Why funds avoid this

```text
deep OTM puts reprice dramatically
```

Example (March 2020):

| Strike      | Price change |
| ----------- | ------------ |
| ATM put     | ~5×          |
| 30% OTM put | ~30×         |

Deep OTM options benefit from:

```text
price drop
+ volatility spike
+ skew steepening
```

### Holding hedges passively instead of rolling them

Retail investor often:

```text
buy 2-year puts
wait
watch them decay
```

Professional hedge programs **continuously manage maturity and strike**.

Why?

For ATM options, Theta roughly scales with:

$\Theta \propto \frac{1}{T}$

As maturity shortens, this relationship no longer holds, with time decay accelerating dramatically.

Tail funds typically **roll hedges before this decay phase**.
Gamma scales approximately to:

$\Gamma \propto \frac{1}{\sqrt{T}}$

## PART XI — Educational Resources

### Books

#### Trading Volatility – Colin Bennett

Probably the best practitioner book.

Topics:

- volatility surface
- skew
- hedging
- market maker thinking

#### Volatility & Pricing – Sheldon Natenberg

Industry classic covering:

- Greeks
- volatility trading
- spreads
- hedging strategies
- option pricing

Widely recommended by traders as a foundational text. ([Mutiny Fund][mutinyfund])

##### Dynamic Hedging – Nassim Taleb

Advanced but essential. Professional-level treatment of:

- tail risk
- convexity
- crash hedging
- option hedging

##### Volatility Trading – Euan Sinclair

Very practical. Best modern practitioner book. Topics:

- volatility/variance risk premium
- option portfolio management
- volatility strategies

##### Tail Risk Hedging — Vineer Bhansali

It explains how to design systematic crash protection and quantify hedge payoffs. ([Barnes & Noble][barnesnoble]) One of the most complete frameworks for portfolio hedging using derivatives.

### Research Papers on Tail Hedging

#### Universa / Mark Spitznagel

```text
Safe Haven
The Dao of Capital
```

Topics:

- tail-risk hedging
- convex payoff structures

#### AQR

Search for:

```text
AQR tail risk hedging paper
```

#### CBOE research

Excellent data on:

- skew
- VIX
- tail risk

#### Other Areas to Search For

Look for papers on:

- tail-risk hedging
- convexity strategies
- variance risk premium

Key topics:

- rolling long-put hedges
- VIX-based hedges
- volatility risk premium capture

For example, research shows that rolling long puts provides direct protection against equity drawdowns, though it can have negative carry over time. ([Alpha Architect][alpha-arch])

### Online Courses

#### Option Alpha (free)

Good fundamentals.

#### CME Institute

Free institutional-level content.

#### Coursera

Search:

```text
Options, Futures, and Derivatives
```

### Youtube

- [Hedging Against Market Crashes w/ Kris Sidial](https://www.youtube.com/watch?v=iVAM9vShYno)

#### Cem Karsan / Kai Volatility

Probably the **best volatility discussion online**.

Topics:

- dealer gamma
- volatility regimes
- crash dynamics

#### SpotGamma

Great for:

- dealer positioning
- gamma flows
- volatility regime analysis

#### Cem Karsan interviews

Excellent insights into:

```text
long-dated hedges
volatility cycles
tail risk
```

#### Kris Sidial (Ambrus Group)

Very clear explanations of **carry-neutral tail hedging strategies**.

[Youtube: Hedging Against Market Crashes w/ Kris Sidial (TIP702)](https://youtu.be/iVAM9vShYno)

### Best Websites for Data

#### Volatility data

```text
spotgamma.com
volatilityresearch.com
Quantpedia
Alpha Architect
```

#### Academic volatility research

```text
SSRN
arXiv
```

<!-- References -->
[wiki-greeks]: https://en.wikipedia.org/wiki/Greeks_%28finance%29 "Wikipedia: Greeks (finance)"
[informaconnect]: https://informaconnect.com/assessing-risk-profile-of-quant-strategies-the-convexity-vs-skewness/ "Assessing risk-profile of quant strategies: the convexity vs ..."
[wiki-skew]: https://en.wikipedia.org/wiki/skew "Wikipedia: SKEW"
[gateway]: https://www.gia.com/wp-content/uploads/2022/03/Convexity-A-Powerful-and-Customizable-Approach-to-Tail-Risk-Hedging.pdf "A Powerful and Customizable Approach to Tail Risk Hedging"
[resonanzcapital]: https://resonanzcapital.com/insights/strategic-tail-risk-hedging-building-antifragility-into-institutional-portfolios "Strategic Tail-Risk Hedging: Building Antifragility into ..."
[barnesnoble]: https://www.barnesandnoble.com/w/tail-risk-hedging-vineer-bhansali/1117029721 "Tail Risk Hedging: Creating Robust Portfolios for Volatile ..."
[mutinyfund]: https://mutinyfund.com/best-tail-hedging-books/ "The Best Tail Hedging Books for Beginners"
[alpha-arch]: https://alphaarchitect.com/strategies-to-mitigate-tail-risk/ "Strategies to Mitigate Tail Risk -"
