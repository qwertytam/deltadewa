# Releasing

How a version is cut, and how `CHANGELOG.md` stays current between cuts.
Written for #451 after the CHANGELOG's versioned headings stopped at 0.7.0
while tags ran to `v0.9.1`, and `0.9.2` was deployed from `main` untagged.

## The rule in one line

**`CHANGELOG.md`'s newest versioned heading is always `pyproject.toml`'s
`version`, and that version is tagged before anything is deployed.**
`tests/test_changelog.py` enforces the first half; the steps below, and
RUNBOOK §4, cover the second.

## Between releases: every PR

A PR with a user-visible or operator-visible effect adds an entry under
`## [Unreleased]` in `CHANGELOG.md`, in the same PR, under the matching
`### Added` / `### Changed` / `### Fixed` / `### Removed` heading:

- Lead with the issue or PR number and a bold one-line summary, then say
  what an operator or reader would notice. Match the neighbouring entries.
- "User-visible" includes ops: a config key, a backup manifest field, a
  RUNBOOK step, a breaking change for a live `config/ips.yaml` (say so).
- A pure refactor, test-only or docs-only PR with no such effect needs no
  entry. Say "no changelog entry: <why>" in the PR description so a
  reviewer can tell it was a decision, not an omission.
- Do **not** bump `pyproject.toml`'s version in an ordinary PR.

`.github/pull_request_template.md` carries this as a checklist line.

## Cutting a release

Pick the number by the largest change since the last tag: patch for fixes
and docs, minor for new features or a breaking IPS change (pre-1.0), major
only for 1.0 and after. Then, in **one release PR** off `main`:

1. Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` (the date the tag
   will be cut), and add a fresh `## [Unreleased]` above it containing
   `Nothing yet.`
2. Update the links at the foot of the file: `[Unreleased]` compares
   `vX.Y.Z...HEAD`, and add `[X.Y.Z]` comparing the previous tag to
   `vX.Y.Z`.
3. Bump `version` in `pyproject.toml` to `X.Y.Z`. Run `poetry install` so
   `__version__` (read from installed metadata) matches; the weekly digest
   golden `tests/test_reporting/goldens/weekly_digest.md` quotes
   `Running vX.Y.Z` and must be updated in the same PR.
4. Run the gate (`CONTRIBUTING.md`) and merge. `tests/test_changelog.py`
   fails if steps 1 to 3 disagree.
5. Tag **from `main`, at the merge commit, once CI is green on it**, as an
   annotated tag, and push it:

   ```bash
   git checkout main && git pull --ff-only
   git tag -a vX.Y.Z -m "vX.Y.Z: <one-line summary>"
   git push origin vX.Y.Z
   ```

6. Only now deploy (RUNBOOK §4: `git checkout <tag>`). A deploy from an
   untagged `main` records a version no tag names in the backup manifest;
   since #450 the manifest also carries `git_commit`, so a restore still
   works, but the tag is what makes the version mean something.

Squash-merge note: push nothing to a PR branch after it has merged. Commits
pushed late are not in the squash and recreate the branch on the remote
(this happened to #444 and #449).

## If a version was deployed without a tag

Tag the deployed commit retroactively (`git tag -a vX.Y.Z <sha>`), taking
the sha from the backup manifest's `git_commit` or `git -C ~/deltadewa
rev-parse HEAD` on the host. Do not move an existing tag.
