"""Health metrics mixin for portfolio analysis."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from deltadewa import constants as const
from deltadewa.analysis.crash_repricing import CrashShock, crash_convexity_pct
from deltadewa.ips_config import (
    DEFAULT_VOL_REGIME_HIGH,
    DEFAULT_VOL_REGIME_LOW,
    IpsConvexity,
)

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio

# Vol-regime rank window. The normalization band (decimal implied vol) is
# single-sourced from the IPS — ``ips_config.DEFAULT_VOL_REGIME_LOW`` /
# ``DEFAULT_VOL_REGIME_HIGH`` (surfaced on ``IpsMarketEnvironment``). No band
# literal lives here; callers pass the policy value in.
VOL_REGIME_LOOKBACK_DAYS: Final[int] = 252

# Returned by ``calculate_convexity_cliff_days`` when the book holds no long
# puts, i.e. there is no convexity to decay and the metric does not apply. Named
# so consumers test for "not applicable" instead of comparing against a literal;
# it is a sentinel, not a runway of 999 days, and must never be rendered as one.
NO_LONG_PUTS_CLIFF_DAYS: Final[int] = 999


class VolRegimeBasis(StrEnum):
    """How a vol-regime figure was derived.

    Distinguishes an honest percentile from the min-max fallback so no caller
    can present a normalized number as a percentile it never computed.
    """

    PERCENTILE = "percentile"
    """True rank of current vol against a VIX history distribution."""
    NORMALIZED = "normalized"
    """Min-max normalization between the historical band — NOT a percentile."""


@dataclass(frozen=True)
class VolRegime:
    """A vol-regime reading and the basis it was computed on.

    Attributes:
        value: Regime figure on a 0-100 scale (0 = cheap, 100 = expensive).
        basis: Whether ``value`` is a true percentile or a normalized figure.
        lookback_days: Rank window in trading days when
            ``basis is VolRegimeBasis.PERCENTILE``; ``None`` for the normalized
            fallback (a normalized figure has no lookback).
        sample_size: Number of historical observations ranked against when
            ``basis is VolRegimeBasis.PERCENTILE``; ``None`` otherwise.

    """

    value: float
    basis: VolRegimeBasis
    lookback_days: int | None
    sample_size: int | None


def _normalized_vol_regime(
    current_vol: float,
    low: float,
    high: float,
) -> float:
    """Min-max normalize *current_vol* into 0-100 between *low* and *high*.

    This is the legacy figure: linear interpolation between a hardcoded band,
    clamped to [0, 100]. It is NOT a percentile — it is only ever returned
    labelled ``VolRegimeBasis.NORMALIZED``.
    """
    if current_vol <= low:
        return 0.0
    if current_vol >= high:
        return 100.0
    return (current_vol - low) / (high - low) * 100.0


def compute_vol_regime(
    current_vol: float,
    *,
    vix_history: Sequence[float] | None,
    normalized_low: float = DEFAULT_VOL_REGIME_LOW,
    normalized_high: float = DEFAULT_VOL_REGIME_HIGH,
    lookback_days: int = VOL_REGIME_LOOKBACK_DAYS,
) -> VolRegime:
    """Rank *current_vol* against VIX history, or normalize honestly.

    When *vix_history* is non-empty, computes a **true** percentile: the
    fraction of the last *lookback_days* VIX closes at or below *current_vol*,
    scaled to 0-100 (inclusive ``<=`` rank, the same convention as
    ``MarketDataProvider.get_skew_percentile``). When it is ``None`` or empty
    — the offline/no-history case — falls back to min-max normalization
    between *normalized_low*/*normalized_high* and labels it
    ``VolRegimeBasis.NORMALIZED`` so it is never mistaken for a percentile.

    Args:
        current_vol: Current implied volatility as a decimal (e.g. ``0.20``).
        vix_history: Historical VIX closes in **vol points** (e.g. ``20.0``),
            as returned by ``MarketDataProvider.get_vix_history``. ``None`` or
            empty selects the normalized fallback.
        normalized_low: Historical low vol (decimal) for the fallback.
        normalized_high: Historical high vol (decimal) for the fallback.
        lookback_days: Number of trailing observations to rank against.

    Returns:
        A ``VolRegime`` carrying the figure and its basis.

    """
    if vix_history:
        # VIX history is in points; convert to decimal to match current_vol.
        window = [level / 100.0 for level in list(vix_history)[-lookback_days:]]
        at_or_below = sum(1 for level in window if level <= current_vol)
        percentile = at_or_below / len(window) * 100.0
        return VolRegime(
            value=percentile,
            basis=VolRegimeBasis.PERCENTILE,
            lookback_days=lookback_days,
            sample_size=len(window),
        )
    normalized = _normalized_vol_regime(
        current_vol,
        normalized_low,
        normalized_high,
    )
    return VolRegime(
        value=normalized,
        basis=VolRegimeBasis.NORMALIZED,
        lookback_days=None,
        sample_size=None,
    )


def delta_drift_from_target(
    net_delta: float,
    underlying_qty: float,
    target_delta_ratio_pct: float,
) -> float | None:
    """Delta drift as signed deviation from a target net-delta ratio.

    A tail-hedged book is deliberately net long, so drift is measured against a
    stated ``target_delta_ratio_pct`` (the intended net-delta-to-equity ratio,
    e.g. ``90.0``) rather than against full delta-neutrality. This is the single
    definition shared by the health gauge
    (:meth:`HealthMixin.calculate_delta_drift_pct`) and the delta trigger
    (``hedge_triggers.evaluate_hedge_triggers``).

    Args:
        net_delta: Net portfolio delta (options + underlying).
        underlying_qty: Equity/underlying quantity being hedged.
        target_delta_ratio_pct: Intended net-delta-to-equity ratio, as a percent
            (single-sourced from ``IpsTriggers.target_delta_ratio_pct``).

    Returns:
        Signed deviation from target in percentage points (0 = at target,
        positive = under-hedged / more net long, negative = over-hedged), or
        ``None`` when ``underlying_qty`` is unset — the ratio is then undefined
        and the metric is reported unavailable, never a fabricated ``0.0``.

    """
    if underlying_qty == 0:
        return None
    return net_delta / underlying_qty * 100.0 - target_delta_ratio_pct


class HealthMixin:
    """Mixin for portfolio health metrics calculation.

    Provides methods for calculating various hedge health metrics including
    carry, convexity, vega sufficiency, delta drift, and overall health scores.
    """

    if TYPE_CHECKING:
        portfolio: "OptionPortfolio"

    def calculate_net_carry_pct(self) -> float | None:
        """Calculate net carry (theta) as annualized % of underlying value.

        Returns:
            Annualized theta as percentage of underlying value (positive =
            earning carry, negative = paying carry), or ``None`` when the
            underlying position is unset — the ratio is then undefined and the
            metric is reported unavailable, never a fabricated ``0.0``.

        """
        stats = self.portfolio.summary_stats()
        daily_theta = stats["total_theta"]
        underlying_value = abs(stats["total_underlying_value"])

        if underlying_value == 0:
            return None

        # Annualize and convert to percentage
        annual_theta = daily_theta * const.DAYS_PER_YEAR
        return float((annual_theta / underlying_value) * 100)

    def calculate_crash_convexity_pct(self, shock: CrashShock) -> float:
        """Calculate crash convexity, hedge-only and repriced (§1-3).

        Repriced, hedge-only value change of the option legs at the crash
        state, as a percentage of the protected book. The underlying / equity
        position is excluded from both terms, the legs are repriced at the
        crash spot and shocked vol (full option value, not intrinsic, not
        value at expiry), and the valuation date does not advance. See
        ``docs/repricing-methodology.md``.

        A positive value means the hedge gains value in a crash.

        Args:
            shock: The crash basis — depth, flat vol bump, and wing steepening
                with its anchor. **Required, with no default**, and every
                caller (this gauge, the scenario table, and the roll trigger)
                builds it with ``CrashShock.from_ips`` so no site can reprice
                against a different crash state than the others. Note the
                target band is *not* on it: read that from ``IpsConvexity``.

        Returns:
            Hedge-only crash convexity as a percentage of the protected book
            (``abs(underlying_quantity * spot)``). ``0.0`` when the book is
            empty, since the ratio is then undefined.

        """
        return crash_convexity_pct(self.portfolio, shock=shock)

    def calculate_vega_sufficiency_pct(
        self,
        vol_shock_points: float = 10.0,
    ) -> float:
        """Calculate vega sufficiency: Portfolio % impact per vol shock.

        Shows how much the portfolio value changes for a vol point increase.
        High absolute values indicate significant volatility exposure.

        Args:
            vol_shock_points: Volatility shock in points (default: 10.0)

        Returns:
            Percentage change in portfolio value per vol point shock.

        """
        stats = self.portfolio.summary_stats()
        total_vega = stats["total_vega"]
        portfolio_value = abs(stats["total_portfolio_value"])

        if portfolio_value == 0:
            return 0.0

        # Vega is $ change per 1% vol change
        # For vol_shock_points, impact = vega * vol_shock_points
        vol_shock_impact = total_vega * vol_shock_points

        return float((vol_shock_impact / portfolio_value) * 100)

    def calculate_delta_drift_pct(
        self,
        target_delta_ratio_pct: float,
    ) -> float | None:
        """Calculate delta drift as deviation from the target hedge ratio.

        Drift is the net-delta-to-equity ratio minus the stated
        ``target_delta_ratio_pct`` (see :func:`delta_drift_from_target`). 0 =
        at target, positive = under-hedged (more net long than target), negative
        = over-hedged.

        Args:
            target_delta_ratio_pct: Intended net-delta-to-equity ratio (%),
                single-sourced from ``IpsTriggers.target_delta_ratio_pct``.

        Returns:
            Signed deviation from target in percentage points, or ``None`` when
            ``underlying_quantity`` is unset (metric unavailable).

        """
        stats = self.portfolio.summary_stats()
        return delta_drift_from_target(
            stats["net_delta"],
            stats["underlying_quantity"],
            target_delta_ratio_pct,
        )

    def calculate_convexity_cliff_days(
        self,
        cliff_threshold_days: int = 180,
    ) -> int:
        """Calculate days until long puts enter high-gamma region.

        Returns the minimum days to maturity for long put positions.
        Lower values mean convexity is about to decay rapidly.

        Args:
            cliff_threshold_days: Days threshold for high-gamma region
            (default: 180)

        Returns:
            Days until nearest long put enters high-gamma region.
            Returns :data:`NO_LONG_PUTS_CLIFF_DAYS` if no long puts exist.

        """
        min_days = NO_LONG_PUTS_CLIFF_DAYS

        for pos in self.portfolio.positions:
            # Check for long puts (negative quantity for puts means short)
            is_put = pos.option.option_type == const.OptionType.PUT
            is_long = pos.quantity > 0

            if is_put and is_long:
                days_to_maturity = (
                    pos.option.maturity_date - self.portfolio.valuation_date
                ).days
                # Calculate days until entering high-gamma region
                days_until_cliff = days_to_maturity - cliff_threshold_days
                min_days = min(min_days, max(0, days_until_cliff))

        return min_days

    def calculate_vol_regime_percentile(
        self,
        historical_vol_low: float = DEFAULT_VOL_REGIME_LOW,
        historical_vol_high: float = DEFAULT_VOL_REGIME_HIGH,
        vix_history: Sequence[float] | None = None,
        lookback_days: int = VOL_REGIME_LOOKBACK_DAYS,
    ) -> float:
        """Calculate the volatility-regime figure (0-100).

        Returns a **true** percentile (rank of the current implied vol against
        the trailing VIX distribution) when *vix_history* is supplied, and
        otherwise a min-max normalized figure between the historical band. This
        method returns only the value; use :func:`compute_vol_regime` when the
        caller needs to know which basis was used (percentile vs normalized) so
        a normalized figure is never mislabelled a percentile.

        Args:
            historical_vol_low: Historical low volatility for the normalized
                fallback (default: :data:`DEFAULT_VOL_REGIME_LOW`).
            historical_vol_high: Historical high volatility for the normalized
                fallback (default: :data:`DEFAULT_VOL_REGIME_HIGH`).
            vix_history: Trailing VIX closes in vol points; when non-empty a
                true percentile is computed. ``None``/empty -> normalized.
            lookback_days: Rank window in trading days (default:
                :data:`VOL_REGIME_LOOKBACK_DAYS`).

        Returns:
            Volatility-regime figure (0-100).

        """
        return compute_vol_regime(
            self.portfolio.volatility,
            vix_history=vix_history,
            normalized_low=historical_vol_low,
            normalized_high=historical_vol_high,
            lookback_days=lookback_days,
        ).value

    def calculate_hedge_success_pct(
        self,
        cumulative_carry_paid: float,
        crash_scenario_pct: float,
    ) -> float:
        """Calculate hedge success: Hedge P&L vs cumulative carry paid.

        Shows whether the hedge protection value exceeds the carry cost.
        Positive = hedge is "worth it", Negative = paying more than protecting.

        Args:
            cumulative_carry_paid: Total carry paid for the hedge
            crash_scenario_pct: Signed crash move as a percent of current spot
                (e.g. ``-25.0`` for a 25% decline). Single-sourced from
                ``IpsConvexity.crash_scenario_pct``.

        Returns:
            Ratio of hedge P&L to carry paid as percentage.
            Returns 0 if no carry has been paid.

        """
        if abs(cumulative_carry_paid) < 0.01:
            return 0.0

        # Get current hedge P&L (options value change from initial)
        # This is a simplified measure - actual hedge P&L would need
        # historical tracking
        # https://github.com/qwertytam/deltadewa/issues/70
        # For now, use crash protection value as a proxy for hedge value.
        # NOTE (M1.2/Mo1): only the crash *scenario* is single-sourced here;
        # the include_underlying basis and carry wiring are unchanged and this
        # gauge stays a proxy until M2.4 wires it to realized tracking.
        current_spot = self.portfolio.spot_price
        crash_spot = current_spot * (1 + crash_scenario_pct / 100)
        hedge_pnl = self.portfolio.calculate_pnl_at_expiry(
            crash_spot,
            include_underlying=True,
        )

        # Compare crash protection to carry paid
        # Positive if hedge protection > carry cost
        return (hedge_pnl / abs(cumulative_carry_paid)) * 100

    def calculate_overall_health_score(
        self,
        metrics: dict[str, Any],
    ) -> float:
        """Calculate an overall health score (0-100) based on all metrics.

        Args:
            metrics: dictionary containing metric configurations with keys:
                - actual: Actual metric value
                - min_val: Minimum threshold value
                - max_val: Maximum threshold value
                - invert_colors: Whether lower values are better

        Returns:
            Overall health score (0-100).

        """
        scores = []

        for metric in metrics.values():
            # Skip metrics reported unavailable (e.g. delta drift with no
            # underlying_quantity) — they contribute no score rather than a
            # fabricated one.
            if metric.actual is None:
                continue

            # Normalize metric to 0-100 score
            # For non-inverted metrics: min_val=0, max_val=100
            # For inverted metrics: min_val=100, max_val=0

            if metric.actual <= metric.min_val:
                raw_score: float = 0 if not metric.invert_colors else 100
            elif metric.actual >= metric.max_val:
                raw_score = 100 if not metric.invert_colors else 0
            else:
                # Linear interpolation between min and max
                range_val = metric.max_val - metric.min_val
                position = (metric.actual - metric.min_val) / range_val
                if metric.invert_colors:
                    raw_score = (1 - position) * 100
                else:
                    raw_score = position * 100

            scores.append(max(0, min(100, raw_score)))

        return sum(scores) / len(scores) if scores else 50

    def calculate_health_metrics(  # pylint: disable=too-many-arguments  # one metric-config arg per gauge
        self,
        cumulative_carry_paid: float = 0.0,
        historical_vol_low: float = DEFAULT_VOL_REGIME_LOW,
        historical_vol_high: float = DEFAULT_VOL_REGIME_HIGH,
        convexity_cliff_days: int = 180,
        *,
        crash: IpsConvexity | None = None,
        target_delta_ratio_pct: float | None = None,
        vix_history: Sequence[float] | None = None,
        vol_regime_lookback_days: int = VOL_REGIME_LOOKBACK_DAYS,
    ) -> dict[str, Any]:
        """Calculate all health metrics in one call.

        .. note::

           **This entry point is historical.** Its only caller is
           ``widgets/health_dashboard.py``, a Jupyter surface that CI stopped
           gating at M2.6 when the notebook-execution and ``nbqa`` steps were
           retired. Nothing on a shipping Dash page reads it.

           Four of the gauges it assembles (``delta_drift_pct``,
           ``net_carry_pct``, ``convexity_cliff_days``, ``hedge_success_pct``)
           are reachable *only* through here, so they are ungated too — see
           ``docs/part-x-coverage.md``, "Open questions", for the standing
           decision on whether to revive, fold, or delete them. The three
           methods with live consumers (crash convexity, vol regime, and —
           since M2.7 — vega sufficiency) are all called directly by their
           consumers, not through this function.

        Args:
            cumulative_carry_paid: Total carry paid for the hedge (default: 0.0)
            historical_vol_low: Historical low volatility for the vol-regime
                normalized fallback (default: :data:`DEFAULT_VOL_REGIME_LOW`)
            historical_vol_high: Historical high volatility for the vol-regime
                normalized fallback (default: :data:`DEFAULT_VOL_REGIME_HIGH`)
            convexity_cliff_days: Days threshold for high-gamma region
            (default: 180)
            crash: The IPS crash policy (pass ``ips_config.convexity``). The
                crash *scenario* and its *vol shock* are bundled here so they
                can never diverge — supplying a scenario always carries the
                matching shock. When ``None`` (no IPS supplied), the
                crash-derived gauges (crash convexity, hedge success) are
                DISABLED and read ``0.0``, rather than silently reprice
                spot-only against a fabricated scenario or a defaulted zero
                shock. Both are single-sourced from ``IpsConvexity``.
            target_delta_ratio_pct: Intended net-delta-to-equity ratio (%),
                single-sourced from ``IpsTriggers.target_delta_ratio_pct``.
                When ``None`` (no IPS supplied), ``delta_drift_pct`` is ``None``
                (unavailable) rather than measured against a hardcoded target.
            vix_history: Trailing VIX closes in vol points (from
                ``MarketDataProvider.get_vix_history``). When non-empty the
                vol-regime figure is a **true** percentile; ``None``/empty
                yields the min-max normalized figure, labelled as such.
            vol_regime_lookback_days: Rank window for the vol-regime percentile
                (default: :data:`VOL_REGIME_LOOKBACK_DAYS`).

        Returns:
            Dictionary containing all calculated health metrics:
            - net_carry_pct: Net carry as % of underlying, or ``None`` when
              ``underlying_quantity`` is unset (unavailable)
            - crash_convexity_pct: Hedge P&L at the IPS crash scenario
            - vega_sufficiency_pct: Portfolio % impact per +10 vol
            - delta_drift_pct: Deviation from the target hedge ratio (pp), or
              ``None`` when unavailable
            - convexity_cliff_days: Days until high-gamma region
            - vol_regime_percentile: Vol-regime figure (0-100)
            - vol_regime_basis: ``"percentile"`` (true rank vs VIX history) or
              ``"normalized"`` (min-max fallback — not a percentile)
            - vol_regime_lookback_days: Rank window when the basis is a true
              percentile, else ``None``
            - hedge_success_pct: Hedge P&L vs carry paid

        """
        if crash is None:
            crash_convexity_value = 0.0
            hedge_success_pct = 0.0
        else:
            crash_convexity_value = self.calculate_crash_convexity_pct(
                CrashShock.from_ips(crash),
            )
            hedge_success_pct = self.calculate_hedge_success_pct(
                cumulative_carry_paid,
                crash.crash_scenario_pct,
            )

        if target_delta_ratio_pct is None:
            delta_drift_value = None
        else:
            delta_drift_value = self.calculate_delta_drift_pct(
                target_delta_ratio_pct,
            )

        vol_regime = compute_vol_regime(
            self.portfolio.volatility,
            vix_history=vix_history,
            normalized_low=historical_vol_low,
            normalized_high=historical_vol_high,
            lookback_days=vol_regime_lookback_days,
        )

        return {
            "net_carry_pct": self.calculate_net_carry_pct(),
            "crash_convexity_pct": crash_convexity_value,
            "vega_sufficiency_pct": self.calculate_vega_sufficiency_pct(),
            "delta_drift_pct": delta_drift_value,
            "convexity_cliff_days": self.calculate_convexity_cliff_days(
                convexity_cliff_days,
            ),
            "vol_regime_percentile": vol_regime.value,
            "vol_regime_basis": vol_regime.basis.value,
            "vol_regime_lookback_days": vol_regime.lookback_days,
            "hedge_success_pct": hedge_success_pct,
        }
