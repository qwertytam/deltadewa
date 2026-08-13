"""Hedge efficiency: crash payoff per unit of annual carry.

The handbook's headline "is this hedge worth the money" figure, and the one
Part X metric that had no home function anywhere in the codebase. Sits beside
:func:`~deltadewa.analysis.carry.carry_vs_budget`, whose shape it follows: a
keyword-only free function over already-computed numbers, returning a frozen
dataclass. No portfolio argument and no repricing — the caller supplies the
crash payoff it already has.

**Part X items #5 and #15 are the same number here, not two metrics.** The
handbook states the ratio twice:

- ``Hedge Efficiency = Crash payoff / Annual carry`` in dollars, item #15
  (handbook `HER Metric
  <https://github.com/qwertytam/deltadewa-handbook/blob/main/HANDBOOK.md#her-metric>`_),
  and
- ``Carry-Convexity Ratio = Convexity / Carry`` in percentages, item #5
  (handbook `Mathematical Definition of the Ratio
  <https://github.com/qwertytam/deltadewa-handbook/blob/main/HANDBOOK.md#mathematical-definition-of-the-ratio>`_),
  also given as ``Crash payoff % / Annual carry %`` in the same HER Metric
  section above.

In this codebase both percentages normalize by the *same* protected book —
:func:`~deltadewa.analysis.crash_repricing.crash_convexity_pct` and
:func:`~deltadewa.analysis.carry.carry_vs_budget` each divide by
``abs(underlying_quantity * spot)`` — so the normalizer cancels and the
percentage form reduces exactly to the dollar form. One function serves both
items. (The handbook's own `Example of a Full Dashboard
<https://github.com/qwertytam/deltadewa-handbook/blob/main/HANDBOOK.md#example-of-a-full-dashboard>`_
prints ``Convexity/carry ratio: 7.5`` and ``Hedge efficiency: 6.3x`` as if
they were different figures; on a common normalizer they cannot be.)

The band is policy, not presentation: it answers a mandate question ("is this
hedge worth the money"), so it comes from ``ips.yaml``'s ``convexity`` section
and is never defaulted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EfficiencyVerdict(StrEnum):
    """Reading of the efficiency ratio against the IPS band.

    Names follow the handbook's own `Interpretation of the Ratio
    <https://github.com/qwertytam/deltadewa-handbook/blob/main/HANDBOOK.md#interpretation-of-the-ratio>`_
    table: below the band is a poor hedge, inside it is acceptable, above it
    is attractive.
    """

    POOR = "POOR"
    ACCEPTABLE = "ACCEPTABLE"
    ATTRACTIVE = "ATTRACTIVE"


@dataclass(frozen=True)
class HedgeEfficiency:
    """Crash payoff per dollar of annual carry, read against the IPS band.

    Attributes:
        ratio: ``crash_payoff / abs(annual_carry)`` — dimensionless dollars
            of crash payoff bought per dollar of annual carry. ``None`` when
            ``annual_carry`` is zero: the ratio is then undefined, not zero
            (same convention as
            :attr:`~deltadewa.analysis.monitor_scenario.ScenarioResult.offset_ratio`).
        crash_payoff: The payoff term, verbatim from the argument. Signed —
            a hedge that *loses* value in the crash keeps its negative sign
            rather than being clamped.
        annual_carry: The carry term, verbatim from the argument
            (negative = cost; sign-preserving, unlike the denominator of
            ``ratio`` — matching
            :attr:`~deltadewa.analysis.carry.CarryBudgetStatus.theta_annual`).
        band_min_ratio: IPS lower band, echoed back so a renderer never has
            to re-read policy to label the figure.
        band_max_ratio: IPS upper band, echoed back likewise.
        verdict: The reading against the band, or ``None`` exactly when
            ``ratio`` is ``None``.

    """

    ratio: float | None
    crash_payoff: float
    annual_carry: float
    band_min_ratio: float
    band_max_ratio: float
    verdict: EfficiencyVerdict | None


def _classify(
    ratio: float,
    band_min_ratio: float,
    band_max_ratio: float,
) -> EfficiencyVerdict:
    """Read *ratio* against the band, boundaries inclusive.

    Exactly at ``band_min_ratio`` or ``band_max_ratio`` is ``ACCEPTABLE`` —
    the same inclusive-boundary convention
    :func:`~deltadewa.analysis.decision_matrix._classify_adequacy` uses for
    the convexity band.
    """
    if ratio < band_min_ratio:
        return EfficiencyVerdict.POOR
    if ratio > band_max_ratio:
        return EfficiencyVerdict.ATTRACTIVE
    return EfficiencyVerdict.ACCEPTABLE


def hedge_efficiency(
    *,
    crash_payoff: float,
    annual_carry: float,
    band_min_ratio: float,
    band_max_ratio: float,
) -> HedgeEfficiency:
    """Crash payoff per unit of annual carry, read against the IPS band.

    Args:
        crash_payoff: Hedge value gained in the crash scenario, in dollars
            (e.g. ``ScenarioResult.hedge_gain``). Signed — negative means
            the hedge loses value in the crash, which is a real reading and
            is preserved, not clamped.
        annual_carry: Net annual theta in dollars (sign-agnostic; ``abs`` is
            taken internally, since carry is a cost measured as a magnitude —
            the same treatment
            :func:`~deltadewa.analysis.carry.carry_vs_budget` gives it).
        band_min_ratio: IPS lower band — below this the hedge reads POOR.
        band_max_ratio: IPS upper band — above this it reads ATTRACTIVE.

    Returns:
        The ratio, its inputs, the band, and the verdict. ``ratio`` and
        ``verdict`` are both ``None`` when ``annual_carry`` is zero.

    Raises:
        ValueError: If ``band_min_ratio > band_max_ratio``. The IPS loader
            rejects this too; the guard is here so a hand-built band cannot
            silently produce a verdict no value can satisfy.

    """
    if band_min_ratio > band_max_ratio:
        msg = (
            f"band_min_ratio ({band_min_ratio}) must be <= band_max_ratio "
            f"({band_max_ratio})"
        )
        raise ValueError(msg)

    if annual_carry == 0:
        return HedgeEfficiency(
            ratio=None,
            crash_payoff=crash_payoff,
            annual_carry=annual_carry,
            band_min_ratio=band_min_ratio,
            band_max_ratio=band_max_ratio,
            verdict=None,
        )

    ratio = crash_payoff / abs(annual_carry)
    return HedgeEfficiency(
        ratio=ratio,
        crash_payoff=crash_payoff,
        annual_carry=annual_carry,
        band_min_ratio=band_min_ratio,
        band_max_ratio=band_max_ratio,
        verdict=_classify(ratio, band_min_ratio, band_max_ratio),
    )
