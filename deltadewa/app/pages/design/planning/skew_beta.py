"""PLANNING zone: the Skew Exposure (skew beta) panel (Part X #9, 8c / N9).

One number, one chip. Reprices the book with one vol point of extra
downside skew at the IPS wing anchor — no spot move, no flat vol bump —
so it carries its own basis chip rather than the zone's crash-skew one,
the same reason ``delta_drift.py`` does.

Ungraded by design: the handbook rates skew beta only qualitatively and
gives no number, so this panel shows the reading and says so rather than
inventing a band (see ``analysis/skew_beta.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from dash import Input, Output, html

from deltadewa.analysis.skew_beta import calculate_skew_beta
from deltadewa.app import format as fmt
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.skew_beta import SkewBeta
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-skew-beta",
    title="Skew exposure (skew beta)",
)

_PANEL_ID = "plan-skew-beta-panel"

_NO_BAND_TEXT = (
    "No handbook band — the handbook grades skew beta only qualitatively "
    "(low for at-the-money puts, high for deep out-of-the-money tails) and "
    "gives no number, so this reading is not graded. Skew exposure is not "
    "skew level: how expensive skew is today is the market-environment "
    "panel's skew percentile. The handbook notes a hedge can carry strong "
    "skew exposure even while skew is expensive."
)


def _basis_label(ips_config: IpsConfig) -> str:
    """Name the basis: what was bumped, where, and what was held still."""
    wing = ips_config.convexity.skew_reference_delta * 100
    return f"basis: +1 vol pt skew at the IPS {wing:g}Δ wing, today's spot"


def _skew_beta_view(beta: SkewBeta | None) -> Component:
    if beta is None:
        return html.P(
            "No live option legs — nothing to measure.",
            className="env-verdict",
        )
    book_text = (
        f" ({fmt.signed_percent(beta.pct_of_protected_book, decimals=2)} "
        "of the protected book)"
        if beta.pct_of_protected_book is not None
        else ""
    )
    expired_text = (
        f" {beta.excluded_expired} expired leg"
        f"{'s' if beta.excluded_expired != 1 else ''} left out."
        if beta.excluded_expired
        else ""
    )
    return html.Div(
        [
            html.P(
                f"{fmt.signed_compact_currency(beta.dollars_per_vol_pt)} "
                f"per +1 vol point of downside skew{book_text}.",
                className="env-verdict",
            ),
            html.P(
                "How much the option legs' value changes if out-of-the-"
                "money put vol rises one point relative to at-the-money "
                "vol, with spot and at-the-money vol unchanged — the "
                "handbook's ∂V/∂Skew. Long puts gain; short puts give it "
                f"back.{expired_text}",
                className="plain-language",
            ),
            html.P(_NO_BAND_TEXT, className="plain-language"),
        ],
    )


def _render_skew_beta_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render the skew beta panel for the current book."""
    return _safe_render(
        lambda: _skew_beta_view(
            calculate_skew_beta(
                portfolio,
                skew_reference_delta=ips_config.convexity.skew_reference_delta,
            ),
        ),
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> html.Div:
    """Build the Skew Exposure panel."""
    return html.Div(
        [
            html.H3(
                [SECTION.title, basis_chip(_basis_label(ips_config))],
                id=SECTION.anchor_id,
            ),
            html.Div(
                _render_skew_beta_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                ),
                id=_PANEL_ID,
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Skew Exposure panel's re-render callback."""

    @app.callback(
        Output(_PANEL_ID, "children"),
        Input(BOOK_VERSION_STORE, "data"),
    )
    def _render_skew_beta_panel(_version: int) -> Component:
        return _render_skew_beta_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
        )
