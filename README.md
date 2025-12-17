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

2. Install Poetry (if not already installed):
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

3. Install dependencies:
```bash
poetry install
```

4. Activate the virtual environment:
```bash
poetry shell
```

## Usage

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
    notional_position=1000.0,  # Long 1000 shares
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

## Project Structure

```
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
