#!/usr/bin/env sh
# docker-entrypoint.sh — chown the bind-mounted exports/ tree, then drop
# from root to the fixed-UID appuser before exec'ing the real command.
#
# Why this runs on every start, not just once: Docker's bind-mount source
# auto-creation (when ./exports doesn't exist yet on the host) happens at
# the daemon level, as root, regardless of which user the container itself
# runs as — so switching the image to a non-root USER alone does not fix
# first-boot ownership, it just makes the app unable to write either. This
# script starts as root (the image's default — see Dockerfile, no USER
# directive), fixes ownership, then steps down. See issue #220.
#
# Ownership invariant (#220 / #237): the app owns its data files
# (program_state.json, marketdata-cache/, reports/weekly/); root owns
# exports/.git — created and pushed by the host's root cron,
# ops/backup-exports.sh — and exports/ itself. Neither side re-owns the
# other's. This used to chown -R the whole tree on every start, which
# recursively re-owned .git (and exports/ itself, since a recursive
# chown includes its own target) to appuser — silently breaking the next
# backup push, since git's dubious-ownership guard (safe.directory,
# default since git 2.35.2) checks ownership of BOTH the working-tree
# top and the gitdir against the invoking euid, and root's cron has no
# heartbeat-independent way to notice a fatal git error in a log file
# nobody's watching. See #237.
#
# So: never chown exports/ itself, never touch anything under .git/.
# appuser instead gets access via the GROUP bit — chgrp (not chown)
# leaves the owner/uid untouched, so it's invisible to git's owner-based
# check — plus the sticky bit, so having group-write doesn't hand
# appuser delete/rename rights over root's .git (the same 1777-style
# pattern /tmp itself uses, scoped down to just these two users).
# Existing children other than .git are chowned to appuser recursively,
# same as before; anything appuser creates fresh directly under
# exports/ is already appuser-owned by construction.
#
# `runuser` (util-linux, present in python:3.11-slim/Debian — no extra
# package install needed) rather than `gosu`/`su-exec`: neither of those
# ships in this base image, and runuser execs the target command directly
# without needing a login shell for the target user.
set -eu

# Overridable for testing — the real path is only writable as root
# inside an actual container, not on a dev machine or in CI. Default
# unchanged.
EXPORTS_DIR="${DELTADEWA_EXPORTS_DIR:-/app/exports}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "${EXPORTS_DIR}"

    chgrp appuser "${EXPORTS_DIR}"
    chmod g+w "${EXPORTS_DIR}"
    chmod +t "${EXPORTS_DIR}"

    find "${EXPORTS_DIR}" -mindepth 1 -maxdepth 1 ! -name .git \
        -exec chown -R appuser:appuser {} +

    exec runuser -u appuser -- "$@"
fi

# Already non-root (shouldn't happen given the image has no USER
# directive, but defensive: never re-chown/re-exec as a different user
# than whatever this process is already running as).
exec "$@"
