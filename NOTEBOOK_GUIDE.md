# Options Dashboard Notebook Guide

## Overview

The `options_dashboard.ipynb` notebook has been restructured into a streamlined 3-mode interface for comprehensive options portfolio management.

## New Structure

### 1. Global Setup (Cells 1-9)

- **Imports**: All required libraries loaded once
- **Configuration**: Portfolio initialization from YAML or defaults
- **Global Assumptions Widget**: Centralized market parameters panel
  - Spot price, volatility, interest rates, dividend yield
  - Time horizon presets and scenario parameters
  - Single source of truth for all analysis
- **Net Hedge Summary**: Always-visible KPI dashboard
  - Real-time portfolio Greeks
  - Crash convexity indicators
  - Probabilistic statistics

### 2. MODE 1: BUILD (Cells 10-19)

#### Portfolio Construction and Management

- Position editor with interactive widgets
- Import/export controls (JSON, CSV, YAML)
- Portfolio summary and health check
- Detailed position table with styling
- Real-time updates to Net Hedge Summary

**Key Features:**

- Add/modify/delete positions
- Load existing portfolios
- Track position changes
- Automatic hedge summary refresh

### 3. MODE 2: EXPLAIN (Cells 20-33)

#### At-a-Glance Hedge Behavior

- **Consolidated Greeks View**: Single unified visualization
  - Net portfolio Greeks table
  - Top 5 contributors per Greek
  - Greeks sensitivity heatmap
  - Optional detailed breakdowns by strike/maturity
  
- **P&L Diagrams**:
  - Options-only P&L profile
  - Total P&L including underlying exposure
  
- **Position Breakdown Charts**:
  - By option type (calls/puts)
  - By strike price
  - By maturity date
  - Delta contribution analysis
  
- **Cashflow & Theta Tracking**
- **Position Aging Analysis**
- **Hedge Decision Triggers**

**Key Features:**

- All charts reference Global Assumptions
- No duplicate parameter sliders
- Uses `plot_greeks_consolidated()` for efficiency

### 4. MODE 3: STRESS (Cells 34-45)

#### Scenario Analysis and Risk Metrics

- **Interactive Heatmaps**:
  - Spot price vs. volatility scenarios
  - Color-coded P&L surface
  - Current position marker
  
- **Time Decay Scenarios**:
  - Multiple spot price paths
  - Evolution across time horizons
  - Configurable via Global Assumptions
  
- **Risk/Reward Analysis**:
  - Monte Carlo simulations (100K paths)
  - Value at Risk (VaR 95%, 99%)
  - Conditional VaR (CVaR)
  - Probability distributions
  
- **3D P&L Surface** (optional, requires Plotly)
- **Volatility Profile Analysis**

**Key Features:**

- Uses `ScenarioGridCache` for performance
- Leverages Global Assumptions parameters
- Probabilistic metrics and tail risk

### 5. Export & Session Management (Cells 46-52)

- Session change log review
- Portfolio export with full history
- Multiple format support (JSON/CSV/YAML)

## Key Improvements

### ✅ Centralized Parameters

- **Before**: 4+ scattered slider controls for market parameters
- **After**: Single `GlobalAssumptions` widget referenced everywhere
- **Benefit**: Consistency, easier parameter sweeps, cleaner UI

### ✅ Always-Visible KPIs

- **New**: `NetHedgeSummary` widget at top of notebook
- **Updates**: Automatically refreshes on portfolio changes
- **Content**: Core Greeks, crash indicators, probabilistic stats

### ✅ Consolidated Greeks

- **Before**: Separate sections for each Greek
- **After**: Single `plot_greeks_consolidated()` visualization
- **Benefit**: 80/20 rule - show what matters, details on demand

### ✅ Performance Optimization

- **New**: `ScenarioGridCache` for expensive calculations
- **Benefit**: Faster scenario analysis, automatic invalidation

### ✅ Clear Organization

- **Visual Mode Headers**: Gradient-styled HTML dividers
- **Logical Flow**: Build → Explain → Stress → Export
- **Focused Sections**: Each mode has specific purpose

## Usage Tips

1. **First Run**: Execute cells sequentially from top
2. **Global Assumptions**: Change parameters here, effects ripple everywhere
3. **Net Hedge Summary**: Glance at this for portfolio health
4. **BUILD Mode**: Construct positions, see immediate updates
5. **EXPLAIN Mode**: Understand current Greeks and P&L
6. **STRESS Mode**: Test extreme scenarios before they happen
7. **Export**: Save work frequently using final widgets

## Migration Notes

### From Old Notebook (44 cells → 52 cells)

- All functionality preserved
- Market parameter sliders consolidated
- Position editor moved to BUILD mode
- Greeks analysis in EXPLAIN mode
- Scenario analysis in STRESS mode
- Export remains at end

### Backward Compatibility

- Import/export formats unchanged
- Portfolio files load exactly as before
- All analysis functions preserved
- Configuration YAML still supported

## Dependencies

### Required

- deltadewa (with new widgets module)
- numpy, pandas, matplotlib
- ipywidgets

### Optional

- plotly (for 3D visualizations)

## Cell Execution Order

1. **Always run**: Cells 1-9 (setup)
2. **Build Portfolio**: Cells 10-19
3. **Analysis**: Any of cells 20-45 (independent)
4. **Export**: Cells 46-52

## Troubleshooting

### "GlobalAssumptions not found"

- Ensure cell 3 (imports) executed successfully
- Check deltadewa installation includes latest widgets

### "NetHedgeSummary not updating"

- Verify callback registered in position editor (cell 14)
- Manually call `net_hedge_summary.update()` if needed

### "ScenarioGridCache errors"

- Check deltadewa.analysis module import (cell 3)
- Cache is optional - can disable for debugging

## Backup

Original notebook saved as: `options_dashboard_backup.ipynb`

## Version

- Structure Version: 3.0 (3-Mode Layout)
- Compatible with: deltadewa v0.2.0+
- Last Updated: 2024
