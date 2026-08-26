"""Tests for deltadewa.ips_config."""

from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml

from deltadewa.clock import DEFAULT_PROGRAM_TIMEZONE
from deltadewa.constants import ExerciseStyle
from deltadewa.ips_config import (
    DEFAULT_DATA_TTL_MINUTES,
    DEFAULT_SKEW_HIGH_PCTILE,
    DEFAULT_SKEW_LOW_PCTILE,
    DEFAULT_SPOT_DIVERGENCE_WARN_PCT,
    DEFAULT_TERM_CONTANGO_TOLERANCE,
    DEFAULT_VOL_REGIME_HIGH,
    DEFAULT_VOL_REGIME_LOW,
    IpsConfigError,
    load_ips_config,
)

EXAMPLE_IPS_YAML = Path(__file__).parent.parent / "config" / "ips.example.yaml"
# #245: the real config/ips.yaml is gitignored (it holds this program's real
# policy), so the tracked config/ips.example.yaml — a documented placeholder
# template, not real values — is what these "shipped file" tests exercise.

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

    def test_timezone_defaults_to_the_us_equity_calendar(
        self,
        tmp_path: Path,
    ) -> None:
        """An IPS with no ``timezone`` gets the exchange's, not the server's.

        The default is deliberately not UTC: a program that never names a
        timezone is still hedging SPX on the US calendar (#182).
        """
        config = dict(_VALID_CONFIG)

        program = load_ips_config(_write_yaml(tmp_path, config)).program

        assert program.timezone == DEFAULT_PROGRAM_TIMEZONE

    def test_timezone_is_read_from_policy(self, tmp_path: Path) -> None:
        """A program on another exchange sets its own trading calendar."""
        config = dict(_VALID_CONFIG)
        config["program"] = {**config["program"], "timezone": "Europe/London"}

        program = load_ips_config(_write_yaml(tmp_path, config)).program

        assert program.timezone == ZoneInfo("Europe/London")

    def test_unknown_timezone_is_a_policy_error(self, tmp_path: Path) -> None:
        """A typo'd zone fails loudly rather than silently falling back.

        Silently defaulting would price the book on a calendar the policy
        did not ask for, which is the class of quiet wrongness #182 exists
        to remove.
        """
        config = dict(_VALID_CONFIG)
        config["program"] = {**config["program"], "timezone": "Mars/Olympus"}

        with pytest.raises(IpsConfigError, match=r"program\.timezone"):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_accepts_a_plain_string_path(self) -> None:
        """A ``str`` path loads, like the serializer's loaders (#182).

        Was: ``AttributeError: 'str' object has no attribute 'exists'`` —
        found while writing verification scripts for the review that filed
        the issue, which is exactly the "obvious" way to call it.
        """
        from_str = load_ips_config(str(EXAMPLE_IPS_YAML))
        from_path = load_ips_config(EXAMPLE_IPS_YAML)

        assert from_str == from_path

    def test_string_path_to_a_missing_file_raises_ips_config_error(
        self,
        tmp_path: Path,
    ) -> None:
        """The missing-file guard still fires, and still names the file.

        Accepting ``str`` must not turn a clear policy error into an
        ``AttributeError`` from somewhere deeper in the loader.
        """
        missing = str(tmp_path / "nope.yaml")

        with pytest.raises(IpsConfigError, match=r"ips\.yaml not found"):
            load_ips_config(missing)

    def test_loads_example_ips_yaml(self) -> None:
        """Test that the tracked config/ips.example.yaml loads (#245)."""
        ips = load_ips_config(EXAMPLE_IPS_YAML)

        assert ips.program.instrument == "SPX"
        assert ips.pricing.exercise_style == ExerciseStyle.EUROPEAN
        # Handbook family-office carry ceiling is 1% (Mi6); example default.
        assert ips.budget.annual_carry_pct == pytest.approx(1.0, rel=1e-7)
        assert ips.convexity.target_min_pct == pytest.approx(10.0, rel=1e-4)
        assert ips.convexity.target_max_pct == pytest.approx(20.0, rel=1e-4)
        assert ips.convexity.crash_vol_shock == pytest.approx(0.15, rel=1e-4)
        # #245's example uses its own placeholder, distinct from the 0.0
        # dataclass default, to show the field is meant to be set.
        assert ips.convexity.skew_steepening == pytest.approx(0.08, rel=1e-8)
        # M1.7: the steepening is anchored to each leg's ~10-delta wing.
        assert ips.convexity.skew_reference_delta == pytest.approx(
            0.10, rel=1e-8
        )
        assert ips.convexity.crash_floor_reported is True
        # M2.7: the example band is the handbook's own reading of the
        # convexity/carry ratio (< 3 poor, 3-6 acceptable, > 6 attractive).
        assert ips.convexity.efficiency_min_ratio == pytest.approx(3.0)
        assert ips.convexity.efficiency_max_ratio == pytest.approx(6.0)
        assert ips.drawdown.max_tolerance_pct == pytest.approx(15.0, rel=1e-4)
        assert ips.triggers.target_delta_ratio_pct == pytest.approx(
            90.0, rel=1e-4
        )
        assert ips.triggers.delta_drift_warn_pct == pytest.approx(4.0, rel=1e-7)
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

        assert ips.convexity.crash_vol_shock == pytest.approx(0.15, rel=1e-4)
        assert ips.convexity.skew_steepening == pytest.approx(0.0, rel=1e-8)
        assert ips.convexity.skew_reference_delta == pytest.approx(
            0.10, rel=1e-8
        )
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

        assert ips.convexity.crash_vol_shock == pytest.approx(0.20, rel=1e-8)
        assert ips.convexity.skew_steepening == pytest.approx(0.30, rel=1e-8)
        assert ips.convexity.skew_reference_delta == pytest.approx(
            0.15, rel=1e-4
        )
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

    def test_efficiency_band_defaults_to_the_handbook_reading(
        self,
        tmp_path: Path,
    ) -> None:
        """Omitted efficiency bands fall back to the handbook's 3 / 6."""
        # _VALID_CONFIG's convexity section carries no efficiency band.
        path = _write_yaml(tmp_path, _VALID_CONFIG)

        ips = load_ips_config(path)

        assert ips.convexity.efficiency_min_ratio == pytest.approx(3.0)
        assert ips.convexity.efficiency_max_ratio == pytest.approx(6.0)

    def test_efficiency_band_round_trips_when_set(
        self,
        tmp_path: Path,
    ) -> None:
        """A program running a different efficiency mandate is honoured."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
                "efficiency_min_ratio": 4.0,
                "efficiency_max_ratio": 9.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        ips = load_ips_config(path)

        assert ips.convexity.efficiency_min_ratio == pytest.approx(4.0)
        assert ips.convexity.efficiency_max_ratio == pytest.approx(9.0)

    def test_inverted_efficiency_band_raises(self, tmp_path: Path) -> None:
        """min > max would make ACCEPTABLE unreachable, so it's rejected."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
                "efficiency_min_ratio": 6.0,
                "efficiency_max_ratio": 3.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="efficiency_min_ratio"):
            load_ips_config(path)

    def test_negative_efficiency_min_raises(self, tmp_path: Path) -> None:
        """A negative efficiency floor raises IpsConfigError."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
                "efficiency_min_ratio": -1.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="efficiency_min_ratio"):
            load_ips_config(path)

    def test_cliff_thresholds_default_to_the_retired_gauge_values(
        self,
        tmp_path: Path,
    ) -> None:
        """Omitted cliff keys reproduce dashboard.yaml's old gauge exactly.

        The promotion out of presentation config must not change what a
        reading means, so the defaults are the gauge's own 180 / 90 / 30.
        #241 has since removed that gauge's copy of them, making these the
        only definition; the numbers must not move with it.
        """
        # _VALID_CONFIG's convexity section carries no cliff keys.
        path = _write_yaml(tmp_path, _VALID_CONFIG)

        ips = load_ips_config(path)

        assert ips.convexity.cliff_threshold_days == 180
        assert ips.convexity.cliff_review_days == 90
        assert ips.convexity.cliff_urgent_days == 30

    def test_cliff_thresholds_round_trip_when_set(
        self,
        tmp_path: Path,
    ) -> None:
        """A program wanting more warning before a roll is honoured."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
                "cliff_threshold_days": 270,
                "cliff_review_days": 120,
                "cliff_urgent_days": 45,
            },
        }
        path = _write_yaml(tmp_path, config)

        ips = load_ips_config(path)

        assert ips.convexity.cliff_threshold_days == 270
        assert ips.convexity.cliff_review_days == 120
        assert ips.convexity.cliff_urgent_days == 45

    def test_urgent_line_past_review_line_raises(self, tmp_path: Path) -> None:
        """URGENT must be reached after REVIEW, not before it.

        Inverted, every reading inside the review window would grade URGENT
        and the review line would be unreachable.
        """
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
                "cliff_review_days": 30,
                "cliff_urgent_days": 90,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="cliff_urgent_days"):
            load_ips_config(path)

    def test_negative_cliff_threshold_raises(self, tmp_path: Path) -> None:
        """A negative region boundary is meaningless, so it's rejected."""
        config = {
            **_VALID_CONFIG,
            "convexity": {
                "crash_scenario_pct": -25.0,
                "target_min_pct": 15.0,
                "target_max_pct": 25.0,
                "cliff_threshold_days": -10,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="cliff_threshold_days"):
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

        assert ips.triggers.roll_review_buffer == pytest.approx(1.5, rel=1e-7)
        assert ips.triggers.strike_drift_review_fraction == pytest.approx(
            0.75, rel=1e-4
        )

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

        assert ips.triggers.roll_review_buffer == pytest.approx(2.0, rel=1e-7)
        assert ips.triggers.strike_drift_review_fraction == pytest.approx(
            0.5, rel=1e-4
        )

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

        assert ips.triggers.target_delta_ratio_pct == pytest.approx(
            90.0, rel=1e-4
        )

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

        assert ips.triggers.target_delta_ratio_pct == pytest.approx(
            80.0, rel=1e-4
        )

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
        assert env.data_ttl_minutes == DEFAULT_DATA_TTL_MINUTES
        # vix_* defaults are seeded from the Python literals
        # entry_timing_tree used to hardcode, before M2.8 moved them here.
        assert env.vix_very_high == pytest.approx(40.0)
        assert env.vix_caution == pytest.approx(25.0)
        assert env.vix_low == pytest.approx(15.0)
        assert env.spot_divergence_warn_pct == DEFAULT_SPOT_DIVERGENCE_WARN_PCT

    def test_example_ips_yaml_market_environment(self) -> None:
        """The tracked config/ips.example.yaml carries the policy bands."""
        env = load_ips_config(EXAMPLE_IPS_YAML).market_environment

        assert env.vol_regime_low == pytest.approx(0.15, rel=1e-4)
        assert env.vol_regime_high == pytest.approx(0.35, rel=1e-4)
        assert env.skew_low_pctile == 25
        assert env.skew_high_pctile == 75
        assert env.term_contango_tolerance == pytest.approx(0.5, rel=1e-4)
        assert env.data_ttl_minutes == pytest.approx(1440.0, rel=1e-7)
        assert env.vix_very_high == pytest.approx(40.0)
        assert env.vix_caution == pytest.approx(25.0)
        assert env.vix_low == pytest.approx(15.0)
        assert env.spot_divergence_warn_pct == pytest.approx(2.0)

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
                "data_ttl_minutes": 45,
                "vix_very_high": 35.0,
                "vix_caution": 22.0,
                "vix_low": 13.0,
                "spot_divergence_warn_pct": 3.5,
            },
        }
        env = load_ips_config(_write_yaml(tmp_path, config)).market_environment

        assert env.vol_regime_low == pytest.approx(0.12, rel=1e-4)
        assert env.vol_regime_high == pytest.approx(0.40, rel=1e-8)
        assert env.skew_low_pctile == 20
        assert env.skew_high_pctile == 80
        assert env.term_contango_tolerance == pytest.approx(1.0, rel=1e-7)
        assert env.data_ttl_minutes == pytest.approx(45.0, rel=1e-7)
        assert env.vix_very_high == pytest.approx(35.0)
        assert env.vix_caution == pytest.approx(22.0)
        assert env.vix_low == pytest.approx(13.0)
        assert env.spot_divergence_warn_pct == pytest.approx(3.5)

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

    def test_zero_data_ttl_raises(self, tmp_path: Path) -> None:
        """A zero TTL would mark every cache hit STALE — refuse it."""
        config = {
            **_VALID_CONFIG,
            "market_environment": {"data_ttl_minutes": 0},
        }
        with pytest.raises(IpsConfigError, match="data_ttl_minutes"):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_negative_data_ttl_raises(self, tmp_path: Path) -> None:
        """A negative freshness window is meaningless."""
        config = {
            **_VALID_CONFIG,
            "market_environment": {"data_ttl_minutes": -5},
        }
        with pytest.raises(IpsConfigError, match="data_ttl_minutes"):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_vix_thresholds_out_of_order_raises(self, tmp_path: Path) -> None:
        """vix_low < vix_caution < vix_very_high must hold strictly."""
        config = {
            **_VALID_CONFIG,
            "market_environment": {
                "vix_low": 25.0,
                "vix_caution": 15.0,
                "vix_very_high": 40.0,
            },
        }
        with pytest.raises(IpsConfigError, match="vix"):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_vix_caution_equal_to_very_high_raises(
        self,
        tmp_path: Path,
    ) -> None:
        """Boundaries are strict, not inclusive."""
        config = {
            **_VALID_CONFIG,
            "market_environment": {
                "vix_low": 15.0,
                "vix_caution": 40.0,
                "vix_very_high": 40.0,
            },
        }
        with pytest.raises(IpsConfigError, match="vix"):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_negative_spot_divergence_warn_pct_raises(
        self,
        tmp_path: Path,
    ) -> None:
        """A negative divergence threshold is meaningless — refuse it."""
        config = {
            **_VALID_CONFIG,
            "market_environment": {"spot_divergence_warn_pct": -1.0},
        }
        with pytest.raises(
            IpsConfigError,
            match="spot_divergence_warn_pct",
        ):
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
        assert triggers.theta_cost_excellent_pct == pytest.approx(1.0, rel=1e-7)

    def test_example_ips_yaml_expiry_theta(self) -> None:
        """The tracked config/ips.example.yaml carries the trigger keys."""
        triggers = load_ips_config(EXAMPLE_IPS_YAML).triggers

        assert triggers.expiry_urgent_days == 7
        assert triggers.expiry_soon_days == 21
        assert triggers.theta_cost_excellent_pct == pytest.approx(1.0, rel=1e-7)

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
        assert triggers.theta_cost_excellent_pct == pytest.approx(0.5, rel=1e-4)

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

        assert triggers.gamma_drift_moderate_pct == pytest.approx(2.0, rel=1e-7)
        assert triggers.gamma_drift_high_pct == pytest.approx(5.0, rel=1e-7)

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

        assert triggers.gamma_drift_moderate_pct == pytest.approx(1.5, rel=1e-7)
        assert triggers.gamma_drift_high_pct == pytest.approx(4.0, rel=1e-7)

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


