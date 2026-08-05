"""A small pill naming the pricing basis a repricing surface uses.

Presentation-only, same category as ``app.bands``: no engine calls, no
arithmetic — just labelling an already-chosen basis so it's a visible
attribute of a panel rather than an invisible default. Shared by
``/monitor`` and ``/design``'s PLANNING zone so both pages use one
vocabulary for "what did this number get priced against" (see
``docs/implementation-plan.md`` M2.5).
"""

from __future__ import annotations

from dash import html


def basis_chip(text: str) -> html.Span:
    """Build a basis chip.

    Args:
        text: The basis label, e.g. ``"basis: crash-skew (IPS anchor)"``.

    Returns:
        An ``html.Span`` (class ``basis-chip``) carrying *text*.

    """
    return html.Span(text, className="basis-chip")
