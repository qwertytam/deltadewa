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
# knobs are the flat vol-bump magnitude, the deep-OTM skew steepening and the
# put-delta wing it is anchored to (M1.6/M1.7), and the intrinsic-floor toggle
# used by the M1.2 crash-repricing metric.
_DEFAULT_CRASH_VOL_SHOCK: Final[float] = 0.15
_DEFAULT_SKEW_STEEPENING: Final[float] = 0.0
_DEFAULT_SKEW_REFERENCE_DELTA: Final[float] = 0.10
_DEFAULT_CRASH_FLOOR_REPORTED: Final[bool] = True

# Hedge-efficiency band: crash payoff per dollar of annual carry, read against
# the handbook's own interpretation table (docs/hedging handbook.md:4342-4348 —
# "< 3 poor / 3 to 6 acceptable / > 6 attractive"). Policy rather than
# presentation because it answers a mandate question ("is this hedge worth the
# money"), the same class as the convexity band it sits beside.
_DEFAULT_EFFICIENCY_MIN_RATIO: Final[float] = 3.0
_DEFAULT_EFFICIENCY_MAX_RATIO: Final[float] = 6.0

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

# Default portfolio beta vs SPX for hedge sizing (see ``IpsSizing``). 1.0 means
# the protected book is assumed to move 1:1 with the index — the same implicit
# assumption the sizing framework carried before beta-adjustment, so a config
# without a ``sizing`` section reproduces the pre-beta sizing exactly.
_DEFAULT_PORTFOLIO_BETA: Final[float] = 1.0

# Vega sufficiency band, in % portfolio value change per +10 vol points (see
# ``IpsVega``). The handbook gives this metric no numeric band — only a
# Low<->High gauge — so these are seeded from the values
# ``config/dashboard.yaml``'s ``vega_sufficiency`` gauge already carried
# (``max_val: 20`` as the "high vega exposure" line, ``end: 50`` as its
# ceiling), so that moving the metric onto a policy surface does not silently
# change what a given reading means. They are a starting point to be set
# deliberately per program, not a derived constant.
_DEFAULT_VEGA_SUFFICIENCY_MIN_PCT: Final[float] = 20.0
_DEFAULT_VEGA_SUFFICIENCY_MAX_PCT: Final[float] = 50.0

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

# Defaults for the entry-timing VIX thresholds (M2.8). Seeded from the
# values ``decision_matrix.entry_timing_tree`` used to hardcode as Python
# defaults, so moving them onto this policy surface does not silently
# change what a given VIX reading means. Private (unlike the bands above):
# entry_timing_tree's vix_* parameters are no longer defaulted at all — a
# caller must pass them explicitly (the M1.4/M1.5 fail-loud pattern) — so
# these are consulted only when loading ips.yaml, never as a function
# default elsewhere.
_DEFAULT_VIX_VERY_HIGH: Final[float] = 40.0
_DEFAULT_VIX_CAUTION: Final[float] = 25.0
_DEFAULT_VIX_LOW: Final[float] = 15.0

