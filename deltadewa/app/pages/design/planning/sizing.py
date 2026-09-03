"""PLANNING zone: the Sizing Workbench panel, plus Part X #4 Vega Sufficiency.

The vega-sufficiency block sits inside this panel because it is the
same question one step back: sizing asks "how many contracts", vega
sufficiency asks "does what we already hold respond to volatility at
all". It is a sibling of the candidate rather than part of
:func:`_sizing_panel_view`, and is rendered *whatever* the candidate
does — it depends on neither the dials nor an underlying position, so
folding it into the candidate's own render would let an unfinished
dial or an empty book take Part X #4 off the page again.

``basis_crash_skew`` is a parameter, not a module constant: every
PLANNING panel that prices the IPS crash shares this basis chip text,
so the string lives in ``page.py`` and is passed down.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dash import Input, Output, dcc, html

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.sizing import size_hedge
from deltadewa.app import format as fmt
from deltadewa.app.bands import band_bar
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.panel_guard import incomplete_notice as _incomplete
from deltadewa.app.panel_guard import safe_render as _safe_render

from ..book import BOOK_VERSION_STORE

if TYPE_CHECKING:
    from dash.development.base_component import Component

    from deltadewa.analysis.sizing import HedgeSizingResult
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

# PLANNING zone: dial default. Carried over from the sizing cell of
# hedge_design.ipynb, which Stage 4.3 deleted — the starting point that
# notebook hardcoded, kept here as an adjustable dial default. Genuinely
# presentation, not policy: no IPS strike-selection section exists to read
# it from, and inventing one is its own decision, not #316's (which is
# about tenor, not delta/OTM). The MATURITY dial default beside it in the
# original notebook was #316's actual bug (0.5y, unbacked by any policy)
# and now comes from ips_config.maturity_selection instead — see layout().
_DEFAULT_SIZING_PCT_OTM = 20.0

# #326: safe_render's BLOCKED remediation pointer for this panel, which
# raises ValueError on a book with no underlying position (size_hedge).
# Presentation, on the page that knows where the fix lives -- not baked
# into the analysis-layer exception text.
_SIZING_BLOCKED_HINT = (
    "Set the underlying spot and quantity in the BOOK zone; sizing "
    "needs them to size a candidate hedge."
)


def _vega_sufficiency_block(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Render Part X #4 — is the book big enough to answer a vol spike.

    Sits inside the sizing panel because it is the same question one step
    back: sizing asks "how many contracts", this asks "does what we already
    hold respond to volatility at all". It describes **the current book**,
    not the sized candidate above it, and says so — otherwise the reading
    is naturally taken for the candidate's.

    The denominator is named for the same reason.
    ``calculate_vega_sufficiency_pct`` normalizes by total portfolio value
    (options **plus** underlying), which on a tail-hedge book is dominated
    by the equity leg — a reader assuming the option book alone would take
    this figure for something roughly two orders of magnitude larger.
    """
    band = ips_config.vega
    value = PortfolioAnalyzer(portfolio).calculate_vega_sufficiency_pct()
    verdict = (
        "within band"
        if band.sufficiency_min_pct <= value <= band.sufficiency_max_pct
        else "outside band"
    )
    return html.Div(
        [
            html.H4("Vega sufficiency"),
            html.P(
                f"The book as it stands moves {fmt.percent(value)} of total "
                "portfolio value (options plus underlying) per +10 vol "
                f"points, against an IPS band of "
                f"{fmt.percent(band.sufficiency_min_pct)}-"
                f"{fmt.percent(band.sufficiency_max_pct)} ({verdict}). "
                "This describes the current book, not the candidate sized "
                "above.",
                className="plain-language",
            ),
            band_bar(
                value=value,
                low=band.sufficiency_min_pct,
                high=band.sufficiency_max_pct,
            ),
        ],
        id="vega-sufficiency",
    )


