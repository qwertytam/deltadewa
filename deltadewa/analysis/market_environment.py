"""Classify live market data into a hedge-cost market environment.

Turns ``MarketDataProvider`` readings (VIX, VIX term structure, SKEW) into
a single ``MarketEnvironment`` snapshot for `Tier-2
<https://qwertytam.github.io/deltadewa-handbook/part-10/tier-2-market-environment-metrics/>`_
of the hedging handbook -- "is crash protection cheap or expensive right
now?" The future C3
decision matrix in ``analysis.recommendations`` consumes this snapshot
rather than raw provider calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from deltadewa.formatters.values import format_ordinal_percentile
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
class SeriesProvenance:
    """One of the four series ``assess_market_environment`` fetches.

    Batch 3d / #368: kept so a consumer can tell "one series is on its
    normal, expected schedule (VIX's routine FRED lag)" apart from "the
    whole pipeline stopped" — a distinction the single combined
    ``MarketEnvironment.as_of``/``data_quality`` cannot make on its own,
    which was the field-test confusion #368 reported.
    """

    name: str
    quality: DataQuality
    as_of: datetime | None
    fetched_at: datetime | None


@dataclass(frozen=True)
class MarketEnvironment:
    """A point-in-time classification of market conditions.

    All fields except ``data_quality`` are ``None`` when ``data_quality``
    is ``DataQuality.UNAVAILABLE``.

    Attributes:
        vix: Current VIX level, in vol points (e.g. 18.0 for 18%).
        regime_band_position_pct: Where VIX sits inside the IPS
            ``vol_regime_low``-``vol_regime_high`` band, 0-100 and clamped
            at both ends, from ``classify_vix_regime``. **Not a
            percentile** — no history is ranked; it is ``0`` for every VIX
            at or below the band floor. Renamed from ``regime_percentile``
            (8c, N5): the old name, rendered on ``/design`` as "regime
            percentile 53" on a day VIX ranked 95th over the trailing
            year, was #175's mislabel on a path #175's fix never reached
            (``health.compute_vol_regime`` is the true-rank figure).
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
            this snapshot, or ``UNAVAILABLE`` if the provider failed. This
            combination rule is deliberately conservative and does **not**
            change with #368 — see ``series``/``oldest_series`` below for
            the resolution #368 adds instead of loosening it.
        as_of: Observation date of the *oldest* reading in the snapshot — what
            a stale-data banner must display. ``None`` when ``data_quality``
            is ``STATIC`` or ``UNAVAILABLE``, neither of which has one.
        series: Per-series provenance for each of the four fetched
            readings (#368) — what let a 2026-08-25 field test tell "VIX's
            normal FRED lag" apart from "the pipeline stopped" once this
            was surfaced on ``/health``. Empty when ``data_quality`` is
            ``UNAVAILABLE`` (nothing was successfully read at all).
        fetched_at: When this process last retrieved the *oldest-observed*
            series — i.e. the same combined reading ``as_of`` describes,
            but the retrieval instant rather than the source's own
            observation date. A banner showing both together (#368) can
            distinguish "the data itself is old" from "the pipeline
            hasn't run since it fetched this old-but-expected reading."
            ``None`` under the same conditions as ``as_of``.
        oldest_series: Name of the series ``as_of`` was taken from (one of
            ``series``' names), or ``None`` when ``data_quality`` is
            ``STATIC`` or ``UNAVAILABLE`` (neither has a meaningful
            "oldest" among synthetic/absent timestamps).
        skew_lookback_days: The trading-session window ``skew_percentile``
            was ranked over (``IpsMarketEnvironment.skew_lookback_days``,
            #317), carried so every surface quoting the percentile can
            state its window — the handbook's condition for any window
            (see :func:`describe_lookback`). ``None`` when
            ``data_quality`` is ``UNAVAILABLE``.

    """

    vix: float | None
    regime_band_position_pct: float | None
    regime_label: RegimeLabel | None
    skew_index: float | None
    skew_percentile: float | None
    term_structure: dict[str, float] | None
    term_shape: TermShape | None
    forward_vol_front_3m: float | None
    hedge_cost_verdict: HedgeCostVerdict | None
    data_quality: DataQuality
    as_of: datetime | None
    # #368: new, defaulted fields, kept last so every existing call site
    # that builds a MarketEnvironment positionally or by keyword still
    # constructs correctly.
    series: tuple[SeriesProvenance, ...] = ()
    fetched_at: datetime | None = None
    oldest_series: str | None = None
    skew_lookback_days: int | None = None


_VIX_LABEL_LOW_PCT: Final[float] = 25.0
_VIX_LABEL_HIGH_PCT: Final[float] = 75.0
_VIX_TENOR_YEARS: Final[float] = 1 / 12
_VIX3M_TENOR_YEARS: Final[float] = 3 / 12
# A calendar convention (the count every 252-session "year" in this codebase
# already assumes), not policy: it only turns a session count into words.
_SESSIONS_PER_YEAR: Final[int] = 252


def describe_lookback(sessions: int) -> str:
    """Name a percentile rank window for a reader, e.g. ``"trailing 5y"``.

    The handbook lets a program rank skew over any window "provided it
    states the window every time it quotes a percentile"
    (`The Lookback Window
    <https://qwertytam.github.io/deltadewa-handbook/part-3/volatility-skew/#the-lookback-window>`_),
    so every surface rendering ``MarketEnvironment.skew_percentile``
    renders this beside it. Whole years read as years; anything else
    reads as a session count rather than a rounded, misleading year.

    Args:
        sessions: The window in trading sessions.

    Returns:
        ``"trailing Ny"`` for a whole number of 252-session years,
        otherwise ``"trailing N sessions"``.

    """
    years, remainder = divmod(sessions, _SESSIONS_PER_YEAR)
    if remainder == 0 and years > 0:
        return f"trailing {years}y"
    return f"trailing {sessions} sessions"


def describe_skew_percentile(
    fraction: float,
    lookback_days: int | None,
) -> str:
    """Render a skew percentile with the window it was ranked over.

    E.g. ``"88th percentile (trailing 5y)"``. The one formatter every
    surface quoting a skew percentile uses — the ``/design`` skew row,
    the entry-timing step, and the program report —
    so the handbook's "state the window every time" condition (#317) is
    met by construction and the surfaces cannot disagree on rounding.

    Args:
        fraction: The percentile as a 0-1 fraction.
        lookback_days: The window it was ranked over, in sessions.
            ``None`` only for a reading whose window was never recorded,
            which is then said rather than guessed.

    Returns:
        The ordinal percentile with its window in parentheses.

    """
    window = (
        describe_lookback(lookback_days)
        if lookback_days is not None
        else "window not recorded"
    )
    return f"{format_ordinal_percentile(fraction)} percentile ({window})"


def _interpolate_band_position(value: float, low: float, high: float) -> float:
    """Linear-interpolate *value* between *low* and *high* into 0-100.

    A position inside the band, not a percentile — see
    ``classify_vix_regime``.

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
    """Classify a VIX level by its position inside the IPS band, plus a label.

    Linear interpolation of VIX between the IPS *low*/*high* band, clamped
    to 0-100 — a **band position**, not a percentile: nothing is ranked
    against history (8c, N5; the same mislabel #175 fixed for
    ``health.compute_vol_regime``, which does rank against VIX history).
    *vix* is in vol points (e.g. 18.0 for 18%) and is converted to
    decimal before comparing against the decimal *low*/*high* band.

    The label cuts the band position at 25/75 -- the breakpoints the retired
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
        Tuple of (regime_band_position_pct, regime_label).

    """
    band_position = _interpolate_band_position(vix / 100, low, high)
    label = _classify_band(
        band_position,
        _VIX_LABEL_LOW_PCT,
        _VIX_LABEL_HIGH_PCT,
    )
    return band_position, label


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


def _oldest_series_name(
    named_observations: tuple[tuple[str, Observation[Any]], ...],
) -> str | None:
    """Return the name of the series with the earliest ``as_of``.

    ``None`` if every observation's ``as_of`` is ``None`` — cannot occur
    for the non-``STATIC`` case ``assess_market_environment`` calls this
    from, but there is no honest name to return if it somehow did.
    """
    dated = [
        (name, obs.as_of)
        for name, obs in named_observations
        if obs.as_of is not None
    ]
    if not dated:
        return None
    return min(dated, key=lambda pair: pair[1])[0]


def assess_market_environment(
    provider: MarketDataProvider,
    env_policy: IpsMarketEnvironment | None = None,
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
            ``get_skew_percentile`` returns once, here at the edge. The
            skew percentile is ranked over its ``skew_lookback_days``
            (#317) — policy, read here and nowhere else, and recorded on
            the returned snapshot so every surface can state the window
            it quotes.

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
    skew_lookback_days = policy.skew_lookback_days
    try:
        vix_obs = provider.get_vix()
        term_obs = provider.get_vix_term_structure()
        skew_index_obs = provider.get_skew_index()
        skew_pctile_obs = provider.get_skew_percentile(skew_lookback_days)
    except MarketDataError:
        return MarketEnvironment(
            vix=None,
            regime_band_position_pct=None,
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

    regime_band_position_pct, regime_label = classify_vix_regime(
        vix, *regime_bands
    )
    skew_label = _classify_band(skew_percentile, *skew_bands)
    term_shape = term_structure_shape(term, term_tolerance)

    # The snapshot is only as trustworthy — and only as fresh — as its
    # weakest input, so combine the four readings rather than asking the
    # provider what kind of provider it is. This combination rule stays
    # exactly as conservative as before (#368 does not loosen it) — what
    # #368 adds is keeping the per-series breakdown below instead of
    # discarding it once combined, so a consumer can tell "one series is
    # on its normal, expected lag" apart from "the whole pipeline
    # stopped."
    named_observations = (
        ("vix", vix_obs),
        ("vix_term_structure", term_obs),
        ("skew_index", skew_index_obs),
        ("skew_percentile", skew_pctile_obs),
    )
    provenance = Observation.combine(
        None,
        (obs for _, obs in named_observations),
    )
    series = tuple(
        SeriesProvenance(
            name=name,
            quality=_SOURCE_TO_QUALITY[obs.source],
            as_of=obs.as_of,
            fetched_at=obs.fetched_at,
        )
        for name, obs in named_observations
    )
    # A single STATIC part collapses combine() straight to
    # Observation.static(), whose as_of/fetched_at are both None — there
    # is no honest "oldest" to name among synthetic/absent timestamps.
    oldest_series = (
        _oldest_series_name(named_observations)
        if provenance.source is not Source.STATIC
        else None
    )

    return MarketEnvironment(
        vix=vix,
        regime_band_position_pct=regime_band_position_pct,
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
        series=series,
        fetched_at=provenance.fetched_at,
        oldest_series=oldest_series,
        skew_lookback_days=skew_lookback_days,
    )
