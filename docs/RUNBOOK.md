# RUNBOOK

One page, copy-pasteable. Written for a fresh clone six months from now with
nothing memorised. Scope: the M2.3 skeleton — a single Dash container on a
DigitalOcean droplet, reachable only over Tailscale. Provisioning (clicking
in DigitalOcean) is manual; everything below the click is a command.

**M2.6 note:** cron, the offsite backup push, and the weekly digest email
are now live — see §9–§13 below.

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

docker compose up -d --build
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

## 3. Client setup — what the other users do once

1. Install Tailscale (desktop or mobile — <https://tailscale.com/download>).
2. Sign in with the authorized account (MFA lives on this login, not on
   the app itself).
3. Bookmark: `http://<tailscale-ip>:8050/monitor`

No VPN client config, no port, no password beyond the Tailscale login.

## 4. Routine ops

```bash
# Deploy an update — pull a TAG, not main, so what's running is
# always a known, reviewed point, not whatever HEAD happens to be
cd deltadewa
git fetch --tags
git checkout <tag>
docker compose build
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
`exports/` bind mount. If it's missing or invalid, `/monitor` renders a
single "No IPS policy is loaded" screen in place of the crash-led content
(there's no partial-policy state — see `docker compose logs -f app` for
why it was skipped); to change it, edit `config/ips.yaml` in the repo
clone and rebuild (`docker compose build`) — a live container won't pick
up a host-side edit to it.

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
#    final `docker compose up -d --build`

# 2. Restore exports/ from the offsite Codeberg backup (see §8) — clone
#    it directly into the repo's exports/ directory (the bind-mount
#    source). Needs the same SSH deploy key set up as §10 describes.
rm -rf ~/deltadewa/exports   # the bind-mount source; §1 hasn't created it yet
git clone codeberg-backup:deploy_deltadewa-exports-backup.git \
    ~/deltadewa/exports

# 3. Bring it up
docker compose up -d --build

# 4. Confirm state actually came back
curl http://<new-tailscale-ip>:8050/health   # state_loaded should be true
# market_data.source should read CACHED (or STALE, not UNAVAILABLE) —
# the restored exports/marketdata-cache/ means this box doesn't start
# blind even before the next refresh cron fires.
```

**Email will fail until Brevo's IP allowlist is updated.** A new droplet
means a new outbound IP, and Brevo (like most transactional-email
providers) only accepts sends from allowlisted sending IPs — the weekly
digest job fails to send until the new droplet's IP is added in the
Brevo dashboard. This trips the `DIGEST_HEARTBEAT_URL` alarm (§13) on the
next scheduled run, which is the mechanism that will actually catch it if
this step gets missed — but don't rely on that: add the new IP to
Brevo's allowlist as part of step 3 above, not after the first missed
digest surfaces it.

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
  submodule conflict), pushed nightly by root's cron to a private
  Codeberg repo — see §9 (cron), §10 (the SSH deploy key), §12 (verifying
  the last push). `age` encryption is a deliberate follow-up, not done
  yet: a backup you can't decrypt is worse than one you can, and adding
  it needs an explicit key-escrow step first.

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
sudo crontab -e
30 3 * * * /home/deploy/deltadewa/ops/backup-exports.sh >> /var/log/deltadewa-backup.log 2>&1
```

Log rotation isn't set up yet — `logs/` and `/var/log/deltadewa-backup.log`
will grow unbounded until a follow-up adds `logrotate` config; check
periodically until then.

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
  values, no code change. `SMTP_PORT` selects the connection mode: `465`
  is implicit TLS/SMTPS, anything else (typically `587`) is STARTTLS.
  **DigitalOcean blocks outbound traffic on 25/465/587 by default** — this
  deployment uses **2525** (also STARTTLS), which DigitalOcean leaves
  open; if a droplet's digest job hangs or times out on connect rather
  than failing on auth, check the port before the credentials. If using
  Amazon SES, sandbox mode is fine indefinitely for this use case — just
  verify the two fixed recipient addresses (`REPORT_EMAIL_TO` and
  `REPORT_EMAIL_FROM`) in the SES console rather than requesting
  production access.
- **The Codeberg SSH deploy key** — `/root/.ssh/codeberg_backup` (mode
  `0600`, root-owned), referenced by a `~/.ssh/config` alias so
  `ops/backup-exports.sh` never hardcodes the key path:

  ```text
  # /root/.ssh/config
  Host codeberg-backup
      HostName codeberg.org
      User git
      IdentityFile /root/.ssh/codeberg_backup
      IdentitiesOnly yes
  ```

  Provisioning (once, manual, same spirit as §1's droplet click-through):
  generate the key (`ssh-keygen -t ed25519 -f /root/.ssh/codeberg_backup
  -N ""`), create a **private** repo on Codeberg
  (`deploy_deltadewa-exports-backup`), add the key's public half as a
  deploy key with **write** access.

  **Remote-URL note:** `ops/backup-exports.sh` only runs `git remote add
  origin` inside its `if [ ! -d .git ]` first-init branch — it never
  `set-url`s on a subsequent run. If `exports/.git` is ever created or
  restored with an `https://` remote instead of the `codeberg-backup:`
  SSH alias above (e.g. a manual `git clone` during §7's recovery using
  the HTTPS form of the repo URL), the script won't notice or correct
  it — `git push` against that remote hangs on a non-interactive
  credential prompt under cron (no TTY, no `GIT_TERMINAL_PROMPT=0` guard
  in the script), and the backup silently stops running. If a restore
  ever needs the HTTPS URL for any reason, re-point the remote by hand
  afterwards: `git -C ~/deltadewa/exports remote set-url origin
  codeberg-backup:deploy_deltadewa-exports-backup.git`.
- **The optional token alternative** — `/etc/deltadewa/backup.env`
  (mode `0600`, root-owned), sourced by `ops/backup-exports.sh` if
  present. **Never** put a Codeberg token in `.env` — `env_file: .env` is
  read into the `jobs` container, so anything there is exposed to every
  job command run through it; the whole point of a host-side credential
  (SSH key or this file) is that it never enters a container at all.

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

Also check the healthchecks.io (or equivalent) dashboard — both checks
should show green with a "last ping" time inside their schedule + grace
window (see §13).

## 13. What each heartbeat alarm means when it fires

`REFRESH_HEARTBEAT_URL` and `DIGEST_HEARTBEAT_URL` (`.env`, §10) are two
*separate* checks because the two jobs fail independently and an overdue
alarm means something different for each — see
`deltadewa/heartbeat.py`'s docstring for the full design rationale.
Suggested starting grace periods (comfortably over each job's own
schedule; tune from there): refresh — period 1 day, grace 4 hours;
digest — period 1 week, grace 1 day.

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
