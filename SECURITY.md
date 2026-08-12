# Security Policy

## Reporting a vulnerability

Please report security issues privately rather than opening a public
GitHub issue — use
[GitHub's private vulnerability reporting](https://github.com/qwertytam/deltadewa/security/advisories/new)
for this repository. Include what you found, how you found it, and its
potential impact; a working reproduction is helpful but not required.

There is no fixed response-time commitment — this is a single-maintainer
project — but reports will be acknowledged and triaged.

## The standing rule

This repository is **public**. Three exposure incidents established the
rule that now governs everything that goes into it:

> **No real operational values in the repo.** Config is templated via
> `*.example.yaml` (or `.env.example`); the live files they template are
> gitignored and live only on the deploy host. Secrets, credentials, and
> deployment specifics (backup remotes, SMTP provider/allowlist, droplet
> sizing) never appear in tracked files, commit messages, or docs — only
> in host-side env vars / `/etc/deltadewa/backup.env`, or referenced as
> "see private ops doc."

`secret-scanner` runs before any commit that touches config, ops scripts,
or RUNBOOK/docs for exactly this reason — treat a bypass or gap in that
coverage as itself worth reporting.

### The three incidents behind the rule

- **[#245](https://github.com/qwertytam/deltadewa/issues/245)** —
  `config/ips.yaml` and `config/dashboard.yaml` were tracked with this
  program's real policy values (carry budget, convexity targets, program
  name), not template data. Fixed going forward: both were gitignored,
  with `config/ips.example.yaml` / `config/dashboard.example.yaml` as the
  tracked templates (#248) — this is the origin of the `*.example.yaml`
  convention stated above. (#279 later retired the `dashboard.yaml` surface
  entirely; only the IPS pair remains.) **Still open**: the fix is forward-only: every
  past revision of those real values remains visible in this public
  repo's git history. Closing this needs an actual decision — private
  repo, history rewrite, or a written accepted-risk sign-off — not just
  the current-state fix. See the issue for the live status; this file
  intentionally doesn't restate it, to avoid drifting out of sync with
  the real decision.
- **[#249](https://github.com/qwertytam/deltadewa/issues/249)** (closed)
  — `examples/ips/ips_default.yaml`, documented as a starter preset, was
  actually a near-exact mirror of the same real policy #245 was about,
  kept in sync with it since the first IPS commit. #245's own audit
  missed it because it only covered `config/`. Fixed: sanitized to
  genuinely illustrative `EXAMPLE VALUE` placeholders, with
  `tests/test_example_configs.py` guarding against a re-sync (#257).
- **[#243](https://github.com/qwertytam/deltadewa/issues/243)** (closed)
  — a narrower case of the same class: `ops/backup-exports.sh` hardcoded
  a real backup-repo name as its own fallback default. Fixed: the backup
  remote is now a required env var with no default (fails loudly if
  unset), reconciled against the actual remote on every run rather than
  only at first init (#250). The same PR scrubbed `docs/RUNBOOK.md` of
  the backup host/alias and SMTP provider specifics it had named
  directly, replacing them with "see private ops doc" pointers.

## Scope and what "secure" means here

`deltadewa` is a single-name SPX tail-hedge dashboard, not a
multi-tenant or internet-facing service by default. Beyond the standing
rule above, the main categories worth reporting:

- A way for `config/ips.yaml` (gitignored, never shipped — see
  `docs/yaml-config-guide.md`) to leak into a tracked file, a log line, or
  an exported artifact that isn't meant to carry it.
- A way for the deployed Dash app to expose portfolio data, IPS policy, or
  market-data credentials to an unauthenticated or unintended caller.
- A credential or secret committed to the repository or its history.
