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
    crash_value_curve,
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


# Below this shock magnitude the underlying hasn't moved enough for
# hedge_gain / abs(underlying_loss) to mean anything — a materiality gate on
# shock_pct rather than a dollar threshold, since underlying_loss's dollar
# magnitude scales with book size but "close enough to zero shock to blow up
# the ratio" does not. Combined (see build_scenario_curve) with an exact
# loss != 0 guard, matching build_scenario's own, for the zero-quantity case
# where the loss is zero at every shock, not just near zero shock.
_OFFSET_RATIO_MATERIAL_SHOCK_PCT = 1.0


@dataclass(frozen=True)
class ScenarioCurvePoint:
    """One point of the monitor's four-series scenario curve.

    Sign convention matches :class:`ScenarioResult`: ``underlying_loss`` is
    signed P&L (negative on a down move, per
    :func:`~deltadewa.analysis.crash_repricing.underlying_pnl`), and ``net``
    is ``hedge_gain + underlying_loss`` on that same convention — negative is
    a net loss, positive is a net gain, at every point on the curve, not just
    the dial's own point.

    Attributes:
        shock_pct: This point's signed spot shock, percent.
        shocked_spot_price: ``portfolio.spot_price * (1 + shock_pct / 100)``
            — the spot level this point represents.
        hedge_value: All-legs option value repriced at this shock (dollars;
            the same quantity
            :func:`~deltadewa.analysis.crash_repricing.crash_value_curve`
            returns — a level, not a change from today).
        underlying_loss: Scenario-local underlying P&L at this shock and
            *quantity* (signed; negative on a down move).
        net: ``hedge_gain + underlying_loss``, where ``hedge_gain`` is this
            point's ``hedge_value`` minus the unshocked hedge value.
        offset_ratio: ``hedge_gain / abs(underlying_loss)``, or ``None`` when
            the loss is exactly zero (e.g. a zero-quantity scenario, matching
            :func:`build_scenario`'s own guard) or when
            ``abs(shock_pct) < _OFFSET_RATIO_MATERIAL_SHOCK_PCT`` — never a
            divide-by-near-zero spike.

    """

    shock_pct: float
    shocked_spot_price: float
    hedge_value: float
    underlying_loss: float
    net: float
    offset_ratio: float | None


def build_scenario_curve(
    portfolio: OptionPortfolio,
    ips_config: IpsConfig,
    *,
    vol_points: float,
    quantity: float,
    shock_range: tuple[float, float] = (-40.0, 10.0),
    n_points: int = 25,
) -> list[ScenarioCurvePoint]:
    """Build the monitor's four-series scenario curve across a shock sweep.

    Reuses :func:`~deltadewa.analysis.crash_repricing.crash_value_curve` for
    the repricing sweep itself — same grid, same basis construction as
    :func:`build_scenario`'s single point — so ``hedge_value`` here is
    identical to what that function already returns at each grid point, not
    a second repricing pass.

    Args:
        portfolio: Portfolio to evaluate. Never mutated.
        ips_config: Hedge program policy — supplies the crash basis
            (skew/vol shape).
        vol_points: Scenario additive vol bump, in vol points, replacing the
            IPS's own ``crash_vol_shock`` — same units as
            :func:`build_scenario`'s ``vol_points``.
        quantity: Scenario-local underlying share quantity — independent of
            ``portfolio.underlying_quantity``.
        shock_range: (min_shock_pct, max_shock_pct) bounding the grid; passed
            through to ``crash_value_curve``.
        n_points: Number of evenly-spaced grid points; passed through to
            ``crash_value_curve``.

    Returns:
        One :class:`ScenarioCurvePoint` per grid point, sorted ascending
        (matching ``crash_value_curve``'s own sort order).

    """
    base_shock = dataclasses.replace(
        CrashShock.from_ips(ips_config.convexity),
        crash_vol_shock=vol_points,
    )
    hedge_today = hedge_value(portfolio)
    value_curve = crash_value_curve(
        portfolio,
        shock=base_shock,
        shock_range=shock_range,
        n_points=n_points,
    )

    points: list[ScenarioCurvePoint] = []
    for pct, hedge_val in value_curve:
        hedge_gain = hedge_val - hedge_today
        spot_shock = pct / 100.0
        loss = underlying_pnl(
            quantity=quantity,
            spot_price=portfolio.spot_price,
            spot_shock=spot_shock,
        )
        net = hedge_gain + loss
        offset_ratio = (
            hedge_gain / abs(loss)
            if loss != 0 and abs(pct) >= _OFFSET_RATIO_MATERIAL_SHOCK_PCT
            else None
        )
        points.append(
            ScenarioCurvePoint(
                shock_pct=pct,
                shocked_spot_price=portfolio.spot_price * (1.0 + spot_shock),
                hedge_value=hedge_val,
                underlying_loss=loss,
                net=net,
                offset_ratio=offset_ratio,
            ),
        )
    return points
