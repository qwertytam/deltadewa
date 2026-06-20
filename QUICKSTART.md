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
import datetime
from datetime import datetime as dt
from datetime import timedelta
from deltadewa import AmericanOption

# Create an American put option
put = AmericanOption(
    spot_price=100.0,
    strike_price=95.0,
    maturity_date=dt.now(datetime.UTC) + timedelta(days=30),
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
maturity = dt.now(datetime.UTC) + timedelta(days=60)
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
from deltadewa.analysis import PortfolioAnalyzer

# Create analyzer from portfolio
analyzer = PortfolioAnalyzer(portfolio)

# Analyze P&L across different spot prices
spot_range = np.linspace(80, 120, 41)
time_points = [portfolio.valuation_date]
scenario_df = analyzer.scenario_grid(
    spot_scenarios=spot_range,
    time_points=time_points,
    metric='pnl',
)

# View results
print(scenario_df[['spot_price', 'value']])
```
```

### Example 4: Interactive Dashboards

The dashboard is split into two notebooks, each for a different audience
and workflow. See `README.md`'s Dashboard Organization section for the
full panel list.

#### Monitor & Report — `monitor_dashboard.ipynb`

```bash
jupyter lab monitor_dashboard.ipynb
```

Read-mostly view of the current book, for routine checks and IC/board
reporting. Starts **empty** — load a portfolio via the import widget.

1. **Load a portfolio**: import via JSON/YAML
2. **Review health**: Net Hedge Summary, Hedge Health, Roll Status,
   Hedge Decision Triggers
3. **Review detail**: Cost of Carry, Position Aging, Position Detail,
   Consolidated Greeks
4. **Stress snapshot**: a single current-structure spot x vol heatmap

#### Design & Roll — `hedge_design.ipynb`

```bash
jupyter lab hedge_design.ipynb
```

Workbench mode: load a book and design changes to it.

1. **Build/edit**: Position Editor, editable scenario assumptions
2. **Plan a roll**: candidate roll-up costs via `analysis.roll_status`
3. **Stress-test**: eager Monte Carlo run, time x price / spot x vol
   heatmaps, Risk/Reward summary, Volatility Profile
4. *(stubbed, future work)* Sizing workbench, strike ladder builder,
   monetization planner

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
- See `monitor_dashboard.ipynb` / `hedge_design.ipynb` for interactive analysis
