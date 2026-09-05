"""The `/design` page: editor (BOOK), planners (PLANNING), stress (EXPLORATION).

BOOK: add/remove positions, the underlying quantity, and guarded
import/export. PLANNING: the read-only planners — sizing, strike ladder,
roll, monetization — each a thin wrapper over its `analysis/` function,
pricing the same IPS crash basis `/monitor`'s gauge uses, alongside the
panels that read a different basis and chip themselves accordingly
(market environment, hedge triggers, delta drift, convexity cliff).
EXPLORATION: the three notebook stress surfaces — spot/vol heatmap,
time/price heatmap, Monte Carlo distribution — priced on a *different*
basis (proportional vol, a generic GBM move) than PLANNING's crash-skew;
the zone header, a boundary sentence, and a basis chip on every panel say
so, so the two zones' numbers disagreeing on the same cell reads as two
questions, not a bug. Gates at the page level: without ``ips_config``
there is no source for the exercise-style default and no policy to plan
against, so the whole page becomes a single "no IPS policy loaded" state,
the same discipline ``monitor.py`` uses.

BOOK's own mutators, and the guarded-mutation convention they share
(:func:`~deltadewa.app.pages.design.book._guarded_mutation`, module-level
``_..._logic`` functions directly callable from tests), now live in
:mod:`~deltadewa.app.pages.design.book` — see that module's docstring.
PLANNING's and EXPLORATION's own reads have no mutator to guard, so they
route through :func:`_safe_render` instead — the same no-leaked-traceback
discipline, applied to an engine ``ValueError`` (a structurally missing
input, e.g. no underlying position or an out-of-range dial) rather than
a failed mutation. Every panel here watches ``book.BOOK_VERSION_STORE`` —
the single ``dcc.Store`` a successful BOOK edit bumps — for "the book
changed, re-read it."
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from dash import Input, Output, dcc, html

from deltadewa import __version__
from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.ips_notice import build_no_ips_layout
from deltadewa.app.section_nav import (
    TOP_ANCHOR_ID,
    SectionGroup,
    back_to_top_link,
    build_section_nav,
)
from deltadewa.app.shape_notice import shape_notice_text

from . import book
from .exploration import (
    monte_carlo,
    spot_vol,
    time_price,
    vega_term,
    volatility_profile,
)
from .planning import (
    convexity_cliff,
    delta_drift,
    hedge_triggers,
    ladder,
    monetization,
    position_aging,
    provenance,
    roll_plan,
    roll_status,
    sizing,
)
from .planning import market_env as market_env_panel

if TYPE_CHECKING:
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.state import ProgramState

_logger = logging.getLogger(__name__)

# Every PLANNING panel prices this basis — size_hedge, build_strike_ladder,
# and evaluate_roll_status each build CrashShock.from_ips(...) internally,
# the same construction /monitor's build_scenario uses at the IPS crash
# point. One literal, so the zone header and every panel's chip say the
# same thing.
_BASIS_CRASH_SKEW = "basis: crash-skew (IPS anchor)"
# The market-environment panel's own _BASIS_LIVE_MARKET_DATA now lives in
# planning/market_env.py, its only reader.
# Nor does the trigger panel: it reads the book's Greeks at today's market,
# with no crash shock applied at all.
_BASIS_BOOK_GREEKS = "basis: book Greeks at today's market"
# The delta drift panel's own _BASIS_MINUS_5PCT, the convexity cliff
# panel's own _BASIS_MATURITY_CALENDAR, and the volatility profile
# panel's own _BASIS_BOOK_VOLATILITY now live in planning/delta_drift.py,
# planning/convexity_cliff.py, and exploration/volatility_profile.py —
# each is that panel's only reader. The EXPLORATION dial defaults and
# _METRIC_OPTIONS/_EXPLORATION_EMPTY_BOOK_MSG now live with the panels
# that use them (spot_vol.py, time_price.py, monte_carlo.py) or in
# dials.py, for the two of those needed by more than one panel module.

# Every EXPLORATION panel prices this basis instead — a generic vol move,
# not the policy crash. proportional_vol is always passed explicitly to
# the cache (M2.1 finding (c): VolMapping is required, never defaulted).
_BASIS_PROPORTIONAL = "basis: proportional vol (GBM, risk-neutral drift)"

# #357: the zone headings' own anchor ids — book.ZONE_ANCHOR is the third,
# owned by book.py since it renders that H2.
_PLANNING_ZONE_ANCHOR: Final = "zone-planning"
_EXPLORATION_ZONE_ANCHOR: Final = "zone-exploration"

# #357: the page's TOC is derived from the same per-panel SECTION constants
# each layout() call below uses for its own heading — one source, so a
# panel added to a zone without adding it here fails
# test_design_sections.py's document-order check rather than silently
# drifting from the rendered page.
_PLANNING_SECTIONS: Final = (
    market_env_panel.SECTION,
    sizing.SECTION,
    ladder.SECTION,
    roll_plan.SECTION,
    roll_status.SECTION,
    provenance.SECTION,
    position_aging.SECTION,
    hedge_triggers.SECTION,
    delta_drift.SECTION,
    convexity_cliff.SECTION,
    monetization.SECTION,
)
_EXPLORATION_SECTIONS: Final = (
    volatility_profile.SECTION,
    spot_vol.SECTION,
    time_price.SECTION,
    monte_carlo.SECTION,
    vega_term.SECTION,
)


def _no_ips_layout(state: ProgramState) -> html.Div:
    """Build the single "no IPS policy loaded" state for the /design page."""
    return build_no_ips_layout(
        state,
        title="Design",
        lead=(
            "No IPS policy is loaded, so there is no policy to plan "
            "against — sizing targets, ladder bands, and roll thresholds "
            "are all policy-derived, and the position editor's "
            "exercise-style default has no source either."
        ),
        page_class="page-design",
    )


def render(app: ProgramDashApp) -> html.Div:
    """Build the /design page: the BOOK zone and the PLANNING zone.

    BOOK is the editor (add/remove, import/export); PLANNING is the
    read-only planners (sizing, strike ladder, roll, monetization) priced on
    the same IPS crash basis ``/monitor``'s gauge uses, plus the panels
    carrying their own basis chip. Built
    fresh per request from ``app.program_state``/``app.ips_config`` — no
    module-level singleton, so this page's content actually differs from
    ``/monitor``'s (``test_pages.py``'s distinctness assertion).
    """
    if app.ips_config is None:
        return _no_ips_layout(app.program_state)

    ips_config = app.ips_config
    portfolio = app.program_state.portfolio
    default_style = ips_config.pricing.exercise_style.value
    # One assessment shared by the market-environment and monetization
    # panels. Both need the same snapshot, and a second fetch could return a
    # different one — the two panels would then disagree on the same page.
    market_env = assess_market_environment(
        app.market_data,
        ips_config.market_environment,
    )

    book_zone = book.layout(
        app=app,
        portfolio=portfolio,
        default_style=default_style,
    )

    planning_zone = html.Div(
        [
            html.H2(
                ["Planning", basis_chip(_BASIS_CRASH_SKEW)],
                id=_PLANNING_ZONE_ANCHOR,
            ),
            html.P(
                "Every panel below that prices the book prices the IPS "
                "crash — the same basis /monitor's gauge uses. Those agree "
                "with /monitor to the cent. Any panel on a different basis — "
                "reading the live feed, the book's Greeks unshocked, another "
                "shock, or just the position calendar — carries its own "
                "chip.",
                className="plain-language",
            ),
            market_env_panel.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                market_env=market_env,
            ),
            sizing.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_crash_skew=_BASIS_CRASH_SKEW,
            ),
            ladder.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_crash_skew=_BASIS_CRASH_SKEW,
            ),
            roll_plan.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_crash_skew=_BASIS_CRASH_SKEW,
            ),
            roll_status.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_crash_skew=_BASIS_CRASH_SKEW,
            ),
            provenance.layout(
                app=app,
                portfolio=portfolio,
                ips_config=ips_config,
            ),
            position_aging.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_book_greeks=_BASIS_BOOK_GREEKS,
            ),
            hedge_triggers.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_book_greeks=_BASIS_BOOK_GREEKS,
            ),
            delta_drift.layout(portfolio=portfolio),
            convexity_cliff.layout(
                portfolio=portfolio,
                ips_config=ips_config,
            ),
            monetization.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                market_env=market_env,
                basis_crash_skew=_BASIS_CRASH_SKEW,
            ),
            back_to_top_link(),
        ],
        className="zone-planning",
    )

    exploration_zone = html.Div(
        [
            html.H2(
                ["Exploration", basis_chip(_BASIS_PROPORTIONAL)],
                id=_EXPLORATION_ZONE_ANCHOR,
            ),
            html.P(
                "These grids price a generic volatility move — every leg "
                "scaled so the vega-weighted average reaches the level on "
                "the axis. The PLANNING panels above price the IPS crash "
                "with its wing-anchored skew instead. The same spot/vol "
                "cell will read differently on the two — they are answers "
                "to different questions, not a disagreement.",
                className="plain-language",
            ),
            dcc.Link(
                "See the policy crash number on /monitor.",
                href="/monitor",
            ),
            volatility_profile.layout(portfolio=portfolio),
            spot_vol.layout(
                portfolio=portfolio,
                cache=app.scenario_cache,
                basis_proportional=_BASIS_PROPORTIONAL,
            ),
            time_price.layout(
                portfolio=portfolio,
                cache=app.scenario_cache,
                basis_proportional=_BASIS_PROPORTIONAL,
            ),
            monte_carlo.layout(
                portfolio=portfolio,
                basis_proportional=_BASIS_PROPORTIONAL,
            ),
            vega_term.layout(
                portfolio=portfolio,
                ips_config=ips_config,
                basis_book_greeks=_BASIS_BOOK_GREEKS,
            ),
            back_to_top_link(),
        ],
        className="zone-exploration",
    )

    # #357: derived from the same SECTION constants every panel's own
    # layout() renders its heading id from — see _PLANNING_SECTIONS/
    # _EXPLORATION_SECTIONS above and book.SECTIONS. A panel added to a
    # zone without adding it to one of those tuples is caught by
    # test_design_sections.py, not by a reader noticing it's unreachable.
    section_nav = build_section_nav(
        [
            SectionGroup(
                label="Book",
                anchor_id=book.ZONE_ANCHOR,
                sections=book.SECTIONS,
            ),
            SectionGroup(
                label="Planning",
                anchor_id=_PLANNING_ZONE_ANCHOR,
                sections=_PLANNING_SECTIONS,
            ),
            SectionGroup(
                label="Exploration",
                anchor_id=_EXPLORATION_ZONE_ANCHOR,
                sections=_EXPLORATION_SECTIONS,
            ),
        ],
    )

    return html.Div(
        [
            html.H1("Design", id=TOP_ANCHOR_ID),
            section_nav,
            html.Div(
                shape_notice_text(portfolio),
                id="shape-notice",
                className="shape-notice",
            ),
            book_zone,
            planning_zone,
            exploration_zone,
            _page_footer(),
        ],
        className="page page-design",
    )


def _page_footer() -> html.Div:
    """Build the page's own last element: a muted build-version stamp.

    #359 (originally fixed on /monitor, applied here to match): a
    build-version stamp styled identically to the surrounding financial
    sentences gets skimmed past. This used to be a ``.plain-language``
    paragraph sandwiched inside the exploration zone, after the vega
    term exposure panel. Placed here instead — the true last child of
    the page, after every zone — it stays in the same place regardless
    of which panels are expanded or collapsed, and its styling (shared
    ``.page-footer`` class, same as /monitor) marks it as metadata
    rather than portfolio commentary.
    """
    return html.Div(
        html.P(f"Running v{__version__}"),
        className="page-footer",
    )


def register_callbacks(  # pylint: disable=too-many-locals
    app: ProgramDashApp,
) -> None:
    """Wire the BOOK zone's mutating callbacks and the read-only panels.

    One nested callback per mutator/panel is the natural shape of this
    function — the local count tracks how many the page wires, not
    unrelated complexity, so a targeted disable is more honest than
    restructuring around the lint.

    A no-op when ``app.ips_config is None`` — mirrors ``render()``'s own
    page-level gate, so a gated page has nothing wired to a mutator
    either.
    """
    if app.ips_config is None:
        return
    # Captured once into a local rather than re-read from app.ips_config
    # inside each nested callback below: mypy narrows a local variable's
    # None-ness across a closure, but not a property re-accessed later
    # (the same reason monitor.py's register_callbacks does this).
    ips_config = app.ips_config

    book.register(app)
    convexity_cliff.register(app, ips_config=ips_config)
    position_aging.register(app, ips_config=ips_config)
    hedge_triggers.register(app, ips_config=ips_config)
    delta_drift.register(app)
    sizing.register(app, ips_config=ips_config)
    ladder.register(app, ips_config=ips_config)
    roll_plan.register(app, ips_config=ips_config)
    roll_status.register(app, ips_config=ips_config)
    provenance.register(app, ips_config=ips_config)
    monetization.register(app, ips_config=ips_config)
    market_env_panel.register(app, ips_config=ips_config)
    volatility_profile.register(app)
    spot_vol.register(app)
    time_price.register(app)
    monte_carlo.register(app)
    vega_term.register(app, ips_config=ips_config)

    @app.callback(
        Output("shape-notice", "children"),
        Input(book.BOOK_VERSION_STORE, "data"),
    )
    def _render_shape_notice(_version: int) -> str | None:
        # Restores #261: /design can change the book's shape (add/remove a
        # position) without a re-import, so this has to watch book-version
        # like every other read-only panel on this page, not just render
        # once at page load.
        return shape_notice_text(app.program_state.portfolio)
