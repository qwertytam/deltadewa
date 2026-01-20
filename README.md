# deltadewa

American Options Dashboard using QuantLib - Bjerksund-Stensland Model

## Overview

`deltadewa` is a comprehensive Jupyter-based dashboard for pricing and managing American options portfolios. It uses the **Bjerksund-Stensland** approximation model via QuantLib to provide accurate American option pricing and Greeks calculation.

### Features

- **American Option Pricing**: Uses the Bjerksund-Stensland approximation for accurate American option valuation
- **Portfolio Management**: Handle multiple positions with different strikes, maturities, and option types
- **Greeks Calculation**: Delta, Gamma, Vega, Theta, and Rho for individual positions and portfolio
- **Hedge Analysis**: Manage options against a notional position with hedge ratio and delta adjustment recommendations
- **Interactive Dashboard**: Jupyter widgets for real-time scenario analysis
- **Visualizations**: Comprehensive charts for P&L, Greeks, and position breakdowns
- **Scenario Analysis**: Test portfolio performance across different spot prices and volatilities

## Installation

### Prerequisites

- Python 3.9 or higher
- Poetry (for dependency management)

### Setup

1. Clone the repository:

```bash
git clone https://github.com/qwertytam/deltadewa.git
cd deltadewa
```

<!-- markdownlint-disable-next-line -->
2. Install Poetry (if not already installed):

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

<!-- markdownlint-disable-next-line -->
3. Install dependencies:

```bash
poetry install
```

<!-- markdownlint-disable-next-line -->
4. Activate the virtual environment:

```bash
poetry shell
```

### Jupyter Notebook Output Management

This repository uses `nbstripout` to keep notebook outputs out of version control while preserving them locally.

**Initial Setup:**

```bash
# Install dev dependencies (includes nbstripout)
poetry install --with dev

# Configure one-way filter (commit-only)
./setup_nbstripout.sh

# Or manually:
git config filter.nbstripout-commit.clean 'nbstripout'
git config filter.nbstripout-commit.smudge 'cat'
git config filter.nbstripout-commit.required true
```

**Why one-way filtering?**

- Outputs are stripped when you **commit** (keeps repo clean)
- Outputs are preserved when you **checkout/pull** (no duplicates)
- Prevents repeated cell outputs in VSCode when pulling agent changes

**If you see repeated outputs:** You need to run the setup script above.

## Usage

### Dashboard Organization

The `options_dashboard.ipynb` is organized into **3 intuitive modes** for streamlined workflow:

#### 🏗️ **Mode 1: BUILD (Portfolio Construction)**
- **Global Assumptions Panel**: Single source of truth for market parameters
  - Spot price, volatility, interest rates, dividend yield
  - Time horizon selector (T+0, T+7, T+30, T+60, T+90, custom)
  - Scenario grid parameters for stress testing
- **Net Hedge Summary**: Always-visible KPI header showing:
  - Core Greeks: Delta, Gamma, Vega, Theta
  - Portfolio cost and current value
  - Crash convexity indicators (-10%, -20%, -30% scenarios)
  - Expandable probabilistic statistics
- **Position Editor**: Interactive widget to add/update/remove positions
- **Import/Export**: Load/save portfolios in JSON or YAML format
- **Portfolio Summary**: Detailed position breakdown tables

#### 📊 **Mode 2: EXPLAIN (At-a-Glance Hedge Behavior)**
- **Consolidated Greeks View**: 80/20 optimized display
  - Net portfolio Greeks in a single table
  - Top 5 contributors bar charts for each Greek
  - Greeks sensitivity heatmap
  - Expandable detailed breakdowns (on-demand)
- **P&L Diagrams**: 
  - Options-only P&L at expiration
  - Total portfolio P&L (options + underlying)
  - Breakeven points, max loss/profit markers
- **Position Breakdown Charts**:
  - By option type (calls vs puts)
  - By strike price
  - By maturity date
- **Cashflow Tracking**: Premium paid/received analysis
- **Aging Analysis**: Position maturity profile

