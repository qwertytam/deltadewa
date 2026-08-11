# deltadewa

SPX tail-risk hedging system — two Jupyter dashboards, IPS-driven, QuantLib-priced.

## Overview

`deltadewa` is a Jupyter-based hedging dashboard for a single-name **SPX tail-risk /
downside-protection** program. Two notebooks share the same underlying package, each
targeting a different audience:

- **`monitor_dashboard.ipynb` — Monitor & Report**: read-mostly view of the current book
  for routine checks and IC/board reporting. Covers handbook Tiers 1–4 and the Part VII
  program report.
- **`hedge_design.ipynb` — Hedge Design**: the analyst's workbench — position editor, roll
  planner, sizing workbench, strike ladder builder, monetization planner, and decision
  matrix.

Both call `start_session(role=..., globals_dict=globals())` from `deltadewa.dashboard`.
The program policy lives in `config/ips.yaml` (carry budget, convexity targets, drawdown
tolerance, roll and monetization triggers). Methodology is drawn from
[`docs/hedging handbook.md`](docs/hedging%20handbook.md).

Market data defaults to **fully offline** (seeded from the loaded portfolio), with an
optional live CBOE/FRED pull that falls back gracefully on network failure.

## Features

- **Crash convexity & payoff ratio** — hedge P&L at the IPS crash scenario
  (`convexity.crash_scenario_pct`); realised payoff vs. cumulative carry paid
- **Net carry** — annualized theta as % of notional; tracked against the IPS carry budget
- **Market-environment tiers** — VIX term structure (contango / flat / backwardation),
  SKEW-index percentile, vol-regime percentile
- **Roll Status** — per-position moneyness drift, time decay, and roll-up cost ladder
- **Seven hedge-health gauges** with configurable thresholds (`config/dashboard.yaml`)
- **Sizing workbench, strike ladder builder, monetization planner** — done; drive
  a panel in `hedge_design.ipynb` and the Dash `/design` page's PLANNING zone
- **Decision matrix** — structured roll / monetization / re-risk checklist
- **Program report** — IC/board format (Monitor dashboard)
- **IPS policy contract** — carry budget, convexity and drawdown targets, roll/rally/
  monetization triggers (`config/ips.yaml`)
- **Live CBOE/FRED market data** (optional; disk-cached with a policy-driven TTL
  — `market_environment.data_ttl_minutes` in `config/ips.yaml`; automatic offline
  fallback)

## Pricing

### SPX — European (default)

SPX options are **cash-settled European** with no early-exercise value. Price them with
the analytic Black-Scholes engine by setting `exercise_style: "EUROPEAN"` on each
position (see `examples/portfolios/spx_protective_put.yaml`). The American approximation
**overstates put values** for SPX and must not be used.

### SPY / single-name equities — American (secondary)

For underlyings with potential early exercise (dividends, physically-settled single-stock
options), omit `exercise_style` or set it to `"AMERICAN"`. This selects the
**Bjerksund-Stensland** analytical approximation via QuantLib.

#### Bjerksund-Stensland Model

The Bjerksund-Stensland model provides fast, closed-form American option pricing that:

- Handles early-exercise features for dividend-paying underlyings
- Works for both calls and puts
- Delivers near-instantaneous Greeks without lattice or PDE overhead

Both engines share the same `OptionValuation` interface in `deltadewa/valuation.py`;
exercise style is selected per-position in the portfolio YAML.

## Installation

### Prerequisites

