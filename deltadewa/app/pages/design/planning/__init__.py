"""The `/design` page's PLANNING zone: one module per read-only panel.

Each panel module exposes exactly two names to `page.py`'s composition:
`layout(...)` (the panel's markup fragment, owning its own element ids)
and `register(app)` (its callback). This file stays a namespace only —
no re-exports, no shared composition logic — so it cannot quietly grow
into the grab-bag module #308's plan explicitly ruled out.
"""
