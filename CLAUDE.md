# CLAUDE.md

Project memory for Claude Code. Read this before making changes.

## What this is

`deltadewa` is an options hedging dashboard for a single-name **SPX** tail-hedge
program. Pricing is done with **QuantLib**; the UI is a Jupyter notebook
(`options_dashboard.ipynb`) built from `ipywidgets`, `matplotlib`, and `plotly`.
The notebook is a thin orchestration layer — all real logic lives in the package.

## Environment & commands

Python `>=3.11,<4.0`, managed with **Poetry**. Run everything through `poetry run`.

- Install: `poetry install`
- Tests: `poetry run pytest`
- Type-check: `poetry run mypy .` (custom stubs live in `typings/`; `pandas-stubs` is installed)
- Lint: `poetry run ruff check .`
- Format: `poetry run black .` (or `poetry run ruff format .`) — **line length is 80**
- Lint/type-check notebooks: `poetry run nbqa ruff <notebook>` / `poetry run nbqa mypy <notebook>`

Before considering any change done: `poetry run pytest` and `poetry run mypy .` must both be green,
and `poetry run ruff check .` must be clean.

## Architecture (keep UI thin)

The package is layered. Put logic in the lower layers; keep widgets dumb.

- `portfolio/` — domain model and pricing. `position.py` (`OptionPosition`),
  `core.py` (`OptionPortfolio`), Monte Carlo, risk, factory.
- `valuation.py` — `OptionValuation`, the QuantLib pricing engine. Supports
  **both** `ExerciseStyle.AMERICAN` (Bjerksund–Stensland / finite-difference) and
  `ExerciseStyle.EUROPEAN` (analytic Black–Scholes). Enum is in `constants.py`.
- `analysis/` — metrics and decision logic: `health.py`, `hedge_triggers.py`,
  `carry.py`, `volatility.py`. **New metric/decision code goes here, UI-free.**
- `dashboard/` + `widgets/` — Jupyter UI only. `setup.py` wires a session together.
- `visualization/` — chart builders.
- `persistence.py` — portfolio load/save (YAML/JSON). Round-trip new fields here.
- `reporting/` — console/text output.

Rule of thumb: if it has a number in it, it belongs in `analysis/` or `portfolio/`
with a test — not in a widget or a notebook cell.

## Domain rules that matter

- **SPX options are European-exercise and cash-settled** — price them with
  `ExerciseStyle.EUROPEAN` (analytic engine), not the American approximation.
  American is correct only for SPY/single stocks. Do not change `OptionValuation`'s
  own default; select the style upstream (config / portfolio).
- Program thresholds (carry budget, convexity targets, drawdown tolerance, roll and
  monetization triggers) are policy — they belong in `ips.yaml`, not hardcoded.
- Presentation settings stay in `dashboard_config_*.yaml`. Keep policy and
  presentation config separate.

## Code conventions (ruff is strict — preview mode, large rule set)

- **Line length 80**, target `py311`.
- **Docstrings required** (`pydocstyle`/`D`) on modules, classes, and public functions.
- **Type annotations required** (`ANN`) on all new code; keep `mypy` clean.
- **Use `pathlib`**, not `os.path` (`PTH`).
- Bandit security checks are on (`S`): no hardcoded secrets, no bare `assert` in
  library code, be careful with `subprocess`/`requests`.
- Also enforced: isort import order (`I`), trailing commas (`COM`), pep8 naming
  (`N`), bugbear (`B`), comprehensions (`C4`), simplify (`SIM`), no commented-out
  code (`ERA`). Run `ruff check` early and often.

## Testing

- Tests live in `tests/`, mirroring the package (`tests/test_portfolio/`,
  `tests/test_dashboard/`, `tests/test_visualization/`). ~47 files today.
- Add or extend tests for every behaviour change. Pricing/metric logic must have
  unit tests with crafted inputs; UI widgets get lighter smoke tests.
- Prefer deterministic tests — no live network calls (mock HTTP; use static/offline
  providers for any market-data code).

## Notebooks

- Outputs are stripped on commit by a **one-way nbstripout git filter** (see
  `.gitattributes`: `*.ipynb filter=nbstripout-commit`). Never commit notebook
  outputs; the filter handles it, but don't fight it.
- `jupytext` is available if you need to diff/edit notebooks as scripts.
- Keep notebook cells short — construct a widget/display from the package and show it.

## Work in progress

Active foundation work (see `docs/deltadewa_implementation_plan.md` if present):
a `marketdata/` provider interface (free CBOE/FRED backend), an `ips.yaml` program
config, and a Roll Status panel — built in that order, then the notebook is split
into a Monitor dashboard and a Hedge-Design dashboard.

## Workflow expectations

- Use plan mode for non-trivial changes: propose file/function signatures and a plan
  before editing, and wait for approval.
- Make small, reviewable commits with conventional-commit messages.
- Read the relevant existing module before adding a sibling — match its style.
  