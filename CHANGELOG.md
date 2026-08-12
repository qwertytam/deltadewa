# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project uses [Semantic Versioning](https://semver.org/).

This file starts tracking from `v0.6.0`. Earlier history (`v0.3.0` through
`v0.5.0`) predates the changelog (#185 item 5) and is not backfilled here —
see the `v*` git tags and their PR history for that record, rather than a
reconstruction risking factual drift.

## [Unreleased]

Changes merged to `main` since the `v0.6.0` tag, not yet in a tagged
release:

- `deltadewa/clock.py`: a single program trading-day source
  (`program_trading_date`, `days_between`) replacing ad hoc
  `datetime.now()`/timestamp-subtraction day counts across the package —
  fixes a day-count floor that crossed roll/expiry triggers a day early
  and a UTC clock that rolled the book's valuation date at 20:00 ET (#182).
- Both Jupyter notebooks, `example.py`, `deltadewa/widgets/health_dashboard.py`
  (the gauge wall), and the `nbstripout`/`nbqa`/`jupytext` toolchain
  retired — `/monitor` and `/design` cover what they used to (Stage 4.3,
  #242).
- `examples/ips/ips_default.yaml` sanitized of live-looking values; a
  repo-wide exposure re-audit (#249).
- Ops hardening: non-root container user with self-healing `exports/`
  ownership, `BACKUP_REMOTE`/`HEARTBEAT_URL` precedence and self-healing,
  log rotation for the deploy-owned stanza, dead-man's-switch heartbeat
  fixes (#243, #244, #254, #255, #256).
- Convexity-cliff panel ported to `/design` (#247).

## [0.6.0] - 2026-08-10

- `reporting/weekly_report.py`: stop the report contradicting the digest
  it's embedded in (#234).
- Docker: non-root container user, entrypoint ownership, and the backup
  dead-man's-switch fix (#235, #238).
- Market-data refresh job: always fetch live and stop counting cache hits
  as refreshes (#239).

[Unreleased]: https://github.com/qwertytam/deltadewa/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/qwertytam/deltadewa/releases/tag/v0.6.0
