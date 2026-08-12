"""Classify live market data into a hedge-cost market environment.

Turns ``MarketDataProvider`` readings (VIX, VIX term structure, SKEW) into
a single ``MarketEnvironment`` snapshot for Tier-2 of the hedging handbook
-- "is crash protection cheap or expensive right now?" The future C3
decision matrix in ``analysis.recommendations`` consumes this snapshot
rather than raw provider calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from deltadewa.ips_config import (
    DEFAULT_VOL_REGIME_HIGH,
    DEFAULT_VOL_REGIME_LOW,
    IpsMarketEnvironment,
)
from deltadewa.marketdata._errors import MarketDataError
from deltadewa.marketdata._observation import Observation, Source

if TYPE_CHECKING:
    from datetime import datetime

    from deltadewa.marketdata._protocols import MarketDataProvider


class RegimeLabel(StrEnum):
    """Classification of a percentile into a low/normal/high regime."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class TermShape(StrEnum):
    """Shape of the VIX term structure curve."""

    CONTANGO = "CONTANGO"
    FLAT = "FLAT"
    BACKWARDATION = "BACKWARDATION"


class HedgeCostVerdict(StrEnum):
    """Overall read on whether crash protection is cheap or expensive."""

    CHEAP = "CHEAP"
    FAIR = "FAIR"
    EXPENSIVE = "EXPENSIVE"


class DataQuality(StrEnum):
    """Data quality level of a ``MarketEnvironment``.

    Derived from the ``Source`` of the observations that went into the
    reading — what the fetches actually did — never from the provider's type.
    """

    LIVE = "LIVE"
    """Every reading was fetched over the network on this call."""
    CACHED = "CACHED"
    """At worst, a reading came from the disk cache within its TTL."""
    STALE = "STALE"
    """A reading came from the cache past its TTL, the live fetch failing."""
    STATIC = "STATIC"
    """A reading was synthetic/hardcoded (e.g. ``StaticProvider``)."""
    UNAVAILABLE = "UNAVAILABLE"
    """Provider failed; all environment fields are ``None``."""


_SOURCE_TO_QUALITY: Final[dict[Source, DataQuality]] = {
    Source.LIVE: DataQuality.LIVE,
    Source.CACHED: DataQuality.CACHED,
    Source.STALE: DataQuality.STALE,
    Source.STATIC: DataQuality.STATIC,
}


@dataclass(frozen=True)
class MarketEnvironment:
    """A point-in-time classification of market conditions.

    All fields except ``data_quality`` are ``None`` when ``data_quality``
    is ``DataQuality.UNAVAILABLE``.

    Attributes:
        vix: Current VIX level, in vol points (e.g. 18.0 for 18%).
        regime_percentile: VIX regime percentile (0-100), from
            ``classify_vix_regime``.
        regime_label: VIX regime label, from ``classify_vix_regime``.
        skew_index: Current CBOE SKEW index level.
        skew_percentile: SKEW index's percentile rank, as a 0-1 fraction
            (the same units as ``MarketDataProvider.get_skew_percentile``).
        term_structure: VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels keyed by name.
        term_shape: Shape of the VIX term structure, from
            ``term_structure_shape``.
        forward_vol_front_3m: Implied forward vol between the front (VIX)
            and 3M tenors, in vol points. ``None`` if unavailable.
        hedge_cost_verdict: Overall cheap/fair/expensive read.
        data_quality: The weakest ``Source`` among the readings that went into
            this snapshot, or ``UNAVAILABLE`` if the provider failed.
        as_of: Observation date of the *oldest* reading in the snapshot — what
            a stale-data banner must display. ``None`` when ``data_quality``
            is ``STATIC`` or ``UNAVAILABLE``, neither of which has one.

    """

    vix: float | None
    regime_percentile: float | None
    regime_label: RegimeLabel | None
    skew_index: float | None
    skew_percentile: float | None
    term_structure: dict[str, float] | None
    term_shape: TermShape | None
    forward_vol_front_3m: float | None
    hedge_cost_verdict: HedgeCostVerdict | None
    data_quality: DataQuality
    as_of: datetime | None


_VIX_LABEL_LOW_PCT: Final[float] = 25.0
_VIX_LABEL_HIGH_PCT: Final[float] = 75.0
_VIX_TENOR_YEARS: Final[float] = 1 / 12
_VIX3M_TENOR_YEARS: Final[float] = 3 / 12