def _sizing_panel_view(
    result: HedgeSizingResult,
    ips_config: IpsConfig,
) -> Component:
    """Render one sized candidate: the rationale first, then the answer.

    The intrinsic floor is a labelled conservative lower bound, surfaced only
    when the IPS opts in (``convexity.crash_floor_reported``) and never the
    headline — it reads far below the repriced payoff (2.5x against 17.5x in
    the handbook's worked example), so a program may reasonably keep it off
    the page rather than risk it being read as the protection on offer. See
    ``docs/repricing-methodology.md`` §3/§5.
    """
    conv = ips_config.convexity
    carry_verdict = "within" if result.within_budget else "over"
    convexity_verdict = "within" if result.meets_convexity_target else "over"
    intrinsic_floor_text = (
        " (intrinsic floor "
        + fmt.currency(result.per_contract_intrinsic_floor, decimals=2)
        + ")"
        if conv.crash_floor_reported
        else ""
    )
    return html.Div(
        [
            html.H4("Rationale"),
            html.P(
                f"Book notional {fmt.currency(result.book_notional)} x "
                f"beta {result.portfolio_beta:.2f} = beta-adjusted "
                f"notional {fmt.currency(result.beta_adjusted_notional)}. "
                "The hedge must recover "
                f"{fmt.currency(result.required_crash_offset)} beyond the "
                "drawdown tolerance at the IPS crash.",
                className="plain-language",
            ),
            html.H4("Candidate economics"),
            html.P(
                f"{result.candidate_pct_otm:.1f}% OTM, "
                f"{result.candidate_maturity_years:.2f}y to expiry — "
                "crash payoff "
                f"{fmt.currency(result.per_contract_payoff, decimals=2)}"
                f"/contract{intrinsic_floor_text}, "
                f"carry {fmt.currency(result.per_contract_carry, decimals=2)}"
                "/contract/year.",
                className="plain-language",
            ),
            html.H4("Sizing"),
            html.P(
                f"{result.contracts_needed:,} contracts needed — implied "
                f"annual carry {fmt.currency(result.implied_annual_carry)} "
                f"vs {fmt.currency(result.carry_budget)} budget "
                f"({carry_verdict} budget, headroom "
                f"{fmt.signed_currency(result.carry_headroom)}; max "
                f"affordable {result.max_affordable_contracts:,} contracts).",
            ),
            band_bar(
                value=result.implied_annual_carry,
                low=0.0,
                high=result.carry_budget,
            ),
            html.P(
                "Achieved convexity "
                f"{fmt.percent(result.achieved_convexity_pct)} vs "
                f"{fmt.percent(conv.target_min_pct)}-"
                f"{fmt.percent(conv.target_max_pct)} target "
                f"({convexity_verdict} target).",
            ),
            band_bar(
                value=result.achieved_convexity_pct,
                low=conv.target_min_pct,
                high=conv.target_max_pct,
            ),
        ],
    )


def _render_sizing_panel_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    pct_otm: float | None,
    maturity_years: float | None,
    vol_override: float | None,
) -> Component:
    """Render the sizing panel: the candidate, then the book's vega reading.

    The vega-sufficiency block is a sibling of the candidate rather than
    part of :func:`_sizing_panel_view`, and is rendered *whatever* the
    candidate does. It depends on neither the dials nor an underlying
    position, so folding it into the candidate's own render would let an
    unfinished dial or an empty book take Part X #4 off the page again —
    which is the regression this restores.
    """
    candidate: Component
    if pct_otm is None or maturity_years is None:
        candidate = _incomplete(
            "Enter a strike (% OTM) and a maturity (years) to size a "
            "candidate hedge.",
        )
    else:

        def _build() -> Component:
            result = size_hedge(
                portfolio,
                ips_config,
                candidate_pct_otm=pct_otm,
                candidate_maturity_years=maturity_years,
                vol=vol_override,
            )
            return _sizing_panel_view(result, ips_config)

        candidate = _safe_render(_build, blocked_hint=_SIZING_BLOCKED_HINT)

    return html.Div(
        [
            candidate,
            _safe_render(
                lambda: _vega_sufficiency_block(portfolio, ips_config),
            ),
        ],
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    basis_crash_skew: str,
) -> html.Div:
    """Build the Sizing Workbench panel.

    #316: the maturity dial's initial value comes from policy (entry
    tenor), not a hardcoded 0.5y.
    """
    sizing_maturity_default = ips_config.maturity_selection.entry_tenor_years
    return html.Div(
        [
            html.H3(["Sizing workbench", basis_chip(basis_crash_skew)]),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Strike (% OTM)"),
                            html.Div(
                                [
                                    dcc.Input(
                                        id="sizing-pct-otm",
                                        type="number",
                                        value=_DEFAULT_SIZING_PCT_OTM,
                                        debounce=True,
                                    ),
                                    html.Span(
                                        "%",
                                        className="input-suffix",
                                    ),
                                ],
                                className="input-with-suffix",
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Maturity (years)"),
                            dcc.Input(
                                id="sizing-maturity-years",
                                type="number",
                                value=sizing_maturity_default,
                                debounce=True,
                            ),
                        ],
                        className="editor-field",
                    ),
                    html.Div(
                        [
                            html.Label("Vol override (optional)"),
                            dcc.Input(
                                id="sizing-vol-override",
                                type="number",
                                debounce=True,
                                # #356: blank means "using the portfolio
                                # default", not "failed to load" — nothing
                                # at rest distinguished the two.
                                placeholder="auto",
                            ),
                        ],
                        className="editor-field",
                    ),
                ],
                className="editor-form",
            ),
            html.Div(
                _render_sizing_panel_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                    pct_otm=_DEFAULT_SIZING_PCT_OTM,
                    maturity_years=sizing_maturity_default,
                    vol_override=None,
                ),
                id="plan-sizing-panel",
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the Sizing Workbench panel's re-render callback."""

    @app.callback(
        Output("plan-sizing-panel", "children"),
        Input(BOOK_VERSION_STORE, "data"),
        Input("sizing-pct-otm", "value"),
        Input("sizing-maturity-years", "value"),
        Input("sizing-vol-override", "value"),
    )
    def _render_sizing_panel(
        _version: int,
        pct_otm: float | None,
        maturity_years: float | None,
        vol_override: float | None,
    ) -> Component:
        return _render_sizing_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            pct_otm=pct_otm,
            maturity_years=maturity_years,
            vol_override=vol_override,
        )
