# An Options & Downside Hedging Handbook

Updated: 2026-03-07

---

## Table of Contents

- [PART I — Options Fundamentals](#part-i--options-fundamentals)
- [PART II — The Greeks](#part-ii--the-greeks)
- [PART III — Volatility & the Vol Surface](#part-iii--volatility--the-vol-surface)
- [PART IV — Trading Terminology](#part-iv--trading-terminology)
- [PART V — Portfolio Hedging Concepts](#part-v--portfolio-hedging-concepts)
- [PART VII — Institutional Hedge Dashboards](#part-vii--institutional-hedge-dashboards)
- [PART VIII — Designing a Tail Hedge Program](#part-viii--designing-a-tail-hedge-program)
- [PART IX — Monetization & Re-Risk Rules](#part-ix--monetization--re-risk-rules)
- [PART X — Common Structural Mistakes](#part-x--common-structural-mistakes)
- [PART XI — Educational Resources](#part-xi--educational-resources)

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

The Greeks measure **how (V) changes when one of these variables changes**.

### Delta (Δ)

Delta is the sensitivity of the option price to changes in the underlying price.

*Example:* “A 0.30 delta call moves ~$0.30 per $1 move in underyling.”

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

- Approximate probability of finishing ITM (for short maturities)
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

High gamma means:

- delta changes quickly
- option responds strongly to large moves

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
- $\Gamma > 0$

### Volatility of Volatility (Vol-of-Vol)

Vol-of-vol measures **how much implied volatility itself fluctuates**. Volatility of implied volatility.

*Example:* “VIX options trade vol-of-vol.”

$\sigma_t$

represents implied volatility, then vol-of-vol measures variability of:

$d\sigma_t$

VIX may move:

```python
20 → 35
```

This reflects high vol-of-vol.

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

### Cash Convexity

It captures **convexity with respect to volatility**. Crash convexity measures how much a hedging position gains if the underlying experiences a large downward move.

It captures the **nonlinear payoff** from options during a market crash.

In simple terms:
> crash convexity = how much protection you get in a large drawdown.

#### Algebraic framing

- $P(S)$ = value of hedge
- $S$ = underlying index level

Crash convexity measures the **second-order payoff sensitivity** to large negative moves.

A practical approximation:

$\text{Crash Convexity} = \frac{P(S(1-\Delta)) - P(S)}{S}$

where:

- $\Delta$ = crash size (e.g., 20%)

Another way to think about it is using **gamma exposure**:

$\Gamma = \frac{\partial^2 V}{\partial S^2}$

Large positive gamma → strong convex crash protection.

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

Crash convexity answers:

> “How much does my hedge help during a real crisis?”

Typical target institutional hedge:

```text
10–30% crash convexity
```

```text
-20% market → hedge offsets 10–30% of loss
```

### Vega Sufficiency

#### Definition

Vega sufficiency measures whether a hedge has **enough volatility exposure** to benefit from the **volatility spike that usually accompanies a market crash**.

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

#### Portfolio Interpretation of Vega Sufficiency

If vega is too small:

```text
price drop helps
vol spike doesn't
```

Good crash hedges often rely heavily on vega.

Long-dated options typically provide stronger vega.

## PART III — Volatility & the Vol Surface

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

In equity markets, volatility usually **increases for lower strikes**.

OTM puts more expensive than calls.

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

### Terminology

These terms describe **portfolio behaviour**, not individual option parameters.

#### Convexity

Convexity means **the payoff accelerates as the underlying moves**.

*Example:* “Long puts add convexity to portfolio.”

Mathematically:

$\Gamma > 0$

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

#### Optionality

Optionality refers to **asymmetric payoff structures**.

Definition:

> limited downside, unlimited or large upside.

Example:

```text
buying a call
```

Loss limited to premium, but upside potentially unlimited.

*Example:* “Buying downside optionality.”

#### Pin Risk

Pin risk occurs when the underlying closes **very close to a strike price at expiration**.

*Example:* “Avoid pin risk into expiration.”

```text
stock = 100
strike = 100
```

#### Open Interest (OI)

Number of outstanding contracts.

*Example:* “High OI at 5000 strike.”

#### Liquidity / Spread

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

## Gamma Scalping

Gamma scalping is a trading strategy that profits from volatility.

1. buy options (long gamma)
2. hedge delta dynamically

When price moves:

```text
buy low
sell high
```

This captures realized volatility.

## Volatility Risk Premium

It is essentially the **insurance premium paid to maintain protection**. Markets tend to price **implied volatility higher than realized volatility**.

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

## PART V — Portfolio Hedging Concepts

## PART VII — Institutional Hedge Dashboards

## PART VIII — Designing a Tail Hedge Program

## PART IX — Monetization & Re-Risk Rules

## PART X — Common Structural Mistakes

## PART XI — Educational Resources

### Youtube

- [Hedging Against Market Crashes w/ Kris Sidial](https://www.youtube.com/watch?v=iVAM9vShYno&utm_source=chatgpt.com)