#### ⚡ **Mode 3: STRESS (Scenario Analysis)**
- **Interactive Heatmaps**: 2D scenario grids with caching
  - Spot vs volatility heatmaps
  - Time vs price P&L evolution
  - Greeks sensitivity surfaces
- **Monte Carlo Analysis**: Risk/reward metrics
  - Value at Risk (VaR)
  - Conditional VaR (CVaR)
  - Probability distributions
- **3D Visualization**: Optional 3D P&L surfaces (Plotly)
- **Performance Optimization**: Automatic scenario caching for speed

### Key Improvements

- **No Duplicate Controls**: Single GlobalAssumptions instance replaces scattered sliders
- **Reactive Updates**: Net Hedge Summary auto-updates on portfolio changes
- **Efficient Calculations**: ScenarioGridCache optimizes expensive computations
- **Clear Navigation**: Visual mode headers with gradient styling
- **Streamlined**: Consolidated Greeks view replaces 5 separate sections

### Launch Jupyter Dashboard

Start the interactive dashboard:

```bash
jupyter lab options_dashboard.ipynb
```

Or use the classic notebook interface:

```bash
jupyter notebook options_dashboard.ipynb
```

### Quick Start Example

The dashboard provides a complete workflow:

1. **Set Market Parameters**: Configure spot price, volatility, interest rates
2. **Build Portfolio**: Add multiple option positions (calls/puts, different strikes/maturities)
3. **Analyze Positions**: View all positions with Greeks and values
4. **Review Analytics**: Get portfolio-level metrics and hedge analysis
5. **Run Scenarios**: Test P&L across different market conditions
6. **Get Recommendations**: Receive hedge adjustment suggestions

### Python API Usage

You can also use the library programmatically:

```python
from datetime import datetime, timedelta
from deltadewa import AmericanOption, OptionPortfolio

# Create a portfolio
portfolio = OptionPortfolio(
    underlying_quantity=1000.0,  # Long 1000 shares
    spot_price=100.0,
    volatility=0.25,
    risk_free_rate=0.05,
    dividend_yield=0.02
)

# Add option positions
maturity = datetime.now() + timedelta(days=60)
portfolio.add_position(
    strike_price=95.0,
    maturity_date=maturity,
    quantity=10,
    option_type="put"
)

# Get portfolio analytics
stats = portfolio.summary_stats()
print(f"Total Delta: {stats['total_delta']:.2f}")
print(f"Net Delta: {stats['net_delta']:.2f}")
print(f"Hedge Ratio: {stats['hedge_ratio']:.2f}%")

# View positions
df = portfolio.to_dataframe()
print(df)
```

### Per-Position Volatility

You can specify different implied volatilities for individual positions to model volatility skew or smile:

```python
portfolio = OptionPortfolio(
    underlying_quantity=1000.0,
    spot_price=100.0,
    volatility=0.25,  # Default volatility
    risk_free_rate=0.05,
    dividend_yield=0.02
)

# Add position with custom volatility (e.g., modeling volatility skew)
portfolio.add_position(
    strike_price=95.0,
    maturity_date=maturity,
    quantity=10,
    option_type="put",
    volatility=0.35  # Custom volatility for this position (35%)
)

# Add position using default portfolio volatility
portfolio.add_position(
    strike_price=100.0,
    maturity_date=maturity,
    quantity=-5,
    option_type="call",
    # No volatility specified - uses portfolio default of 0.25
)

# View volatility per position
df = portfolio.to_dataframe()
print(df[['type', 'strike', 'volatility', 'custom_volatility']])

# Check volatility statistics
stats = portfolio.summary_stats()
print(f"Volatility range: {stats['volatility_min']:.2%} - {stats['volatility_max']:.2%}")
print(f"Positions with custom volatility: {stats['custom_volatility_count']}")
```

## Example Scenario

The default dashboard configuration includes:

