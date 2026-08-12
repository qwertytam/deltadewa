# Contributing

Contributions are welcome. This is a short, practical guide to the
project's actual workflow — the full picture lives in `CLAUDE.md`, which
this file summarizes rather than duplicates; read that first for anything
not covered here.

## Setup

```bash
poetry install
poetry run pre-commit install   # once per clone
```

Python `>=3.11,<4.0`, managed with Poetry. Run everything through
`poetry run`.

## Before opening a PR

Always work on a feature branch — never commit directly to `main`. Use a
conventional-commit message (`fix:`, `feat:`, `docs:`, `chore:`, …), and
prefer several small, reviewable commits over one large one.

The gate a change must pass, all via `poetry run`:

```bash
pytest                # every test green
mypy deltadewa          # strict mode — pyproject.toml's [tool.mypy]
ruff check .              # lint
ruff format .              # line length 80
pylint deltadewa          # must score 10.00/10, not just "no errors"
```

`pylint`'s bar is the full score, not just a non-error exit — a 9.8x with
warnings still fails the gate. If your change touches config, ops
scripts, or anything that could sit next to real operational values, scan
the diff for secrets before committing — see `SECURITY.md`'s standing
rule: no real operational values in this repo, ever, in any tracked file.

## Where things go

The package is layered — keep the UI thin and put logic in the lower
layers (`portfolio/`, `analysis/`, `valuation.py`). See CLAUDE.md's
"Architecture" section for the full map, and read a sibling module before
adding one so new code matches its style.

Add or extend tests for every behaviour change. Pricing/metric logic needs
unit tests with crafted inputs; UI gets lighter smoke tests. There are no
notebooks in this repo, and none should be added — see CLAUDE.md's
"Notebooks" section for why.

## Domain rules

Two are easy to get wrong by habit:

- SPX options are European-exercise and cash-settled — price them with
  `ExerciseStyle.EUROPEAN`, not the American approximation.
- The program's "today" and day counts come from `deltadewa/clock.py`
  (`program_trading_date()`, `days_between()`), never from
  `datetime.now()` or subtracting timestamps directly.

## Sub-agent workflow (optional, but reproducible if you use it)

This project's own development uses a small set of read-only Haiku
sub-agents (`.claude/agents/`, gitignored — the roster below is the
versioned record) to keep verification cheap and out of the main
conversation's context. Not required to contribute, but if you're using
Claude Code against this repo, using the same roster keeps results
reproducible and comparable to what past PRs report:

| Sub-agent | When | What it does |
|---|---|---|
| `fast-processor` | Orienting on unfamiliar code | Quick lookups, symbol searches, module summaries — read-only |
| `gate-runner` | After an implementation step | Runs the full code gate (ruff, format, mypy, pytest, pylint) and reports pass/fail |
| `dash-smoke-runner` | After a UI (`/monitor`, `/design`) change | Brings the Dash app up headless, runs the app-level smoke/Playwright suite — a green `gate-runner` doesn't mean the app renders |
| `doc-sync-checker` | Before a milestone, after a merge | Audits `CLAUDE.md`/README/`docs/implementation-plan.md` against the repo for drift (test counts, version, milestone status, dead references) |
| `secret-scanner` | Before any commit touching config, ops scripts, or RUNBOOK/docs | Scans the working tree for operational values that must not land in this public repo |

The pattern that has worked in practice: `fast-processor` to orient →
implement → `gate-runner` to verify → `secret-scanner` if the diff
touches config/ops/docs → commit. Match the model to the step, not the
whole task — see CLAUDE.md's "Model & sub-agent usage" for the reasoning
behind the split (routing well-specified implementation to a cheaper tier
than design decisions).

## Reporting a bug or requesting a feature

Open a GitHub issue. Include how you verified the problem (a
reproduction, a traced call path, a failing test) — issues in this repo
are expected to show their work, not just assert a symptom. For security
issues specifically, see `SECURITY.md` — don't open a public issue.
