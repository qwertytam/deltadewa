# Quick Start Guide

## Installation

```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies
poetry install --with dev

# Activate environment
poetry shell

# Copy the config templates and fill in your own policy
cp config/ips.example.yaml config/ips.yaml
```

## Quick Examples

### Example 1: Price a Single Option

SPX options are cash-settled and European-exercise (see CLAUDE.md's domain
rules), so this prices a European put directly through `OptionValuation` —
the same engine every position in the app is priced with. Use
`ExerciseStyle.AMERICAN` only for single-name/SPY-style options.

```python
from datetime import timedelta

from deltadewa import OptionValuation
from deltadewa.clock import program_trading_date
from deltadewa.constants import ExerciseStyle, OptionType

today = program_trading_date()

put = OptionValuation(
    spot_price=100.0,
    strike_price=95.0,
    maturity_date=today + timedelta(days=30),
    volatility=0.25,
    risk_free_rate=0.05,
    dividend_yield=0.02,
    exercise_style=ExerciseStyle.EUROPEAN,
    option_type=OptionType.PUT,
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
from datetime import timedelta

from deltadewa import OptionPortfolio
from deltadewa.constants import ExerciseStyle, OptionType

# Create portfolio with a notional position
portfolio = OptionPortfolio(
    underlying_quantity=1000.0,  # Long 1000 shares
    spot_price=100.0,
    volatility=0.25,
    risk_free_rate=0.05,
    dividend_yield=0.02,
    # Positions added via add_position() fall back to this when they
    # don't set their own exercise_style — required, or add_position()
    # raises ValueError. SPX portfolios always want EUROPEAN.
    default_exercise_style=ExerciseStyle.EUROPEAN,
)

# Add protective puts
maturity = portfolio.valuation_date + timedelta(days=60)
portfolio.add_position(95.0, maturity, 10, OptionType.PUT)
portfolio.add_position(100.0, maturity, 5, OptionType.PUT)

# Get portfolio analytics
stats = portfolio.summary_stats()
print(f"Portfolio Value: ${stats['total_value']:,.2f}")
print(f"Net Delta: {stats['net_delta']:.2f}")
print(f"Hedge Ratio: {stats['hedge_ratio']:.2f}%")
print(f"Delta Adjustment: {stats['delta_adjustment']:.0f} shares")
```

### Example 3: Run Scenario Analysis

Continuing from Example 2's `portfolio`:

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
    metric="pnl",
)

# View results
print(scenario_df[["spot_price", "value"]])
```

### Example 4: Interactive Dashboards

The Dash app serves two pages, each for a different audience and workflow.
Start it with:

```bash
poetry run python -m deltadewa.app
```

See `README.md`'s Dashboard Organization section for the full panel list.

#### Monitor & Report — <http://127.0.0.1:8050/monitor>

Read-mostly view of the current book, for routine checks and IC/board
reporting.

1. **Crash scenario**: spot/vol/quantity dials, payoff curve, scenario numbers
2. **Cost**: carry against the IPS budget, plus the hedge-efficiency reading
3. **Decisions**: per-position roll verdicts with reasons, monetization schedule
4. **Position detail**: the collapsed per-leg ledger

#### Design & Roll — <http://127.0.0.1:8050/design>

Workbench mode: load a book and design changes to it.

1. **BOOK**: position editor, underlying quantity, net-delta readout,
   guarded import/export
2. **PLANNING**: market environment, sizing, strike ladder, roll table,
   hedge rebalance triggers, delta drift, convexity cliff, monetization
3. **EXPLORATION**: spot x vol and time x price heatmaps, Monte Carlo
   distribution, vega term exposure

## Common Use Cases

### Protective Collar Strategy

```python
from datetime import timedelta

from deltadewa import OptionPortfolio
from deltadewa.constants import ExerciseStyle, OptionType

# Long underlying position
portfolio = OptionPortfolio(
    underlying_quantity=1000,
    spot_price=100,
    default_exercise_style=ExerciseStyle.EUROPEAN,
)
maturity_30d = portfolio.valuation_date + timedelta(days=30)

# Buy protective puts (downside protection)
portfolio.add_position(95, maturity_30d, 10, OptionType.PUT)

# Sell covered calls (income generation)
portfolio.add_position(105, maturity_30d, -10, OptionType.CALL)

stats = portfolio.summary_stats()
print(f"Protected range: $95 - $105")
print(f"Net cost: ${stats['total_value']:.2f}")
```

### Delta Hedging

Continuing from the collar's `portfolio`:

```python
# Check hedge effectiveness
stats = portfolio.summary_stats()

if abs(stats["net_delta"]) > 10:
    if stats["delta_adjustment"] > 0:
        print(f"BUY {stats['delta_adjustment']:.0f} shares")
    else:
        print(f"SELL {abs(stats['delta_adjustment']):.0f} shares")
else:
    print("Portfolio is delta neutral ✓")
```

### Monitor Time Decay

Continuing from the same `portfolio`:

```python
# Check daily theta
stats = portfolio.summary_stats()
annual_theta = stats["total_theta"] * 365  # Calendar days (industry standard)

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
  - &lt;100% = under-hedged
  - &gt;100% = over-hedged

## Tips

1. **Rebalance regularly**: Delta changes as market moves (gamma effect)
2. **Monitor theta**: Factor in daily time decay costs
3. **Volatility risk**: Understand your vega exposure
4. **Liquidity**: Consider bid-ask spreads in real trading
5. **Early exercise**: American options can be exercised early - monitor intrinsic value

## Further Reading

- See `README.md` for detailed documentation
- Run `poetry run python -m deltadewa.app` and open `/monitor` or `/design`
  for interactive analysis
- The handbook itself lives at
  [qwertytam/deltadewa-handbook](https://github.com/qwertytam/deltadewa-handbook)
  (`HANDBOOK.md`); see `docs/part-x-coverage.md` for the handbook-item →
  surface map
