## Summary

<!-- What changed and why. Link the issue: "Closes #NNN". -->

## Checklist

- [ ] Gate is green: `pytest`, `mypy deltadewa`, `ruff check .`, `ruff format .`, `pylint deltadewa`
- [ ] `CHANGELOG.md` has an entry under `## [Unreleased]`, **or** this PR says "no changelog entry: <why>" (pure refactor, tests-only, docs-only). See `docs/RELEASING.md`
- [ ] No version bump unless this is a release PR (`docs/RELEASING.md`)
- [ ] No real operational values in the diff (`SECURITY.md`)
