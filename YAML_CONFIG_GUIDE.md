# YAML Configuration Guide

## Overview

The Options Dashboard now supports YAML-based configuration files for defining market parameters and portfolio positions. This makes it easier to:

- Define different portfolio scenarios without modifying code
- Version control your portfolio configurations
- Share portfolio setups with colleagues
- Quickly switch between different strategies

## Quick Start

### 1. Using Example Configurations

Three example YAML configuration files are provided:

- **`portfolio_config_example.yaml`** - Complete example with puts and calls
- **`portfolio_config_collar.yaml`** - Protective collar strategy
- **`portfolio_config_straddle.yaml`** - Long straddle strategy

To use any of these:

1. Copy the desired example to `portfolio_config.yaml`:
   ```bash
   cp portfolio_config_example.yaml portfolio_config.yaml
   ```

2. Run the notebook - it will automatically detect and load `portfolio_config.yaml`

### 2. Creating Your Own Configuration

Create a file named `portfolio_config.yaml` with this structure:

```yaml
market_parameters:
  spot_price: 100.0          # Current price of underlying
  volatility: 0.25           # 25% annual volatility
  risk_free_rate: 0.05       # 5% annual rate
  dividend_yield: 0.02       # 2% annual yield
  notional_position: 1000.0  # Underlying shares position
  symbol: "SPY"              # Optional default symbol

positions:
  - option_type: "put"
    strike_price: 95.0
    maturity_days: 30        # Days from today
    quantity: 5              # Positive = long, negative = short
    symbol: "SPY"            # Optional override
  
  - option_type: "call"
    strike_price: 105.0
    maturity_date: "2026-01-18"  # Or use absolute date
    quantity: -3             # Short 3 contracts
```

## YAML Configuration Reference

### Market Parameters (Required)

| Parameter | Type | Description |
|-----------|------|-------------|
| `spot_price` | float | Current price of underlying asset |
| `volatility` | float | Annual volatility (e.g., 0.25 = 25%) |
| `risk_free_rate` | float | Annual risk-free rate (e.g., 0.05 = 5%) |
| `dividend_yield` | float | Annual dividend yield (e.g., 0.02 = 2%) |
| `notional_position` | float | Size of underlying position in shares (optional, default: 0) |
| `symbol` | string | Default symbol for positions (optional, default: "UNKNOWN") |

### Position Configuration

Each position requires:

| Field | Type | Description |
|-------|------|-------------|
| `option_type` | string | "call" or "put" (case insensitive) |
| `strike_price` | float | Strike price of the option |
| `quantity` | integer | Number of contracts (positive = long, negative = short) |
| `symbol` | string | Underlying symbol (optional, inherits from market_parameters) |

**Maturity Date** - Use ONE of these:
- `maturity_days`: integer - Days from today (e.g., 30)
- `maturity_date`: string - Absolute date in ISO format (e.g., "2026-01-18")

## Export and Import Features

### Exporting Portfolios

The notebook's Section 11 provides interactive widgets for exporting:

**Export Formats:**
- **JSON** - Complete portfolio state with all greeks and metadata
- **CSV** - Positions and risk metrics in spreadsheet format
- **YAML** - Configuration format (easy to edit and version control)
- **All Formats** - Export to all three formats at once

**To Export:**
1. Navigate to Section 11 in the notebook
2. Select desired format
3. Enter filename prefix
4. Click "Export Portfolio"

### Importing Portfolios

The import widgets support:

**Import Sources:**
- **File Upload** - Upload JSON or YAML files directly in the browser
- **Filename** - Load files from the exports directory

**Import Options:**
- **Preview** - View portfolio contents before importing
- **Replace current portfolio** - Update the active `portfolio` variable (checkbox)

**To Import:**
1. Navigate to Section 11 in the notebook
2. Choose JSON or YAML format
3. Either upload a file or enter filename
4. Click "Preview File" to inspect (optional)
5. Check "Replace current portfolio" to update active portfolio
6. Click "Import Portfolio"

## Backward Compatibility

If no `portfolio_config.yaml` file exists, the notebook will use the hardcoded default portfolio (puts and calls at various strikes and maturities). This ensures existing workflows continue to work.

Status messages will indicate:
- 📁 "MARKET PARAMETERS LOADED FROM YAML" - when YAML is found
- 📝 "USING DEFAULT MARKET PARAMETERS" - when no YAML exists

## Example: Switching Between Strategies

```bash
# Use protective collar
cp portfolio_config_collar.yaml portfolio_config.yaml

# Run notebook cells 1-6
# Portfolio now has collar strategy

# Switch to long straddle
cp portfolio_config_straddle.yaml portfolio_config.yaml

# Restart kernel and run cells 1-6
# Portfolio now has straddle strategy
```

## Validation and Error Handling

The YAML loader validates:
- Required market parameters are present
- YAML syntax is correct
- Position structures are valid

Error messages will indicate:
- Missing required fields
- Invalid YAML syntax
- File not found
- Other configuration errors

## Tips and Best Practices

1. **Version Control**: Keep your YAML configs in git for history tracking
2. **Comments**: Use YAML comments (#) to document your strategy
3. **Naming**: Use descriptive filenames (e.g., `portfolio_hedge_2024Q1.yaml`)
4. **Validation**: Always use "Preview" when importing to verify correctness
5. **Backup**: Export your current portfolio before importing a new one
6. **Testing**: Test new configurations with small position sizes first

## File Locations

- Configuration files: Place `portfolio_config.yaml` in the notebook directory
- Exports: Saved to `exports/` subdirectory (configurable in cell 1)
- Examples: `portfolio_config_*.yaml` files included in repository

## Troubleshooting

**"No YAML config found" message**
- File must be named exactly `portfolio_config.yaml`
- File must be in the same directory as the notebook
- Check file permissions

**"Missing required market parameter" error**
- Ensure all required parameters are present in `market_parameters` section
- Check spelling of parameter names

**Import fails with FileNotFoundError**
- Check that file exists in `exports/` directory
- Verify filename matches exactly (case sensitive)
- Try using the file upload widget instead

**Positions not loading from YAML**
- Ensure each position has either `maturity_days` or `maturity_date`
- Check that `option_type` is "call" or "put"
- Verify `strike_price` and `quantity` are present

## See Also

- [QUICKSTART.md](QUICKSTART.md) - General dashboard usage
- [README.md](README.md) - Project overview
- Example configurations in repository root