class TestVegaSufficiency:
    """The vega band is policy (Part X #4), and the section is optional."""

    def test_example_ips_yaml_carries_the_band(self) -> None:
        ips = load_ips_config(EXAMPLE_IPS_YAML)

        assert ips.vega.sufficiency_min_pct == pytest.approx(1.5)
        assert ips.vega.sufficiency_max_pct == pytest.approx(4.0)

    def test_missing_section_falls_back_to_defaults(
        self,
        tmp_path: Path,
    ) -> None:
        """An ips.yaml written before this section existed still loads."""
        # _VALID_CONFIG has no vega section at all.
        path = _write_yaml(tmp_path, _VALID_CONFIG)

        ips = load_ips_config(path)

        assert ips.vega.sufficiency_min_pct == pytest.approx(1.5)
        assert ips.vega.sufficiency_max_pct == pytest.approx(4.0)

    def test_band_is_on_the_scale_the_metric_actually_produces(self) -> None:
        """The band must be reachable by a real book (#241).

        M2.7 seeded this band from ``dashboard.yaml``'s ``vega_sufficiency``
        gauge, whose numbers were a signed display axis rather than a band.
        The result (20-50) could not be hit: the metric divides by total
        portfolio value including the equity leg, so a tail-hedge book reads
        low single digits and ``/design`` said "outside band" always.

        This pins the *scale*, not the values — retune the band freely, but a
        band the canonical book cannot sit inside is the bug, not a policy.
        """
        ips = load_ips_config(EXAMPLE_IPS_YAML)
        canonical_book_reading_pct = 2.70  # spx_tail_20m, priced at 20% vol

        assert (
            ips.vega.sufficiency_min_pct
            <= canonical_book_reading_pct
            <= ips.vega.sufficiency_max_pct
        )

    def test_explicit_band_round_trips(self, tmp_path: Path) -> None:
        config = {
            **_VALID_CONFIG,
            "vega": {
                "sufficiency_min_pct": 12.5,
                "sufficiency_max_pct": 40.0,
            },
        }
        path = _write_yaml(tmp_path, config)

        ips = load_ips_config(path)

        assert ips.vega.sufficiency_min_pct == pytest.approx(12.5)
        assert ips.vega.sufficiency_max_pct == pytest.approx(40.0)

    @pytest.mark.parametrize(
        ("min_pct", "max_pct"),
        [(50.0, 20.0), (20.0, 20.0)],
    )
    def test_non_increasing_band_raises(
        self,
        tmp_path: Path,
        min_pct: float,
        max_pct: float,
    ) -> None:
        """band_bar requires low < high, so a degenerate band is rejected."""
        config = {
            **_VALID_CONFIG,
            "vega": {
                "sufficiency_min_pct": min_pct,
                "sufficiency_max_pct": max_pct,
            },
        }
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="sufficiency_min_pct"):
            load_ips_config(path)

    def test_non_mapping_section_raises(self, tmp_path: Path) -> None:
        config = {**_VALID_CONFIG, "vega": 20.0}
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="vega"):
            load_ips_config(path)