# How long a fetched market data value stays trustworthy. This is the boundary
# between a CACHED reading (good enough for a verdict) and a STALE one (not),
# so it is policy, not a provider implementation detail.
#
# This is also what a config that omits `data_ttl_minutes` silently gets
# (see IpsMarketEnvironment's dataclass default and resolve_data_ttl's
# ips_config=None fallback, both of which resolve here) — 15 minutes suits
# fetch-on-demand local use, but a deployment refreshed by cron needs a TTL
# exceeding its refresh interval (see config/ips.yaml, 2160 = 36h for a
# daily refresh), or every read will be STALE. A missing/unreadable
# ips.yaml on a cron-refreshed deployment hits this fallback, not a loud
# error, so it fails as silent permanent-STALE rather than a config error.
DEFAULT_DATA_TTL_MINUTES: Final[float] = 15.0

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
        ``data_ttl_minutes`` is how long a fetched value stays trustworthy —
        the CACHED/STALE boundary, and so a policy decision about how old data
        may be before it stops supporting a verdict.
        ``vix_very_high``/``vix_caution``/``vix_low`` are VIX levels (vol
        points, e.g. ``40.0``), the entry-timing tree's three stops (M2.8) —
        see :func:`~deltadewa.analysis.decision_matrix.entry_timing_tree`.
    """

    vol_regime_low: float = DEFAULT_VOL_REGIME_LOW
    vol_regime_high: float = DEFAULT_VOL_REGIME_HIGH
    skew_low_pctile: float = DEFAULT_SKEW_LOW_PCTILE
    skew_high_pctile: float = DEFAULT_SKEW_HIGH_PCTILE
    term_contango_tolerance: float = DEFAULT_TERM_CONTANGO_TOLERANCE
    data_ttl_minutes: float = DEFAULT_DATA_TTL_MINUTES
    vix_very_high: float = _DEFAULT_VIX_VERY_HIGH
    vix_caution: float = _DEFAULT_VIX_CAUTION
    vix_low: float = _DEFAULT_VIX_LOW


@dataclass(frozen=True)
class IpsBudget:
    """Premium budget for the hedge program."""

    annual_carry_pct: float


@dataclass(frozen=True)
class IpsConvexity:
    """Target convexity (hedge payoff) range under a crash scenario.

    ``crash_scenario_pct`` is the single source of truth for the crash *move*
    (a signed percent, e.g. ``-25.0``) across every panel. ``crash_vol_shock``,
    ``skew_steepening``, ``skew_reference_delta`` and ``crash_floor_reported``
    are the crash-repricing knobs co-located here (see
    ``docs/repricing-methodology.md`` §5): the flat additive volatility bump
    applied at the crash spot, an optional deep-OTM skew steepening added on top
    of that bump and capped at each leg's own ~10-delta wing (M1.6/M1.7; ``0.0``
    keeps the flat bump), the put-delta magnitude of that wing (the anchor the
    steepening is calibrated to, e.g. ``0.10``), and whether the intrinsic-floor
    column is surfaced.

    ``efficiency_min_ratio`` / ``efficiency_max_ratio`` band the hedge
    efficiency ratio (crash payoff per dollar of annual carry — see
    ``analysis.hedge_efficiency``). They live here rather than in ``budget``
    because the ratio is the convexity/carry trade-off itself, and because this
    section already carries a min/max band pair every consumer reads the same
    way.
    """

    crash_scenario_pct: float
    target_min_pct: float
    target_max_pct: float
    crash_vol_shock: float = _DEFAULT_CRASH_VOL_SHOCK
    skew_steepening: float = _DEFAULT_SKEW_STEEPENING
    skew_reference_delta: float = _DEFAULT_SKEW_REFERENCE_DELTA
    crash_floor_reported: bool = _DEFAULT_CRASH_FLOOR_REPORTED
    efficiency_min_ratio: float = _DEFAULT_EFFICIENCY_MIN_RATIO
    efficiency_max_ratio: float = _DEFAULT_EFFICIENCY_MAX_RATIO


@dataclass(frozen=True)
class IpsDrawdown:
    """Maximum tolerated portfolio drawdown."""

    max_tolerance_pct: float


@dataclass(frozen=True)
class IpsSizing:
    """Hedge-sizing policy inputs (handbook §2499 — Beta-Adjusted Sizing).

    ``portfolio_beta`` is the protected book's beta versus SPX. The hedge
    notional the sizing framework works against is
    ``book_value * portfolio_beta`` (the SPX-equivalent market exposure), so a
    beta below 1.0 sizes down the hedge and a beta above 1.0 sizes it up,
    proportionally.

    ``portfolio_beta`` is a **user input, not estimated** here: the investor
    recalculates it (handbook: at least annually, or on a >10% position change)
    and sets it in policy. SPX puts hedge only the systematic (market-beta)
    component of the book, so they **under-protect idiosyncratic risk** — a
    concentrated single-name book carries crash exposure this multiplier does
    not capture (see ``docs/implementation-plan.md``, Phase 3).
    """

    portfolio_beta: float = _DEFAULT_PORTFOLIO_BETA


@dataclass(frozen=True)
class IpsVega:
    """Vega sufficiency band — "is the book big enough to answer a vol spike".

    Handbook Part X #4. The metric is the portfolio's percentage value change
    per +10 vol points (``HealthMixin.calculate_vega_sufficiency_pct``);
    ``sufficiency_min_pct`` is the floor below which the book will barely
    respond to a volatility spike, and ``sufficiency_max_pct`` the ceiling
    above which it is vega-dominated rather than convexity-driven.

    This is policy, not presentation. "Is the hedge big enough" is a mandate
    question of the same class as the convexity band, so it lives here rather
    than in ``dashboard_config_*.yaml`` — where a copy still backs the
    Jupyter-only gauge in ``widgets/health_dashboard.py``. Retiring that copy
    is a ``widgets/`` change, not an M2.7 one.
    """

    sufficiency_min_pct: float = _DEFAULT_VEGA_SUFFICIENCY_MIN_PCT
    sufficiency_max_pct: float = _DEFAULT_VEGA_SUFFICIENCY_MAX_PCT


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
    sizing: IpsSizing = dataclass_field(default_factory=IpsSizing)
    vega: IpsVega = dataclass_field(default_factory=IpsVega)


def _require_section(config: dict[str, Any], name: str) -> dict[str, Any]:
    if name not in config or not isinstance(config[name], dict):
        raise IpsConfigError(f"ips.yaml must contain a '{name}' section")
    return dict(config[name])


def _require_field(
    section: dict[str, Any],
    section_name: str,
    field: str,
) -> Any:  # ruff: ignore[any-type]  # YAML field is polymorphic (str | int | float | bool | list | dict)
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
    skew_steepening = section.get(
        "skew_steepening",
        _DEFAULT_SKEW_STEEPENING,
    )
    _require_non_negative(skew_steepening, "convexity.skew_steepening")
    skew_reference_delta = section.get(
        "skew_reference_delta",
        _DEFAULT_SKEW_REFERENCE_DELTA,
    )
    if not 0 < skew_reference_delta < 0.5:
        raise IpsConfigError(
            "convexity.skew_reference_delta must be in (0, 0.5), got "
            f"{skew_reference_delta}",
        )
    crash_floor_reported = bool(
        section.get("crash_floor_reported", _DEFAULT_CRASH_FLOOR_REPORTED),
    )

    efficiency_min_ratio = section.get(
        "efficiency_min_ratio",
        _DEFAULT_EFFICIENCY_MIN_RATIO,
    )
    efficiency_max_ratio = section.get(
        "efficiency_max_ratio",
        _DEFAULT_EFFICIENCY_MAX_RATIO,
    )
    _require_non_negative(
        efficiency_min_ratio,
        "convexity.efficiency_min_ratio",
    )
    if efficiency_min_ratio > efficiency_max_ratio:
        raise IpsConfigError(
            "convexity.efficiency_min_ratio must be <= efficiency_max_ratio, "
            f"got {efficiency_min_ratio} > {efficiency_max_ratio}",
        )

    return IpsConvexity(
        crash_scenario_pct=crash_scenario_pct,
        target_min_pct=target_min_pct,
        target_max_pct=target_max_pct,
        crash_vol_shock=crash_vol_shock,
        skew_steepening=skew_steepening,
        skew_reference_delta=skew_reference_delta,
        crash_floor_reported=crash_floor_reported,
        efficiency_min_ratio=efficiency_min_ratio,
        efficiency_max_ratio=efficiency_max_ratio,
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
    data_ttl = section.get("data_ttl_minutes", DEFAULT_DATA_TTL_MINUTES)
    vix_very_high = section.get("vix_very_high", _DEFAULT_VIX_VERY_HIGH)
    vix_caution = section.get("vix_caution", _DEFAULT_VIX_CAUTION)
    vix_low = section.get("vix_low", _DEFAULT_VIX_LOW)

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
    if data_ttl <= 0:
        raise IpsConfigError(
            "market_environment.data_ttl_minutes must be > 0, got "
            f"{data_ttl} — a zero TTL would mark every cache hit STALE",
        )
    if not vix_low < vix_caution < vix_very_high:
        raise IpsConfigError(
            "market_environment VIX thresholds must satisfy vix_low < "
            "vix_caution < vix_very_high, got "
            f"{vix_low}, {vix_caution}, {vix_very_high}",
        )

    return IpsMarketEnvironment(
        vol_regime_low=vol_low,
        vol_regime_high=vol_high,
        skew_low_pctile=skew_low,
        skew_high_pctile=skew_high,
        term_contango_tolerance=term_tol,
        data_ttl_minutes=data_ttl,
        vix_very_high=vix_very_high,
        vix_caution=vix_caution,
        vix_low=vix_low,
    )


def _parse_sizing(config: dict[str, Any]) -> IpsSizing:
    """Parse the optional ``sizing`` policy section.

    The section is optional: a missing section (or a missing
    ``portfolio_beta``) falls back to ``_DEFAULT_PORTFOLIO_BETA`` (1.0) — the
    same value the dataclass default uses — so an older ips.yaml keeps the
    pre-beta sizing behaviour.
    """
    section = config.get("sizing", {})
    if not isinstance(section, dict):
        raise IpsConfigError("ips.yaml 'sizing' section must be a mapping")

    portfolio_beta = section.get("portfolio_beta", _DEFAULT_PORTFOLIO_BETA)
    if portfolio_beta <= 0:
        raise IpsConfigError(
            f"sizing.portfolio_beta must be > 0, got {portfolio_beta}",
        )

    return IpsSizing(portfolio_beta=portfolio_beta)


def _parse_vega(config: dict[str, Any]) -> IpsVega:
    """Parse the optional ``vega`` policy section.

    Optional, like ``sizing`` and ``market_environment``: a missing section
    (or a missing field) falls back to the ``_DEFAULT_VEGA_*`` constants, so
    every ips.yaml written before this section existed keeps loading.
    """
    section = config.get("vega", {})
    if not isinstance(section, dict):
        raise IpsConfigError("ips.yaml 'vega' section must be a mapping")

    min_pct = section.get(
        "sufficiency_min_pct",
        _DEFAULT_VEGA_SUFFICIENCY_MIN_PCT,
    )
    max_pct = section.get(
        "sufficiency_max_pct",
        _DEFAULT_VEGA_SUFFICIENCY_MAX_PCT,
    )
    if min_pct >= max_pct:
        raise IpsConfigError(
            "vega.sufficiency_min_pct must be < sufficiency_max_pct, got "
            f"{min_pct} >= {max_pct}",
        )

    return IpsVega(
        sufficiency_min_pct=min_pct,
        sufficiency_max_pct=max_pct,
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
        sizing=_parse_sizing(config),
        vega=_parse_vega(config),
    )
