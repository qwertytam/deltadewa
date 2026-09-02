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
# exports/config-backup/ips.yaml is a copy of config/ips.yaml, staged by
# stage_policy_snapshot() below (#301) so it rides this same push, remote
# and credential — config/ips.yaml itself is baked into the image at
# build time (Dockerfile COPY), never bind-mounted, so it is otherwise
# unreachable from anywhere this cron or a container could back it up.
# This does NOT change what SECURITY.md's public-repo rule covers: this
# repo's tracked files are untouched, config/ips.yaml stays gitignored,
# and *.example.yaml stays the tracked template. See SECURITY.md's "Why
# the offsite backup carries policy but not secrets" for why pushing
# policy (not .env) to this private remote is a deliberate, bounded
# exception to that rule rather than a loosening of it.
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

# Where a heartbeat-ping failure gets recorded so the weekly digest can
# surface it (#252 — see ping_heartbeat() below). exports/ is the only
# filesystem path both this root cron and the `deploy`-run `jobs`
# container share (compose.yaml bind-mounts only exports/, not the repo
# root), so that's where this has to live despite being cron metadata
# rather than portfolio data; deltadewa.reporting.weekly_report reads it.
BACKUP_HEARTBEAT_STATUS_FILE="${EXPORTS_DIR}/.backup-heartbeat-status.json"

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
# but the contract is the same: never fail the job it's reporting on. A
# ping failure (curl exit, or a non-2xx like 400) stays exit-0 here too —
# flipping that would mean an unrelated monitoring hiccup starts reading
# as a backup outage, which is worse than the thing it's meant to catch.
# BACKUP_HEARTBEAT_URL is deliberately NOT read from .env (see
# .env.example's entry for it) — set it in root's crontab env or
# /etc/deltadewa/backup.env instead (RUNBOOK §9/§10).
#
# "Never fails the job" must not mean "never visible" (#252) — a curl 400
# used to disappear into stderr of a root cron nobody tails, so broken
# monitoring was itself unmonitored. On failure this now also records a
# marker in BACKUP_HEARTBEAT_STATUS_FILE that the weekly digest reads and
# surfaces (deltadewa.reporting.weekly_report); a later successful ping
# clears it, so a one-off blip doesn't alarm forever. See RUNBOOK.md §13.
ping_heartbeat() {
    if [ -z "${BACKUP_HEARTBEAT_URL:-}" ]; then
        echo "backup-exports: BACKUP_HEARTBEAT_URL not configured, skipping heartbeat ping"
        return 0
    fi
    # `if ! curl ...` is exempt from `set -e` (a command that's the
    # condition of an `if` never triggers it), so a ping hiccup logs and
    # falls through rather than aborting a backup that actually succeeded.
    if curl -fsS --max-time 10 -o /dev/null "${BACKUP_HEARTBEAT_URL}"; then
        rm -f "${BACKUP_HEARTBEAT_STATUS_FILE}" || true
    else
        echo "backup-exports: heartbeat ping failed" >&2
        # Best-effort: a failure writing this marker (e.g. a permissions
        # hiccup) must not itself abort a backup that already succeeded,
        # same spirit as the ping failure it's recording.
        printf '{"failed_at": "%s", "url_var": "BACKUP_HEARTBEAT_URL"}\n' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            > "${BACKUP_HEARTBEAT_STATUS_FILE}" 2>/dev/null || true
    fi
    return 0
}

# On the clean-tree (nothing-to-commit) path, verify the remote actually
# has what we think it has before pinging the heartbeat (#252). An
# unchanged working tree only means there's nothing NEW to push — it says
# nothing about whether a PREVIOUS run's push actually landed. Before
# this, every no-op run pinged unconditionally, so a push that silently
# failed to land (and then stopped generating new local changes to flag
# it) could report green indefinitely. Reachability failure and a real
# SHA mismatch are both treated as fatal, not just "skip the ping" — a
# broken remote or an unlanded push is exactly the outage this
# dead-man's-switch exists to catch.
verify_remote_matches_head() {
    local local_head
    local remote_head
    # Declared and assigned separately (not `local x=$(...)`) — bash's
    # `local` swallows the command substitution's own exit status when
    # combined on one line, which would defeat the `if !` check below.
    if ! local_head="$(git rev-parse HEAD 2>/dev/null)"; then
        echo "backup-exports: no commits yet in exports/.git to verify, not pinging heartbeat" >&2
        return 1
    fi
    if ! remote_head="$(git ls-remote --exit-code origin main 2>/dev/null | cut -f1)"; then
        echo "backup-exports: could not reach origin to verify remote HEAD, not pinging heartbeat" >&2
        return 1
    fi
    if [ "${remote_head}" != "${local_head}" ]; then
        echo "backup-exports: remote main (${remote_head}) does not match local HEAD (${local_head}) — an earlier push did not land" >&2
        return 1
    fi
    return 0
}

