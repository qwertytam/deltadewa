"""App construction shared by local dev and the production container.

``python -m deltadewa.app`` (``__main__.py``) and gunicorn (the Dockerfile's
``CMD``, via ``deltadewa.app.wsgi:server()``) both need the same wiring — the
shared ``exports/`` state and a read-only ``CboeFredProvider`` — so it lives
here once rather than twice. Construction is deferred into a function rather
than run at module import time: gunicorn's app-loader accepts a call
expression in the module string (``module:server()``), so a function is what
it needs anyway, and it means importing this module has no side effect —
only calling ``server()``/``dash_app()`` does.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from deltadewa.app.factory import create_app
from deltadewa.marketdata import (
    CboeFredProvider,
    default_cache_dir,
    resolve_data_ttl,
)
from deltadewa.state import ProgramState

if TYPE_CHECKING:
    from flask import Flask

    from deltadewa.app.factory import ProgramDashApp


def _build() -> ProgramDashApp:
    """Construct the app once, against the shared ``exports/`` state."""
    logging.basicConfig(level=logging.INFO)
    state = ProgramState.load(Path("exports"))
    return create_app(
        state=state,
        market_data=CboeFredProvider(
            cache_dir=default_cache_dir(),
            ttl=resolve_data_ttl(state.ips_config),
            read_only=True,
        ),
        ips_config=state.ips_config,
    )


def server() -> Flask:
    """Gunicorn's entrypoint: ``deltadewa.app.wsgi:server()``."""
    # Dash types .server as Any (it's pluggable, per-backend); cast since
    # this app only ever runs on the Flask backend.
    return cast("Flask", _build().server)


def dash_app() -> ProgramDashApp:
    """Local-dev entrypoint — the Dash object itself, for ``Dash.run()``."""
    return _build()
