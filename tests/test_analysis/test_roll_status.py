"""Tests for deltadewa.analysis.roll_status."""

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis import roll_status
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.analysis.roll_status import (
    RollVerdict,
    compute_moneyness_drift,
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


def _make_position(
    option_type: OptionType = OptionType.PUT,
    spot_price: float = 100.0,
    strike_price: float = 90.0,
    days_to_maturity: int = 200,
    quantity: int = 10,
    entry_spot: float | None = 100.0,
    volatility: float = 0.2,
) -> OptionPosition:
    option = OptionValuation(
        spot_price=spot_price,
        strike_price=strike_price,
        maturity_date=datetime.now(tz=UTC) + timedelta(days=days_to_maturity),
        volatility=volatility,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        option_type=option_type,
        exercise_style=ExerciseStyle.EUROPEAN,
    )
    return OptionPosition(
        option=option,
        quantity=quantity,
        exercise_style=ExerciseStyle.EUROPEAN,
        entry_spot=entry_spot,
        entry_date=datetime.now(tz=UTC) - timedelta(days=30),
    )


class TestComputeMoneynessDrift:
    """Tests for compute_moneyness_drift."""

    def test_call_otm_positive_above_strike_unreached(self) -> None:
        """Test a CALL below its strike is OTM (positive %OTM)."""
        position = _make_position(
            option_type=OptionType.CALL,
            strike_price=110.0,
            entry_spot=100.0,
        )

        drift = compute_moneyness_drift(position, current_spot=100.0)

        assert drift.current_otm_pct == pytest.approx(10.0)

    def test_put_otm_positive_below_strike_unreached(self) -> None:
        """Test a PUT above its strike is OTM (positive %OTM)."""
        position = _make_position(
            option_type=OptionType.PUT,
            strike_price=90.0,
            entry_spot=100.0,
        )

        drift = compute_moneyness_drift(position, current_spot=100.0)

        assert drift.current_otm_pct == pytest.approx(10.0)

    def test_drift_pct_is_difference_of_otm(self) -> None:
        """Test drift_pct equals current_otm_pct - entry_otm_pct."""
        position = _make_position(
            option_type=OptionType.PUT,
            strike_price=90.0,
            entry_spot=100.0,
        )

        drift = compute_moneyness_drift(position, current_spot=95.0)

        assert drift.entry_otm_pct is not None
        assert drift.drift_pct is not None
        assert drift.entry_otm_pct == pytest.approx(10.0)
        assert drift.current_otm_pct == pytest.approx((95 - 90) / 95 * 100)
        assert drift.drift_pct == pytest.approx(
            drift.current_otm_pct - drift.entry_otm_pct,
        )
        assert drift.drift_pct < 0  # moved nearer the money

    def test_no_entry_spot_yields_none_entry_and_drift(self) -> None:
        """Test missing entry_spot yields None entry_otm_pct/drift_pct."""
        position = _make_position(entry_spot=None)

        drift = compute_moneyness_drift(position, current_spot=95.0)

        assert drift.entry_otm_pct is None
        assert drift.drift_pct is None
        assert drift.current_otm_pct is not None


class TestEstimateRollUpCost:
    """Tests for estimate_roll_up_cost."""

    def test_same_strike_and_vol_costs_approximately_zero(self) -> None:
        """Test rolling to the same strike/vol costs ~nothing."""
        position = _make_position(option_type=OptionType.PUT, strike_price=90.0)

        cost = estimate_roll_up_cost(
            position,
            new_strike=90.0,
            vol=position.option.volatility,
        )

        assert cost == pytest.approx(0.0, abs=1e-6)

    def test_rolling_put_to_higher_strike_costs_more(self) -> None:
        """Test rolling a long put closer to the money costs more (debit)."""
        position = _make_position(
            option_type=OptionType.PUT,
            strike_price=90.0,
            quantity=10,
        )

        cost = estimate_roll_up_cost(
            position,
            new_strike=98.0,
            vol=position.option.volatility,
        )

        assert cost > 0


class TestTriggerHelpers:
    """Direct tests of the private trigger-verdict helpers."""

    def test_time_trigger_roll_within_window(self) -> None:
        """Test ROLL when days_to_maturity is within the roll window."""
        trigger = roll_status._time_trigger_verdict(
            days_to_maturity=10,
            roll_window_days=30,
            review_buffer=1.5,
        )

        assert trigger.verdict == RollVerdict.ROLL
        assert "10d" in trigger.reason
        assert "30d" in trigger.reason

    def test_time_trigger_review_within_buffer(self) -> None:
        """Test REVIEW when within the buffered window but not the window."""
        trigger = roll_status._time_trigger_verdict(
            days_to_maturity=40,
            roll_window_days=30,
            review_buffer=1.5,
        )

        assert trigger.verdict == RollVerdict.REVIEW
        assert "40d" in trigger.reason
        assert "30d" in trigger.reason

    def test_time_trigger_hold_outside_buffer(self) -> None:
        """Test HOLD when well outside the roll window."""
        trigger = roll_status._time_trigger_verdict(
            days_to_maturity=100,
            roll_window_days=30,
            review_buffer=1.5,
        )

        assert trigger.verdict == RollVerdict.HOLD
        assert "100d" in trigger.reason
        assert "30d" in trigger.reason

    def test_convexity_trigger_roll_below_min(self) -> None:
        """Test ROLL when crash convexity is below the target band."""
        trigger = roll_status._convexity_trigger_verdict(
            crash_convexity_pct=5.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        assert trigger.verdict == RollVerdict.ROLL
        assert "5.0%" in trigger.reason
        assert "15-25%" in trigger.reason

    def test_convexity_trigger_monitor_above_max(self) -> None:
        """Test MONITOR when crash convexity exceeds the target band."""
        trigger = roll_status._convexity_trigger_verdict(
            crash_convexity_pct=40.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        assert trigger.verdict == RollVerdict.MONITOR
        assert "40.0%" in trigger.reason
        assert "15-25%" in trigger.reason

    def test_convexity_trigger_hold_within_band(self) -> None:
        """Test HOLD when crash convexity is within the target band."""
        trigger = roll_status._convexity_trigger_verdict(
            crash_convexity_pct=20.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        assert trigger.verdict == RollVerdict.HOLD
        assert "20.0%" in trigger.reason
        assert "15-25%" in trigger.reason

    def test_strike_drift_trigger_hold_when_no_entry_data(self) -> None:
        """Test HOLD when drift_pct is None (no entry data)."""
        trigger = roll_status._strike_drift_trigger_verdict(
            drift_pct=None,
            max_otm_drift_pct=45.0,
            review_fraction=0.75,
        )

        assert trigger.verdict == RollVerdict.HOLD
        assert trigger.reason == "no entry spot recorded"

    def test_strike_drift_trigger_roll_beyond_max(self) -> None:
        """Test ROLL when |drift_pct| exceeds the max threshold."""
        trigger = roll_status._strike_drift_trigger_verdict(
            drift_pct=-50.0,
            max_otm_drift_pct=45.0,
            review_fraction=0.75,
        )

        assert trigger.verdict == RollVerdict.ROLL
        assert "-50.0%" in trigger.reason
        assert "45%" in trigger.reason

    def test_strike_drift_trigger_review_within_buffer(self) -> None:
        """Test REVIEW when |drift_pct| is within the review fraction band."""
        trigger = roll_status._strike_drift_trigger_verdict(
            drift_pct=40.0,
            max_otm_drift_pct=45.0,
            review_fraction=0.75,
        )

        assert trigger.verdict == RollVerdict.REVIEW
        assert "+40.0%" in trigger.reason
        assert "45%" in trigger.reason

    def test_strike_drift_trigger_hold_within_band(self) -> None:
        """Test HOLD when |drift_pct| is comfortably within the band."""
        trigger = roll_status._strike_drift_trigger_verdict(
            drift_pct=5.0,
            max_otm_drift_pct=45.0,
            review_fraction=0.75,
        )

        assert trigger.verdict == RollVerdict.HOLD
        assert "+5.0%" in trigger.reason
        assert "45%" in trigger.reason


class TestEvaluateRollStatus:
    """Integration tests for evaluate_roll_status."""

    def _portfolio_with(self, position: OptionPosition) -> OptionPortfolio:
        portfolio = OptionPortfolio(spot_price=position.option.spot_price)
        portfolio.positions.append(position)
        return portfolio

    def _patch_convexity(
        self,
        monkeypatch: pytest.MonkeyPatch,
        value: float,
    ) -> None:
        def _fake_calculate_crash_convexity_pct(
            self,
            shock: CrashShock,
        ) -> float:
            return value

        monkeypatch.setattr(
            roll_status.PortfolioAnalyzer,
            "calculate_crash_convexity_pct",
            _fake_calculate_crash_convexity_pct,
        )

    def test_hold_when_nothing_triggers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test HOLD when time/convexity/drift are all comfortable."""
        self._patch_convexity(monkeypatch, 20.0)
        position = _make_position(
            days_to_maturity=200,
            entry_spot=100.0,
        )
        portfolio = self._portfolio_with(position)
        ips = _make_ips_config(target_min_pct=15.0, target_max_pct=25.0)

        records = evaluate_roll_status(portfolio, ips, current_spot=100.0)

        assert records[0].verdict == RollVerdict.HOLD
        assert records[0].estimated_roll_up_cost is None
        assert records[0].time_trigger.verdict == RollVerdict.HOLD
        assert records[0].convexity_trigger.verdict == RollVerdict.HOLD
        assert records[0].drift_trigger.verdict == RollVerdict.HOLD

    def test_roll_from_time_trigger_alone(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test ROLL driven purely by an imminent maturity."""
        self._patch_convexity(monkeypatch, 20.0)
        position = _make_position(days_to_maturity=10, entry_spot=100.0)
        portfolio = self._portfolio_with(position)
        ips = _make_ips_config(roll_time_months=1.0)  # ~30 day window

        records = evaluate_roll_status(portfolio, ips, current_spot=100.0)

        assert records[0].verdict == RollVerdict.ROLL
        assert records[0].estimated_roll_up_cost is not None

    def test_valuation_date_moves_roll_verdict(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A what-if valuation date, not the wall clock, drives the roll DTE."""
        self._patch_convexity(monkeypatch, 20.0)  # convexity comfortable
        position = _make_position(days_to_maturity=200, entry_spot=100.0)
        ips = _make_ips_config(roll_time_months=1.0)  # ~30-day roll window

        # As of today (~200 days out) -> HOLD.
        today_rec = evaluate_roll_status(
            self._portfolio_with(position),
            ips,
            current_spot=100.0,
        )[0]
        assert today_rec.verdict == RollVerdict.HOLD

        # Move the valuation date to 10 days before maturity -> ROLL.
        whatif = self._portfolio_with(position)
        whatif.valuation_date = position.option.maturity_date - timedelta(
            days=10,
        )
        whatif_rec = evaluate_roll_status(whatif, ips, current_spot=100.0)[0]
        assert whatif_rec.days_to_maturity == 10
        assert whatif_rec.verdict == RollVerdict.ROLL

    def test_roll_from_convexity_below_min_alone(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test ROLL driven purely by insufficient crash convexity."""
        self._patch_convexity(monkeypatch, 5.0)
        position = _make_position(days_to_maturity=200, entry_spot=100.0)
        portfolio = self._portfolio_with(position)
        ips = _make_ips_config(target_min_pct=15.0, target_max_pct=25.0)

        records = evaluate_roll_status(portfolio, ips, current_spot=100.0)

        assert records[0].verdict == RollVerdict.ROLL

    def test_monitor_from_convexity_above_max_alone(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test MONITOR driven purely by over-hedged crash convexity."""
        self._patch_convexity(monkeypatch, 40.0)
        position = _make_position(days_to_maturity=200, entry_spot=100.0)
        portfolio = self._portfolio_with(position)
        ips = _make_ips_config(target_min_pct=15.0, target_max_pct=25.0)

        records = evaluate_roll_status(portfolio, ips, current_spot=100.0)

        assert records[0].verdict == RollVerdict.MONITOR

    def test_roll_from_strike_drift_further_otm(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test ROLL when a put has drifted far further out of the money."""
        self._patch_convexity(monkeypatch, 20.0)
        # Entry at spot 100 (10% OTM); now spot has rallied to 140 (put is
        # far deeper OTM: (140-90)/140*100 ~= 35.7%, drift ~= +25.7%)
        position = _make_position(
            option_type=OptionType.PUT,
            strike_price=90.0,
            entry_spot=100.0,
            days_to_maturity=200,
        )
        portfolio = self._portfolio_with(position)
        ips = _make_ips_config(strike_drift_max_otm_pct=20.0)

        records = evaluate_roll_status(portfolio, ips, current_spot=140.0)

        assert records[0].moneyness.drift_pct is not None
        assert records[0].moneyness.drift_pct > 0
        assert records[0].verdict == RollVerdict.ROLL

    def test_downgrade_to_monitor_when_put_moves_nearer_money(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test the gamma/theta nuance downgrades ROLL to MONITOR.

        A put moving nearer the money (negative drift) with no time
        pressure and crash convexity still within target should be
        downgraded from ROLL (strike-drift-only trigger) to MONITOR.
        """
        self._patch_convexity(monkeypatch, 20.0)
        # Entry at spot 100 (10% OTM); spot drops to 95
        # (put nearer money: (95-90)/95*100 ~= 5.26%, drift ~= -4.74%)
        position = _make_position(
            option_type=OptionType.PUT,
            strike_price=90.0,
            entry_spot=100.0,
            days_to_maturity=200,
        )
        portfolio = self._portfolio_with(position)
        # Small max drift so the modest -4.74% drift still exceeds it.
        ips = _make_ips_config(
            roll_time_months=1.0,
            strike_drift_max_otm_pct=3.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        records = evaluate_roll_status(portfolio, ips, current_spot=95.0)

        assert records[0].moneyness.drift_pct is not None
        assert records[0].moneyness.drift_pct < 0
        assert records[0].verdict == RollVerdict.MONITOR
        # The suppression overrides the record's verdict, but the raw
        # sub-verdicts still reflect what each trigger actually saw.
        assert records[0].drift_trigger.verdict == RollVerdict.ROLL
        assert records[0].time_trigger.verdict == RollVerdict.HOLD
        assert records[0].convexity_trigger.verdict == RollVerdict.HOLD

    def test_no_downgrade_for_call_option(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test the nuance downgrade does not apply to CALL positions."""
        self._patch_convexity(monkeypatch, 20.0)
        # Mirror the downgrade scenario but with a CALL: entry at spot 100
        # (10% OTM, strike 110); spot rises to 105 (call nearer money:
        # (110-105)/105*100 ~= 4.76%, drift ~= -5.24%)
        position = _make_position(
            option_type=OptionType.CALL,
            strike_price=110.0,
            entry_spot=100.0,
            days_to_maturity=200,
        )
        portfolio = self._portfolio_with(position)
        ips = _make_ips_config(
            roll_time_months=1.0,
            strike_drift_max_otm_pct=3.0,
            target_min_pct=15.0,
            target_max_pct=25.0,
        )

        records = evaluate_roll_status(portfolio, ips, current_spot=105.0)

        assert records[0].moneyness.drift_pct is not None
        assert records[0].moneyness.drift_pct < 0
        assert records[0].verdict == RollVerdict.ROLL

    def test_no_entry_data_does_not_crash_and_skips_drift_trigger(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test a position with entry_spot=None evaluates without error."""
        self._patch_convexity(monkeypatch, 20.0)
        position = _make_position(entry_spot=None, days_to_maturity=200)
        portfolio = self._portfolio_with(position)
        ips = _make_ips_config()

        records = evaluate_roll_status(portfolio, ips, current_spot=100.0)

        assert records[0].moneyness.entry_otm_pct is None
        assert records[0].verdict == RollVerdict.HOLD
        assert records[0].estimated_roll_up_cost is None