class TestSizing:
    """Tests for the ``sizing`` policy section.

    Handbook `Beta-Adjusted Hedge Sizing
    <https://qwertytam.github.io/deltadewa-handbook/part-7/beta-adjusted-hedge-sizing/>`_.
    """

    def test_defaults_when_section_absent(self, tmp_path: Path) -> None:
        """A config without a sizing section defaults portfolio_beta to 1.0."""
        path = _write_yaml(tmp_path, _VALID_CONFIG)  # no sizing section
        assert load_ips_config(path).sizing.portfolio_beta == pytest.approx(
            1.0, rel=1e-4
        )

    def test_example_ips_yaml_sizing(self) -> None:
        """The tracked config/ips.example.yaml carries portfolio_beta 1.0."""
        assert load_ips_config(
            EXAMPLE_IPS_YAML
        ).sizing.portfolio_beta == pytest.approx(1.0, rel=1e-7)

    def test_round_trips_custom_value(self, tmp_path: Path) -> None:
        """A supplied portfolio_beta round-trips through the loader."""
        config = {**_VALID_CONFIG, "sizing": {"portfolio_beta": 0.85}}
        sizing = load_ips_config(_write_yaml(tmp_path, config)).sizing
        assert sizing.portfolio_beta == pytest.approx(0.85, rel=1e-4)

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


