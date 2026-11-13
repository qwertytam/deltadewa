"""PLANNING zone: the Ladder composer -- score a blend of strikes as one unit.

Handbook `Strike Selection
<https://qwertytam.github.io/deltadewa-handbook/part-7/strike-selection/>`_
asks whether a *ladder* -- layers of protection at several strikes, 35/40/25
across 20/30/40% OTM -- trades convexity against carry better than a single
strike, and how it covers the crash spectrum. The Strike candidates table
above answers a different question (each row alone), so this panel composes
rungs and weights, sizes them as one ladder, and shows it beside the live
book (#410, 8d).

The panel is a presentation layer. Sizing, the shadow book and the depth
profile come from :mod:`deltadewa.analysis.ladder`; every grade comes from
:func:`deltadewa.app.compliance.scorecard`, the same call that grades the
live book -- there is no convexity or band comparison written out here.

Input format: ``pct@years:weight, ...`` (``20@1.5:35, 30@1.5:40``).
``@years`` defaults to the program's entry tenor and ``:weight`` to equal
weights; weights are *relative* (shares of contract count), so 35/40/25 and
7/8/5 are the same ladder.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Final, NamedTuple

from dash import (
    ALL,
    Input,
    NoUpdate,
    Output,
    State,
    ctx,
    dcc,
    html,
    no_update,
)

from deltadewa.analysis.ladder import (
    LadderSource,
    ProposedLadder,
    RungSpec,
    book_convexity_by_depth,
    ladder_depth_profile,
    ladder_from_book,
    legs_outside_ladder,
    materialize_ladder,
    profile_depths,
    size_ladder,
)
from deltadewa.analysis.sizing import GROSS_SIZING_NOTE
from deltadewa.app import format as fmt
from deltadewa.app.basis_chip import basis_chip
from deltadewa.app.compliance import Scorecard, scorecard
from deltadewa.app.panel_guard import NoticeKind, panel_notice, status_message
from deltadewa.app.panel_guard import incomplete_notice as _incomplete
from deltadewa.app.panel_guard import safe_render as _safe_render
from deltadewa.app.section_nav import SectionSpec

from ..book import BOOK_VERSION_STORE
from .ladder import ADD_RUNG_TYPE

if TYPE_CHECKING:
    from collections.abc import Sequence

    from dash.development.base_component import Component

    from deltadewa.analysis.hedge_efficiency import HedgeEfficiency
    from deltadewa.analysis.ladder import SizedLadder
    from deltadewa.app.factory import ProgramDashApp
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.reporting.program_report import (
        IpsComplianceRow,
        IpsComplianceSection,
    )

_logger = logging.getLogger(__name__)

#: #357: this panel's TOC entry and heading id, from one source.
SECTION: Final[SectionSpec] = SectionSpec(
    anchor_id="section-ladder-composer",
    title="Ladder composer",
)

# #326: safe_render's BLOCKED remediation pointer -- size_ladder raises
# ValueError on a book with no underlying position.
_COMPOSER_BLOCKED_HINT = (
    "Set the underlying spot and quantity in the BOOK zone; a ladder is "
    "sized against them."
)

_EMPTY_HEADLINE = "No rungs yet."
_EMPTY_DETAIL = (
    "Load the IPS ladder or the current book, add strikes from the Strike "
    "candidates table above, or type rungs as pct@years:weight, e.g. "
    "20@1.5:35, 30@1.5:40, 40@1.5:25."
)

# The one thing a reader most needs to know about the convexity row. Every
# ladder here is sized to the same crash-offset target (on gross repriced
# value), so its convexity at the IPS depth lands near |crash| - drawdown
# tolerance whatever its shape, less premium drag (the row is net of
# premium, and premium does depend on shape) and rounding. A FAIL therefore
# usually says the IPS's own tolerance and band do not line up, not that the
# ladder is badly shaped; carry, efficiency and the depth table tell
# ladders apart.
_CONVEXITY_CAVEAT = (
    "Every ladder here is sized to the same crash-offset target, so "
    "convexity at the IPS depth is close for all of them; it differs only "
    "by premium paid and rounding. A FAIL there usually means your drawdown "
    "tolerance and convexity band do not line up, not that this ladder is "
    "badly shaped. Carry, efficiency and the depth table are what separate "
    "one ladder from another."
)

_DEPTH_FOOTNOTE = (
    "Only the IPS depth is compared with the convexity band: the handbook "
    "states the band at one depth, and a figure at any other depth cannot "
    "be read against it. The other depths are shown, not graded."
)

_RUNG_PATTERN: Final = re.compile(
    r"^\s*(?P<pct>-?\d+(?:\.\d+)?)"
    r"\s*(?:@\s*(?P<years>\d+(?:\.\d+)?))?"
    r"\s*(?::\s*(?P<weight>\d+(?:\.\d+)?))?\s*$",
)

# Two volatilities closer than this are the same basis (float noise, not a
# difference a reader could act on).
_VOL_BASIS_TOLERANCE: Final[float] = 1e-9

_RUNGS_INPUT_ID: Final[str] = "ladder-composer-rungs"
_LOAD_IPS_ID: Final[str] = "ladder-composer-load-ips"
_LOAD_BOOK_ID: Final[str] = "ladder-composer-load-book"
_PANEL_ID: Final[str] = "plan-ladder-composer-panel"
_STATUS_ID: Final[str] = "ladder-composer-status"


# ---------------------------------------------------------------------------
# Text <-> rungs
# ---------------------------------------------------------------------------


def _num(value: float, decimals: int) -> str:
    """Format *value* with at most *decimals* places, no trailing zeros."""
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def _format_rungs(rungs: Sequence[RungSpec]) -> str:
    """Write rungs back as ``pct@years:weight, ...`` for the input."""
    return ", ".join(
        f"{_num(r.pct_otm, 2)}@{_num(r.maturity_years, 3)}:{_num(r.weight, 2)}"
        for r in rungs
    )


def _parse_rungs(
    raw: str | None,
    *,
    default_tenor: float,
) -> tuple[ProposedLadder | None, str | None]:
    """Parse the input text into a ladder.

    Returns:
        ``(ladder, None)`` on success, ``(None, None)`` for blank text, and
        ``(None, message)`` for text that does not describe a valid ladder
        -- a dial-parsing failure, handled before anything is priced.

    """
    if raw is None or not raw.strip():
        return None, None
    parts = [part for part in raw.split(",") if part.strip()]
    if not parts:
        # Only separators ("," or " , "): nothing was typed, same as blank.
        return None, None
    specs: list[RungSpec] = []
    for part in parts:
        match = _RUNG_PATTERN.match(part)
        if match is None:
            return None, (
                f"Could not read {part.strip()!r}. Write each rung as "
                "pct@years:weight, e.g. 20@1.5:35."
            )
        try:
            specs.append(
                RungSpec(
                    pct_otm=float(match["pct"]),
                    maturity_years=(
                        float(match["years"])
                        if match["years"] is not None
                        else default_tenor
                    ),
                    weight=(
                        float(match["weight"])
                        if match["weight"] is not None
                        else 1.0
                    ),
                ),
            )
        except ValueError as exc:
            return None, f"{part.strip()!r}: {exc}"
    try:
        ladder = ProposedLadder(
            rungs=tuple(specs),
            source=LadderSource.OPERATOR,
        )
    except ValueError as exc:
        return None, str(exc)
    return ladder, None


def _seed_text(portfolio: OptionPortfolio, ips_config: IpsConfig) -> str:
    """Return the composer's starting rungs: IPS ladder, else book, else none.

    In that order -- the program's stated intent first, what it happens to
    hold second. The live book is always shown as the baseline regardless
    of which seeds the input.
    """
    if ips_config.strike_ladder is not None:
        return _format_rungs(
            ProposedLadder.from_ips(
                ips_config.strike_ladder,
                ips_config.maturity_selection,
            ).rungs,
        )
    held = ladder_from_book(portfolio)
    return _format_rungs(held.rungs) if held is not None else ""


def _safe_seed_text(portfolio: OptionPortfolio, ips_config: IpsConfig) -> str:
    """Return :func:`_seed_text`, or blank text if the book defeats it.

    ``layout()`` runs while the whole page is being built, outside any
    panel's ``safe_render``, so an exception here would take /design down
    rather than degrade one panel. A book that cannot be read as a ladder
    (a zero spot, say) starts the composer blank; the panel below still
    explains itself through its own guarded render.
    """
    try:
        return _seed_text(portfolio, ips_config)
    except Exception:  # pylint: disable=broad-exception-caught
        # Logged, like safe_render's own swallow: the blank seed renders
        # "No rungs yet", which is only honest if the server log says why.
        _logger.exception("Could not seed the ladder composer")
        return ""


class _Update(NamedTuple):
    """What a control click does to the rungs input.

    ``text`` is the input's next value, or ``None`` to leave it alone.
    ``note`` says why a click changed nothing -- a no-op is never silent.
    """

    text: str | None
    note: str | None = None


def _append_rung(
    current: str | None,
    *,
    pct_otm: float,
    maturity_years: float,
    default_tenor: float,
) -> _Update:
    """Add one strike to the typed rungs.

    The new rung takes the average of the existing weights (weights are
    relative, so a fixed ``1`` would be a rounding error beside 35/40/25).
    A strike already in the ladder, or text that does not parse, is left
    untouched rather than guessed at -- and the :class:`_Update` says so.
    """
    ladder, error = _parse_rungs(current, default_tenor=default_tenor)
    if error is not None:
        return _Update(None, f"Fix the rungs text before adding: {error}")
    try:
        if ladder is None:
            return _Update(
                _format_rungs([RungSpec(pct_otm, maturity_years, 1.0)]),
            )
        if any(
            abs(r.pct_otm - pct_otm) < 0.005
            and abs(r.maturity_years - maturity_years) < 0.0005
            for r in ladder.rungs
        ):
            return _Update(None, "That strike is already in the ladder.")
        mean_weight = sum(r.weight for r in ladder.rungs) / len(ladder.rungs)
        return _Update(
            _format_rungs(
                [*ladder.rungs, RungSpec(pct_otm, maturity_years, mean_weight)],
            ),
        )
    except ValueError as exc:
        return _Update(None, f"Could not add that strike: {exc}")


def _next_rungs_text(
    trigger: str | dict[str, float] | None,
    *,
    current: str | None,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> _Update:
    """Decide the input's next text from whichever control fired.

    ``text`` is ``None`` when the click should change nothing (an unknown
    trigger, nothing to load, a duplicate strike); ``note`` then says why.
    """
    if trigger == _LOAD_IPS_ID:
        if ips_config.strike_ladder is None:
            return _Update(None, "ips.yaml has no strike_ladder: section.")
        return _Update(
            _format_rungs(
                ProposedLadder.from_ips(
                    ips_config.strike_ladder,
                    ips_config.maturity_selection,
                ).rungs,
            ),
        )
    if trigger == _LOAD_BOOK_ID:
        held = ladder_from_book(portfolio)
        if held is None:
            return _Update(None, "The book holds no live long puts to load.")
        return _Update(_format_rungs(held.rungs))
    if isinstance(trigger, dict):
        return _append_rung(
            current,
            pct_otm=trigger["pct_otm"],
            maturity_years=trigger["maturity"],
            default_tenor=ips_config.maturity_selection.entry_tenor_years,
        )
    return _Update(None)


def _status(note: str | None) -> Component | str:
    """Render a click's note, or clear the status line."""
    return "" if note is None else html.P(note, className="unsolvable-note")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _badge(passes: bool | None) -> html.Span:
    """Build a PASS/FAIL badge in the compliance strip's own classes.

    ``None`` is an unmeasured reading: grey and worded as such, because a
    metric that could not be measured must not read as one that is fine,
    nor as one that failed.
    """
    if passes is None:
        return html.Span(
            "N/A",
            className="verdict-badge verdict-badge--unavailable",
            title="Not measured: neither a pass nor a breach.",
        )
    return html.Span(
        "PASS" if passes else "FAIL",
        className=(
            "verdict-badge verdict-badge--ok"
            if passes
            else "verdict-badge verdict-badge--action"
        ),
    )


