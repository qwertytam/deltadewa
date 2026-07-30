"""Dash application: the deployed program dashboard.

Distinct from ``dashboard/`` + ``widgets/``, which are the Jupyter/
``ipywidgets`` UI and stay notebook-only. This package is the Dash app —
one process, two pages (``/monitor``, ``/design``) — that will eventually
replace the notebooks per ``docs/implementation-plan.md``'s Phase 2.

Callbacks and layouts here stay UI-thin: they call ``analysis/`` for any
metric or decision logic, never reimplement it.
"""

from deltadewa.app.factory import create_app

__all__ = ["create_app"]
