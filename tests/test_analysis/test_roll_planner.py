"""Tests for deltadewa.analysis.roll_planner."""

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis import roll_status
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.analysis.roll_planner import (
    RollAction,
    RollPlanRecord,
    build_roll_plan,
    gamma_theta_delay,
    group_into_structures,
    net_structure_roll_cost,
    structure_target_strikes,
)
from deltadewa.analysis.roll_status import (
    RollVerdict,
    estimate_roll_up_cost,
    evaluate_roll_status,
)
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
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.position import OptionPosition
from deltadewa.valuation import OptionValuation
from tests.clock_helpers import days_from_today

_SPOT = 100.0
_VOL = 0.20
_RATE = 0.04


def _make_ips_config(
    *,
    roll_at_months_remaining: float = 1.0,
    roll_review_buffer: float = 1.5,
    strike_drift_max_otm_pct: float = 45.0,
    strike_drift_review_fraction: float = 0.75,
    crash_scenario_pct: float = -25.0,
    target_min_pct: float = 15.0,
    target_max_pct: float = 25.0,
) -> IpsConfig:
    return IpsConfig(
        program=IpsProgram(name="test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=crash_scenario_pct,
            target_min_pct=target_min_pct,
            target_max_pct=target_max_pct,
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=20.0),
        triggers=IpsTriggers(
            delta_ratio_deviation_warn_pct=5.0,
            delta_ratio_deviation_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_at_months_remaining=roll_at_months_remaining,
            rally_rebalance_pct=15.0,
            strike_drift_max_otm_pct=strike_drift_max_otm_pct,
            roll_review_buffer=roll_review_buffer,
            strike_drift_review_fraction=strike_drift_review_fraction,
        ),
        monetization=IpsMonetization(schedule=()),
    )


def _make_put(
    spot_price: float = _SPOT,
    strike_price: float = 90.0,
    days_to_maturity: int = 200,
    quantity: int = 5,
    entry_spot: float | None = _SPOT,
    volatility: float = _VOL,
) -> OptionPosition:
    option = OptionValuation(
        spot_price=spot_price,
        strike_price=strike_price,
        maturity_date=datetime.now(tz=UTC) + timedelta(days=days_to_maturity),
        volatility=volatility,
        risk_free_rate=_RATE,
        dividend_yield=0.0,
        option_type=OptionType.PUT,
        exercise_style=ExerciseStyle.EUROPEAN,
    )
    return OptionPosition(
        option=option,
        quantity=quantity,
        exercise_style=ExerciseStyle.EUROPEAN,
        entry_spot=entry_spot,
        entry_date=datetime.now(tz=UTC) - timedelta(days=30),
    )


def _portfolio_with(*positions: OptionPosition) -> OptionPortfolio:
    portfolio = OptionPortfolio(spot_price=positions[0].option.spot_price)
    for pos in positions:
        portfolio.positions.append(pos)
    return portfolio


def _patch_convexity(
    monkeypatch: pytest.MonkeyPatch,
    value: float,
) -> None:
    def _fake(self: object, shock: CrashShock) -> float:
        return value

    monkeypatch.setattr(
        roll_status.PortfolioAnalyzer,
        "calculate_crash_convexity_pct",
        _fake,
    )


# ---------------------------------------------------------------------------
# gamma_theta_delay — pure logic, no portfolio
# ---------------------------------------------------------------------------


