"""Tests for deltadewa.ips_config."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from deltadewa.constants import ExerciseStyle
from deltadewa.ips_config import IpsConfigError, load_ips_config

EXAMPLE_IPS_YAML = Path(__file__).parent.parent / "config" / "ips.yaml"

_VALID_CONFIG: dict[str, Any] = {
    "program": {"name": "SPX tail hedge", "instrument": "SPX"},
    "pricing": {"exercise_style": "EUROPEAN", "american_use_closed_form": True},
    "budget": {"annual_carry_pct": 2.0},
    "convexity": {
        "crash_scenario_pct": -25.0,
        "target_min_pct": 15.0,
        "target_max_pct": 25.0,
    },
    "drawdown": {"max_tolerance_pct": 20.0},
    "triggers": {
        "delta_drift_warn_pct": 5.0,
        "delta_drift_action_pct": 10.0,
        "theta_cost_acceptable_pct": 2.0,
        "roll_time_months": 9.0,
        "rally_rebalance_pct": 15.0,
        "strike_drift_max_otm_pct": 45.0,
    },
    "monetization": {
        "schedule": [
            {"gain_pct": 100, "sell_pct": 25},
            {"gain_pct": 200, "sell_pct": 25},
        ],
    },
}


def _write_yaml(
    tmp_path: Path,
    config: dict,
    filename: str = "ips.yaml",
) -> Path:
    path = tmp_path / filename
    path.write_text(yaml.safe_dump(config))
    return path


class TestLoadIpsConfig:
    """Tests for load_ips_config."""

    def test_loads_example_ips_yaml(self) -> None:
        """Test that the shipped config/ips.yaml loads successfully."""
        ips = load_ips_config(EXAMPLE_IPS_YAML)

        assert ips.program.instrument == "SPX"
        assert ips.pricing.exercise_style == ExerciseStyle.EUROPEAN
        assert ips.budget.annual_carry_pct == 2.0
        assert ips.convexity.target_min_pct == 15.0
        assert ips.convexity.target_max_pct == 25.0
        assert ips.convexity.crash_vol_shock == 0.15
        assert ips.convexity.crash_floor_reported is True
        assert ips.drawdown.max_tolerance_pct == 20.0
        assert ips.triggers.delta_drift_warn_pct == 5.0
        assert len(ips.monetization.schedule) == 3
        assert ips.monetization.schedule[0].gain_pct == 100

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        """Test that a missing file raises IpsConfigError."""
        with pytest.raises(IpsConfigError, match="not found"):
            load_ips_config(tmp_path / "does_not_exist.yaml")

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        """Test that malformed YAML raises IpsConfigError."""
        path = tmp_path / "bad.yaml"
        path.write_text("program: [unterminated")

        with pytest.raises(IpsConfigError, match="Invalid YAML"):
            load_ips_config(path)

    def test_missing_section_raises(self, tmp_path: Path) -> None:
        """Test that a missing top-level section raises IpsConfigError."""
        config = {k: v for k, v in _VALID_CONFIG.items() if k != "budget"}
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="'budget'"):
            load_ips_config(path)

    def test_invalid_exercise_style_raises(self, tmp_path: Path) -> None:
        """Test that an unrecognized exercise_style raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "pricing": {"exercise_style": "BERMUDAN"},
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="exercise_style"):
            load_ips_config(path)

    def test_delta_drift_ordering_validated(self, tmp_path: Path) -> None:
        """Test that warn_pct >= action_pct raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "delta_drift_warn_pct": 10.0,
                "delta_drift_action_pct": 5.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="delta_drift_warn_pct"):
            load_ips_config(path)

    def test_convexity_min_max_ordering_validated(self, tmp_path: Path) -> None:
        """Test that target_min_pct > target_max_pct raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 30.0,
                "target_max_pct": 25.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="target_min_pct"):
            load_ips_config(path)

    def test_crash_scenario_pct_must_be_negative(self, tmp_path: Path) -> None:
        """Test that a non-negative crash_scenario_pct raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": 25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="crash_scenario_pct"):
            load_ips_config(path)

    def test_crash_knobs_default_when_omitted(self, tmp_path: Path) -> None:
        """Omitted crash_vol_shock / crash_floor_reported fall back."""
        # _VALID_CONFIG's convexity section carries no crash knobs.
        path = _write_yaml(tmp_path, _VALID_CONFIG)

        ips = load_ips_config(path)

        assert ips.convexity.crash_vol_shock == 0.15
        assert ips.convexity.crash_floor_reported is True

    def test_crash_knobs_round_trip_when_set(self, tmp_path: Path) -> None:
        """Explicit crash_vol_shock / crash_floor_reported are honoured."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
                "crash_vol_shock": 0.20,
                "crash_floor_reported": False,
            },
        }
        path = _write_yaml(tmp_path, config)

        ips = load_ips_config(path)

        assert ips.convexity.crash_vol_shock == 0.20
        assert ips.convexity.crash_floor_reported is False

    def test_negative_crash_vol_shock_raises(self, tmp_path: Path) -> None:
        """A negative crash_vol_shock raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
                "crash_vol_shock": -0.05,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="crash_vol_shock"):
            load_ips_config(path)

    def test_negative_budget_raises(self, tmp_path: Path) -> None:
        """Test that a negative annual_carry_pct raises IpsConfigError."""
        config = {**_VALID_CONFIG, "budget": {"annual_carry_pct": -1.0}}
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="annual_carry_pct"):
            load_ips_config(path)

    def test_monetization_schedule_over_100_percent_raises(
        self,
        tmp_path: Path,
    ) -> None:
        """Test that a schedule selling more than 100% raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "monetization": {
                "schedule": [
                    {"gain_pct": 100, "sell_pct": 60},
                    {"gain_pct": 200, "sell_pct": 60},
                ],
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="sell_pct"):
            load_ips_config(path)

    def test_review_buffers_default_when_omitted(self, tmp_path: Path) -> None:
        """Test that omitted REVIEW buffer fields fall back to defaults."""
        path = _write_yaml(tmp_path, _VALID_CONFIG)

        ips = load_ips_config(path)

        assert ips.triggers.roll_review_buffer == 1.5
        assert ips.triggers.strike_drift_review_fraction == 0.75

    def test_review_buffers_round_trip_when_set(self, tmp_path: Path) -> None:
        """Test that explicit REVIEW buffer values are loaded as given."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "roll_review_buffer": 2.0,
                "strike_drift_review_fraction": 0.5,
            },
        }
        path = _write_yaml(tmp_path, config)

        ips = load_ips_config(path)

        assert ips.triggers.roll_review_buffer == 2.0
        assert ips.triggers.strike_drift_review_fraction == 0.5

    def test_roll_review_buffer_must_exceed_one(self, tmp_path: Path) -> None:
        """Test that roll_review_buffer <= 1.0 raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "roll_review_buffer": 1.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="roll_review_buffer"):
            load_ips_config(path)

    def test_strike_drift_review_fraction_must_be_in_unit_interval(
        self,
        tmp_path: Path,
    ) -> None:
        """Test that strike_drift_review_fraction outside (0, 1) raises."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "strike_drift_review_fraction": 1.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(
            IpsConfigError,
            match="strike_drift_review_fraction",
        ):
            load_ips_config(path)