def _efficiency_text(efficiency: HedgeEfficiency) -> str:
    """Write the efficiency ratio and its band reading in words."""
    if efficiency.ratio is None or efficiency.verdict is None:
        return "n/a (no carry)"
    return f"{efficiency.ratio:.1f}x ({efficiency.verdict.value.lower()})"


def _convexity_row(
    compliance: IpsComplianceSection,
) -> IpsComplianceRow | None:
    """Pick the crash-convexity row out of a compliance section."""
    return next(
        (r for r in compliance.rows if r.metric.startswith("Crash convexity")),
        None,
    )


def _scorecard_table(
    baseline: Scorecard,
    proposal: Scorecard,
    *,
    ips_config: IpsConfig,
) -> html.Table:
    """Grade the book and the ladder side by side, with one function."""
    rows = [
        html.Tr(
            [
                html.Td(base.metric),
                html.Td(base.target),
                html.Td(
                    [base.actual, _badge(base.passes)],
                    className="scorecard-cell",
                ),
                html.Td(
                    [prop.actual, _badge(prop.passes)],
                    className="scorecard-cell",
                ),
            ],
        )
        for base, prop in zip(
            baseline.compliance.rows,
            proposal.compliance.rows,
            strict=True,
        )
    ]
    conv = ips_config.convexity
    rows.append(
        html.Tr(
            [
                html.Td("Hedge efficiency (crash gain per $ of carry)"),
                html.Td(
                    f"{conv.efficiency_min_ratio:g}-"
                    f"{conv.efficiency_max_ratio:g}x",
                ),
                html.Td(_efficiency_text(baseline.efficiency)),
                html.Td(_efficiency_text(proposal.efficiency)),
            ],
        ),
    )
    # The compliance section's own overall verdict -- the one /monitor's
    # strip and the digest render -- rather than leaving it computed and
    # dropped. Efficiency is a reading, not a row, so it is not in it.
    rows.append(
        html.Tr(
            [
                html.Td("All IPS checks above"),
                html.Td("every row passes"),
                html.Td(
                    _badge(baseline.compliance.all_pass),
                    className="scorecard-cell",
                ),
                html.Td(
                    _badge(proposal.compliance.all_pass),
                    className="scorecard-cell",
                ),
            ],
            className="depth-row--ips",
        ),
    )
    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Metric"),
                        html.Th("IPS target"),
                        html.Th("Current book (as held)"),
                        html.Th("This ladder (in place of the book's options)"),
                    ],
                ),
            ),
            html.Tbody(rows),
        ],
        className="planning-table",
    )


