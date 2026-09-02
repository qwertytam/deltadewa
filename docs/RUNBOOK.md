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

**Continuity note (#311):** this page is about the **droplet** dying —
§7 covers that recovery. A different scenario, the **operator** being
gone, is covered by
[`docs/continuity-annex.md`](continuity-annex.md) (what the dashboard
and the weekly digest can actually be trusted for once nobody is running
them) and the handbook's [Continuity
Planning](https://qwertytam.github.io/deltadewa-handbook/part-7/continuity-planning/)
page (the decision and the concrete steps — wind down, run off, or
maintain). Neither of those two documents carries this program's actual
broker, accountant, or credentials; that stays in the private ops doc.

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
# expected: {"status":"ok", ...} — read past "status" though: check
# boot_wiring.ips_loaded too (§12, #309). /health returns 200 even when
# degraded, by design, so a bare 200 here doesn't confirm the IPS policy
# actually loaded.
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

# config/ips.yaml is baked in at build time, not live (§5) — a host-side
# edit needs a rebuild before it takes effect. If this tag changed the
# IPS schema (a new required field, a renamed key — check the release's
# PR body/notes; that fact currently lives only there), edit
# config/ips.yaml on the droplet now, before building, or the pre-flight
# check below will fail against a stale-but-otherwise-valid file.
docker compose build app jobs   # name both, or `jobs` drifts — §1, #293

# Validate the freshly-built image's baked config BEFORE cutover, so a
# missing/invalid ips.yaml is caught here rather than as a live "No IPS
# policy is loaded" page. `run --rm`, not `exec`: at this point the OLD
# container is still what `exec` would reach, so only running against
# the image just built actually validates what's about to go live.
# No --strict here: an operator legitimately omitting an optional
# section is not a failed deploy — that's what §7's restore drill uses
# --strict for, where a silently-defaulted or silently-ignored value is
# exactly what must not pass unnoticed.
docker compose run --rm app python -m deltadewa.ips_config \
    --check config/ips.yaml

docker compose up -d

# Logs
docker compose logs -f app

# Restart (no rebuild)
docker compose restart app

# Health check — read past "status": "ok"; check boot_wiring.ips_loaded
# too (§12, #309). /health returns 200 even when degraded, by design, so
# a bare 200 here doesn't confirm the policy actually loaded.
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

**The importer writes the state *file*, not the running app (#355).** It
runs in its own process (`docker compose exec` starts a fresh one inside
the container) and never touches the live gunicorn worker's memory — the
worker only reads `exports/program_state.json` once, at boot. **A restart
is required after every import** for the change to show up on `/monitor`
or `/design`; skipping it leaves the browser showing the old book with no
error. The importer's own output makes this concrete: after a successful
write it best-effort probes the running worker's `/health` and tells you
plainly whether that worker already reflects the write (it almost never
does) — see that message rather than trusting "Loaded N position(s)..."
alone.

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

# 3. Restart so the live worker actually picks this up — the import
#    above never reaches it
docker compose restart app
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
place of the crash-led content (there's no partial-policy state). **That
screen names the parse error itself** (#385) — the missing key or bad
value, verbatim — so you should not need `docker compose logs -f app` for
this failure; the log is the fallback, not the first stop. Note what the
screen also says: the file it is reporting on is the one baked into the
*running container*, which is not the host's copy until you rebuild. To
change it, edit
`config/ips.yaml` directly on the droplet, then rebuild **and cut over** —
a live container won't pick up a host-side edit to it, and there's nothing
to commit or push:

```bash
# 1. Rebuild so the edited file is baked into the image. Name both
#    services, §1, #293: `jobs` bakes in the same `COPY config ./config`
#    and goes just as stale.
docker compose build app jobs

# 2. Cut over — the build alone changes nothing the running container
#    serves. Skipping this leaves the old policy live with no error, and
#    the Verify step below passing against the pre-edit image.
docker compose up -d
```

**Verify:**

```bash
curl http://<tailscale-ip>:8050/health
# expect: "state_loaded": true, and market_data.source/as_of reflecting
# the data's actual freshness. After an ips.yaml edit, check
# boot_wiring.ips_loaded too (§12, #309): /health returns 200 even when
# degraded, by design, so a bare 200 here won't catch a policy file that
# failed to load or a rebuild that was never cut over.
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

Target: **under 30 minutes, nothing memorised.** For the *operator*
being gone rather than the droplet — a different scenario, with no
30-minute target — see the Continuity note above.

```bash
# 1. New droplet, repeat section 1 in full, up to (not including) the
#    final `docker compose build app jobs` / `docker compose up -d`.
#    §1's own `cp config/ips.example.yaml config/ips.yaml` step runs as
#    part of this — leave it; step 2b below overwrites it with the real
#    policy. Skipping it isn't a shortcut: later steps (docker compose
#    run, the app itself) expect config/ips.yaml to exist.

# 2a. Restore exports/ from the offsite backup remote (see §8) — clone
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

# 2b. Restore the policy file. config/ips.yaml is baked into the image at
#    build time (§4/§5) — it is NOT part of the exports/ bind mount and
#    NOT part of the code checkout in step 1 either (it's gitignored,
#    #245). The only surviving copy is the nightly snapshot
#    ops/backup-exports.sh stages under exports/config-backup/ (#301),
#    which just landed with step 2a above. Read its manifest FIRST:
cat ~/deltadewa/exports/config-backup/MANIFEST.json
#   {"written_by": "backup-exports.sh", "source": "config/ips.yaml",
#    "sha256": "<64 hex chars>", "app_version": "0.9.2",
#    "policy_changed_at": "<UTC timestamp>"}
#
#   `app_version` is the last app version this exact policy file is KNOWN
#   to load on. This matters because it will usually NOT be whatever tag
#   step 1's plain `git clone` left you on: check out that exact version
#   now — a policy file always loads on the version it was captured
#   under — get the program running as it was, THEN upgrade forward
#   through §4's normal deploy path, where the release notes carry each
#   schema change. Do not skip straight to the latest tag here; that is
#   what §7.2 below is for, when this version is unavailable.
cd ~/deltadewa
git fetch --tags
git checkout v<app_version from the manifest above>   # e.g. v0.9.2
cp ~/deltadewa/exports/config-backup/ips.yaml ~/deltadewa/config/ips.yaml

# 3. Bring it up — build both, name both (§1, #293), then start
docker compose build app jobs

# Validate BEFORE cutover, same pre-flight §4 uses for a routine deploy —
# `run --rm`, not `exec`, so this checks the image just built, not
# whatever (if anything) is already running. If this fails, the file
# doesn't load on this version either — see §7.2.
docker compose run --rm app python -m deltadewa.ips_config \
    --check config/ips.yaml

docker compose up -d

# 4. Confirm state actually came back
curl http://<new-tailscale-ip>:8050/health   # state_loaded should be true
# market_data.source should read CACHED (or STALE, not UNAVAILABLE) —
# the restored exports/marketdata-cache/ means this box doesn't start
# blind even before the next refresh cron fires. Check
# boot_wiring.ips_loaded too (§12, #309): /health returns 200 even when
# degraded, by design, so 200 alone doesn't confirm the restored
# config/ips.yaml actually loaded.
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

**`.env` is not restored by any of the above.** It is deliberately never
part of the offsite backup — see §10's "Why `.env` stays out of the
backup." Recreate it from the private ops doc's own copy (kept current
there per §14's quarterly review) before the jobs service can send email
or the backup cron can run on this new droplet.

### 7.1. Recovery drill — run this before you need it

Run this **from the live droplet**, in a scratch directory outside
`~/deltadewa/exports/` — the real bind mount is never touched, the live
container is never restarted, and nothing here is destructive. Reuses the
`app` image already built on this droplet, so there is nothing new to
build. Fifteen to twenty minutes the first time; a few minutes once it's
routine. See §14 for how often.

1. **Clone the backup to a scratch directory** — never into the real
   `~/deltadewa/exports/`:

   ```bash
   cd ~/deltadewa
   DRILL=/tmp/deltadewa-drill-$(date -u +%Y%m%d)
   sudo git clone <BACKUP_REMOTE — see private ops doc> "${DRILL}"
   ```

2. **Read the policy manifest** and confirm it's actually current:

   ```bash
   cat "${DRILL}/config-backup/MANIFEST.json"
   ```

   Compare its `sha256` against today's live file:

   ```bash
   sha256sum ~/deltadewa/config/ips.yaml   # or: shasum -a 256 ...
   ```

   Match confirms the nightly snapshot is picking up real edits — this
   *is* #301's acceptance criterion, "a drill confirms recovery
   reproduces the exact live policy." A mismatch means either
   `stage_policy_snapshot()` isn't running (check
   `/var/log/deltadewa-backup.log`), or the host file was edited without
   a rebuild-and-cutover (§4/§5) since the last successful backup run.

3. **Check `program_state.json`'s provenance (#355):**

   ```bash
   grep -A1 '"written_by"\|"exported_at"' "${DRILL}/program_state.json"
   ```

   - `written_by` should read `"app"`. If it reads
     `"import_portfolio_cli"`, the last write into this backup came from
     the CLI importer, not the live worker (#355) — the running app may
     never have loaded what's in this file. Restart `app` on the
     droplet, confirm `/health`'s `state.written_by` reads `"app"`, and
     let the next nightly run recapture it.
   - `exported_at` should be within the last week or so. This is the
     only check here that catches a *frozen* state file:
     `marketdata-cache/` inside `exports/` churns every night regardless,
     so the backup repo keeps committing and looks healthy even if
     `program_state.json` itself stopped updating months ago.

4. **Validate the policy on the currently-deployed version** — the
   same-version case, which should be routine:

   ```bash
   docker compose run --rm --no-deps \
       -v "${DRILL}:/restore:ro" app \
       python -m deltadewa.ips_config --check --strict \
       /restore/config-backup/ips.yaml
   ```

   `--strict` here, unlike §4's pre-flight: a drill exists to catch a
   silently-defaulted section or a silently-ignored retired key, not just
   a load failure. Expect exit 0 — this proves today's snapshot loads
   clean on what's actually running.

5. **Exercise a version-skewed restore.** This is the step that changed
   since #301 was filed — several IPS schema changes have shipped since
   (#297 added four required trigger fields, #344 added another, #384
   retired two), so an *old* snapshot will not load on current code.
   Walk the backup's own history and pick an old revision:

   ```bash
   sudo git -C "${DRILL}" log --oneline -- config-backup/ips.yaml
   sudo git -C "${DRILL}" show <an old commit>:config-backup/ips.yaml \
       > /tmp/old-ips.yaml
   docker compose run --rm --no-deps \
       -v /tmp/old-ips.yaml:/restore/ips.yaml:ro app \
       python -m deltadewa.ips_config --check --strict /restore/ips.yaml
   ```

   **Expect this to fail** against any revision predating #297 — that is
   the drill working, not a bug. A commit against `crash_scenario_pct`
   still not required, or a schema old enough to predate #384, is the
   easiest one to reach for. If step 5 unexpectedly passes, the schema
   hasn't actually changed since that snapshot — nothing further to do.
   If it fails, that is exactly §7.2's scenario — read it now, before a
   real recovery does.

6. **Record the run** in the private ops doc: date, the backup commit
   sha from step 1, the `app_version` from step 2, and the outcome of
   steps 4 and 5. Then discard the scratch clone:

   ```bash
   # ${DRILL}/.git is root-owned (the sudo clone in step 1), same as the
   # real exports/.git (§10's Ownership note) — needs sudo to remove.
   # /tmp/old-ips.yaml was written by the shell's own `>` redirect in
   # step 5, before sudo ever ran, so it's deploy-owned and needs none.
   sudo rm -rf "${DRILL}"
   rm -f /tmp/old-ips.yaml
   ```

### 7.2. If the restored policy won't load

This is the actual recovery scenario for anything but the newest backup
— not a fallback path, the expected one. `--check`'s error names exactly
one problem per run; work through it rather than guessing:

1. **Prefer time-travel over hand-repair.** Check out the tag
   `MANIFEST.json`'s `app_version` names (`git checkout v<version>`, per
   step 2b above) rather than the latest tag. A policy file always loads
   on the version it was captured under — this gets the program running
   exactly as it was. Only fall back to the steps below if that tag is
   genuinely unavailable (a corrupted/incomplete checkout, or a version
   old enough it predates something else you need).
2. **Never seed a live file from `config/ips.example.yaml`.** It carries
   `EXAMPLE VALUE` placeholders (#249/#257) — booting on it runs the
   program on numbers that are not this program's, and nothing in the
   app says so. Keep the restored file as the source of truth throughout.
3. **Add only the fields the error names, one at a time, re-running
   `--check --strict` after each.** For a genuinely new required field
   (#297/#344-class), there is no correct value to invent — mark it
   plainly and move on:

   ```yaml
   rally_monitor_pct: 5.0  # PROVISIONAL — restored 2026-09-02, needs owner review
   ```

   Validate each edit against the already-built `app` image (from step 3
   above) without rebuilding for every field — bind-mount the host file
   in read-only, the same pattern §7.1's drill uses, rather than
   `docker compose run --rm app python -m deltadewa.ips_config --check
   config/ips.yaml`, which would only ever see the image's *baked-in*
   copy, not this in-progress edit:

   ```bash
   docker compose run --rm --no-deps \
       -v "$(pwd)/config/ips.yaml:/restore/ips.yaml:ro" app \
       python -m deltadewa.ips_config --check --strict /restore/ips.yaml
   ```

   Only once this reports no warnings does a real rebuild-and-cutover
   (step 5 below) become worth doing.

4. **Once it loads, resolve every warning `--strict` reported** — not
   just the load failure:
   - A **defaulted section** (silently running on this code's built-in
     defaults) is a decision to make explicitly, not leave implicit —
     write in your own numbers, or knowingly accept the code defaults
     and remove the ambiguity by saying so in a comment.
   - An **unrecognised key** most often means one of two things, and
     only a human can tell which: it's genuinely retired (delete it —
     e.g. #384's `strike_drift_max_otm_pct`/`strike_drift_review_fraction`,
     which read as policy and do nothing), or it was **renamed** and the
     checker is reporting the old and new names as two separate,
     unrelated facts (a missing field plus an unrecognised one). 4.2
     renamed `triggers.roll_time_months` →
     `triggers.roll_at_months_remaining`,
     `triggers.delta_drift_warn_pct`/`_action_pct` →
     `triggers.delta_ratio_deviation_warn_pct`/`_action_pct`. For a
     rename, carry the OLD value across under the NEW name — never
     substitute the example's placeholder for a value you actually have.
5. **Rebuild and re-run §4's pre-flight**, then confirm `/health` shows
   both `boot_wiring.ips_loaded` and no defaulted/unrecognised warnings
   you didn't knowingly accept.
6. **Every value tagged PROVISIONAL is an open policy decision, not a
   closed recovery step.** File it (an issue, or however this program
   normally tracks open decisions) so it doesn't quietly stay a guess.
   A restore cannot recover a policy value that was never written under
   the new schema — it can only get you to a short, named list of
   decisions instead of a blank page. That is the honest ceiling here.

## 8. What lives where

- **`exports/`** — the only stateful directory. Bind-mounted (not a named
  volume, so `ops/backup-exports.sh` can read it directly off the host
  filesystem — see `compose.yaml`). Contains `program_state.json` (the
  live portfolio + IPS state), `exports/marketdata-cache/` (the warmed
  CBOE/FRED cache both `app` and `jobs` share via `DELTADEWA_CACHE_DIR` —
  see `docs/market-data.md` for which readings live in it and which
  pricing inputs are hand-entered and never refresh),
  `exports/reports/weekly/` (digest + snapshot history),
  `exports/config-backup/` (see below), and any autosaves.
- **`exports/config-backup/`** — a nightly copy of `config/ips.yaml` and
  a small manifest (`ips.yaml`, `MANIFEST.json`: `sha256`, `app_version`,
  `policy_changed_at`), staged by `ops/backup-exports.sh` on every run
  (#301). This is a **copy for recovery, not a live source** — the app
  never reads it; it only exists so the offsite push carries the
  program's real policy, not just its portfolio state. `config/ips.yaml`
  itself is baked into the image at build time (§4/§5), never
  bind-mounted, so before this it was reachable from nowhere the backup
  cron could see. **Policy travels in this backup; secrets do not** — see
  §10's "Why `.env` stays out of the backup" for the split and the
  reasoning; SECURITY.md has the full argument for why that split is
  safe for this specific private remote.
- **Everything else** — code, the image itself — is rebuildable from
  `git clone` + `docker compose build`. `config/ips.yaml` is the one
  exception: it's gitignored (#245), so a plain `git clone` does *not*
  bring it back — see §7's recovery steps and `exports/config-backup/`
  above for how it actually gets restored.
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
  `REPORT_EMAIL_TO`, `REPORT_EMAIL_FROM`, `REPORT_EMAIL_FROM_NAME`
  (optional, #319 — a friendlier digest From display name; see below),
  `FRED_API_KEY` (reserved, safe to leave blank),
  `REFRESH_HEARTBEAT_URL`, `DIGEST_HEARTBEAT_URL`. Read into the `jobs`
  container via `env_file: .env`; the six required-for-email vars (not
  `REPORT_EMAIL_FROM_NAME`, which is cosmetic-only) are also declared
  `${VAR:?...}` in `compose.yaml` so a `docker compose run jobs ...`
  fails immediately, at the command line, if `.env` was never populated
  — not three months later inside a Python traceback.

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
  production access. `REPORT_EMAIL_FROM_NAME` (#319, optional) sets a
  friendlier display name on the digest's From header — e.g. "The Smith
  Family Hedge" instead of a raw relay-assigned address — without
  changing `REPORT_EMAIL_FROM`'s actual sending address, which still
  must stay a verified sender at the relay. Defaults to "Weekly Hedge
  Digest" if left unset.

  **Why `.env` stays out of the backup, and where its recovery copy
  actually lives (#301).** `config/ips.yaml` rides the nightly offsite
  push (`exports/config-backup/`, §8) — it's policy, not a secret, and
  #245's own remediation already established that distinction for this
  program. `.env` is different in kind, not just in sensitivity: every
  value in it is a live credential, and the offsite backup is
  **unencrypted** (`age` is a deliberate, not-yet-built follow-up — see
  §8's note and `ops/backup-exports.sh`'s own header). Putting a
  credential into a plaintext backup is an access loss, not a
  confidentiality loss the way a policy number leaking would be — see
  `SECURITY.md`'s "Why the offsite backup carries policy but not
  secrets" for the full argument, including why this reasoning is
  *specific to this private remote* and doesn't loosen anything about
  the public repo. So `.env`'s only recovery copy is a plain copy kept
  current in **the private ops doc** (§14's quarterly review is what
  keeps it from going stale) — there is no automated backup for it, on
  purpose. Recreating it on a new droplet is a manual step in §7.
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

**Market-data refresh exit codes** — a manual `echo $?` after the refresh
command above is a documented diagnosis, not a guess:

|Exit|Meaning|Files/cache written?|Heartbeat pinged?|
|---|---|---|---|
|`0`|Every series refreshed live and read back through the app's own path (#377)|Data cache (every series) + refresh manifest (#378)|Yes|
|`1`|Some series refreshed+verified live, some did not (partial — routine for FRED's VIXCLS lag)|Data cache (the series that succeeded) + refresh manifest|Yes|
|`2`|No series fetched live at all (a fetch failure)|No data cache writes this run — refresh manifest still written, recording an empty series list|No|
|`3`|At least one series fetched live, but none of it reads back through the app's own read path (#377, a write-readability failure — distinct from exit 2: the network worked, the write didn't land somewhere this process's own read path can see)|Data cache write happened but couldn't be confirmed readable + refresh manifest|No|

See `deltadewa/marketdata/refresh.py`'s module docstring for the
authoritative version of this table.

**Weekly digest exit codes** — a manual `echo $?` after the command above
is a documented diagnosis, not a guess:

|Exit|Meaning|Files written?|Heartbeat pinged?|
|---|---|---|---|
|`0`|Sent (or, without `--send-email`, built and written)|md/html/snapshot|Yes — the *only* outcome that pings `DIGEST_HEARTBEAT_URL`|
|`1`|Refused — no IPS policy, or an empty book|No|No|
|`2`|Built and written, but `--send-email` delivery failed (missing/invalid env var, or the SMTP relay rejected it)|md/html/snapshot|No|
|`3`|Build itself failed (#364) — an input this module does not control raised partway through (provider outage, a repricing edge case)|**No — not even a partial one**, so next week's digest still compares against last week's real snapshot|No. With `--send-email`, a best-effort plain-language failure alert is sent instead (subject `Weekly Hedge Digest — FAILED to build (<date>)`)|

See `deltadewa/reporting/weekly_report.py`'s `main()` docstring for the
authoritative version of this table.

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

# The app's own view of data freshness AND boot-wiring health (#309)
curl http://<tailscale-ip>:8050/health
```

**Read past `"status": "ok"` — check `boot_wiring` too (#309).** `/health`
asserting `state_loaded`/`market_data` presence alone missed #295 for
weeks: `ips_config` and the portfolio object both existed, so a presence
check passed while `default_exercise_style` was never actually wired and
two panels rendered dead. `boot_wiring` is the fix — seven explicit,
post-boot assertions on the objects the app actually built (see
`deltadewa/app/health_checks.py` for the full list and why these seven):

```json
"status": "ok",
"boot_wiring": {
  "ips_loaded": {"ok": true, "detail": "ips.yaml loaded"},
  "ips_sections_configured": {"ok": true, "detail": "...", "value": []},
  "exercise_style_wired": {"ok": true, "detail": "default_exercise_style=EUROPEAN"},
  "state_persisted": {"ok": true, "detail": "no unsaved changes"},
  "state_file_undisturbed": {"ok": true, "detail": "..."},
  "cache_dir_writable": {"ok": true, "detail": "...", "value": "/app/exports/marketdata-cache"},
  "cache_manifest_matches": {"ok": true, "detail": "...", "value": {"recorded_cache_dir": "/app/exports/marketdata-cache", "written_at": "...", "resolved_cache_dir": "/app/exports/marketdata-cache"}}
}
```

- **`status` can read `"degraded"` while HTTP still returns 200** —
  `/health` stays a liveness probe (never restart-loop the container over
  it); `degraded` means *investigate*, not *the app is down*.
- **`ips_sections_configured`'s `value` lists which of
  `market_environment`/`sizing`/`vega` fell back to code defaults.** This
  one never turns `status` to `degraded` on its own — a program
  deliberately content with the defaults is legitimate — but a non-empty
  list here after you edited `config/ips.yaml` almost always means a typo
  in that section's key name (the section silently reads as absent
  rather than raising).
- **`exercise_style_wired: false`** means `add_position()` will raise for
  any leg with no explicit `exercise_style` — check `pricing.
  exercise_style` is actually present in `config/ips.yaml` (§5).
- **`state_file_undisturbed: false`** is §5's importer notice, restated
  here: `exports/program_state.json` changed since this worker last
  loaded or saved it (almost always the CLI importer having just run) —
  restart to pick it up.
- **`cache_dir_writable: false`** is #300's finding, made checkable
  directly: the `value` field names the exact resolved path this worker
  tried to write — diff it against `docker compose run --rm jobs env |
  grep CACHE_DIR` if `app` and `jobs` might have resolved
  `DELTADEWA_CACHE_DIR` differently.
- **`cache_manifest_matches: false`** is #377/#378's own cross-check: it
  reads the manifest the refresh job wrote on its last run and compares
  the `cache_dir` recorded there against what this app process resolved.
  `value.recorded_cache_dir: null` means no manifest was found at all —
  either the refresh job hasn't run against this `cache_dir` yet, or it
  resolved a different `DELTADEWA_CACHE_DIR` than this app process did
  (the check can't tell the two apart); a non-null `recorded_cache_dir`
  that differs from `resolved_cache_dir` means `app` and `jobs` are
  actually resolving `DELTADEWA_CACHE_DIR` to different paths — diff it
  the same way as `cache_dir_writable` above. `compose.yaml` hardcodes
  both services' `DELTADEWA_CACHE_DIR` identically today, so this is a
  detector for future drift, not a live failure mode as shipped.

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
  entry itself stopped firing, CBOE/FRED have been unreachable for longer
  than a routine early-morning lag (exit 2), or every series fetched live
  but none of it read back through the app's own read path (exit 3,
  #377 — a write-readability failure, distinct from a fetch failure).
  Check `~/deltadewa/logs/refresh.log`, then run §11's refresh command by
  hand and read its exit code (`echo $?`; see §11's exit-code table:
  0/1 partial-or-full success and read-back-verified, 2 total fetch
  failure, 3 fetched but unreadable back through this process's own read
  path).
- **DIGEST overdue**: the weekly email did not send. This is the
  dangerous one — an overdue digest reads exactly like "a quiet week, no
  news," which is precisely why the design pings only on a *confirmed*
  send (`deltadewa/reporting/weekly_report.py`). **The contract is exact:
  `DIGEST_HEARTBEAT_URL` is pinged on exit `0` only** — see §11's exit-
  code table. Refused (`1`), built-not-sent (`2`), and build-failed (`3`,
  #364) all leave it un-pinged on purpose: a build-failed run sends its
  own best-effort plain-language failure alert email when `--send-email`
  is set, but that alert is a *separate* signal from the heartbeat, never
  a substitute for it — if SMTP itself is the fault, the alert never
  arrives either. Check `~/deltadewa/logs/weekly_report.log` for a
  `--send-email` failure (missing/invalid env var, or the SMTP relay
  rejecting the credentials/quota) or a build failure (exit `3`), then
  re-run §11's send command by hand.
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

## 14. Quarterly review — keeping recovery possible

The heartbeats (§13) tell you the backup *ran*. None of them tell you
whether what it carries would actually get the program back on its feet
— that's a colder failure, only visible when you go looking, which is
exactly why it belongs on a calendar rather than waiting to be noticed.
About five minutes, quarterly:

1. **The `.env` copy in the private ops doc still matches the live
   file** — at minimum, the same set of keys; ideally, the same values.
   It drifts silently whenever a credential is rotated or `.env.example`
   gains a new var and nobody remembers the private doc also needs it.
2. **Run §7.1's recovery drill, steps 1–4** (~5 minutes): clone the
   backup, confirm the policy snapshot's checksum matches the live file,
   confirm `program_state.json`'s provenance, confirm today's policy
   loads clean under `--strict` on the currently-deployed version.
3. **Run §7.1's step 5 (the version-skewed restore) too — and also,
   separately, right after any release that adds or renames a required
   IPS key**, not only on the quarterly cadence. That is the moment an
   old backup actually goes stale; waiting for the next quarter to find
   out means carrying an unverified backup for as long as three months.
4. **`MANIFEST.json`'s `app_version` matches what's actually running.**
   A mismatch here (without a version bump in between) would mean
   `stage_policy_snapshot()` stopped reading `pyproject.toml` correctly
   — worth a one-line sanity check, not a full investigation, since step
   2 already exercises the same manifest.

Record each run in the private ops doc (date, backup commit sha, pass/
fail per step) — the same log §7.1 step 6 asks for after a drill.
