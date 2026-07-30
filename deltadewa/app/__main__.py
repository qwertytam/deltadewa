"""Entrypoint: run the Dash app (``python -m deltadewa.app``).

Wires the shared ``ProgramState`` (backed by ``exports/``) to a read-only
``CboeFredProvider`` — this process never fetches; a separate cron job
(later milestone) is what refreshes the disk cache it reads from.
"""

from __future__ import annotations

import logging
from pathlib import Path

from deltadewa.app.factory import create_app
from deltadewa.marketdata import CboeFredProvider
from deltadewa.state import ProgramState


def main() -> None:
    """Build and run the app against the shared ``exports/`` state."""
    logging.basicConfig(level=logging.INFO)

    state = ProgramState.load(Path("exports"))
    market_data = CboeFredProvider(read_only=True)

    app = create_app(
        state=state,
        market_data=market_data,
        ips_config=state.ips_config,
    )
    app.run(debug=False)


if __name__ == "__main__":
    main()
