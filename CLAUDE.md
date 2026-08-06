# CLAUDE.md

Project memory for Claude Code. Read this before making changes.

## What this is

`deltadewa` is an options hedging dashboard for a single-name **SPX** tail-hedge
program. Pricing is done with **QuantLib**; the UI is two Jupyter notebooks —
`monitor_dashboard.ipynb` (read-mostly book review, for routine checks and
IC/board reporting) and `hedge_design.ipynb` (the workbench: position editor,
roll planning, stress testing) — built from `ipywidgets`, `matplotlib`, and
`plotly`. Both call `start_session(role=..., globals_dict=globals())` from
`deltadewa.dashboard`. Notebooks are a thin orchestration layer — all real
logic lives in the package.

## Environment & commands

Python `>=3.11,<4.0`, managed with **Poetry**. Run everything through `poetry run`.

- Install: `poetry install`
- Pre-commit hooks: `poetry run pre-commit install` (once per clone; installs the `.pre-commit-config.yaml` hooks)
- Tests: `poetry run pytest`
- Type-check: `poetry run mypy deltadewa` — **strict mode** (`strict = true` in `[tool.mypy]` in
  `pyproject.toml`); custom stubs live in `typings/`; `pandas-stubs` installed; tests/ and
  typings/ are excluded from strict checking via per-module overrides.
- Lint: `poetry run ruff check .`
- Design/refactor smells: `poetry run pylint deltadewa` — covers duplicate-code, cyclic-import, and
  complexity limits; `tests/` and notebooks are intentionally out of scope for now
- Format: `poetry run ruff format .` — **line length is 80**
- Lint/type-check notebooks: `poetry run nbqa ruff <notebook>` / `poetry run nbqa mypy <notebook>`
- Clock-shift determinism probe: `make test-clockshift` — runs the suite under a +0/+90/+1000/+3000
  day clock to catch tests that assert wall-clock-dependent values. **Not part of the gate**: it
  swaps `datetime.datetime` for a subclass that C extensions hold pointers to, so a dependency bump
  can segfault it — that must never block a merge. Cost is not the reason (the suite is ~8s, so the
  matrix is ~30s). CI runs it twice: the full matrix nightly against `main`
  (`.github/workflows/clockshift.yml`, the authoritative run) and an advisory `+0/+1000` job on
  every PR (`clockshift-advisory` in `ci.yml`, `continue-on-error`).

Before considering any change done: `poetry run pytest` and `poetry run mypy deltadewa` must both be
green, `poetry run ruff check .` must be clean, and `poetry run pylint deltadewa` must exit 0.

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
- `app/` — the Dash app (Phase 2 rebuild). `factory.py` builds the two-page
  (`/monitor`, `/design`) app over the shared `state.ProgramState`; `chrome.py`
  is the provenance banner shared by both pages; `pages/` holds page layouts.
  Distinct from `dashboard/`/`widgets/`, which stay Jupyter-only.
- `state.py` — `ProgramState`, the single shared server-side portfolio + IPS
  state backing the Dash app (dirty-flag autosave to `exports/`, confirm-gated
  destructive ops/import). Not per-session — one hedge program, one instance.
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
  `tests/test_dashboard/`, `tests/test_visualization/`). For the current size run
  `poetry run pytest --co -q | tail -1` — don't write the number down here. A
  literal has rotted twice already (M0.1 corrected it once, to a figure that was
  wrong again within the phase) and nothing in the gate can catch it.
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

The foundation is done and the handbook's Part X panels are built: a
`marketdata/` provider interface (free CBOE/FRED backend), an `ips.yaml` program
config, a Roll Status panel, and the notebook split into `monitor_dashboard.ipynb`
and `hedge_design.ipynb`. The **sizing workbench, strike-ladder builder, and
monetization planner are also done, tested, and wired** — each is its own
`analysis/`-layer module (`sizing.py`, `strike_ladder.py`, `monetization.py`, with
`roll_planner.py`) driving a panel in `hedge_design.ipynb` and, since M2.5, the
Dash `/design` page's PLANNING zone. See `docs/part-x-coverage.md` for the full
handbook-item → implementation map and `docs/hedging handbook.md` for the cited
sections.

