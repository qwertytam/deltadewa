"""CLI: load a portfolio YAML into the shared program state *file*.

Usage::

    python -m deltadewa.app.import_portfolio <path-to-portfolio.yaml>

Stopgap until the M2.5 position editor exists — today the only supported
way to get positions into ``exports/program_state.json`` short of hand-
editing it. Writes through ``ProgramState.import_portfolio``, so it
inherits that method's atomic write and its refusal to leave a partial
state file behind on a bad import.

**This does not reach the running app (#355).** ``docker compose exec``
starts a fresh process inside the container; it never touches the live
gunicorn worker's Python heap. This CLI builds its own ``ProgramState``,
writes ``exports/program_state.json``, and exits — the worker keeps
serving whatever it already had in memory until it is restarted. See
``deltadewa/state.py``'s "What this module still does not do (#355)" for
why that gap is not closed with a reload here. After a successful import
this prints what it wrote, and — unless ``--no-live-check`` is passed —
best-effort probes the running worker's own ``/health`` to make that gap
concrete rather than theoretical: which process the worker thinks last
wrote the file, and whether that matches this run.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import requests

from deltadewa.analysis.crash_repricing import describe_expired_legs, is_expired
from deltadewa.analysis.portfolio_shape import classify_portfolio_shape
from deltadewa.state import STATE_FILENAME, ProgramState

_DEFAULT_EXPORT_DIR = Path("exports")
_DEFAULT_IPS_PATH = Path("config/ips.yaml")
_NOTICE_RULE_WIDTH = 70
_WRITER_LABEL = "import_portfolio_cli"
_HEALTH_URL_ENV_VAR = "DELTADEWA_HEALTH_URL"
_DEFAULT_HEALTH_URL = "http://127.0.0.1:8050/health"
_HEALTH_REQUEST_TIMEOUT_SECONDS = 5


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for the importer."""
    parser = argparse.ArgumentParser(
        description=(
            "Load a portfolio YAML into the app's shared state file. "
            "Does NOT reach a running app worker directly — see the "
            "module docstring."
        ),
    )
    parser.add_argument(
        "portfolio_path",
        type=Path,
        help="Path to a portfolio YAML file (see examples/portfolios/).",
    )
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=_DEFAULT_EXPORT_DIR,
        help=(
            "Directory holding the shared state file "
            f"(default: {_DEFAULT_EXPORT_DIR})."
        ),
    )
    parser.add_argument(
        "--ips-path",
        type=Path,
        default=_DEFAULT_IPS_PATH,
        help=(
            "Path to the hedge program policy file, used for the default "
            f"exercise style (default: {_DEFAULT_IPS_PATH})."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite an existing state file. Without this flag, the "
            "import is refused if the export directory already holds a "
            "state file, so it can never be silently clobbered."
        ),
    )
    parser.add_argument(
        "--app-url",
        default=None,
        help=(
            "Base health-check URL of the running app worker, used only "
            "for the post-import live-divergence notice (default: "
            f"${_HEALTH_URL_ENV_VAR} if set, else {_DEFAULT_HEALTH_URL} — "
            "correct when run via `docker compose exec app ...`, since "
            "that shares the app container's network namespace)."
        ),
    )
    parser.add_argument(
        "--no-live-check",
        action="store_true",
        help=(
            "Skip the post-import probe of the running worker's /health. "
            "The import itself is unaffected either way — this only "
            "controls whether the CLI tries to report on staleness."
        ),
    )
    return parser.parse_args(argv)


def _warn_if_non_conforming(state: ProgramState) -> None:
    """Print a loud, un-scrollable-past warning for a non-conforming book.

    Restores #261: this ran once per session as a notebook cell
    (``classify_portfolio_shape``, commit ``73cf8da``) before Stage 4.3
    deleted the notebooks without a replacement. A non-conforming book is a
    warning, not a failure — the operator may have imported it
    deliberately — so this never affects the exit code; it just makes sure
    the warning can't be missed in a ``docker exec`` log.
    """
    shape = classify_portfolio_shape(state.portfolio)
    if shape.is_conforming:
        return
    rule = "!" * _NOTICE_RULE_WIDTH
    print(rule, file=sys.stderr)
    print(
        f"WARNING: non-conforming portfolio shape ({shape.reason})",
        file=sys.stderr,
    )
    print(shape.notice, file=sys.stderr)
    print(rule, file=sys.stderr)


