# RUNBOOK

One page, copy-pasteable. Written for a fresh clone six months from now with
nothing memorised. Scope: the M2.3 skeleton — a single Dash container on a
DigitalOcean droplet, reachable only over Tailscale. Provisioning (clicking
in DigitalOcean) is manual; everything below the click is a command.

**Stub notice (M2.3, finalised in Phase 3 / M2.6):** sections marked
`[M2.6 TODO]` don't exist yet — no cron, no backup push, no email. Until
then, backups and restarts are manual.

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

## 3. Client setup — what the partner does once

1. Install Tailscale (desktop or mobile — https://tailscale.com/download).
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

`[M2.6 TODO]` Host cron: market-data refresh, monthly report email,
`exports/` backup push — not implemented yet; do these manually until then.

## 5. Recovery — the droplet dies

Target: **under 30 minutes, nothing memorised.**

```bash
# 1. New droplet, repeat section 1 in full, up to (not including) the
#    final `docker compose up -d --build`

# 2. Restore exports/ from the last backup onto the new droplet, into the
#    repo's exports/ directory (the bind-mount source — see §6). Until
#    [M2.6 TODO]'s offsite backup exists, this means: whatever manual copy
#    (scp, USB, etc.) you made of exports/ from the old box.
scp -r old-backup/exports/ deploy@<new-tailscale-ip>:~/deltadewa/exports/

# 3. Bring it up
docker compose up -d --build

# 4. Confirm state actually came back
curl http://<new-tailscale-ip>:8050/health   # state_loaded should be true
```

## 6. What lives where

- **`exports/`** — the only stateful directory. Bind-mounted (not a named
  volume, so a future backup job can read it directly off the host
  filesystem — see `compose.yaml`). Contains `program_state.json`
  (the live portfolio + IPS state) and any autosaves.
- **Everything else** — code, config, the image itself — is rebuildable
  from `git clone` + `docker compose build`. Nothing else on the droplet
  needs to survive a rebuild.

`[M2.6 TODO]` Offsite backup target (private Codeberg repo, optional `age`
encryption) and the cron/push commands for it — not implemented yet.
