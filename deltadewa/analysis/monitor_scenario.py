"""Build a scenario-local repricing snapshot for the monitor's explorer.

Ties CrashShock, the all-legs crash repricers, and the carry/budget
comparison into the one dataclass the monitor page's two-knob-plus-quantity
scenario explorer (M2.4, app/ layer, not built yet) will render. UI-free —
returns every number the page needs to print; the page must not recompute
any of them.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.carry import CarryBudgetStatus, carry_vs_budget
from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_hedge_value,
    hedge_value,
    underlying_pnl,
)

if TYPE_CHECKING:
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio


@dataclass(frozen=True)
class ScenarioResult:
    """Every number the monitor's scenario explorer prints.

    Attributes:
        spot_pct: The scenario's spot move, signed percent (echoed back).
        vol_points: The scenario's additive vol bump, in vol points (echoed
            back).
        quantity: The scenario's underlying share quantity (echoed back;
            may differ from the portfolio's stored quantity).
        hedge_value_today: All-legs option value at today's spot/vol.
        hedge_value_shocked: All-legs option value at the scenario shock.
        hedge_gain: ``hedge_value_shocked - hedge_value_today``.
        underlying_loss: Scenario-local underlying P&L under the same spot
            move (see
            :func:`~deltadewa.analysis.crash_repricing.underlying_pnl`).
        net: ``hedge_gain + underlying_loss``.
        offset_ratio: ``hedge_gain / abs(underlying_loss)``, or ``None``
            when ``underlying_loss == 0`` (undefined, not zero).
        book_notional: ``abs(quantity) * spot_price`` — the scenario book,
            not the stored one.
        carry: Carry cost vs. the IPS annual budget, measured against
            ``book_notional`` (so the quantity dial moves this even though
            it doesn't move ``hedge_value_*``).

    """

    spot_pct: float
    vol_points: float
    quantity: float
    hedge_value_today: float
    hedge_value_shocked: float
    hedge_gain: float
    underlying_loss: float
    net: float
    offset_ratio: float | None
    book_notional: float
    carry: CarryBudgetStatus


def build_scenario(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    *,
    spot_pct: float,
    vol_points: float,
    quantity: float,
) -> ScenarioResult:
    """Reprice the hedge at a scenario-local (spot, vol, quantity) point.

    Builds ``CrashShock.from_ips(ips_config.convexity)`` with
    ``crash_vol_shock`` replaced by *vol_points*, re-aimed at *spot_pct* via
    :meth:`CrashShock.at_pct`, then reprices via the shock's own
    :meth:`CrashShock.to_shock` / :meth:`CrashShock.vol_mapping` pair (never
    a raw ``MarketShock`` assembled by hand) — so that at
    ``spot_pct == ips_config.convexity.crash_scenario_pct`` and
    ``vol_points == ips_config.convexity.crash_vol_shock`` this reproduces
    :func:`~deltadewa.analysis.crash_repricing.crash_hedge_value` to the
    cent (the same guarantee M2.1 pinned between the crash gauge and any
    surface reproducing it).

    Args:
        portfolio: Portfolio to evaluate. Never mutated.
        ips_config: Hedge program policy — supplies the crash basis
            (skew/vol shape) and the carry budget.
        spot_pct: Scenario spot move, signed percent (e.g. ``-25.0``).
        vol_points: Scenario additive vol bump, in vol points (e.g.
            ``0.15``), replacing the IPS's own ``crash_vol_shock``.
        quantity: Scenario-local underlying share quantity — independent of
            ``portfolio.underlying_quantity``.

    Returns:
        Every number the scenario explorer needs to render.

    """
    base_shock = CrashShock.from_ips(ips_config.convexity)
    shock = dataclasses.replace(
        base_shock,
        crash_vol_shock=vol_points,
    ).at_pct(spot_pct)

    hedge_today = hedge_value(portfolio)
    hedge_shocked = crash_hedge_value(portfolio, shock=shock)
    hedge_gain = hedge_shocked - hedge_today

    underlying_loss = underlying_pnl(
        quantity=quantity,
        spot_price=portfolio.spot_price,
        spot_shock=shock.crash_move,
    )
    net = hedge_gain + underlying_loss
    offset_ratio = (
        hedge_gain / abs(underlying_loss) if underlying_loss != 0 else None
    )

    book_notional = abs(quantity) * portfolio.spot_price
    theta_annual: float = PortfolioAnalyzer(
        portfolio,
    ).calculate_carry_metrics()["total_theta_annual"]
    carry = carry_vs_budget(
        theta_annual=theta_annual,
        book_notional=book_notional,
        budget_annual_pct=ips_config.budget.annual_carry_pct,
    )

    return ScenarioResult(
        spot_pct=spot_pct,
        vol_points=vol_points,
        quantity=quantity,
        hedge_value_today=hedge_today,
        hedge_value_shocked=hedge_shocked,
        hedge_gain=hedge_gain,
        underlying_loss=underlying_loss,
        net=net,
        offset_ratio=offset_ratio,
        book_notional=book_notional,
        carry=carry,
    )