- Python 3.11 or higher
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
4. Copy the config templates and fill in your own program's policy (they
   hold real values and are gitignored — see [Configuration](#configuration)):

```bash
cp config/ips.example.yaml config/ips.yaml
cp config/dashboard.example.yaml config/dashboard.yaml
```

<!-- markdownlint-disable-next-line -->
5. Activate the virtual environment:

```bash
poetry shell
```

### Jupyter Notebook Output Management

This repository uses `nbstripout` to keep notebook outputs out of version control while
preserving them locally.

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

## Dashboard Organization

The dashboard is split into two notebooks, each with its own audience and purpose. Both
call `start_session(role=..., globals_dict=globals())` from `deltadewa.dashboard` and
share the same underlying package — only the panels and setup differ.

#### 📋 `monitor_dashboard.ipynb` — Monitor & Report

Read-mostly view of the current book, for routine checks and IC/board reporting. Starts
**empty** — load a portfolio explicitly via the import widget. No position editor.

- Net Hedge Summary, Hedge Health, Roll Status, Hedge Decision Triggers
- Cost of Carry, Position Aging, Position Detail
- Consolidated Greeks view
- A single current-structure stress snapshot (spot × vol heatmap)
- Session Change Log and export

#### 🛠️ `hedge_design.ipynb` — Hedge Design

Workbench mode: load a book and design changes to it.

- Position Editor, editable scenario assumptions
- Roll planner (candidate roll-up costs via `analysis.roll_status`)
- Sizing workbench, strike ladder builder, monetization planner — done; also on
  the Dash `/design` page's PLANNING zone
- Eager Monte Carlo run, full stress tooling (time × price / spot × vol heatmaps),
  Risk/Reward summary, Volatility Profile
- Session Change Log and export

### Launch Jupyter Dashboard

Start the Monitor dashboard (read-only book review):

```bash
jupyter lab monitor_dashboard.ipynb
```

Start the Hedge Design dashboard (construction + stress testing):

```bash
jupyter lab hedge_design.ipynb
```

## Quick Start

The canonical SPX tail-hedge book is in `examples/portfolios/spx_protective_put.yaml` —
two tranches of OTM long puts against a 1,000-unit SPX notional, with European exercise
style, entry tracking, and realistic implied-vol skew. Import it via the
**Import Portfolio** widget at the top of each notebook.

### Session bootstrap

```python
# Paste into the notebook setup cell, then run all cells.
from deltadewa.dashboard import start_session

ctx = start_session(role="monitor", globals_dict=globals())
# Use the Import Portfolio widget to load a YAML book, e.g.:
#   examples/portfolios/spx_protective_put.yaml
```

```python
# For live CBOE/FRED market data (optional; falls back offline on network error):
ctx = start_session(
    role="monitor",
    globals_dict=globals(),
    use_live_market_data=True,
)
```

The `role` argument (`"monitor"` or `"design"`) is stored on the returned
`SessionContext` for later use.

### Per-position volatility

Portfolio YAML files support per-position implied volatility to model the skew:

```yaml
positions:
  - option_type: "put"
    strike_price: 5200.0
    maturity_date: "2027-06-17"
    quantity: 5
    volatility: 0.19          # OTM skew above ATM
    exercise_style: "EUROPEAN"
```

Scenario grids (stress tests) preserve the relative skew structure by scaling each
position's vol proportionally to a vega-weighted portfolio average. Use
`get_volatility_stats` to inspect:

```python
from deltadewa.analysis import get_volatility_stats

stats = get_volatility_stats(ctx.portfolio)
print(f"Vega-weighted avg: {stats['avg_volatility']:.2%}")
print(
    f"Vol range:         {stats['min_volatility']:.2%} – {stats['max_volatility']:.2%}"
)
```

## Configuration

`config/ips.yaml` and `config/dashboard.yaml` hold this program's real policy
and presentation values — they are gitignored, not shipped (#245), mirroring
the repo's `.env` / `.env.example` split. Copy the tracked templates and fill
in your own numbers before running anything:

```bash
cp config/ips.example.yaml config/ips.yaml
cp config/dashboard.example.yaml config/dashboard.yaml
```

| File | Purpose | Guide |
|---|---|---|
| `config/ips.yaml` | Program policy — carry budget, convexity targets, drawdown tolerance, roll/monetization triggers | [yaml-config-guide.md](docs/yaml-config-guide.md) |
| `config/dashboard.yaml` | Health-gauge thresholds and color bands (presentation only) | [dashboard-config-guide.md](docs/dashboard-config-guide.md) |

A missing `config/dashboard.yaml` falls back to sensible built-in defaults —
never a hard failure. A missing `config/ips.yaml` is different: the loader
raises, and every consumer degrades *visibly* rather than silently (`/monitor`
and `/design` render an explicit "No IPS policy is loaded" screen; the weekly
digest refuses to build). Copy the example rather than relying on that
fallback — it means the app is running without your program's real policy.

Presets live in `examples/ips/` and `examples/dashboard/`. Copy one over the
corresponding `config/` file to activate it.

## Project Structure

```ini
deltadewa/
├── deltadewa/
│   ├── analysis/          # metrics: carry, health, hedge triggers, market env, roll status, vol
│   ├── dashboard/         # start_session(), session bootstrap, widget wiring
│   ├── marketdata/        # CboeFredProvider, StaticProvider, provider interface
│   ├── portfolio/         # domain model: position.py, core.py, Monte Carlo, risk, factory
│   ├── reporting/         # ConsoleReporter, PortfolioLogger
│   ├── visualization/     # chart builders
│   ├── widgets/           # Jupyter UI widgets
│   ├── constants.py       # ExerciseStyle enum and shared constants
│   ├── ips_config.py      # IPS policy schema and loader
│   ├── persistence.py     # PortfolioSerializer (YAML/JSON round-trip)
│   └── valuation.py       # OptionValuation (QuantLib pricing engine)
├── config/
│   ├── ips.example.yaml       # template — copy to ips.yaml and fill in
│   ├── dashboard.example.yaml # template — copy to dashboard.yaml and fill in
│   ├── ips.yaml           # program policy (gitignored — real values, #245)
│   └── dashboard.yaml     # health-gauge thresholds (gitignored — real values)
├── examples/
│   ├── portfolios/        # spx_protective_put.yaml, spy_collar.yaml, …
│   ├── ips/               # policy presets
│   └── dashboard/         # gauge-threshold presets
├── docs/
│   ├── hedging handbook.md
│   ├── yaml-config-guide.md
│   └── dashboard-config-guide.md
├── monitor_dashboard.ipynb
├── hedge_design.ipynb
├── pyproject.toml
└── tests/
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

- [`docs/hedging handbook.md`](docs/hedging%20handbook.md) — methodology source of truth
  for the hedging program
- [QuantLib Documentation](https://www.quantlib.org/)
- Bjerksund, P., and Stensland, G. (1993). "Closed-Form Approximation of American
  Options"
- Hull, J. C. "Options, Futures, and Other Derivatives"
