"""Pin #357's TOC-vs-page agreement for the real, rendered /design page.

``test_design_ids.py`` checks the *source* mechanically (no anchor id is
created twice, no id is referenced without being created). This module
checks the *rendered output*: that the TOC ``page.py`` builds from
``book.SECTIONS``/``_PLANNING_SECTIONS``/``_EXPLORATION_SECTIONS`` links to
exactly the anchor ids the page actually renders, in the same order — a
panel added to a zone's call list without adding it to the matching tuple
(or added in a different order) fails here, rather than only being
noticed by a reader clicking a stale TOC link.
"""

from __future__ import annotations

from pathlib import Path

from dash.development.base_component import Component

from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages import design
from deltadewa.constants import ExerciseStyle
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState

_EXAMPLE_IPS_YAML = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)  # #245: real config/ips.yaml is gitignored; use the tracked example.


def _app_with_ips(tmp_path: Path) -> ProgramDashApp:
    state = ProgramState.load(
        tmp_path,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    market_data = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    return create_app(
        state=state,
        market_data=market_data,
        ips_config=state.ips_config,
    )


def _toc_href_ids(node: object) -> list[str]:
    """Every ``#anchor`` href under the page's own ``.section-nav``.

    Restricted to the TOC specifically (rather than every link on the
    page) by looking only inside the component whose ``className`` is
    ``"section-nav"`` — the exploration zone's own
    ``dcc.Link("See the policy crash number on /monitor.", ...)`` is a
    route link, not a fragment one, and must not be counted here.
    """
    if isinstance(node, Component):
        if getattr(node, "className", None) == "section-nav":
            return _hrefs(node)
        return _toc_href_ids(getattr(node, "children", None))
    if isinstance(node, (list, tuple)):
        for child in node:
            found = _toc_href_ids(child)
            if found:
                return found
    return []


def _hrefs(node: object) -> list[str]:
    """Every fragment ``href`` (``#...``) in *node*'s tree, in order."""
    hrefs: list[str] = []
    if isinstance(node, Component):
        href = getattr(node, "href", None)
        if isinstance(href, str) and href.startswith("#"):
            hrefs.append(href.removeprefix("#"))
        hrefs.extend(_hrefs(getattr(node, "children", None)))
    elif isinstance(node, (list, tuple)):
        for child in node:
            hrefs.extend(_hrefs(child))
    return hrefs


def _ids_in_document_order(node: object, *, only: set[str]) -> list[str]:
    """Every component id in *node*'s tree that is in *only*, in order."""
    ids: list[str] = []
    if isinstance(node, Component):
        component_id = getattr(node, "id", None)
        if isinstance(component_id, str) and component_id in only:
            ids.append(component_id)
        ids.extend(
            _ids_in_document_order(getattr(node, "children", None), only=only),
        )
    elif isinstance(node, (list, tuple)):
        for child in node:
            ids.extend(_ids_in_document_order(child, only=only))
    return ids


class TestDesignTocAgreesWithTheRenderedPage:
    """The TOC's link order must match where each anchor actually renders."""

    def test_every_toc_link_lands_on_an_id_that_renders_exactly_once(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app_with_ips(tmp_path)
        layout = design.render(app)

        toc_ids = _toc_href_ids(layout)
        assert toc_ids, "the TOC rendered no links at all"

        rendered_ids = _ids_in_document_order(layout, only=set(toc_ids))
        assert len(rendered_ids) == len(set(rendered_ids)), (
            "an anchor id the TOC links to renders more than once: "
            f"{rendered_ids}"
        )
        assert set(rendered_ids) == set(toc_ids), (
            "the TOC and the rendered page disagree on which sections "
            f"exist: toc={sorted(toc_ids)} rendered={sorted(rendered_ids)}"
        )

    def test_toc_order_matches_render_order(self, tmp_path: Path) -> None:
        """Not just the same set — the same order top to bottom.

        A panel moved in ``page.py``'s call list without also moving its
        ``SectionSpec`` in the matching ``_PLANNING_SECTIONS``/
        ``_EXPLORATION_SECTIONS`` tuple fails here even though the set
        check above would still pass.
        """
        app = _app_with_ips(tmp_path)
        layout = design.render(app)

        toc_ids = _toc_href_ids(layout)
        rendered_ids = _ids_in_document_order(layout, only=set(toc_ids))

        assert rendered_ids == toc_ids