def _warn_if_expired_legs(state: ProgramState) -> None:
    """Print an advisory naming any leg already expired at import (#365).

    ``add_position()`` refuses an expired maturity by *default*, but the
    importers pass ``reject_expired=False`` deliberately — a real
    historical or autosaved book can legitimately hold a leg that expired
    after being added. That means an import can silently bring in a leg
    with zero remaining runway; this surfaces it instead, on the same
    channel as :func:`_warn_if_non_conforming` and with the same
    never-affects-the-exit-code posture.
    """
    expired = [
        position
        for position in state.portfolio.positions
        if is_expired(position, valuation_date=state.portfolio.valuation_date)
    ]
    if not expired:
        return
    rule = "!" * _NOTICE_RULE_WIDTH
    print(rule, file=sys.stderr)
    print(
        f"WARNING: {len(expired)} already-expired position(s) in the "
        "imported book:",
        file=sys.stderr,
    )
    for label in describe_expired_legs(expired):
        print(f"  - {label}", file=sys.stderr)
    print(rule, file=sys.stderr)


def _fetch_live_health(app_url: str) -> dict[str, Any] | None:
    """Best-effort GET of the running worker's ``/health``.

    Never raises — mirrors ``deltadewa.heartbeat.ping``'s contract: a
    monitoring hiccup here must not fail the import that already
    succeeded. Returns ``None`` on any connection error, timeout, or
    non-2xx response.
    """
    try:
        response = requests.get(
            app_url,
            timeout=_HEALTH_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    try:
        payload: dict[str, Any] = response.json()
    except ValueError:
        return None
    return payload


def _report_live_divergence(state: ProgramState, app_url: str) -> None:
    """Print what the just-written file holds vs. what the live worker does.

    This never fails the import and never changes the exit code — it is
    informational only, printed after the write already succeeded. The
    two-process split means the live worker (if any) almost never already
    reflects this write; the point is to make that concrete instead of
    letting the importer's own "Loaded N position(s)..." success message
    read as if it reached the running app.
    """
    written_by = state.written_by
    loaded_at = state.loaded_at
    print(
        f"\nJust wrote {state.state_path} "
        f"(written_by={written_by!r}, loaded_at={loaded_at!r}).",
    )

    health = _fetch_live_health(app_url)
    if health is None:
        print(
            f"Could not reach a running app worker at {app_url} to "
            "confirm whether it has this. If the app is running, it has "
            "NOT picked this up — restart it: "
            "docker compose restart app",
            file=sys.stderr,
        )
        return

    live_state = health.get("state") or {}
    live_written_by = live_state.get("written_by")
    live_loaded_at = live_state.get("loaded_at")

    if (
        health.get("state_loaded")
        and live_written_by == written_by
        and (live_loaded_at == loaded_at)
    ):
        # Only possible if the worker independently loaded from the same
        # file at the same instant this process did (e.g. it restarted
        # between the write and this probe) — not something a caller
        # should rely on, but worth saying plainly if it happens.
        print(
            "The running app worker's /health now reports this same "
            "write — it already reflects the import.",
        )
        return

    print(
        "The running app worker has NOT picked this up yet — its "
        f"/health reports written_by={live_written_by!r}, "
        f"loaded_at={live_loaded_at!r}, which does not match what was "
        "just written above. Restart it to apply this import: "
        "docker compose restart app",
        file=sys.stderr,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Import a portfolio YAML into ``<export-dir>/program_state.json``.

    Returns:
        Process exit code: ``0`` on success, ``1`` if refused because a
        state file already exists and ``--force`` was not given.

    """
    args = _parse_args(argv)
    state = ProgramState.load(
        args.export_dir,
        ips_path=args.ips_path,
        writer_label=_WRITER_LABEL,
    )

    if state.loaded_from is not None and not args.force:
        print(
            f"{state.loaded_from} already holds portfolio state; "
            "pass --force to overwrite it.",
            file=sys.stderr,
        )
        return 1

    style = (
        state.ips_config.pricing.exercise_style
        if state.ips_config is not None
        else None
    )

    print(f"Reading portfolio from {args.portfolio_path}")
    state.import_portfolio(
        args.portfolio_path,
        default_exercise_style=style,
        confirm=True,
    )

    dest = args.export_dir / STATE_FILENAME
    print(
        f"Loaded {len(state.portfolio.positions)} position(s) from "
        f"{args.portfolio_path} into {dest}",
    )
    _warn_if_non_conforming(state)
    _warn_if_expired_legs(state)

    if not args.no_live_check:
        app_url = (
            args.app_url
            or os.environ.get(_HEALTH_URL_ENV_VAR)
            or _DEFAULT_HEALTH_URL
        )
        _report_live_divergence(state, app_url)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
