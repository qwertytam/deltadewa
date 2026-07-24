"""Tests for deltadewa.ips_config."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from deltadewa.constants import ExerciseStyle
from deltadewa.ips_config import (
    DEFAULT_SKEW_HIGH_PCTILE,
    DEFAULT_SKEW_LOW_PCTILE,
    DEFAULT_TERM_CONTANGO_TOLERANCE,
    DEFAULT_VOL_REGIME_HIGH,
    DEFAULT_VOL_REGIME_LOW,
    IpsConfigError,
    load_ips_config,
)

EXAMPLE_IPS_YAML = Path(__file__).parent.parent / "config" / "ips.yaml"

_VALID_CONFIG: dict[str, Any] = {
    "program": {"name": "SPX tail hedge", "instrument": "SPX"},
    "pricing": {"exercise_style": "EUROPEAN"},
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
        # Handbook family-office carry ceiling is 1% (Mi6); shipped default.
        assert ips.budget.annual_carry_pct == 1.0
        assert ips.convexity.target_min_pct == 15.0
        assert ips.convexity.target_max_pct == 25.0
        assert ips.convexity.crash_vol_shock == 0.15
        # M1.6: the shipped default adopts the skew-calibrated crash shock.
        assert ips.convexity.skew_steepening == 0.10
        # M1.7: the steepening is anchored to each leg's ~10-delta wing.
        assert ips.convexity.skew_reference_delta == 0.10
        assert ips.convexity.crash_floor_reported is True
        assert ips.drawdown.max_tolerance_pct == 20.0
        assert ips.triggers.target_delta_ratio_pct == 90.0
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
        assert ips.convexity.skew_steepening == 0.0
        assert ips.convexity.skew_reference_delta == 0.10
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
                "skew_steepening": 0.30,
                "skew_reference_delta": 0.15,
                "crash_floor_reported": False,
            },
        }
        path = _write_yaml(tmp_path, config)

        ips = load_ips_config(path)

        assert ips.convexity.crash_vol_shock == 0.20
        assert ips.convexity.skew_steepening == 0.30
        assert ips.convexity.skew_reference_delta == 0.15
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

    def test_negative_skew_steepening_raises(self, tmp_path: Path) -> None:
        """A negative skew_steepening raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
                "skew_steepening": -0.05,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="skew_steepening"):
            load_ips_config(path)

    @pytest.mark.parametrize("bad_delta", [0.0, -0.05, 0.5, 0.75])
    def test_skew_reference_delta_out_of_range_raises(
        self,
        tmp_path: Path,
        bad_delta: float,
    ) -> None:
        """A skew_reference_delta outside (0, 0.5) raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
                "skew_reference_delta": bad_delta,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="skew_reference_delta"):
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

    def test_target_delta_ratio_default_when_omitted(
        self,
        tmp_path: Path,
    ) -> None:
        """Omitted target_delta_ratio_pct falls back to 90.0."""
        # _VALID_CONFIG's triggers section carries no target_delta_ratio_pct.
        path = _write_yaml(tmp_path, _VALID_CONFIG)

        ips = load_ips_config(path)

        assert ips.triggers.target_delta_ratio_pct == 90.0

    def test_target_delta_ratio_round_trip_when_set(
        self,
        tmp_path: Path,
    ) -> None:
        """An explicit target_delta_ratio_pct is loaded as given."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "target_delta_ratio_pct": 80.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        ips = load_ips_config(path)

        assert ips.triggers.target_delta_ratio_pct == 80.0

    def test_negative_target_delta_ratio_raises(
        self,
        tmp_path: Path,
    ) -> None:
        """A negative target_delta_ratio_pct raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "target_delta_ratio_pct": -10.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="target_delta_ratio_pct"):
            load_ips_config(path)


class TestMarketEnvironment:
    """Tests for the ``market_environment`` policy section (Mo2)."""

    def test_defaults_when_section_absent(self, tmp_path: Path) -> None:
        """A config without the section uses the DEFAULT_* single source."""
        path = _write_yaml(tmp_path, _VALID_CONFIG)  # no market_environment
        env = load_ips_config(path).market_environment

        assert env.vol_regime_low == DEFAULT_VOL_REGIME_LOW
        assert env.vol_regime_high == DEFAULT_VOL_REGIME_HIGH
        assert env.skew_low_pctile == DEFAULT_SKEW_LOW_PCTILE
        assert env.skew_high_pctile == DEFAULT_SKEW_HIGH_PCTILE
        assert env.term_contango_tolerance == DEFAULT_TERM_CONTANGO_TOLERANCE

    def test_example_ips_yaml_market_environment(self) -> None:
        """The shipped config/ips.yaml carries the policy bands."""
        env = load_ips_config(EXAMPLE_IPS_YAML).market_environment

        assert env.vol_regime_low == 0.15
        assert env.vol_regime_high == 0.35
        assert env.skew_low_pctile == 25
        assert env.skew_high_pctile == 75
        assert env.term_contango_tolerance == 0.5

    def test_round_trips_custom_values(self, tmp_path: Path) -> None:
        """Section values round-trip through the loader unchanged."""
        config = {
            **_VALID_CONFIG,
            "market_environment": {
                "vol_regime_low": 0.12,
                "vol_regime_high": 0.40,
                "skew_low_pctile": 20,
                "skew_high_pctile": 80,
                "term_contango_tolerance": 1.0,
            },
        }
        env = load_ips_config(_write_yaml(tmp_path, config)).market_environment

        assert env.vol_regime_low == 0.12
        assert env.vol_regime_high == 0.40
        assert env.skew_low_pctile == 20
        assert env.skew_high_pctile == 80
        assert env.term_contango_tolerance == 1.0

    def test_vol_low_not_below_high_raises(self, tmp_path: Path) -> None:
        """vol_regime_low >= vol_regime_high raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "market_environment": {
                "vol_regime_low": 0.40,
                "vol_regime_high": 0.35,
            },
        }
        with pytest.raises(IpsConfigError, match="vol_regime_low"):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_skew_low_not_below_high_raises(self, tmp_path: Path) -> None:
        """skew_low_pctile >= skew_high_pctile raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "market_environment": {
                "skew_low_pctile": 75,
                "skew_high_pctile": 25,
            },
        }
        with pytest.raises(IpsConfigError, match="skew"):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_skew_out_of_percentile_range_raises(
        self,
        tmp_path: Path,
    ) -> None:
        """A skew percentile above 100 raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "market_environment": {
                "skew_low_pctile": 25,
                "skew_high_pctile": 120,
            },
        }
        with pytest.raises(IpsConfigError, match="skew"):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_negative_term_tolerance_raises(self, tmp_path: Path) -> None:
        """A negative term_contango_tolerance raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "market_environment": {"term_contango_tolerance": -0.5},
        }
        with pytest.raises(IpsConfigError, match="term_contango_tolerance"):
            load_ips_config(_write_yaml(tmp_path, config))


class TestExpiryThetaTriggers:
    """Tests for the expiry / theta-excellent trigger thresholds (Mo3)."""

    def test_defaults_when_absent(self, tmp_path: Path) -> None:
        """A triggers section without the new keys uses the defaults."""
        # _VALID_CONFIG's triggers omit the new keys.
        ips = load_ips_config(_write_yaml(tmp_path, _VALID_CONFIG))
        triggers = ips.triggers

        assert triggers.expiry_urgent_days == 7
        assert triggers.expiry_soon_days == 21
        assert triggers.theta_cost_excellent_pct == 1.0

    def test_example_ips_yaml_expiry_theta(self) -> None:
        """The shipped config/ips.yaml carries the new trigger keys."""
        triggers = load_ips_config(EXAMPLE_IPS_YAML).triggers

        assert triggers.expiry_urgent_days == 7
        assert triggers.expiry_soon_days == 21
        assert triggers.theta_cost_excellent_pct == 1.0

    def test_round_trips_custom_values(self, tmp_path: Path) -> None:
        """Custom expiry / theta-excellent values round-trip."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "expiry_urgent_days": 10,
                "expiry_soon_days": 40,
                "theta_cost_excellent_pct": 0.5,
            },
        }
        triggers = load_ips_config(_write_yaml(tmp_path, config)).triggers

        assert triggers.expiry_urgent_days == 10
        assert triggers.expiry_soon_days == 40
        assert triggers.theta_cost_excellent_pct == 0.5

    def test_urgent_not_below_soon_raises(self, tmp_path: Path) -> None:
        """expiry_urgent_days >= expiry_soon_days raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "expiry_urgent_days": 30,
                "expiry_soon_days": 21,
            },
        }
        with pytest.raises(IpsConfigError, match="expiry_urgent_days"):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_theta_excellent_not_below_acceptable_raises(
        self,
        tmp_path: Path,
    ) -> None:
        """theta_cost_excellent_pct >= theta_cost_acceptable_pct raises."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "theta_cost_excellent_pct": 3.0,  # acceptable is 2.0
            },
        }
        with pytest.raises(IpsConfigError, match="theta_cost_excellent_pct"):
            load_ips_config(_write_yaml(tmp_path, config))


