"""Hedge health dashboard widgets for portfolio analysis.

This module provides visual gauge-based dashboard widgets for monitoring
the health and effectiveness of equity hedges through key metrics.
"""

import json
from typing import Any

import ipywidgets as widgets
import yaml

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.portfolio.core import OptionPortfolio

from .gauges import GaugeConfig, GaugeIndicator


class HedgeHealthMetric:
    """Configuration and calculation for a single hedge health metric.

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

    def __init__(  # pylint: disable=too-many-arguments  # metric config
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
    ) -> None:
        """Initialize the HedgeHealthMetric."""
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
    """Comprehensive hedge health dashboard with visual gauge indicators.

    Displays seven key hedge health metrics as visual gauges with configurable
    thresholds. Supports loading configuration from YAML/JSON files.

    Attributes:
        portfolio: OptionPortfolio instance to analyze
        analyzer: PortfolioAnalyzer for advanced calculations
        cumulative_carry_paid: Running total of carry paid (for hedge success)
        config: dictionary storing current threshold configuration

    Example:
        from deltadewa.widgets import HedgeHealthDashboard
        from deltadewa.analysis.base import PortfolioAnalyzer

        dashboard = HedgeHealthDashboard(portfolio)
        display(dashboard.display())

        # Update when portfolio changes
        dashboard.update()

        # Track cumulative carry for hedge success metric
        dashboard.add_carry_paid(100.0)  # Add daily carry

        # Load configuration from file
        config_loader = dashboard.display_config_loader()
        display(config_loader)

    """

    def __init__(
        self,
        portfolio: OptionPortfolio,
        cumulative_carry_paid: float = 0.0,
        historical_vol_low: float = 0.15,
        historical_vol_high: float = 0.35,
        convexity_cliff_days: int = 180,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the Hedge Health Dashboard.

        Args:
            portfolio: OptionPortfolio instance
            cumulative_carry_paid: Running total of carry paid to date
            historical_vol_low: 25th percentile IV for vol regime assessment
            historical_vol_high: 75th percentile IV for vol regime assessment
            convexity_cliff_days: Days threshold for high-gamma convexity cliff
            config: Optional presentation config (``parameters``/``metrics``
                keys, see ``_get_default_config``) merged on top of the
                built-in defaults via ``load_config``. Typically
                ``SessionContext.dashboard_config`` from ``start_session``.
                ``display_config_loader()`` remains available afterwards
                for ad hoc overrides on top of this.

        """
        self.portfolio = portfolio
        self.cumulative_carry_paid = cumulative_carry_paid

        # Initialize default configuration
        self.config = self._get_default_config()

        # Override defaults with init parameters
        self.config["parameters"]["historical_vol_low"] = historical_vol_low
        self.config["parameters"]["historical_vol_high"] = historical_vol_high
        self.config["parameters"]["convexity_cliff_days"] = convexity_cliff_days

        self.analyzer = PortfolioAnalyzer(portfolio)

        self._widget = None
        self._metrics: dict[str, HedgeHealthMetric] = {}
        self._gauges: dict[str, GaugeIndicator] = {}

        if config is not None:
            self.load_config(config)

    def add_carry_paid(self, amount: float) -> None:
        """Add to cumulative carry paid (for tracking hedge success).

        Args:
            amount: Amount of carry paid (positive = cost)

        """
        self.cumulative_carry_paid += amount

    def reset_carry_paid(self) -> None:
        """Reset cumulative carry paid to zero."""
        self.cumulative_carry_paid = 0.0

    def _get_default_config(self) -> dict[str, Any]:
        """Return the default configuration dictionary."""
        return {
            "parameters": {
                "historical_vol_low": 0.15,
                "historical_vol_high": 0.35,
                "convexity_cliff_days": 180,
            },
            "metrics": {
                "net_carry": {
                    "start": -10.0,
                    "end": 10.0,
                    "min_val": -5.0,
                    "mid_val": 0.0,
                    "max_val": 2.0,
                    "invert_colors": False,
                },
                "crash_convexity": {
                    "start": -30.0,
                    "end": 30.0,
                    "min_val": -10.0,
                    "mid_val": 0.0,
                    "max_val": 10.0,
                    "invert_colors": False,
                },
                "vega_sufficiency": {
                    "start": -50.0,
                    "end": 50.0,
                    "min_val": -20.0,
                    "mid_val": 0.0,
                    "max_val": 20.0,
                    "invert_colors": False,
                },
                "delta_drift": {
                    "start": -50.0,
                    "end": 50.0,
                    "min_val": -20.0,
                    "mid_val": 0.0,
                    "max_val": 20.0,
                    "invert_colors": False,
                },
                "convexity_cliff": {
                    "start": 0,
                    "end": 365,
                    "min_val": 30,
                    "mid_val": 90,
                    "max_val": 180,
                    "invert_colors": False,
                },
                "vol_regime": {
                    "start": 0,
                    "end": 100,
                    "min_val": 25,
                    "mid_val": 50,
                    "max_val": 75,
                    "invert_colors": True,
                },
                "hedge_success": {
                    "start": -200,
                    "end": 200,
                    "min_val": -100,
                    "mid_val": 0,
                    "max_val": 100,
                    "invert_colors": False,
                },
            },
        }

    def load_config(self, config_data: dict[str, Any]) -> None:
        """Update configuration from a dictionary and refresh dashboard.

        Args:
            config_data: dictionary containing 'parameters' and/or 'metrics'
            keys.

        """
        if "parameters" in config_data:
            self.config["parameters"].update(config_data["parameters"])

        if "metrics" in config_data:
            for key, val in config_data["metrics"].items():
                if key in self.config["metrics"]:
                    self.config["metrics"][key].update(val)

        self.update()

    # ==========================================================================
    # Metric Calculations - Delegated to HealthMixin in analyzer
    # ==========================================================================

    def _get_health_metrics(self) -> dict[str, Any]:
        """Get all health metrics from the analyzer.

        Returns:
            Dictionary containing all calculated health metrics.

        """
        params = self.config["parameters"]
        return self.analyzer.calculate_health_metrics(
            cumulative_carry_paid=self.cumulative_carry_paid,
            historical_vol_low=params["historical_vol_low"],
            historical_vol_high=params["historical_vol_high"],
            convexity_cliff_days=params["convexity_cliff_days"],
        )

    # ==========================================================================
    # Metric Configuration
    # ==========================================================================

    def _configure_metrics(self) -> dict[str, HedgeHealthMetric]:
        """Configure all seven health metrics with their gauge parameters using.

        Will use self.config values.

        Returns:
            Dictionary of metric name -> HedgeHealthMetric configuration.

        """
        # Get all calculated metrics from the analyzer
        health_data = self._get_health_metrics()

        metrics = {}
        cfg = self.config["metrics"]

        # 1. Net Carry (Theta) as % of underlying
        c = cfg["net_carry"]
        metrics["net_carry"] = HedgeHealthMetric(
            name="Net Carry (Theta)",
            description="Annualized theta as % of underlying value",
            start=c["start"],
            end=c["end"],
            min_val=c["min_val"],
            mid_val=c["mid_val"],
            max_val=c["max_val"],
            actual=health_data["net_carry_pct"],
            unit="",
            invert_colors=c["invert_colors"],
            label_format="{:+.2f}%",
        )

        # 2. Crash Convexity (Hedge P&L at -20% spot)
        c = cfg["crash_convexity"]
        metrics["crash_convexity"] = HedgeHealthMetric(
            name="Crash Convexity",
            description="Hedge P&L at -20% spot as % of underlying",
            start=c["start"],
            end=c["end"],
            min_val=c["min_val"],
            mid_val=c["mid_val"],
            max_val=c["max_val"],
            actual=health_data["crash_convexity_pct"],
            unit="",
            invert_colors=c["invert_colors"],
            label_format="{:+.1f}%",
        )

        # 3. Vega Sufficiency (Portfolio % per +10 vol)
        c = cfg["vega_sufficiency"]
        metrics["vega_sufficiency"] = HedgeHealthMetric(
            name="Vega Exposure",
            description="Portfolio % change per +10 vol shock",
            start=c["start"],
            end=c["end"],
            min_val=c["min_val"],
            mid_val=c["mid_val"],
            max_val=c["max_val"],
            actual=health_data["vega_sufficiency_pct"],
            unit="",
            invert_colors=c["invert_colors"],
            label_format="{:+.1f}%",
        )

        # 4. Delta Drift (Net delta as % of underlying)
        c = cfg["delta_drift"]
        metrics["delta_drift"] = HedgeHealthMetric(
            name="Delta Drift",
            description="Net hedge delta as % of equity delta",
            start=c["start"],
            end=c["end"],
            min_val=c["min_val"],
            mid_val=c["mid_val"],
            max_val=c["max_val"],
            actual=health_data["delta_drift_pct"],
            unit="",
            invert_colors=c["invert_colors"],
            label_format="{:+.1f}%",
        )

        # 5. Time-to-Convexity Cliff (days until puts in high-gamma)
        c = cfg["convexity_cliff"]
        metrics["convexity_cliff"] = HedgeHealthMetric(
            name="Time to Convexity Cliff",
            description="Days until long puts enter high-gamma region",
            start=c["start"],
            end=c["end"],
            min_val=c["min_val"],
            mid_val=c["mid_val"],
            max_val=c["max_val"],
            actual=min(
                health_data["convexity_cliff_days"],
                365,
            ),  # Cap at 365 for display
            unit=" days",
            invert_colors=c["invert_colors"],
            label_format="{:.0f}",
        )

        # 6. Volatility Regime (IV percentile)
        c = cfg["vol_regime"]
        metrics["vol_regime"] = HedgeHealthMetric(
            name="Volatility Regime",
            description="Current IV percentile (0=cheap, 100=expensive)",
            start=c["start"],
            end=c["end"],
            min_val=c["min_val"],
            mid_val=c["mid_val"],
            max_val=c["max_val"],
            actual=health_data["vol_regime_percentile"],
            unit="th percentile",
            invert_colors=c["invert_colors"],
            label_format="{:.0f}",
        )

        # 7. Hedge Success (Hedge P&L vs carry paid)
        c = cfg["hedge_success"]
        val = health_data["hedge_success_pct"]
        metrics["hedge_success"] = HedgeHealthMetric(
            name="Hedge Success",
            description="Hedge P&L vs cumulative carry paid",
            start=c["start"],
            end=c["end"],
            min_val=c["min_val"],
            mid_val=c["mid_val"],
            max_val=c["max_val"],
            actual=max(c["start"], min(c["end"], val)),  # Clamp for display
            unit="",
            invert_colors=c["invert_colors"],
            label_format="{:+.0f}%",
        )

        return metrics

    # ==========================================================================
    # Widget Building
    # ==========================================================================

    def _create_gauge_html(self, metric: HedgeHealthMetric) -> str:
        """Create HTML for a single gauge indicator.

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

        cfg = GaugeConfig(
            start=metric.start,
            end=metric.end,
            min_val=metric.min_val,
            mid_val=metric.mid_val,
            max_val=metric.max_val,
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
            title=None,
        )
        gauge = GaugeIndicator(actual=metric.actual, config=cfg)

        # Use the public API to create the widget and return its HTML value
        return str(gauge.create_widget().value)

    def _build_metric_card_html(
        self,
        metric: HedgeHealthMetric,
        gauge_html: str,
    ) -> str:
        """Build HTML for a metric card with title, gauge, and description.

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
        """Build the complete dashboard HTML with all metrics.

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

        dashboard_html = (
            f"""
        <div style="
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', """
            f"""Roboto, sans-serif;
            border: 2px solid {DEFAULT_PALETTE.med_dark_background};
            border-radius: 8px;
            margin: 10px 0;
            background: white;
        ">
            <!-- Header -->
            <div style="
                background: linear-gradient(135deg, """
            f"""{DEFAULT_PALETTE.med_dark_background} 0%, """
            f"""{DEFAULT_PALETTE.dark_background} 100%);
                color: white;
                padding: 15px 20px;
                border-radius: 6px 6px 0 0;
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <div>
                    <h3 style="margin: 0; font-size: 18px;">"""
            f"""📊 Hedge Health Dashboard</h3>
                    <p style="margin: 5px 0 0 0; font-size: 12px; """
            f"""opacity: 0.9;">
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
        )
        return dashboard_html

    def _calculate_overall_health_score(self) -> float:
        """Calculate an overall health score (0-100) based on all metrics.

        Returns:
            Overall health score.

        """
        return self.analyzer.calculate_overall_health_score(self._metrics)

    # ==========================================================================
    # Public Interface
    # ==========================================================================

    def create_widget(self) -> "widgets.HTML":
        """Create and return the ipywidgets HTML widget.

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
        """Create the widget and return it for display.

        Returns:
            The created HTML widget.

        """
        return self.create_widget()

    def get_metrics_summary(self) -> dict[str, Any]:
        """Get a dictionary summary of all metrics for programmatic access.

        Returns:
            Dictionary with metric values and status, plus an 'overall_score'
            float.

        """
        self._metrics = self._configure_metrics()

        summary: dict[str, Any] = {}
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

    def display_config_loader(self) -> widgets.VBox:
        """Display a widget to load configuration from YAML/JSON file.

        Returns:
            VBox widget containing file upload and status output.

        """
        uploader = widgets.FileUpload(
            accept=".json,.yaml,.yml",
            multiple=False,
            description="Load Config",
        )
        output = widgets.Output()

        def on_upload(change: dict[str, Any]) -> None:
            if not change["new"]:
                return

            with output:
                output.clear_output()
                try:
                    uploaded_file = change["new"][0]
                    try:
                        content = (
                            uploaded_file["content"].tobytes().decode("utf-8")
                        )
                    except UnicodeDecodeError:
                        print("❌ Error: File must be UTF-8 encoded")
                        return

                    filename = uploaded_file["name"]

                    if filename.endswith(".json"):
                        try:
                            data = json.loads(content)
                        except json.JSONDecodeError as e:
                            print(f"❌ Invalid JSON format: {e!s}")
                            return
                    elif filename.endswith((".yaml", ".yml")):
                        try:
                            data = yaml.safe_load(content)
                        except yaml.YAMLError as e:
                            print(f"❌ Invalid YAML format: {e!s}")
                            return
                    else:
                        print(f"❌ Unsupported file type: {filename}")
                        return

                    self.load_config(data)
                    print(f"✅ Successfully loaded config from {filename}")

                    # Clear uploader to allow reloading same file
                    uploader.value = []

                except (KeyError, TypeError) as e:
                    print(
                        f"❌ Invalid config structure: {e!s}. "
                        "Expected 'parameters' and/or 'metrics' keys.",
                    )

        uploader.observe(on_upload, names="value")

        return widgets.VBox(
            [
                widgets.HTML("<b>Load Dashboard Configuration</b>"),
                uploader,
                output,
            ],
        )
