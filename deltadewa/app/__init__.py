"""Dash application: the deployed program dashboard.

The Dash app — one process, two pages (``/monitor``, ``/design``) — that
replaced the notebooks per ``docs/implementation-plan.md``'s Phase 2.

Callbacks and layouts here stay UI-thin: they call ``analysis/`` for any
metric or decision logic, never reimplement it.
"""

from deltadewa.app.factory import create_app

__all__ = ["create_app"]