class TestPricingInputs:
    """Tests for the ``pricing_inputs`` policy section (Batch 3d, #367).

    Review-cadence bands for the four hand-entered pricing inputs — spot,
    per-leg IV, risk-free rate, dividend yield — the program never fetches.
    """

    def test_defaults_when_section_absent(self, tmp_path: Path) -> None:
        """A config without the section falls back to the module defaults."""
        path = _write_yaml(tmp_path, _VALID_CONFIG)
        pricing_inputs = load_ips_config(path).pricing_inputs

        assert pricing_inputs.spot_max_age_days == 1
        assert pricing_inputs.volatility_max_age_days == 7
        assert pricing_inputs.risk_free_rate_max_age_days == 30
        assert pricing_inputs.dividend_yield_max_age_days == 90

    def test_example_ips_yaml_carries_the_section(self) -> None:
        """The tracked config/ips.example.yaml writes the section out."""
        pricing_inputs = load_ips_config(EXAMPLE_IPS_YAML).pricing_inputs

        assert pricing_inputs.spot_max_age_days == 1
        assert pricing_inputs.volatility_max_age_days == 7
        assert pricing_inputs.risk_free_rate_max_age_days == 30
        assert pricing_inputs.dividend_yield_max_age_days == 90

    def test_round_trips_custom_values(self, tmp_path: Path) -> None:
        config = {
            **_VALID_CONFIG,
            "pricing_inputs": {
                "spot_max_age_days": 2,
                "volatility_max_age_days": 14,
                "risk_free_rate_max_age_days": 60,
                "dividend_yield_max_age_days": 180,
            },
        }
        pricing_inputs = load_ips_config(
            _write_yaml(tmp_path, config)
        ).pricing_inputs

        assert pricing_inputs.spot_max_age_days == 2
        assert pricing_inputs.volatility_max_age_days == 14
        assert pricing_inputs.risk_free_rate_max_age_days == 60
        assert pricing_inputs.dividend_yield_max_age_days == 180

    @pytest.mark.parametrize(
        "field",
        [
            "spot_max_age_days",
            "volatility_max_age_days",
            "risk_free_rate_max_age_days",
            "dividend_yield_max_age_days",
        ],
    )
    def test_non_positive_max_age_raises(
        self,
        tmp_path: Path,
        field: str,
    ) -> None:
        """A zero or negative max age has no honest reading — reject it."""
        config = {**_VALID_CONFIG, "pricing_inputs": {field: 0}}
        with pytest.raises(IpsConfigError, match=field):
            load_ips_config(_write_yaml(tmp_path, config))

    def test_non_mapping_section_raises(self, tmp_path: Path) -> None:
        config = {**_VALID_CONFIG, "pricing_inputs": 30}
        path = _write_yaml(tmp_path, config)

        with pytest.raises(IpsConfigError, match="pricing_inputs"):
            load_ips_config(path)


