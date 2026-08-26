"""Typed loader for the hedge program policy file (``ips.yaml``).

The IPS ("Investment Policy Statement") config is the single source of
truth for hedge program thresholds and the pricing-engine default exercise
style — distinct from ``dashboard_config_*.yaml``, which is
presentation-only (gauge ranges).

``dashboard_config_*.yaml`` has neither a reader nor a loader: its only
consumer was ``widgets/health_dashboard.py``, deleted in Stage 4.3 with the
notebooks, and #279 deleted the Jupyter session loader that still parsed it.
The IPS is the sole config the shipping Dash app loads.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from deltadewa.clock import DEFAULT_PROGRAM_TIMEZONE
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
# the handbook's own Interpretation of the Ratio table
# (https://qwertytam.github.io/deltadewa-handbook/0.1/part-6/hedge-efficiency-ratio/#interpretation-of-the-ratio
# — "< 3 poor / 3 to 6 acceptable / > 6 attractive"). Policy rather than
# presentation because it answers a mandate question ("is this hedge worth the
# money"), the same class as the convexity band it sits beside.
#
# The link is pinned to handbook version 0.1, not the moving root: the two
# defaults below are transcribed from that table, so the citation has to keep
# naming the table they were transcribed from. A band revised upstream should
# show up as a decision to make here, not as a comment that quietly stops
# describing the constants under it. Drop the /0.1/ segment for the current
# page.
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
# Low<->High gauge — so it has to be calibrated to the scale the metric
# actually produces.
#
# M2.7 seeded it from ``config/dashboard.yaml``'s ``vega_sufficiency`` gauge
# (``max_val: 20`` and ``end: 50``) on the assumption that the gauge's numbers
# were a band. They were not: that gauge is a *signed, symmetric* display axis
# (-50..+50, green above +20, nothing bad above it), so ``end: 50`` was an axis
# bound rather than a ceiling. The resulting 20-50 band was unreachable — the
# shipped example books price at +1.8% to +2.7%, and no denominator brings them
# near 20 (option-book-relative they are ~1200-1800%), so ``/design`` read
# "outside band" on every book in the repo (#241).
#
# These values are calibrated instead to the metric as implemented, normalizing
# by total portfolio value (options **plus** underlying): ``spx_tail_20m``, the
# canonical SPX book, reads +2.70%, and ``spx_protective_put`` +2.29%. The band
# brackets that with room either side. Still a starting point to be set
# deliberately per program, not a derived constant — but one a real book can sit
# inside.
_DEFAULT_VEGA_SUFFICIENCY_MIN_PCT: Final[float] = 1.5
_DEFAULT_VEGA_SUFFICIENCY_MAX_PCT: Final[float] = 4.0

# Convexity-cliff thresholds, in days (see ``IpsConvexity``). Seeded verbatim
# from what ``config/dashboard.yaml`` carried for the Jupyter-only gauge before
# #241 removed it — ``parameters.convexity_cliff_days: 180`` became the region
# boundary, and the ``convexity_cliff`` gauge's ``mid_val: 90`` / ``min_val:
# 30`` became the REVIEW and URGENT lines — so promoting the metric to a policy
# surface did not silently change what a reading means. Unlike the vega band
# above, those three genuinely were grading lines, so the carry-over was sound;
# "when does decaying convexity force a decision" is a mandate question, not a
# display choice.
_DEFAULT_CLIFF_THRESHOLD_DAYS: Final[int] = 180
_DEFAULT_CLIFF_REVIEW_DAYS: Final[int] = 90
_DEFAULT_CLIFF_URGENT_DAYS: Final[int] = 30

# Single source for the market-environment policy bands (see
# ``IpsMarketEnvironment``). Public because they are consumed across
# ``analysis.market_environment``, ``analysis.health``,
# and ``analysis.decision_matrix`` — no consumer
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
# exceeding its refresh interval (roughly 1.5x it — a daily refresh wants
# something past 24h), or every read will be STALE. A missing/unreadable
# ips.yaml on a cron-refreshed deployment hits this fallback, not a loud
# error, so it fails as silent permanent-STALE rather than a config error.
DEFAULT_DATA_TTL_MINUTES: Final[float] = 15.0

# How far the observed market spot may diverge from the book's hand-entered
# spot before /monitor's cross-check (analysis.spot_reading, #336) flags it.
# A display threshold, not a pricing one — nothing here feeds a calculation.
DEFAULT_SPOT_DIVERGENCE_WARN_PCT: Final[float] = 2.0

# How long a hand-entered pricing input may go unconfirmed before Batch 3d's
# provenance ledger (analysis.provenance) grades it AGING rather than FRESH.
# A review cadence, not a market fact: there is no feed to compare a
# hand-entered rate or IV against, so "stale" here means "nobody has
# re-confirmed this number in a while," and how long is acceptable
# genuinely differs by input — spot moves every session, a dividend
# assumption does not. See #367 and docs/market-data.md.
_DEFAULT_SPOT_MAX_AGE_DAYS: Final[int] = 1
_DEFAULT_VOLATILITY_MAX_AGE_DAYS: Final[int] = 7
_DEFAULT_RISK_FREE_RATE_MAX_AGE_DAYS: Final[int] = 30
_DEFAULT_DIVIDEND_YIELD_MAX_AGE_DAYS: Final[int] = 90

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False


class IpsConfigError(ValueError):
    """Raised when an ips.yaml file is missing, malformed, or out of range."""


@dataclass(frozen=True)
class IpsProgram:
    """Identifies the hedge program, its instrument, and its trading day.

    ``timezone`` is policy rather than presentation: it decides which day's
    close a position is priced against, so it changes numbers, not just
    labels. Before #182 the program's day was implicitly UTC, which rolled
    the whole book forward at 20:00 America/New_York. See ``deltadewa.clock``.
    """

    name: str
    instrument: str
    timezone: ZoneInfo = DEFAULT_PROGRAM_TIMEZONE


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
        ``spot_divergence_warn_pct`` is a percent (e.g. ``2.0`` for 2%): how
        far the observed market spot may diverge from the book's
        hand-entered spot before ``/monitor``'s cross-check flags it — see
        :func:`~deltadewa.analysis.spot_reading.observe_spot` (#336). Display
        policy only; the observed reading never feeds a calculation.
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
    spot_divergence_warn_pct: float = DEFAULT_SPOT_DIVERGENCE_WARN_PCT


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
    column is surfaced. ``crash_floor_reported`` is presentation policy and so
    stays off ``CrashShock``; ``False`` drops the floor from ``/design``'s
    sizing panel, the only live surface that reports it (#273).

    ``efficiency_min_ratio`` / ``efficiency_max_ratio`` band the hedge
    efficiency ratio (crash payoff per dollar of annual carry — see
    ``analysis.hedge_efficiency``). They live here rather than in ``budget``
    because the ratio is the convexity/carry trade-off itself, and because this
    section already carries a min/max band pair every consumer reads the same
    way.

    ``cliff_threshold_days`` / ``cliff_review_days`` / ``cliff_urgent_days``
    are the convexity-cliff policy (handbook Part X, "Time to Convexity
    Cliff"; ``HealthMixin.calculate_convexity_cliff_days``). The first is the
    *region boundary* — the remaining maturity at which a long put is treated
    as having entered the high-gamma zone where convexity decays quickly — and
    it is the value the metric is computed against. The other two band the
    resulting runway: at or below ``cliff_review_days`` the cliff is close
    enough to plan a roll, at or below ``cliff_urgent_days`` it is imminent.

    Unlike every other band in this class these are **one-sided**: more runway
    is unambiguously better, so there is no upper bound above which a reading
    turns bad. Consumers must not render them as a two-sided good-zone band.
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
    cliff_threshold_days: int = _DEFAULT_CLIFF_THRESHOLD_DAYS
    cliff_review_days: int = _DEFAULT_CLIFF_REVIEW_DAYS
    cliff_urgent_days: int = _DEFAULT_CLIFF_URGENT_DAYS


@dataclass(frozen=True)
class IpsDrawdown:
    """Maximum tolerated portfolio drawdown."""

    max_tolerance_pct: float


@dataclass(frozen=True)
class IpsSizing:
    """Hedge-sizing policy inputs.

    Handbook `Beta-Adjusted Hedge Sizing
    <https://qwertytam.github.io/deltadewa-handbook/part-7/beta-adjusted-hedge-sizing/>`_.

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

    Read the band's scale off ``_DEFAULT_VEGA_SUFFICIENCY_MIN_PCT`` before
    setting it: the metric divides by total portfolio value (options *plus*
    underlying), which on a tail hedge is dominated by the equity leg, so real
    readings are low single-digit percentages. A band in the tens cannot be hit.

    This is policy, not presentation, and since #241 it lives here **only**.
    "Is the hedge big enough" is a mandate question of the same class as the
    convexity band. ``dashboard_config_*.yaml``'s ``vega_sufficiency`` block is
    display geometry for the Jupyter gauge and never was this band — see the
    constants above for why conflating the two produced an unreachable one.
    """

    sufficiency_min_pct: float = _DEFAULT_VEGA_SUFFICIENCY_MIN_PCT
    sufficiency_max_pct: float = _DEFAULT_VEGA_SUFFICIENCY_MAX_PCT


@dataclass(frozen=True)
class IpsPricingInputs:
    """Review-cadence policy for hand-entered pricing inputs.

    The four inputs a book is actually priced on that the program never
    fetches — per-leg implied volatility, spot, the risk-free rate, and
    the dividend yield (#367) — have no ``as_of`` unless a human confirms
    one at entry, and no feed to grade staleness against. So "stale" here
    is a maximum unconfirmed age, in days, one per input class because
    the honest review cadence genuinely differs: spot should be re-eyed
    every session, a dividend-yield assumption not nearly as often.

    Each field is compared against ``clock.days_between(as_of, stamp)``,
    never wall-clock subtraction, per ``deltadewa/clock.py``'s rule.
    ``analysis.provenance.build_provenance_ledger`` is the only consumer.
    """

    spot_max_age_days: int = _DEFAULT_SPOT_MAX_AGE_DAYS
    volatility_max_age_days: int = _DEFAULT_VOLATILITY_MAX_AGE_DAYS
    risk_free_rate_max_age_days: int = _DEFAULT_RISK_FREE_RATE_MAX_AGE_DAYS
    dividend_yield_max_age_days: int = _DEFAULT_DIVIDEND_YIELD_MAX_AGE_DAYS


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

    ``roll_time_months`` is maturity **remaining**, never time elapsed since
    entry: the roll fires once an option has this many months left to run, so
    a smaller value rolls later in its life. The name alone does not say which
    referent is meant, and the two are not interchangeable — an 18-month put
    rolled on the elapsed reading lands in the 6-9 month theta-acceleration
    zone the handbook warns against. Consumers agree with this reading:
    ``roll_status.evaluate_roll_status`` compares ``days_to_maturity``, which
    ``clock.days_between`` computes as ``maturity_date - as_of``. See the
    handbook's `Typical Hedge Program Targets
    <https://qwertytam.github.io/deltadewa-handbook/0.1/part-7/typical-hedge-program-targets/>`_,
    which owns the roll-interval band. That link is pinned to handbook version
    0.1 because the paragraph above depends on the handbook stating the band
    as maturity *remaining*: this field's meaning was settled against that
    wording, and the referent flipping upstream is precisely the failure the
    paragraph exists to prevent. Drop the ``/0.1/`` segment for the current
    band.
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
    pricing_inputs: IpsPricingInputs = dataclass_field(
        default_factory=IpsPricingInputs,
    )
    # #309: which of the optional sections above (market_environment,
    # sizing, vega, pricing_inputs) were absent from the loaded ips.yaml
    # and are running on their DEFAULT_* module constants instead of the
    # operator's own numbers. Populated once, in load_ips_config, from the
    # raw parsed YAML — never recomputed from this object's own field
    # values, since a field that happens to equal its default (an
    # operator who typed the same number back in) is not the same
    # condition as a section that was never written at all.
    defaulted_sections: frozenset[str] = dataclass_field(
        default_factory=frozenset,
    )


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
    raw_tz = section.get("timezone")
    if raw_tz is None:
        timezone = DEFAULT_PROGRAM_TIMEZONE
    else:
        try:
            timezone = ZoneInfo(str(raw_tz))
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise IpsConfigError(
                f"program.timezone must be an IANA timezone name (e.g. "
                f"'America/New_York'), got '{raw_tz}'",
            ) from exc
    return IpsProgram(
        name=_require_field(section, "program", "name"),
        instrument=_require_field(section, "program", "instrument"),
        timezone=timezone,
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

    cliff_threshold_days = int(
        section.get("cliff_threshold_days", _DEFAULT_CLIFF_THRESHOLD_DAYS),
    )
    cliff_review_days = int(
        section.get("cliff_review_days", _DEFAULT_CLIFF_REVIEW_DAYS),
    )
    cliff_urgent_days = int(
        section.get("cliff_urgent_days", _DEFAULT_CLIFF_URGENT_DAYS),
    )
    _require_non_negative(
        cliff_threshold_days, "convexity.cliff_threshold_days"
    )
    _require_non_negative(cliff_review_days, "convexity.cliff_review_days")
    _require_non_negative(cliff_urgent_days, "convexity.cliff_urgent_days")
    if cliff_urgent_days > cliff_review_days:
        raise IpsConfigError(
            "convexity.cliff_urgent_days must be <= cliff_review_days, got "
            f"{cliff_urgent_days} > {cliff_review_days}",
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
        cliff_threshold_days=cliff_threshold_days,
        cliff_review_days=cliff_review_days,
        cliff_urgent_days=cliff_urgent_days,
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
    spot_divergence_warn_pct = section.get(
        "spot_divergence_warn_pct",
        DEFAULT_SPOT_DIVERGENCE_WARN_PCT,
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
    _require_non_negative(
        spot_divergence_warn_pct,
        "market_environment.spot_divergence_warn_pct",
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
        spot_divergence_warn_pct=spot_divergence_warn_pct,
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


def _parse_pricing_inputs(config: dict[str, Any]) -> IpsPricingInputs:
    """Parse the optional ``pricing_inputs`` policy section.

    Optional, like ``sizing`` and ``vega``: a missing section (or a
    missing field) falls back to the ``_DEFAULT_*_MAX_AGE_DAYS``
    constants, so an ips.yaml written before #367 keeps loading — with
    every hand-entered input graded against the same review cadence a
    freshly written one gets.
    """
    section = config.get("pricing_inputs", {})
    if not isinstance(section, dict):
        raise IpsConfigError(
            "ips.yaml 'pricing_inputs' section must be a mapping",
        )

    fields = {
        "spot_max_age_days": _DEFAULT_SPOT_MAX_AGE_DAYS,
        "volatility_max_age_days": _DEFAULT_VOLATILITY_MAX_AGE_DAYS,
        "risk_free_rate_max_age_days": (_DEFAULT_RISK_FREE_RATE_MAX_AGE_DAYS),
        "dividend_yield_max_age_days": (_DEFAULT_DIVIDEND_YIELD_MAX_AGE_DAYS),
    }
    resolved: dict[str, int] = {}
    for name, default in fields.items():
        value = section.get(name, default)
        if value <= 0:
            raise IpsConfigError(
                f"pricing_inputs.{name} must be > 0, got {value}",
            )
        resolved[name] = value

    return IpsPricingInputs(**resolved)


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


def load_ips_config(path: str | Path) -> IpsConfig:
    """Load and validate a hedge program policy file into an ``IpsConfig``.

    Args:
        path: Path to the ``ips.yaml`` file. A ``str`` is accepted and
            normalized to a ``Path`` on entry — the annotation states what
            the function takes rather than leaving a ``str`` caller to
            discover ``AttributeError: 'str' object has no attribute
            'exists'`` at the first filesystem call (#182). This matches
            ``PortfolioSerializer``'s loaders, which already accept both.

    Returns:
        Fully validated ``IpsConfig``.

    Raises:
        IpsConfigError: If the file is missing, the YAML is malformed, a
            required field is missing, or any value fails validation.

    """
    if not YAML_AVAILABLE:
        raise IpsConfigError("PyYAML is not installed; cannot load ips.yaml")

    # Normalized once, at the boundary, so every use below — including the
    # error messages, which name the file — sees the same Path.
    path = Path(path)

    if not path.exists():
        raise IpsConfigError(
            f"ips.yaml not found at {path} — this file holds your program's "
            "real policy and is gitignored (#245), so it's never shipped. "
            "Copy config/ips.example.yaml to "
            f"{path} and fill in your own program's values.",
        )

    try:
        with Path.open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise IpsConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(config, dict):
        raise IpsConfigError("ips.yaml root must be a mapping/object")

    # #309: computed from the raw YAML's own top-level keys, not from
    # comparing parsed values to defaults — see IpsConfig.defaulted_sections.
    defaulted_sections = frozenset(
        name
        for name in (
            "market_environment",
            "sizing",
            "vega",
            "pricing_inputs",
        )
        if name not in config
    )

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
        pricing_inputs=_parse_pricing_inputs(config),
        defaulted_sections=defaulted_sections,
    )
