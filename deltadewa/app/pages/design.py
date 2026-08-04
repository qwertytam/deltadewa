"""The `/design` page: the dense expert workbench (hedge design/roll/stress).

Placeholder for this milestone (M2.2/M2.4) — the workbench surfaces land
in M2.5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import html

if TYPE_CHECKING:
    from deltadewa.app.factory import ProgramDashApp

_layout = html.Div(
    [
        html.H1("Design"),
        html.P("The design page is not built yet — this is the M2.2 shell."),
    ],
    className="page page-design",
)


def render(_app: ProgramDashApp) -> html.Div:
    """Build the /design page layout.

    M2.2 placeholder; M2.5 builds the real workbench content.
    """
    return _layout


def register_callbacks(_app: ProgramDashApp) -> None:
    """No callbacks yet — placeholder page."""
