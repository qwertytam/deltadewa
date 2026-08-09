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
# directive), fixes ownership, then steps down. Runs on every container
# start/restart so it also self-heals after the host's root cron
# (ops/backup-exports.sh) leaves root-owned files under exports/ (e.g.
# .git/ internals) — the app itself never touches those paths, only
# program_state.json, marketdata-cache/, and reports/weekly/, so this is
# enough for the app to keep working even if a scheduling race leaves the
# backup's own files root-owned between restarts. See issue #220.
#
# `runuser` (util-linux, present in python:3.11-slim/Debian — no extra
# package install needed) rather than `gosu`/`su-exec`: neither of those
# ships in this base image, and runuser execs the target command directly
# without needing a login shell for the target user.
set -eu

if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/exports
    chown -R appuser:appuser /app/exports
    exec runuser -u appuser -- "$@"
fi

# Already non-root (shouldn't happen given the image has no USER
# directive, but defensive: never re-chown/re-exec as a different user
# than whatever this process is already running as).
exec "$@"
