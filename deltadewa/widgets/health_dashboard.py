"""
Hedge health dashboard widgets for portfolio analysis.

This module provides visual gauge-based dashboard widgets for monitoring
the health and effectiveness of equity hedges through key metrics.
"""

from typing import TYPE_CHECKING, Any, Dict
import ipywidgets as widgets  # type: ignore[import-untyped]
from deltadewa.colours import DEFAULT_PALETTE
from deltadewa import constants as const
from .gauges import GaugeIndicator

if TYPE_CHECKING:
    from deltadewa.portfolio import OptionPortfolio
    from deltadewa.analysis import PortfolioAnalyzer


class HedgeHealthMetric:
    """
    Configuration and calculation for a single hedge health metric.

    Attributes:
        name: Display name of the metric
        description: Tooltip/hover description
        start: Gauge start value
        end: Gauge end value
        min_val: Where "bad" color ends
        mid_val: Neutral point
        max_val: Where "good" color begins
        actual: Calculated actual value
        unit: Display unit (%, days, etc.)
        invert_colors: If True, low values are good (green), high are bad (red)
    """

    def __init__(
        self,
        name: str,
        description: str,
        start: float,
        end: float,
        min_val: float,
        mid_val: float,
        max_val: float,
        actual: float,
        unit: str = "%",
        invert_colors: bool = False,
        label_format: str = "{:.1f}",
    ):
        self.name = name
        self.description = description
        self.start = start
        self.end = end
        self.min_val = min_val
        self.mid_val = mid_val
        self.max_val = max_val
        self.actual = actual
        self.unit = unit
        self.invert_colors = invert_colors
        self.label_format = label_format


