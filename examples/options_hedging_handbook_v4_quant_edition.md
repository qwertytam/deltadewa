# Additional Content

- [PART XII — Visual Intuition Diagrams](#part-xii--visual-intuition-diagrams)
  - [Linear vs Convex Payoff](#linear-vs-convex-payoff)
  - [Volatility Surface (Conceptual)](#volatility-surface-conceptual)
  - [Downside Skew in Equity Markets](#downside-skew-in-equity-markets)
- [PART XIII — Mathematical Appendix](#part-xiii--mathematical-appendix)
- [PART XIV — Python Examples for Hedge Analytics](#part-xiv--python-examples-for-hedge-analytics)
  - [Black‑Scholes Pricing](#blackscholes-pricing)
  - [Crash Scenario Simulation](#crash-scenario-simulation)
  - [Vega Exposure Calculation](#vega-exposure-calculation)
- [PART XV — Institutional Tail‑Hedge Playbooks](#part-xv--institutional-tailhedge-playbooks)
  - [Monetization Rules](#monetization-rules)
  - [Re‑Hedging Discipline](#rehedging-discipline)
- [PART XVI — Canonical Institutional Hedge Structures](#part-xvi--canonical-institutional-hedge-structures)
  - [1. Long Deep OTM Puts (Pure Tail Hedge)](#1-long-deep-otm-puts-pure-tail-hedge)
  - [2. Put Spread Hedge](#2-put-spread-hedge)
  - [3. Put + VIX Convexity Overlay](#3-put--vix-convexity-overlay)
- [PART XVII — Strike Selection Models](#part-xvii--strike-selection-models)
  - [Expected Crash Distribution](#expected-crash-distribution)
- [PART XVIII — Rolling Frameworks](#part-xviii--rolling-frameworks)
- [PART XIX — Python Backtest Framework](#part-xix--python-backtest-framework)
  - [Basic Backtest Skeleton](#basic-backtest-skeleton)
  - [Crash Scenario Engine](#crash-scenario-engine)
  - [Hedge Efficiency Simulation](#hedge-efficiency-simulation)
  - [Example Workflow](#example-workflow)
- [PART XX — Professional Implementation Playbook](#part-xx--professional-implementation-playbook)
  - [Step 1 — Establish Protection Budget](#step-1--establish-protection-budget)
  - [Step 2 — Build Strike Ladder](#step-2--build-strike-ladder)
  - [Step 3 — Maintain Tenor Ladder](#step-3--maintain-tenor-ladder)
  - [Step 4 — Monetize During Crashes](#step-4--monetize-during-crashes)
  - [Step 5 — Rebuild Protection](#step-5--rebuild-protection)
- [PART XXI — Dealer Gamma and Market Microstructure](#part-xxi--dealer-gamma-and-market-microstructure)
  - [Dealer Gamma](#dealer-gamma)
  - [Gamma Regimes](#gamma-regimes)
- [PART XXII — Vanna and Charm Flows](#part-xxii--vanna-and-charm-flows)
  - [Vanna](#vanna)
  - [Charm](#charm)
- [PART XXIII — Skew Term Structure Dynamics](#part-xxiii--skew-term-structure-dynamics)
  - [Skew Expansion During Crises](#skew-expansion-during-crises)
- [PART XXIV — Volatility Risk Premium](#part-xxiv--volatility-risk-premium)
  - [Implications for Hedging](#implications-for-hedging)
- [PART XXV — How Tail-Risk Funds Monetize Hedges](#part-xxv--how-tail-risk-funds-monetize-hedges)
  - [Re-Risking After Monetization](#re-risking-after-monetization)
- [PART XXVI — Portfolio Hedge Sizing Frameworks](#part-xxvi--portfolio-hedge-sizing-frameworks)
- [PART XXVII — Optimal Hedge Budget](#part-xxvii--optimal-hedge-budget)
  - [Carry vs Convexity Optimization](#carry-vs-convexity-optimization)
- [PART XXVIII — Tax Considerations for Hedging Instruments](#part-xxviii--tax-considerations-for-hedging-instruments)
- [PART XXIX — Historical Crash Analysis](#part-xxix--historical-crash-analysis)
- [PART XXX — Portfolio Drawdown Reduction Modeling](#part-xxx--portfolio-drawdown-reduction-modeling)

## PART XII — Visual Intuition Diagrams

### Linear vs Convex Payoff

Linear exposure (stock):

```text
P&L
 ^
 |        /
 |       /
 |      /
 |_____/_____________> Price
```

Long put payoff:

```text
P&L
 ^
 | |  |   |   \______
 |          \
 +-----------\--------> Price
```

Interpretation:

- Linear assets move **1‑for‑1** with price.
- Long options produce **convex payoffs** where gains accelerate during large moves.

---

### Volatility Surface (Conceptual)

```text
Implied Volatility
       ^
       |         surface
       |       /
       |      /
       |     /
       +------------------> Strike
            \
             \
              ---> Maturity
```

Volatility depends on:

```text
σ = σ(K, T)
```

Where:

- K = strike
- T = maturity

---

### Downside Skew in Equity Markets

```text
Volatility
 ^
 |\
 | \
 |  \
 |   \
 +-----\------------> Strike
```

OTM puts trade with higher implied volatility because investors demand crash protection.

---

## PART XIII — Mathematical Appendix

## PART XIV — Python Examples for Hedge Analytics

Below are simplified code snippets that mirror the calculations used in hedge dashboards.

### Black‑Scholes Pricing

```python
import numpy as np
from scipy.stats import norm

def bs_call(S, K, T, r, sigma):
    d1 = (np.log(S/K)+(r+0.5*sigma**2)*T)/(sigma*np.sqrt(T))
    d2 = d1 - sigma*np.sqrt(T)

    call = S*norm.cdf(d1)-K*np.exp(-r*T)*norm.cdf(d2)
    return call
```

---

### Crash Scenario Simulation

```python
def crash_payoff(hedge_value, portfolio_value):
    return hedge_value / portfolio_value
```

Example:

```text
portfolio = 10_000_000
hedge_gain = 1_800_000

convexity = hedge_gain / portfolio
```

---

### Vega Exposure Calculation

```python
portfolio_vega = 20000
vol_change = 20

profit = portfolio_vega * vol_change
```

---

## PART XV — Institutional Tail‑Hedge Playbooks

Professional hedge programs follow systematic rules rather than discretionary trades.

---

### Monetization Rules

Example framework:

```text
SPX −15% → sell 30% of hedge
SPX −25% → sell 50% of hedge
SPX −35% → monetize most remaining protection
```

Use hedge gains to **increase equity exposure when markets are cheaper**.

---

### Re‑Hedging Discipline

Professional approach:

```text
do not buy protection during volatility spikes
rebuild hedges once volatility normalizes
```

---

## PART XVI — Canonical Institutional Hedge Structures

Institutional investors typically rely on a small number of well-understood hedge structures.
Each structure balances **carry cost, convexity, and reliability**.

### 1. Long Deep OTM Puts (Pure Tail Hedge)

Structure:

```text
Buy long‑dated OTM puts
No short options
No financing leg
```

---

### 2. Put Spread Hedge

Structure:

```text
Buy OTM put
Sell deeper OTM put
```

Example:

```text
Buy 85% strike
Sell 65% strike
```

Advantages:

```text
lower carry cost
more capital efficient
```

Disadvantages:

```text
caps extreme crash payoff
```

---

### 3. Put + VIX Convexity Overlay

Structure:

```text
Long OTM SPX puts
Long VIX calls
```

Advantages:

```text
two sources of convexity
price drop
volatility explosion
```

Disadvantages:

```text
basis risk
more complex management
```

---

## PART XVII — Strike Selection Models

Professional hedge programs do not choose strikes randomly.

They optimize for:

```text
crash convexity
skew exposure
carry cost
```

### Expected Crash Distribution

Funds often model crash sizes:

```text
10% correction
20% bear market
30–40% crisis
```

Strike ladders are built to respond to each layer.

Example ladder:

```text
10% OTM
20% OTM
30% OTM
```

---

## PART XVIII — Rolling Frameworks

Professional hedge programs rely on systematic rolling rules.

## PART XIX — Python Backtest Framework

A simplified structure for testing hedge strategies.

### Basic Backtest Skeleton

```python
import pandas as pd
import numpy as np

def backtest_put_hedge(spx_returns, hedge_cost):
    
    portfolio = 1.0
    hedge = 0
    
    for r in spx_returns:
        portfolio *= (1+r)
        hedge -= hedge_cost
    
    return portfolio + hedge
```

---

### Crash Scenario Engine

```python
def crash_scenario(portfolio, crash_size, hedge_payoff):

    equity_loss = portfolio * crash_size
    hedge_gain = hedge_payoff

    return equity_loss + hedge_gain
```

---

### Hedge Efficiency Simulation

```python
def hedge_efficiency(crash_payoff, annual_cost):
    return crash_payoff / annual_cost
```

---

### Example Workflow

```text
1 load SPX historical returns
2 simulate hedge portfolio
3 compute crash convexity
4 compute annual carry
5 evaluate hedge efficiency
```

---

## PART XX — Professional Implementation Playbook

Institutional hedge programs follow a structured process.

### Step 1 — Establish Protection Budget

Typical allocation:

```text
1–3% annual carry
```

---

### Step 2 — Build Strike Ladder

Example:

```text
20% allocation → 90% strike
40% allocation → 85% strike
40% allocation → 80% strike
```

---

### Step 3 — Maintain Tenor Ladder

Maintain:

```text
12–24 month maturity
quarterly roll schedule
```

---

### Step 4 — Monetize During Crashes

Example rule:

```text
SPX −15% → monetize 30%
SPX −25% → monetize 50%
SPX −35% → monetize most remaining hedges
```

Use profits to **increase equity exposure**.

---

### Step 5 — Rebuild Protection

When volatility normalizes:

```text
VIX < ~20
```

Gradually rebuild hedge positions.

---

## PART XXI — Dealer Gamma and Market Microstructure

Modern equity markets are heavily influenced by **options dealer positioning**.

Dealers typically hedge the options they sell by dynamically trading the underlying index or futures.

This creates feedback effects in market movements.

### Dealer Gamma

Dealer gamma measures the aggregate **gamma exposure held by market makers**.

When dealers are:

```text
long gamma
```

they hedge by:

```text
selling into rallies
buying into dips
```

This behavior **dampens volatility**.

When dealers are:

```text
short gamma
```

they hedge by:

```text
buying when the market rises
selling when the market falls
```

This **amplifies volatility**.

---

### Gamma Regimes

Markets often shift between two regimes.

#### Positive Dealer Gamma

Characteristics:

```text
low volatility
mean-reverting price action
small intraday moves
```

Example environments:

```text
range-bound markets
post-expiry periods
```

#### Negative Dealer Gamma

Characteristics:

```text
high volatility
large directional moves
momentum-driven markets
```

Example environments:

```text
during crashes
during large macro events
```

Understanding these regimes helps traders anticipate **when volatility may accelerate**.

---

## PART XXII — Vanna and Charm Flows

Beyond the standard Greeks, professional volatility traders monitor **second-order sensitivities**.

These include:

```text
vanna
charm
vomma
```

---

### Vanna

Vanna measures how **delta changes when volatility changes**.

Mathematically:

```text
Vanna = ∂²V / (∂S ∂σ)
```

Interpretation:

```text
when volatility rises
option deltas change
dealers must rebalance hedges
```

This can create **large flows in the underlying market**.

---

### Charm

Charm measures how **delta changes as time passes**.

Mathematically:

```text
Charm = ∂²V / (∂S ∂t)
```

Interpretation:

Even if price does not move:

```text
dealer hedges must change over time
```

This can produce **systematic buying or selling pressure**.

---

## PART XXIII — Skew Term Structure Dynamics

Volatility skew is not constant across maturities.

Short-dated options often exhibit **steeper skew** than long-dated options.

Example:

| Maturity | ATM IV | OTM Put IV |
| -------- | ------ | ---------- |
| 1M       | 20%    | 30%        |
| 1Y       | 19%    | 24%        |

Interpretation:

```text
short-term crash insurance
is more expensive
```

Long-dated hedges therefore often have **better carry characteristics**.

---

### Skew Expansion During Crises

During market stress:

```text
OTM put volatility increases dramatically
```

Example:

| Strike      | IV before | IV during crisis |
| ----------- | --------- | ---------------- |
| ATM         | 20%       | 35%              |
| 30% OTM put | 25%       | 60%              |

This phenomenon drives the explosive performance of **deep OTM tail hedges**.

---

## PART XXIV — Volatility Risk Premium

Options markets typically price volatility **higher than realized volatility**.

This difference is called the **volatility risk premium (VRP)**.

Formula:

```text
VRP = IV − RV
```

Where:

```text
IV = implied volatility
RV = realized volatility
```

Example:

```text
IV = 22%
RV = 17%
VRP = 5%
```

This premium exists because investors are willing to **pay for insurance**.

---

### Implications for Hedging

Because IV > RV on average:

```text
long option strategies lose money in normal markets
```

This is why tail hedging must rely on **rare but large payoff events**.

---

## PART XXV — How Tail-Risk Funds Monetize Hedges

Professional tail-risk funds rarely hold hedges until expiration.

Instead they monetize gains during volatility spikes.

Typical monetization signals include:

```text
large market drawdowns
volatility spikes
skew expansion
```

Example rules:

```text
SPX -15% → monetize portion of hedge
VIX > 40 → monetize aggressively
```

---

### Re-Risking After Monetization

When hedges are monetized, the proceeds are often used to:

```text
buy equities at lower prices
increase portfolio beta
```

This converts hedge gains into **long-term portfolio growth**.

---

## PART XXVI — Portfolio Hedge Sizing Frameworks

---

## PART XXVII — Optimal Hedge Budget

Hedges are typically funded through an **annual carry budget**.

Most institutional hedge programs target:

```text
1–3% annual portfolio cost
```

Example:

```text
Portfolio value = $10M
Annual hedge budget = 2%
Hedge budget = $200k per year
```

This budget must cover:

```text
option premiums
rolling costs
transaction costs
```

---

### Carry vs Convexity Optimization

The hedge designer must balance:

```text
minimize carry cost
maximize crash payoff
```

This is often visualized as:

```text
Convexity
   ^
   |
   |      optimal zone
   |
   |
   +------------------> Carry cost
```

Deep OTM long-dated options often sit near the **efficient frontier** of this tradeoff.

---

## PART XXVIII — Tax Considerations for Hedging Instruments

---

## PART XXIX — Historical Crash Analysis

---

## PART XXX — Portfolio Drawdown Reduction Modeling
