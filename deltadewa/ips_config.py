"""Typed loader for the hedge program policy file (``ips.yaml``).

The IPS ("Investment Policy Statement") config is the single source of
truth for hedge program thresholds and the pricing-engine default exercise
style — distinct from ``dashboard_config_*.yaml`` (loaded by
``widgets/health_dashboard.py``), which is presentation-only (gauge ranges).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deltadewa.constants import ExerciseStyle

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class IpsConfigError(ValueError):
    """Raised when an ips.yaml file is missing, malformed, or out of range."""


@dataclass(frozen=True)
class IpsProgram:
    """Identifies the hedge program and its underlying instrument."""

    name: str
    instrument: str


@dataclass(frozen=True)
class IpsPricing:
    """Pricing-engine defaults for the program's instrument."""

    exercise_style: ExerciseStyle
    american_use_closed_form: bool = True


@dataclass(frozen=True)
class IpsBudget:
    """Premium budget for the hedge program."""

    annual_carry_pct: float


@dataclass(frozen=True)
class IpsConvexity:
    """Target convexity (hedge payoff) range under a crash scenario."""

    crash_scenario_pct: float
    target_min_pct: float
    target_max_pct: float


@dataclass(frozen=True)
class IpsDrawdown:
    """Maximum tolerated portfolio drawdown."""

    max_tolerance_pct: float


@dataclass(frozen=True)
class IpsTriggers:
    """Thresholds that trigger a hedge review or rebalance."""

    delta_drift_warn_pct: float
    delta_drift_action_pct: float
    theta_cost_acceptable_pct: float
    roll_time_months: float
    rally_rebalance_pct: float
    strike_drift_max_otm_pct: float


@dataclass(frozen=True)
class IpsMonetizationStep:
    """One step of a hedge-gain monetization schedule."""

    gain_pct: float
    sell_pct: float


@dataclass(frozen=True)
class IpsMonetization:
    """Schedule for monetizing hedge gains as the hedge appreciates."""

    schedule: tuple[IpsMonetizationStep, ...]


@dataclass(frozen=True)
class IpsConfig:
    """Fully validated hedge program policy."""

    program: IpsProgram
    pricing: IpsPricing
    budget: IpsBudget
    convexity: IpsConvexity
    drawdown: IpsDrawdown
    triggers: IpsTriggers
    monetization: IpsMonetization


def _require_section(config: dict[str, Any], name: str) -> dict[str, Any]:
    if name not in config or not isinstance(config[name], dict):
        raise IpsConfigError(f"ips.yaml must contain a '{name}' section")
    return config[name]


def _require_field(
    section: dict[str, Any],
    section_name: str,
    field: str,
) -> Any:  # noqa: ANN401
    if field not in section:
        raise IpsConfigError(
            f"ips.yaml '{section_name}' section missing required field "
            f"'{field}'",
        )
    return section[field]


def _require_non_negative(value: float, label: str) -> None:
    if value < 0:
        raise IpsConfigError(f"{label} must be >= 0, got {value}")


def _parse_program(config: dict[str, Any]) -> IpsProgram:
    section = _require_section(config, "program")
    return IpsProgram(
        name=_require_field(section, "program", "name"),
        instrument=_require_field(section, "program", "instrument"),
    )


def _parse_pricing(config: dict[str, Any]) -> IpsPricing:
    section = _require_section(config, "pricing")
    raw_style = _require_field(section, "pricing", "exercise_style")
    try:
        exercise_style = ExerciseStyle(raw_style)
    except ValueError as exc:
        raise IpsConfigError(
            f"pricing.exercise_style must be one of "
            f"{[s.value for s in ExerciseStyle]}, got '{raw_style}'",
        ) from exc
    return IpsPricing(
        exercise_style=exercise_style,
        american_use_closed_form=section.get("american_use_closed_form", True),
    )


def _parse_budget(config: dict[str, Any]) -> IpsBudget:
    section = _require_section(config, "budget")
    annual_carry_pct = _require_field(section, "budget", "annual_carry_pct")
    _require_non_negative(annual_carry_pct, "budget.annual_carry_pct")
    return IpsBudget(annual_carry_pct=annual_carry_pct)