class TestDefaultedSections:
    """#309: which optional sections silently fell back to code defaults.

    ``defaulted_sections`` is what ``/health``'s ``ips_sections_configured``
    check reports (deltadewa/app/health_checks.py) — computed from the raw
    YAML's own top-level keys, not from comparing parsed values back to the
    ``DEFAULT_*`` constants, so an operator who deliberately typed the
    default number back in is not mistaken for a missing section.
    """

    def test_all_four_optional_sections_absent(
        self,
        tmp_path: Path,
    ) -> None:
        """_VALID_CONFIG carries none of the four optional sections."""
        path = _write_yaml(tmp_path, _VALID_CONFIG)

        config = load_ips_config(path)

        assert config.defaulted_sections == frozenset(
            {"market_environment", "sizing", "vega", "pricing_inputs"},
        )

    def test_example_ips_yaml_has_no_defaulted_sections(self) -> None:
        """The tracked template writes out all three sections explicitly."""
        config = load_ips_config(EXAMPLE_IPS_YAML)

        assert config.defaulted_sections == frozenset()

    def test_one_section_present_is_not_reported_as_defaulted(
        self,
        tmp_path: Path,
    ) -> None:
        """Only the sections actually missing from the YAML are flagged."""
        config_dict = {**_VALID_CONFIG, "sizing": {"portfolio_beta": 0.85}}
        path = _write_yaml(tmp_path, config_dict)

        config = load_ips_config(path)

        assert config.defaulted_sections == frozenset(
            {"market_environment", "vega", "pricing_inputs"},
        )

    def test_a_value_matching_the_default_is_still_not_defaulted(
        self,
        tmp_path: Path,
    ) -> None:
        """Typing the default back in is not the same as omitting it."""
        config_dict = {
            **_VALID_CONFIG,
            "sizing": {"portfolio_beta": 1.0},  # equals _DEFAULT_PORTFOLIO_BETA
        }
        path = _write_yaml(tmp_path, config_dict)

        config = load_ips_config(path)

        assert "sizing" not in config.defaulted_sections
