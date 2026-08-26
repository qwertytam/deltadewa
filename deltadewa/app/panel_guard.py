"""The panel-level error boundary shared by ``/design`` and ``/monitor``.

Both pages assemble a request's page from several independent panel
builders, each driven by one or more ``analysis/`` calls. A raise from any
one of them must degrade only its own panel, not the whole page — and it
must say so *on* the page, since an operator reading a live droplet cannot
see the server log. :func:`safe_render` is the one place that boundary is
implemented.

Originally local to ``design.py`` (M2.5). #363 found ``/monitor`` had no
error handling at all — zero ``try`` statements — so one raise (#362's
expired-leg wing solve) took the whole page to an HTTP 500 instead of
degrading the one panel that hit it. Extracted here rather than copied a
second time so both pages share one idiom instead of two copies that can
drift, and so ``ruff``/``pylint``'s duplicate-code check has nothing to
flag.

Isolation is only real if *both* a panel's analysis calls and its
rendering happen inside the same :func:`safe_render` closure — a value
computed outside it and only rendered inside can still raise before
``safe_render`` ever runs. Where two panels share an underlying
computation (e.g. both consult ``assess_market_environment``), each
panel's closure calls it fresh rather than reusing a value computed for
the other panel, so a failure in one panel's copy cannot take the other
down too. See ``design.py`` for worked examples of that pattern.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from dash import html

if TYPE_CHECKING:
    from collections.abc import Callable

    from dash.development.base_component import Component

_logger = logging.getLogger(__name__)


def incomplete_notice(message: str) -> html.P:
    """Build an "incomplete inputs" notice.

    Never render zeros for a missing or malformed dial — an unfinished
    input says so in words. Distinct from :func:`status_message`: this
    isn't a failed action, there is no action to fail.
    """
    return html.P(message, className="plain-language")


def status_message(message: str, *, error: bool) -> html.Div:
    """Build a one-line status/error notice."""
    modifier = "error" if error else "success"
    return html.Div(
        message,
        className=f"status-message status-message--{modifier}",
    )


def safe_render(build: Callable[[], Component]) -> Component:
    """Render one panel, turning a raise into a visible, panel-local notice.

    ``build`` should perform both this panel's analysis calls and its
    component construction — see the module docstring on why sharing
    already-computed state with another panel would make the isolation
    fake. A structural ``ValueError`` (e.g. ``size_hedge`` /
    ``build_strike_ladder`` raising on a book with no underlying position,
    rather than fabricating a zero result) renders as plain incomplete-
    input text via :func:`incomplete_notice`. Anything else is logged at
    the severity an unhandled 500 would have been and shown generically
    via :func:`status_message`, so a page reader — not only someone
    reading the server log — can tell this panel broke.

    Args:
        build: Zero-argument callable producing one panel's ``Component``.

    Returns:
        ``build()``'s result, or a degraded notice in its place.

    """
    try:
        return build()
    except ValueError as exc:
        return incomplete_notice(str(exc))
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Unexpected error rendering a panel")
        return status_message(
            "Something went wrong — see the server log.",
            error=True,
        )