class HedgeHealthDashboard:
    """
    Comprehensive hedge health dashboard with visual gauge indicators.

    Displays seven key hedge health metrics as visual gauges:
    1. Net Carry (Theta) - Annualized theta as % of underlying value
    2. Crash Convexity - Hedge P&L as % of underlying at -20% spot
    3. Vega Sufficiency - Portfolio % impact per +10 vol shock
    4. Delta Drift - Net hedge delta as % of equity delta
    5. Time-to-Convexity Cliff - Days until puts enter high-gamma region
    6. Volatility Regime Alert - IV percentile assessment
    7. Hedge Success - Hedge P&L vs cumulative carry paid

    Each metric is displayed as a colored gauge bar with:
    - Color gradient from red (bad) through yellow (neutral) to green (good)
    - Chevron marker showing actual value
    - Configurable thresholds for each metric

    Attributes:
        portfolio: OptionPortfolio instance to analyze
        analyzer: PortfolioAnalyzer for advanced calculations
        cumulative_carry_paid: Running total of carry paid (for hedge success)
        historical_vol_low: 25th percentile IV for vol regime (default: 0.15)
        historical_vol_high: 75th percentile IV for vol regime (default: 0.35)
        convexity_cliff_days: Days threshold for high-gamma region (default: 180)

    Example:
        from deltadewa.widgets import HedgeHealthDashboard
        from deltadewa.analysis import PortfolioAnalyzer

        dashboard = HedgeHealthDashboard(portfolio)
        display(dashboard.display())

        # Update when portfolio changes
        dashboard.update()

        # Track cumulative carry for hedge success metric
        dashboard.add_carry_paid(100.0)  # Add daily carry
    """

    def __init__(
        self,
        portfolio,
        cumulative_carry_paid: float = 0.0,
        historical_vol_low: float = 0.15,
        historical_vol_high: float = 0.35,
        convexity_cliff_days: int = 180,
    ):
        """
        Initialize the Hedge Health Dashboard.

        Args:
            portfolio: OptionPortfolio instance
            cumulative_carry_paid: Running total of carry paid to date
            historical_vol_low: 25th percentile IV for vol regime assessment
            historical_vol_high: 75th percentile IV for vol regime assessment
            convexity_cliff_days: Days threshold for high-gamma convexity cliff
        """
        self.portfolio = portfolio
        self.cumulative_carry_paid = cumulative_carry_paid
        self.historical_vol_low = historical_vol_low
        self.historical_vol_high = historical_vol_high
        self.convexity_cliff_days = convexity_cliff_days

        self.analyzer = PortfolioAnalyzer(portfolio)

        self._widget = None
        self._metrics: Dict[str, HedgeHealthMetric] = {}
        self._gauges: Dict[str, GaugeIndicator] = {}

    def add_carry_paid(self, amount: float) -> None:
        """
        Add to cumulative carry paid (for tracking hedge success).

        Args:
            amount: Amount of carry paid (positive = cost)
        """
        self.cumulative_carry_paid += amount

    def reset_carry_paid(self) -> None:
        """Reset cumulative carry paid to zero."""
        self.cumulative_carry_paid = 0.0

    # ==========================================================================
    # Metric Calculations
    # ==========================================================================

    def _calculate_net_carry_pct(self) -> float:
        """
        Calculate net carry (theta) as annualized % of underlying value.

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

    def _calculate_crash_convexity_pct(self) -> float:
        """
        Calculate crash convexity: Hedge P&L at -20% spot as % of underlying.

        A positive value means the hedge is providing protection in a crash.
        A negative value means the portfolio loses money in a crash.

        Returns:
            Hedge P&L at -20% spot as percentage of underlying value.
        """
        stats = self.portfolio.summary_stats()
        underlying_value = abs(stats["total_underlying_value"])
        current_spot = self.portfolio.spot_price

        if underlying_value == 0:
            return 0.0

        # Calculate P&L at -20% spot (include underlying to see net effect)
        crash_spot = current_spot * 0.80
        hedge_pnl = self.portfolio.calculate_pnl_at_expiry(
            crash_spot, include_underlying=True
        )

        return (hedge_pnl / underlying_value) * 100

    def _calculate_vega_sufficiency_pct(self) -> float:
        """
        Calculate vega sufficiency: Portfolio % impact per +10 vol shock.

        Shows how much the portfolio value changes for a 10-point vol increase.
        High absolute values indicate significant volatility exposure.

        Returns:
            Percentage change in portfolio value per +10 vol point shock.
        """
        stats = self.portfolio.summary_stats()
        total_vega = stats["total_vega"]
        portfolio_value = abs(stats["total_portfolio_value"])

        if portfolio_value == 0:
            return 0.0

        # Vega is $ change per 1% vol change
        # For +10 vol points (0.10), impact = vega * 10
        vol_shock_impact = total_vega * 10

        return (vol_shock_impact / portfolio_value) * 100

    def _calculate_delta_drift_pct(self) -> float:
        """
        Calculate delta drift: Net hedge delta as % of equity delta.

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

    def _calculate_convexity_cliff_days(self) -> int:
        """
        Calculate days until long puts enter high-gamma region (<6 months).

        Returns the minimum days to maturity for long put positions.
        Lower values mean convexity is about to decay rapidly.

        Returns:
            Days until nearest long put enters high-gamma region.
            Returns 999 if no long puts exist.
        """
        min_days = 999

        for pos in self.portfolio.positions:
            # Check for long puts (negative quantity for puts means short)
            is_put = pos.option.option_type.lower() == "put"
            is_long = pos.quantity > 0

            if is_put and is_long:
                days_to_maturity = (
                    pos.option.maturity_date - self.portfolio.valuation_date
                ).days
                # Calculate days until entering high-gamma region
                days_until_cliff = days_to_maturity - self.convexity_cliff_days
                min_days = min(min_days, max(0, days_until_cliff))

        return min_days

    def _calculate_vol_regime_percentile(self) -> float:
        """
        Calculate volatility regime as a percentile (0-100).

        Uses simple linear interpolation between historical low and high.
        0 = at or below historical low (cheap vol)
        50 = at historical median
        100 = at or above historical high (expensive vol)

        Returns:
            Volatility percentile (0-100).
        """
        current_vol = self.portfolio.volatility

        if current_vol <= self.historical_vol_low:
            return 0.0
        elif current_vol >= self.historical_vol_high:
            return 100.0
        else:
            # Linear interpolation
            vol_range = self.historical_vol_high - self.historical_vol_low
            percentile = (
                (current_vol - self.historical_vol_low) / vol_range
            ) * 100
            return percentile

    def _calculate_hedge_success_pct(self) -> float:
        """
        Calculate hedge success: Hedge P&L vs cumulative carry paid.

        Shows whether the hedge protection value exceeds the carry cost.
        Positive = hedge is "worth it", Negative = paying more than protecting.

        Returns:
            Ratio of hedge P&L to carry paid as percentage.
            Returns 0 if no carry has been paid.
        """
        if abs(self.cumulative_carry_paid) < 0.01:
            return 0.0

        # Get current hedge P&L (options value change from initial)
        # This is a simplified measure - actual hedge P&L would need
        # historical tracking
        stats = self.portfolio.summary_stats()

        # pylint: disable=unused-variable
        current_option_value = stats["total_value"]  # noqa: F841

        # For now, use crash protection value as a proxy for hedge value
        current_spot = self.portfolio.spot_price
        crash_spot = current_spot * 0.80
        hedge_pnl = self.portfolio.calculate_pnl_at_expiry(
            crash_spot, include_underlying=True
        )

        # Compare crash protection to carry paid
        # Positive if hedge protection > carry cost
        return (hedge_pnl / abs(self.cumulative_carry_paid)) * 100

    # ==========================================================================
    # Metric Configuration
    # ==========================================================================

    def _configure_metrics(self) -> Dict[str, HedgeHealthMetric]:
        """
        Configure all seven health metrics with their gauge parameters.

        Returns:
            Dictionary of metric name -> HedgeHealthMetric configuration.
        """
        metrics = {}

        # 1. Net Carry (Theta) as % of underlying
        # Good: positive (earning carry), Bad: negative (paying carry)
        net_carry = self._calculate_net_carry_pct()
        metrics["net_carry"] = HedgeHealthMetric(
            name="Net Carry (Theta)",
            description="Annualized theta as % of underlying value",
            start=-10.0,
            end=10.0,
            min_val=-5.0,  # Full red at -5% annual carry cost
            mid_val=0.0,  # Neutral at 0
            max_val=2.0,  # Full green at +2% carry income
            actual=net_carry,
            unit="",  # Display % in label, not unit
            invert_colors=False,
            label_format="{:+.2f}%",
        )

        # 2. Crash Convexity (Hedge P&L at -20% spot)
        # Good: positive (hedge working), Bad: negative (losing money in crash)
        crash_convexity = self._calculate_crash_convexity_pct()
        metrics["crash_convexity"] = HedgeHealthMetric(
            name="Crash Convexity",
            description="Hedge P&L at -20% spot as % of underlying",
            start=-30.0,
            end=30.0,
            min_val=-10.0,  # Full red at -10% loss in crash
            mid_val=0.0,  # Neutral at breakeven
            max_val=10.0,  # Full green at +10% gain in crash
            actual=crash_convexity,
            unit="",  # Display % in label, not unit
            invert_colors=False,
            label_format="{:+.1f}%",
        )

        # 3. Vega Sufficiency (Portfolio % per +10 vol)
        # Target: low absolute value (not too exposed to vol)
        # This is inverted: low absolute value = good
        vega_suff = self._calculate_vega_sufficiency_pct()
        metrics["vega_sufficiency"] = HedgeHealthMetric(
            name="Vega Exposure",
            description="Portfolio % change per +10 vol shock",
            start=-50.0,
            end=50.0,
            min_val=-20.0,  # Full color at high negative vega
            mid_val=0.0,  # Neutral at low vega
            max_val=20.0,  # Full color at high positive vega
            actual=vega_suff,
            unit="",  # Display % in label, not unit
            invert_colors=False,  # For vega, we show direction
            label_format="{:+.1f}%",
        )

        # 4. Delta Drift (Net delta as % of underlying)
        # Target: 0% (perfectly hedged)
        delta_drift = self._calculate_delta_drift_pct()
        metrics["delta_drift"] = HedgeHealthMetric(
            name="Delta Drift",
            description="Net hedge delta as % of equity delta",
            start=-50.0,
            end=50.0,
            min_val=-20.0,  # Full red at -20% (under-hedged)
            mid_val=0.0,  # Green at 0% (perfectly hedged)
            max_val=20.0,  # Full red at +20% (over-hedged)
            actual=delta_drift,
            unit="",  # Display % in label, not unit
            invert_colors=False,
            label_format="{:+.1f}%",
        )

        # 5. Time-to-Convexity Cliff (days until puts in high-gamma)
        # Good: many days, Bad: few days
        cliff_days = self._calculate_convexity_cliff_days()
        metrics["convexity_cliff"] = HedgeHealthMetric(
            name="Time to Convexity Cliff",
            description="Days until long puts enter high-gamma region",
            start=0,
            end=365,
            min_val=30,  # Full red at <30 days
            mid_val=90,  # Yellow at 90 days
            max_val=180,  # Full green at >180 days
            actual=min(cliff_days, 365),  # Cap at 365 for display
            unit=" days",
            invert_colors=False,
            label_format="{:.0f}",
        )

        # 6. Volatility Regime (IV percentile)
        # Low vol = cheap hedges = good, High vol = expensive = caution
        vol_percentile = self._calculate_vol_regime_percentile()
        metrics["vol_regime"] = HedgeHealthMetric(
            name="Volatility Regime",
            description="Current IV percentile (0=cheap, 100=expensive)",
            start=0,
            end=100,
            min_val=25,  # Full green below 25th percentile
            mid_val=50,  # Yellow at median
            max_val=75,  # Full red above 75th percentile
            actual=vol_percentile,
            unit="th percentile",
            invert_colors=True,  # Low is good (green), high is bad (red)
            label_format="{:.0f}",
        )

        # 7. Hedge Success (Hedge P&L vs carry paid)
        # Good: positive (hedge value > carry cost)
        hedge_success = self._calculate_hedge_success_pct()
        metrics["hedge_success"] = HedgeHealthMetric(
            name="Hedge Success",
            description="Hedge P&L vs cumulative carry paid",
            start=-200,
            end=200,
            min_val=-100,  # Full red: hedge lost more than carry paid
            mid_val=0,  # Yellow: breakeven
            max_val=100,  # Full green: hedge gained more than carry cost
            actual=max(-200, min(200, hedge_success)),  # Clamp for display
            unit="",  # Display % in label, not unit
            invert_colors=False,
            label_format="{:+.0f}%",
        )

        return metrics

    # ==========================================================================
    # Widget Building
    # ==========================================================================

    def _create_gauge_html(self, metric: HedgeHealthMetric) -> str:
        """
        Create HTML for a single gauge indicator.

        Args:
            metric: HedgeHealthMetric configuration

        Returns:
            HTML string for the gauge.
        """
        # Determine colors based on invert_colors flag
        if metric.invert_colors:
            low_color = DEFAULT_PALETTE.positive  # Green for low
            mid_color = DEFAULT_PALETTE.yellow  # Yellow
            high_color = DEFAULT_PALETTE.negative  # Red for high
        else:
            low_color = DEFAULT_PALETTE.negative  # Red for low
            mid_color = DEFAULT_PALETTE.yellow  # Yellow
            high_color = DEFAULT_PALETTE.positive  # Green for high

        gauge = GaugeIndicator(
            start=metric.start,
            end=metric.end,
            min_val=metric.min_val,
            mid_val=metric.mid_val,
            max_val=metric.max_val,
            actual=metric.actual,
            low_color=low_color,
            mid_color=mid_color,
            high_color=high_color,
            orientation="horizontal",
            width=280,
            height=25,
            show_actual_label=True,
            show_minmidmax_labels=False,
            show_startend_labels=True,
            label_format=metric.label_format,
            title=None,  # We'll add title separately
        )

        # Use the public API to create the widget and return its HTML value
        return gauge.create_widget().value

    def _build_metric_card_html(
        self, metric: HedgeHealthMetric, gauge_html: str
    ) -> str:
        """
        Build HTML for a metric card with title, gauge, and description.

        Args:
            metric: HedgeHealthMetric configuration
            gauge_html: Pre-rendered gauge HTML

        Returns:
            HTML string for the complete metric card.
        """
        # Determine status color based on where actual falls
        if metric.invert_colors:
            if metric.actual <= metric.min_val:
                status_color = DEFAULT_PALETTE.positive
                status = "Good"
            elif metric.actual >= metric.max_val:
                status_color = DEFAULT_PALETTE.negative
                status = "Alert"
            else:
                status_color = DEFAULT_PALETTE.yellow
                status = "Watch"
        else:
            if metric.actual >= metric.max_val:
                status_color = DEFAULT_PALETTE.positive
                status = "Good"
            elif metric.actual <= metric.min_val:
                status_color = DEFAULT_PALETTE.negative
                status = "Alert"
            else:
                status_color = DEFAULT_PALETTE.yellow
                status = "Watch"

        # Format actual value for display
        actual_display = metric.label_format.format(metric.actual) + metric.unit

        # Assemble the html for the card
        show_description = True

        # We show the actual value on the gauge marker, so no need to repeat it
        show_separate_metric_value = False

        card_background_html = f"""
        <div style="
            background: {DEFAULT_PALETTE.very_light_grey};
            border-radius: 8px;
            padding: 12px;
            margin: 8px;
            min-width: 320px;
            max-width: 360px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        ">
        """

        metric_name_html = f"""
        <span style="font-weight: bold; font-size: 13px; color: #333;">
        {metric.name}</span>
        """

        metric_status_html = f"""
        <span style="background: {status_color}; color: white;
        padding: 2px 8px; border-radius: 10px; font-size: 11px;
        font-weight: bold;">{status}</span>
        """

        metric_display_html = f"""
        <div style="font-size: 22px; font-weight: bold; color: #333;
        margin-bottom: 8px;">
        {actual_display}
        </div>
        """

        metric_description_html = f"""
        <div style="font-size: 10px; color: #666; margin-top: 8px;">
        {metric.description}
        </div>
        """

        card_html = f"""
        {card_background_html}
            <div style="display: flex; justify-content: space-between;
            align-items: center; margin-bottom: 8px;">
                {metric_name_html}
                {metric_status_html}
            </div>
            {metric_display_html if show_separate_metric_value else ""}
            {gauge_html}
            {metric_description_html if show_description else ""}
        </div>
        """
        return card_html

    def _build_dashboard_html(self) -> str:
        """
        Build the complete dashboard HTML with all metrics.

        Returns:
            Complete HTML string for the dashboard.
        """
        self._metrics = self._configure_metrics()

        # Build metric cards
        cards_html = ""
        for key in [
            "net_carry",
            "crash_convexity",
            "vega_sufficiency",
            "delta_drift",
            "convexity_cliff",
            "vol_regime",
            "hedge_success",
        ]:
            metric = self._metrics[key]
            gauge_html = self._create_gauge_html(metric)
            cards_html += self._build_metric_card_html(metric, gauge_html)

        # Calculate overall health score (simple average of normalized metrics)
        overall_score = self._calculate_overall_health_score()
        overall_color = (
            DEFAULT_PALETTE.positive
            if overall_score >= 70
            else (
                DEFAULT_PALETTE.yellow
                if overall_score >= 40
                else DEFAULT_PALETTE.negative
            )
        )

        dashboard_html = f"""
        <div style="
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            border: 2px solid #0F4761;
            border-radius: 8px;
            margin: 10px 0;
            background: white;
        ">
            <!-- Header -->
            <div style="
                background: linear-gradient(135deg, #0F4761 0%, #1a5a7a 100%);
                color: white;
                padding: 15px 20px;
                border-radius: 6px 6px 0 0;
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <div>
                    <h3 style="margin: 0; font-size: 18px;">📊 Hedge Health Dashboard</h3>
                    <p style="margin: 5px 0 0 0; font-size: 12px; opacity: 0.9;">
                        Real-time portfolio health indicators
                    </p>
                </div>
                <div style="
                    background: {overall_color};
                    padding: 8px 16px;
                    border-radius: 20px;
                    font-weight: bold;
                ">
                    Health Score: {overall_score:.0f}/100
                </div>
            </div>

            <!-- Metric Cards Grid -->
            <div style="
                display: flex;
                flex-wrap: wrap;
                justify-content: flex-start;
                padding: 10px;
            ">
                {cards_html}
            </div>
        </div>
        """
        return dashboard_html

    def _calculate_overall_health_score(self) -> float:
        """
        Calculate an overall health score (0-100) based on all metrics.

        Returns:
            Overall health score.
        """
        scores = []

        for (
            key,  # pylint: disable=unused-variable
            metric,
        ) in self._metrics.items():
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

    # ==========================================================================
    # Public Interface
    # ==========================================================================

    def create_widget(self) -> "widgets.HTML":
        """
        Create and return the ipywidgets HTML widget.

        Returns:
            ipywidgets.HTML widget containing the dashboard.
        """
        self._widget = widgets.HTML(value=self._build_dashboard_html())
        return self._widget

    def update(self) -> None:
        """Update all metrics and refresh the display."""
        if self._widget is not None:
            self._widget.value = self._build_dashboard_html()

    def display(self) -> "widgets.HTML":
        """
        Create the widget and return it for display.

        Returns:
            The created HTML widget.
        """
        return self.create_widget()

    def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get a dictionary summary of all metrics for programmatic access.

        Returns:
            Dictionary with metric values and status, plus an 'overall_score' float.
        """
        self._metrics = self._configure_metrics()

        summary: Dict[str, Any] = {}
        for key, metric in self._metrics.items():
            # Determine status
            if metric.invert_colors:
                if metric.actual <= metric.min_val:
                    status = "good"
                elif metric.actual >= metric.max_val:
                    status = "alert"
                else:
                    status = "watch"
            else:
                if metric.actual >= metric.max_val:
                    status = "good"
                elif metric.actual <= metric.min_val:
                    status = "alert"
                else:
                    status = "watch"

            summary[key] = {
                "name": metric.name,
                "value": metric.actual,
                "unit": metric.unit,
                "status": status,
                "description": metric.description,
            }

        summary["overall_score"] = self._calculate_overall_health_score()

        return summary
