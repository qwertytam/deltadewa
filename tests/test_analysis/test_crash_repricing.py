"""Tests for deltadewa.analysis.crash_repricing (M1.2 / C1).

Pins the normative crash-repricing methodology in
``docs/repricing-methodology.md``: hedge-only, repriced (not intrinsic, not
expiry), instantaneous. §4's worked example is the regression anchor; the
remaining tests guard the C1 (hedge-only) and C4 (repriced) invariants and the
single-basis consistency across the health gauge, the crash scenario table, and
the summary crash-convexity ladder.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from deltadewa.analysis import classify_portfolio_shape
from deltadewa.analysis import crash_repricing as cr
from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.candidate import evaluate_candidate
from deltadewa.analysis.crash_payoff import (
    compute_crash_convexity,
    crash_payoff_ratio,
    crash_scenario_table,
)
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.analysis.health import HealthMixin
from deltadewa.analysis.roll_status import evaluate_roll_status
from deltadewa.analysis.sizing import size_hedge
from deltadewa.analysis.strike_ladder import build_strike_ladder
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMonetization,
    IpsPricing,
    IpsProgram,
    IpsTriggers,
)
from deltadewa.persistence import PortfolioSerializer
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.position import OptionPosition
from deltadewa.valuation import OptionValuation
from deltadewa.widgets.summary import NetHedgeSummary

# §4 worked-example crash state.
_APPENDIX_SPOT = 6600.0
_APPENDIX_BOOK = 20_000_000.0
_APPENDIX_MOVE = -0.25
# Same crash depth in the signed-percent form CrashShock carries.
_APPENDIX_PCT = -25.0
_APPENDIX_VOL_SHOCK = 0.15
# Shipped deep-OTM skew steepening (M1.6/M1.7): extra vol reached at each leg's
# own ~10-delta wing, capped there and interpolated (in log-moneyness) below it.
# The §4 worked example is skew-aware; the anchor is per-leg, not book-relative.
_APPENDIX_SKEW = 0.10
_APPENDIX_SKEW_ANCHOR = 0.10
# As-of date for the YAML fixture loads below. This is the date on which the
# published canonical golden (+16.098902%) was measured. The canonical fixture
# carries an *absolute* maturity, so without a pin its time-to-expiry — and
# every number derived from it — walks with the calendar.
_FIXTURE_AS_OF = datetime(2026, 7, 26, tzinfo=UTC)
# (strike, contract count) for the 20/30/40%-OTM three-rung ladder.
_APPENDIX_LEGS = ((5280.0, 23), (4620.0, 26), (3960.0, 16))


def _make_appendix_book(
    *,
    underlying_quantity: float | None = None,
) -> OptionPortfolio:
    """Build the conformant $20M book from ``docs/repricing-methodology.md`` §4.

    Args:
        underlying_quantity: Override the equity leg size. Defaults to the
            share count that makes the book worth $20M at the appendix spot.

    Returns:
        A portfolio matching the appendix inputs (European puts, 18-month
        tenor, 20% flat today-vol, r=4.5%, q=1.5%).
    """
    valuation_date = datetime(2026, 1, 2, tzinfo=UTC)
    maturity = valuation_date + timedelta(days=round(1.5 * 365))
    uq = (
        _APPENDIX_BOOK / _APPENDIX_SPOT
        if underlying_quantity is None
        else underlying_quantity
    )
    portfolio = OptionPortfolio(
        spot_price=_APPENDIX_SPOT,
        volatility=0.20,
        risk_free_rate=0.045,
        dividend_yield=0.015,
        underlying_quantity=uq,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        valuation_date=valuation_date,
    )
    for strike, quantity in _APPENDIX_LEGS:
        portfolio.add_position(
            strike_price=strike,
            maturity_date=maturity,
            quantity=quantity,
            option_type=OptionType.PUT,
            volatility=0.20,
        )
    return portfolio


def _make_mixed_leg_book() -> OptionPortfolio:
    """Appendix book plus one short (covered) call — a genuinely mixed book.

    The existing appendix/canonical fixtures are all-long-puts, so a curve
    that accidentally dropped non-put legs would still match
    ``crash_hedge_value`` on every other fixture in this file. This book
    exists to catch exactly that regression.
    """
    portfolio = _make_appendix_book()
    maturity = portfolio.positions[0].option.maturity_date
    portfolio.add_position(
        strike_price=7260.0,
        maturity_date=maturity,
        quantity=-10,
        option_type=OptionType.CALL,
        volatility=0.20,
    )
    return portfolio


def _make_call_book() -> OptionPortfolio:
    """A long-call book with no OTM put — the skew knob has no wing to anchor.

    Returns:
        A portfolio holding a single OTM call at the appendix spot/tenor.
    """
    valuation_date = datetime(2026, 1, 2, tzinfo=UTC)
    maturity = valuation_date + timedelta(days=round(1.5 * 365))
    portfolio = OptionPortfolio(
        spot_price=_APPENDIX_SPOT,
        volatility=0.20,
        risk_free_rate=0.045,
        dividend_yield=0.015,
        underlying_quantity=_APPENDIX_BOOK / _APPENDIX_SPOT,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        valuation_date=valuation_date,
    )
    portfolio.add_position(
        strike_price=7260.0,
        maturity_date=maturity,
        quantity=10,
        option_type=OptionType.CALL,
        volatility=0.20,
    )
    return portfolio


def _load_canonical_example() -> OptionPortfolio:
    """Load examples/portfolios/spx_protective_put.yaml (European), pinned."""
    path = (
        Path(__file__).parent.parent.parent
        / "examples"
        / "portfolios"
        / "spx_protective_put.yaml"
    )
    result = PortfolioSerializer(Path()).import_from_yaml(
        path,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        valuation_date=_FIXTURE_AS_OF,
    )
    return result["portfolio"]


def _load_golden_20m_example() -> OptionPortfolio:
    """Load examples/portfolios/spx_tail_20m.yaml — the §4 golden book.

    Pinned for consistency with the canonical loader. This fixture's maturities
    are *relative* (``maturity_days``), so its numbers are date-invariant either
    way — see
    :meth:`TestFixtureValuationDatePins.test_golden_20m_is_valuation_date_invariant`.
    """
    path = (
        Path(__file__).parent.parent.parent
        / "examples"
        / "portfolios"
        / "spx_tail_20m.yaml"
    )
    result = PortfolioSerializer(Path()).import_from_yaml(
        path,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        valuation_date=_FIXTURE_AS_OF,
    )
    return result["portfolio"]


def _leg_extra_crash_vol(
    portfolio: OptionPortfolio,
    position: OptionPosition,
    *,
    skew: float = _APPENDIX_SKEW,
    anchor: float = _APPENDIX_SKEW_ANCHOR,
) -> float:
    """Per-leg crash-vol steepening above ``vol_i + vol_shock`` (test helper).

    Drives the production per-leg helper with the portfolio's market snapshot
    and returns the add-on the wing steepening applies to this leg alone.
    """
    crash_vol = cr._leg_crash_vol(
        position,
        spot=portfolio.spot_price,
        risk_free_rate=portfolio.risk_free_rate,
        dividend_yield=portfolio.dividend_yield,
        valuation_date=portfolio.valuation_date,
        shock=CrashShock(
            crash_scenario_pct=0.0,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
            skew_steepening=skew,
            skew_reference_delta=anchor,
        ),
    )
    return crash_vol - (position.option.volatility + _APPENDIX_VOL_SHOCK)


def _make_appendix_ips(
    *,
    crash_scenario_pct: float,
    skew_reference_delta: float = _APPENDIX_SKEW_ANCHOR,
) -> IpsConfig:
    """Full IpsConfig at the appendix crash knobs, parameterised on depth.

    Carries the shipped skew-aware shock (``_APPENDIX_VOL_SHOCK`` /
    ``_APPENDIX_SKEW`` / ``_APPENDIX_SKEW_ANCHOR``) so every surface driven from
    this one config shares a single crash basis. ``crash_scenario_pct`` varies
    so the roll trigger evaluates convexity at the chosen depth, and
    ``skew_reference_delta`` varies so the anchor-propagation guards can move
    the wing off its shipped 0.10.
    """
    return IpsConfig(
        program=IpsProgram(name="appendix", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=crash_scenario_pct,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
            skew_steepening=_APPENDIX_SKEW,
            skew_reference_delta=skew_reference_delta,
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=20.0),
        triggers=IpsTriggers(
            delta_drift_warn_pct=5.0,
            delta_drift_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_time_months=1.0,
            rally_rebalance_pct=15.0,
            strike_drift_max_otm_pct=45.0,
        ),
        monetization=IpsMonetization(schedule=()),
    )


class TestAppendixGoldenValues:
    """§7.1 — the §4 worked example reprices to the published figures.

    The shipped shock is skew-aware (``_APPENDIX_SKEW``), anchored per-leg to
    each leg's own ~10-delta wing (M1.7); these anchors are the post-M1.7 §4
    goldens. The flat-bump baseline (``+18.0%`` / ``13.1x``) is pinned
    separately by :class:`TestSkewSteepeningNoOp` at ``skew=0.0``.
    """

    def test_hedge_values_within_tolerance(self) -> None:
        """V_today and V_crash sit within ~0.5% of the skew-aware §4 table."""
        portfolio = _make_appendix_book()

        v_today = cr.hedge_value(portfolio)
        v_crash = cr.crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        # V_today is skew-free (skew is a crash-state effect only).
        assert v_today == pytest.approx(297_715.0, rel=0.005)
        assert v_crash == pytest.approx(5_226_004.0, rel=0.005)

    def test_convexity_is_in_band_near_ceiling(self) -> None:
        """§4 reprices to +24.64% — the VALUE anchor, riding just under +25%.

        This value assertion (not the ``meets_target`` boolean in
        :class:`TestBand`) is the §4 regression anchor. §4 is a deliberately
        deep 20/30/40 ladder, so a faithful crash model correctly places it near
        the top of the +15..+25% band — it rides only 0.36pp under the +25% IPS
        ceiling by design. Pinning the value (not the boolean) makes any future
        re-calibration that nudges §4 surface as a visible number change
        demanding a deliberate decision, never a silent ``meets_target`` flip
        that would masquerade as a regression while the fixture just hugs the
        rail.
        """
        portfolio = _make_appendix_book()

        convexity = cr.crash_convexity_pct(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert convexity == pytest.approx(24.64, abs=0.1)
        assert 15.0 <= convexity <= 25.0
        # Rides 0.36pp under the +25% IPS ceiling (target_max_pct) by design.
        assert 25.0 - convexity == pytest.approx(0.36, abs=0.1)

    def test_payoff_ratio_is_about_17x(self) -> None:
        """The repriced headline payoff ratio is ~17.5x (not the 2.5x floor)."""
        portfolio = _make_appendix_book()
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
            skew_steepening=_APPENDIX_SKEW,
        )

        result = compute_crash_convexity(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=0.0,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
            ips_convexity=ips,
        )

        assert result.payoff_ratio is not None
        assert result.payoff_ratio == pytest.approx(17.53, rel=0.02)

    def test_intrinsic_floor_is_the_conservative_759k(self) -> None:
        """The intrinsic floor (~$759k) is far below the repriced value."""
        portfolio = _make_appendix_book()

        floor = cr.crash_intrinsic_floor(portfolio, crash_move=_APPENDIX_MOVE)

        # The floor is vol/skew-independent (pure intrinsic at the crash spot).
        assert floor == pytest.approx(759_000.0, rel=0.005)
        assert floor < cr.crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )


class TestSkewSteepeningNoOp:
    """M1.6 — the optional skew_steepening knob is a no-op when ``0.0``.

    Proves the refactor changes nothing while disabled: an explicit
    ``skew_steepening=0.0`` reproduces the parameter-omitted call byte-for-byte,
    and every §4 golden anchor still lands. This must hold before any golden is
    recomputed under a positive steepening (M1.6 sequencing).
    """

    def test_crash_hedge_value_noop(self) -> None:
        """``$3,895,901`` V_crash is unchanged by ``skew_steepening=0.0``."""
        portfolio = _make_appendix_book()

        base = cr.crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        with_knob = cr.crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert with_knob == base
        assert with_knob == pytest.approx(3_895_901.0, rel=0.005)

    def test_crash_convexity_pct_noop(self) -> None:
        """``+18.0%`` convexity is unchanged by ``skew_steepening=0.0``."""
        portfolio = _make_appendix_book()

        base = cr.crash_convexity_pct(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        with_knob = cr.crash_convexity_pct(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert with_knob == base
        assert with_knob == pytest.approx(18.0, abs=0.5)

    def test_payoff_ratio_unchanged(self) -> None:
        """The ``13.1x`` payoff anchor is untouched by the knob."""
        portfolio = _make_appendix_book()
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
        )

        result = compute_crash_convexity(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=0.0,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
            ips_convexity=ips,
        )

        assert result.payoff_ratio == pytest.approx(13.1, rel=0.02)

    def test_intrinsic_floor_is_vol_independent(self) -> None:
        """The ``$759,000`` intrinsic floor is vol-independent."""
        portfolio = _make_appendix_book()

        floor = cr.crash_intrinsic_floor(portfolio, crash_move=_APPENDIX_MOVE)

        assert floor == pytest.approx(759_000.0, rel=0.005)

    def test_leg_crash_vol_noop_is_byte_for_byte(self) -> None:
        """skew=0.0 returns the flat bump exactly, per leg (solves no wing).

        The tightest no-op guard, at the primitive: an explicit
        ``skew_steepening=0.0`` returns ``vol_i + vol_shock`` byte-for-byte for
        every leg — including the two deep rungs that WOULD cap under a positive
        steepening — because the disabled knob short-circuits before any wing is
        solved. Pins the flat-baseline reproduction the aggregate no-ops need.
        """
        portfolio = _make_appendix_book()

        for position in portfolio.positions:
            flat = position.option.volatility + _APPENDIX_VOL_SHOCK
            got = cr._leg_crash_vol(
                position,
                spot=portfolio.spot_price,
                risk_free_rate=portfolio.risk_free_rate,
                dividend_yield=portfolio.dividend_yield,
                valuation_date=portfolio.valuation_date,
                shock=CrashShock(
                    crash_scenario_pct=0.0,
                    crash_vol_shock=_APPENDIX_VOL_SHOCK,
                    skew_steepening=0.0,
                    skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
                ),
            )

            assert got == flat


class TestSkewSteepeningBehaviour:
    """M1.6 — a positive skew_steepening lifts deep-OTM put vol above ATM."""

    def test_steepening_raises_crash_hedge_value(self) -> None:
        """Long OTM puts gain IV under steepening, so V_crash rises."""
        portfolio = _make_appendix_book()

        flat = cr.crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        steepened = cr.crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.10,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert steepened > flat

    def test_crash_vol_matches_per_leg_wing_formula(self) -> None:
        """V_crash matches the leg vols rebuilt from the per-leg wing form.

        Independently reconstructs each put leg's shocked vol as
        ``0.20 + vol_shock + min(skew, slope * ln(S/K))`` with
        ``slope = skew / ln(S / K_ref)`` and ``K_ref`` the leg's own ~10-delta
        wing, prices with the public engine, and requires an exact match —
        pinning the crash vol to the per-leg wing anchor and the cap (M1.7),
        not the old book-relative deepest-put anchor.
        """
        portfolio = _make_appendix_book()
        skew = _APPENDIX_SKEW

        got = cr.crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=skew,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        crash_spot = _APPENDIX_SPOT * (1.0 + _APPENDIX_MOVE)
        expected = 0.0
        for position in portfolio.positions:
            strike = position.option.strike_price
            is_otm_put = (
                position.option.option_type == OptionType.PUT
                and strike < _APPENDIX_SPOT
            )
            if is_otm_put:
                k_ref = cr._solve_wing_strike(
                    spot=_APPENDIX_SPOT,
                    maturity_date=position.option.maturity_date,
                    volatility=position.option.volatility,
                    risk_free_rate=portfolio.risk_free_rate,
                    dividend_yield=portfolio.dividend_yield,
                    valuation_date=portfolio.valuation_date,
                    anchor_delta=_APPENDIX_SKEW_ANCHOR,
                )
                slope = skew / math.log(_APPENDIX_SPOT / k_ref)
                extra = min(skew, slope * math.log(_APPENDIX_SPOT / strike))
            else:
                extra = 0.0
            vol = 0.20 + _APPENDIX_VOL_SHOCK + extra
            leg = OptionValuation(
                spot_price=crash_spot,
                strike_price=strike,
                maturity_date=position.option.maturity_date,
                volatility=vol,
                risk_free_rate=portfolio.risk_free_rate,
                dividend_yield=portfolio.dividend_yield,
                option_type=position.option.option_type,
                valuation_date=portfolio.valuation_date,
                exercise_style=position.exercise_style,
            )
            expected += leg.price() * position.quantity * position.contract_size

        assert got == pytest.approx(expected, rel=1e-9)

    def test_no_otm_put_means_no_steepening(self) -> None:
        """With no OTM put to anchor the wing, the knob is inert."""
        portfolio = _make_call_book()

        flat = cr.crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        steepened = cr.crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.10,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert steepened == flat


class TestPerLegWingAnchor:
    """M1.7 — the skew is a pure per-leg function of the leg's own wing.

    Pins the re-anchoring this milestone exists to make: the extra crash vol on
    each leg is ``min(skew, slope * ln(S/K))`` against that leg's own ~10-delta
    wing, capped there, and independent of what else the book holds. The values
    match ``scratch/skew_anchor_sweep.py`` rule (e), the signed-off calibration.
    """

    def test_per_leg_extra_vol_matches_sweep_canonical(self) -> None:
        """Canonical legs steepen to their own wing: K5200 +5.77, K4900 +7.67.

        Both legs are shallower than their own ~10-delta wing, so neither is
        capped — the extra interpolates below +10 vol pts.
        """
        portfolio = _load_canonical_example()
        extras = {
            pos.option.strike_price: _leg_extra_crash_vol(portfolio, pos)
            for pos in portfolio.positions
            if pos.option.option_type == OptionType.PUT
        }

        assert extras[5200.0] == pytest.approx(0.0577, abs=0.0015)
        assert extras[4900.0] == pytest.approx(0.0767, abs=0.0015)
        # Neither shallow leg reaches the cap.
        assert extras[5200.0] < _APPENDIX_SKEW
        assert extras[4900.0] < _APPENDIX_SKEW

    def test_per_leg_extra_vol_matches_sweep_appendix(self) -> None:
        """§4 legs: K5280 +9.46, K4620 and K3960 pinned at the +10 cap."""
        portfolio = _make_appendix_book()
        extras = {
            pos.option.strike_price: _leg_extra_crash_vol(portfolio, pos)
            for pos in portfolio.positions
        }

        assert extras[5280.0] == pytest.approx(0.0946, abs=0.0015)
        assert extras[5280.0] < _APPENDIX_SKEW
        # The two deeper legs sit at or beyond their wing -> capped at skew.
        assert extras[4620.0] == pytest.approx(_APPENDIX_SKEW, abs=1e-9)
        assert extras[3960.0] == pytest.approx(_APPENDIX_SKEW, abs=1e-9)

    def test_crash_vol_independent_of_book_composition(self) -> None:
        """Adding a deeper put leaves a shallower leg's crash vol unchanged.

        The M1.7 acceptance criterion: market skew at a strike is not a function
        of what else is held. Under the old book-relative anchor the shallow
        leg's steepening tracked the *deepest held* put; here it tracks the
        leg's own wing, so a new, deeper leg cannot move it.
        """
        portfolio = _make_appendix_book()  # deepest held put is K3960
        shallow = next(
            pos
            for pos in portfolio.positions
            if pos.option.strike_price == pytest.approx(5280.0, rel=1e-2)
        )

        before = _leg_extra_crash_vol(portfolio, shallow)

        # Add a leg deeper than the existing deepest (K3960 -> K3000).
        portfolio.add_position(
            strike_price=3000.0,
            maturity_date=shallow.option.maturity_date,
            quantity=5,
            option_type=OptionType.PUT,
            volatility=0.20,
        )
        after = _leg_extra_crash_vol(portfolio, shallow)

        # The shallow leg's crash vol does not move.
        assert after == before
        # ...and it is the own-wing value, not the book-relative (deepest-put)
        # weight the old model would have produced.
        book_relative = _APPENDIX_SKEW * (
            math.log(_APPENDIX_SPOT / 5280.0)
            / math.log(_APPENDIX_SPOT / 3960.0)
        )
        assert before == pytest.approx(0.0946, abs=0.0015)
        assert before != pytest.approx(book_relative, abs=0.001)

    def test_cap_binds_at_and_beyond_the_wing(self) -> None:
        """Extra vol == skew at/beyond the wing; interpolates below it."""
        portfolio = _make_appendix_book()
        maturity = portfolio.positions[0].option.maturity_date
        k_wing = cr._solve_wing_strike(
            spot=_APPENDIX_SPOT,
            maturity_date=maturity,
            volatility=0.20,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            valuation_date=portfolio.valuation_date,
            anchor_delta=_APPENDIX_SKEW_ANCHOR,
        )

        # Three probe puts: shallower than the wing, at it, and deeper than it.
        probe = OptionPortfolio(
            spot_price=_APPENDIX_SPOT,
            volatility=0.20,
            risk_free_rate=0.045,
            dividend_yield=0.015,
            underlying_quantity=1000.0,
            default_exercise_style=ExerciseStyle.EUROPEAN,
            valuation_date=portfolio.valuation_date,
        )
        for strike in (k_wing * 1.1, k_wing, k_wing * 0.85):
            probe.add_position(
                strike_price=strike,
                maturity_date=maturity,
                quantity=1,
                option_type=OptionType.PUT,
                volatility=0.20,
            )
        shallow_extra, at_wing_extra, deep_extra = (
            _leg_extra_crash_vol(probe, pos) for pos in probe.positions
        )

        # Exactly the cap at the wing, and still capped beyond it.
        assert at_wing_extra == pytest.approx(_APPENDIX_SKEW, abs=1e-9)
        assert deep_extra == pytest.approx(_APPENDIX_SKEW, abs=1e-9)
        # Below the wing the steepening interpolates strictly under the cap.
        assert 0.0 < shallow_extra < _APPENDIX_SKEW


class TestCompositionInvariance:
    """M1.7 — a leg's crash vol is a pure function of its own wing.

    First-class guard (not a sub-assertion): market skew at a strike is not a
    function of what else the book holds, so adding, removing, or reshuffling
    other legs must leave every existing leg's crash vol byte-for-byte
    unchanged. This is the property the per-leg anchor (``b1f4e3d``) exists to
    provide; the old book-relative anchor, which tracked the deepest held put,
    failed it.
    """

    def test_no_leg_crash_vol_depends_on_book_composition(self) -> None:
        """Every original leg's crash vol is identical after adding others."""
        portfolio = _make_appendix_book()
        maturity = portfolio.positions[0].option.maturity_date
        before = {
            pos.option.strike_price: _leg_extra_crash_vol(portfolio, pos)
            for pos in portfolio.positions
        }

        # Add unrelated legs on both sides of the ladder and a call: none is an
        # input to any existing leg's own-wing steepening.
        for strike, opt in (
            (3000.0, OptionType.PUT),  # deeper than the deepest held put
            (6000.0, OptionType.PUT),  # shallower than the shallowest
            (7260.0, OptionType.CALL),  # a call — no wing at all
        ):
            portfolio.add_position(
                strike_price=strike,
                maturity_date=maturity,
                quantity=5,
                option_type=opt,
                volatility=0.20,
            )

        after = {
            pos.option.strike_price: _leg_extra_crash_vol(portfolio, pos)
            for pos in portfolio.positions
            if pos.option.strike_price in before
        }

        # Byte-for-byte: the added legs moved nothing.
        assert after == before


