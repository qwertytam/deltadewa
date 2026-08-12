# Security Policy

## Reporting a vulnerability

Please report security issues privately rather than opening a public
GitHub issue — use
[GitHub's private vulnerability reporting](https://github.com/qwertytam/deltadewa/security/advisories/new)
for this repository. Include what you found, how you found it, and its
potential impact; a working reproduction is helpful but not required.

There is no fixed response-time commitment — this is a single-maintainer
project — but reports will be acknowledged and triaged.

## Scope and what "secure" means here

`deltadewa` is a single-name SPX tail-hedge dashboard, not a
multi-tenant or internet-facing service by default. The main categories
worth reporting:

- A way for `config/ips.yaml` or `config/dashboard.yaml` (this program's
  real policy/presentation values, gitignored and never shipped — see
  `docs/yaml-config-guide.md`) to leak into a tracked file, a log line, or
  an exported artifact that isn't meant to carry them.
- A way for the deployed Dash app to expose portfolio data, IPS policy, or
  market-data credentials to an unauthenticated or unintended caller.
- A credential or secret committed to the repository or its history.
  `secret-scanner` runs before commits that touch config, ops scripts, or
  RUNBOOK/docs for exactly this reason — a bypass or gap in that coverage
  is itself worth reporting.

## Known open item

The repository's git history may contain example/template values from
before the config-sanitization work landed (#245, #249, #257). That issue
is tracked publicly and is the authoritative record of what's been
verified clean versus what still needs a decision (private repo, history
rewrite, or a written accepted-risk sign-off) — see it rather than this
file for current status.