def _interpolate_percentile(value: float, low: float, high: float) -> float:
    """Linear-interpolate *value* between *low* and *high* into 0-100.

    Same approach as ``HealthMixin.calculate_vol_regime_percentile``:
    0 = at/below low, 100 = at/above high, linear in between.
    """
    if value <= low:
        return 0.0
    if value >= high:
        return 100.0
    return (value - low) / (high - low) * 100


def _classify_band(value: float, low: float, high: float) -> RegimeLabel:
    """Classify *value* as LOW/NORMAL/HIGH against a low/high band."""
    if value < low:
        return RegimeLabel.LOW
    if value > high:
        return RegimeLabel.HIGH
    return RegimeLabel.NORMAL


def classify_vix_regime(
    vix: float,
    low: float = DEFAULT_VOL_REGIME_LOW,
    high: float = DEFAULT_VOL_REGIME_HIGH,
) -> tuple[float, RegimeLabel]:
    """Classify a VIX level into a regime percentile and label.

    Uses the same linear-interpolation approach as
    ``HealthMixin.calculate_vol_regime_percentile``, applied to VIX
    instead of portfolio volatility. *vix* is in vol points (e.g. 18.0
    for 18%) and is converted to decimal before comparing against the
    decimal *low*/*high* band.

    The label cuts at percentile 25/75 -- the breakpoints the retired
    ``config/dashboard.yaml`` ``vol_regime`` gauge used (``min_val: 25``
    green/cheap, ``max_val: 75`` red/expensive), carried forward so the
    label keeps the meaning that gauge established (#279).

    Args:
        vix: Current VIX level, in vol points.
        low: Historical low VIX, decimal. Defaults to the IPS single source
            :data:`~deltadewa.ips_config.DEFAULT_VOL_REGIME_LOW`.
        high: Historical high VIX, decimal. Defaults to
            :data:`~deltadewa.ips_config.DEFAULT_VOL_REGIME_HIGH`.

    Returns:
        Tuple of (regime_percentile, regime_label).

    """
    percentile = _interpolate_percentile(vix / 100, low, high)
    label = _classify_band(
        percentile,
        _VIX_LABEL_LOW_PCT,
        _VIX_LABEL_HIGH_PCT,
    )
    return percentile, label


def term_structure_shape(
    term: dict[str, float],
    tolerance: float = 0.5,
) -> TermShape:
    """Classify the VIX term structure's shape.

    ``BACKWARDATION`` when the front (VIX) trades more than *tolerance*
    above VIX3M (a stress signal on its own). ``CONTANGO`` when VIX is
    below VIX3M, and VIX3M is not meaningfully below VIX6M, both beyond
    *tolerance* (a calm, upward-sloping curve). Otherwise ``FLAT`` --
    covers tiny/noisy differences and ambiguous shapes.

    Args:
        term: VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels keyed by name, as
            returned by ``MarketDataProvider.get_vix_term_structure``.
        tolerance: Vol-point tolerance below which a difference reads
            as noise rather than a real slope (default 0.5).

    Returns:
        The term structure's classified shape.

    """
    front = term["VIX"]
    three_m = term["VIX3M"]
    six_m = term["VIX6M"]

    if front - three_m > tolerance:
        return TermShape.BACKWARDATION
    if three_m - front > tolerance and six_m - three_m > -tolerance:
        return TermShape.CONTANGO
    return TermShape.FLAT


def forward_vol(term: dict[str, float]) -> float | None:
    """Implied forward vol between the front (VIX) and 3M tenors.

    forward_var = (s2^2*t2 - s1^2*t1) / (t2 - t1), with s1/s2 the
    decimal VIX/VIX3M levels and t1/t2 their tenors in years (1/12 and
    3/12). Returns sqrt(max(forward_var, 0)), rescaled back to vol
    points to match *term*'s own units.

    Args:
        term: VIX9D/VIX/VIX3M/VIX6M/VIX1Y levels keyed by name.

    Returns:
        Forward vol in vol points, or ``None`` if VIX or VIX3M is
        missing from *term*.

    """
    if "VIX" not in term or "VIX3M" not in term:
        return None

    s1 = term["VIX"] / 100
    s2 = term["VIX3M"] / 100
    forward_var = (s2**2 * _VIX3M_TENOR_YEARS - s1**2 * _VIX_TENOR_YEARS) / (
        _VIX3M_TENOR_YEARS - _VIX_TENOR_YEARS
    )
    return math.sqrt(max(forward_var, 0.0)) * 100