- **Market**: Spot = $100, Vol = 25%, Risk-free = 5%, Dividend = 2%
- **Notional**: Long 1000 shares (to be hedged)
- **Positions**:
  - Long puts at strikes 90, 95, 100 (downside protection)
  - Short calls at strikes 105, 110, 115 (income generation)
  - Multiple maturities: 30, 60, 90 days

This creates a **collar-like** strategy that protects the downside while generating income from covered calls.

## Key Concepts

### Bjerksund-Stensland Model

The Bjerksund-Stensland model is an analytical approximation for American option pricing that:

- Provides fast, closed-form solutions
- Accurately handles early exercise features
- Works well for both calls and puts
- Considers dividends in the valuation

### Greeks

- **Delta**: Sensitivity to underlying price changes (hedge ratio)
- **Gamma**: Rate of change of delta (convexity risk)
- **Vega**: Sensitivity to volatility changes
- **Theta**: Time decay per day
- **Rho**: Sensitivity to interest rate changes

### Hedge Management

The dashboard helps you:

- Monitor net delta exposure (portfolio + notional)
- Calculate hedge ratio (% of notional hedged)
- Determine adjustments needed for delta neutrality
- Understand gamma risk and how delta will change

### Volatility Analysis

The dashboard includes sophisticated volatility sensitivity analysis that properly handles portfolios with position-level volatilities:

**Proportional Volatility Scaling**

When testing volatility scenarios (stress tests, scenario grids), the system:

1. Calculates a **vega-weighted average volatility** across all positions
2. Scales each position's volatility proportionally to maintain the volatility skew/smile
3. Preserves the relative volatility structure between positions

**Example:**

```python
# Portfolio with volatility skew
positions = [
    {"strike": 90, "vol": 0.35},   # OTM put - higher IV
    {"strike": 95, "vol": 0.30},   # Nearer put
    {"strike": 100, "vol": 0.25},  # ATM - default IV
    {"strike": 105, "vol": 0.22},  # OTM call - lower IV
]

# Vega-weighted average: 0.283
# Testing +20% vol scenario (avg becomes 0.34):
#   90 strike: 0.35 → 0.42 (scaled by 1.2×)
#   95 strike: 0.30 → 0.36 (scaled by 1.2×)
#   100 strike: 0.25 → 0.30 (scaled by 1.2×)
#   105 strike: 0.22 → 0.264 (scaled by 1.2×)
# Skew structure preserved!
```

**Benefits:**

- **Accurate vega analysis** - Position sensitivities remain proportional
- **Realistic scenarios** - Models real market volatility behavior
- **Proper risk assessment** - Captures volatility skew effects

**Volatility Statistics:**

Use the utility functions to analyze your portfolio's volatility profile:

```python
from deltadewa.utils import get_volatility_stats, calculate_portfolio_avg_volatility

stats = get_volatility_stats(portfolio)
print(f"Vega-weighted avg: {stats['avg_volatility']:.2%}")
print(f"Volatility range: {stats['min_volatility']:.2%} - {stats['max_volatility']:.2%}")
print(f"Positions with custom vol: {stats['num_custom_vol']}/{stats['num_positions']}")
```

## Project Structure

```ini
deltadewa/
├── deltadewa/                 # Python package
│   ├── __init__.py
│   ├── american_option.py    # American option pricing
│   └── portfolio.py           # Portfolio management
├── options_dashboard.ipynb    # Main Jupyter dashboard
├── pyproject.toml            # Poetry dependencies
└── README.md                 # This file
```

## Dependencies

- **QuantLib-Python**: Quantitative finance library for option pricing
- **Jupyter/JupyterLab**: Interactive notebook environment
- **pandas**: Data manipulation and analysis
- **numpy**: Numerical computing
- **matplotlib**: Static visualizations
- **plotly**: Interactive charts
- **ipywidgets**: Interactive dashboard widgets

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

See LICENSE file for details.

## References

- [QuantLib Documentation](https://www.quantlib.org/)
- Bjerksund, P., and Stensland, G. (1993). "Closed-Form Approximation of American Options"
- Hull, J. C. "Options, Futures, and Other Derivatives"
