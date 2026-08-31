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

A panel that *raises* is only half the isolation story, though. #326
found the strike-ladder panel going visually blank without raising at
all — every rung unsolvable at the requested inputs — and every one of
its dead ends (a raise, a malformed dial, an empty answer) rendered as
the identical grey ``.plain-language`` paragraph the panels also use for
their own explanatory prose. A reader could not tell "still to build"
from "nothing solves here" from "broken". :func:`panel_notice` gives
each dead end a distinct, visibly-a-notice identity via
:class:`NoticeKind`; :func:`safe_render`'s own branches now build on it
instead of on bare paragraph/div markup.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from dash import html

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from dash.development.base_component import Component

_logger = logging.getLogger(__name__)


class NoticeKind(StrEnum):
    """Why a panel has nothing (or only a degraded something) to show.

    Four reasons, one idiom (#326) — a panel with nothing to render
    always uses :func:`panel_notice`, never bare prose, so the *shape*
    of the notice tells a reader which of these it is before they read
    a word of the message:

    * ``INPUT`` — the dials themselves are blank or unparseable; the
      engine was never asked anything.
    * ``BLOCKED`` — the book cannot be answered yet: a structural
      ``ValueError`` from the analysis layer (no underlying position,
      no exercise style set).
    * ``EMPTY`` — the engine ran and answered, and the answer is that
      there is genuinely nothing to show (e.g. every ladder rung
      unsolvable at the requested deltas).
    * ``ERROR`` — an unexpected exception; the one case that was
      already visible before #326, kept here as the fourth idiom
      rather than a fifth format.

    """

    INPUT = "input"
    BLOCKED = "blocked"
    EMPTY = "empty"
    ERROR = "error"


def panel_notice(
    headline: str,
    *,
    kind: NoticeKind,
    detail: str | None = None,
    body: Sequence[Component] = (),
) -> html.Div:
    """Render one panel's dead end as a bordered, kind-specific notice.

    Never the same class the panels use for their own explanatory
    prose (``.plain-language``) — that identity collision is what made
    #326's three empty/blocked/input states unreadable as anything but
    absent content. *headline* is always shown; *detail* — e.g. a
    page-supplied remediation pointer via :func:`safe_render`'s
    ``blocked_hint`` — renders as a second, muted line when given;
    *body* carries any structured content a caller still wants inside
    the notice (e.g. the ladder's unsolvable-rung lines).

    Args:
        headline: The one-line statement of what happened.
        kind: Which of the four dead ends this is; selects the CSS
            modifier (``panel-notice--{kind}``).
        detail: Optional second line — typically what would fix it.
        body: Optional extra content rendered below the headline/detail.

    Returns:
        An ``html.Div`` styled as a notice, never as body prose.

    """
    children: list[Component] = [
        html.P(headline, className="panel-notice__headline"),
    ]
    if detail:
        children.append(html.P(detail, className="panel-notice__detail"))
    children.extend(body)
    return html.Div(
        children,
        className=f"panel-notice panel-notice--{kind.value}",
    )


def incomplete_notice(message: str) -> html.Div:
    """Build an "incomplete inputs" notice.

    Never render zeros for a missing or malformed dial — an unfinished
    input says so in words. Distinct from :func:`status_message`: this
    isn't a failed action, there is no action to fail. A thin wrapper
    over :func:`panel_notice` at ``kind=NoticeKind.INPUT`` (#326) —
    every existing caller keeps working unchanged.
    """
    return panel_notice(message, kind=NoticeKind.INPUT)


def status_message(message: str, *, error: bool) -> html.Div:
    """Build a one-line status/error notice."""
    modifier = "error" if error else "success"
    return html.Div(
        message,
        className=f"status-message status-message--{modifier}",
    )


def safe_render(
    build: Callable[[], Component],
    *,
    blocked_hint: str | None = None,
) -> Component:
    """Render one panel, turning a raise into a visible, panel-local notice.

    ``build`` should perform both this panel's analysis calls and its
    component construction — see the module docstring on why sharing
    already-computed state with another panel would make the isolation
    fake. A structural ``ValueError`` (e.g. ``size_hedge`` /
    ``build_strike_ladder`` raising on a book with no underlying position,
    rather than fabricating a zero result) renders as a
    :attr:`NoticeKind.BLOCKED` notice: the exception's own message as
    the headline, plus *blocked_hint* as the detail line when the
    caller supplies one. The hint is deliberately a parameter, not
    something ``analysis/`` embeds in its own exception text — the
    remediation pointer (e.g. "set the underlying spot and quantity in
    the BOOK zone") is presentation, and belongs with the page that
    knows where that control lives, not in a domain-layer message
    (#326). Anything else is logged at the severity an unhandled 500
    would have been and shown as a :attr:`NoticeKind.ERROR` notice, so
    a page reader — not only someone reading the server log — can tell
    this panel broke.

    Args:
        build: Zero-argument callable producing one panel's ``Component``.
        blocked_hint: Optional remediation pointer appended as the
            detail line when ``build`` raises ``ValueError``.

    Returns:
        ``build()``'s result, or a degraded notice in its place.

    """
    try:
        return build()
    except ValueError as exc:
        return panel_notice(
            str(exc),
            kind=NoticeKind.BLOCKED,
            detail=blocked_hint,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        _logger.exception("Unexpected error rendering a panel")
        return panel_notice(
            "Something went wrong — see the server log.",
            kind=NoticeKind.ERROR,
        )