class TestGammaThetaDelay:
    """Truth-table tests for gamma_theta_delay."""

    def _triggers(
        self,
        roll_at_months_remaining: float = 1.0,
    ) -> IpsTriggers:
        return IpsTriggers(
            delta_ratio_deviation_warn_pct=5.0,
            delta_ratio_deviation_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_at_months_remaining=roll_at_months_remaining,
            rally_rebalance_pct=15.0,
            strike_drift_max_otm_pct=10.0,
        )

    def _convexity(
        self,
        target_min_pct: float = 15.0,
        target_max_pct: float = 25.0,
    ) -> IpsConvexity:
        return IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=target_min_pct,
            target_max_pct=target_max_pct,
        )

    def _delay(
        self,
        *,
        months_to_maturity: float = 3.0,
        convexity_now_pct: float = 20.0,
        drift_pct: float | None = -5.0,
        roll_at_months_remaining: float = 1.0,
    ) -> bool:
        """Call gamma_theta_delay with all three conditions satisfied.

        Defaults sit squarely in the delay case — outside the roll
        window, convexity mid-band, put nearer the money — so each test
        varies exactly one condition.
        """
        return gamma_theta_delay(
            months_to_maturity=months_to_maturity,
            convexity_now_pct=convexity_now_pct,
            drift_pct=drift_pct,
            ips_triggers=self._triggers(
                roll_at_months_remaining=roll_at_months_remaining
            ),
            ips_convexity=self._convexity(15.0, 25.0),
        )

    def test_all_three_conditions_met_returns_true(self) -> None:
        """Outside window + convexity in band + nearer the money → delay."""
        assert self._delay() is True

    def test_inside_roll_window_returns_false(self) -> None:
        """Inside the roll window overrides the other two checks."""
        assert self._delay(months_to_maturity=0.5) is False

    def test_exactly_at_roll_window_boundary_returns_false(self) -> None:
        """Equality is not 'outside' — delay requires strictly greater."""
        assert self._delay(months_to_maturity=1.0) is False

    def test_convexity_below_min_returns_false(self) -> None:
        """Convexity out of band (too low) → don't delay; need to roll."""
        assert self._delay(convexity_now_pct=10.0) is False

    def test_convexity_above_max_returns_false(self) -> None:
        """Convexity out of band (too high) → don't delay."""
        assert self._delay(convexity_now_pct=30.0) is False

    # ------------------------------------------------------------------
    # Handbook (https://github.com/qwertytam/deltadewa-handbook) condition
    # (b): "the put has moved meaningfully nearer to the money". Without it
    # the deferral also fires on a market rally, recommending inaction on a
    # live Rule 2 rebalance trigger while citing gamma the position is not
    # accumulating.
    # ------------------------------------------------------------------

    def test_drifted_further_otm_returns_false(self) -> None:
        """A rallied put is losing gamma, not gaining it → never delay."""
        assert self._delay(drift_pct=+8.0) is False

    def test_zero_drift_returns_false(self) -> None:
        """Unmoved put has no gamma story; 'nearer' is strict."""
        assert self._delay(drift_pct=0.0) is False

    def test_unknown_drift_returns_false(self) -> None:
        """No entry_spot → gamma story unverifiable → the roll stands."""
        assert self._delay(drift_pct=None) is False

    def test_rally_is_not_rescued_by_a_healthy_convexity_band(self) -> None:
        """Convexity in band does not license deferring a rally trigger.

        This is the inversion the surface must never show: every other
        condition is comfortable, so only the drift sign separates
        "defer, you are gaining gamma" from "roll up, you are not".
        """
        assert self._delay(drift_pct=-0.1) is True
        assert self._delay(drift_pct=+0.1) is False


# ---------------------------------------------------------------------------
# build_roll_plan
# ---------------------------------------------------------------------------