def _hedge_cost_verdict(
    vix_label: RegimeLabel,
    skew_label: RegimeLabel,
    term_shape: TermShape,
) -> HedgeCostVerdict:
    """Combine VIX/skew labels and term shape into an overall verdict."""
    if (
        vix_label is RegimeLabel.LOW
        and skew_label is RegimeLabel.LOW
        and term_shape is TermShape.CONTANGO
    ):
        return HedgeCostVerdict.CHEAP
    if (
        vix_label is RegimeLabel.HIGH
        and skew_label is RegimeLabel.HIGH
        and term_shape is TermShape.BACKWARDATION
    ):
        return HedgeCostVerdict.EXPENSIVE
    return HedgeCostVerdict.FAIR


def assess_market_environment(
    provider: MarketDataProvider,
    env_policy: IpsMarketEnvironment | None = None,
    *,
    skew_lookback_days: int = 252,
) -> MarketEnvironment:
    """Assess current market conditions from a ``MarketDataProvider``.

    Pulls VIX, the VIX term structure, and SKEW from *provider* and
    classifies them against the IPS market-environment policy bands (the
    single source of the hedge-cost thresholds — never presentation config).
    Never raises: if any provider call raises ``MarketDataError``, returns a
    ``MarketEnvironment`` with every field ``None`` except
    ``data_quality=DataQuality.UNAVAILABLE``.

    Args:
        provider: Source of VIX/SKEW market data.
        env_policy: The IPS market-environment policy bands
            (``ips_config.market_environment``). ``None`` uses the
            ``IpsMarketEnvironment`` defaults (the ``DEFAULT_*`` single source).
            The skew percentile band is converted to the 0-1 fraction
            ``get_skew_percentile`` returns once, here at the edge.
        skew_lookback_days: Lookback window passed to
            ``get_skew_percentile`` (default 252).

    Returns:
        A fully classified ``MarketEnvironment``, or a degraded one with
        ``data_quality=UNAVAILABLE`` on any provider failure.

    """
    policy = env_policy if env_policy is not None else IpsMarketEnvironment()
    regime_bands = (policy.vol_regime_low, policy.vol_regime_high)
    # Skew band is policy in percentiles (0-100); convert to the 0-1 fraction
    # ``get_skew_percentile`` returns, once, here at the edge.
    skew_bands = (
        policy.skew_low_pctile / 100.0,
        policy.skew_high_pctile / 100.0,
    )
    term_tolerance = policy.term_contango_tolerance
    try:
        vix_obs = provider.get_vix()
        term_obs = provider.get_vix_term_structure()
        skew_index_obs = provider.get_skew_index()
        skew_pctile_obs = provider.get_skew_percentile(skew_lookback_days)
    except MarketDataError:
        return MarketEnvironment(
            vix=None,
            regime_percentile=None,
            regime_label=None,
            skew_index=None,
            skew_percentile=None,
            term_structure=None,
            term_shape=None,
            forward_vol_front_3m=None,
            hedge_cost_verdict=None,
            data_quality=DataQuality.UNAVAILABLE,
            as_of=None,
        )

    vix = vix_obs.value
    term = term_obs.value
    skew_percentile = skew_pctile_obs.value

    regime_percentile, regime_label = classify_vix_regime(vix, *regime_bands)
    skew_label = _classify_band(skew_percentile, *skew_bands)
    term_shape = term_structure_shape(term, term_tolerance)

    # The snapshot is only as trustworthy — and only as fresh — as its
    # weakest input, so combine the four readings rather than asking the
    # provider what kind of provider it is.
    provenance = Observation.combine(
        None,
        (vix_obs, term_obs, skew_index_obs, skew_pctile_obs),
    )

    return MarketEnvironment(
        vix=vix,
        regime_percentile=regime_percentile,
        regime_label=regime_label,
        skew_index=skew_index_obs.value,
        skew_percentile=skew_percentile,
        term_structure=term,
        term_shape=term_shape,
        forward_vol_front_3m=forward_vol(term),
        hedge_cost_verdict=_hedge_cost_verdict(
            regime_label,
            skew_label,
            term_shape,
        ),
        data_quality=_SOURCE_TO_QUALITY[provenance.source],
        as_of=provenance.as_of,
    )
