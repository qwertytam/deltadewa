#!/usr/bin/env bash
# ops/backup-exports.sh — nightly offsite push of exports/ to a private
# git remote. Run from root's cron (see docs/RUNBOOK.md "Cron setup").
#
# The remote itself is never named or defaulted here — see BACKUP_REMOTE
# below (#243). Which host/account/repo this actually points at is an
# operational value, not something this public repo should carry; it
# lives in the private ops doc and on the droplet only.
#
# The push credential is host-side only — an SSH deploy key at
# /root/.ssh/backup_deploy_key (0600), referenced via a ~/.ssh/config Host
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
#   DELTADEWA_REPO_DIR — the app repo checkout (default below)
#   DELTADEWA_BACKUP_ENV_FILE — path to the optional token-alternative
#                   file described below (default below)
#
# Required, no default (#243 — a hardcoded remote here would be exactly
# the kind of leak #245 fixed for config/ips.yaml):
#   BACKUP_REMOTE — the full destination git remote URL (an ~/.ssh/config
#                   Host alias form like `<alias>:<repo>.git`, or a full
#                   https:// URL). Never read from .env (same host-only
#                   boundary as BACKUP_HEARTBEAT_URL — set it in root's
#                   crontab or /etc/deltadewa/backup.env, see RUNBOOK.md
#                   §10 — both are sourced/checked below before use).
#                   Reconciled against exports/.git's actual origin on
#                   every run, not just at first init — see the
#                   remote-reconcile block below. If BOTH the crontab
#                   environment and backup.env set this (or
#                   BACKUP_HEARTBEAT_URL), the environment wins (#253) —
#                   a plain `source` has no notion of "already set", it
#                   just assigns, so a bare `if [ -f ... ]; then source
#                   ...; fi` used to let the file silently clobber an
#                   operator's explicit `BACKUP_REMOTE=... ./backup-
#                   exports.sh`. See the pre-source capture below.
set -euo pipefail

REPO_DIR="${DELTADEWA_REPO_DIR:-/home/deploy/deltadewa}"
EXPORTS_DIR="${REPO_DIR}/exports"
BACKUP_ENV_FILE="${DELTADEWA_BACKUP_ENV_FILE:-/etc/deltadewa/backup.env}"

# Optional token-based alternative to the SSH deploy key described above —
# root-owned 0600, NEVER .env (compose reads that and would expose it to
# containers). Sourced first, before BACKUP_REMOTE is required below, so
# a deploy that sets BACKUP_REMOTE (and/or BACKUP_HEARTBEAT_URL) only in
# this file rather than in root's crontab still works.
#
# Environment beats file (#253): capture whatever the environment already
# had *before* sourcing, then restore it afterwards if it was non-empty —
# `source` would otherwise let the file overwrite an explicitly-set
# `BACKUP_REMOTE=... ./backup-exports.sh` silently.
if [ -f "${BACKUP_ENV_FILE}" ]; then
    PRE_SOURCE_BACKUP_REMOTE="${BACKUP_REMOTE:-}"
    PRE_SOURCE_BACKUP_HEARTBEAT_URL="${BACKUP_HEARTBEAT_URL:-}"

    # shellcheck disable=SC1090
    source "${BACKUP_ENV_FILE}"

    if [ -n "${PRE_SOURCE_BACKUP_REMOTE}" ]; then
        BACKUP_REMOTE="${PRE_SOURCE_BACKUP_REMOTE}"
        echo "backup-exports: BACKUP_REMOTE from environment (overriding backup.env)"
    elif [ -n "${BACKUP_REMOTE:-}" ]; then
        echo "backup-exports: BACKUP_REMOTE from backup.env"
    fi

    if [ -n "${PRE_SOURCE_BACKUP_HEARTBEAT_URL}" ]; then
        BACKUP_HEARTBEAT_URL="${PRE_SOURCE_BACKUP_HEARTBEAT_URL}"
        echo "backup-exports: BACKUP_HEARTBEAT_URL from environment (overriding backup.env)"
    elif [ -n "${BACKUP_HEARTBEAT_URL:-}" ]; then
        echo "backup-exports: BACKUP_HEARTBEAT_URL from backup.env"
    fi
fi

: "${BACKUP_REMOTE:?BACKUP_REMOTE is not set — see docs/RUNBOOK.md §10 (or the private ops doc) for the offsite backup remote URL}"

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
fi

# Reconcile the origin remote on every run, not just at first init — a
# stale/incorrect origin (e.g. left over from a manual restore that used
# a different URL form than BACKUP_REMOTE — see RUNBOOK.md §10's
# Remote-URL note) used to go unnoticed and unfixed indefinitely (#243).
# Same `if` exemption from `set -e` as ping_heartbeat() above: a failed
# `git remote get-url` (no remote configured yet) is the expected
# first-init case, not an error.
if git remote get-url origin >/dev/null 2>&1; then
    CURRENT_REMOTE="$(git remote get-url origin)"
    if [ "${CURRENT_REMOTE}" != "${BACKUP_REMOTE}" ]; then
        echo "backup-exports: origin remote changed (${CURRENT_REMOTE} -> ${BACKUP_REMOTE}), updating" >&2
        git remote set-url origin "${BACKUP_REMOTE}"
    fi
else
    git remote add origin "${BACKUP_REMOTE}"
fi

# Set on every run, not just init — a restored `git clone` (RUNBOOK §7)
# carries no local identity, and a commit without one fails on a box with
# no global git config either.
git config user.email "deltadewa-backup@localhost"
git config user.name "deltadewa-backup"

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
