"""Tests for deltadewa.analysis.hedge_triggers."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from deltadewa.analysis.hedge_triggers import (
    HedgeTriggerThresholds,
    evaluate_hedge_triggers,
)
from deltadewa.constants import DAYS_PER_YEAR, ExerciseStyle, OptionType
from deltadewa.ips_config import IpsTriggers, load_ips_config
from deltadewa.portfolio.core import OptionPortfolio

EXAMPLE_IPS_YAML = Path(__file__).parent.parent.parent / "config" / "ips.yaml"


def _mock_portfolio(
    net_delta: float,
    underlying_qty: float,
    total_theta: float = 0.0,
    total_gamma: float = 0.0,
) -> Mock:
    """Positionless portfolio mock: crafted net_delta / equity / theta / gamma.

    With ``spot_price == underlying_qty == 100`` the gamma-drift metric
    (``|gamma| * spot / |underlying_qty|``) equals ``total_gamma``, so the
    crafted gamma is also the drift percent.
    """
    portfolio = Mock()
    portfolio.positions = []
    portfolio.spot_price = 100.0
    portfolio.summary_stats.return_value = {
        "net_delta": net_delta,
        "underlying_quantity": underlying_qty,
        "total_theta": total_theta,
        "total_gamma": total_gamma,
    }
    return portfolio


def _reporter_text(reporter: Mock) -> str:
    """Join the text of every success/warning/error call on a Mock reporter."""
    lines = [
        str(call.args[0])
        for method in ("success", "warning", "error")
        for call in getattr(reporter, method).call_args_list
        if call.args
    ]
    return " ".join(lines)


def _action_text(result_actions: list[tuple[str, str]]) -> str:
    """Join all action descriptions for substring assertions."""
    return " ".join(desc for _, desc in result_actions)


_ASOF_MATURITY = datetime(2027, 1, 1, tzinfo=UTC)


def _asof_portfolio(days_before_maturity: int) -> OptionPortfolio:
    """Single-put portfolio whose valuation date is N days before maturity."""
    portfolio = OptionPortfolio(
        underlying_quantity=100.0,
        spot_price=100.0,
        volatility=0.2,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.add_position(
        strike_price=90.0,
        maturity_date=_ASOF_MATURITY,
        quantity=1,
        option_type=OptionType.PUT,
    )
    portfolio.valuation_date = _ASOF_MATURITY - timedelta(
        days=days_before_maturity,
    )
    return portfolio


class TestValuationDateDrivesExpiry:
    """Expiry/DTE triggers move with the portfolio's what-if valuation date."""

    _MATURITY = datetime(2027, 1, 1, tzinfo=UTC)

    def _portfolio_asof(self, days_before_maturity: int) -> OptionPortfolio:
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.2,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.add_position(
            strike_price=90.0,
            maturity_date=self._MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
        )
        # A what-if valuation date, not the wall clock, sets the DTE.
        portfolio.valuation_date = self._MATURITY - timedelta(
            days=days_before_maturity,
        )
        return portfolio

    def test_far_valuation_date_is_not_urgent(self) -> None:
        """100 days out -> nearest expiry 100 days, nothing near-expiry."""
        result = evaluate_hedge_triggers(self._portfolio_asof(100), Mock())
        assert result.days_to_nearest_expiry == 100
        assert result.near_expiry_count == 0

    def test_soon_window_exercises_the_dataframe_dte_path(self) -> None:
        """15 days out (soon-but-not-urgent) uses the valuation-date DTE."""
        result = evaluate_hedge_triggers(self._portfolio_asof(15), Mock())
        assert result.days_to_nearest_expiry == 15
        assert result.near_expiry_count == 0

    def test_near_valuation_date_is_urgent(self) -> None:
        """5 days out (< 7-day urgent window) counts as near-expiry."""
        result = evaluate_hedge_triggers(self._portfolio_asof(5), Mock())
        assert result.days_to_nearest_expiry == 5
        assert result.near_expiry_count == 1


