# CLAUDE.md

Project memory for Claude Code. Read this before making changes.

## What this is

`deltadewa` is an options hedging dashboard for a single-name **SPX** tail-hedge
program. Pricing is done with **QuantLib**; the UI is a **Dash app**
(`deltadewa/app/`) with two pages — `/monitor` (read-mostly book review, for
routine checks and IC/board reporting) and `/design` (the workbench: position
editor, roll planning, stress testing) — plus an emailed weekly digest
(`deltadewa/reporting/weekly_report.py`). Pages are a thin orchestration
layer — all real logic lives in the package.

**There are no notebooks, and no Jupyter layer.** Stage 4.3 retired
`monitor_dashboard.ipynb` and `hedge_design.ipynb` once `/monitor` and
`/design` covered them; see `docs/part-x-coverage.md`, "Stage 4.3", for the
parity record and what was deliberately dropped. #279 then deleted the layer
they drove — `deltadewa/widgets/`, `deltadewa/dashboard/`, `deltadewa/config.py`
and the whole ipywidgets/Jupyter dependency stack. Do not re-add any of it; see
`docs/part-x-coverage.md`, "The Jupyter layer itself — retired (#279)".

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
  complexity limits; `tests/` is intentionally out of scope for now
- Format: `poetry run ruff format .` — **line length is 80**
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

The package is layered. Put logic in the lower layers; keep the UI dumb.

- `portfolio/` — domain model and pricing. `position.py` (`OptionPosition`),
  `core.py` (`OptionPortfolio`), Monte Carlo, risk, factory.
- `valuation.py` — `OptionValuation`, the QuantLib pricing engine. Supports
  **both** `ExerciseStyle.AMERICAN` (Bjerksund–Stensland / finite-difference) and
  `ExerciseStyle.EUROPEAN` (analytic Black–Scholes). Enum is in `constants.py`.
- `analysis/` — metrics and decision logic: `health.py`, `hedge_triggers.py`,
  `carry.py`, `volatility.py`. **New metric/decision code goes here, UI-free.**
- `app/` — the Dash app (Phase 2 rebuild). `factory.py` builds the two-page
  (`/monitor`, `/design`) app over the shared `state.ProgramState`; `chrome.py`
  is the provenance banner shared by both pages; `pages/` holds page layouts.
- `state.py` — `ProgramState`, the single shared server-side portfolio + IPS
  state backing the Dash app (dirty-flag autosave to `exports/`, confirm-gated
  destructive ops/import). Not per-session — one hedge program, one instance.
- `visualization/` — chart builders.
- `persistence.py` — portfolio load/save (YAML/JSON). Round-trip new fields here.
- `reporting/` — console/text output.

Rule of thumb: if it has a number in it, it belongs in `analysis/` or `portfolio/`
with a test — not in a page callback.

## Domain rules that matter

- **SPX options are European-exercise and cash-settled** — price them with
  `ExerciseStyle.EUROPEAN` (analytic engine), not the American approximation.
  American is correct only for SPY/single stocks. Do not change `OptionValuation`'s
  own default; select the style upstream (config / portfolio).
- Program thresholds (carry budget, convexity targets, drawdown tolerance, roll and
  monetization triggers) are policy — they belong in `ips.yaml`, not hardcoded.
- **The program's day comes from `deltadewa/clock.py`, never from `datetime.now()`.**
  `program_trading_date()` is midnight in `ips.yaml`'s `program.timezone`
  (default `America/New_York`) and seeds every default valuation date;
  `days_between()` is the only day count, because QuantLib prices on calendar
  dates and subtracting timestamps floors the result a day low. Both were #182:
  a UTC clock repriced the book a day forward at 20:00 ET, and the floored count
  crossed the expiry triggers a day early. New code that needs "today" or "days
  to expiry" calls these, not the stdlib.
- `ips.yaml` is the only config the app loads. The `dashboard_config_*.yaml`
  gauge-presentation surface was retired in #279 — its policy had already
  migrated into the IPS and its last loader went with the Jupyter layer.
  Do not reintroduce a second config file without a reader.

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
  `tests/test_app/`, `tests/test_visualization/`). For the current size run
  `poetry run pytest --co -q | tail -1` — don't write the number down here. A
  literal has rotted twice already (M0.1 corrected it once, to a figure that was
  wrong again within the phase) and nothing in the gate can catch it.
- Add or extend tests for every behaviour change. Pricing/metric logic must have
  unit tests with crafted inputs; Dash pages get lighter smoke tests.
- Prefer deterministic tests — no live network calls (mock HTTP; use static/offline
  providers for any market-data code).

## Notebooks

