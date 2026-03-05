"""Health metrics mixin for portfolio analysis."""

from typing import TYPE_CHECKING, Any

from deltadewa import constants as const

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
        return (annual_theta / underlying_value) * 100

    def calculate_crash_convexity_pct(self, crash_pct: float = 0.80) -> float:
        """Calculate crash convexity.

        Calculates Hedge P&L at crash spot as % of underlying.

        A positive value means the hedge is providing protection in a crash.
        A negative value means the portfolio loses money in a crash.

        Args:
            crash_pct: Crash scenario as percentage of current spot (default:
            0.80 for -20%)

        Returns:
            Hedge P&L at crash spot as percentage of underlying value.

        """
        stats = self.portfolio.summary_stats()
        underlying_value = abs(stats["total_underlying_value"])
        current_spot = self.portfolio.spot_price

        if underlying_value == 0:
            return 0.0

        # Calculate P&L at crash spot (include underlying to see net effect)
        crash_spot = current_spot * crash_pct
        hedge_pnl = self.portfolio.calculate_pnl_at_expiry(
            crash_spot,
            include_underlying=True,
        )

        return (hedge_pnl / underlying_value) * 100

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

        return (vol_shock_impact / portfolio_value) * 100

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

        return (net_delta / underlying_qty) * 100

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
        elif current_vol >= historical_vol_high:
            return 100.0
        else:
            # Linear interpolation
            vol_range = historical_vol_high - historical_vol_low
            percentile = ((current_vol - historical_vol_low) / vol_range) * 100
            return percentile

    def calculate_hedge_success_pct(
        self,
        cumulative_carry_paid: float,
        crash_pct: float = 0.80,
    ) -> float:
        """Calculate hedge success: Hedge P&L vs cumulative carry paid.

        Shows whether the hedge protection value exceeds the carry cost.
        Positive = hedge is "worth it", Negative = paying more than protecting.

        Args:
            cumulative_carry_paid: Total carry paid for the hedge
            crash_pct: Crash scenario as percentage of current spot
            (default: 0.80 for -20%)

        Returns:
            Ratio of hedge P&L to carry paid as percentage.
            Returns 0 if no carry has been paid.

        """
        if abs(cumulative_carry_paid) < 0.01:
            return 0.0

        # Get current hedge P&L (options value change from initial)
        # TODO: This is a simplified measure - actual hedge P&L would need
        # historical tracking
        # stats = self.portfolio.summary_stats()  # noqa: ERA001
        # current_option_value = stats["total_value"]  # noqa: ERA001

        # For now, use crash protection value as a proxy for hedge value
        current_spot = self.portfolio.spot_price
        crash_spot = current_spot * crash_pct
        hedge_pnl = self.portfolio.calculate_pnl_at_expiry(
            crash_spot,
            include_underlying=True,
        )

        # Compare crash protection to carry paid
        # Positive if hedge protection > carry cost
        return (hedge_pnl / abs(cumulative_carry_paid)) * 100

    def calculate_overall_health_score(self, metrics: dict) -> float:
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

        for (
            _key,
            metric,
        ) in metrics.items():
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

    def calculate_health_metrics(
        self,
        cumulative_carry_paid: float = 0.0,
        historical_vol_low: float = 0.15,
        historical_vol_high: float = 0.35,
        convexity_cliff_days: int = 180,
    ) -> dict[str, Any]:
        """Calculate all health metrics in one call.

        Args:
            cumulative_carry_paid: Total carry paid for the hedge (default: 0.0)
            historical_vol_low: Historical low volatility (default: 0.15)
            historical_vol_high: Historical high volatility (default: 0.35)
            convexity_cliff_days: Days threshold for high-gamma region
            (default: 180)

        Returns:
            Dictionary containing all calculated health metrics:
            - net_carry_pct: Net carry as % of underlying
            - crash_convexity_pct: Hedge P&L at -20% spot
            - vega_sufficiency_pct: Portfolio % impact per +10 vol
            - delta_drift_pct: Net delta as % of equity
            - convexity_cliff_days: Days until high-gamma region
            - vol_regime_percentile: Volatility percentile (0-100)
            - hedge_success_pct: Hedge P&L vs carry paid

        """
        return {
            "net_carry_pct": self.calculate_net_carry_pct(),
            "crash_convexity_pct": self.calculate_crash_convexity_pct(),
            "vega_sufficiency_pct": self.calculate_vega_sufficiency_pct(),
            "delta_drift_pct": self.calculate_delta_drift_pct(),
            "convexity_cliff_days": self.calculate_convexity_cliff_days(
                convexity_cliff_days,
            ),
            "vol_regime_percentile": self.calculate_vol_regime_percentile(
                historical_vol_low,
                historical_vol_high,
            ),
            "hedge_success_pct": self.calculate_hedge_success_pct(
                cumulative_carry_paid,
            ),
        }
