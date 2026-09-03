"""The `/design` page's EXPLORATION zone: one module per stress panel.

Each panel module exposes exactly two names to `page.py`'s composition:
`layout(...)` (the panel's markup fragment, owning its own element ids)
and `register(app)` (its callback). This file stays a namespace only —
no re-exports, no shared composition logic — matching `planning/__init__.py`.
"""
