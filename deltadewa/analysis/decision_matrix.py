"""Decision matrix and entry-timing tree for the SPX tail-hedge program.

Implements the handbook Part X.2 synthesis layer: given a
``MarketEnvironment`` (from ``analysis.market_environment``), current
hedge convexity, and an optional monetization plan, produces an
actionable ``DecisionVerdict`` (BUY / MAINTAIN / AVOID / MONETIZE /
INSUFFICIENT_DATA) and a three-step entry-timing recommendation
(VIX → skew percentile → term structure).

Never fabricates a verdict on untrustworthy data: unless ``data_quality``
is ``LIVE`` or ``CACHED``, returns ``INSUFFICIENT_DATA`` with a clear
explanation instead, while still reporting the hedge-adequacy
classification (which depends only on IPS config and portfolio convexity,
not on live market data).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from deltadewa.analysis.market_environment import (
    DataQuality,
    HedgeCostVerdict,
    TermShape,
)
from deltadewa.ips_config import (
    DEFAULT_SKEW_HIGH_PCTILE,
    DEFAULT_SKEW_LOW_PCTILE,
)

if TYPE_CHECKING:
    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.analysis.monetization import MonetizationPlan
    from deltadewa.ips_config import IpsConvexity


# Data good enough to issue a market-environment verdict on. A within-TTL
# cache hit is the normal path, not a degraded one — the values are the same
# ones the live fetch just wrote. STALE, STATIC and UNAVAILABLE are not here:
# each means the numbers are old or invented, and a verdict on those is the
# failure mode this gate exists to prevent.
_VERDICT_QUALITIES: Final[frozenset[DataQuality]] = frozenset(
    {DataQuality.LIVE, DataQuality.CACHED},
)


class DecisionVerdict(StrEnum):
    """Overall verdict from the tail-hedge decision matrix."""

    BUY = "BUY"
    MAINTAIN = "MAINTAIN"
    AVOID = "AVOID"
    MONETIZE = "MONETIZE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class HedgeAdequacy(StrEnum):
    """Classification of current convexity against the IPS target band."""

    UNDER = "UNDER"
    ADEQUATE = "ADEQUATE"
    OVER = "OVER"


@dataclass(frozen=True)
class DecisionResult:
    """Result of :func:`decision_matrix`.

    Attributes:
        verdict: The primary decision verdict.
        rationale: Human-readable explanation of the verdict.
        data_quality_note: Set when ``verdict`` is
            ``INSUFFICIENT_DATA`` to explain why a full verdict could
            not be produced.
        hedge_adequacy: Convexity classification vs the IPS band;
            always computed, even when the environment verdict is
            ``INSUFFICIENT_DATA``.
        cost_verdict: Mirrors ``market_env.hedge_cost_verdict``.
        gains_available: ``True`` when the monetization plan reports a
            positive ``value_to_harvest``.

    """

    verdict: DecisionVerdict
    rationale: str
    data_quality_note: str | None
    hedge_adequacy: HedgeAdequacy | None
    cost_verdict: HedgeCostVerdict | None
    gains_available: bool


@dataclass
class EntryTimingStep:
    """A single step in the entry-timing decision tree.

    Attributes:
        step: Sequential step number (1, 2, or 3).
        label: Name of the factor checked at this step.
        value: Observed value of the factor.
        recommendation: Guidance derived at this step.
        proceed: ``False`` when the tree stops here.

    """

    step: int
    label: str
    value: float | str | None
    recommendation: str
    proceed: bool


@dataclass(frozen=True)
class EntryTimingResult:
    """Result of :func:`entry_timing_tree`.

    Attributes:
        recommendation: Final timing recommendation string.
        should_enter: ``True`` when conditions support entering a new
            hedge position.
        steps: The path taken through the tree (1-3 steps).
        data_quality_note: Set when the tree declined due to non-LIVE
            data quality.

    """

    recommendation: str
    should_enter: bool
    steps: list[EntryTimingStep]
    data_quality_note: str | None


def _classify_adequacy(
    convexity_now_pct: float,
    ips_convexity: IpsConvexity,
) -> HedgeAdequacy:
    """Classify current convexity against the IPS target band.

    Inclusive boundaries: exactly at ``target_min_pct`` or
    ``target_max_pct`` is ``ADEQUATE``.

    Args:
        convexity_now_pct: Current convexity, in percent.
        ips_convexity: IPS convexity band configuration.

    Returns:
        ``UNDER``, ``ADEQUATE``, or ``OVER``.

    """
    if convexity_now_pct < ips_convexity.target_min_pct:
        return HedgeAdequacy.UNDER
    if convexity_now_pct > ips_convexity.target_max_pct:
        return HedgeAdequacy.OVER
    return HedgeAdequacy.ADEQUATE


def _environment_verdict(
    adequacy: HedgeAdequacy,
    cost: HedgeCostVerdict,
    gains: bool,
) -> DecisionVerdict:
    """Map (adequacy, cost, gains) to a verdict (all args non-None)."""
    if adequacy is HedgeAdequacy.UNDER:
        if cost is HedgeCostVerdict.EXPENSIVE:
            return DecisionVerdict.AVOID
        return DecisionVerdict.BUY
    # ADEQUATE or OVER: monetize only when gains are available and the
    # hedge is either over-sized or the cost justifies harvesting.
    if gains and (
        adequacy is HedgeAdequacy.OVER or cost is HedgeCostVerdict.EXPENSIVE
    ):
        return DecisionVerdict.MONETIZE
    return DecisionVerdict.MAINTAIN


def _verdict_rationale(
    verdict: DecisionVerdict,
    adequacy: HedgeAdequacy,
    cost: HedgeCostVerdict,
) -> str:
    """Build a human-readable rationale for a non-INSUFFICIENT_DATA verdict."""
    if verdict is DecisionVerdict.BUY:
        cost_word = "cheap" if cost is HedgeCostVerdict.CHEAP else "fair"
        return f"Under-hedged; protection is {cost_word} — add exposure"
    if verdict is DecisionVerdict.AVOID:
        return (
            "Under-hedged but protection is expensive"
            " — wait for a better entry (see entry-timing tree)"
        )
    if verdict is DecisionVerdict.MONETIZE:
        if adequacy is HedgeAdequacy.OVER:
            return "Over-hedged with gains available — reduce and monetize"
        return (
            "Convexity adequate; protection expensive with gains"
            " available — harvest"
        )
    # MAINTAIN
    if adequacy is HedgeAdequacy.OVER:
        return "Over-hedged but no gains to harvest — hold"
    return "Convexity within IPS band — maintain program"


def decision_matrix(
    market_env: MarketEnvironment,
    *,
    convexity_now_pct: float,
    ips_convexity: IpsConvexity,
    monetization_plan: MonetizationPlan | None = None,
) -> DecisionResult:
    """Combine market environment, convexity, and monetization into a verdict.

    Handbook Part X.2.  Verdict table (``LIVE`` data only):

    +----------+------------------+--------+-----------+
    | Adequacy | hedge_cost_verdict| gains? | Verdict   |
    +==========+==================+========+===========+
    | UNDER    | CHEAP            | any    | BUY       |
    | UNDER    | FAIR             | any    | BUY       |
    | UNDER    | EXPENSIVE        | any    | AVOID     |
    | ADEQUATE | CHEAP or FAIR    | any    | MAINTAIN  |
    | ADEQUATE | EXPENSIVE        | False  | MAINTAIN  |
    | ADEQUATE | EXPENSIVE        | True   | MONETIZE  |
    | OVER     | any              | False  | MAINTAIN  |
    | OVER     | any              | True   | MONETIZE  |
    +----------+------------------+--------+-----------+

    FAIR is treated as a hold signal: it does not block adding to an
    under-hedged book (adequacy takes priority) and does not justify
    harvesting an adequate one.

    When ``market_env.data_quality`` is not ``LIVE``, the environment
    verdict is ``INSUFFICIENT_DATA`` — synthetic or absent data should
    never drive a trading decision.  Hedge adequacy is still classified
    because it depends only on portfolio convexity and IPS policy.

    Args:
        market_env: Market environment snapshot from
            :func:`assess_market_environment`.
        convexity_now_pct: Current convexity at the IPS crash scenario,
            as a percentage (e.g. 18.0 for 18%).
        ips_convexity: IPS convexity band configuration.
        monetization_plan: Optional plan from
            :func:`build_monetization_plan`; ``value_to_harvest > 0``
            marks gains as available.

    Returns:
        A :class:`DecisionResult` with the verdict, rationale, and
        contributing factors.

    """
    adequacy = _classify_adequacy(convexity_now_pct, ips_convexity)
    gains_available = (
        monetization_plan is not None and monetization_plan.value_to_harvest > 0
    )

    if market_env.data_quality not in _VERDICT_QUALITIES:
        note = (
            f"data_quality is {market_env.data_quality}"
            " — enable live data for an environment verdict"
        )
        return DecisionResult(
            verdict=DecisionVerdict.INSUFFICIENT_DATA,
            rationale=(
                "Market environment data is not LIVE or CACHED"
                " — hedge adequacy reported; environment verdict"
                " requires trustworthy data"
            ),
            data_quality_note=note,
            hedge_adequacy=adequacy,
            cost_verdict=None,
            gains_available=gains_available,
        )

    cost = market_env.hedge_cost_verdict
    if cost is None:
        return DecisionResult(
            verdict=DecisionVerdict.INSUFFICIENT_DATA,
            rationale=(
                "hedge_cost_verdict is None despite usable data quality"
            ),
            data_quality_note=(
                "MarketEnvironment.hedge_cost_verdict is None"
                " — provider may be missing skew or term-structure data"
            ),
            hedge_adequacy=adequacy,
            cost_verdict=None,
            gains_available=gains_available,
        )

    verdict = _environment_verdict(adequacy, cost, gains_available)
    return DecisionResult(
        verdict=verdict,
        rationale=_verdict_rationale(verdict, adequacy, cost),
        data_quality_note=None,
        hedge_adequacy=adequacy,
        cost_verdict=cost,
        gains_available=gains_available,
    )


def entry_timing_tree(
    market_env: MarketEnvironment,
    *,
    vix_very_high: float,
    vix_caution: float,
    vix_low: float,
    skew_high: float = DEFAULT_SKEW_HIGH_PCTILE / 100.0,
    skew_low: float = DEFAULT_SKEW_LOW_PCTILE / 100.0,
) -> EntryTimingResult:
    """Walk the three-step entry-timing tree for new hedge purchases.

    Handbook Part X.2 entry-timing checks, in order:

    1. **VIX level** — stop if elevated (> ``vix_caution``) or extreme
       (> ``vix_very_high``).
    2. **Skew percentile** — stop if expensive vs history
       (> ``skew_high``).
    3. **Term structure shape** — notes roll-cost implication but does
       not stop entry.

    Unit conventions:

    - ``vix_*`` thresholds are in vol points (e.g. 40.0 = VIX at 40),
      matching ``MarketEnvironment.vix``.
    - ``skew_high`` / ``skew_low`` are 0-1 fractions, matching
      ``MarketEnvironment.skew_percentile`` (e.g. 0.75 = the 75th percentile).

    Declines on non-``LIVE`` ``data_quality``; returns
    ``should_enter=False`` with a ``data_quality_note``.  Also returns
    ``INSUFFICIENT_DATA`` when a required field is ``None`` despite
    ``LIVE`` quality, including as many completed steps as possible.

    Args:
        market_env: Market environment snapshot.
        vix_very_high: VIX level above which existing hedges should be
            monetised and no new purchases made. **Required, no default**
            (M2.8 — the M1.4/M1.5 fail-loud pattern): source from
            ``IpsMarketEnvironment.vix_very_high``, never a hardcoded
            literal at the call site.
        vix_caution: VIX level above which new purchases should be
            avoided except for required rolls. **Required** — see
            ``IpsMarketEnvironment.vix_caution``.
        vix_low: VIX level at or below which accumulation urgency
            increases. **Required** — see ``IpsMarketEnvironment.vix_low``.
        skew_high: Skew percentile (0-1) above which protection is
            expensive vs history. Defaults to the IPS single source
            ``DEFAULT_SKEW_HIGH_PCTILE`` (as a 0-1 fraction).
        skew_low: Skew percentile (0-1) below which protection is
            cheap vs history. Defaults to ``DEFAULT_SKEW_LOW_PCTILE``
            (as a 0-1 fraction).

    Returns:
        An :class:`EntryTimingResult` with the terminal recommendation,
        a ``should_enter`` flag, and the steps taken.

    """
    if market_env.data_quality not in _VERDICT_QUALITIES:
        note = (
            f"data_quality is {market_env.data_quality}"
            " — enable live data for an entry-timing recommendation"
        )
        return EntryTimingResult(
            recommendation="INSUFFICIENT_DATA",
            should_enter=False,
            steps=[],
            data_quality_note=note,
        )

    steps: list[EntryTimingStep] = []

    # ── Step 1: VIX level ─────────────────────────────────────────────
    vix = market_env.vix
    if vix is None:
        steps.append(
            EntryTimingStep(
                step=1,
                label="VIX",
                value=None,
                recommendation=("VIX unavailable despite LIVE data quality"),
                proceed=False,
            ),
        )
        return EntryTimingResult(
            recommendation="INSUFFICIENT_DATA",
            should_enter=False,
            steps=steps,
            data_quality_note=(
                "MarketEnvironment.vix is None with LIVE data_quality"
            ),
        )

    if vix > vix_very_high:
        rec = (
            "Monetize existing hedges;"
            " do not buy new protection at this VIX level"
        )
        steps.append(
            EntryTimingStep(
                step=1,
                label="VIX",
                value=vix,
                recommendation=rec,
                proceed=False,
            ),
        )
        return EntryTimingResult(
            recommendation=rec,
            should_enter=False,
            steps=steps,
            data_quality_note=None,
        )

    if vix > vix_caution:
        rec = (
            "Caution — avoid new purchases unless a roll is required;"
            " if rolling, reduce size and consider put spreads"
        )
        steps.append(
            EntryTimingStep(
                step=1,
                label="VIX",
                value=vix,
                recommendation=rec,
                proceed=False,
            ),
        )
        return EntryTimingResult(
            recommendation=rec,
            should_enter=False,
            steps=steps,
            data_quality_note=None,
        )

    urgency = " — increased urgency to accumulate" if vix <= vix_low else ""
    step1_rec = f"Vol regime moderate to low{urgency}; proceed to skew check"
    steps.append(
        EntryTimingStep(
            step=1,
            label="VIX",
            value=vix,
            recommendation=step1_rec,
            proceed=True,
        ),
    )

    # ── Step 2: Skew percentile (0-1 fraction) ────────────────────────
    skew = market_env.skew_percentile
    if skew is None:
        steps.append(
            EntryTimingStep(
                step=2,
                label="skew_percentile",
                value=None,
                recommendation=(
                    "Skew percentile unavailable despite LIVE data quality"
                ),
                proceed=False,
            ),
        )
        return EntryTimingResult(
            recommendation="INSUFFICIENT_DATA",
            should_enter=False,
            steps=steps,
            data_quality_note=(
                "MarketEnvironment.skew_percentile is None"
                " with LIVE data_quality"
            ),
        )

    if skew > skew_high:
        rec = "Buy selectively or defer — deep OTM puts expensive vs history"
        steps.append(
            EntryTimingStep(
                step=2,
                label="skew_percentile",
                value=skew,
                recommendation=rec,
                proceed=False,
            ),
        )
        return EntryTimingResult(
            recommendation=rec,
            should_enter=False,
            steps=steps,
            data_quality_note=None,
        )

    step2_rec = (
        "Accumulate aggressively — protection historically cheap"
        if skew < skew_low
        else "Normal accumulation pace"
    )
    steps.append(
        EntryTimingStep(
            step=2,
            label="skew_percentile",
            value=skew,
            recommendation=step2_rec,
            proceed=True,
        ),
    )

    # ── Step 3: Term structure ─────────────────────────────────────────
    shape = market_env.term_shape
    if shape is None:
        steps.append(
            EntryTimingStep(
                step=3,
                label="term_shape",
                value=None,
                recommendation=(
                    "Term structure unavailable despite LIVE data quality"
                ),
                proceed=False,
            ),
        )
        return EntryTimingResult(
            recommendation="INSUFFICIENT_DATA",
            should_enter=False,
            steps=steps,
            data_quality_note=(
                "MarketEnvironment.term_shape is None with LIVE data_quality"
            ),
        )

    if shape is TermShape.BACKWARDATION:
        step3_rec = (
            "Term in backwardation — roll costs lower;"
            " consider refreshing the ladder earlier"
        )
    elif shape is TermShape.CONTANGO:
        step3_rec = (
            "Term in contango — roll costs higher;"
            " consider reducing roll frequency or size"
        )
    else:
        step3_rec = "Term flat — normal conditions; proceed as planned"

    steps.append(
        EntryTimingStep(
            step=3,
            label="term_shape",
            value=str(shape),
            recommendation=step3_rec,
            proceed=True,
        ),
    )
    return EntryTimingResult(
        recommendation=step3_rec,
        should_enter=True,
        steps=steps,
        data_quality_note=None,
    )
