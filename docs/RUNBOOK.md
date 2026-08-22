# RUNBOOK

One page, copy-pasteable. Written for a fresh clone six months from now with
nothing memorised. Scope: the M2.3 skeleton — a single Dash container on a
DigitalOcean droplet, reachable only over Tailscale. Provisioning (clicking
in DigitalOcean) is manual; everything below the click is a command.

**M2.6 note:** cron, the offsite backup push, and the weekly digest email
are now live — see §9–§13 below.

**Ownership note (#220, #237):** the container runs as a fixed-UID
non-root user (`docker-entrypoint.sh`), not root — see §1's
`docker compose build` step and §2's sanity check below. §10 has the
full exports/.git ownership invariant #237 fixed.

---

## 1. First-time setup — provision the droplet

**Size:** one Dash app + QuantLib is CPU-light (analytic pricing, no
lattice/PDE) but the Poetry/Jupyter dependency set is heavy on disk and the
image build wants headroom. Basic Droplet, regular (shared CPU), **2 vCPU /
4 GB RAM / 80 GB SSD**, Ubuntu 24.04 LTS. Undersized (1 GB) has failed
`docker compose build` from OOM during the QuantLib wheel install in
testing elsewhere; go straight to 4 GB.

```bash
# (root — droplet console / first SSH as root, right after first boot)

adduser deploy
usermod -aG sudo deploy
su - deploy
```

Everything below this point runs as `deploy` (the `su -` above already
switched you). The Docker and Tailscale installers below are still run as
`deploy`, not root — each script detects it isn't running as root and
re-invokes itself via `sudo` internally, which works because `deploy` has
passwordless-prompted `sudo` from `usermod -aG sudo` above.

```bash
# (deploy)

# Docker + Compose plugin (official convenience script; includes
# docker-compose-plugin, i.e. `docker compose`, not the standalone v1 binary)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
newgrp docker
docker compose version   # sanity check

# Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up        # opens an auth URL — approve in the tailnet admin

# This droplet's Tailscale IP — you will need it for BIND_ADDR below and
# for every bookmark/curl in this doc
tailscale ip -4

# Clone
git clone https://github.com/qwertytam/deltadewa.git
cd deltadewa

# BIND_ADDR: docker compose reads this from .env (gitignored, not committed).
# MUST be the Tailscale IP just printed above — never 0.0.0.0. See the
# exposure check (§2) for why this is the actual security boundary.
echo "BIND_ADDR=<tailscale-ip-from-above>" > .env

# config/ips.yaml holds this program's real policy and is gitignored (#245)
# — the clone above does not include it. Copy the template and fill in your
# real numbers before the first build, or the app comes up with no policy
# loaded (§5's "No IPS policy is loaded" screen) rather than failing the
# build. (#279 retired the companion config/dashboard.yaml; the IPS is now
# the only config the app loads.)
cp config/ips.example.yaml config/ips.yaml
# edit config/ips.yaml now

# Build BOTH images explicitly, then start. `docker compose up -d --build`
# on its own only builds/starts `app` — `jobs` is profile-gated (see
# compose.yaml) and Compose excludes non-active-profile services from a
# bare `build` the exact same way it excludes them from `up`, so `--build`
# here would silently leave `jobs` unbuilt. Naming both services on
# `build` still does not start `jobs` — that gate is untouched, and `up`
# below is still bare, so only `app` comes up. This split is the fix for
# #293; every later `docker compose build` in this doc follows the same
# two-service form for the same reason.
docker compose build app jobs
docker compose up -d
```

**exports/ ownership (#220):** the container runs as a fixed-UID non-root
user, not root, and `docker-entrypoint.sh` chowns the bind-mounted
`exports/` tree to that user on every container start — so a fresh
`exports/` that Docker auto-creates as `root:root` on this first `up`
self-heals immediately, no manual `chown` needed. This only works cleanly
if that fixed UID/GID (default `1000`, matching the first non-root user
`adduser deploy` creates on a fresh Ubuntu box) actually matches `deploy`:

```bash
# (deploy) — confirm before the first docker compose build, or after if
# unsure; a UID/GID mismatch here is why deploy might still see
# Permission denied writing into exports/ directly (scp/mv, §5) even
# though the app itself runs fine
id deploy
# uid=1000(deploy) gid=1000(deploy) ... -> nothing to do, default matches

# If deploy's UID/GID differ from 1000, set them and rebuild:
echo "APP_UID=$(id -u deploy)" >> .env
echo "APP_GID=$(id -g deploy)" >> .env
docker compose build app jobs   # both images take APP_UID/APP_GID as build args
docker compose up -d
```

## 2. The exposure check — mandatory after any ports change

Docker inserts published ports into the `nat` table **ahead of** any
UFW/iptables rule — published ports bypass UFW entirely. `BIND_ADDR` in
`compose.yaml` (not the firewall) is what keeps this off the public
internet. Run both checks below after `docker compose up` and after any
change to `compose.yaml`'s `ports:` line.

```bash
# From a machine OFF the tailnet (e.g. your phone on cellular data, or
# `curl --interface <public-uplink>` from elsewhere): must refuse/timeout
curl -m 5 http://<droplet-public-ip>:8050/health
# expected: "Connection refused" or a timeout — NOT a JSON response

# From a machine ON the tailnet: must succeed
curl http://<tailscale-ip>:8050/health
# expected: {"status":"ok", ...}
```

If the public-IP curl returns JSON, stop — `BIND_ADDR` is wrong or unset
(falls back to `127.0.0.1`, which is safe, but check `.env` exists and
`docker compose config` shows the tailnet IP, not the fallback, before
assuming anything).

**exports/ ownership sanity check (#220)** — worth running alongside the
above after any fresh `docker compose up`, since both catch a config
problem before it becomes a 3am surprise:

```bash
ls -la ~/deltadewa/exports
# expected: owned by deploy (uid 1000, or whatever APP_UID/APP_GID §1 set),
# not root — confirms docker-entrypoint.sh's chown ran and deploy can
# scp/mv into it directly (§5) without a manual chown workaround
```

## 3. Client setup — what the other users do once

1. Install Tailscale (desktop or mobile — <https://tailscale.com/download>).
2. Sign in with the authorized account (MFA lives on this login, not on
   the app itself).
3. Bookmark: `http://<tailscale-ip>:8050/monitor`

No VPN client config, no port, no password beyond the Tailscale login.

## 4. Routine ops

**One-time, the first deploy past #245 only:** before that tag's
`git checkout`, `config/ips.yaml` and `config/dashboard.yaml` are still
git-tracked on this droplet (#279 has since retired `dashboard.yaml`
altogether — if the droplet is already past #245, back up `ips.yaml` alone
and skip the rest of this step); after it, they're gitignored and no longer
shipped by any tag. `git checkout` deletes a tracked file from the working
tree when the target tag no longer tracks it — so checking out that tag
straight will silently wipe your live policy out from under the running
container. Back the two files up first, checkout, then put them back
(they're untracked from then on, so this is a one-time step, not a
per-deploy one):

```bash
cp config/ips.yaml config/dashboard.yaml /tmp/
git fetch --tags
git checkout <the #245 tag or later>
cp /tmp/ips.yaml /tmp/dashboard.yaml config/
docker compose build app jobs   # COPY config ./config bakes the restored
                                 # files in; name both — §1 explains why
docker compose up -d
```

```bash
# Deploy an update — pull a TAG, not main, so what's running is
# always a known, reviewed point, not whatever HEAD happens to be
cd deltadewa
git fetch --tags
git checkout <tag>
docker compose build app jobs   # name both, or `jobs` drifts — §1, #293
docker compose up -d

# Logs
docker compose logs -f app

# Restart (no rebuild)
docker compose restart app

# Health check
curl http://<tailscale-ip>:8050/health
```

Host cron drives the market-data refresh, the weekly digest email, and the
`exports/` backup push automatically — see §9 for the crontab lines, §11 to
run any of them by hand.

## 5. Loading your positions

For a bulk or fresh load, the CLI importer is still the right tool — it's
the fastest way to get a whole book in at once, run against the shared
`exports/` state. For adding one or two positions to a book that's already
live, use `/design` instead (§6).

```bash
# 1. Write the portfolio YAML into exports/ (the bind-mounted, stateful
#    directory — see §8). examples/portfolios/spx_protective_put.yaml (in
#    the repo, not on the droplet's bind mount) is the format to copy —
#    scp it up or paste its contents into a new file here.
scp examples/portfolios/spx_protective_put.yaml \
    deploy@<tailscale-ip>:~/deltadewa/exports/portfolio.yaml

# 2. Run the importer inside the container (matches the app's own
#    Python/deps — this is the normal path)
docker compose exec app python -m deltadewa.app.import_portfolio \
    exports/portfolio.yaml

# On the host instead, only if it has a matching Poetry env set up
# (not the normal case for this droplet):
# poetry run python -m deltadewa.app.import_portfolio exports/portfolio.yaml

# Re-importing later refuses to overwrite the existing state unless forced
docker compose exec app python -m deltadewa.app.import_portfolio \
    exports/portfolio.yaml --force
```

Fields worth getting right before importing, or specific panels degrade to
an explicit "unavailable" rather than a number:

- **`underlying_quantity`** — without it, delta-drift/theta-cost/hedge-ratio
  metrics and the offset framing report unavailable rather than a
  fabricated figure.
- **`entry_spot` / `entry_premium`** on each leg — without them, the
  monetization gain basis falls back to an explicit unknown-basis figure
  instead of a computed cost basis.
- **`exercise_style: EUROPEAN`** on every SPX leg — SPX is cash-settled
  European; the American finite-difference path is only correct for
  single-name/SPY and must not be left as the default for an SPX book.

**IPS policy file.** `config/ips.yaml` is baked into the image at build
time (`COPY config ./config` in the `Dockerfile`) — it is *not* on the
`exports/` bind mount, and it's gitignored (#245): the clone doesn't
include it, and `git checkout`/`git pull` never touch it once it exists
here (see §4's one-time note for the transition). If it's missing or
invalid, `/monitor` renders a single "No IPS policy is loaded" screen in
place of the crash-led content (there's no partial-policy state — see
`docker compose logs -f app` for why it was skipped); to change it, edit
`config/ips.yaml` directly on the droplet and rebuild
(`docker compose build app jobs` — name both, §1, #293: `jobs` bakes in
the same `COPY config ./config` and goes just as stale) — a live
container won't pick up a host-side edit to it, and there's nothing to
commit or push.

**Verify:**

```bash
curl http://<tailscale-ip>:8050/health
# expect: "state_loaded": true, and market_data.source/as_of reflecting
# the data's actual freshness
```

Reload `http://<tailscale-ip>:8050/monitor` and confirm:

- the crash-led headline sentence at the top shows real numbers (spot
  move, vol shock, hedge gain, underlying loss, share count) — not zeros
  and not the "No IPS policy is loaded" screen
- the monetization panel shows an actual gain percentage if `entry_premium`
  was set on the puts, or its explicit "No entry price is recorded..."
  sentence if it wasn't
- the as-of stamp under the top banner reflects the data's actual
  freshness, with no STALE/SYNTHETIC/UNAVAILABLE banner unless that's
  genuinely the feed's current state

## 6. Adding a position via `/design`

Bookmark `http://<tailscale-ip>:8050/design`. This is the operator's editor
— §5's CLI importer is still the right tool for a bulk or fresh load;
`/design` is for one-off additions to a book that's already live.

- Fill in Strike, Maturity, Quantity, Type (put/call, defaults to put),
  Exercise style (defaults from `config/ips.yaml`'s pricing exercise
  style — don't override it for an SPX leg), and Entry premium (optional,
  but needed for the monetization panel's real gain basis rather than its
  "unknown" one). Click **Add position**.
- There is no in-place edit — changing a position is remove + add. Click
  **Remove** on the old row (a browser confirm dialog is the safety gate,
  and it can't be scripted around), then re-add it with the new numbers.
- Underlying quantity has its own field at the top of the BOOK zone; it
  autosaves like every other mutation on this page.
- Every add/remove autosaves immediately to `exports/program_state.json`
  — the same file `/monitor` reads — so there's nothing further to run.

**Verify:** reload `/monitor` — the new position should be in the collapsed
"Position detail" table, and (if `entry_premium` was set) the monetization
panel should show a real gain percentage instead of "No entry price is
recorded...". `/design`'s own PLANNING panels reprice against the change on
their own — there's no Recompute button anywhere on this page.

## 7. Recovery — the droplet dies

Target: **under 30 minutes, nothing memorised.**

```bash
# 1. New droplet, repeat section 1 in full, up to (not including) the
#    final `docker compose build app jobs` / `docker compose up -d`

# 2. Restore exports/ from the offsite backup remote (see §8) — clone
#    it directly into the repo's exports/ directory (the bind-mount
#    source). `sudo` is required, not optional: the SSH deploy key this
#    needs (§10) is root-owned 0600 at /root/.ssh/backup_deploy_key, so
#    only a root-privileged clone can authenticate at all. This is also
#    what lands the restored exports/ and exports/.git root-owned,
#    matching the ownership invariant docker-entrypoint.sh now preserves
#    (§10's Ownership note, #237) — `~` still resolves to /home/deploy
#    here (expanded by deploy's own shell before sudo runs), so the
#    destination path is unaffected, only the process's privilege is.
#    The actual remote URL is BACKUP_REMOTE — see private ops doc.
sudo rm -rf ~/deltadewa/exports   # the bind-mount source; §1 hasn't created it yet
sudo git clone <BACKUP_REMOTE — see private ops doc> \
    ~/deltadewa/exports

# 3. Bring it up — build both, name both (§1, #293), then start
docker compose build app jobs
docker compose up -d

# 4. Confirm state actually came back
curl http://<new-tailscale-ip>:8050/health   # state_loaded should be true
# market_data.source should read CACHED (or STALE, not UNAVAILABLE) —
# the restored exports/marketdata-cache/ means this box doesn't start
# blind even before the next refresh cron fires.
```

**Email will fail until the SMTP relay's IP allowlist is updated.** A new
droplet means a new outbound IP, and most transactional-email providers
only accept sends from allowlisted sending IPs — the weekly digest job
fails to send until the new droplet's IP is added on the relay's side
(see private ops doc for which provider and dashboard). This trips the
`DIGEST_HEARTBEAT_URL` alarm (§13) on the next scheduled run, which is
the mechanism that will actually catch it if this step gets missed — but
don't rely on that: add the new IP to the allowlist as part of step 3
above, not after the first missed digest surfaces it.

## 8. What lives where

- **`exports/`** — the only stateful directory. Bind-mounted (not a named
  volume, so `ops/backup-exports.sh` can read it directly off the host
  filesystem — see `compose.yaml`). Contains `program_state.json` (the
  live portfolio + IPS state), `exports/marketdata-cache/` (the warmed
  CBOE/FRED cache both `app` and `jobs` share via `DELTADEWA_CACHE_DIR`),
  `exports/reports/weekly/` (digest + snapshot history), and any
  autosaves.
- **Everything else** — code, config, the image itself — is rebuildable
  from `git clone` + `docker compose build`. Nothing else on the droplet
  needs to survive a rebuild.
- **Offsite backup**: `exports/` is *itself* a standalone git repo (nested
  inside this repo's already-gitignored `exports/`, so there's no
  submodule conflict), pushed nightly by root's cron to a private offsite
  git remote (`BACKUP_REMOTE` — see §10, and the private ops doc for
  which host/repo) — see §9 (cron), §10 (the SSH deploy key), §12
  (verifying the last push). `age` encryption is a deliberate follow-up,
  not done yet: a backup you can't decrypt is worse than one you can, and
  adding it needs an explicit key-escrow step first.

## 9. Cron setup

Two crontabs, on purpose — see §10 for why the credentials underneath
them are kept apart:

```bash
# deploy's crontab (crontab -e, as `deploy`) — the two jobs, both run
# through the `jobs` compose service (see compose.yaml). The digest line
# is scheduled AFTER the refresh line so it reads freshly-warmed data.
mkdir -p ~/deltadewa/logs

crontab -e
# Market-data refresh — seven days a week (CBOE/FRED are closed weekends,
# but a weekend run still re-observes Friday's close and refreshes
# fetched_at; a weekdays-only schedule would leave a 72h gap the TTL
# can't absorb — see deltadewa/marketdata/refresh.py's own docstring).
30 2 * * * cd /home/deploy/deltadewa && docker compose run --rm --no-deps jobs python -m deltadewa.marketdata.refresh >> /home/deploy/deltadewa/logs/refresh.log 2>&1

# Weekly digest, with delivery — Sundays 03:00 UTC, after the refresh above.
0 3 * * 0 cd /home/deploy/deltadewa && docker compose run --rm --no-deps jobs python -m deltadewa.reporting.weekly_report --send-email >> /home/deploy/deltadewa/logs/weekly_report.log 2>&1
```

```bash
# root's crontab (sudo crontab -e) — the offsite backup push. Separate
# from deploy's crontab because the push credential is root-owned (§10).
# BACKUP_REMOTE is required — the script fails loudly at the first line
# if it's unset (#243); see §10 for why neither value below goes in
# .env or gets hardcoded in the script. BACKUP_HEARTBEAT_URL wires up
# the third dead-man's-switch check — see §13.
sudo crontab -e
BACKUP_REMOTE=<see private ops doc>
BACKUP_HEARTBEAT_URL=<see private ops doc>
30 3 * * * /home/deploy/deltadewa/ops/backup-exports.sh >> /var/log/deltadewa-backup.log 2>&1
```

**Log rotation (#244)** — install once, as root:

```bash
sudo cp ops/logrotate-deltadewa.conf /etc/logrotate.d/deltadewa
```

Rotates `~/deltadewa/logs/*.log` and `/var/log/deltadewa-backup.log`
weekly, keeping 8 compressed generations (~2 months) — see the config
file's own header comment for why no `postrotate`/`copytruncate` is
needed here.

## 10. Secrets — three separate homes, don't mix them up

- **`.env`** (repo root, gitignored — `.env.example` is the tracked
  template). Holds `BIND_ADDR` and everything the `jobs` compose service
  needs: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
  `REPORT_EMAIL_TO`, `REPORT_EMAIL_FROM`, `FRED_API_KEY` (reserved, safe
  to leave blank), `REFRESH_HEARTBEAT_URL`, `DIGEST_HEARTBEAT_URL`. Read
  into the `jobs` container via `env_file: .env`; the six required-for-email
  vars are also declared `${VAR:?...}` in `compose.yaml` so a
  `docker compose run jobs ...` fails immediately, at the command line, if
  `.env` was never populated — not three months later inside a Python
  traceback.

  The email transport (`deltadewa/reporting/email_smtp.py`) is plain
  stdlib SMTP, so the provider is interchangeable — any SMTP relay works
  (Resend, Brevo, Amazon SES, Mailtrap, ...) by changing only these `.env`
  values, no code change; see the private ops doc for which provider and
  port this deployment actually uses. `SMTP_PORT` selects the connection
  mode: `465` is implicit TLS/SMTPS, anything else (typically `587`) is
  STARTTLS. **DigitalOcean blocks outbound traffic on 25/465/587 by
  default** — pick a relay/port combination DigitalOcean leaves open; if
  a droplet's digest job hangs or times out on connect rather than
  failing on auth, check the port before the credentials. If using
  Amazon SES, sandbox mode is fine indefinitely for this use case — just
  verify the two fixed recipient addresses (`REPORT_EMAIL_TO` and
  `REPORT_EMAIL_FROM`) in the SES console rather than requesting
  production access.
- **The offsite backup SSH deploy key** — `/root/.ssh/backup_deploy_key`
  (mode `0600`, root-owned), referenced by a `~/.ssh/config` alias so
  `ops/backup-exports.sh` never hardcodes the key path, and by
  `BACKUP_REMOTE` (§9) so it never hardcodes the remote either (#243):

  ```text
  # /root/.ssh/config
  Host backup-remote
      HostName <see private ops doc>
      User git
      IdentityFile /root/.ssh/backup_deploy_key
      IdentitiesOnly yes
  ```

  Provisioning (once, manual, same spirit as §1's droplet click-through):
  generate the key (`ssh-keygen -t ed25519 -f /root/.ssh/backup_deploy_key
  -N ""`), create a **private** repo on your chosen git host — see private
  ops doc for which provider and the exact repo name — add the key's
  public half as a deploy key with **write** access.

  **Ownership note (#220, fixed by #237):** this cron runs as root, so
  `exports/.git` — and `exports/` itself, the working-tree top —
  end up root-owned. `docker-entrypoint.sh` used to `chown -R` the
  *entire* `exports/` tree, including both of those, to the app user on
  every container start/restart, which silently broke this cron's next
  push: git's dubious-ownership guard (`safe.directory`, default since
  git 2.35.2) checks ownership of **both** the working-tree top and the
  gitdir against the invoking euid, and a mismatch on either one is
  fatal. Fixed in #237 — the entrypoint now chowns everything under
  `exports/` **except** `.git/`, and never touches `exports/` itself; the
  app gets write access via the group bit (`chgrp`, not `chown` —
  invisible to git's owner-based check) instead of ownership.

  **The resulting invariant:** the app owns its data files
  (`program_state.json`, `marketdata-cache/`, `reports/weekly/`); root
  owns `.git/` and `exports/` itself; neither re-owns the other's.
  Restart the container as often as you like, run the backup cron as
  often as you like — neither disturbs the other's ownership.

  **Remote-URL note (#243):** `ops/backup-exports.sh` reconciles
  `exports/.git`'s `origin` against `BACKUP_REMOTE` on **every** run, not
  just at first init — if they differ (e.g. `exports/.git` was created or
  restored with a different URL form than `BACKUP_REMOTE`, such as a
  manual `git clone` during §7's recovery using the HTTPS form of the
  repo URL instead of the SSH alias above), the script runs `git remote
  set-url` itself and logs that it changed, rather than silently pushing
  against a stale remote or hanging on a non-interactive credential
  prompt under cron (no TTY). `BACKUP_REMOTE` itself is required with no
  default or fallback — the script fails loudly at the top if it's unset,
  rather than reusing whatever happened to be configured from a previous
  run.
- **The optional token alternative** — `/etc/deltadewa/backup.env`
  (mode `0600`, root-owned), sourced by `ops/backup-exports.sh` if
  present, before `BACKUP_REMOTE` is even checked for (so this file alone
  is enough to satisfy it). **Never** put the backup-remote credential in
  `.env` — `env_file: .env` is read into the `jobs` container, so
  anything there is exposed to every job command run through it; the
  whole point of a host-side credential (SSH key or this file) is that it
  never enters a container at all. This same file (or the crontab line
  itself, §9) is also where `BACKUP_REMOTE` and `BACKUP_HEARTBEAT_URL`
  are set — `.env.example` documents both for discoverability, but the
  backup cron never reads `.env` for the same reason: it's root's
  crontab, not the `jobs` container.

  **The crontab line and this file are not interchangeable (#253):** the
  crontab environment always wins if both set `BACKUP_REMOTE` and/or
  `BACKUP_HEARTBEAT_URL` — `ops/backup-exports.sh` captures whatever the
  environment already had before sourcing `backup.env` and restores it
  afterwards, so the file can only *fill in* a value the crontab left
  unset, never override one. The script logs which source won on every
  run (`BACKUP_REMOTE from environment (overriding backup.env)` or
  `BACKUP_REMOTE from backup.env`), so a mismatch between what you
  expect and what actually ran is visible in the cron log rather than
  silent. Before #253 this was a plain `source`, which has no notion of
  "already set" — it just assigned, so `backup.env` silently clobbered
  an explicit crontab-line value.

This section exists because all three are plausible places to reach for
the same kind of "just add a secret here" instinct — they are
deliberately not interchangeable.

## 11. Running each job manually

```bash
# Market-data refresh
docker compose run --rm --no-deps jobs python -m deltadewa.marketdata.refresh

# Weekly digest — build only, no email (files land under exports/reports/weekly/)
docker compose run --rm --no-deps jobs python -m deltadewa.reporting.weekly_report --as-of 2026-08-05

# Weekly digest — build and send
docker compose run --rm --no-deps jobs python -m deltadewa.reporting.weekly_report --send-email

# Offsite backup push (root; needs the SSH key from §10)
sudo /home/deploy/deltadewa/ops/backup-exports.sh
```

## 12. Verifying the last run succeeded

```bash
# Cron logs
tail -50 ~/deltadewa/logs/refresh.log
tail -50 ~/deltadewa/logs/weekly_report.log
sudo tail -50 /var/log/deltadewa-backup.log

# Latest digest + snapshot files
ls -la ~/deltadewa/exports/reports/weekly/ | tail -5

# Market-data cache freshness (mtimes should track the refresh schedule)
ls -la ~/deltadewa/exports/marketdata-cache/

# Last backup commit actually pushed
cd ~/deltadewa/exports && git log -1 --format='%H %ci'

# The app's own view of data freshness
curl http://<tailscale-ip>:8050/health
```

Also check the healthchecks.io (or equivalent) dashboard — all three
checks should show green with a "last ping" time inside their schedule +
grace window (see §13).

## 13. What each heartbeat alarm means when it fires

`REFRESH_HEARTBEAT_URL`, `DIGEST_HEARTBEAT_URL`, and
`BACKUP_HEARTBEAT_URL` (`.env`/root's crontab, §10) are three *separate*
checks because the three jobs fail independently and an overdue alarm
means something different for each — see `deltadewa/heartbeat.py`'s
docstring for the refresh/digest design rationale (`ops/backup-exports.sh`'s
own `ping_heartbeat()` mirrors the same contract in bash, since that cron
runs outside Python entirely). Suggested starting grace periods
(comfortably over each job's own schedule; tune from there): refresh —
period 1 day, grace 4 hours; digest — period 1 week, grace 1 day; backup
— period 1 day, grace 4 hours (same cadence reasoning as refresh — it
also runs nightly, at 03:30).

- **REFRESH overdue**: the market-data refresh hasn't produced even a
  partial success (exit 0 or 1) within the grace window — either the cron
  entry itself stopped firing, or CBOE/FRED have been unreachable for
  longer than a routine early-morning lag. Check
  `~/deltadewa/logs/refresh.log`, then run §11's refresh command by hand
  and read its exit code (`echo $?`; 0/1 partial-or-full success, 2 total
  failure).
- **DIGEST overdue**: the weekly email did not send. This is the
  dangerous one — an overdue digest reads exactly like "a quiet week, no
  news," which is precisely why the design pings only on a *confirmed*
  send (`deltadewa/reporting/weekly_report.py`). Check
  `~/deltadewa/logs/weekly_report.log` for a `--send-email` failure
  (missing/invalid env var, or the SMTP relay rejecting the
  credentials/quota), then re-run §11's send command by hand.
- **BACKUP overdue**: the offsite `exports/` push (or its "nothing
  changed" no-op) hasn't confirmed within the grace window — either
  root's crontab entry stopped firing, or the push itself is failing.
  Check `sudo tail -50 /var/log/deltadewa-backup.log` first — a `fatal:
  detected dubious ownership` (or `fatal: not in a git directory`) error
  there means `exports/` or `.git/` ended up owned by something other
  than root; see §10's Ownership note and #237 before assuming it's a
  network/credential problem. Otherwise re-run §11's backup command by
  hand (`sudo ...backup-exports.sh`, no `>>` redirect, so errors print
  directly). **A no-op run only pings after confirming the remote (#252):**
  on the "nothing to commit" path the script now runs `git ls-remote`
  against `origin main` and compares it to local `HEAD` before pinging —
  a genuinely unreachable remote or a SHA mismatch (an earlier push that
  silently didn't land) both fail the run and skip the ping, rather than
  reporting green on an unchanged local tree alone. Look for `does not
  match local HEAD` or `could not reach origin` in the log for that
  failure mode specifically.

**A failed heartbeat ping is not itself a backup failure (#252)** —
`ping_heartbeat()` stays exit-0 on a ping failure (a curl error or a
non-2xx like 400), same contract as `deltadewa/heartbeat.py`'s `ping()`:
a monitoring hiccup must not read as a backup outage. That silence used
to make a broken `BACKUP_HEARTBEAT_URL` invisible, so a ping failure now
also writes `exports/.backup-heartbeat-status.json` (cleared on the next
successful ping) — the weekly digest reads it and shows a caveat banner
("Offsite backup heartbeat ping failed as of ...") when present. If you
see that banner but the `sudo tail .../deltadewa-backup.log` history
shows real pushes/no-ops landing, the backup itself is fine — only
`BACKUP_HEARTBEAT_URL` needs attention (dead URL, expired healthchecks.io
check, DNS).
