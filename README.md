# deltadewa

SPX tail-risk hedging system — a two-page Dash app, IPS-driven, QuantLib-priced.

## Overview

`deltadewa` is a hedging dashboard for a single-name **SPX tail-risk /
downside-protection** program. One Dash app (`deltadewa/app/`) serves two pages off a
shared server-side `ProgramState`, each targeting a different audience:

- **`/monitor` — Monitor & Report**: read-mostly view of the current book for routine
  checks and IC/board reporting, led by the crash scenario.
- **`/design` — Hedge Design**: the analyst's workbench — position editor, roll table,
  sizing workbench, strike ladder builder, monetization planner, and decision matrix.

The program policy lives in `config/ips.yaml` (carry budget, convexity targets, drawdown
tolerance, roll and monetization triggers). Methodology is drawn from the
[deltadewa-handbook](https://github.com/qwertytam/deltadewa-handbook) repo
(`HANDBOOK.md`), extracted out of this repo's `docs/` so it can be read and
reused on its own.

Market data defaults to **fully offline** (seeded from the loaded portfolio), with an
optional live CBOE/FRED pull that falls back gracefully on network failure.

## Features

- **Crash convexity & payoff ratio** — hedge P&L at the IPS crash scenario
  (`convexity.crash_scenario_pct`); realised payoff vs. cumulative carry paid
- **Net carry** — annualized theta as % of notional; tracked against the IPS carry budget
- **Market-environment tiers** — VIX term structure (contango / flat / backwardation),
  SKEW-index percentile, vol-regime percentile
- **Roll Status** — per-position moneyness drift, time decay, and roll-up cost ladder
- **Vega sufficiency, delta drift, convexity cliff** — banded against IPS policy on
  `/design`
- **Sizing workbench, strike ladder builder, monetization planner** — drive the
  `/design` page's PLANNING zone
- **Decision matrix** — structured roll / monetization / re-risk checklist
- **Program report** — IC/board format, delivered as the emailed weekly digest
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
```

<!-- markdownlint-disable-next-line -->
5. Activate the virtual environment:

```bash
poetry shell
```

## Dashboard Organization

The Dash app serves two pages off one shared server-side `ProgramState`, each with
its own audience and purpose.

### 📋 `/monitor` — Monitor & Report

Read-mostly view of the current book, for routine checks and IC/board reporting.

- Crash scenario explorer — spot/vol/quantity dials, payoff curve, scenario numbers
- Cost panel, including the hedge-efficiency reading
- Decisions — per-position roll verdicts with reasons, monetization schedule
- Position detail ledger (collapsed)

### 🛠️ `/design` — Hedge Design

Workbench mode: load a book and design changes to it. Three zones:

- **BOOK** — position editor, underlying quantity with net-delta readout,
  guarded import/export
- **PLANNING** — market environment, sizing (with vega sufficiency), strike
  ladder, roll table, hedge rebalance triggers, delta drift, convexity cliff,
  monetization
- **EXPLORATION** — spot × vol and time × price heatmaps, Monte Carlo
  distribution, vega term exposure

Plus the **weekly digest** (`deltadewa/reporting/weekly_report.py`) — an emailed
report carrying the Part VII board/IC format, the decision matrix and market context.

### Launch the dashboard

```bash
poetry run python -m deltadewa.app
```

Then open <http://127.0.0.1:8050/monitor> or `/design`.

## Quick Start

The canonical SPX tail-hedge book is in `examples/portfolios/spx_protective_put.yaml` —
two tranches of OTM long puts against a 1,000-unit SPX notional, with European exercise
style, entry tracking, and realistic implied-vol skew. Import it via the
**Import portfolio** control in `/design`'s BOOK zone.

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

stats = get_volatility_stats(portfolio)
print(f"Vega-weighted avg: {stats['avg_volatility']:.2%}")
print(
    f"Vol range:         {stats['min_volatility']:.2%} – {stats['max_volatility']:.2%}"
)
```

## Configuration

`config/ips.yaml` holds this program's real policy values — it is gitignored,
not shipped (#245), mirroring the repo's `.env` / `.env.example` split. Copy the
tracked template and fill in your own numbers before running anything:

```bash
cp config/ips.example.yaml config/ips.yaml
```

| File | Purpose | Guide |
|---|---|---|
| `config/ips.yaml` | Program policy — carry budget, convexity targets, drawdown tolerance, roll/monetization triggers | [yaml-config-guide.md](docs/yaml-config-guide.md) |

**The IPS is the only config the app loads.** There was a second,
presentation-only `config/dashboard.yaml` carrying gauge geometry; it lost its
last reader in Stage 4.3 and its last loader in #279, which retired the file,
its template, the `examples/dashboard/` presets and their guide. Its policy
content had already migrated into the IPS — see `docs/part-x-coverage.md`,
"`config/dashboard.yaml` had no reader — and then no loader (#279)".

A missing `config/ips.yaml` is different: the loader
raises, and every consumer degrades *visibly* rather than silently (`/monitor`
and `/design` render an explicit "No IPS policy is loaded" screen; the weekly
digest refuses to build). Copy the example rather than relying on that
fallback — it means the app is running without your program's real policy.

For the IPS, start from `config/ips.example.yaml` above;
`examples/ips/ips_default.yaml` illustrates the same schema with the same
placeholder numbers. Nothing under `examples/` is this
program's real policy (#249).

## Project Structure

```ini
deltadewa/
├── deltadewa/
│   ├── analysis/          # metrics: carry, health, hedge triggers, market env, roll status, vol
│   ├── app/               # the Dash app: factory.py, chrome.py, pages/{monitor,design}.py
│   ├── marketdata/        # CboeFredProvider, StaticProvider, provider interface
│   ├── portfolio/         # domain model: position.py, core.py, Monte Carlo, risk, factory
│   ├── reporting/         # weekly digest, program report, ConsoleReporter, PortfolioLogger
│   ├── visualization/     # chart builders
│   ├── constants.py       # ExerciseStyle enum and shared constants
│   ├── ips_config.py      # IPS policy schema and loader
│   ├── persistence.py     # PortfolioSerializer (YAML/JSON round-trip)
│   ├── state.py           # ProgramState — the shared server-side book + IPS state
│   └── valuation.py       # OptionValuation (QuantLib pricing engine)
├── config/
│   ├── ips.example.yaml   # template — copy to ips.yaml and fill in
│   └── ips.yaml           # program policy (gitignored — real values, #245)
├── examples/
│   ├── portfolios/        # spx_protective_put.yaml, spy_collar.yaml, …
│   └── ips/               # policy presets
├── docs/
│   ├── part-x-coverage.md # handbook-item → surface map; read before moving a panel
│   └── yaml-config-guide.md
├── pyproject.toml
└── tests/
```

## Dependencies

- **QuantLib-Python**: Quantitative finance library for option pricing
- **Dash**: the web UI (`/monitor`, `/design`)
- **pandas**: Data manipulation and analysis
- **numpy**: Numerical computing
- **plotly**: Interactive charts
- **gunicorn**: production WSGI server

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for the
gate a change must pass and the project's actual workflow.

## Security

See [SECURITY.md](SECURITY.md) for how to report a vulnerability and this
repo's standing rule on operational values.

## License

See [LICENSE](LICENSE) file for details. See
[CHANGELOG.md](CHANGELOG.md) for release history.

## References

- [deltadewa-handbook](https://github.com/qwertytam/deltadewa-handbook) —
  methodology source of truth for the hedging program
- [QuantLib Documentation](https://www.quantlib.org/)
- Bjerksund, P., and Stensland, G. (1993). "Closed-Form Approximation of American
  Options"
- Hull, J. C. "Options, Futures, and Other Derivatives"