There are none, and none should be added. Stage 4.3 deleted both notebooks and
the whole `nbstripout` / `nbqa` / `jupytext` toolchain with them — there is no
output filter, no notebook lint step, and no `.gitattributes`. #279 then removed
the runtime side: no `ipywidgets`, `ipyfilechooser`, `jupyter`, `jupyterlab`,
`notebook`, `jupyter-server` or `nbconvert` in any dependency group, and
**IPython is not installed at all**. Two product modules degrade gracefully
without it and are tested for it (`formatters/dataframes.py`'s
`IPYTHON_AVAILABLE` fallback and `ConsoleReporter.clear_and_print`'s labelled
`ImportError`) — keep that property. New UI goes on a Dash page under
`deltadewa/app/pages/`.

## Work in progress

The foundation is done and the handbook's Part X panels are built: a
`marketdata/` provider interface (free CBOE/FRED backend), an `ips.yaml` program
config, and a Roll Status panel. The **sizing workbench, strike-ladder builder,
and monetization planner are also done, tested, and wired** — each is its own
`analysis/`-layer module (`sizing.py`, `strike_ladder.py`, `monetization.py`)
driving a panel in the Dash `/design` page's PLANNING zone since M2.5.
`roll_planner.py` was the exception until #258 wired it: `/design` now has a
**Roll plan** panel (the `ROLL_NOW`/`DELAY`/`HOLD` action, target strike and
roll-up cost, from `roll_planner.build_roll_plan`) *and* a **Roll status by
tranche** panel (the per-trigger table, from `roll_status.evaluate_roll_status`)
— the old "Roll planner" title named the table, which is what made the coverage
row a false PRESENT. Keep the two titles distinct. #258 also corrected
`gamma_theta_delay`, which was missing the handbook's "put has moved nearer the
money" condition and so would defer a roll on a *rally* trigger; see
`docs/part-x-coverage.md`, "The roll plan is restored (#258)".
See `docs/part-x-coverage.md` for the full
handbook-item → implementation map and the
[deltadewa-handbook](https://github.com/qwertytam/deltadewa-handbook) repo,
published at <https://qwertytam.github.io/deltadewa-handbook/> (#246), for the
cited sections — the handbook was extracted
out of this repo's `docs/` into its own public repo so it can be read and
cited without pulling in the hedge-program internals; see `docs/part-x-coverage.md`'s
intro for how citations into it are anchored.

The engine-correctness fixes and the Dash migration of both notebooks are done:
`/monitor` (M2.4, the crash-led read-mostly review) and `/design` (M2.5, the
editor/planning/exploration workbench) are both live on the deployed app.
**M2.6 — the headless report, cron, and backup heartbeat — has shipped**,
closing Phase 2: the weekly digest (`reporting/weekly_report.py`,
provider-agnostic SMTP delivery), the market-data refresh job, the offsite
`exports/` backup, and a
two-check dead-man's-switch are all built, tested, and documented (RUNBOOK
§9–13). The notebook-execution and `nbqa` CI steps were retired here — the app
and report test suites cover both surfaces the notebooks used to (see the
M2.6 close-out in `docs/implementation-plan.md` for the coverage mapping).
**Stage 4.3 then deleted the notebooks themselves**, along with `example.py`,
`setup_nbstripout.sh` and the `nbstripout`/`nbqa`/`jupytext` toolchain; the
parity record and the six items it disposed of are in
`docs/part-x-coverage.md`, "Stage 4.3". Jupyter/notebook and Playwright moved out of the main
Poetry dependency group into `dev`/`test`, shrinking the production image
from 1.32 GB to 758 MB (**#279 has since deleted the Jupyter half of that
`dev` group outright** — see below). The droplet deploy of this milestone is pending on
this PR merging and a release tag being cut — see `docs/implementation-plan.md`'s
M2.6 section for what's left to verify live. **Phase 3 (docs/handbook) and
Phase 4 (exposure, ops correctness, the notebook retirement) have both since
shipped** — see those sections of `docs/implementation-plan.md`, which stays
the source of truth for what to build next.

**M2.7 has shipped**, closing the five Part X coverage regressions the
2026-08-06 re-audit found. All of them were surfacing gaps, not engine gaps:
**#4 Vega Sufficiency** and **#10**'s net-delta scalar are on `/design`;
**#6**/**#7**/**#8** are a new `/design` market-environment panel that also
carries the decision matrix (previously digest-only); **#5**/**#15** — the
convexity÷carry ratio, which existed nowhere in the codebase — is a new
`analysis/hedge_efficiency.py` surfaced in `/monitor`'s cost panel. M2.7 also
gave `analysis/hedge_triggers.py` its first product consumer, by extracting a
pure `evaluate_hedge_trigger_set` from the console-printing
`evaluate_hedge_triggers` (whose signature and output are unchanged) and
adding a `/design` panel for it.

