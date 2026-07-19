"""Typed loader for the hedge program policy file (``ips.yaml``).

The IPS ("Investment Policy Statement") config is the single source of
truth for hedge program thresholds and the pricing-engine default exercise
style — distinct from ``dashboard_config_*.yaml`` (loaded by
``widgets/health_dashboard.py``), which is presentation-only (gauge ranges).
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any, Final

from deltadewa.constants import ExerciseStyle

# Defaults for the crash-repricing knobs that live alongside
# ``crash_scenario_pct`` in the ``convexity`` section. The crash *move* itself
# is single-sourced from ``crash_scenario_pct`` (never duplicated here); these
# two knobs are the flat vol-bump magnitude and the intrinsic-floor toggle used
# by the M1.2 crash-repricing metric.
_DEFAULT_CRASH_VOL_SHOCK: Final[float] = 0.15
_DEFAULT_CRASH_FLOOR_REPORTED: Final[bool] = True

# Default for the delta-drift target that lives alongside the delta_drift
# thresholds in the ``triggers`` section. A tail-hedged book is deliberately
# net long (deep-OTM puts offset only a sliver of equity delta), so drift is
# measured as deviation from this stated net-delta-to-equity ratio rather than
# distance from full delta-neutrality.
_DEFAULT_TARGET_DELTA_RATIO_PCT: Final[float] = 90.0

# Defaults for the expiry / theta trigger thresholds that
# ``HedgeTriggerThresholds`` previously hardcoded. Sourced here so ``from_ips``
# can map every threshold and no policy value stays on a dataclass literal.
_DEFAULT_EXPIRY_URGENT_DAYS: Final[int] = 7
_DEFAULT_EXPIRY_SOON_DAYS: Final[int] = 21
_DEFAULT_THETA_COST_EXCELLENT_PCT: Final[float] = 1.0

# Gamma-drift bands, in % of the hedged equity that net delta shifts per 1% spot
# move (``|gamma| * spot / |underlying_quantity|`` — book-size-independent).
# A tail hedge is deliberately gamma-light: the canonical SPX book reads ~1.3%.
_DEFAULT_GAMMA_DRIFT_MODERATE_PCT: Final[float] = 2.0
_DEFAULT_GAMMA_DRIFT_HIGH_PCT: Final[float] = 5.0

# Single source for the market-environment policy bands (see
# ``IpsMarketEnvironment``). Public because they are consumed across
# ``analysis.market_environment``, ``analysis.health``,
# ``analysis.decision_matrix``, and ``widgets.health_dashboard`` — no consumer
# redefines a band literal. The vol-regime band is decimal implied vol; the skew
# band is a percentile on 0-100 (converted to a 0-1 fraction at the consumer
# edge); the term tolerance is in VIX points.
DEFAULT_VOL_REGIME_LOW: Final[float] = 0.15
DEFAULT_VOL_REGIME_HIGH: Final[float] = 0.35
DEFAULT_SKEW_LOW_PCTILE: Final[float] = 25.0
DEFAULT_SKEW_HIGH_PCTILE: Final[float] = 75.0
DEFAULT_TERM_CONTANGO_TOLERANCE: Final[float] = 0.5

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


@dataclass(frozen=True)
class IpsMarketEnvironment:
    """Policy bands that classify the market's hedge-cost environment.

    These drive the ``hedge_cost_verdict`` decision (CHEAP/FAIR/EXPENSIVE) and
    the vol-regime gauge, so they are policy, not presentation. This is the
    single source every consumer reads; no module redefines a band literal.

    Units:
        ``vol_regime_low``/``vol_regime_high`` are decimal implied vol
        (``0.15`` = 15%), compared against ``VIX / 100``.
        ``skew_low_pctile``/``skew_high_pctile`` are SKEW percentiles on 0-100,
        converted to the 0-1 fraction ``get_skew_percentile`` returns once at
        the ``assess_market_environment`` edge.
        ``term_contango_tolerance`` is in VIX points; slopes below it read FLAT.
    """

    vol_regime_low: float = DEFAULT_VOL_REGIME_LOW
    vol_regime_high: float = DEFAULT_VOL_REGIME_HIGH
    skew_low_pctile: float = DEFAULT_SKEW_LOW_PCTILE
    skew_high_pctile: float = DEFAULT_SKEW_HIGH_PCTILE
    term_contango_tolerance: float = DEFAULT_TERM_CONTANGO_TOLERANCE


@dataclass(frozen=True)
class IpsBudget:
    """Premium budget for the hedge program."""

    annual_carry_pct: float


@dataclass(frozen=True)
class IpsConvexity:
    """Target convexity (hedge payoff) range under a crash scenario.

    ``crash_scenario_pct`` is the single source of truth for the crash *move*
    (a signed percent, e.g. ``-25.0``) across every panel. ``crash_vol_shock``
    and ``crash_floor_reported`` are the two crash-repricing knobs co-located
    here (see ``docs/repricing-methodology.md`` §5): the flat additive
    volatility bump applied at the crash spot, and whether the intrinsic-floor
    column is surfaced.
    """

    crash_scenario_pct: float
    target_min_pct: float
    target_max_pct: float
    crash_vol_shock: float = _DEFAULT_CRASH_VOL_SHOCK
    crash_floor_reported: bool = _DEFAULT_CRASH_FLOOR_REPORTED


@dataclass(frozen=True)
class IpsDrawdown:
    """Maximum tolerated portfolio drawdown."""

    max_tolerance_pct: float


@dataclass(frozen=True)
class IpsTriggers:
    """Thresholds that trigger a hedge review or rebalance.

    ``target_delta_ratio_pct`` is the intended net-delta-to-equity ratio (%)
    the book is run at; delta drift is measured as deviation from it (in
    percentage points), and the ``delta_drift_*`` fields are those deviation
    bands. Distinct from ``recommendations``'s ``target_hedge_ratio`` (the
    complement, option-offset framing).

    ``expiry_urgent_days`` / ``expiry_soon_days`` bound the URGENT / SOON
    expiration windows and ``theta_cost_excellent_pct`` is the EXCELLENT theta
    cutoff; ``HedgeTriggerThresholds.from_ips`` maps them all so no trigger
    threshold stays hardcoded.

    ``gamma_drift_moderate_pct`` / ``gamma_drift_high_pct`` band the gamma
    trigger. It fires on gamma *drift* — the % of the hedged equity that net
    delta shifts per 1% spot move — not raw gamma, which scales with book size.
    """

    delta_drift_warn_pct: float
    delta_drift_action_pct: float
    theta_cost_acceptable_pct: float
    roll_time_months: float
    rally_rebalance_pct: float
    strike_drift_max_otm_pct: float
    target_delta_ratio_pct: float = _DEFAULT_TARGET_DELTA_RATIO_PCT
    roll_review_buffer: float = 1.5
    strike_drift_review_fraction: float = 0.75
    expiry_urgent_days: int = _DEFAULT_EXPIRY_URGENT_DAYS
    expiry_soon_days: int = _DEFAULT_EXPIRY_SOON_DAYS
    theta_cost_excellent_pct: float = _DEFAULT_THETA_COST_EXCELLENT_PCT
    gamma_drift_moderate_pct: float = _DEFAULT_GAMMA_DRIFT_MODERATE_PCT
    gamma_drift_high_pct: float = _DEFAULT_GAMMA_DRIFT_HIGH_PCT


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
    market_environment: IpsMarketEnvironment = dataclass_field(
        default_factory=IpsMarketEnvironment,
    )


def _require_section(config: dict[str, Any], name: str) -> dict[str, Any]:
    if name not in config or not isinstance(config[name], dict):
        raise IpsConfigError(f"ips.yaml must contain a '{name}' section")
    return dict(config[name])


def _require_field(
    section: dict[str, Any],
    section_name: str,
    field: str,
) -> Any:  # noqa: ANN401  # YAML field is polymorphic (str | int | float | bool | list | dict)
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
    return IpsPricing(exercise_style=exercise_style)


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

    crash_vol_shock = section.get(
        "crash_vol_shock",
        _DEFAULT_CRASH_VOL_SHOCK,
    )
    _require_non_negative(crash_vol_shock, "convexity.crash_vol_shock")
    crash_floor_reported = bool(
        section.get("crash_floor_reported", _DEFAULT_CRASH_FLOOR_REPORTED),
    )

    return IpsConvexity(
        crash_scenario_pct=crash_scenario_pct,
        target_min_pct=target_min_pct,
        target_max_pct=target_max_pct,
        crash_vol_shock=crash_vol_shock,
        crash_floor_reported=crash_floor_reported,
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
        key: _require_field(section, "triggers", key)
        for key in (
            "delta_drift_warn_pct",
            "delta_drift_action_pct",
            "theta_cost_acceptable_pct",
            "roll_time_months",
            "rally_rebalance_pct",
            "strike_drift_max_otm_pct",
        )
    }
    for key, value in fields.items():
        _require_non_negative(value, f"triggers.{key}")
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

    roll_review_buffer = section.get("roll_review_buffer", 1.5)
    if roll_review_buffer <= 1.0:
        raise IpsConfigError(
            "triggers.roll_review_buffer must be > 1.0, got "
            f"{roll_review_buffer}",
        )

    strike_drift_review_fraction = section.get(
        "strike_drift_review_fraction",
        0.75,
    )
    if not 0 < strike_drift_review_fraction < 1:
        raise IpsConfigError(
            "triggers.strike_drift_review_fraction must be in (0, 1), got "
            f"{strike_drift_review_fraction}",
        )

    target_delta_ratio_pct = section.get(
        "target_delta_ratio_pct",
        _DEFAULT_TARGET_DELTA_RATIO_PCT,
    )
    _require_non_negative(
        target_delta_ratio_pct,
        "triggers.target_delta_ratio_pct",
    )

    expiry_urgent_days = section.get(
        "expiry_urgent_days",
        _DEFAULT_EXPIRY_URGENT_DAYS,
    )
    expiry_soon_days = section.get(
        "expiry_soon_days",
        _DEFAULT_EXPIRY_SOON_DAYS,
    )
    _require_non_negative(expiry_urgent_days, "triggers.expiry_urgent_days")
    _require_non_negative(expiry_soon_days, "triggers.expiry_soon_days")
    if expiry_urgent_days >= expiry_soon_days:
        raise IpsConfigError(
            "triggers.expiry_urgent_days must be < expiry_soon_days, got "
            f"{expiry_urgent_days} >= {expiry_soon_days}",
        )

    theta_cost_excellent_pct = section.get(
        "theta_cost_excellent_pct",
        _DEFAULT_THETA_COST_EXCELLENT_PCT,
    )
    _require_non_negative(
        theta_cost_excellent_pct,
        "triggers.theta_cost_excellent_pct",
    )
    if theta_cost_excellent_pct >= fields["theta_cost_acceptable_pct"]:
        raise IpsConfigError(
            "triggers.theta_cost_excellent_pct must be < "
            "theta_cost_acceptable_pct, got "
            f"{theta_cost_excellent_pct} >= "
            f"{fields['theta_cost_acceptable_pct']}",
        )

    gamma_drift_moderate_pct = section.get(
        "gamma_drift_moderate_pct",
        _DEFAULT_GAMMA_DRIFT_MODERATE_PCT,
    )
    gamma_drift_high_pct = section.get(
        "gamma_drift_high_pct",
        _DEFAULT_GAMMA_DRIFT_HIGH_PCT,
    )
    _require_non_negative(
        gamma_drift_moderate_pct,
        "triggers.gamma_drift_moderate_pct",
    )
    if gamma_drift_moderate_pct >= gamma_drift_high_pct:
        raise IpsConfigError(
            "triggers.gamma_drift_moderate_pct must be < gamma_drift_high_pct, "
            f"got {gamma_drift_moderate_pct} >= {gamma_drift_high_pct}",
        )

    return IpsTriggers(
        **fields,
        target_delta_ratio_pct=target_delta_ratio_pct,
        roll_review_buffer=roll_review_buffer,
        strike_drift_review_fraction=strike_drift_review_fraction,
        expiry_urgent_days=expiry_urgent_days,
        expiry_soon_days=expiry_soon_days,
        theta_cost_excellent_pct=theta_cost_excellent_pct,
        gamma_drift_moderate_pct=gamma_drift_moderate_pct,
        gamma_drift_high_pct=gamma_drift_high_pct,
    )


def _parse_market_environment(config: dict[str, Any]) -> IpsMarketEnvironment:
    """Parse the optional ``market_environment`` policy section.

    The section is optional: a missing section (or any missing field) falls back
    to the ``DEFAULT_*`` module constants — the same single source the dataclass
    defaults use — so an older ips.yaml keeps working.
    """
    section = config.get("market_environment", {})
    if not isinstance(section, dict):
        raise IpsConfigError(
            "ips.yaml 'market_environment' section must be a mapping",
        )

    vol_low = section.get("vol_regime_low", DEFAULT_VOL_REGIME_LOW)
    vol_high = section.get("vol_regime_high", DEFAULT_VOL_REGIME_HIGH)
    skew_low = section.get("skew_low_pctile", DEFAULT_SKEW_LOW_PCTILE)
    skew_high = section.get("skew_high_pctile", DEFAULT_SKEW_HIGH_PCTILE)
    term_tol = section.get(
        "term_contango_tolerance",
        DEFAULT_TERM_CONTANGO_TOLERANCE,
    )

    if vol_low >= vol_high:
        raise IpsConfigError(
            "market_environment.vol_regime_low must be < vol_regime_high, got "
            f"{vol_low} >= {vol_high}",
        )
    if not 0 <= skew_low < skew_high <= 100:
        raise IpsConfigError(
            "market_environment skew percentiles must satisfy 0 <= "
            "skew_low_pctile < skew_high_pctile <= 100, got "
            f"{skew_low}, {skew_high}",
        )
    _require_non_negative(
        term_tol,
        "market_environment.term_contango_tolerance",
    )

    return IpsMarketEnvironment(
        vol_regime_low=vol_low,
        vol_regime_high=vol_high,
        skew_low_pctile=skew_low,
        skew_high_pctile=skew_high,
        term_contango_tolerance=term_tol,
    )


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
        if not 0 < sell_pct <= 100:
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
        market_environment=_parse_market_environment(config),
    )