class TestBuildRollPlan:
    """Integration tests for build_roll_plan on crafted portfolios."""

    # ------------------------------------------------------------------
    # Scenario A: put has rallied far OTM (drift > threshold → ROLL)
    #   entry_spot=100, current spot=120, strike=80
    #   entry_otm=20%, current_otm≈33%, drift≈13% > max_drift=10%
    # ------------------------------------------------------------------

    def _rallied_position(self) -> OptionPosition:
        """Put that has moved far OTM after a 20% rally."""
        return _make_put(
            spot_price=120.0,
            strike_price=80.0,
            days_to_maturity=90,
            entry_spot=100.0,
        )

    def test_rallied_far_otm_has_roll_or_review_verdict(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Far-OTM rallied put has REVIEW or ROLL verdict."""
        _patch_convexity(monkeypatch, 20.0)
        pos = self._rallied_position()
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config(
            strike_drift_max_otm_pct=10.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        records = build_roll_plan(portfolio, ips)

        assert len(records) == 1
        assert records[0].verdict in (RollVerdict.REVIEW, RollVerdict.ROLL)

    def test_rallied_far_otm_target_strike_populated(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Target strike is computed and roll cost is non-zero."""
        _patch_convexity(monkeypatch, 20.0)
        pos = self._rallied_position()
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config(strike_drift_max_otm_pct=10.0)

        records = build_roll_plan(portfolio, ips)

        rec = records[0]
        assert rec.target_strike is not None
        # Restores 20% OTM at spot 120 → 96.0
        assert rec.target_strike == pytest.approx(96.0)
        assert rec.roll_up_cost is not None
        assert rec.roll_up_cost != pytest.approx(0.0)

    def test_rallied_outside_window_in_band_yields_roll_now(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A rallied put is never deferred, however healthy the band.

        The put has drifted *further* OTM (+13%), so the handbook's
        gamma/theta deferral does not apply — this is Rule 2's market
        rally rebalance trigger and the sanctioned action is to roll up.
        Deferring here would sit on a live signal.
        """
        _patch_convexity(monkeypatch, 20.0)
        pos = self._rallied_position()  # 90 days >> 30-day window
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config(
            roll_at_months_remaining=1.0,
            strike_drift_max_otm_pct=10.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        records = build_roll_plan(portfolio, ips)

        assert records[0].action == RollAction.ROLL_NOW
        assert "further OTM" in records[0].rationale

    # ------------------------------------------------------------------
    # Scenario B: market has declined, put is nearer the money
    #   entry_spot=100, current spot=90, strike=80
    #   entry_otm=20%, current_otm≈11%, drift≈-8.9%
    #   With max_drift=10% and review_fraction=0.75 the drift trigger is
    #   REVIEW, which is actionable but not suppressed by roll_status.
    # ------------------------------------------------------------------

    def _declined_position(self, days_to_maturity: int = 90) -> OptionPosition:
        """Put that has moved nearer the money after a 10% decline."""
        return _make_put(
            spot_price=90.0,
            strike_price=80.0,
            days_to_maturity=days_to_maturity,
            entry_spot=100.0,
        )

    def test_nearer_the_money_outside_window_in_band_yields_delay(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The handbook's sanctioned deferral: gaining gamma → DELAY."""
        _patch_convexity(monkeypatch, 20.0)
        pos = self._declined_position()
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config(
            roll_at_months_remaining=1.0,
            strike_drift_max_otm_pct=10.0,
            strike_drift_review_fraction=0.75,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        records = build_roll_plan(portfolio, ips)

        assert records[0].verdict in (RollVerdict.REVIEW, RollVerdict.ROLL)
        assert records[0].action == RollAction.DELAY

    def test_delay_rationale_names_all_three_conditions(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DELAY explains itself: gamma, roll window, and convexity band.

        A bare verdict word on a fired trigger is not actionable, so the
        rationale must carry the IPS values it was measured against.
        """
        _patch_convexity(monkeypatch, 20.0)
        pos = self._declined_position()
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config(
            roll_at_months_remaining=1.0,
            strike_drift_max_otm_pct=10.0,
            strike_drift_review_fraction=0.75,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        rationale = build_roll_plan(portfolio, ips)[0].rationale

        assert "nearer the money" in rationale
        assert "gamma" in rationale
        assert "roll window" in rationale
        # The IPS band, not a hardcoded one.
        assert "15-25% IPS target band" in rationale

    def test_unknown_drift_is_not_deferred(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No entry_spot → no gamma story → ROLL_NOW, not DELAY.

        Time trigger sits in the REVIEW buffer (40d vs a 30d window,
        1.5x buffer), so the verdict is actionable while the position is
        still outside the mandatory window — isolating the drift leg.
        """
        _patch_convexity(monkeypatch, 20.0)
        pos = _make_put(days_to_maturity=40, entry_spot=None)
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config(
            roll_at_months_remaining=1.0,
            roll_review_buffer=1.5,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        records = build_roll_plan(portfolio, ips)

        assert records[0].verdict == RollVerdict.REVIEW
        assert records[0].action == RollAction.ROLL_NOW

    def test_inside_roll_window_yields_roll_now(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Inside mandatory roll window → ROLL_NOW regardless of convexity."""
        _patch_convexity(monkeypatch, 20.0)
        pos = _make_put(
            spot_price=120.0,
            strike_price=80.0,
            days_to_maturity=10,  # ~0.33 mo << 1-mo window
            entry_spot=100.0,
        )
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config(
            roll_at_months_remaining=1.0,
            strike_drift_max_otm_pct=10.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        records = build_roll_plan(portfolio, ips)

        assert records[0].action == RollAction.ROLL_NOW

    def test_convexity_out_of_band_yields_roll_now(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Convexity below target → ROLL_NOW (no delay when band breached)."""
        _patch_convexity(monkeypatch, 5.0)  # below target_min=15
        pos = self._rallied_position()
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config(
            roll_at_months_remaining=1.0,
            strike_drift_max_otm_pct=10.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        records = build_roll_plan(portfolio, ips)

        assert records[0].action == RollAction.ROLL_NOW

    # ------------------------------------------------------------------
    # No trigger → HOLD
    # ------------------------------------------------------------------

    def test_no_trigger_yields_hold(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Comfortable position with no trigger → HOLD action."""
        _patch_convexity(monkeypatch, 20.0)
        pos = _make_put(
            spot_price=_SPOT,
            strike_price=90.0,
            days_to_maturity=200,
            entry_spot=_SPOT,
        )
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config(
            roll_at_months_remaining=1.0,
            strike_drift_max_otm_pct=45.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        records = build_roll_plan(portfolio, ips)

        assert records[0].action == RollAction.HOLD

    # ------------------------------------------------------------------
    # Verdict consistency with evaluate_roll_status
    # ------------------------------------------------------------------

    def test_verdict_matches_evaluate_roll_status(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """build_roll_plan verdict is identical to evaluate_roll_status."""
        _patch_convexity(monkeypatch, 20.0)
        pos = self._rallied_position()
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config(strike_drift_max_otm_pct=10.0)

        plan_records = build_roll_plan(portfolio, ips)
        status_records = [
            r
            for r in evaluate_roll_status(portfolio, ips)
            if r.position.option.option_type == OptionType.PUT
            and r.position.quantity > 0
        ]

        assert len(plan_records) == len(status_records)
        for plan, status in zip(plan_records, status_records, strict=True):
            assert plan.verdict == status.verdict

    # ------------------------------------------------------------------
    # Edge: empty portfolio
    # ------------------------------------------------------------------

    def test_empty_portfolio_returns_empty_list(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An empty portfolio produces an empty plan without raising."""
        _patch_convexity(monkeypatch, 20.0)
        portfolio = OptionPortfolio(spot_price=_SPOT)
        ips = _make_ips_config()

        records = build_roll_plan(portfolio, ips)

        assert records == []

    # ------------------------------------------------------------------
    # Edge: missing entry_spot (target_strike/cost degrade to None)
    # ------------------------------------------------------------------

    def test_missing_entry_spot_does_not_raise(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """entry_spot=None yields target_strike=None without raising."""
        _patch_convexity(monkeypatch, 20.0)
        pos = _make_put(entry_spot=None)
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config()

        records = build_roll_plan(portfolio, ips)

        assert len(records) == 1
        rec = records[0]
        assert rec.target_strike is None
        assert rec.roll_up_cost is None

    # ------------------------------------------------------------------
    # Edge: non-long-put positions are excluded
    # ------------------------------------------------------------------

    def test_short_put_excluded_from_plan(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Short put is listed with a reason, never silently dropped."""
        _patch_convexity(monkeypatch, 20.0)
        long_put = _make_put(quantity=5)
        short_put = _make_put(quantity=-5)
        portfolio = _portfolio_with(long_put, short_put)
        ips = _make_ips_config()

        records = build_roll_plan(portfolio, ips)

        assert len(records) == 2
        by_position = {r.position.position_id: r for r in records}
        assert by_position[long_put.position_id].action is not None
        excluded = by_position[short_put.position_id]
        assert excluded.action is None
        assert excluded.excluded_reason is not None
        assert "short put" in excluded.excluded_reason

    def test_call_position_excluded_from_plan(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A CALL is listed with a reason, never silently dropped."""
        _patch_convexity(monkeypatch, 20.0)
        long_put = _make_put(quantity=5, spot_price=_SPOT)
        call_option = OptionValuation(
            spot_price=_SPOT,
            strike_price=110.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=200),
            volatility=_VOL,
            risk_free_rate=_RATE,
            dividend_yield=0.0,
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.EUROPEAN,
        )
        long_call = OptionPosition(
            option=call_option,
            quantity=5,
            exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio = _portfolio_with(long_put, long_call)
        ips = _make_ips_config()

        records = build_roll_plan(portfolio, ips)

        assert len(records) == 2
        excluded = next(r for r in records if r.action is None)
        assert excluded.position is long_call
        assert excluded.excluded_reason is not None
        assert "not a protective put" in excluded.excluded_reason
        assert records[0].position is long_put

    # ------------------------------------------------------------------
    # RollPlanRecord field checks
    # ------------------------------------------------------------------

    def test_record_fields_are_populated(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """All mandatory fields on RollPlanRecord are non-None and typed."""
        _patch_convexity(monkeypatch, 20.0)
        pos = _make_put()
        portfolio = _portfolio_with(pos)
        ips = _make_ips_config()

        records = build_roll_plan(portfolio, ips)

        rec = records[0]
        assert isinstance(rec, RollPlanRecord)
        assert isinstance(rec.verdict, RollVerdict)
        assert isinstance(rec.action, RollAction)
        assert isinstance(rec.convexity_now_pct, float)
        assert isinstance(rec.meets_convexity_target, bool)
        assert isinstance(rec.gamma, float)
        assert isinstance(rec.theta, float)
        assert isinstance(rec.rationale, str)
        assert len(rec.rationale) > 0
        # Long put: theta should be negative, gamma positive
        assert rec.theta < 0.0
        assert rec.gamma > 0.0


# ======================================================================
# #333 — spreads roll as a unit
# ======================================================================


def _spread_leg(
    *,
    strike_price: float,
    quantity: int,
    structure_id: str | None,
    days_to_maturity: int = 200,
) -> OptionPosition:
    """A put leg tagged into a structure, seeded off the program clock."""
    option = OptionValuation(
        spot_price=_SPOT,
        strike_price=strike_price,
        maturity_date=days_from_today(days_to_maturity),
        volatility=_VOL,
        risk_free_rate=_RATE,
        dividend_yield=0.0,
        option_type=OptionType.PUT,
        exercise_style=ExerciseStyle.EUROPEAN,
    )
    return OptionPosition(
        option=option,
        quantity=quantity,
        exercise_style=ExerciseStyle.EUROPEAN,
        entry_spot=_SPOT,
        entry_date=days_from_today(-30),
        structure_id=structure_id,
    )


class TestGroupIntoStructures:
    """Grouping is by the explicit tag only — never inferred."""

    def test_untagged_legs_are_single_leg_structures(self) -> None:
        """The property that leaves every pre-existing book unchanged."""
        legs = [_make_put(quantity=5), _make_put(quantity=3)]

        structures = group_into_structures(legs)

        assert len(structures) == 2
        assert all(not s.is_spread for s in structures)
        assert all(s.structure_id is None for s in structures)

    def test_shared_tag_groups_legs(self) -> None:
        long_leg = _spread_leg(
            strike_price=90.0,
            quantity=5,
            structure_id="spread-a",
        )
        short_leg = _spread_leg(
            strike_price=80.0,
            quantity=-5,
            structure_id="spread-a",
        )

        structures = group_into_structures([long_leg, short_leg])

        assert len(structures) == 1
        assert structures[0].is_spread
        assert structures[0].legs == (long_leg, short_leg)
        assert structures[0].anchor is long_leg

    def test_same_maturity_and_sign_are_not_inferred_together(self) -> None:
        """Inference would mispair a book that legs in separately (#333)."""
        a = _spread_leg(strike_price=90.0, quantity=5, structure_id=None)
        b = _spread_leg(strike_price=80.0, quantity=-5, structure_id=None)

        assert len(group_into_structures([a, b])) == 2

    def test_overlapping_spreads_on_one_expiry_stay_distinct(self) -> None:
        legs = [
            _spread_leg(strike_price=90.0, quantity=5, structure_id="a"),
            _spread_leg(strike_price=80.0, quantity=-5, structure_id="a"),
            _spread_leg(strike_price=85.0, quantity=3, structure_id="b"),
            _spread_leg(strike_price=75.0, quantity=-3, structure_id="b"),
        ]

        structures = group_into_structures(legs)

        assert [s.structure_id for s in structures] == ["a", "b"]
        assert all(len(s.legs) == 2 for s in structures)

    def test_empty_book_yields_no_structures(self) -> None:
        """Degenerate case: empty."""
        assert group_into_structures([]) == ()

    def test_structure_with_no_long_put_has_no_anchor(self) -> None:
        """Degenerate case: nothing to plan a roll around."""
        short_only = _spread_leg(
            strike_price=80.0,
            quantity=-5,
            structure_id="s",
        )

        assert group_into_structures([short_only])[0].anchor is None


class TestStructureGeometryAndCost:
    """A spread keeps its percentage width, and its cost nets."""

    def test_targets_preserve_percentage_width(self) -> None:
        long_leg = _spread_leg(
            strike_price=90.0,
            quantity=5,
            structure_id="s",
        )
        short_leg = _spread_leg(
            strike_price=80.0,
            quantity=-5,
            structure_id="s",
        )
        structure = group_into_structures([long_leg, short_leg])[0]

        targets = structure_target_strikes(structure, anchor_target_strike=99.0)

        # 90 -> 99 is +10%; the short leg moves by the same ratio, so the
        # spread stays 8/9ths as wide relative to its anchor.
        assert targets[long_leg.position_id] == pytest.approx(99.0)
        assert targets[short_leg.position_id] == pytest.approx(88.0)
        ratio_before = short_leg.option.strike_price / 90.0
        ratio_after = targets[short_leg.position_id] / 99.0
        assert ratio_after == pytest.approx(ratio_before)

    def test_netted_cost_is_the_sum_of_its_legs(self) -> None:
        """The sign question: short quantity already carries the credit."""
        long_leg = _spread_leg(
            strike_price=90.0,
            quantity=5,
            structure_id="s",
        )
        short_leg = _spread_leg(
            strike_price=80.0,
            quantity=-5,
            structure_id="s",
        )
        structure = group_into_structures([long_leg, short_leg])[0]
        targets = structure_target_strikes(structure, anchor_target_strike=99.0)

        netted = net_structure_roll_cost(structure, targets)
        long_cost = estimate_roll_up_cost(
            long_leg,
            targets[long_leg.position_id],
            long_leg.option.volatility,
        )
        short_cost = estimate_roll_up_cost(
            short_leg,
            targets[short_leg.position_id],
            short_leg.option.volatility,
        )

        assert netted == pytest.approx(long_cost + short_cost)
        # The short leg's contribution really is a credit — if it were not,
        # summing the legs would be the wrong operation.
        assert short_cost < 0
        assert netted < long_cost

    def test_single_leg_structure_costs_what_the_leg_costs(self) -> None:
        """Degenerate case: an outright put is a structure of one."""
        leg = _spread_leg(strike_price=90.0, quantity=5, structure_id=None)
        structure = group_into_structures([leg])[0]
        targets = structure_target_strikes(structure, anchor_target_strike=99.0)

        assert net_structure_roll_cost(structure, targets) == pytest.approx(
            estimate_roll_up_cost(leg, 99.0, leg.option.volatility),
        )


class TestRollPlanCoversEveryLeg:
    """No leg is ever silently absent from the plan (#333)."""

    def test_spread_legs_share_one_netted_cost(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_convexity(monkeypatch, 20.0)
        long_leg = _spread_leg(
            strike_price=90.0,
            quantity=5,
            structure_id="s",
        )
        short_leg = _spread_leg(
            strike_price=80.0,
            quantity=-5,
            structure_id="s",
        )
        portfolio = _portfolio_with(long_leg, short_leg)

        records = build_roll_plan(portfolio, _make_ips_config())

        assert len(records) == 2
        by_id = {r.position.position_id: r for r in records}
        planned = by_id[long_leg.position_id]
        skipped = by_id[short_leg.position_id]
        assert planned.structure_id == "s"
        assert skipped.structure_id == "s"
        assert skipped.action is None
        assert skipped.excluded_reason is not None
        assert "rolls with its structure" in skipped.excluded_reason

    def test_outright_long_put_is_unchanged_by_the_structure_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The acceptance criterion: single-leg behaviour is untouched."""
        _patch_convexity(monkeypatch, 20.0)
        pos = _make_put(quantity=5)
        portfolio = _portfolio_with(pos)

        records = build_roll_plan(portfolio, _make_ips_config())

        assert len(records) == 1
        rec = records[0]
        assert rec.structure_id is None
        assert rec.excluded_reason is None
        assert rec.action is not None
        assert rec.target_strike is not None

    def test_expired_leg_is_listed_as_expired_not_as_a_short_leg(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Expiry settles what to do with it, so it is reported first."""
        _patch_convexity(monkeypatch, 20.0)
        expired = _spread_leg(
            strike_price=90.0,
            quantity=-5,
            structure_id=None,
            days_to_maturity=-40,
        )
        portfolio = _portfolio_with(expired)

        records = build_roll_plan(portfolio, _make_ips_config())

        assert len(records) == 1
        assert records[0].action is None
        assert records[0].excluded_reason is not None
        assert "expired" in records[0].excluded_reason

    def test_records_come_back_in_portfolio_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_convexity(monkeypatch, 20.0)
        legs = [
            _spread_leg(strike_price=90.0, quantity=5, structure_id="s"),
            _make_put(quantity=3, strike_price=70.0),
            _spread_leg(strike_price=80.0, quantity=-5, structure_id="s"),
        ]
        portfolio = _portfolio_with(*legs)

        records = build_roll_plan(portfolio, _make_ips_config())

        assert [r.position.position_id for r in records] == [
            leg.position_id for leg in legs
        ]

    def test_empty_book_yields_an_empty_plan(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Degenerate case: empty."""
        _patch_convexity(monkeypatch, 20.0)

        portfolio = OptionPortfolio(spot_price=_SPOT)

        assert build_roll_plan(portfolio, _make_ips_config()) == []
