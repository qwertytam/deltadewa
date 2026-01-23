# Quick Start Guide

## Installation

```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies (includes nbstripout in dev)
poetry install --with dev

# Activate environment
poetry shell

# Configure nbstripout (prevents repeated cell outputs)
./setup_nbstripout.sh
```

## Quick Examples

### Example 1: Price a Single American Option

```python
from datetime import datetime, timedelta
from deltadewa import AmericanOption

# Create an American put option
put = AmericanOption(
    spot_price=100.0,
    strike_price=95.0,
    maturity_date=datetime.now() + timedelta(days=30),
    volatility=0.25,
    risk_free_rate=0.05,
    dividend_yield=0.02,
    option_type="put"
)

# Get price and Greeks
print(f"Price: ${put.price():.4f}")
print(f"Delta: {put.delta():.4f}")
print(f"Gamma: {put.gamma():.6f}")
print(f"Vega: {put.vega():.4f}")
print(f"Theta: ${put.theta():.4f}/day")
```

### Example 2: Build and Analyze a Portfolio

```python
from deltadewa import OptionPortfolio

# Create portfolio with a notional position
portfolio = OptionPortfolio(
    underlying_quantity=1000.0,  # Long 1000 shares
    spot_price=100.0,
    volatility=0.25,
    risk_free_rate=0.05,
    dividend_yield=0.02
)

# Add protective puts
maturity = datetime.now() + timedelta(days=60)
portfolio.add_position(95.0, maturity, 10, "put")
portfolio.add_position(100.0, maturity, 5, "put")

# Get portfolio analytics
stats = portfolio.summary_stats()
print(f"Portfolio Value: ${stats['total_value']:,.2f}")
print(f"Net Delta: {stats['net_delta']:.2f}")
print(f"Hedge Ratio: {stats['hedge_ratio']:.2f}%")
print(f"Delta Adjustment: {stats['delta_adjustment']:.0f} shares")
```

### Example 3: Run Scenario Analysis

```python
import numpy as np

# Analyze P&L across different spot prices
spot_range = np.linspace(80, 120, 41)
scenario_df = portfolio.scenario_analysis(spot_range)

# View results
print(scenario_df[['spot_price', 'portfolio_value', 'net_delta']])
```

### Example 4: Interactive Dashboard (New 3-Mode Layout)

The dashboard is now organized into 3 intuitive modes for a streamlined workflow:

```bash
jupyter lab options_dashboard.ipynb
```

#### **Workflow: BUILD → EXPLAIN → STRESS**

#### Step 1: BUILD Mode 🏗️

1. **Set Global Assumptions**:
   - Configure spot price, volatility, interest rates
   - Select time horizon (T+0, T+7, T+30, T+60, T+90, custom)
   - Define scenario grid parameters

2. **Build Your Portfolio**:
   - Use the position editor to add/update/remove positions
   - Import existing portfolios from JSON/YAML
   - View portfolio summary table

3. **Monitor KPIs**:
   - Net Hedge Summary shows real-time Greeks
   - Crash convexity indicators (-10%, -20%, -30%)
   - Updates automatically when portfolio changes

#### Step 2: EXPLAIN Mode 📊

1. **Consolidated Greeks View**:
   - See net portfolio Greeks in one table
   - View top 5 contributors for each Greek
   - Expand detailed breakdowns as needed

2. **P&L Analysis**:
   - Options-only P&L diagram
   - Total portfolio P&L (with underlying)
   - Identify breakeven points and max loss/profit

3. **Position Breakdown**:
   - Charts by type, strike, maturity
   - Cashflow tracking
   - Aging analysis

#### Step 3: STRESS Mode ⚡

1. **Run Scenario Grids**:
   - Interactive spot vs volatility heatmaps
   - Time vs price P&L evolution
   - Automatic caching for speed

2. **Monte Carlo Analysis**:
   - Value at Risk (VaR)
   - Conditional VaR (CVaR)
   - Probability distributions

3. **3D Visualization**:
   - Optional 3D P&L surfaces
   - Interactive Plotly charts

**Key Features:**

- ✅ Single GlobalAssumptions panel (no duplicate sliders)
- ✅ Always-visible Net Hedge Summary
- ✅ Automatic caching for performance
- ✅ Clear mode separation with visual headers
- ✅ Consolidated Greeks (80/20 view)

Or use the classic notebook:

```bash
jupyter notebook options_dashboard.ipynb
```

## Common Use Cases

### Protective Collar Strategy

```python
# Long underlying position
portfolio = OptionPortfolio(underlying_quantity=1000, spot_price=100)

# Buy protective puts (downside protection)
portfolio.add_position(95, maturity_30d, 10, "put")

# Sell covered calls (income generation)
portfolio.add_position(105, maturity_30d, -10, "call")

stats = portfolio.summary_stats()
print(f"Protected range: $95 - $105")
print(f"Net cost: ${stats['total_value']:.2f}")
```

### Delta Hedging

```python
# Check hedge effectiveness
stats = portfolio.summary_stats()

if abs(stats['net_delta']) > 10:
    if stats['delta_adjustment'] > 0:
        print(f"BUY {stats['delta_adjustment']:.0f} shares")
    else:
        print(f"SELL {abs(stats['delta_adjustment']):.0f} shares")
else:
    print("Portfolio is delta neutral ✓")
```

### Monitor Time Decay

```python
# Check daily theta
stats = portfolio.summary_stats()
annual_theta = stats['total_theta'] * 365  # Calendar days (industry standard)

print(f"Daily time decay: ${stats['total_theta']:.2f}")
print(f"Annual time decay: ${annual_theta:.2f}")
```

**Note on Theta Convention**: This library uses the industry standard of 365 calendar days (not 252 trading days) for theta calculations. This matches:

- Option pricing model assumptions (Black-Scholes, Bjerksund-Stensland)
- VIX and exchange conventions
- How volatility is expressed in time-to-expiration

## Key Metrics Explained

- **Delta**: Change in option price for $1 change in underlying
  - Call: 0 to 1, Put: -1 to 0
  - Portfolio delta = sum of all position deltas

- **Gamma**: Change in delta for $1 change in underlying
  - High gamma = delta changes rapidly
  - Max gamma near ATM (at-the-money)

- **Vega**: Change in option price for 1% change in volatility
  - Long options = positive vega (benefit from vol increase)
  - Short options = negative vega (benefit from vol decrease)

- **Theta**: Daily time decay
  - Long options = negative theta (lose value over time)
  - Short options = positive theta (gain value over time)

- **Net Delta**: Portfolio delta + notional position delta
  - Close to 0 = well hedged
  - Positive = net long exposure
  - Negative = net short exposure

- **Hedge Ratio**: % of notional position hedged by options
  - 100% = fully hedged
  - <100% = under-hedged
  - >100% = over-hedged

## Tips

1. **Rebalance regularly**: Delta changes as market moves (gamma effect)
2. **Monitor theta**: Factor in daily time decay costs
3. **Volatility risk**: Understand your vega exposure
4. **Liquidity**: Consider bid-ask spreads in real trading
5. **Early exercise**: American options can be exercised early - monitor intrinsic value

## Further Reading

- See `example.py` for a complete working example
- See `README.md` for detailed documentation
- See `options_dashboard.ipynb` for interactive analysis