class TestHedgeTriggerThresholdsFromIpsConfig:
    """Tests for HedgeTriggerThresholds.from_ips."""

    def test_maps_shared_fields(self) -> None:
        """Test that fields present in IpsConfig are mapped across."""
        ips = load_ips_config(EXAMPLE_IPS_YAML)

        thresholds = HedgeTriggerThresholds.from_ips(ips.triggers)

        assert (
            thresholds.target_delta_ratio_pct
            == ips.triggers.target_delta_ratio_pct
        )
        assert (
            thresholds.delta_drift_warn_pct == ips.triggers.delta_drift_warn_pct
        )
        assert (
            thresholds.delta_drift_action_pct
            == ips.triggers.delta_drift_action_pct
        )
        assert (
            thresholds.theta_cost_acceptable_pct
            == ips.triggers.theta_cost_acceptable_pct
        )
        assert thresholds.expiry_urgent_days == ips.triggers.expiry_urgent_days
        assert thresholds.expiry_soon_days == ips.triggers.expiry_soon_days
        assert (
            thresholds.theta_cost_excellent_pct
            == ips.triggers.theta_cost_excellent_pct
        )

    def test_maps_gamma_drift_bands(self) -> None:
        """The gamma-drift bands are mapped too — nothing stays unmapped now."""
        ips = load_ips_config(EXAMPLE_IPS_YAML)

        thresholds = HedgeTriggerThresholds.from_ips(ips.triggers)

        assert (
            thresholds.gamma_drift_moderate_pct
            == ips.triggers.gamma_drift_moderate_pct
        )
        assert (
            thresholds.gamma_drift_high_pct == ips.triggers.gamma_drift_high_pct
        )

    def test_from_ips_maps_triggers_section_directly(self) -> None:
        """Test from_ips accepts an IpsTriggers section directly."""
        ips = load_ips_config(EXAMPLE_IPS_YAML)

        thresholds = HedgeTriggerThresholds.from_ips(ips.triggers)

        assert (
            thresholds.delta_drift_warn_pct == ips.triggers.delta_drift_warn_pct
        )
        assert (
            thresholds.delta_drift_action_pct
            == ips.triggers.delta_drift_action_pct
        )
        assert (
            thresholds.theta_cost_acceptable_pct
            == ips.triggers.theta_cost_acceptable_pct
        )


class TestIpsThresholdsMoveTriggers:
    """Each newly-mapped IPS threshold changes the trigger it drives."""

    def test_from_ips_maps_all_non_gamma_thresholds(self) -> None:
        """Distinct IPS values (not the dataclass defaults) are mapped."""
        triggers = IpsTriggers(
            delta_drift_warn_pct=5.0,
            delta_drift_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_time_months=9.0,
            rally_rebalance_pct=15.0,
            strike_drift_max_otm_pct=45.0,
            expiry_urgent_days=9,
            expiry_soon_days=40,
            theta_cost_excellent_pct=0.5,
        )

        thresholds = HedgeTriggerThresholds.from_ips(triggers)

        assert thresholds.expiry_urgent_days == 9
        assert thresholds.expiry_soon_days == 40
        assert thresholds.theta_cost_excellent_pct == pytest.approx(
            0.5, rel=1e-4
        )

    def test_expiry_soon_days_moves_the_soon_action(self) -> None:
        """A wider soon window turns a 25-DTE book into a SOON action."""
        portfolio = _asof_portfolio(days_before_maturity=25)

        narrow = evaluate_hedge_triggers(
            portfolio,
            Mock(),
            HedgeTriggerThresholds(expiry_soon_days=21),
        )
        wide = evaluate_hedge_triggers(
            portfolio,
            Mock(),
            HedgeTriggerThresholds(expiry_soon_days=30),
        )

        # The expiry-specific SOON action (distinct from a delta-drift one).
        assert "approaching expiration" not in _action_text(narrow.actions)
        assert "approaching expiration" in _action_text(wide.actions)

    def test_expiry_urgent_days_moves_the_urgent_count(self) -> None:
        """The urgent window decides whether a 5-DTE leg is near-expiry."""
        portfolio = _asof_portfolio(days_before_maturity=5)

        narrow = evaluate_hedge_triggers(
            portfolio,
            Mock(),
            HedgeTriggerThresholds(expiry_urgent_days=3),
        )
        wide = evaluate_hedge_triggers(
            portfolio,
            Mock(),
            HedgeTriggerThresholds(expiry_urgent_days=7),
        )

        assert narrow.near_expiry_count == 0  # 5 is not < 3
        assert wide.near_expiry_count == 1  # 5 < 7

    def test_theta_cost_excellent_pct_moves_the_label(self) -> None:
        """The EXCELLENT cutoff decides the theta label for a 1.5% cost book."""
        # annual theta 150 on 10,000 notional -> theta_cost_pct == 1.5%.
        portfolio = _mock_portfolio(
            net_delta=90.0,
            underlying_qty=100.0,
            total_theta=-150.0 / DAYS_PER_YEAR,
        )

        below = Mock()
        evaluate_hedge_triggers(
            portfolio,
            below,
            HedgeTriggerThresholds(theta_cost_excellent_pct=1.0),
        )
        above = Mock()
        evaluate_hedge_triggers(
            portfolio,
            above,
            HedgeTriggerThresholds(theta_cost_excellent_pct=1.8),
        )

        # 1.5% > 1.0 cutoff -> ACCEPTABLE; 1.5% < 1.8 cutoff -> EXCELLENT.
        assert "ACCEPTABLE" in _reporter_text(below)
        assert "EXCELLENT" not in _reporter_text(below)
        assert "EXCELLENT" in _reporter_text(above)


