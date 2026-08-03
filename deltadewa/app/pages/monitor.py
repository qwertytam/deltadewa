"""The `/monitor` page: read-mostly book review for the non-technical partner.

Placeholder for this milestone (M2.2) — the crash-led content lands in M2.4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import html

if TYPE_CHECKING:
    from deltadewa.app.factory import ProgramDashApp

_layout = html.Div(
    [
        html.H1("Monitor"),
        html.P("The monitor page is not built yet — this is the M2.2 shell."),
    ],
    className="page page-monitor",
)


def render(_app: ProgramDashApp) -> html.Div:
    """Build the /monitor page layout.

    M2.2 placeholder; M2.4 builds the real crash-led content.
    """
    return _layout


def register_callbacks(_app: ProgramDashApp) -> None:
    """No callbacks yet — placeholder page."""