The engine-correctness fixes and the Dash migration of both notebooks are done:
`/monitor` (M2.4, the crash-led read-mostly review) and `/design` (M2.5, the
editor/planning/exploration workbench) are both live on the deployed app.
**M2.6 — the headless report, cron, and backup heartbeat — has shipped**,
closing Phase 2: the weekly digest (`reporting/weekly_report.py`, SendGrid
delivery), the market-data refresh job, the offsite `exports/` backup, and a
two-check dead-man's-switch are all built, tested, and documented (RUNBOOK
§9–13). The notebook-execution and `nbqa` CI steps are retired — the app and
report test suites now cover both surfaces the notebooks used to (see the
M2.6 close-out in `docs/implementation-plan.md` for the coverage mapping);
the notebook files themselves are unchanged and still work locally, just no
longer CI-gated. Jupyter/notebook and Playwright moved out of the main
Poetry dependency group into `dev`/`test`, shrinking the production image
from 1.32 GB to 758 MB. The droplet deploy of this milestone is pending on
this PR merging and a release tag being cut — see `docs/implementation-plan.md`'s
M2.6 section for what's left to verify live. Phase 3 (docs/handbook) is next;
**treat `docs/implementation-plan.md` as the source of truth for what to
build there.**

The only features still genuinely outstanding are the data-blocked Tier-4 metrics —
**#12 Liquidity Risk**, **#13 Delta Drift**, and **#14 Vega Term Exposure** — each
of which needs a live options-chain or position-history feed that isn't available
yet (see "Outstanding Tier-4 items" in `docs/part-x-coverage.md`).

## Workflow expectations

- Use plan mode for non-trivial changes: propose file/function signatures and a plan
  before editing, and wait for approval.
- Make small, reviewable commits with conventional-commit messages.
- Read the relevant existing module before adding a sibling — match its style.
- Always create/checkout a feature branch before making changes; never commit directly to `main`

## Model & sub-agent usage

Match the model to the *step*, not the milestone — every task mixes cheap and
expensive work, so routing the whole task to one tier wastes the most on the parts
that need it least.

- **Haiku** — read-only and mechanical steps: the orient/inventory opener ("read X,
  report, wait"), verification, doc sweeps. Delegate these to the sub-agents below so
  raw file contents and command output stay out of the main thread's context.
- **Opus** — the judgment: plan-mode design decisions, API and UX shape, the session
  model. In Phase 2 the reasoning concentrates in **M2.1's compute-API design** and
  **M2.4 (the monitor)** — spend Opus there. **M2.3 (deploy)** and the cron/backup
  parts of **M2.6** are cheap; don't run Opus on them.
- **Sonnet** — well-specified implementation once the design is approved.

Sub-agents live in `.claude/agents/` — all Haiku, all read-only (they report, they
don't fix):

- **fast-processor** — quick lookups, symbol searches, module summaries. Use for the
  "orient" step so file contents don't fill the main context.
- **gate-runner** — the code gate: ruff, format, mypy, pytest, nbqa. Use after an
  implementation step.
- **dash-smoke-runner** — the app/integration gate: brings the Dash app up headless
  and runs the app-level smoke / Playwright suite. Use after a UI step. Distinct from
  gate-runner — a green code gate does not imply the live app renders.
- **doc-sync-checker** — audits CLAUDE.md / README / `docs/implementation-plan.md`
  against the repo and flags drift (test counts, version, milestone status, dead
  references). Run before a milestone and after a merge.

`.claude/` is gitignored, so the agent *files* aren't versioned — **this section is
the versioned record of the convention.** Keep it current if the agents change.
  