def _rung_table(sized: SizedLadder) -> html.Table:
    """Tabulate the sized rungs: strike, tenor, weight, contracts, cost."""
    weights = sized.ladder.normalized_weights
    total = sized.total_contracts
    rows = [
        html.Tr(
            [
                html.Td(f"{rung.spec.pct_otm:.1f}% OTM"),
                html.Td(f"{rung.metrics.strike:,.0f}"),
                html.Td(f"{rung.spec.maturity_years:.2f}y"),
                html.Td(fmt.percent(weight * 100.0), className="num"),
                html.Td(f"{rung.contracts:,}", className="num"),
                # Achieved, not asked: rounding each rung up moves it.
                html.Td(
                    fmt.percent(rung.contracts / total * 100.0)
                    if total
                    else "n/a",
                    className="num",
                ),
                html.Td(
                    fmt.currency(rung.contracts * rung.metrics.premium),
                    className="num",
                ),
                html.Td(
                    fmt.currency(
                        rung.contracts * rung.metrics.per_contract_carry,
                    ),
                    className="num",
                ),
            ],
        )
        for rung, weight in zip(sized.rungs, weights, strict=True)
    ]
    rows.append(
        html.Tr(
            [
                html.Td("Ladder"),
                html.Td(""),
                html.Td(""),
                html.Td(""),
                html.Td(f"{sized.total_contracts:,}", className="num"),
                html.Td(""),
                html.Td(
                    fmt.currency(
                        sum(
                            r.contracts * r.metrics.premium for r in sized.rungs
                        ),
                    ),
                    className="num",
                ),
                html.Td(
                    fmt.currency(sized.implied_annual_carry),
                    className="num",
                ),
            ],
            className="depth-row--ips",
        ),
    )
    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Rung"),
                        html.Th("Strike"),
                        html.Th("Tenor"),
                        html.Th("Weight asked", className="num"),
                        html.Th("Contracts", className="num"),
                        html.Th("Share held", className="num"),
                        html.Th("Premium", className="num"),
                        html.Th("Annual carry", className="num"),
                    ],
                ),
            ),
            html.Tbody(rows),
        ],
        className="planning-table",
    )


