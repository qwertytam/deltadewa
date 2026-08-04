"""CLI: load a portfolio YAML into the running app's shared state.

Usage::

    python -m deltadewa.app.import_portfolio <path-to-portfolio.yaml>

Stopgap until the M2.5 position editor exists — today the only supported
way to get positions into ``exports/program_state.json`` short of hand-
editing it. Writes through ``ProgramState.import_portfolio``, so it
inherits that method's atomic write and its refusal to leave a partial
state file behind on a bad import.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from deltadewa.state import STATE_FILENAME, ProgramState

_DEFAULT_EXPORT_DIR = Path("exports")
_DEFAULT_IPS_PATH = Path("config/ips.yaml")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse CLI arguments for the importer."""
    parser = argparse.ArgumentParser(
        description=(
            "Load a portfolio YAML into the app's shared program state."
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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Import a portfolio YAML into ``<export-dir>/program_state.json``.

    Returns:
        Process exit code: ``0`` on success, ``1`` if refused because a
        state file already exists and ``--force`` was not given.

    """
    args = _parse_args(argv)
    state = ProgramState.load(args.export_dir, ips_path=args.ips_path)

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
