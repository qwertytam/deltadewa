"""Staged hedge-gain monetization planner — handbook Part VIII §3729.

Evaluates the IPS monetization schedule against the current hedge book and
produces a recommended sell programme.  No positions are altered; every
output is advisory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from deltadewa.analysis.market_environment import RegimeLabel
from deltadewa.constants import OptionType

if TYPE_CHECKING:
    from deltadewa.analysis.market_environment import MarketEnvironment
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MonetizationStepStatus:
    """One IPS schedule step annotated with its trigger status.

    Attributes:
        gain_pct: Threshold gain at which this step activates (mirrors
            ``IpsMonetizationStep.gain_pct``).
        sell_pct: Fraction of hedge value to sell at this step (mirrors
            ``IpsMonetizationStep.sell_pct``).
        triggered: ``True`` when current hedge gain >= gain_pct.

    """

    gain_pct: float
    sell_pct: float
    triggered: bool


@dataclass(frozen=True)
class MonetizationPlan:
    """Advisory monetization programme at current hedge gain.

    Everything here is a recommendation based on the current mark — no
    positions have been altered.

    Attributes:
        current_gain_pct: Weighted gain of long protective puts vs. their
            cost basis, or ``None`` when cost basis is unknown.
        steps: Each IPS schedule step with its trigger status.
        recommended_cumulative_sell_pct: Sum of sell_pct for all triggered
            steps, capped at 100.
        value_to_harvest: recommended_cumulative_sell_pct / 100 times the
            current long-put mark (dollars).
        remaining_sell_capacity: Sum of sell_pct for untriggered steps;
            headroom still available in the IPS schedule.
        gain_basis: ``"paid"`` when all relevant legs have entry_premium;
            ``"unknown"`` when cost basis is missing for one or more legs.
        vol_spike_context: Optional note added when market_env.regime_label
            is HIGH, flagging that elevated vol may argue for harvesting
            sooner.

    """

    current_gain_pct: float | None
    steps: list[MonetizationStepStatus]
    recommended_cumulative_sell_pct: float
    value_to_harvest: float
    remaining_sell_capacity: float
    gain_basis: Literal["paid", "unknown"]
    vol_spike_context: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _long_protective_puts(portfolio: OptionPortfolio) -> list[OptionPosition]:
    """Return long put positions from *portfolio*."""
    return [
        p
        for p in portfolio.positions
        if p.quantity > 0 and p.option.option_type == OptionType.PUT
    ]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def compute_hedge_gain_pct(portfolio: OptionPortfolio) -> float | None:
    """Compute the weighted gain% of the long protective put legs.

    Gain is measured against the aggregate cost basis using
    ``entry_premium``.  Returns ``None`` (degrades gracefully) when there
    are no long put legs or any such leg is missing ``entry_premium`` —
    never raises.

    Args:
        portfolio: Live portfolio whose positions are inspected.

    Returns:
        Gain percentage relative to aggregate cost basis, or ``None`` when
        cost basis cannot be determined for all relevant legs.

    """
    legs = _long_protective_puts(portfolio)
    if not legs:
        return None
    if any(p.entry_premium is None for p in legs):
        return None
    total_cost = sum(
        ep * p.quantity * p.contract_size
        for p in legs
        if (ep := p.entry_premium) is not None
    )
    if total_cost == 0.0:
        return None
    total_mark = sum(p.position_value() for p in legs)
    return (total_mark - total_cost) / total_cost * 100.0


def build_monetization_plan(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    *,
    market_env: MarketEnvironment | None = None,
) -> MonetizationPlan:
    """Build an advisory monetization programme at the current hedge gain.

    Marks each IPS schedule step as triggered when the current gain
    percentage meets or exceeds its threshold, sums the triggered sell
    percentages into a cumulative recommendation, and values the harvest
    against the current long-put mark.  Everything is advisory; no
    positions are altered.

    Args:
        portfolio: Live portfolio supplying current marks and cost basis.
        ips_config: Policy parameters including the monetization schedule.
        market_env: Optional market environment.  When provided and
            ``regime_label`` is ``RegimeLabel.HIGH``, a vol-spike context
            note is added to the plan.

    Returns:
        :class:`MonetizationPlan` describing the recommended sell programme.

    """
    legs = _long_protective_puts(portfolio)
    gain_basis: Literal["paid", "unknown"] = (
        "paid"
        if legs and all(p.entry_premium is not None for p in legs)
        else "unknown"
    )
    current_gain_pct = compute_hedge_gain_pct(portfolio)
    current_hedge_mark = sum(p.position_value() for p in legs)

    steps = [
        MonetizationStepStatus(
            gain_pct=step.gain_pct,
            sell_pct=step.sell_pct,
            triggered=(
                current_gain_pct is not None
                and current_gain_pct >= step.gain_pct
            ),
        )
        for step in ips_config.monetization.schedule
    ]

    recommended_cumulative_sell_pct = min(
        100.0,
        sum(s.sell_pct for s in steps if s.triggered),
    )
    value_to_harvest = (
        recommended_cumulative_sell_pct / 100.0 * current_hedge_mark
    )
    remaining_sell_capacity = sum(s.sell_pct for s in steps if not s.triggered)

    vol_spike_context: str | None = None
    if market_env is not None and market_env.regime_label == RegimeLabel.HIGH:
        vol_spike_context = (
            "Vol spike detected (VIX regime: HIGH)"
            " — consider harvesting gains promptly."
        )

    return MonetizationPlan(
        current_gain_pct=current_gain_pct,
        steps=steps,
        recommended_cumulative_sell_pct=recommended_cumulative_sell_pct,
        value_to_harvest=value_to_harvest,
        remaining_sell_capacity=remaining_sell_capacity,
        gain_basis=gain_basis,
        vol_spike_context=vol_spike_context,
    )
