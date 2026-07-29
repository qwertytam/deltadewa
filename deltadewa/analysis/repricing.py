"""The shared repricing primitive and shock/mapping vocabulary (M2.1).

Before this module three repricing paths grew independently — the crash
gauge (``crash_repricing.py``), the 2D spot/vol grid
(``scenarios.py::scenario_grid_spot_vol``), and the dashboard's heatmap
orchestration — and two of them answered "what happens at -25%?" with
materially different numbers. Measured on the §4 golden book at the crash
overlap point, the naive grid knob underreported the crash-repriced hedge
value by 25.4%. The pricing primitive itself was never the fork (spot-only
reprices agree to the cent); the entire gap was the vol-shock -> sigma'
mapping, hiding a unit mismatch: the grid's ``vol_scenarios`` are absolute
target average vol levels, ``CrashShock.crash_vol_shock`` is an additive
bump.

This module is the single place both semantics resolve through:

* :class:`MarketState` -- the market a shock is applied to. **Always the
  BASE, pre-shock state.** ``crash_skew_vol`` (in ``crash_repricing.py``)
  solves its wing anchor and measures log-moneyness against
  ``state.spot_price`` -- today's spot, never the shocked spot. Passing a
  shocked state to a mapping would silently change every pinned crash
  value.
* :class:`MarketShock` -- the dials: ``spot_shock`` and ``vol_shock`` are
  **required** (a ``vol_shock`` of ``0.0`` is a pricing claim, not a
  neutral default -- the M1.2/M1.4/M1.5 fail-loud rule); ``days_forward``
  defaults to ``0`` because "absent" is unambiguously instantaneous.
* :data:`VolMapping` -- the pluggable vol-shock -> sigma' rule, **required
  on every generic entry point, never defaulted**. A caller that forgets to
  pass the crash-conditional mapping would silently render the general
  model and disagree with its own gauge by 25% -- the exact failure this
  module exists to prevent, reintroduced by omission.

``flat_bump_vol`` and ``proportional_vol`` are plain module-level functions
-- stateless, singleton references, so identity-based equality/hash is
already cache-safe. ``crash_skew_vol`` (``crash_repricing.py``) is a
*factory* returning a frozen-dataclass mapping instead, because it carries
runtime configuration (the skew calibration); frozen-dataclass equality is
by value, so two independently-built mappings with the same calibration
still hit the same cache key.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING

from deltadewa.analysis.volatility import calculate_portfolio_avg_volatility
from deltadewa.valuation import OptionValuation

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.portfolio.position import OptionPosition


@dataclasses.dataclass(frozen=True)
class MarketState:
    """The market a shock is applied to -- always the BASE, pre-shock state.

    Never construct this from an already-shocked portfolio; every mapping
    and the wing-anchor solve in ``crash_skew_vol`` assume ``spot_price`` and
    ``valuation_date`` are today's, not the crash state's.

    Attributes:
        spot_price: Today's underlying spot.
        risk_free_rate: Portfolio risk-free rate.
        dividend_yield: Portfolio dividend yield.
        valuation_date: Portfolio valuation date.
        avg_volatility: Vega-weighted average volatility across the
            portfolio's positions at this state (see
            :func:`~deltadewa.analysis.volatility.calculate_portfolio_avg_volatility`).
            Consulted only by :func:`proportional_vol`; other mappings
            ignore it. Must be computed once per repricing call and reused
            across every shock in a sweep -- recomputing it after a shock
            has already moved spot is the order-dependence bug this module
            fixes (a vega-weighted average that changes underneath you
            between vol slices).

    """

    spot_price: float
    risk_free_rate: float
    dividend_yield: float
    valuation_date: datetime
    avg_volatility: float

    @classmethod
    def from_portfolio(cls, portfolio: OptionPortfolio) -> MarketState:
        """Snapshot a portfolio's current (unshocked) market state.

        Args:
            portfolio: Portfolio to read today's market from.

        Returns:
            The base state every shock in a single repricing call should
            share.

        """
        return cls(
            spot_price=portfolio.spot_price,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            valuation_date=portfolio.valuation_date,
            avg_volatility=calculate_portfolio_avg_volatility(portfolio),
        )


@dataclasses.dataclass(frozen=True)
class MarketShock:
    """The dials of a repricing scenario, travelling as one value.

    Attributes:
        spot_shock: Signed fractional spot move, required (e.g. ``-0.25``
            for a 25% decline). No default: an unstated spot shock is a
            pricing claim, not a neutral one.
        vol_shock: Additive vol bump as a decimal, required (e.g. ``0.15``
            for +15 vol points). Interpretation of "bump" is delegated to
            the :data:`VolMapping` in use -- see :func:`proportional_vol`
            for how it converts to an absolute target level.
        days_forward: Calendar days forward from the base valuation date.
            Defaults to ``0`` -- unlike the other two dials, "absent" is
            unambiguously *instantaneous*, so a default here does not hide
            a pricing decision.

    """

    spot_shock: float
    vol_shock: float
    days_forward: int = 0

    def shocked_spot(self, state: MarketState) -> float:
        """Spot after this shock, applied to *state*'s base spot.

        Args:
            state: The base (pre-shock) market state.

        Returns:
            ``state.spot_price * (1 + spot_shock)``.

        """
        return state.spot_price * (1.0 + self.spot_shock)

    def shocked_valuation_date(self, state: MarketState) -> datetime:
        """Valuation date after this shock's ``days_forward`` offset.

        Args:
            state: The base (pre-shock) market state.

        Returns:
            ``state.valuation_date`` unchanged when ``days_forward == 0``
            (avoids manufacturing a new but equal ``datetime``), otherwise
            offset by ``days_forward`` calendar days.

        """
        if self.days_forward == 0:
            return state.valuation_date
        return state.valuation_date + timedelta(days=self.days_forward)


# A per-leg vol-shock -> sigma' rule. Called with the leg being priced, the
# BASE (pre-shock) market state, and the shock being applied; returns the
# leg's shocked volatility as a decimal. Required on every generic
# repricing entry point in this package -- see the module docstring.
VolMapping = Callable[["OptionPosition", MarketState, MarketShock], float]


def flat_bump_vol(
    position: OptionPosition,
    _state: MarketState,
    shock: MarketShock,
) -> float:
    """Apply the flat bump: ``sigma_i + vol_shock``. No skew, no scaling.

    Args:
        position: Option leg to shock.
        _state: The base market state (unused -- this mapping is purely
            leg-local).
        shock: The shock being applied; only ``vol_shock`` is read.

    Returns:
        The leg's shocked volatility as a decimal.

    """
    return position.option.volatility + shock.vol_shock


def proportional_vol(
    position: OptionPosition,
    state: MarketState,
    shock: MarketShock,
) -> float:
    """Scale every leg so the vega-weighted average moves by ``vol_shock``.

    The general mapping. A pure re-expression of
    :func:`~deltadewa.analysis.volatility.apply_proportional_volatility_shift`
    that *returns* sigma' per leg instead of mutating the portfolio, and
    converts level semantics (an absolute target average) to bump semantics
    (an additive offset from the base average) at this seam -- that
    conversion is where a 25% gap against the crash-conditional mapping used
    to hide on a skewed book.

    ``state.avg_volatility`` must be the vega-weighted average at the BASE
    (pre-shock) state, computed once per repricing call
    (:meth:`MarketState.from_portfolio`) and reused across every shock in a
    sweep. Recomputing it after spot has already moved for a prior shock is
    an order-dependence bug: vega depends on spot, so the scaling factor
    would depend on sweep order, invisible on a flat-vol book and worth up
    to several percent on a skewed one.

    Args:
        position: Option leg to shock.
        state: The base market state; ``avg_volatility`` anchors the scale.
        shock: The shock being applied; only ``vol_shock`` is read.

    Returns:
        The leg's shocked volatility as a decimal. When the base average is
        zero (degenerate book), every leg is set directly to the target
        level ``vol_shock`` -- mirroring the zero-division fallback of the
        function this re-expresses.

    """
    target_avg = state.avg_volatility + shock.vol_shock
    if state.avg_volatility == 0:
        return target_avg
    scale = target_avg / state.avg_volatility
    return position.option.volatility * scale


def shocked_leg_option(
    position: OptionPosition,
    state: MarketState,
    *,
    spot: float,
    volatility: float,
    valuation_date: datetime,
) -> OptionValuation:
    """Build a scratch :class:`OptionValuation` for one leg at a shocked point.

    Never mutates *position*, *state*, or any portfolio.

    Args:
        position: Option leg to price -- supplies strike, maturity, type,
            and exercise style.
        state: The base market state -- supplies rate and dividend yield
            (these are held fixed across a shock; only spot, vol, and date
            move).
        spot: Shocked spot to price at.
        volatility: Shocked volatility to price at (from a
            :data:`VolMapping`).
        valuation_date: Shocked valuation date to price at.

    Returns:
        A freshly constructed :class:`OptionValuation`, priced at the
        shocked point.

    """
    return OptionValuation(
        spot_price=spot,
        strike_price=position.option.strike_price,
        maturity_date=position.option.maturity_date,
        volatility=volatility,
        risk_free_rate=state.risk_free_rate,
        dividend_yield=state.dividend_yield,
        option_type=position.option.option_type,
        valuation_date=valuation_date,
        exercise_style=position.exercise_style,
    )


def reprice_leg(
    position: OptionPosition,
    state: MarketState,
    *,
    spot: float,
    volatility: float,
    valuation_date: datetime,
) -> float:
    """Total value of one option leg at a shocked point.

    Args:
        position: Option leg to reprice.
        state: The base market state.
        spot: Shocked spot to price at.
        volatility: Shocked volatility to price at.
        valuation_date: Shocked valuation date to price at.

    Returns:
        ``price * quantity * contract_size`` in dollars (signed by
        quantity).

    """
    option = shocked_leg_option(
        position,
        state,
        spot=spot,
        volatility=volatility,
        valuation_date=valuation_date,
    )
    return option.price() * position.quantity * position.contract_size


def reprice_legs_at(
    positions: Sequence[OptionPosition],
    state: MarketState,
    *,
    shock: MarketShock,
    vol_mapping: VolMapping,
) -> float:
    """Sum of *positions*' values under *shock*, given a precomputed *state*.

    The efficient form for a sweep: build :class:`MarketState` once (it
    includes a vega-weighted average pass over every position) and call this
    once per shock, rather than re-deriving the base state on every grid
    cell.

    Args:
        positions: Legs to price.
        state: The base (pre-shock) market state, shared across the sweep.
        shock: The shock to apply.
        vol_mapping: **Required.** The per-leg vol-shock -> sigma' rule.
            Never defaulted -- see the module docstring.

    Returns:
        Summed repriced value of *positions*, in dollars.

    """
    shocked_spot = shock.shocked_spot(state)
    shocked_date = shock.shocked_valuation_date(state)
    return float(
        sum(
            reprice_leg(
                position,
                state,
                spot=shocked_spot,
                volatility=vol_mapping(position, state, shock),
                valuation_date=shocked_date,
            )
            for position in positions
        ),
    )


def reprice_portfolio(
    portfolio: OptionPortfolio,
    *,
    shock: MarketShock,
    vol_mapping: VolMapping,
    positions: Sequence[OptionPosition] | None = None,
) -> float:
    """Derive the base state from *portfolio*, then reprice under *shock*.

    A one-shot convenience; never mutates *portfolio*.

    For a sweep over many shocks against the same base state, build
    :class:`MarketState` once with :meth:`MarketState.from_portfolio` and
    call :func:`reprice_legs_at` directly instead -- calling this function
    per shock would redo the vega-weighted average pass every time.

    Args:
        portfolio: Portfolio to evaluate.
        shock: The shock to apply.
        vol_mapping: **Required.** The per-leg vol-shock -> sigma' rule.
            Never defaulted -- see the module docstring.
        positions: Legs to price. Defaults to every position in the
            portfolio; pass a subset to value part of the book.

    Returns:
        Summed repriced value of the selected legs, in dollars.

    """
    state = MarketState.from_portfolio(portfolio)
    legs = portfolio.positions if positions is None else positions
    return reprice_legs_at(
        legs,
        state,
        shock=shock,
        vol_mapping=vol_mapping,
    )
