#!/usr/bin/env bash
# ops/backup-exports.sh — nightly offsite push of exports/ to a private
# Codeberg repo. Run from root's cron (see docs/RUNBOOK.md "Cron setup").
#
# The push credential is host-side only — an SSH deploy key at
# /root/.ssh/codeberg_backup (0600), referenced via a ~/.ssh/config Host
# alias — and never enters a container. compose.yaml's `env_file: .env`
# is read by the `jobs` container; a credential placed in .env would be
# exposed to every job command run through it. This script and its key
# live entirely outside that boundary, on the host, run by root.
#
# `exports/` is treated as its own standalone git repo, nested inside the
# app repo's already-fully-gitignored exports/ directory — no submodule
# conflict, since the parent repo never walks into an ignored path.
# exports/marketdata-cache/ (a few KB of JSON) is backed up along with
# everything else in exports/ — on a fresh box after a restore, that
# means the app comes up STALE-with-numbers rather than UNAVAILABLE.
#
# `age` encryption is deliberately deferred: a backup you cannot decrypt
# is worse than one you can. Private repo now; `age` is a follow-up that
# needs an explicit key-escrow step, not something to add silently later.
#
# Exit 0, quietly, when there is nothing new to commit — that is the
# normal nightly state, not a "didn't run." Any git failure (init, add,
# commit, push) is fatal via `set -e` and must be treated as a backup
# outage, not silently retried.
#
# Pings BACKUP_HEARTBEAT_URL (healthchecks.io-compatible) on both success
# paths — a real push and a clean no-op alike — never on a failure. See
# ping_heartbeat() below and docs/RUNBOOK.md §13.
#
# Overridable for testing (and for a non-default host layout) via env:
#   DELTADEWA_REPO_DIR        — the app repo checkout (default below)
#   DELTADEWA_BACKUP_REMOTE   — the ~/.ssh/config Host alias for Codeberg
#   DELTADEWA_BACKUP_REMOTE_URL — full remote URL override, bypassing the
#                                 alias entirely (used by the test suite
#                                 to point at a local bare repo — git push
#                                 mechanics don't care that it isn't SSH)
set -euo pipefail

REPO_DIR="${DELTADEWA_REPO_DIR:-/home/deploy/deltadewa}"
REMOTE_ALIAS="${DELTADEWA_BACKUP_REMOTE:-codeberg-backup}"
DEFAULT_REMOTE_URL="${REMOTE_ALIAS}:deploy_deltadewa-exports-backup.git"
REMOTE_URL="${DELTADEWA_BACKUP_REMOTE_URL:-${DEFAULT_REMOTE_URL}}"
EXPORTS_DIR="${REPO_DIR}/exports"

# Dead-man's-switch ping (healthchecks.io-compatible), the bash-side
# equivalent of deltadewa/heartbeat.py's ping() — this cron runs on the
# host, outside any Python venv, so it can't reuse that module directly,
# but the contract is the same: never fail the job it's reporting on.
# BACKUP_HEARTBEAT_URL is deliberately NOT read from .env (see
# .env.example's entry for it) — set it in root's crontab env or
# /etc/deltadewa/backup.env instead (RUNBOOK §9/§10).
ping_heartbeat() {
    if [ -z "${BACKUP_HEARTBEAT_URL:-}" ]; then
        echo "backup-exports: BACKUP_HEARTBEAT_URL not configured, skipping heartbeat ping"
        return 0
    fi
    # `if ! curl ...` is exempt from `set -e` (a command that's the
    # condition of an `if` never triggers it), so a ping hiccup logs and
    # falls through rather than aborting a backup that actually succeeded.
    if ! curl -fsS --max-time 10 -o /dev/null "${BACKUP_HEARTBEAT_URL}"; then
        echo "backup-exports: heartbeat ping failed" >&2
    fi
    return 0
}

cd "${EXPORTS_DIR}"

if [ ! -d .git ]; then
    echo "backup-exports: initializing exports/ as its own git repo" >&2
    git init -q
    git checkout -q -b main
    git remote add origin "${REMOTE_URL}"
fi

# Set on every run, not just init — a restored `git clone` (RUNBOOK §7)
# carries no local identity, and a commit without one fails on a box with
# no global git config either.
git config user.email "deltadewa-backup@localhost"
git config user.name "deltadewa-backup"

# Optional token-based alternative to the SSH deploy key above — root-owned
# 0600, NEVER .env (compose reads that and would expose it to containers).
if [ -f /etc/deltadewa/backup.env ]; then
    # shellcheck disable=SC1091
    source /etc/deltadewa/backup.env
fi

git add -A

if [ -z "$(git status --porcelain)" ]; then
    echo "backup-exports: nothing to commit, exports/ unchanged"
    ping_heartbeat
    exit 0
fi

git commit -q -m "backup: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push origin HEAD:main
echo "backup-exports: pushed $(git rev-parse --short HEAD)"
ping_heartbeat