class TestGammaDriftBands:
    """Tests for the gamma-drift trigger bands (Mo3)."""

    def test_defaults_when_absent(self, tmp_path: Path) -> None:
        """A triggers section without the gamma keys uses the defaults."""
        ips = load_ips_config(_write_yaml(tmp_path, _VALID_CONFIG))
        triggers = ips.triggers

        assert triggers.gamma_drift_moderate_pct == 2.0
        assert triggers.gamma_drift_high_pct == 5.0

    def test_round_trips_custom_values(self, tmp_path: Path) -> None:
        """Custom gamma-drift bands round-trip."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "gamma_drift_moderate_pct": 1.5,
                "gamma_drift_high_pct": 4.0,
            },
        }
        triggers = load_ips_config(_write_yaml(tmp_path, config)).triggers

        assert triggers.gamma_drift_moderate_pct == 1.5
        assert triggers.gamma_drift_high_pct == 4.0

    def test_moderate_not_below_high_raises(self, tmp_path: Path) -> None:
        """gamma_drift_moderate_pct >= gamma_drift_high_pct raises."""
        config = {
            **_VALID_CONFIG,
            "triggers": {
                **_VALID_CONFIG["triggers"],
                "gamma_drift_moderate_pct": 5.0,
                "gamma_drift_high_pct": 2.0,
            },
        }
        with pytest.raises(IpsConfigError, match="gamma_drift_moderate_pct"):
            load_ips_config(_write_yaml(tmp_path, config))


class TestSizing:
    """Tests for the ``sizing`` policy section (beta-adjusted sizing, §2499)."""

    def test_defaults_when_section_absent(self, tmp_path: Path) -> None:
        """A config without a sizing section defaults portfolio_beta to 1.0."""
        path = _write_yaml(tmp_path, _VALID_CONFIG)  # no sizing section
        assert load_ips_config(path).sizing.portfolio_beta == 1.0

    def test_example_ips_yaml_sizing(self) -> None:
        """The shipped config/ips.yaml carries portfolio_beta 1.0."""
        assert load_ips_config(EXAMPLE_IPS_YAML).sizing.portfolio_beta == 1.0

    def test_round_trips_custom_value(self, tmp_path: Path) -> None:
        """A supplied portfolio_beta round-trips through the loader."""
        config = {**_VALID_CONFIG, "sizing": {"portfolio_beta": 0.85}}
        sizing = load_ips_config(_write_yaml(tmp_path, config)).sizing
        assert sizing.portfolio_beta == 0.85

    def test_zero_beta_raises(self, tmp_path: Path) -> None:
        """A non-positive portfolio_beta raises IpsConfigError."""
        config = {**_VALID_CONFIG, "sizing": {"portfolio_beta": 0.0}}
        with pytest.raises(IpsConfigError, match="portfolio_beta"):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_negative_beta_raises(self, tmp_path: Path) -> None:
        """A negative portfolio_beta raises IpsConfigError."""
        config = {**_VALID_CONFIG, "sizing": {"portfolio_beta": -1.0}}
        with pytest.raises(IpsConfigError, match="portfolio_beta"):
            load_ips_config(_write_yaml(tmp_path, config))