def _rung_labels(sized: SizedLadder) -> list[str]:
    """Label each rung by strike, adding the tenor where strikes repeat.

    Two rungs at one strike with different expiries would otherwise share a
    header and read as the same column.
    """
    strikes = [round(r.spec.pct_otm, 1) for r in sized.rungs]
    return [
        f"{r.spec.pct_otm:.1f}% OTM, {r.spec.maturity_years:.2f}y"
        if strikes.count(round(r.spec.pct_otm, 1)) > 1
        else f"{r.spec.pct_otm:.1f}% OTM"
        for r in sized.rungs
    ]


def _percent_or_dash(value: float | None) -> str:
    """Format a percent, or an em dash for a reading that was not measured."""
    return "\u2014" if value is None else fmt.percent(value)


def _depth_table(
    sized: SizedLadder,
    portfolio: OptionPortfolio,
    shadow: OptionPortfolio,
    proposal: Scorecard,
) -> html.Table:
    """Crash gain by depth: per rung, the ladder, and the current book."""
    shock = sized.basis.shock
    depths = profile_depths(shock)
    profile = ladder_depth_profile(
        shadow,
        sized,
        shock=shock,
        depths=depths,
    )
    baseline_pct = book_convexity_by_depth(
        portfolio,
        shock=shock,
        depths=depths,
    )
    conv_row = _convexity_row(proposal.compliance)
    rows = []
    for row, base_pct in zip(profile, baseline_pct, strict=True):
        graded: list[Component] = [html.Td("")]
        combined_pct = _percent_or_dash(row.combined_pct_of_book)
        if row.is_ips_depth and conv_row is not None:
            graded = [html.Td(_badge(conv_row.passes))]
            # The graded cell is the strip's own text, which follows the
            # referee's display rule (#434): "4.99%" beside a FAIL, never
            # "5.0%" beside it. The other depths are shown, not graded.
            combined_pct = conv_row.actual
        rows.append(
            html.Tr(
                [
                    html.Td(f"{row.shock_pct:+.0f}%"),
                    *(
                        html.Td(fmt.currency(g), className="num")
                        for g in row.rung_gains
                    ),
                    html.Td(fmt.currency(row.combined_gain), className="num"),
                    html.Td(combined_pct, className="num"),
                    html.Td(_percent_or_dash(base_pct), className="num"),
                    *graded,
                ],
                className="depth-row--ips" if row.is_ips_depth else "",
            ),
        )
    return html.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("SPX move"),
                        *(
                            html.Th(label, className="num")
                            for label in _rung_labels(sized)
                        ),
                        html.Th("Ladder gain", className="num"),
                        html.Th("Ladder, % of book", className="num"),
                        html.Th("Current book, % of book", className="num"),
                        html.Th("vs IPS band"),
                    ],
                ),
            ),
            html.Tbody(rows),
        ],
        className="planning-table",
    )


