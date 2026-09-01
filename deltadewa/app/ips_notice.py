"""The "no IPS policy is loaded" page state, shared by both pages (#385).

Not a panel failure, and deliberately not a :func:`panel_guard.panel_notice`:
this is not one panel raising while its neighbours render, it is *every*
panel having nothing to grade against, so the whole page is replaced. A
panel-scoped notice mounted as a page would misstate the scope.

What #385 fixes is narrower than the layout. ``ProgramState.load`` already
caught ``IpsConfigError`` and logged its message — which
``ips_config.py``'s ``_require_field``/band checks write to be
operator-readable — and then dropped it, so both pages could only point at
the server log. On the droplet that meant an SSH hop over Tailscale plus
``docker compose logs app`` to read one sentence, at exactly the moment
the operator is looking at a browser rather than a terminal.

The caveat line is not decoration. ``config/ips.yaml`` is baked into the
image at build time (the ``Dockerfile``'s ``COPY config ./config``), so the
file this error is *about* is the one inside the running container, which
differs from the host's copy precisely when a host-side edit has not been
rebuilt — #386's whole subject. Reporting the parse error without that
distinction reads as "your edit was wrong" when the edit was fine and the
image was stale.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import html

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.state import ProgramState

_CONTAINER_CAVEAT = (
    "This is the {path} baked into the *running container* at its last "
    "build, not necessarily the file on this host right now — the two "
    "differ until a host-side edit is rebuilt. If this appeared after a "
    "deploy rather than after an edit, see RUNBOOK §4."
)

_LOG_FALLBACK = (
    "No reason was recorded for this — see the server log at startup."
)


def build_no_ips_layout(
    state: ProgramState,
    *,
    title: str,
    lead: str,
    page_class: str,
) -> html.Div:
    """Build a page's "no IPS policy loaded" state, naming the reason.

    Both pages share the reason and the container caveat and keep their
    own *lead* sentence, because what is lost differs: ``/monitor`` loses
    its crash anchor, ``/design`` loses everything it would plan against.

    Args:
        state: The shared program state, read for
            :attr:`~deltadewa.state.ProgramState.ips_load_error` and
            :attr:`~deltadewa.state.ProgramState.ips_path`.
        title: The page heading.
        lead: The page-specific sentence on what cannot be rendered.
        page_class: The page's own root class (e.g. ``"page-monitor"``).

    Returns:
        The replacement page ``html.Div``.

    """
    children: list[Component] = [
        html.H1(title),
        html.P(lead, className="no-ips-message"),
    ]
    if state.ips_load_error is not None:
        children.append(
            html.P(
                [
                    html.Strong("Reason: "),
                    html.Code(state.ips_load_error),
                ],
                className="no-ips-reason",
            ),
        )
        children.append(
            html.P(
                _CONTAINER_CAVEAT.format(path=state.ips_path),
                className="no-ips-detail",
            ),
        )
    else:
        children.append(html.P(_LOG_FALLBACK, className="no-ips-detail"))
    return html.Div(children, className=f"page {page_class}")
