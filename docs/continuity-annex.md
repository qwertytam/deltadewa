# Continuity annex: what this program can be trusted for

This page answers one narrow question, for whoever is reading the weekly
digest or `/monitor` after the operator who set this program up is no
longer around to explain it: **which parts of what you're looking at can
you actually rely on, and which parts still need a human?**

## What this is not

This is not the decision guide — whether to keep running the hedge, wind
it down, or let it lapse; the concrete steps to close SPX options at a
broker; which deadlines actually bind; who to call. That guide belongs
on a page a partner can read without touching a terminal, and the
handbook's [Continuity
Planning](https://qwertytam.github.io/deltadewa-handbook/part-7/continuity-planning/)
page already covers most of it — the three paths (wind down / run off /
maintain), how long inaction is safe, which deadlines bind, closing a
spread as one order, and a handover checklist by role. **What that page
does not yet cover, and this one exists to fill, is the software-trust
question** — it says what to do, not what the dashboard and the email
can tell you while you're deciding.

This is also not the filled-in instance of either document. The actual
broker, the actual accountant, actual login credentials, and the actual
positions never belong in this public repository — see `SECURITY.md`'s
standing rule and the handbook page's own "Access and people" /
"Storage" checklist items, both of which say the same thing from their
own side: that detail lives in the private ops doc, RUNBOOK.md §10, or
wherever this program's own operator has recorded it — never here,
never as a placeholder "for illustration."

## What can be trusted, once nobody is actively running this

Everything below is a property of the shipped code, not a promise about
market conditions or broker behaviour — cited to what actually
implements it, so a claim here can be checked against the source rather
than taken on faith.

- **A stale or missing hand-entered price says so.** Per-leg implied
  volatility, spot, the risk-free rate, and the dividend yield are typed
  in by a person and never refresh on their own. The provenance ledger
  grades every one of them against a review-cadence policy and shows the
  worst grade on both pages' banner (#367) — a book nobody has touched
  in months reads as stale, not as quietly current. **What this does not
  do:** catch a value that was mistyped correctly-but-wrong at entry
  time, or notice that the underlying position itself no longer matches
  what the broker actually holds.
- **A missing or broken policy file says so, by name.** `/health`
  reports whether `config/ips.yaml` loaded at all, which of its optional
  sections are silently running on code defaults, and the pricing-style
  wiring behind it (#309) — a config problem shows up as a named,
  specific fact, not a blank dashboard.
- **The dashboard and the email endpoint cannot go dark from an
  ordinary fault.** Both `/health` and the chrome banner that wraps
  every page independently catch a raise in the code that assesses
  market conditions and provenance, and degrade to a visible notice
  instead — `/health` always answers with a distinct status rather than
  a raw error, which matters because it's also what the dead-man's-switch
  heartbeat reads (#381).
- **A partial book announces itself.** If a leg's price could not be
  computed — most commonly, it has already expired — the compliance
  strip on `/monitor` and the digest's Protection section both name
  which leg was excluded from the convexity figure, rather than showing
  a smaller number with no explanation (#375).
- **A failed weekly digest is distinguishable from silence.** If
  building the digest itself raises, the run exits with a distinct code,
  writes no partial files, and — when email is configured — sends a
  best-effort plain-language failure notice in place of the digest
  (#364). Only a **confirmed, successfully sent** digest pings the
  heartbeat; a build failure, a refusal, or a delivery failure all leave
  it unpinged on purpose, so "no digest" and "the heartbeat went quiet"
  are the same signal, not two things to separately worry about.
- **The heartbeats are a real dead-man's-switch, not a formality.**
  Three independent checks (refresh, digest, backup) each alarm on their
  own overdue window — see RUNBOOK.md §13. This digest's own footer
  restates the plainest version of that contract: **no digest for two
  weeks means the system itself is down**, not that the market has been
  quiet.
- **The offsite backup is encrypted to two independent keys, one of
  them meant for exactly this scenario.** `ops/backup-exports.sh`
  `age`-encrypts every nightly push (#320); either of two recipients'
  private keys decrypts it on its own — recipient 1 is the operator's
  own, recipient 2 is a second key deliberately kept somewhere reachable
  *without* the operator (with the accountant, in a safe — wherever this
  program's own continuity plan records it; see RUNBOOK.md §10 for the
  mechanism, the private ops doc for the actual location). If you are
  reading this page because the operator is genuinely gone, that second
  key — not a login the operator alone had — is what gets you into
  `program_state.json` and the policy snapshot inside the backup.
  **What this does not do:** recover anything if *both* keys are lost —
  age has no backdoor, by design, and a backup nobody can decrypt is
  exactly the failure this feature exists to prevent, not something it
  can itself detect. Confirming the second key still works, and still
  reaches whoever it's meant to, is a periodic check for the same
  reason RUNBOOK.md §14 runs a recovery drill on the backup's *content*
  — the drill covers the encryption too, decrypting once with each key
  and confirming both give identical output.

## What this cannot do — read these limits as seriously as the list above

- **It cannot tell you the book still matches reality at the broker.**
  Everything on both pages reprices whatever is recorded in
  `program_state.json`. A leg the broker closed, exercised, or expired
  without the book being updated here will keep pricing as if it were
  still open until a person corrects it.
- **It prices on stale data rather than refusing to render.** The
  design is deliberate — "send stamped-stale, never silently skip" — but
  that means a STALE or worse marker is something a reader has to
  actually notice, not something the app will stop and insist on. A
  banner that's easy to skim past is still a banner, not a lock.
- **Nothing here reviews whether the policy itself is still right.** The
  carry budget, convexity band, and roll/rally triggers in
  `config/ips.yaml` are whatever was last set. They do not self-update
  for a changed risk tolerance, a materially different SPX level, or
  time passing — only a person re-reading the handbook against the
  current numbers would catch that they've drifted out of date.
- **It cannot place, close, or roll a trade.** Every one of the
  observations above is read-only. The decision the continuity annex
  above is actually for — close the structure, let it run, do nothing —
  is always a human action taken at a broker, off this program entirely.
- **A dead droplet looks identical to a quiet week, for up to two
  weeks.** If the box itself goes down — not a data problem, a hosting
  problem — nothing here notices immediately; the heartbeats' grace
  windows are the only thing that eventually will. See RUNBOOK.md §13
  for exactly how long that takes for each check.
- **Every guarantee above assumes the state file itself loads.** The
  provenance ledger, the boot-wiring report, and the compliance strip
  all need `program_state.json` to be readable before they can say
  anything at all. A corrupted or unreadable state file is a `/health`
  failure to diagnose from RUNBOOK.md §12, not something these surfaces
  can explain from the inside.

## Where the rest of this lives

- **RUNBOOK.md** cross-references this page for the "operator is gone,"
  not "droplet is gone," scenario — §7 covers the latter.
- **The handbook's [Continuity
  Planning](https://qwertytam.github.io/deltadewa-handbook/part-7/continuity-planning/)
  page** covers the decision and the procedure. Linking the software-trust
  content above from that page — so a partner reading it in one place
  gets both halves — is handbook-repo work, not done as part of this
  page; [#311](https://github.com/qwertytam/deltadewa/issues/311) (filed
  in this repo) tracks it, but the actual change needs its own PR against
  `qwertytam/deltadewa-handbook`.
- **The private ops doc** carries the one thing that belongs in neither
  public document: this specific program's broker, accountant, login
  credentials, and positions.