def _comparability_notes(
    portfolio: OptionPortfolio,
    ladder: ProposedLadder,
) -> list[str]:
    """Say where "Current book" and "This ladder" are not like-for-like.

    The ladder column is the ladder *in place of* the book's option legs:
    long puts only, priced at the book's volatility. "Current book" is the
    book as held. Where those differ the reader is told, rather than left
    to read two columns as one measuring stick.
    """
    notes: list[str] = []
    outside = max(legs_outside_ladder(portfolio), ladder.excluded_leg_count)
    if outside:
        notes.append(
            f"{outside} leg(s) of the current book are not live long puts "
            '(short, call or expired). "Current book" includes them; '
            '"This ladder" cannot.'
        )
    # Compared by value, not by the custom_volatility flag: a leg entered
    # explicitly at the book's own volatility (the golden book does this)
    # shares the basis, and warning there would cry wolf.
    if any(
        abs(p.option.volatility - portfolio.volatility) > _VOL_BASIS_TOLERANCE
        for p in portfolio.positions
    ):
        notes.append(
            "Some current legs are priced at their own entered volatility; "
            "every rung of the ladder is priced at the book's "
            f"{fmt.percent(portfolio.volatility * 100.0)}, so the two "
            "columns are not on one volatility basis."
        )
    return notes