Two new IPS sections came out of that: `convexity.efficiency_min_ratio` /
`_max_ratio` (the handbook's 3/6 hedge-efficiency band) and a `vega:` section
for the sufficiency band. Both are policy, not presentation — see
`docs/part-x-coverage.md`'s "Where the vega band went" for why the band moved
out of `dashboard.yaml`.

**M2.8 has shipped**, closing the two Part X items M2.7 left as surfacing
gaps rather than data gaps, plus a policy leak M2.7 exposed by putting the
entry-timing tree on a page for the first time. **§13 Delta Drift** is
`analysis/scenarios.ScenariosMixin.calculate_delta_drift` — the handbook's
`Δ(−5%) − Δ(0)`, hedge-only and signed — on `/design`'s PLANNING panel
beside the hedge rebalance triggers. **§14 Vega Term Exposure** is
`analysis/maturity.MaturityMixin.calculate_vega_by_maturity`, reusing the
same maturity-bucketing helper `carry.py` already applies to theta, on
`/design`'s EXPLORATION panel. The policy leak: `entry_timing_tree`'s VIX
thresholds were Python defaults, invisible to `ips.yaml`; they moved to
`IpsMarketEnvironment`'s `market_environment:` section as required
keyword-only params with no default, so the function can no longer be
called without them.

**#279 has shipped**, retiring the leftover Jupyter layer: `dashboard/` (12
modules), `widgets/` (11), `config.py`, their 253 tests, the symbols they were
the last caller of (`formatters/gradients.py` and `formatters/html.py` whole,
plus five individual functions), the `dashboard_config_*.yaml` presentation
surface, and the entire ipywidgets/Jupyter dependency stack (`poetry.lock`
166 → 80 packages). Orphaning was verified **import-path-qualified**, because
three retired modules shared a bare name with a live `analysis/` module —
`roll_status.py`, `position_aging.py`, `stress.py`. Symbols that lost their
last caller but were kept are annotated at the function; four sweep candidates
were false positives and are recorded as such. See
`docs/part-x-coverage.md`, "The Jupyter layer itself — retired (#279)".

Two follow-ups came out of it, neither acted on:

- **`triggers.rally_rebalance_pct` is validated but read by nothing** —
  required with no default, in both example YAMLs, handbook-backed ("Rule 2 —
  Market Rally Rebalance Trigger"), and skipped by
  `HedgeTriggerThresholds.from_ips`. Pre-existing, and the only IPS key with no
  reader. The key stays (thresholds are policy); the trigger needs building.
- **A second orphan set: the matplotlib half of `visualization/`.** `base.py`
  (`OptionCharts`) and its five mixins (`crash_charts`, `greeks_charts`,
  `pnl_charts`, `scenarios`, `theta_charts`), plus `convenience.py` and
  `_protocols.py` — 8 modules, ~2,760 lines, 51 tests, **no importer outside
  `visualization/` and its own tests**. The live chart modules are the three
  `*_plotly` ones. Retiring this set is what would let `matplotlib` and
  `pillow` go; it was deliberately kept out of #279 to keep that PR
  reviewable.

Still open: **#12 Liquidity Risk** is genuinely data-blocked (needs per-strike
bid/ask and open interest, which the free CBOE/FRED provider doesn't return).
**#9**'s skew-beta scalar has never existed — an unbuilt feature, not a
regression.

**Read `docs/part-x-coverage.md` before adding or moving a dashboard panel**
— it is the current handbook-item → surface map (mapping into the public
[deltadewa-handbook](https://github.com/qwertytam/deltadewa-handbook) repo,
by anchor rather than line number), and its "Conscious retirements" section
records what must *not* be re-added.

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
- **gate-runner** — the code gate: ruff, format, mypy, pytest, pylint. Use after an
  implementation step.
- **dash-smoke-runner** — the app/integration gate: brings the Dash app up headless
  and runs the app-level smoke / Playwright suite. Use after a UI step. Distinct from
  gate-runner — a green code gate does not imply the live app renders.
- **doc-sync-checker** — audits CLAUDE.md / README / `docs/implementation-plan.md`
  against the repo and flags drift (test counts, version, milestone status, dead
  references). Run before a milestone and after a merge.
- **secret-scanner** — scans the working tree for operational values that must not
  land in this public repo (see SECURITY.md's standing rule). Run before any commit
  that touches config, ops scripts, or RUNBOOK/docs.

`.claude/` is gitignored, so the agent *files* aren't versioned — **this section is
the versioned record of the convention.** Keep it current if the agents change.
  