# #301: stage a copy of config/ips.yaml under exports/config-backup/
# before `git add -A` picks it up below, so the nightly push carries the
# program's real policy alongside its state — see the header comment
# above and SECURITY.md for why that's safe to push to this private
# remote. Content-addressed, not run-timestamped: the manifest this
# writes only changes when the policy's bytes (or the checked-out app
# version) actually change, so an unmodified policy leaves the working
# tree exactly as clean as it was before this existed — the #252
# no-op/remote-verification path above must keep seeing "nothing to
# commit" on an ordinary night.
#
# A missing config/ips.yaml (e.g. a fresh checkout before the operator
# has populated it) warns and marks, but never aborts: this is a backup
# of program_state.json too, and a policy problem must not take that
# down or trip the backup dead-man's-switch — the wrong alarm for the
# wrong condition. The marker is cleared as soon as a real policy file
# is found again, so it doesn't linger past the condition it describes.
POLICY_SRC="${REPO_DIR}/config/ips.yaml"
POLICY_BACKUP_DIR="${EXPORTS_DIR}/config-backup"
POLICY_DEST="${POLICY_BACKUP_DIR}/ips.yaml"
POLICY_MANIFEST="${POLICY_BACKUP_DIR}/MANIFEST.json"
POLICY_MISSING_MARKER="${POLICY_BACKUP_DIR}/POLICY-MISSING.txt"

stage_policy_snapshot() {
    mkdir -p "${POLICY_BACKUP_DIR}"

    if [ ! -f "${POLICY_SRC}" ]; then
        echo "backup-exports: ${POLICY_SRC} not found, config-backup/ not updated this run" >&2
        if [ ! -f "${POLICY_MISSING_MARKER}" ]; then
            printf 'config/ips.yaml was not found on this host as of %s.\nThe policy snapshot in this directory (if any) is from an earlier run and may be stale.\n' \
                "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
                > "${POLICY_MISSING_MARKER}"
        fi
        return 0
    fi
    rm -f "${POLICY_MISSING_MARKER}"

    # sha256sum (GNU coreutils, the droplet's Ubuntu image) or shasum
    # (macOS, used by this suite's own tests) — whichever is present.
    local policy_sha256
    if command -v sha256sum >/dev/null 2>&1; then
        policy_sha256="$(sha256sum "${POLICY_SRC}" | cut -d' ' -f1)"
    elif command -v shasum >/dev/null 2>&1; then
        policy_sha256="$(shasum -a 256 "${POLICY_SRC}" | cut -d' ' -f1)"
    else
        policy_sha256="unavailable"
    fi

    # The checked-out app's own version, read from a plain file — never
    # `git describe`/`git log` against REPO_DIR: that's a `deploy`-owned
    # checkout and this cron runs as root, which is exactly the dubious-
    # ownership trap #237 exists to avoid, from the other direction.
    local app_version="unknown"
    if [ -f "${REPO_DIR}/pyproject.toml" ]; then
        app_version="$(
            sed -n 's/^version *= *"\(.*\)"/\1/p' "${REPO_DIR}/pyproject.toml" \
                | head -1
        )"
        [ -n "${app_version}" ] || app_version="unknown"
    fi

    # policy_changed_at tracks the last run whose sha256 actually
    # differed from the previous manifest — not "last run", which would
    # just repeat today's date every night regardless of whether the
    # policy moved, defeating the point of asking "how stale is this."
    local old_sha256=""
    local policy_changed_at
    if [ -f "${POLICY_MANIFEST}" ]; then
        old_sha256="$(
            sed -n 's/.*"sha256": *"\([^"]*\)".*/\1/p' "${POLICY_MANIFEST}"
        )"
    fi
    if [ "${old_sha256}" = "${policy_sha256}" ] && [ -f "${POLICY_MANIFEST}" ]; then
        policy_changed_at="$(
            sed -n 's/.*"policy_changed_at": *"\([^"]*\)".*/\1/p' "${POLICY_MANIFEST}"
        )"
    else
        policy_changed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    fi

    cp "${POLICY_SRC}" "${POLICY_DEST}"

    # Written to a tmp file and compared before replacing the tracked
    # manifest — see the no-churn note above the function.
    local tmp_manifest
    tmp_manifest="$(mktemp)"
    printf '{\n  "written_by": "backup-exports.sh",\n  "source": "config/ips.yaml",\n  "sha256": "%s",\n  "app_version": "%s",\n  "policy_changed_at": "%s"\n}\n' \
        "${policy_sha256}" "${app_version}" "${policy_changed_at}" \
        > "${tmp_manifest}"
    if ! cmp -s "${tmp_manifest}" "${POLICY_MANIFEST}" 2>/dev/null; then
        mv "${tmp_manifest}" "${POLICY_MANIFEST}"
    else
        rm -f "${tmp_manifest}"
    fi
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

stage_policy_snapshot

git add -A

if [ -z "$(git status --porcelain)" ]; then
    echo "backup-exports: nothing to commit, exports/ unchanged"
    if verify_remote_matches_head; then
        ping_heartbeat
        exit 0
    fi
    exit 1
fi

git commit -q -m "backup: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git push origin HEAD:main
echo "backup-exports: pushed $(git rev-parse --short HEAD)"
ping_heartbeat