def _composer_view(
    *,
    ladder: ProposedLadder,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
) -> Component:
    """Size the ladder, grade it beside the live book, and lay it out."""
    sized = size_ladder(portfolio, ips_config, ladder)
    shadow = materialize_ladder(portfolio, sized)
    baseline = scorecard(portfolio, ips_config)
    proposal = scorecard(shadow, ips_config)
    basis = sized.basis

    children: list[Component] = [
        html.P(
            "Sized as one ladder so its repriced value at the IPS crash "
            f"covers {fmt.currency(basis.required_crash_offset)} — the "
            "crash loss beyond the drawdown tolerance, the sizing "
            f"workbench's own target: {sized.total_contracts:,} contracts, "
            f"annual carry {fmt.currency(sized.implied_annual_carry)} "
            f"against a {fmt.currency(basis.carry_budget)} budget. Each "
            "rung rounds up to whole contracts, so the share held can "
            "differ a little from the weight asked for. Rungs are priced "
            "at the book's volatility "
            f"({fmt.percent(portfolio.volatility * 100.0)}). "
            + GROSS_SIZING_NOTE,
            className="plain-language",
        ),
        html.H4("Rungs"),
        _rung_table(sized),
        html.H4("Scorecard"),
        _scorecard_table(baseline, proposal, ips_config=ips_config),
        html.P(_CONVEXITY_CAVEAT, className="plain-language"),
        html.H4("Crash gain by depth"),
        _depth_table(sized, portfolio, shadow, proposal),
        html.P(_DEPTH_FOOTNOTE, className="plain-language"),
    ]
    for note in reversed(_comparability_notes(portfolio, ladder)):
        children.insert(0, html.P(note, className="unsolvable-note"))
    if basis.required_crash_offset <= 0.0:
        children.insert(
            0,
            html.P(
                "No contracts are needed: the IPS drawdown tolerance "
                "already covers the crash depth, so the required offset is "
                "$0 and an empty ladder is what sizing asks for.",
                className="unsolvable-note",
            ),
        )
    elif not sized.covers_offset:
        children.insert(
            0,
            html.P(
                "This ladder's repriced value at the IPS crash is below the "
                "required offset, so it does not cover it.",
                className="unsolvable-note",
            ),
        )
    return html.Div(children)


def _render_composer_logic(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    rungs_raw: str | None,
) -> Component:
    """Render the composer's result for the typed rungs."""
    ladder, error = _parse_rungs(
        rungs_raw,
        default_tenor=ips_config.maturity_selection.entry_tenor_years,
    )
    if error is not None:
        return _incomplete(error)
    if ladder is None:
        return panel_notice(
            _EMPTY_HEADLINE,
            kind=NoticeKind.EMPTY,
            detail=_EMPTY_DETAIL,
        )
    return _safe_render(
        lambda: _composer_view(
            ladder=ladder,
            portfolio=portfolio,
            ips_config=ips_config,
        ),
        blocked_hint=_COMPOSER_BLOCKED_HINT,
    )


