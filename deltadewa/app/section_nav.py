"""In-page "jump to" navigation: a derived table of contents per page.

#357: ``/design`` is a long single-scroll page across three zones with no
way to jump to a section or get back to the top without scrolling past
everything above it. #308 already split the page into one module per
panel — this module turns that structure into navigation rather than
adding a hand-maintained list that can drift from it.

**Why not a scroll-tracking side rail.** The stickier, nicer-looking
option — a rail that highlights the section currently in view — needs a
scroll-spy, and a scroll-spy cannot be a Dash clientside callback: those
fire on component *prop changes*, not scroll events. It would need either
a real ``assets/*.js`` file (the one category of product code this
repo's gate — ``ruff``/``mypy``/``pylint``/``pytest`` — cannot see at
all) or a ``dcc.Interval`` poll running for as long as the page is open.
#358 turned down client-side machinery for the same instinct (a
server-side sort over ~12ms, not a JS sorting library); picking JS here
would be inconsistent with that call. A plain "jump to" TOC plus a
"back to top" link at the foot of each zone answers what was actually
asked for — "let me jump to a section without scrolling past everything
above it" — without introducing an untestable surface.

**Where the anchor id lives is page-specific**, and both pages build
their own :class:`SectionSpec` list from the modules they already
compose — see ``pages/design/page.py`` and ``pages/monitor.py`` for the
two call sites, and each for why the anchor sits where it does:

- ``/design``'s panel headings are rendered unconditionally by each
  panel's own ``layout()`` (#308's split), so the anchor lives on that
  ``H3``/``H2`` itself.
- ``/monitor``'s sections are each built inside a
  ``panel_guard.safe_render`` closure, so an anchor placed *inside* one
  would vanish exactly when that panel degrades — the one moment an
  operator most wants to jump straight to it. ``monitor.py`` instead
  wraps each panel's already-built output in :func:`section_wrapper`,
  outside the closure, so the anchor survives a degraded render.

Nothing here calls into ``analysis/`` or reads portfolio state — this is
presentation over an already-built section list, the same category as
``app.basis_chip``/``app.bands``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from dash import html

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dash.development.base_component import Component

#: The anchor id every "back to top" link points at — the page's own
#: ``H1``. Not page-specific: both pages' top-level layout gives their
#: ``H1`` this id so one link idiom works on both.
TOP_ANCHOR_ID = "page-top"


@dataclass(frozen=True, slots=True)
class SectionSpec:
    """One jumpable section: the anchor it renders under and its title.

    A panel module's single source for both its heading text and its
    TOC entry — see this module's docstring on why that pairing is what
    keeps the two from drifting apart.
    """

    anchor_id: str
    title: str


@dataclass(frozen=True, slots=True)
class SectionGroup:
    """A run of :class:`SectionSpec` under one optional zone heading.

    ``label``/``anchor_id`` are both ``None`` for a page with no zone
    tier (``/monitor``) — :func:`build_section_nav` then renders a flat
    list with no group heading.
    """

    label: str | None
    anchor_id: str | None
    sections: tuple[SectionSpec, ...]


def _section_link(section: SectionSpec) -> html.Li:
    """Build one TOC row: a same-document fragment link.

    ``html.A``, not ``dcc.Link`` — a fragment-only href navigates within
    the loaded document (the browser handles it, firing ``hashchange``,
    not ``popstate``), so ``dcc.Location``'s ``pathname`` never changes
    and the page's own routing callback never re-fires. Routing through
    ``dcc.Link`` here would be wrong twice over: it targets a route, not
    a fragment, and Dash would treat the (unchanged) pathname as nothing
    to do anyway.
    """
    return html.Li(
        html.A(section.title, href=f"#{section.anchor_id}"),
        className="section-nav__item",
    )


def _group(group: SectionGroup) -> Component:
    """Build one group: an optional label plus its section list.

    The label is a same-document link to ``group.anchor_id`` (the zone's
    own heading, e.g. ``/design``'s "Planning" ``H2``) when one is given
    — never an ``id`` on the label itself. Giving the label the *same*
    id as the heading it names would put two elements carrying that id
    in the rendered page at once (the label here, and the real heading
    further down), which is invalid HTML and makes "the" element behind
    that id ambiguous to anything that looks it up.
    """
    items = html.Ul(
        [_section_link(section) for section in group.sections],
        className="section-nav__list",
    )
    if group.label is None:
        return items
    label: Component
    if group.anchor_id is not None:
        label = html.A(
            group.label,
            href=f"#{group.anchor_id}",
            className="section-nav__group-label",
        )
    else:
        label = html.Span(group.label, className="section-nav__group-label")
    return html.Div([label, items], className="section-nav__group")


def build_section_nav(groups: Sequence[SectionGroup]) -> html.Nav:
    """Build the "Jump to" table of contents for one page.

    Args:
        groups: The page's sections, grouped by zone (``/design``) or as
            one flat group with ``label=None`` (``/monitor``).

    Returns:
        An ``html.Nav`` (class ``section-nav``) with one link per
        section, grouped as given. Never raises — a page with zero
        groups renders an empty (but present) nav rather than omitting
        it, so a page's TOC is never silently absent.

    """
    return html.Nav(
        [
            html.P("Jump to", className="section-nav__heading"),
            *[_group(group) for group in groups],
        ],
        className="section-nav",
    )


def back_to_top_link() -> html.A:
    """Build a "back to top" link for the foot of a zone.

    A 17-panel page needs the way back as much as the way in — three of
    these cost nothing next to a TOC that otherwise only points one
    direction.
    """
    return html.A(
        "↑ Back to top",
        href=f"#{TOP_ANCHOR_ID}",
        className="back-to-top",
    )


def section_wrapper(spec: SectionSpec, child: Component) -> html.Div:
    """Wrap an already-built panel component in its section's anchor id.

    Used only where the anchor cannot live on the panel's own heading —
    see the module docstring's ``/monitor`` case. The wrapper carries no
    styling of its own (the panel's own ``className`` is untouched); it
    exists purely to give the anchor a place to live that survives a
    degraded render.

    Args:
        spec: The section's anchor id and title (the title is not
            rendered here — the panel already renders its own heading;
            this only needs the id).
        child: The panel's already-built component (e.g. the result of
            a ``panel_guard.safe_render`` call).

    Returns:
        An ``html.Div`` with ``id=spec.anchor_id`` wrapping *child*.

    """
    return html.Div(child, id=spec.anchor_id)