class TestBand:
    """§7.2 (D3) — the band test anchors on the §4 fixture, not the example."""

    def test_appendix_book_meets_target_in_band(self) -> None:
        """The §4 book's -25% row is inside +15..+25% and meets_target."""
        portfolio = _make_appendix_book()
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
            skew_steepening=_APPENDIX_SKEW,
        )

        result = compute_crash_convexity(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=0.0,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
            ips_convexity=ips,
        )
        ips_row = next(
            r
            for r in result.scenario_rows
            if r.shock_pct == pytest.approx(-25.0, rel=1e-4)
        )

        assert 15.0 <= ips_row.convexity_pct <= 25.0
        # This exercises the band-comparison mechanics; the §4 regression is
        # anchored on the convexity VALUE (TestAppendixGoldenValues), not on
        # this boolean, so a re-calibration reads as a number change there
        # rather than a silent flip here (§4 rides 0.36pp under the ceiling).
        assert ips_row.meets_target is True


class TestGoldenExampleFile:
    """The shipped spx_tail_20m.yaml reproduces the §4 golden book on load.

    Guards the loadable demo/smoke fixture (as opposed to the in-code
    ``_make_appendix_book``): it must stay conforming and in-band so it can be
    opened in the monitor as the reference conformant book.
    """

    def test_example_is_shape_conforming(self) -> None:
        """Long underlying + long puts — the monitor shows no shape warning."""
        shape = classify_portfolio_shape(_load_golden_20m_example())
        assert shape.is_conforming is True

    def test_example_hedge_values_within_tolerance(self) -> None:
        """Loaded V_today / V_crash sit within ~0.5% of the §4 table."""
        portfolio = _load_golden_20m_example()

        v_today = cr.hedge_value(portfolio)
        v_crash = cr.crash_hedge_value(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert v_today == pytest.approx(297_715.0, rel=0.005)
        assert v_crash == pytest.approx(5_226_004.0, rel=0.005)

    def test_example_convexity_is_in_band(self) -> None:
        """Loaded book reprices to +24.6% ± epsilon — inside +15..+25%."""
        portfolio = _load_golden_20m_example()

        convexity = cr.crash_convexity_pct(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert convexity == pytest.approx(24.64, abs=0.1)
        assert 15.0 <= convexity <= 25.0
        # Rides 0.36pp under the +25% IPS ceiling (target_max_pct) by design.
        assert 25.0 - convexity == pytest.approx(0.36, abs=0.1)


class TestFixtureValuationDatePins:
    """The YAML goldens above are reproducible on any calendar date.

    Two different mechanisms, so two different guards. The canonical fixture
    carries an *absolute* ``maturity_date``, so it is only deterministic
    because the load is pinned — drop the pin and the golden walks (measured:
    +16.85% in Jan 2026 down to +15.07% a year later). The §4 fixture uses
    *relative* ``maturity_days``, so its tenor is constant by construction.
    """

    def test_canonical_fixture_is_valuation_date_pinned(self) -> None:
        """The canonical loads as-of the date its golden was measured."""
        assert _load_canonical_example().valuation_date == _FIXTURE_AS_OF

    def test_golden_20m_is_valuation_date_invariant(self) -> None:
        """Relative maturities => identical values at far-apart as-ofs.

        Records the property rather than the number: if that YAML is ever
        switched to an absolute ``maturity_date``, this fails loudly instead of
        the §4 golden quietly drifting.
        """
        path = (
            Path(__file__).parent.parent.parent
            / "examples"
            / "portfolios"
            / "spx_tail_20m.yaml"
        )
        shock = CrashShock(
            crash_scenario_pct=_APPENDIX_PCT,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
            skew_steepening=_APPENDIX_SKEW,
            skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
        )

        def measure(as_of: datetime) -> tuple[float, float, float]:
            portfolio = PortfolioSerializer(Path()).import_from_yaml(
                path,
                default_exercise_style=ExerciseStyle.EUROPEAN,
                valuation_date=as_of,
            )["portfolio"]
            return (
                cr.hedge_value(portfolio),
                cr.crash_hedge_value(portfolio, shock=shock),
                cr.crash_convexity_pct(portfolio, shock=shock),
            )

        # Spans two leap years.
        early = measure(datetime(2026, 1, 2, tzinfo=UTC))
        late = measure(datetime(2029, 11, 3, tzinfo=UTC))

        assert early == late


class TestHedgeOnlyInvariant:
    """§7.3 — the numerator is hedge-only (guards C1 from regressing)."""

    def test_hedge_values_independent_of_equity_leg(self) -> None:
        """Scaling the equity leg leaves V_today and V_crash unchanged."""
        base = _make_appendix_book()
        doubled = _make_appendix_book(
            underlying_quantity=base.underlying_quantity * 2,
        )

        assert cr.hedge_value(doubled) == pytest.approx(cr.hedge_value(base))
        assert cr.crash_hedge_value(
            doubled,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        ) == pytest.approx(
            cr.crash_hedge_value(
                base,
                shock=CrashShock(
                    crash_scenario_pct=_APPENDIX_PCT,
                    crash_vol_shock=_APPENDIX_VOL_SHOCK,
                    skew_steepening=0.0,
                    skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
                ),
            ),
        )

    def test_convexity_scales_inversely_with_book(self) -> None:
        """A twice-as-big book halves convexity (denominator is the book)."""
        base = _make_appendix_book()
        doubled = _make_appendix_book(
            underlying_quantity=base.underlying_quantity * 2,
        )

        conv_base = cr.crash_convexity_pct(
            base,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        conv_doubled = cr.crash_convexity_pct(
            doubled,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert conv_doubled == pytest.approx(conv_base / 2.0)

    def test_empty_book_convexity_is_zero(self) -> None:
        """No equity leg -> undefined book -> convexity reads 0.0."""
        portfolio = _make_appendix_book(underlying_quantity=0.0)

        assert cr.crash_convexity_pct(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        ) == pytest.approx(0.0, rel=1e-8)


class TestRepricedInvariant:
    """§7.4 — deep-OTM legs carry value; the floor is strictly below."""

    def test_deep_otm_legs_contribute_at_crash(self) -> None:
        """The 30% and 40%-OTM legs are worth >0 at the -25% crash."""
        portfolio = _make_appendix_book()
        crash_spot = _APPENDIX_SPOT * (1 + _APPENDIX_MOVE)

        for strike in (4620.0, 3960.0):
            leg = next(
                pos
                for pos in portfolio.positions
                if pos.option.strike_price == strike
            )
            value = cr._reprice_leg(
                leg,
                portfolio,
                crash_spot,
                leg.option.volatility + _APPENDIX_VOL_SHOCK,
            )
            assert value > 0.0

    def test_floor_below_repriced_beyond_crash_move(self) -> None:
        """For a strike still OTM after the crash, floor < repriced value."""
        portfolio = _make_appendix_book()
        crash_spot = _APPENDIX_SPOT * (1 + _APPENDIX_MOVE)
        # 3960 strike is below the crash spot (4950) -> zero intrinsic.
        leg = next(
            pos
            for pos in portfolio.positions
            if pos.option.strike_price == pytest.approx(3960.0, rel=1e-2)
        )
        floor = cr.crash_intrinsic_floor(
            portfolio,
            crash_move=_APPENDIX_MOVE,
            positions=[leg],
        )
        repriced = cr._reprice_leg(
            leg,
            portfolio,
            crash_spot,
            leg.option.volatility + _APPENDIX_VOL_SHOCK,
        )

        assert floor == pytest.approx(0.0)
        assert floor < repriced


class TestConsistencyAcrossSurfaces:
    """§7.5 — one basis: gauge == scenario table == summary ladder.

    Exercised under the shipped skew-aware shock (``_APPENDIX_SKEW``): every
    surface reads the same ``IpsConvexity.skew_steepening`` and the same book
    tail, so the deep-OTM steepening must reach them identically.
    """

    def test_summary_rung_equals_health_gauge_and_helper(self) -> None:
        """The summary -20% rung equals the gauge and the helper exactly."""
        portfolio = _make_appendix_book()
        vol_shock = _APPENDIX_VOL_SHOCK

        summary = NetHedgeSummary(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=vol_shock,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        rungs = dict(summary._crash_convexity_rungs())

        analyzer = PortfolioAnalyzer(portfolio)
        gauge = analyzer.calculate_crash_convexity_pct(
            CrashShock(
                crash_scenario_pct=-20.0,
                crash_vol_shock=vol_shock,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        helper = cr.crash_convexity_pct(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-20.0,
                crash_vol_shock=vol_shock,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert rungs[-20.0] == pytest.approx(gauge)
        assert rungs[-20.0] == pytest.approx(helper)

    def test_scenario_table_convexity_equals_gauge(self) -> None:
        """The scenario table's convexity column matches the health gauge."""
        portfolio = _make_appendix_book()
        ips = IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
            skew_steepening=_APPENDIX_SKEW,
        )

        result = compute_crash_convexity(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=0.0,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
            ips_convexity=ips,
        )
        ips_row = next(
            r
            for r in result.scenario_rows
            if r.shock_pct == pytest.approx(-25.0, rel=1e-4)
        )
        gauge = PortfolioAnalyzer(portfolio).calculate_crash_convexity_pct(
            CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert ips_row.convexity_pct == pytest.approx(gauge)

    def test_all_four_surfaces_agree_at_equal_depth(self) -> None:
        """Gauge == roll trigger == summary ladder == scenario table at -20%.

        The full single-basis contract under the shipped skew-aware shock:
        driven from one IPS, the health gauge, the roll trigger's convexity,
        the summary ladder's -20% rung, and the crash_payoff scenario table's
        -20% row must all agree at the same crash depth. -20% is the one depth
        present in every surface (the summary ladder gridpoints, the
        scenario-table defaults, the gauge, and — via ``crash_scenario_pct`` —
        the roll trigger).
        """
        portfolio = _make_appendix_book()
        ips = _make_appendix_ips(crash_scenario_pct=-20.0)
        vol_shock = _APPENDIX_VOL_SHOCK
        skew = _APPENDIX_SKEW

        gauge = PortfolioAnalyzer(portfolio).calculate_crash_convexity_pct(
            CrashShock(
                crash_scenario_pct=-20.0,
                crash_vol_shock=vol_shock,
                skew_steepening=skew,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        roll = evaluate_roll_status(portfolio, ips)[0].crash_convexity_pct
        summary = NetHedgeSummary(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=vol_shock,
                skew_steepening=skew,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        rung = dict(summary._crash_convexity_rungs())[-20.0]
        table = compute_crash_convexity(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=0.0,
                crash_vol_shock=vol_shock,
                skew_steepening=skew,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
            ips_convexity=ips.convexity,
        )
        table_row = next(
            r
            for r in table.scenario_rows
            if r.shock_pct == pytest.approx(-20.0, rel=1e-4)
        )

        # All four surfaces read the same convexity at the same depth.
        assert roll == pytest.approx(gauge)
        assert rung == pytest.approx(gauge)
        assert table_row.convexity_pct == pytest.approx(gauge)
        # ...and the skew-aware path is actually exercised: a flat bump at this
        # book/depth is a materially different (lower) number, so the agreement
        # is not a trivial flat-path coincidence.
        flat = cr.crash_convexity_pct(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-20.0,
                crash_vol_shock=vol_shock,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        assert gauge != pytest.approx(flat)


class TestCrashShockValueObject:
    """M1.8 — the four pricing inputs travel as one object, intact.

    ``from_ips`` is the only construction path production code uses, and
    ``at_pct`` is how the sweeping surfaces change depth. Both must preserve
    the basis exactly, or the divergence this object exists to prevent creeps
    back in through the helpers themselves.
    """

    def test_from_ips_carries_all_four_pricing_fields(self) -> None:
        """Every pricing knob is projected off IpsConvexity, none dropped."""
        convexity = IpsConvexity(
            crash_scenario_pct=-30.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
            crash_vol_shock=0.17,
            skew_steepening=0.08,
            skew_reference_delta=0.07,
        )

        shock = CrashShock.from_ips(convexity)

        assert shock.crash_scenario_pct == pytest.approx(-30.0)
        assert shock.crash_vol_shock == pytest.approx(0.17)
        assert shock.skew_steepening == pytest.approx(0.08)
        assert shock.skew_reference_delta == pytest.approx(0.07)

    def test_crash_move_is_the_decimal_form_of_the_percent(self) -> None:
        """The pricer's decimal move is derived, never separately supplied."""
        shock = CrashShock(-25.0, 0.15, 0.10, 0.10)

        assert shock.crash_move == pytest.approx(-0.25)

    def test_at_pct_changes_only_the_depth(self) -> None:
        """Re-aiming the depth carries the whole vol basis along.

        The guard that makes bundling the scenario safe: the shock grid walks
        depths through this helper, so if it dropped the skew or the anchor the
        ladder would silently price flat below the first rung.
        """
        shock = CrashShock(-25.0, 0.15, 0.10, 0.07)

        moved = shock.at_pct(-40.0)

        assert moved.crash_scenario_pct == pytest.approx(-40.0)
        assert moved.crash_vol_shock == pytest.approx(shock.crash_vol_shock)
        assert moved.skew_steepening == pytest.approx(shock.skew_steepening)
        assert moved.skew_reference_delta == pytest.approx(
            shock.skew_reference_delta,
        )
        # Frozen: re-aiming yields a new value, never a mutation in place.
        assert shock.crash_scenario_pct == pytest.approx(-25.0)


class TestSkewReferenceDeltaReachesBookSurfaces:
    """M1.8 — the IPS wing anchor moves the BOOK gauges, not just candidates.

    Before the ``CrashShock`` bundle, ``crash_payoff`` / ``health`` /
    ``roll_status`` forwarded ``skew_steepening`` but silently dropped
    ``skew_reference_delta``, so those surfaces always priced against
    ``crash_hedge_value``'s own ``0.10``. Sizing and the strike ladder honoured
    the IPS value, so tuning the anchor re-opened the book-vs-candidate split
    M1.7 closed — invisibly, because at the shipped 0.10 the two agree.

    These tests move the anchor off 0.10 and require the book surfaces to
    follow. Every one of them passes vacuously before the bundle.
    """

    # Far enough from the shipped 0.10 to clear solver tolerance on both sides.
    _TIGHT_ANCHOR = 0.05

    def _gauge_at(self, anchor: float) -> float:
        """Book convexity gauge at *anchor*, everything else held fixed."""
        portfolio = _make_appendix_book()
        ips = _make_appendix_ips(
            crash_scenario_pct=_APPENDIX_PCT,
            skew_reference_delta=anchor,
        )
        return PortfolioAnalyzer(portfolio).calculate_crash_convexity_pct(
            CrashShock.from_ips(ips.convexity),
        )

    def test_anchor_moves_the_health_gauge(self) -> None:
        """A tighter wing anchor changes the book convexity gauge."""
        shipped = self._gauge_at(_APPENDIX_SKEW_ANCHOR)
        tightened = self._gauge_at(self._TIGHT_ANCHOR)

        assert shipped != pytest.approx(tightened, abs=0.05)

    def test_anchor_moves_the_scenario_table(self) -> None:
        """The crash_payoff scenario rows follow the IPS anchor too."""
        portfolio = _make_appendix_book()

        def _row_convexity(anchor: float) -> float:
            ips = _make_appendix_ips(
                crash_scenario_pct=_APPENDIX_PCT,
                skew_reference_delta=anchor,
            )
            rows = crash_scenario_table(
                portfolio,
                shocks=[_APPENDIX_PCT],
                ips_convexity=ips.convexity,
            )
            return next(
                r.convexity_pct
                for r in rows
                if r.shock_pct == pytest.approx(_APPENDIX_PCT)
            )

        shipped = _row_convexity(_APPENDIX_SKEW_ANCHOR)
        tightened = _row_convexity(self._TIGHT_ANCHOR)

        assert shipped != pytest.approx(tightened, abs=0.05)

    def test_anchor_moves_the_roll_trigger(self) -> None:
        """The roll trigger's convexity follows the IPS anchor."""
        portfolio = _make_appendix_book()

        def _roll_convexity(anchor: float) -> float:
            ips = _make_appendix_ips(
                crash_scenario_pct=_APPENDIX_PCT,
                skew_reference_delta=anchor,
            )
            return evaluate_roll_status(portfolio, ips)[0].crash_convexity_pct

        shipped = _roll_convexity(_APPENDIX_SKEW_ANCHOR)
        tightened = _roll_convexity(self._TIGHT_ANCHOR)

        assert shipped != pytest.approx(tightened, abs=0.05)

    def test_book_surfaces_agree_with_each_other_off_default(self) -> None:
        """Gauge, roll trigger, and scenario table stay equal off 0.10.

        M1.7 pinned this equality only at the shipped anchor. It held under
        the old code too — the book surfaces dropped the anchor *uniformly*,
        so they agreed with each other while all three were wrong together;
        that consistency is precisely why the defect stayed invisible. What
        this adds is protection against a **partial** regression: a future
        change that re-threads the anchor through some book surfaces and not
        others breaks here. The correctness half is
        :meth:`test_book_equals_candidate_at_a_non_default_anchor`.
        """
        portfolio = _make_appendix_book()
        ips = _make_appendix_ips(
            crash_scenario_pct=_APPENDIX_PCT,
            skew_reference_delta=self._TIGHT_ANCHOR,
        )

        gauge = PortfolioAnalyzer(portfolio).calculate_crash_convexity_pct(
            CrashShock.from_ips(ips.convexity),
        )
        roll = evaluate_roll_status(portfolio, ips)[0].crash_convexity_pct
        row = next(
            r.convexity_pct
            for r in crash_scenario_table(
                portfolio,
                shocks=[_APPENDIX_PCT],
                ips_convexity=ips.convexity,
            )
            if r.shock_pct == pytest.approx(_APPENDIX_PCT)
        )

        assert roll == pytest.approx(gauge)
        assert row == pytest.approx(gauge)

    def test_book_equals_candidate_at_a_non_default_anchor(self) -> None:
        """A candidate matches the book *surface* at a non-default anchor.

        The correctness guard, and the one that actually reproduces the M1.7
        split. It reads the book side off ``compute_crash_convexity`` — a real
        panel surface, not the pricing primitive — because the primitive was
        never the thing that dropped the anchor; the surfaces calling it were.
        The candidate path has honoured the IPS anchor since M1.7, so at an
        anchor away from ``0.10`` the two agree only once the book surface
        threads it too.

        Uses a single-leg book so the surface's summed ``hedge_pnl`` is one
        contract's crash value times quantity, directly comparable to the
        candidate's per-contract figure.
        """
        strike = 5280.0
        quantity = 23
        valuation_date = datetime(2026, 1, 2, tzinfo=UTC)
        maturity = valuation_date + timedelta(days=round(1.5 * 365))
        portfolio = OptionPortfolio(
            spot_price=_APPENDIX_SPOT,
            volatility=0.20,
            risk_free_rate=0.045,
            dividend_yield=0.015,
            underlying_quantity=_APPENDIX_BOOK / _APPENDIX_SPOT,
            default_exercise_style=ExerciseStyle.EUROPEAN,
            valuation_date=valuation_date,
        )
        portfolio.add_position(
            strike_price=strike,
            maturity_date=maturity,
            quantity=quantity,
            option_type=OptionType.PUT,
            volatility=0.20,
        )
        ips = _make_appendix_ips(
            crash_scenario_pct=_APPENDIX_PCT,
            skew_reference_delta=self._TIGHT_ANCHOR,
        )
        conv = ips.convexity

        surface = compute_crash_convexity(
            portfolio,
            shock=CrashShock.from_ips(conv),
            ips_convexity=conv,
            scenario_shocks=[_APPENDIX_PCT],
        )
        book_per_contract = (
            next(
                r.hedge_pnl
                for r in surface.scenario_rows
                if r.shock_pct == pytest.approx(_APPENDIX_PCT)
            )
            / quantity
        )

        candidate = evaluate_candidate(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=conv.crash_scenario_pct,
                crash_vol_shock=conv.crash_vol_shock,
                skew_steepening=conv.skew_steepening,
                skew_reference_delta=conv.skew_reference_delta,
            ),
            strike=strike,
            maturity_years=(maturity - valuation_date).days / 365.0,
        )

        assert candidate.per_contract_payoff == pytest.approx(
            book_per_contract,
            rel=1e-6,
        )


class TestNoLegacyBasisInConvexityPaths:
    """§7.5 grep guard — the equity-netted expiry basis is gone (scoped).

    Scoped to the convexity code paths, not whole files: hedge_success
    (M2.4/#70) and the summary net "P&L @ -20%" indicator legitimately retain
    ``include_underlying`` and are out of this milestone's scope.
    """

    def test_health_gauge_source_is_repriced(self) -> None:
        """calculate_crash_convexity_pct drops the old expiry/equity basis."""
        source = inspect.getsource(
            HealthMixin.calculate_crash_convexity_pct,
        )

        assert "include_underlying" not in source
        assert "calculate_pnl_at_expiry" not in source

    def test_summary_ladder_source_is_repriced(self) -> None:
        """The summary crash-convexity ladder drops the old basis."""
        source = inspect.getsource(
            NetHedgeSummary._crash_convexity_rungs,
        )

        assert "include_underlying" not in source
        assert "calculate_pnl_at_expiry" not in source

    def test_crash_payoff_headline_source_is_repriced(self) -> None:
        """compute_crash_convexity's headline drops the old basis."""
        source = inspect.getsource(compute_crash_convexity)

        assert "include_underlying" not in source
        assert "calculate_pnl_at_expiry" not in source

    def test_shock_is_required_on_the_gauge(self) -> None:
        """The gauge's crash basis has no default — callers must pass one.

        The enforcement point, inherited from ``crash_vol_shock`` (M1.4/M1.5)
        and ``skew_steepening`` (M1.7) and now covering the whole basis: no
        site (gauge, roll trigger, summary ladder) can reprice spot-only, flat,
        or against a stand-in wing by omission.
        """
        param = inspect.signature(
            HealthMixin.calculate_crash_convexity_pct,
        ).parameters["shock"]

        assert param.default is inspect.Parameter.empty

    def test_crash_shock_has_no_field_defaults(self) -> None:
        """No ``CrashShock`` field may default — the whole basis is explicit.

        The structural form of the fail-loud rule. A default on any field
        would let a surface half-state the crash and quietly inherit the rest,
        which is exactly how ``skew_reference_delta`` came to be dropped by the
        book gauges while the candidate surfaces honoured it.
        """
        for field in dataclasses.fields(CrashShock):
            assert field.default is dataclasses.MISSING, field.name
            assert field.default_factory is dataclasses.MISSING, field.name

    def test_crash_shock_carries_no_target_band(self) -> None:
        """Pricing and policy stay on separate objects (M1.5).

        The band lives on ``IpsConvexity``. Folding it in here would mean a
        caller that omits policy silently changes what gets priced.
        """
        names = {f.name for f in dataclasses.fields(CrashShock)}

        assert "target_min_pct" not in names
        assert "target_max_pct" not in names

    def test_roll_status_sources_whole_basis_from_ips(self) -> None:
        """The roll trigger prices on the IPS basis, matching the gauge."""
        source = inspect.getsource(evaluate_roll_status)

        assert "CrashShock.from_ips(convexity)" in source

    def test_scenario_table_sources_whole_basis_from_ips(self) -> None:
        """The scenario table prices on the IPS basis, not a stand-in."""
        source = inspect.getsource(crash_scenario_table)

        assert "CrashShock.from_ips(ips_convexity)" in source

    def test_no_crash_scalar_survives_on_a_pricing_signature(self) -> None:
        """M1.8 — every crash-pricing entry point takes the object, not parts.

        The structural end-state: one pricing-input object everywhere. A
        function that still accepted, say, ``crash_vol_shock`` alongside a
        ``shock`` could be handed a half-stated basis, which is the failure
        mode this whole refactor exists to remove.
        """
        scalars = {
            "crash_pct",
            "crash_scenario_pct",
            "crash_vol_shock",
            "vol_shock",
            "skew_steepening",
            "skew_reference_delta",
        }
        entry_points = (
            cr.crash_hedge_value,
            cr.crash_convexity_pct,
            HealthMixin.calculate_crash_convexity_pct,
            compute_crash_convexity,
            crash_payoff_ratio,
            evaluate_candidate,
            NetHedgeSummary.__init__,
        )

        for fn in entry_points:
            params = set(inspect.signature(fn).parameters)
            assert not (params & scalars), f"{fn.__qualname__}: {params}"

    def test_pricing_entry_points_require_the_shock(self) -> None:
        """None of them defaults ``shock`` — a basis is always stated."""
        entry_points = (
            cr.crash_hedge_value,
            cr.crash_convexity_pct,
            HealthMixin.calculate_crash_convexity_pct,
            compute_crash_convexity,
            crash_payoff_ratio,
            evaluate_candidate,
            NetHedgeSummary.__init__,
        )

        for fn in entry_points:
            param = inspect.signature(fn).parameters["shock"]
            assert param.default is inspect.Parameter.empty, fn.__qualname__

    def test_candidate_surfaces_source_whole_basis_from_ips(self) -> None:
        """Sizing and the ladder build the basis the way the book does.

        M1.7 gave both sides one skew *function*; this pins one *construction
        path* as well, so neither can assemble a basis the other would not.
        """
        for fn in (size_hedge, build_strike_ladder):
            source = inspect.getsource(fn)
            assert "CrashShock.from_ips(ips_config.convexity)" in source, (
                fn.__qualname__
            )


class TestCanonicalExampleInvariants:
    """§7 — invariants on spx_protective_put.yaml, plus the in-band re-golden.

    Under the *flat* bump the corrected convexity at the IPS scenario (-25%,
    vol_shock 0.15) is ~+14.3% of the ~$5.8M book — positive, hedge-only, and
    repriced, but a touch below the +15..+25% floor. The shipped per-leg skew
    shock (M1.7) lifts it to ~+16.1%, comfortably in-band, so the book is
    conformant and **not re-sized** — asserted in
    :meth:`test_canonical_in_band_under_skew_not_resized`.
    """

    def test_convexity_is_positive(self) -> None:
        """The corrected convexity is positive (hedge gains in a crash)."""
        portfolio = _load_canonical_example()

        convexity = cr.crash_convexity_pct(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=-25.0,
                crash_vol_shock=0.15,
                skew_steepening=0.0,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        assert convexity > 0.0

    def test_hedge_only_invariant(self) -> None:
        """Removing the equity leg leaves the hedge value unchanged."""
        portfolio = _load_canonical_example()
        before = cr.hedge_value(portfolio)
        portfolio.underlying_quantity = 0.0

        assert cr.hedge_value(portfolio) == pytest.approx(before)

    def test_repriced_legs_positive_at_crash(self) -> None:
        """Every put leg is worth >0 at the -25% crash (repriced)."""
        portfolio = _load_canonical_example()
        crash_spot = portfolio.spot_price * 0.75

        for pos in portfolio.positions:
            value = cr._reprice_leg(
                pos,
                portfolio,
                crash_spot,
                pos.option.volatility + 0.15,
            )
            assert value > 0.0

    def test_canonical_in_band_under_skew_not_resized(self) -> None:
        """Per-leg skew lifts the canonical to ~+16.1% — in-band, not re-sized.

        The flat bump left it just under the +15% floor (~+14.3%); the
        honestly-calibrated per-leg wing steepening (M1.7) reads ~+16.1%,
        comfortably in the +15..+25% band, so no re-size is needed. The load is
        pinned to ``_FIXTURE_AS_OF`` (the fixture carries an absolute maturity),
        so this is an exact golden rather than a moving target.
        """
        portfolio = _load_canonical_example()

        convexity = cr.crash_convexity_pct(
            portfolio,
            shock=CrashShock(
                crash_scenario_pct=_APPENDIX_PCT,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )

        # Pinned load => exact golden. A loose tolerance here would re-admit
        # the theta drift the pin exists to remove.
        assert convexity == pytest.approx(16.0989, abs=0.001)
        # In-band => the conformance conclusion is "no re-size needed".
        assert 15.0 <= convexity <= 25.0
        # ...and the fixture itself is unchanged: two puts, same strikes/counts.
        puts = {
            (pos.option.strike_price, pos.quantity)
            for pos in portfolio.positions
            if pos.option.option_type == OptionType.PUT
        }
        assert puts == {(5200.0, 5), (4900.0, 5)}


class TestPerLegExerciseStyleRespected:
    """Crash repricing respects per-leg European exercise style.

    _reprice_leg() threads position.exercise_style per leg, allowing a
    mixed-style portfolio (most EUROPEAN, one AMERICAN) to reprice
    correctly. This test verifies that behavior is respected end-to-end.
    """

    def test_mixed_style_portfolio_reprices_per_leg(self) -> None:
        """Mixed EUROPEAN + AMERICAN portfolio reprices with correct styles."""
        portfolio = _make_appendix_book()

        # Add one AMERICAN leg at same strike as first ladder leg
        portfolio.add_position(
            strike_price=5280.0,
            maturity_date=portfolio.positions[0].option.maturity_date,
            quantity=23,
            option_type=OptionType.PUT,
            exercise_style=ExerciseStyle.AMERICAN,
            volatility=0.20,
        )

        crash_spot = _APPENDIX_SPOT * (1.0 + _APPENDIX_MOVE)  # -25% move
        crashed_vol = 0.20 + _APPENDIX_VOL_SHOCK

        # Reprice the two same-strike legs
        first_european = cr._reprice_leg(
            portfolio.positions[0],  # Original European leg
            portfolio,
            crash_spot,
            crashed_vol,
        )
        newly_added_american = cr._reprice_leg(
            portfolio.positions[-1],  # New American leg
            portfolio,
            crash_spot,
            crashed_vol,
        )

        # Prices must differ (same strike, qty; different style)
        assert abs(newly_added_american - first_european) > 1.0

        # American must be >= European (value of early exercise)
        assert newly_added_american >= first_european

    def test_all_european_book_reprices_to_european_engine(self) -> None:
        """All-European appendix book reprices via EUROPEAN engine only."""
        portfolio = _make_appendix_book()
        crash_spot = _APPENDIX_SPOT * (1.0 + _APPENDIX_MOVE)  # -25% move
        crashed_vol = 0.20 + _APPENDIX_VOL_SHOCK

        # Reprice via crash_repricing._reprice_leg
        first_position = portfolio.positions[0]
        repriced_value = cr._reprice_leg(
            first_position,
            portfolio,
            crash_spot,
            crashed_vol,
        )

        # Price the same leg independently with EUROPEAN engine
        direct_european = OptionValuation(
            spot_price=crash_spot,
            strike_price=first_position.option.strike_price,
            maturity_date=first_position.option.maturity_date,
            volatility=crashed_vol,
            risk_free_rate=portfolio.risk_free_rate,
            dividend_yield=portfolio.dividend_yield,
            option_type=first_position.option.option_type,
            valuation_date=portfolio.valuation_date,
            exercise_style=ExerciseStyle.EUROPEAN,
        )
        direct_value = (
            direct_european.price()
            * first_position.quantity
            * first_position.contract_size
        )

        # Repriced value must match direct European pricing
        assert repriced_value == pytest.approx(direct_value, rel=1e-9)


class TestCrashValueCurve:
    """Tests for crash_value_curve — the all-legs monitor sweep (M2.4).

    Distinct from ``compute_crash_convexity``'s ``curve`` (long-puts-only,
    scoped to the payoff-ratio question): this curve must share
    ``crash_hedge_value``'s all-legs basis so the monitor's headline number
    and its chart agree with each other.
    """

    def test_pins_to_crash_hedge_value_at_ips_shock(self) -> None:
        """The curve's IPS-depth point matches crash_hedge_value exactly."""
        portfolio = _make_appendix_book()
        shock = CrashShock(
            crash_scenario_pct=_APPENDIX_PCT,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
            skew_steepening=_APPENDIX_SKEW,
            skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
        )

        curve = cr.crash_value_curve(
            portfolio,
            shock=shock,
            shock_range=(_APPENDIX_PCT, _APPENDIX_PCT),
            n_points=1,
        )
        expected = cr.crash_hedge_value(portfolio, shock=shock)

        assert len(curve) == 1
        pct, value = curve[0]
        assert pct == pytest.approx(_APPENDIX_PCT)
        assert value == pytest.approx(expected, rel=1e-9)

    def test_mixed_leg_book_matches_crash_hedge_value_all_legs(self) -> None:
        """With a call in the book, the curve stays all-legs, not puts-only."""
        portfolio = _make_mixed_leg_book()
        shock = CrashShock(
            crash_scenario_pct=_APPENDIX_PCT,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
            skew_steepening=_APPENDIX_SKEW,
            skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
        )

        curve = cr.crash_value_curve(
            portfolio,
            shock=shock,
            shock_range=(_APPENDIX_PCT, _APPENDIX_PCT),
            n_points=1,
        )
        expected_all_legs = cr.crash_hedge_value(portfolio, shock=shock)

        _, curve_value = curve[0]
        assert curve_value == pytest.approx(expected_all_legs, rel=1e-9)

    def test_mixed_leg_book_curve_differs_from_puts_only_curve(self) -> None:
        """The all-legs curve is NOT the puts-only crash_payoff curve.

        Proves the two curves are genuinely different bases on a book that
        actually holds a non-put leg — not accidentally equal because every
        other fixture in this file happens to be all-long-puts.
        """
        portfolio = _make_mixed_leg_book()
        shock = CrashShock(
            crash_scenario_pct=_APPENDIX_PCT,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
            skew_steepening=_APPENDIX_SKEW,
            skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
        )

        all_legs_curve = cr.crash_value_curve(
            portfolio,
            shock=shock,
            shock_range=(_APPENDIX_PCT, _APPENDIX_PCT),
            n_points=1,
        )
        _, all_legs_value = all_legs_curve[0]

        puts_only_result = compute_crash_convexity(
            portfolio,
            shock=dataclasses.replace(shock, crash_scenario_pct=0.0),
            ips_convexity=IpsConvexity(
                crash_scenario_pct=_APPENDIX_PCT,
                target_min_pct=15.0,
                target_max_pct=25.0,
                crash_vol_shock=_APPENDIX_VOL_SHOCK,
                skew_steepening=_APPENDIX_SKEW,
                skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
            ),
        )
        puts_only_row = next(
            r
            for r in puts_only_result.scenario_rows
            if r.shock_pct == pytest.approx(_APPENDIX_PCT, rel=1e-4)
        )

        # The short call is excluded from the puts-only curve but included
        # (as a negative contribution) in the all-legs curve, so the two
        # must genuinely differ, not just be computed by different code.
        assert all_legs_value != pytest.approx(puts_only_row.hedge_pnl)
        assert all_legs_value < puts_only_row.hedge_pnl

    def test_all_long_puts_book_value_rises_as_shock_severity_rises(
        self,
    ) -> None:
        """Puts gain value as the spot shock gets more negative/severe."""
        portfolio = _make_appendix_book()
        shock = CrashShock(
            crash_scenario_pct=_APPENDIX_PCT,
            crash_vol_shock=_APPENDIX_VOL_SHOCK,
            skew_steepening=_APPENDIX_SKEW,
            skew_reference_delta=_APPENDIX_SKEW_ANCHOR,
        )

        curve = cr.crash_value_curve(portfolio, shock=shock)

        # Sorted ascending by shock_pct (most severe/negative first), so
        # values must be non-increasing across the grid.
        values = [value for _, value in curve]
        assert values == sorted(values, reverse=True)
        assert values[0] > values[-1]


class TestUnderlyingPnl:
    """Tests for underlying_pnl — scenario-local underlying P&L (M2.4)."""

    def test_zero_shock_is_zero_pnl(self) -> None:
        """No spot move means no underlying P&L, regardless of quantity."""
        pnl = cr.underlying_pnl(
            quantity=3000.0,
            spot_price=6600.0,
            spot_shock=0.0,
        )

        assert pnl == pytest.approx(0.0)

    def test_long_quantity_with_negative_shock_is_negative_pnl(self) -> None:
        """A long underlying position loses money when spot drops."""
        pnl = cr.underlying_pnl(
            quantity=3000.0,
            spot_price=6600.0,
            spot_shock=-0.25,
        )

        assert pnl == pytest.approx(3000.0 * 6600.0 * -0.25)
        assert pnl < 0.0

    def test_short_quantity_with_negative_shock_is_positive_pnl(self) -> None:
        """A short underlying position gains money when spot drops."""
        pnl = cr.underlying_pnl(
            quantity=-3000.0,
            spot_price=6600.0,
            spot_shock=-0.25,
        )

        assert pnl == pytest.approx(-3000.0 * 6600.0 * -0.25)
        assert pnl > 0.0
