"""Tests for deltadewa.analysis.hedge_triggers."""

from pathlib import Path

from deltadewa.analysis.hedge_triggers import HedgeTriggerThresholds
from deltadewa.ips_config import load_ips_config

# ruff: noqa: S101

EXAMPLE_IPS_YAML = Path(__file__).parent.parent.parent / "examples" / "ips.yaml"


class TestHedgeTriggerThresholdsFromIpsConfig:
    """Tests for HedgeTriggerThresholds.from_ips."""

    def test_maps_shared_fields(self) -> None:
        """Test that fields present in IpsConfig are mapped across."""
        ips = load_ips_config(EXAMPLE_IPS_YAML)

        thresholds = HedgeTriggerThresholds.from_ips(ips)

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

        thresholds = HedgeTriggerThresholds.from_ips(ips)

        assert thresholds.expiry_urgent_days == defaults.expiry_urgent_days
        assert thresholds.expiry_soon_days == defaults.expiry_soon_days
        assert (
            thresholds.theta_cost_excellent_pct
            == defaults.theta_cost_excellent_pct
        )
        assert thresholds.gamma_low == defaults.gamma_low
        assert thresholds.gamma_moderate == defaults.gamma_moderate