class TestGammaDriftTrigger:
    """The gamma trigger fires on book-size-independent gamma drift."""

    @staticmethod
    def _gamma_action_present(result: object) -> bool:
        return any(
            "gamma drift" in desc.lower()
            for _, desc in result.actions  # type: ignore[attr-defined]
        )

    def test_low_gamma_drift_is_low_risk(self) -> None:
        """1% drift (< 2% moderate) reads LOW and emits no gamma action."""
        portfolio = _mock_portfolio(
            net_delta=90.0,
            underlying_qty=100.0,
            total_gamma=1.0,
        )
        reporter = Mock()

        result = evaluate_hedge_triggers(portfolio, reporter)

        assert result.gamma_drift_pct == pytest.approx(
            1.0, rel=1e-4
        )  # 1.0 * 100 / 100
        assert "LOW RISK" in _reporter_text(reporter)
        assert not self._gamma_action_present(result)

    def test_high_gamma_drift_fires(self) -> None:
        """6% drift (> 5% high) reads HIGH RISK and emits a MONITOR action.

        Raw gamma of 6 would sit far below the old inert 10/30 bands and never
        fire; normalized drift catches it.
        """
        portfolio = _mock_portfolio(
            net_delta=90.0,
            underlying_qty=100.0,
            total_gamma=6.0,
        )
        reporter = Mock()

        result = evaluate_hedge_triggers(portfolio, reporter)

        assert result.gamma_drift_pct == pytest.approx(6.0, rel=1e-4)
        assert "HIGH RISK" in _reporter_text(reporter)
        assert self._gamma_action_present(result)

    def test_bands_move_the_classification(self) -> None:
        """Gamma-drift bands move a 3% book between MODERATE and HIGH."""
        portfolio = _mock_portfolio(
            net_delta=90.0,
            underlying_qty=100.0,
            total_gamma=3.0,
        )

        wide = Mock()
        evaluate_hedge_triggers(
            portfolio,
            wide,
            HedgeTriggerThresholds(
                gamma_drift_moderate_pct=2.0,
                gamma_drift_high_pct=5.0,
            ),
        )
        narrow = Mock()
        evaluate_hedge_triggers(
            portfolio,
            narrow,
            HedgeTriggerThresholds(
                gamma_drift_moderate_pct=1.0,
                gamma_drift_high_pct=2.5,
            ),
        )

        assert "MODERATE" in _reporter_text(wide)
        assert "HIGH RISK" in _reporter_text(narrow)

    def test_unavailable_without_underlying(self) -> None:
        """No equity position -> gamma drift is None and reads unavailable."""
        portfolio = _mock_portfolio(
            net_delta=0.0,
            underlying_qty=0.0,
            total_gamma=6.0,
        )
        reporter = Mock()

        result = evaluate_hedge_triggers(portfolio, reporter)

        assert result.gamma_drift_pct is None
        assert "Gamma drift: unavailable" in _reporter_text(reporter)


class TestThetaUnavailableWithoutUnderlying:
    """Theta cost reports unavailable (None) when the underlying is unset."""

    def test_theta_cost_none_and_unavailable(self) -> None:
        """No equity position -> theta_cost_pct None, no fabricated 0."""
        portfolio = _mock_portfolio(
            net_delta=0.0,
            underlying_qty=0.0,
            total_theta=-100.0,
        )
        reporter = Mock()

        result = evaluate_hedge_triggers(portfolio, reporter)

        assert result.theta_cost_pct is None
        assert "Theta cost: unavailable" in _reporter_text(reporter)
        # No theta REVIEW action is emitted on an unavailable cost.
        assert "Hedge cost is high" not in _action_text(result.actions)


