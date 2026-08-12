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
conventional-commit message (`fix:`, `feat:`, `docs:`, `chore:`, …).

The gate a change must pass, all via `poetry run`:

```bash
pytest                    # must be green
mypy deltadewa             # strict mode
ruff check .                # lint
ruff format .                # line length 80
pylint deltadewa            # must exit 0
```

If your change touches config, ops scripts, or anything that could sit
next to real operational values, scan the diff for secrets before
committing.

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

## Reporting a bug or requesting a feature

Open a GitHub issue. Include how you verified the problem (a
reproduction, a traced call path, a failing test) — issues in this repo
are expected to show their work, not just assert a symptom.
