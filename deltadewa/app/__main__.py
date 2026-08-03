"""Entrypoint: run the Dash app locally (``python -m deltadewa.app``).

Uses the Flask/Werkzeug dev server, bound to ``DELTADEWA_HOST``/
``DELTADEWA_PORT`` (default ``127.0.0.1:8050`` — safe for local use; only
the container's own environment, set in the Dockerfile, overrides the host
to ``0.0.0.0``). The container's production entrypoint is gunicorn against
``deltadewa.app.wsgi:server()`` instead; this module shares that module's
``dash_app()`` construction, so the two paths can't drift apart.
"""

from __future__ import annotations

import os

from deltadewa.app.wsgi import dash_app

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = "8050"


def _host_and_port() -> tuple[str, int]:
    """Read ``DELTADEWA_HOST``/``DELTADEWA_PORT``, default loopback:8050."""
    host = os.environ.get("DELTADEWA_HOST", _DEFAULT_HOST)
    port = int(os.environ.get("DELTADEWA_PORT", _DEFAULT_PORT))
    return host, port


def main() -> None:
    """Run the dev server against the shared ``exports/`` state."""
    host, port = _host_and_port()
    dash_app().run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
