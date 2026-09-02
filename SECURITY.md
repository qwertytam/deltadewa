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
  `config/ips.yaml` was tracked with this program's real policy values
  (carry budget, convexity targets, program name), not template data.
  `config/dashboard.yaml` was named in this incident too, but that was an
  overcorrection: its real-to-template diff was comment-only — a single
  comment line quoting the real book's vega reading — so it never carried
  a bespoke policy value, and is dropped from that description here. Fixed
  going forward: `config/ips.yaml` was gitignored, with
  `config/ips.example.yaml` as the tracked template (#248) — this is the
  origin of the `*.example.yaml` convention stated above;
  `config/dashboard.yaml` was templated alongside it at the same time out
  of the same caution. (#279 later retired the `dashboard.yaml` surface
  entirely, so only the IPS pair remains today — a separate point from the
  correction above: that removal was about the surface ceasing to exist,
  not about what its history held.) **Resolved 2026-08-20 as accepted
  risk, not remediated**: the fix was forward-only, so every past revision
  of `config/ips.yaml`'s real values remains visible in this public repo's
  git history. No history rewrite will be performed. The reasoning, the
  full-history audit that underwrites it, and the condition that would
  reopen it are recorded below under "[Accepted risk: the #245
  history](#accepted-risk-the-245-history)"; tracked at
  [#351](https://github.com/qwertytam/deltadewa/issues/351).
- **[#249](https://github.com/qwertytam/deltadewa/issues/249)** (closed)
  — `examples/ips/ips_default.yaml`, documented as a starter preset, was
  actually a near-exact mirror of the same real policy #245 was about,
  kept in sync with it since the first IPS commit. #245's own audit
  missed it because it only covered `config/`. Fixed: sanitized to
  genuinely illustrative `EXAMPLE VALUE` placeholders, with
  `tests/test_example_configs.py` pinning that the example and preset
  carry one set of numbers and that the program name reads as an
  example (#257). The per-value pin against the specific pre-#245
  numbers was removed in docs/canon-tail (#344): `config/ips.yaml` has
  in practice always been an operator's copy of the example template
  with only `program.name` edited, so that guard's premise — the
  example must differ from a value the real file carries — could never
  hold. Those pre-sanitisation values are already recorded above as
  permanently public in this repo's git history (#351); the per-value
  pin was not protecting anything the two guards that remain don't
  already cover.
- **[#243](https://github.com/qwertytam/deltadewa/issues/243)** (closed)
  — a narrower case of the same class: `ops/backup-exports.sh` hardcoded
  a real backup-repo name as its own fallback default. Fixed: the backup
  remote is now a required env var with no default (fails loudly if
  unset), reconciled against the actual remote on every run rather than
  only at first init (#250). The same PR scrubbed `docs/RUNBOOK.md` of
  the backup host/alias and SMTP provider specifics it had named
  directly, replacing them with "see private ops doc" pointers.

### Accepted risk: the #245 history

**Decision (2026-08-20): the pre-remediation git history of #245 stays as
it is. No rewrite, no repo transfer, no request to GitHub Support.**
Tracked at [#351](https://github.com/qwertytam/deltadewa/issues/351).

**What was accepted.** Revisions of `config/ips.yaml` and
`examples/ips/ips_default.yaml` predating the 2026-08-10 sanitisation
remain readable in history, along with the vendor and ops detail scrubbed
from `docs/RUNBOOK.md` and `ops/backup-exports.sh` in #243/#250, and the
maintainer's personal email on commit author lines. In substance this
exposes **this program's risk tolerance and its operating cadence** — the
thresholds it runs to and the rhythm it runs on.

**What was not exposed.** A full-history audit (2026-08-20, scoped by
class of value across every tracked path and every revision, not by a
file list) found **no portfolio size, no position size, no positions, no
broker, custodian, counterparty or legal entity** anywhere in the
history. It separately cleared the ten `.claude/agents/` files that #349
made tracked and public. The distinction matters: a threshold reveals how
the program thinks, and can be re-set. A position or a counterparty
reveals who and how much, and cannot.

**Why nothing needs rotating.** The same audit found no credential of any
kind: no private keys, no AWS or GitHub tokens, no `password=<value>`.
Every email address in tracked content is `@example.com`, every IP is
`127.0.0.1`, `0.0.0.0` or `192.0.2.1`, every heartbeat URL is a
placeholder. `.env` and `exports/` were never tracked. There is no secret
in this history to invalidate, so there is no rotation step being skipped
here.

**Why GitHub Support was not asked.** Their published policy is that
Support "won't remove non-sensitive data, and will only assist in the
removal of sensitive data in cases where we determine that the risk can't
be mitigated by rotating affected credentials." With no credentials
involved, there is nothing here they would act on.

**Why a rewrite was rejected — the honest version.** A force-push would
in fact work at GitHub's edge: this repo has no fork network (0 forks, 0
stars, 0 watchers), so the old commits would genuinely be orphaned there
rather than surviving in a fork. What defeats it is the copies already
off-platform. In the 14 days to 2026-08-20 the repo saw **772 clones from
234 unique cloners against 7 page views from 3 visitors** — a ratio that
says automated collection by parties who were not invited, not human
readers. The caveat, stated plainly because it cuts against the
conclusion: `actions/checkout` defaults to `depth: 1`, so an unknown and
possibly large fraction of those clones took no history at all. What
remains certain even after that discount is that this repository is
cloned at scale by unknown parties, and a rewrite reaches none of those
copies. It would buy the appearance of remediation, not remediation.

**When to revisit.** This sign-off covers the class of value described
above, and only that class. **If any value touching position size or
counterparty is ever found in the history, this decision is void and must
be retaken from scratch** — no sign-off can mitigate that class, because
the harm does not depend on the value still being current. Re-run the
full-history audit by class (not by file list) after any change to what
the tracked configs carry; an audit scoped to named files cannot tell you
what it missed.

### Why the offsite backup carries policy but not secrets

**[#301](https://github.com/qwertytam/deltadewa/issues/301)** — the
nightly offsite backup (`ops/backup-exports.sh`, `docs/RUNBOOK.md` §7–§8)
now stages a copy of `config/ips.yaml` into the pushed `exports/`
tree, alongside the portfolio state that was already going there.
`.env` — the SMTP credentials, the heartbeat URLs, the bind address —
does not, and never will by the same mechanism; it is recreated from a
plain copy in the private ops doc instead (§10, §14). **This is a
scoped exception to the standing rule above, not a relaxation of it —
read the boundary before extending either direction.**

**Why pushing policy is safe here even though it wouldn't be safe in
this public repo.** The standing rule's scope is *this repository*,
where every tracked byte is permanently world-readable the moment it's
pushed — the #245 history above is the proof: 772 clones from 234
unknown parties in 14 days, and no rewrite reaches any of them. The
offsite backup remote is a different environment: a private repo, one
write-scoped SSH deploy key, no fork network, not indexed, not cloned
by anyone but this program's own root cron. Nothing about this
subsection licenses treating `config/ips.yaml` as safe to commit to
*this* repo — it stays gitignored, `config/ips.example.yaml` stays the
tracked template, unchanged by any of the above.

The decisive point, though, isn't that the backup remote is private —
it's that **its sensitivity ceiling was already set by
`program_state.json`**, which has been going into that same push since
before #301 and carries the actual positions and sizes: exactly the
class this document's own "What was not exposed" note above says
*cannot* be re-set once revealed. `config/ips.yaml` carries thresholds
— carry budget, convexity bands, roll triggers — the class that
*can*. Adding policy to a channel that already carries positions
introduces no new class of exposure, only a new instance of a class
already accepted for the same remote.

**Why `.env` is different, not just "more sensitive."** The offsite
backup is **unencrypted** — `age` encryption is a deliberate,
not-yet-built follow-up (`ops/backup-exports.sh`'s own header: a
backup you cannot decrypt is worse than one you can, and adding it
needs an explicit key-escrow step, not a silent one). Every byte
pushed there is plaintext at the remote and in every clone of it. A
policy value in a compromised backup is a **confidentiality** loss —
embarrassing, reveals risk tolerance, not actionable by an attacker on
its own. A credential in one is an **access** loss — usable
immediately, and it compounds: an SMTP credential lets someone send
mail as this program; a leaked heartbeat URL lets someone fake a
healthy dead-man's-switch. That asymmetry, not the relative
sensitivity of the numbers, is why the line falls where it does.

**Void if the backup remote's own privacy assumption changes** — if it
is ever made public, shared more broadly than this program's own
operator, or `age` encryption lands (which would change what *could*
safely be added, not what already has been): re-derive this decision
from scratch rather than assuming today's boundary still holds. Landing
`age` is its own explicit decision, including the key-escrow question —
it does not retroactively bless adding `.env` here without that
decision being made on its own terms.

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
