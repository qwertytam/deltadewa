"""Tests for deltadewa.app.section_nav — the derived "jump to" TOC (#357)."""

from __future__ import annotations

from dash import html
from dash.development.base_component import Component

from deltadewa.app.section_nav import (
    TOP_ANCHOR_ID,
    SectionGroup,
    SectionSpec,
    back_to_top_link,
    build_section_nav,
    section_wrapper,
)


def _ids(node: object) -> list[str]:
    """Every component's string ``id`` in *node*'s tree."""
    ids: list[str] = []
    if isinstance(node, Component):
        component_id = getattr(node, "id", None)
        if isinstance(component_id, str):
            ids.append(component_id)
        ids.extend(_ids(getattr(node, "children", None)))
    elif isinstance(node, (list, tuple)):
        for child in node:
            ids.extend(_ids(child))
    return ids


def _hrefs(node: object) -> list[str]:
    """Every ``html.A``'s ``href`` in *node*'s tree, in document order."""
    hrefs: list[str] = []
    if isinstance(node, html.A):
        href = getattr(node, "href", None)
        if isinstance(href, str):
            hrefs.append(href)
    children = getattr(node, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            hrefs.extend(_hrefs(child))
    elif children is not None:
        hrefs.extend(_hrefs(children))
    return hrefs


class TestBuildSectionNav:
    """A flat page (no zone tier) — /monitor's shape."""

    def test_one_link_per_section_in_order(self) -> None:
        sections = (
            SectionSpec(anchor_id="section-a", title="Alpha"),
            SectionSpec(anchor_id="section-b", title="Beta"),
        )
        nav = build_section_nav(
            [SectionGroup(label=None, anchor_id=None, sections=sections)],
        )

        assert _hrefs(nav) == ["#section-a", "#section-b"]

    def test_link_text_is_the_section_title(self) -> None:
        sections = (SectionSpec(anchor_id="section-a", title="Alpha"),)
        nav = build_section_nav(
            [SectionGroup(label=None, anchor_id=None, sections=sections)],
        )

        assert "Alpha" in str(nav)

    def test_empty_groups_render_an_empty_but_present_nav(self) -> None:
        """A page with zero sections still gets a Nav, never an omission."""
        nav = build_section_nav([])

        assert isinstance(nav, html.Nav)
        assert _hrefs(nav) == []


class TestBuildSectionNavGrouped:
    """A zoned page — /design's BOOK/PLANNING/EXPLORATION shape."""

    def test_groups_render_in_order_with_their_own_sections(self) -> None:
        groups = [
            SectionGroup(
                label="Book",
                anchor_id="zone-book",
                sections=(SectionSpec("section-add", "Add a position"),),
            ),
            SectionGroup(
                label="Planning",
                anchor_id="zone-planning",
                sections=(
                    SectionSpec("section-sizing", "Sizing workbench"),
                    SectionSpec("section-ladder", "Strike ladder"),
                ),
            ),
        ]
        nav = build_section_nav(groups)

        # Each group's own label links to its zone anchor first, then
        # its sections follow, in order.
        assert _hrefs(nav) == [
            "#zone-book",
            "#section-add",
            "#zone-planning",
            "#section-sizing",
            "#section-ladder",
        ]
        text = str(nav)
        assert "Book" in text
        assert "Planning" in text
        assert "Sizing workbench" in text

    def test_group_label_links_to_the_zone_anchor_not_an_id_on_itself(
        self,
    ) -> None:
        """Regression: the label must never carry the zone's own id.

        An earlier draft put ``id=group.anchor_id`` on the label span
        itself — which, once the real zone heading further down the page
        also carries that id, is two elements sharing one id: invalid
        HTML, and ambiguous to anything that looks the id up. The label
        must instead *link* to the id, never own it.
        """
        groups = [
            SectionGroup(
                label="Planning",
                anchor_id="zone-planning",
                sections=(SectionSpec("section-sizing", "Sizing workbench"),),
            ),
        ]

        nav = build_section_nav(groups)

        ids_in_tree = _ids(nav)
        assert "zone-planning" not in ids_in_tree
        assert "#zone-planning" in _hrefs(nav)

    def test_group_label_is_optional_per_group(self) -> None:
        """A page can mix labelled and unlabelled groups without raising."""
        groups = [
            SectionGroup(
                label=None,
                anchor_id=None,
                sections=(SectionSpec("section-a", "Alpha"),),
            ),
        ]

        nav = build_section_nav(groups)

        assert _hrefs(nav) == ["#section-a"]


class TestBackToTopLink:
    """The per-zone "back to top" link."""

    def test_targets_the_top_anchor_id(self) -> None:
        link = back_to_top_link()

        assert link.href == f"#{TOP_ANCHOR_ID}"

    def test_is_a_plain_html_anchor(self) -> None:
        """A same-document fragment jump, not a dcc.Link route change."""
        link = back_to_top_link()

        assert isinstance(link, html.A)


class TestSectionWrapper:
    """The wrapper used where an anchor cannot live on the panel's own
    heading (a panel built inside a safe_render closure — see /monitor).
    """

    def test_wraps_the_child_with_the_anchor_id(self) -> None:
        spec = SectionSpec(anchor_id="section-x", title="X")
        child = html.Div("panel content")

        wrapped = section_wrapper(spec, child)

        assert wrapped.id == "section-x"
        assert wrapped.children is child

    def test_anchor_survives_a_degraded_child(self) -> None:
        """The whole point: the id must be present even if the panel
        itself rendered a degraded notice rather than its real content.
        """
        spec = SectionSpec(anchor_id="section-x", title="X")
        degraded = html.Div("Something went wrong", className="panel-notice")

        wrapped = section_wrapper(spec, degraded)

        assert wrapped.id == "section-x"
        assert "Something went wrong" in str(wrapped)