def _parse_convexity(config: dict[str, Any]) -> IpsConvexity:
    section = _require_section(config, "convexity")
    crash_scenario_pct = _require_field(
        section,
        "convexity",
        "crash_scenario_pct",
    )
    target_min_pct = _require_field(section, "convexity", "target_min_pct")
    target_max_pct = _require_field(section, "convexity", "target_max_pct")

    if crash_scenario_pct >= 0:
        raise IpsConfigError(
            "convexity.crash_scenario_pct must be negative (a decline), "
            f"got {crash_scenario_pct}",
        )
    _require_non_negative(target_min_pct, "convexity.target_min_pct")
    _require_non_negative(target_max_pct, "convexity.target_max_pct")
    if target_min_pct > target_max_pct:
        raise IpsConfigError(
            "convexity.target_min_pct must be <= target_max_pct, got "
            f"{target_min_pct} > {target_max_pct}",
        )
    return IpsConvexity(
        crash_scenario_pct=crash_scenario_pct,
        target_min_pct=target_min_pct,
        target_max_pct=target_max_pct,
    )


def _parse_drawdown(config: dict[str, Any]) -> IpsDrawdown:
    section = _require_section(config, "drawdown")
    max_tolerance_pct = _require_field(
        section,
        "drawdown",
        "max_tolerance_pct",
    )
    _require_non_negative(max_tolerance_pct, "drawdown.max_tolerance_pct")
    return IpsDrawdown(max_tolerance_pct=max_tolerance_pct)


def _parse_triggers(config: dict[str, Any]) -> IpsTriggers:
    section = _require_section(config, "triggers")
    fields = {
        field: _require_field(section, "triggers", field)
        for field in (
            "delta_drift_warn_pct",
            "delta_drift_action_pct",
            "theta_cost_acceptable_pct",
            "roll_time_months",
            "rally_rebalance_pct",
            "strike_drift_max_otm_pct",
        )
    }
    for field, value in fields.items():
        _require_non_negative(value, f"triggers.{field}")
    if fields["delta_drift_warn_pct"] >= fields["delta_drift_action_pct"]:
        raise IpsConfigError(
            "triggers.delta_drift_warn_pct must be < "
            "delta_drift_action_pct, got "
            f"{fields['delta_drift_warn_pct']} >= "
            f"{fields['delta_drift_action_pct']}",
        )
    if fields["roll_time_months"] <= 0:
        raise IpsConfigError(
            f"triggers.roll_time_months must be > 0, got "
            f"{fields['roll_time_months']}",
        )
    return IpsTriggers(**fields)


def _parse_monetization(config: dict[str, Any]) -> IpsMonetization:
    section = _require_section(config, "monetization")
    raw_schedule = _require_field(section, "monetization", "schedule")
    if not isinstance(raw_schedule, list) or not raw_schedule:
        raise IpsConfigError(
            "monetization.schedule must be a non-empty list",
        )

    steps = []
    total_sell_pct = 0.0
    for i, raw_step in enumerate(raw_schedule):
        step_label = f"monetization.schedule[{i}]"
        gain_pct = _require_field(raw_step, step_label, "gain_pct")
        sell_pct = _require_field(raw_step, step_label, "sell_pct")
        if gain_pct <= 0:
            raise IpsConfigError(
                f"monetization.schedule[{i}].gain_pct must be > 0, got "
                f"{gain_pct}",
            )
        if not (0 < sell_pct <= 100):
            raise IpsConfigError(
                f"monetization.schedule[{i}].sell_pct must be in "
                f"(0, 100], got {sell_pct}",
            )
        total_sell_pct += sell_pct
        steps.append(IpsMonetizationStep(gain_pct=gain_pct, sell_pct=sell_pct))

    if total_sell_pct > 100:
        raise IpsConfigError(
            "monetization.schedule sell_pct values must sum to <= 100, "
            f"got {total_sell_pct}",
        )
    return IpsMonetization(schedule=tuple(steps))


def load_ips_config(path: Path) -> IpsConfig:
    """Load and validate a hedge program policy file into an ``IpsConfig``.

    Args:
        path: Path to the ``ips.yaml`` file.

    Returns:
        Fully validated ``IpsConfig``.

    Raises:
        IpsConfigError: If the file is missing, the YAML is malformed, a
            required field is missing, or any value fails validation.

    """
    if not YAML_AVAILABLE:
        raise IpsConfigError("PyYAML is not installed; cannot load ips.yaml")

    if not path.exists():
        raise IpsConfigError(f"ips.yaml not found at {path}")

    try:
        with Path.open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise IpsConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(config, dict):
        raise IpsConfigError("ips.yaml root must be a mapping/object")

    return IpsConfig(
        program=_parse_program(config),
        pricing=_parse_pricing(config),
        budget=_parse_budget(config),
        convexity=_parse_convexity(config),
        drawdown=_parse_drawdown(config),
        triggers=_parse_triggers(config),
        monetization=_parse_monetization(config),
    )