class TestEvaluateDeltaDriftTrigger:
    """Delta-drift banding, unavailability, and messaging (M1)."""

    def _thresholds(self, target: float = 90.0) -> HedgeTriggerThresholds:
        return HedgeTriggerThresholds(
            target_delta_ratio_pct=target,
            delta_drift_warn_pct=5.0,
            delta_drift_action_pct=10.0,
        )

    def test_at_target_holds(self) -> None:
        """A book at target reads 0.0 drift and triggers no delta action."""
        result = evaluate_hedge_triggers(
            _mock_portfolio(net_delta=90.0, underlying_qty=100.0),
            Mock(),
            self._thresholds(),
        )

        assert result.delta_drift_pct == pytest.approx(0.0, abs=1e-9)
        assert "delta" not in _action_text(result.actions).lower()

    def test_within_warn_holds(self) -> None:
        """Drift below the warn band raises no delta action."""
        result = evaluate_hedge_triggers(
            _mock_portfolio(net_delta=93.0, underlying_qty=100.0),
            Mock(),
            self._thresholds(),
        )

        assert result.delta_drift_pct == pytest.approx(3.0, rel=1e-4)
        assert "delta" not in _action_text(result.actions).lower()

    def test_monitor_band_raises_soon(self) -> None:
        """Drift in (warn, action] raises a SOON monitor action."""
        result = evaluate_hedge_triggers(
            _mock_portfolio(net_delta=97.0, underlying_qty=100.0),
            Mock(),
            self._thresholds(),
        )

        assert result.delta_drift_pct == pytest.approx(7.0, rel=1e-4)
        text = _action_text(result.actions)
        assert "Monitor delta drift" in text
        assert "🟡 SOON" in {label for label, _ in result.actions}

    def test_action_band_raises_urgent_with_target_relative_shares(
        self,
    ) -> None:
        """Drift beyond the action band raises an URGENT rebalance action.

        The share count restores the target ratio (target_net_delta - net_delta
        = 90 - 105 = -15), not full neutrality, and cites no "Section 7".
        """
        result = evaluate_hedge_triggers(
            _mock_portfolio(net_delta=105.0, underlying_qty=100.0),
            Mock(),
            self._thresholds(),
        )

        assert result.delta_drift_pct == pytest.approx(15.0, rel=1e-4)
        text = _action_text(result.actions)
        assert "🔴 URGENT" in {label for label, _ in result.actions}
        assert "Rebalance delta (adjust 15 shares)" in text
        assert "target ratio" in text
        assert "Section 7" not in text

    def test_over_hedged_bands_on_magnitude(self) -> None:
        """Negative drift beyond the action band still fires (abs banding)."""
        result = evaluate_hedge_triggers(
            _mock_portfolio(net_delta=78.0, underlying_qty=100.0),
            Mock(),
            self._thresholds(),
        )

        assert result.delta_drift_pct == pytest.approx(-12.0, rel=1e-4)
        assert "🔴 URGENT" in {label for label, _ in result.actions}

    def test_unset_underlying_is_unavailable(self) -> None:
        """No equity position -> None drift, no verdict, no delta action."""
        reporter = Mock()
        result = evaluate_hedge_triggers(
            _mock_portfolio(net_delta=0.0, underlying_qty=0.0),
            reporter,
            self._thresholds(),
        )

        assert result.delta_drift_pct is None
        assert "delta" not in _action_text(result.actions).lower()
        warned = " ".join(
            str(call.args[0]) for call in reporter.warning.call_args_list
        )
        assert "unavailable" in warned

    def test_target_change_moves_verdict(self) -> None:
        """The same book flips MONITOR->ACTION as the target tightens."""
        monitor = evaluate_hedge_triggers(
            _mock_portfolio(net_delta=97.0, underlying_qty=100.0),
            Mock(),
            self._thresholds(target=90.0),
        )
        action = evaluate_hedge_triggers(
            _mock_portfolio(net_delta=97.0, underlying_qty=100.0),
            Mock(),
            self._thresholds(target=85.0),
        )

        assert monitor.delta_drift_pct == 7.0
        assert "🟡 SOON" in {label for label, _ in monitor.actions}
        assert action.delta_drift_pct == pytest.approx(12.0, rel=1e-4)
        assert "🔴 URGENT" in {label for label, _ in action.actions}
