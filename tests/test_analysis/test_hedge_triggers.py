"""Tests for deltadewa.analysis.hedge_triggers."""

from pathlib import Path
from unittest.mock import Mock

from deltadewa.analysis.hedge_triggers import (
    HedgeTriggerThresholds,
    evaluate_hedge_triggers,
)
from deltadewa.ips_config import load_ips_config

EXAMPLE_IPS_YAML = Path(__file__).parent.parent.parent / "config" / "ips.yaml"


def _mock_portfolio(net_delta: float, underlying_qty: float) -> Mock:
    """Positionless portfolio mock with a crafted net_delta / equity."""
    portfolio = Mock()
    portfolio.positions = []
    portfolio.spot_price = 100.0
    portfolio.summary_stats.return_value = {
        "net_delta": net_delta,
        "underlying_quantity": underlying_qty,
        "total_theta": 0.0,
        "total_gamma": 0.0,
    }
    return portfolio


def _action_text(result_actions: list[tuple[str, str]]) -> str:
    """Join all action descriptions for substring assertions."""
    return " ".join(desc for _, desc in result_actions)


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

    def test_leaves_unmapped_fields_at_dataclass_defaults(self) -> None:
        """Test that fields not in the IPS schema keep their defaults."""
        ips = load_ips_config(EXAMPLE_IPS_YAML)
        defaults = HedgeTriggerThresholds()

        thresholds = HedgeTriggerThresholds.from_ips(ips.triggers)

        assert thresholds.expiry_urgent_days == defaults.expiry_urgent_days
        assert thresholds.expiry_soon_days == defaults.expiry_soon_days
        assert (
            thresholds.theta_cost_excellent_pct
            == defaults.theta_cost_excellent_pct
        )
        assert thresholds.gamma_low == defaults.gamma_low
        assert thresholds.gamma_moderate == defaults.gamma_moderate

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

        assert result.delta_drift_pct == 0.0
        assert "delta" not in _action_text(result.actions).lower()

    def test_within_warn_holds(self) -> None:
        """Drift below the warn band raises no delta action."""
        result = evaluate_hedge_triggers(
            _mock_portfolio(net_delta=93.0, underlying_qty=100.0),
            Mock(),
            self._thresholds(),
        )

        assert result.delta_drift_pct == 3.0
        assert "delta" not in _action_text(result.actions).lower()

    def test_monitor_band_raises_soon(self) -> None:
        """Drift in (warn, action] raises a SOON monitor action."""
        result = evaluate_hedge_triggers(
            _mock_portfolio(net_delta=97.0, underlying_qty=100.0),
            Mock(),
            self._thresholds(),
        )

        assert result.delta_drift_pct == 7.0
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

        assert result.delta_drift_pct == 15.0
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

        assert result.delta_drift_pct == -12.0
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
        assert action.delta_drift_pct == 12.0
        assert "🔴 URGENT" in {label for label, _ in action.actions}
