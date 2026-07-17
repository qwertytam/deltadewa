"""Health metrics mixin for portfolio analysis."""

from typing import TYPE_CHECKING, Any

from deltadewa import constants as const
from deltadewa.analysis.crash_repricing import crash_convexity_pct

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


class HealthMixin:
    """Mixin for portfolio health metrics calculation.

    Provides methods for calculating various hedge health metrics including
    carry, convexity, vega sufficiency, delta drift, and overall health scores.
    """

    if TYPE_CHECKING:
        portfolio: "OptionPortfolio"

    def calculate_net_carry_pct(self) -> float:
        """Calculate net carry (theta) as annualized % of underlying value.

        Returns:
            Annualized theta as percentage of underlying value.
            Positive = earning carry, Negative = paying carry.

        """
        stats = self.portfolio.summary_stats()
        daily_theta = stats["total_theta"]
        underlying_value = abs(stats["total_underlying_value"])

        if underlying_value == 0:
            return 0.0

        # Annualize and convert to percentage
        annual_theta = daily_theta * const.DAYS_PER_YEAR
        return float((annual_theta / underlying_value) * 100)

    def calculate_crash_convexity_pct(
        self,
        crash_scenario_pct: float,
        crash_vol_shock: float = 0.0,
    ) -> float:
        """Calculate crash convexity, hedge-only and repriced (§1-3).

        Repriced, hedge-only value change of the option legs at the crash
        state, as a percentage of the protected book. The underlying / equity
        position is excluded from both terms, the legs are repriced at the
        crash spot and shocked vol (full option value, not intrinsic, not
        value at expiry), and the valuation date does not advance. See
        ``docs/repricing-methodology.md``.

        A positive value means the hedge gains value in a crash.

        Args:
            crash_scenario_pct: Signed crash move as a percent of current spot
                (e.g. ``-25.0`` for a 25% decline). Single-sourced from
                ``IpsConvexity.crash_scenario_pct``; there is no hardcoded
                default.
            crash_vol_shock: Flat additive vol bump as a decimal (e.g.
                ``0.15``) applied to every leg's own today-vol, single-sourced
                from ``IpsConvexity.crash_vol_shock``. Defaults to ``0.0`` (a
                spot-only crash) when no IPS shock is supplied.

        Returns:
            Hedge-only crash convexity as a percentage of the protected book
            (``abs(underlying_quantity * spot)``). ``0.0`` when the book is
            empty, since the ratio is then undefined.

        """
        return crash_convexity_pct(
            self.portfolio,
            crash_move=crash_scenario_pct / 100.0,
            vol_shock=crash_vol_shock,
        )

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

    def calculate_delta_drift_pct(self) -> float:
        """Calculate delta drift: Net hedge delta as % of equity delta.

        Target is 0% (perfectly hedged). Positive means over-hedged,
        negative means under-hedged.

        Returns:
            Net delta as percentage of underlying quantity.

        """
        stats = self.portfolio.summary_stats()
        net_delta = stats["net_delta"]
        underlying_qty = abs(stats["underlying_quantity"])

        if underlying_qty == 0:
            return 0.0

        return float((net_delta / underlying_qty) * 100)

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
            Returns 999 if no long puts exist.

        """
        min_days = 999

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
        historical_vol_low: float = 0.15,
        historical_vol_high: float = 0.35,
    ) -> float:
        """Calculate volatility regime as a percentile (0-100).

        Uses simple linear interpolation between historical low and high.
        0 = at or below historical low (cheap vol)
        50 = at historical median
        100 = at or above historical high (expensive vol)

        Args:
            historical_vol_low: Historical low volatility (default: 0.15)
            historical_vol_high: Historical high volatility (default: 0.35)

        Returns:
            Volatility percentile (0-100).

        """
        current_vol = self.portfolio.volatility

        if current_vol <= historical_vol_low:
            return 0.0
        if current_vol >= historical_vol_high:
            return 100.0
        # Linear interpolation
        vol_range = historical_vol_high - historical_vol_low
        return ((current_vol - historical_vol_low) / vol_range) * 100

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
        historical_vol_low: float = 0.15,
        historical_vol_high: float = 0.35,
        convexity_cliff_days: int = 180,
        *,
        crash_scenario_pct: float | None = None,
        crash_vol_shock: float = 0.0,
    ) -> dict[str, Any]:
        """Calculate all health metrics in one call.

        Args:
            cumulative_carry_paid: Total carry paid for the hedge (default: 0.0)
            historical_vol_low: Historical low volatility (default: 0.15)
            historical_vol_high: Historical high volatility (default: 0.35)
            convexity_cliff_days: Days threshold for high-gamma region
            (default: 180)
            crash_scenario_pct: Signed crash move as a percent of current spot,
                single-sourced from ``IpsConvexity.crash_scenario_pct``. When
                ``None`` (no IPS supplied), the crash-derived gauges
                (crash convexity, hedge success) read ``0.0`` rather than
                fall back to a hardcoded scenario.
            crash_vol_shock: Flat additive crash vol bump as a decimal,
                single-sourced from ``IpsConvexity.crash_vol_shock`` and used
                to reprice the crash-convexity gauge. Defaults to ``0.0``.

        Returns:
            Dictionary containing all calculated health metrics:
            - net_carry_pct: Net carry as % of underlying
            - crash_convexity_pct: Hedge P&L at the IPS crash scenario
            - vega_sufficiency_pct: Portfolio % impact per +10 vol
            - delta_drift_pct: Net delta as % of equity
            - convexity_cliff_days: Days until high-gamma region
            - vol_regime_percentile: Volatility percentile (0-100)
            - hedge_success_pct: Hedge P&L vs carry paid

        """
        if crash_scenario_pct is None:
            crash_convexity_value = 0.0
            hedge_success_pct = 0.0
        else:
            crash_convexity_value = self.calculate_crash_convexity_pct(
                crash_scenario_pct,
                crash_vol_shock,
            )
            hedge_success_pct = self.calculate_hedge_success_pct(
                cumulative_carry_paid,
                crash_scenario_pct,
            )

        return {
            "net_carry_pct": self.calculate_net_carry_pct(),
            "crash_convexity_pct": crash_convexity_value,
            "vega_sufficiency_pct": self.calculate_vega_sufficiency_pct(),
            "delta_drift_pct": self.calculate_delta_drift_pct(),
            "convexity_cliff_days": self.calculate_convexity_cliff_days(
                convexity_cliff_days,
            ),
            "vol_regime_percentile": self.calculate_vol_regime_percentile(
                historical_vol_low,
                historical_vol_high,
            ),
            "hedge_success_pct": hedge_success_pct,
        }
