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
)
from deltadewa.analysis.roll_status import RollVerdict, evaluate_roll_status
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

_SPOT = 100.0
_VOL = 0.20
_RATE = 0.04


def _make_ips_config(
    *,
    roll_time_months: float = 1.0,
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
            delta_drift_warn_pct=5.0,
            delta_drift_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_time_months=roll_time_months,
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
        roll_time_months: float = 1.0,
    ) -> IpsTriggers:
        return IpsTriggers(
            delta_drift_warn_pct=5.0,
            delta_drift_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_time_months=roll_time_months,
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
        roll_time_months: float = 1.0,
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
            ips_triggers=self._triggers(roll_time_months=roll_time_months),
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
            roll_time_months=1.0,
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
            roll_time_months=1.0,
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
            roll_time_months=1.0,
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
            roll_time_months=1.0,
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
            roll_time_months=1.0,
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
            roll_time_months=1.0,
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
            roll_time_months=1.0,
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
        """Short put (quantity < 0) is not included in the plan."""
        _patch_convexity(monkeypatch, 20.0)
        long_put = _make_put(quantity=5)
        short_put = _make_put(quantity=-5)
        portfolio = _portfolio_with(long_put, short_put)
        ips = _make_ips_config()

        records = build_roll_plan(portfolio, ips)

        assert len(records) == 1
        assert records[0].position is long_put

    def test_call_position_excluded_from_plan(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CALL position is not included in the put-only plan."""
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

        assert len(records) == 1
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