def layout(
    *,
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    basis_crash_skew: str,
) -> html.Div:
    """Build the Ladder composer panel."""
    seed = _safe_seed_text(portfolio, ips_config)
    return html.Div(
        [
            html.H3(
                [SECTION.title, basis_chip(basis_crash_skew)],
                id=SECTION.anchor_id,
            ),
            html.P(
                "Compose a ladder — strikes and weights — and score the "
                "blend as one unit against the live book. Weights are "
                "shares of contract count and are relative (35/40/25 is "
                "7/8/5).",
                className="plain-language",
            ),
            html.Div(
                [
                    html.Button(
                        "Load IPS ladder",
                        id=_LOAD_IPS_ID,
                        n_clicks=0,
                        disabled=ips_config.strike_ladder is None,
                        title=(
                            "No strike_ladder: section in ips.yaml"
                            if ips_config.strike_ladder is None
                            else "Load the ladder stated in the IPS"
                        ),
                    ),
                    html.Button(
                        "Load current book",
                        id=_LOAD_BOOK_ID,
                        n_clicks=0,
                        title=(
                            "Load the shape of the long puts held now "
                            "(re-sized to the target)"
                        ),
                    ),
                ],
                className="ladder-composer-actions",
            ),
            html.Div(
                [
                    html.Label("Rungs (pct OTM @ years : weight)"),
                    dcc.Input(
                        id=_RUNGS_INPUT_ID,
                        type="text",
                        value=seed,
                        debounce=True,
                        placeholder="20@1.5:35, 30@1.5:40, 40@1.5:25",
                    ),
                ],
                className="editor-field",
            ),
            html.Div(id=_STATUS_ID),
            html.Div(
                _render_composer_logic(
                    portfolio=portfolio,
                    ips_config=ips_config,
                    rungs_raw=seed,
                ),
                id=_PANEL_ID,
            ),
        ],
        className="panel",
    )


def register(app: ProgramDashApp, *, ips_config: IpsConfig) -> None:
    """Wire the composer's input-writing and re-render callbacks."""

    @app.callback(
        Output(_RUNGS_INPUT_ID, "value"),
        Output(_STATUS_ID, "children"),
        Input(_LOAD_IPS_ID, "n_clicks"),
        Input(_LOAD_BOOK_ID, "n_clicks"),
        Input(
            {"type": ADD_RUNG_TYPE, "pct_otm": ALL, "maturity": ALL},
            "n_clicks",
        ),
        State(_RUNGS_INPUT_ID, "value"),
        prevent_initial_call=True,
    )
    def _write_rungs(
        _load_ips: int | None,
        _load_book: int | None,
        _add_clicks: list[int | None],
        current: str | None,
    ) -> tuple[str | NoUpdate, Component | str | NoUpdate]:
        # A pattern-matching ALL input fires once, with n_clicks still 0,
        # the moment new matching buttons appear in the DOM (every time the
        # candidates table re-solves) -- not just on a click. The same
        # guard the table's sort callback uses: the triggering value is the
        # real click count, so a falsy one means "just appeared".
        if not ctx.triggered or not ctx.triggered[0]["value"]:
            return no_update, no_update
        try:
            update = _next_rungs_text(
                ctx.triggered_id,
                current=current,
                portfolio=app.program_state.portfolio,
                ips_config=ips_config,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # A click that raises must say so on the page, not only in the
            # server log -- the operator would otherwise see nothing happen.
            _logger.exception("Ladder composer control failed")
            return no_update, status_message(
                "Could not update the ladder — see the server log.",
                error=True,
            )
        return (
            no_update if update.text is None else update.text,
            _status(update.note),
        )

    @app.callback(
        Output(_PANEL_ID, "children"),
        Input(BOOK_VERSION_STORE, "data"),
        Input(_RUNGS_INPUT_ID, "value"),
    )
    def _render_composer(
        _version: int,
        rungs_raw: str | None,
    ) -> Component:
        return _render_composer_logic(
            portfolio=app.program_state.portfolio,
            ips_config=ips_config,
            rungs_raw=rungs_raw,
        )
