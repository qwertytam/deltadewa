"""Batch 8a.1 / N1: a leg's cached "today" marks must survive a Monte Carlo run.

``run_monte_carlo_simulation`` (``portfolio/monte_carlo.py``), when
``days_to_expiry`` is left ``None`` -- the default, and what ``/design``'s
EXPLORATION Monte Carlo panel passes on every render with the horizon field
blank -- reprices the book's horizon P&L through a *scratch*
``BatchPricer`` at the nearest maturity in the book. Constructing an
``OptionValuation`` unconditionally writes the process-global QuantLib
``Settings.instance().evaluationDate`` (``valuation.py``'s
``_setup_quantlib()``); nothing restored it afterwards. Left advanced at (or
past) the nearest tranche's own maturity, ``isExpired()`` -- the one place
pricing reads that global live rather than each option's own pinned
reference date -- then reports that tranche's *own persistent*
``OptionValuation`` (held on ``OptionPosition.option`` for the life of the
program) as expired on its next read: price and every Greek silently
return ``0.0``, and ``GreeksCache`` latches the zero in until an unrelated
mutation invalidates it.

Every ``/design`` surface that reads a leg through this persistent object
(the expiration calendar via ``analysis/position_aging.py``, vega term
exposure via ``analysis/maturity.py``, delta drift's "now" reading via
``analysis/scenarios.py``) went to zero for the nearest tranche. ``/monitor``
and every *shocked*-path Greek stayed correct because they price through
``analysis/repricing.shocked_leg_option`` -- a fresh scratch
``OptionValuation`` constructed at read time, which self-heals the global on
construction.

``persistence.py``'s ``PortfolioSerializer`` reimplements the same read
inline (``pos.option.price() * pos.quantity * pos.contract_size`` --
``_build_export_data``) rather than calling ``position.position_value()``,
so it shares this exact vulnerability: a third, independent-looking
producer of "a leg's value today" that in fact reads the same poisoned
cache. This module's property therefore checks three families at once --
the persistent position, the serializer's export, and a fresh independent
reprice standing in for ``/monitor`` -- so "the serializer's mark" is
literally part of what gets pinned, not just a description of the bug.

This module pins the standing rule as one property over the whole book,
rather than one assertion per surface: a leg's price/delta/vega/theta,
however it is read off the persistent ``OptionValuation`` (directly, or via
the serializer), must always agree with a fresh, independently-constructed
reprice at the same (unshocked) point. The referee is the *fresh*
computation, not another reader of the same cached object, so it catches
this failure regardless of which producer left the global dirty.

A second, structurally identical entry point was found and fixed alongside
the reported one: ``analysis/scenarios.py``'s ``scenario_grid_spot_vol``
also sweeps through scratch ``OptionValuation`` constructions and, at a
nonzero ``days_forward`` (a live dial on ``/design``'s spot/vol heatmap
panel), left the same global dirty afterwards -- invisible at the
``days_forward=0`` default, where the leftover global happens to already
equal today's date. Both entry points are exercised below; a *third* one
would not automatically be caught -- this is two targeted regression tests
against the two known producers, not a scan of every possible caller.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.repricing import (
    MarketShock,
    MarketState,
    flat_bump_vol,
    proportional_vol,
    shocked_leg_option,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.persistence import PortfolioSerializer
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.position import OptionPosition
from deltadewa.reporting.audit import PortfolioLogger

_VAL = datetime(2026, 9, 5, tzinfo=UTC)
_SPOT = 5900.0
_VOL = 0.19


def _two_tranche_book() -> OptionPortfolio:
    """Near tranche inside the MC default horizon; far tranche outside it.

    Mirrors the reported book: a ~285-day, ~27.5%-OTM near put (the June
    tranche that read $0) and a further-dated control (the December
    tranche, which read correctly throughout).
    """
    pf = OptionPortfolio(
        underlying_quantity=0.0,
        spot_price=_SPOT,
        volatility=_VOL,
        risk_free_rate=0.04,
        dividend_yield=0.015,
        valuation_date=_VAL,
        symbol="SPX",
        default_exercise_style=ExerciseStyle.EUROPEAN,
        contract_size=100,
    )
    pf.add_position(
        round(_SPOT * 0.725, 2),
        _VAL + timedelta(days=285),
        56,
        OptionType.PUT,
    )
    pf.add_position(
        round(_SPOT * 0.70, 2),
        _VAL + timedelta(days=465),
        40,
        OptionType.PUT,
    )
    return pf


def _fresh_leg_option(
    position: OptionPosition,
    portfolio: OptionPortfolio,
):
    """Self-healing reference: a scratch, zero-shock reprice of one leg.

    Uses the same primitive ``/monitor`` and every shocked-path Greek use
    (``repricing.shocked_leg_option``) rather than the persistent
    ``position.option`` this test is checking, so it cannot share the bug
    being guarded against.
    """
    state = MarketState.from_portfolio(portfolio)
    zero_shock = MarketShock(spot_shock=0.0, vol_shock=0.0)
    return shocked_leg_option(
        position,
        state,
        spot=zero_shock.shocked_spot(state),
        volatility=flat_bump_vol(position, state, zero_shock),
        valuation_date=zero_shock.shocked_valuation_date(state),
    )


def _serialize_book(portfolio: OptionPortfolio) -> dict[str, dict[str, Any]]:
    """Build persistence.py's export data, keyed by position_id.

    ``PortfolioSerializer._build_export_data`` reads a leg's marks the same
    way ``position.position_value()``/``.position_delta()``/etc. do --
    ``pos.option.price()``/``.delta()``/etc. directly off the persistent
    ``OptionValuation`` -- so calling it here, first, stands in for "the
    serializer's mark", and is the *first* read of the persistent cache
    after a poisoning call, exactly as it would be if the serializer ran
    before any panel did.
    """
    with tempfile.TemporaryDirectory() as export_dir:
        serializer = PortfolioSerializer(export_dir=export_dir)
        # pylint: disable=protected-access
        export_data = serializer._build_export_data(
            portfolio,
            PortfolioLogger(),
        )
    return {entry["position_id"]: entry for entry in export_data["positions"]}


def _assert_leg_marks_agree(
    position: OptionPosition,
    portfolio: OptionPortfolio,
    serialized: dict[str, dict[str, Any]],
) -> None:
    """The property: every reader of a leg's "today" marks must agree.

    Three families, all standing in for real surfaces:

    - the serializer's export (``persistence.py`` -- "the serializer's
      mark"), read first (see :func:`_serialize_book`);
    - the persistent position itself (``position_value``/``_delta``/
      ``_vega``/``_theta`` -- the same values ``/design``'s expiration
      calendar, vega term exposure, and delta drift read);
    - a fresh, independently-constructed reprice (standing in for
      ``/monitor`` and every shocked-path Greek), built *last* so its
      self-healing construction cannot mask a divergence the first two
      reads would otherwise have latched in.
    """
    mult = position.quantity * position.contract_size
    entry = serialized[position.position_id]

    persistent_value = position.position_value()
    persistent_delta = position.position_delta()
    persistent_vega = position.position_vega()
    persistent_theta = position.position_theta()

    ref = _fresh_leg_option(position, portfolio)
    ref_value = ref.price() * mult
    ref_delta = ref.delta() * mult
    ref_vega = ref.vega() * mult
    ref_theta = ref.theta() * mult

    assert entry["position_value"] == pytest.approx(ref_value, abs=1e-4)
    assert entry["greeks"]["delta"] * mult == pytest.approx(
        ref_delta,
        abs=1e-4,
    )
    assert entry["greeks"]["vega"] * mult == pytest.approx(
        ref_vega,
        abs=1e-4,
    )
    assert entry["greeks"]["theta"] * mult == pytest.approx(
        ref_theta,
        abs=1e-4,
    )

    assert persistent_value == pytest.approx(ref_value, abs=1e-4)
    assert persistent_delta == pytest.approx(ref_delta, abs=1e-4)
    assert persistent_vega == pytest.approx(ref_vega, abs=1e-4)
    assert persistent_theta == pytest.approx(ref_theta, abs=1e-4)


class TestLegMarksSurviveMonteCarlo:
    """A leg's persistent marks must not zero out after an MC run."""

    def test_near_tranche_matches_hand_checked_black_scholes(self) -> None:
        """Reproduces the review's #3 finding: the near (June) tranche.

        27.5% OTM, 0.78y, 19% vol hand-checks (closed-form Black-Scholes,
        S=5900, K=4277.50, r=4%, q=1.5%) to $6.4182/unit -- not the $0 the
        affected panels showed.
        """
        pf = _two_tranche_book()
        pf.run_monte_carlo_simulation(
            num_simulations=1000,
            days_to_expiry=None,
        )

        near = pf.positions[0]
        assert near.option.price() == pytest.approx(6.4181, abs=1e-3)
        assert abs(near.option.delta()) > 1e-6
        assert abs(near.option.vega()) > 1e-6
        assert abs(near.option.theta()) > 1e-6

    def test_every_leg_marks_agree_with_a_fresh_reprice(self) -> None:
        """The standing property, over the whole book, not per-panel.

        Run after the exact call ``/design``'s Monte Carlo panel makes on
        every render with the horizon field left blank.
        """
        pf = _two_tranche_book()
        pf.run_monte_carlo_simulation(
            num_simulations=1000,
            days_to_expiry=None,
        )

        serialized = _serialize_book(pf)
        for position in pf.positions:
            _assert_leg_marks_agree(position, pf, serialized)

    def test_property_holds_before_any_monte_carlo_run_too(self) -> None:
        """Same property, unpoisoned baseline -- guards the referee itself."""
        pf = _two_tranche_book()
        serialized = _serialize_book(pf)
        for position in pf.positions:
            _assert_leg_marks_agree(position, pf, serialized)


class TestLegMarksSurviveSpotVolGrid:
    """Same bug class, a second door: scenario_grid_spot_vol's days_forward.

    Reachable from the live ``/design`` spot/vol heatmap panel, whose
    ``days_forward`` dial defaults to ``0`` (harmless) but is user-settable.
    """

    def test_every_leg_marks_agree_after_a_forward_dated_grid(self) -> None:
        pf = _two_tranche_book()
        analyzer = PortfolioAnalyzer(pf)

        # Forward past the near tranche's own 285-day maturity -- the same
        # boundary that exposed the Monte Carlo instance of this bug.
        analyzer.scenario_grid_spot_vol(
            spot_scenarios=np.array([_SPOT * 0.9, _SPOT, _SPOT * 1.1]),
            vol_scenarios=np.array([_VOL]),
            vol_mapping=proportional_vol,
            metric="value",
            days_forward=300,
        )

        serialized = _serialize_book(pf)
        for position in pf.positions:
            _assert_leg_marks_agree(position, pf, serialized)
