# pylint: disable=too-many-lines
"""
Interactive Widget Components for Options Dashboard

This module provides reusable ipywidgets components for building interactive
portfolio analysis dashboards. It standardizes widget creation patterns and
reduces code duplication across notebooks.

Classes:
    PortfolioWidgets: Widget creation and management utilities
    InteractiveOutput: Output wrapper with automatic clearing
    GlobalAssumptions: Centralized market parameters and assumptions
    NetHedgeSummary: Always-visible KPI header showing hedge metrics

Usage:
    from deltadewa.widgets import PortfolioWidgets, InteractiveOutput

    widgets = PortfolioWidgets(portfolio)
    position_editor = widgets.create_position_editor()
    display(position_editor)
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Optional,
    Callable,
    List,
    Dict,
    Any,
    Tuple,
    Union,
)
from types import SimpleNamespace
import ipywidgets as widgets  # type: ignore[import-untyped]
from deltadewa.persistence import import_portfolio
from deltadewa.portfolio import OptionPortfolio
from deltadewa.persistence import (
    export_portfolio_to_json,
    export_portfolio_to_csv,
    export_portfolio_to_yaml,
)
from deltadewa.config import (
    create_export_dir_widget as _create_export_dir_widget,
)
from deltadewa.utils import get_volatility_stats
from deltadewa.colours import DEFAULT_PALETTE
from deltadewa import constants as const

if TYPE_CHECKING:
    # Import only for type annotations
    from ipywidgets import Dropdown, VBox  # type: ignore[import-untyped]


class InteractiveOutput:
    """
    Wrapper for widget output with automatic clearing.

    Provides a convenient decorator pattern for widget callbacks that
    automatically clears previous output before displaying new content.

    Example:
        output = InteractiveOutput()

        @output.update
        def my_callback(value):
            print(f"Value changed to: {value}")

        slider.observe(my_callback, 'value')
        display(output.widget)
    """

    def __init__(self):
        """Initialize output widget."""
        self.widget = widgets.Output()

    def update(self, func: Callable) -> Callable:
        """
        Decorator to handle output clearing.

        Args:
            func: Function to wrap with output clearing logic

        Returns:
            Wrapped function that clears output before executing
        """

        def wrapper(*args, **kwargs):
            with self.widget:
                self.widget.clear_output(wait=True)
                return func(*args, **kwargs)

        return wrapper

    def clear(self):
        """Manually clear the output widget."""
        self.widget.clear_output()


class GlobalAssumptions:
    """
    Centralized market parameters and scenario assumptions.

    This class provides a single source of truth for all market parameters
    used throughout the dashboard. It eliminates duplicate slider controls
    and ensures consistency across all analysis sections.

    Attributes:
        spot_price: Current spot price
        volatility: Portfolio default volatility
        risk_free_rate: Risk-free interest rate
        dividend_yield: Dividend yield
        valuation_date: Current valuation date
        time_horizon: Selected time horizon preset
        spot_shock_pct: Spot price shock for scenarios (%)
        vol_shock_pct: Volatility shock for scenarios (%)
        grid_resolution: Number of points in scenario grids
        monte_carlo_num_sims: Number of Monte Carlo simulations to run
        monte_carlo_inc_ul: Include underlying in Monte Carlo simulation

    Example:
        assumptions = GlobalAssumptions(spot_price=420.0, volatility=0.25)
        assumptions.display()

        # Access current values
        spot = assumptions.spot_price.value
        vol = assumptions.volatility.value

        # Register callback for changes
        assumptions.on_change(my_update_function)
    """

    def __init__(
        self,
        spot_price: float = 100.0,
        volatility: float = 0.25,
        risk_free_rate: float = 0.05,
        dividend_yield: float = 0.0,
        valuation_date: Optional[datetime] = None,
        spot_range_pct: float = 30.0,
        vol_range: Tuple[float, float] = (0.05, 1.00),
    ):
        """
        Initialize global assumptions panel.

        Args:
            spot_price: Initial spot price
            volatility: Initial volatility
            risk_free_rate: Risk-free rate
            dividend_yield: Dividend yield
            valuation_date: Valuation date (defaults to today)
            spot_range_pct: Range for spot slider (+/- %)
            vol_range: Min/max for volatility slider
        """
        if valuation_date is None:
            valuation_date = datetime.now()

        # Market parameters
        spot_min = spot_price * (1 - spot_range_pct / 100)
        spot_max = spot_price * (1 + spot_range_pct / 100)

        self.spot_price = widgets.FloatSlider(
            value=spot_price,
            min=spot_min,
            max=spot_max,
            step=spot_price * 0.01,
            description="Spot Price:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
            readout_format=".2f",
        )

        self.volatility = widgets.FloatSlider(
            value=volatility,
            min=vol_range[0],
            max=vol_range[1],
            step=0.01,
            description="Volatility:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
            readout_format=".1%",
        )

        self.risk_free_rate = widgets.FloatSlider(
            value=risk_free_rate,
            min=0.0,
            max=0.10,
            step=0.0025,
            description="Risk-Free Rate:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
            readout_format=".2%",
        )

        self.dividend_yield = widgets.FloatSlider(
            value=dividend_yield,
            min=0.0,
            max=0.05,
            step=0.0025,
            description="Dividend Yield:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
            readout_format=".2%",
        )

        self.valuation_date = widgets.DatePicker(
            value=valuation_date.date(),
            description="Valuation Date:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
        )

        # Time horizon selector
        time_horizon_options = [
            ("Today (T+0)", 0),
            ("1 Week (T+7)", const.DAYS_PER_WEEK),
            ("1 Month (T+30)", const.CALENDAR_DAYS_PER_MONTH),
            ("2 Months (T+60)", const.CALENDAR_DAYS_PER_MONTH * 2),
            ("3 Months (T+90)", const.CALENDAR_DAYS_PER_MONTH * 3),
            ("6 Months (T+180)", const.CALENDAR_DAYS_PER_MONTH * 6),
            ("9 Months (T+270)", const.CALENDAR_DAYS_PER_MONTH * 9),
            ("1 Year (T+365)", const.DAYS_PER_YEAR),
            ("1.5 Years (T+545)", int(const.DAYS_PER_YEAR * 1.5)),
            ("2 Years (T+730)", const.DAYS_PER_YEAR * 2),
            ("Custom", -1),
        ]

        self.time_horizon = widgets.Dropdown(
            options=time_horizon_options,
            value=0,
            description="Time Horizon:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="350px"),
        )

        self.custom_days = widgets.IntText(
            value=30,
            description="Custom Days:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="250px"),
            disabled=True,
        )

        # Link time horizon selector to custom days field
        def on_horizon_change(change):
            if change["new"] == -1:
                self.custom_days.disabled = False
            else:
                self.custom_days.disabled = True

        self.time_horizon.observe(on_horizon_change, "value")

        # Scenario grid parameters
        self.spot_shock_pct = widgets.FloatSlider(
            value=0.5,
            min=0.05,
            max=1.0,
            step=0.05,
            description="Spot Shock:",
            style={"description_width": "200px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
            readout_format=".0%",
        )

        self.vol_shock_pct = widgets.FloatSlider(
            value=0.5,
            min=0.05,
            max=1,
            step=0.1,
            description="Vol Shock:",
            style={"description_width": "200px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
            readout_format=".0%",
        )

        self.grid_resolution = widgets.IntSlider(
            value=25,
            min=10,
            max=50,
            step=5,
            description="Grid Resolution:",
            style={"description_width": "200px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
        )

        self.monte_carlo_num_sims = widgets.FloatLogSlider(
            value=10**5,
            base=10,
            min=3,  # min exponent of base
            max=8,  # max exponent of base
            step=0.1,  # exponent step
            description="No. of Monte Carlo Simulations",
            style={"description_width": "200px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
            readout_format=",.0f",
        )

        self.monte_carlo_inc_ul = widgets.Checkbox(
            value=True,
            disabled=False,
            indent=True,
            description="Include underlying in MC simulation",
            style={"description_width": "200px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
        )

        # Callbacks registry
        self._callbacks: List[Callable] = []

        # Register observers for all widgets
        for widget_attr in [
            "spot_price",
            "volatility",
            "risk_free_rate",
            "dividend_yield",
            "valuation_date",
            "time_horizon",
            "custom_days",
            "spot_shock_pct",
            "vol_shock_pct",
            "grid_resolution",
            "monte_carlo_num_sims",
            "monte_carlo_inc_ul",
        ]:
            getattr(self, widget_attr).observe(self._notify_callbacks, "value")

    def _notify_callbacks(self, change):
        """Notify all registered callbacks when any parameter changes."""
        for callback in self._callbacks:
            callback(change)

    def on_change(self, callback: Callable):
        """
        Register a callback to be called when any parameter changes.

        Args:
            callback: Function to call with change dict
        """
        self._callbacks.append(callback)

    def get_days_forward(self) -> int:
        """
        Get the selected number of days forward.

        Returns:
            Days forward based on time horizon selector
        """
        if self.time_horizon.value == -1:
            return self.custom_days.value
        return self.time_horizon.value

    @property
    def time_horizon_days(self):
        """
        Property to get the selected number of days forward.

        This is a convenience property that wraps get_days_forward()
        to match the expected interface in the notebook.

        Returns:
            Widget-like object with a 'value' attribute containing the days forward
        """
        return SimpleNamespace(value=self.get_days_forward())

    def get_valuation_date_forward(self) -> datetime:
        """
        Get the future valuation date based on time horizon.

        Returns:
            Future datetime based on selected horizon
        """
        val_date = datetime.combine(
            self.valuation_date.value, datetime.min.time()
        )
        return val_date + timedelta(days=self.get_days_forward())

    def to_dict(self) -> Dict[str, Any]:
        """
        Export current assumptions as dictionary.

        Returns:
            Dictionary with all current parameter values
        """
        return {
            "spot_price": self.spot_price.value,
            "volatility": self.volatility.value,
            "risk_free_rate": self.risk_free_rate.value,
            "dividend_yield": self.dividend_yield.value,
            "valuation_date": self.valuation_date.value,
            "time_horizon_days": self.get_days_forward(),
            "spot_shock_pct": self.spot_shock_pct.value,
            "vol_shock_pct": self.vol_shock_pct.value,
            "grid_resolution": self.grid_resolution.value,
            "monte_carlo_num_sims": self.monte_carlo_num_sims.value,
            "monte_carlo_inc_ul": self.monte_carlo_inc_ul.value,
        }

    def display(self) -> widgets.VBox:
        """
        Create and return the display widget.

        Returns:
            VBox widget containing all assumption controls
        """
        market_section = widgets.VBox(
            [
                widgets.HTML("<h4>Market Parameters</h4>"),
                self.spot_price,
                self.volatility,
                self.risk_free_rate,
                self.dividend_yield,
                self.valuation_date,
            ]
        )

        time_section = widgets.VBox(
            [
                widgets.HTML(
                    "<h4>Time Horizon: Days Forward From Valuation Date</h4>"
                ),
                widgets.HBox([self.time_horizon, self.custom_days]),
            ]
        )

        scenario_selectors = widgets.VBox(
            [
                self.spot_shock_pct,
                self.vol_shock_pct,
                self.grid_resolution,
                self.monte_carlo_num_sims,
                self.monte_carlo_inc_ul,
            ]
        )
        scenario_section = widgets.Accordion(children=[scenario_selectors])
        scenario_section.set_title(0, "Scenario Grid Parameters (Expand)")
        scenario_section.selected_index = None  # Collapsed by dfault

        return widgets.VBox(
            [
                widgets.HTML(
                    '<div style="background-color:#0F4761; color:white; '
                    'padding:10px; border-radius:5px; margin-bottom:10px;">'
                    '<h3 style="margin:0;">Global Assumptions Panel</h3>'
                    '<p style="margin:5px 0 0 0; font-size:14px;">'
                    "Single source of truth for all market parameters</p>"
                    "</div>"
                ),
                market_section,
                time_section,
                scenario_section,
            ],
            layout=widgets.Layout(
                border="2px solid #0F4761", padding="15px", margin="10px 0"
            ),
        )


class NetHedgeSummary:
    """
    Always-visible KPI header showing key portfolio hedge metrics.

    Displays core Greeks, crash convexity indicators, and probabilistic
    stats in a compact, color-coded format. Designed to be shown at the
    top of all dashboard modes for at-a-glance portfolio health.

    Attributes:
        portfolio: OptionPortfolio instance to analyze
        widget: VBox containing the KPI display

    Example:
        summary = NetHedgeSummary(portfolio)
        summary.display()

        # Update when portfolio changes
        summary.update()
    """

    def __init__(self, portfolio):
        """
        Initialize net hedge summary widget.

        Args:
            portfolio: OptionPortfolio instance
        """
        self.portfolio = portfolio
        self.widget = None
        self._create_widget()

    def _format_large_block(
        self, color: str, text_color: str, name: str, value_str: str
    ) -> str:
        """
        Return formatted HTML for large block
        """
        return (
            f'<div style="display:inline-block; background-color:{color}; '
            f"color:{text_color}; padding:8px 12px; margin:5px; "
            f'border-radius:5px; font-weight:bold; min-width:120px;">'
            f'<div style="font-size:11px; opacity:0.9;">{name}</div>'
            f'<div style="font-size:16px;">{value_str}</div>'
            f"</div>"
        )

    def _format_greek(
        self,
        name: str,
        value: float,
        is_cost: bool = False,
        is_neutral: bool = False,
    ) -> str:
        """
        Format a Greek metric as colored HTML badge.

        Args:
            name: Greek name
            value: Greek value
            is_cost: Whether this represents a cost (red) vs profit (green)
            is_neutral: Whether to ignore the value and use a netural colour

        Returns:
            HTML string with formatted badge
        """
        boundary_1 = 10**6
        boundary_2 = 10**3

        matches_to_format_as_currency = ["Value", "Cost", "Theta"]
        format_as_currency = False
        if any(
            sub.lower() in (name or "").lower()
            for sub in matches_to_format_as_currency
        ):
            format_as_currency = True

        if abs(value) < 0.01:
            value_str = "~0" if not format_as_currency else "~$0"
        elif abs(value) >= boundary_1:
            value_str = (
                f"${value/boundary_1:,.2f}M"
                if format_as_currency
                else f"{value:,.0f}"
            )
        elif abs(value) >= boundary_2:
            value_str = (
                f"${value/boundary_2:,.2f}k"
                if format_as_currency
                else f"{value:,.1f}"
            )
        else:
            value_str = (
                f"${value:.2f}" if format_as_currency else f"{value:.2f}"
            )

        # Color coding
        if is_cost or value < 0 and not is_neutral:
            color = DEFAULT_PALETTE.negative
            text_color = DEFAULT_PALETTE.white
        elif value > 0 and not is_neutral:
            color = DEFAULT_PALETTE.positive
            text_color = DEFAULT_PALETTE.white
        else:
            color = DEFAULT_PALETTE.medium_grey
            text_color = DEFAULT_PALETTE.white

        return self._format_large_block(color, text_color, name, value_str)

    def _format_pct(
        self, name: str, value: float, is_neutral: bool = False
    ) -> str:
        """
        Format a percentage metric as colored HTML badge.

        Args:
            name: Percent metric name
            value: Percent metric value
            is_neutral: Whether to ignore the value and use a netural colour

        Returns:
            HTML string with formatted badge
        """
        boundary_1 = 10**1

        if abs(value) < 10**-4:
            value_str = "~0%"
        elif abs(value) >= boundary_1:
            value_str = f"{value/boundary_1*100:,.0f}%"
        else:
            value_str = f"{value*100:,.2f}%"

        # Color coding
        if value < 0 and not is_neutral:
            color = DEFAULT_PALETTE.negative
            text_color = DEFAULT_PALETTE.white
        elif value > 0 and not is_neutral:
            color = DEFAULT_PALETTE.positive
            text_color = DEFAULT_PALETTE.white
        else:
            color = DEFAULT_PALETTE.medium_grey
            text_color = DEFAULT_PALETTE.white

        return self._format_large_block(color, text_color, name, value_str)

    def _format_crash_indicator(self, shock_pct: float, pnl: float) -> str:
        """
        Format crash convexity indicator.

        Args:
            shock_pct: Spot price shock percentage
            pnl: P&L at that shock level

        Returns:
            HTML string with formatted indicator
        """
        if pnl >= 0:
            color = DEFAULT_PALETTE.positive
        elif pnl > -1000:
            color = DEFAULT_PALETTE.orange
        else:
            color = DEFAULT_PALETTE.negative

        return (
            f'<div style="display:inline-block; background-color:{color}; '
            f"color:white; padding:6px 10px; margin:3px; "
            f'border-radius:3px; font-size:12px; min-width:100px;">'
            f"<strong>{shock_pct:+.0f}%:</strong> ${pnl:,.0f}"
            f"</div>"
        )

    def _create_widget(self):
        """Create the KPI display widget."""
        self.value_metrics_html = widgets.HTML(value="")
        self.health_indicators_r1_html = widgets.HTML(value="")
        self.health_indicators_r2_html = widgets.HTML(value="")
        self.diagnostics_html = widgets.HTML(value="")
        self.vol_metrics_html = widgets.HTML(value="")
        self.crash_indicators_html = widgets.HTML(value="")
        self.prob_stats_html = widgets.HTML(value="")

        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    '<div style="background-color:#0F4761; color:white; '
                    'padding:10px; border-radius:5px 5px 0 0;">'
                    '<h3 style="margin:0;">Hedge Summary</h3>'
                    "</div>"
                ),
                widgets.HTML(
                    "<h4 style='margin:10px 10px 5px 10px;'>Portfolio Value</h4>"
                ),
                self.value_metrics_html,
                widgets.HTML(
                    "<h4 style='margin:10px 10px 5px 10px;'>Health Indicators</h4>"
                ),
                self.health_indicators_r1_html,
                self.health_indicators_r2_html,
                widgets.Accordion(
                    children=[
                        widgets.VBox(
                            [
                                self.diagnostics_html,
                                self.vol_metrics_html,
                                self.crash_indicators_html,
                            ]
                        ),
                    ],
                    titles=("Diagnostics (Expandable)",),
                ),
            ],
            layout=widgets.Layout(border="2px solid #0F4761", margin="10px 0"),
        )

        self.update()

    def update(self):
        """Update all metrics with current portfolio data."""
        stats = self.portfolio.summary_stats()
        vol_stats = get_volatility_stats(self.portfolio)

        value_html = (
            self._format_greek(
                "Underlying Value", stats["total_underlying_value"]
            )
            + self._format_greek("Option Value", stats["total_value"])
            + self._format_greek(
                "Total Portfolio Value", stats["total_portfolio_value"]
            )
        )
        self.value_metrics_html.value = (
            f'<div style="padding:10px;">{value_html}</div>'
        )

        # Crash convexity
        current_spot = self.portfolio.spot_price
        pnl_0 = self.portfolio.calculate_pnl_at_expiry(
            current_spot * 1.00, include_underlying=True
        )
        pnl_10 = self.portfolio.calculate_pnl_at_expiry(
            current_spot * 0.90, include_underlying=True
        )
        pnl_20 = self.portfolio.calculate_pnl_at_expiry(
            current_spot * 0.80, include_underlying=True
        )
        pnl_30 = self.portfolio.calculate_pnl_at_expiry(
            current_spot * 0.70, include_underlying=True
        )

        crash_html = (
            self._format_greek("Current Spot", pnl_0)
            + self._format_greek("Spot -10%", pnl_10)
            + self._format_greek("Spot -20%", pnl_20)
            + self._format_greek("Spot -30%", pnl_30)
        )
        self.crash_indicators_html.value = (
            f'<div style="padding:10px;">{crash_html}</div>'
        )

        # Core Greeks
        health_indicators_r1_html = (
            self._format_greek("Total Delta", stats["total_delta"])
            + self._format_greek("Net Delta", stats["net_delta"])
            + self._format_greek("Theta (Daily)", stats["total_theta"])
        )
        self.health_indicators_r1_html.value = (
            f'<div style="padding:10px;">{health_indicators_r1_html}</div>'
        )

        health_indicators_r2_html = (
            self._format_greek("Vega", stats["total_vega"])
            + self._format_greek("Gamma", stats["total_gamma"])
            + self._format_greek("P&L @ -20%", pnl_20)
        )
        self.health_indicators_r2_html.value = (
            f'<div style="padding:10px;">{health_indicators_r2_html}</div>'
        )

        diagnostics_html = (
            self._format_greek("Hedge Ratio", stats["hedge_ratio"])
            + self._format_greek("Delta Adj.", stats["delta_adjustment"])
            + self._format_greek("Rho", stats["total_rho"])
        )
        self.diagnostics_html.value = (
            f'<div style="padding:10px;">{diagnostics_html}</div>'
        )

        vol_html = (
            self._format_pct(
                "Min Vol", stats["volatility_min"], is_neutral=True
            )
            + self._format_pct(
                "Max Vol", stats["volatility_max"], is_neutral=True
            )
            + self._format_pct(
                "Vega-W.Avg Vol", vol_stats["avg_volatility"], is_neutral=True
            )
            + self._format_greek(
                "Custom Vol Count",
                stats["custom_volatility_count"],
                is_neutral=True,
            )
        )
        self.vol_metrics_html.value = (
            f'<div style="padding:10px;">{vol_html}</div>'
        )

        # Probabilistic stats (expandable)
        analysis = self.portfolio.risk_reward_analysis()

        prob_html = "<div style='padding:10px;'>"

        # Check if Monte Carlo results exist
        mc_results = self.portfolio.monte_carlo_results
        if (
            mc_results is not None
            and len(mc_results.get("simulated_pnls", [])) > 0
        ):
            expected_pnl = mc_results.get("expected_pnl", 0)
            # Key is 'prob_profit' not 'probability_of_profit'
            prob_profit = mc_results.get("prob_profit", 0)
            prob_html += f"<p><strong>Probability of Profit:</strong> {prob_profit*100:.1f}%</p>"
            prob_html += (
                f"<p><strong>Expected Value:</strong> ${expected_pnl:,.2f}</p>"
            )
        else:
            prob_html += "<p><strong>Probability of Profit:</strong> N/A (requires Monte Carlo)</p>"
            prob_html += "<p><strong>Expected Value:</strong> N/A (requires Monte Carlo)</p>"

        max_loss_opt = analysis.get("max_loss_options", None)
        max_loss_total = analysis.get("max_loss_total", None)
        max_loss_result = "<p><strong>Max Loss:</strong> Options: "
        if max_loss_opt is None:
            max_loss_result += "N/A"
        elif not max_loss_opt.get("is_unlimited", True):
            max_loss_result += f"${-max_loss_opt.get('max_loss', 0):,.2f}"
        else:
            max_loss_result += "Unlimited"

        max_loss_result += ";&nbsp;&nbsp;&nbsp;Total: "
        if max_loss_total is None:
            max_loss_result += "N/A"
        elif not max_loss_total.get("is_unlimited", True):
            max_loss_result += f"${-max_loss_total.get('max_loss', 0):,.2f}"
        else:
            max_loss_result += "Unlimited"
        max_loss_result += "</p>"
        prob_html += max_loss_result

        max_profit_opt = analysis.get("max_profit_options", None)
        max_profit_total = analysis.get("max_profit_total", None)
        max_profit_result = "<p><strong>Max Profit:</strong> Options: "
        if max_profit_opt is None:
            max_profit_result += "N/A"
        elif not max_profit_opt.get("is_unlimited", True):
            max_profit_result += f"${-max_profit_opt.get('max_profit', 0):,.2f}"
        else:
            max_profit_result += "Unlimited"

        max_profit_result += ";&nbsp;&nbsp;&nbsp;Total: "
        if max_profit_total is None:
            max_profit_result += "N/A"
        elif not max_profit_total.get("is_unlimited", True):
            max_profit_result += (
                f"${-max_profit_total.get('max_profit', 0):,.2f}"
            )
        else:
            max_profit_result += "Unlimited"
        max_profit_result += "</p>"
        prob_html += max_profit_result

        breakevens = analysis.get("breakeven_total", [])
        if breakevens:
            be_str = ", ".join([f"${be:.2f}" for be in breakevens])
        else:
            be_str = "N/A"
        prob_html += f"<p><strong>Breakeven Points:</strong> {be_str}</p>"

        prob_html += "</div>"
        self.prob_stats_html.value = prob_html

    def display(self) -> Union[widgets.VBox, None]:
        """
        Get the display widget.

        Returns:
            VBox widget containing the KPI summary
        """
        return self.widget


class PortfolioWidgets:
    """
    Comprehensive widget creation utilities for portfolio analysis.

    This class provides factory methods for creating standardized, reusable
    widgets for common portfolio management tasks.

    Attributes:
        portfolio: OptionPortfolio instance to manage
        export_dir: Directory path for import/export operations
    """

    def __init__(
        self,
        portfolio,
        export_dir: Optional[Union[Path, str]] = None,
    ):
        """
        Initialize widget factory.

        Args:
            portfolio: OptionPortfolio instance
            export_dir: Directory for exports (default: None)
        """
        self.portfolio = portfolio
        self._export_dir = None
        if export_dir:
            self.export_dir = Path(export_dir)

    @property
    def export_dir(self) -> Path:
        """Get the current export directory."""
        if self._export_dir is None:
            raise ValueError(
                "Export directory is not set. Please select a directory first."
            )
        return self._export_dir

    @export_dir.setter
    def export_dir(self, value: Union[Path, str]):
        """Set the export directory and ensure it exists."""
        if value is None:
            self._export_dir = None
            return

        path = Path(value)
        # Create directory if it doesn't exist
        path.mkdir(parents=True, exist_ok=True)
        self._export_dir = path

    # ==========================================================================
    # Position Management Widgets
    # ==========================================================================

    def create_position_selector(
        self,
        description: str = "Select Position:",
        width: str = "500px",
        include_index: bool = True,
    ) -> "Dropdown":
        """
        Create dropdown for position selection.

        Args:
            description: Widget label
            width: Widget width CSS value
            include_index: Whether to include position index in display

        Returns:
            Dropdown widget populated with current positions
        """
        positions = self.portfolio.get_positions()

        if not positions:
            options = ["No positions"]
            disabled = True
        else:
            if include_index:
                options = [
                    f"{i}: {p['symbol']} - {p['type']} {p['strike']} @ {p['expiry']}"
                    for i, p in enumerate(positions)
                ]
            else:
                options = [
                    f"{p['symbol']} - {p['type']} {p['strike']} @ {p['expiry']}"
                    for p in positions
                ]
            disabled = False

        return widgets.Dropdown(
            options=options,
            description=description,
            style={"description_width": "120px"},
            layout=widgets.Layout(width=width),
            disabled=disabled,
        )

    def create_position_editor(
        self, on_change_callback: Optional[Callable] = None
    ) -> "VBox":
        """
        Create complete position editor interface.

        Provides widgets for adding, updating, and removing positions with
        proper event handling and validation.

        Args:
            on_change_callback: Optional callback when portfolio changes

        Returns:
            VBox widget containing the complete editor interface
        """
        # Position selector
        position_selector = widgets.Dropdown(
            options=["No positions"],
            description="Position:",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="500px"),
            disabled=True,
        )

        # Input fields
        quantity_input = widgets.IntText(
            value=1,
            description="Quantity:",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="300px"),
        )

        strike_input = widgets.FloatText(
            value=100.0,
            description="Strike:",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="300px"),
        )

        option_type_selector = widgets.Dropdown(
            options=["Call", "Put"],
            value="Call",
            description="Type:",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="300px"),
        )

        expiry_input = widgets.DatePicker(
            value=datetime.now().date() + timedelta(days=30),
            description="Expiry:",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="300px"),
        )

        # Volatility input
        volatility_input = widgets.FloatText(
            value=self.portfolio.volatility,
            description="Volatility:",
            min=0.01,
            max=2.0,
            step=0.01,
            style={"description_width": "120px"},
            layout=widgets.Layout(width="300px"),
        )

        use_default_vol = widgets.Checkbox(
            value=True,
            description="Use portfolio default volatility",
            style={"description_width": "initial"},
        )

        # Link checkbox to volatility input disabled state
        def on_checkbox_change(change):
            volatility_input.disabled = change["new"]
            if change["new"]:
                volatility_input.value = self.portfolio.volatility

        use_default_vol.observe(on_checkbox_change, "value")
        volatility_input.disabled = True  # Initially disabled

        # Action buttons
        add_button = widgets.Button(
            description="Add Position",
            button_style="success",
            layout=widgets.Layout(width="150px"),
        )

        update_button = widgets.Button(
            description="Update Position",
            button_style="info",
            layout=widgets.Layout(width="150px"),
        )

        remove_button = widgets.Button(
            description="Remove Position",
            button_style="danger",
            layout=widgets.Layout(width="150px"),
        )

        status_label = widgets.Label(value="")
        output = widgets.Output()

        # Helper functions
        def get_position_display_string(pos):
            """Generate consistent display string for a position."""
            result = f"{pos.symbol} - {pos.option.option_type.capitalize()} "
            result += f"{pos.option.strike_price} @ "
            result += f"{pos.option.maturity_date.date()}"
            return result

        def refresh_position_list():
            """Update dropdown with current positions."""
            if self.portfolio.positions:
                position_selector.options = [
                    get_position_display_string(pos)
                    for pos in self.portfolio.positions
                ]
                position_selector.disabled = False
            else:
                position_selector.options = ["No positions"]
                position_selector.disabled = True

        def on_position_selected(change):  # pylint: disable=unused-argument
            """Load selected position data into input fields."""
            if (
                position_selector.value
                and position_selector.value != "No positions"
            ):
                # Find the matching position
                for pos in self.portfolio.positions:
                    if position_selector.value == get_position_display_string(
                        pos
                    ):
                        quantity_input.value = pos.quantity
                        strike_input.value = pos.option.strike_price
                        option_type_selector.value = (
                            "Call"
                            if pos.option.option_type.lower() == "call"
                            else "Put"
                        )
                        expiry_input.value = pos.option.maturity_date.date()
                        # Update volatility input based on position
                        volatility_input.value = pos.option.volatility
                        use_default_vol.value = not pos.custom_volatility
                        break

        def on_add_clicked(b):  # pylint: disable=unused-argument
            """Add a new position."""
            try:
                # Determine volatility parameter
                position_volatility = (
                    None if use_default_vol.value else volatility_input.value
                )

                self.portfolio.add_position(
                    strike_price=strike_input.value,
                    maturity_date=datetime.combine(
                        expiry_input.value, datetime.min.time()
                    ),
                    option_type=(
                        "call"
                        if option_type_selector.value == "Call"
                        else "put"
                    ),
                    quantity=quantity_input.value,
                    symbol="SPY",
                    volatility=position_volatility,
                )
                status_label.value = (
                    f"✓ Added {quantity_input.value} "
                    + f"{option_type_selector.value} @ {strike_input.value}"
                )
                refresh_position_list()
                with output:
                    output.clear_output()
                    print(self.portfolio.summary())

                if on_change_callback:
                    on_change_callback()
            except Exception as e:  # pylint: disable=broad-except
                status_label.value = f"✗ Error: {str(e)}"

        def on_remove_clicked(b):  # pylint: disable=unused-argument
            """Remove selected position."""
            if (
                position_selector.value
                and position_selector.value != "No positions"
            ):
                try:
                    # Find the matching position index
                    for i, pos in enumerate(self.portfolio.positions):
                        if (
                            position_selector.value
                            == get_position_display_string(pos)
                        ):
                            self.portfolio.remove_position(i)
                            status_label.value = (
                                f"✓ Removed position {position_selector.value}"
                            )
                            refresh_position_list()
                            with output:
                                output.clear_output()
                                print(self.portfolio.summary())

                            if on_change_callback:
                                on_change_callback()
                            break
                except Exception as e:  # pylint: disable=broad-except
                    status_label.value = f"✗ Error: {str(e)}"

        def on_update_clicked(b):  # pylint: disable=unused-argument
            """Update selected position."""
            if (
                position_selector.value
                and position_selector.value != "No positions"
            ):
                try:
                    # Find the matching position index
                    for i, pos in enumerate(self.portfolio.positions):
                        if (
                            position_selector.value
                            == get_position_display_string(pos)
                        ):
                            # Determine volatility parameter
                            position_volatility = (
                                None
                                if use_default_vol.value
                                else volatility_input.value
                            )

                            self.portfolio.update_position(
                                i,
                                quantity=quantity_input.value,
                                strike=strike_input.value,
                                expiry=datetime.combine(
                                    expiry_input.value, datetime.min.time()
                                ),
                                option_type=(
                                    "call"
                                    if option_type_selector.value == "Call"
                                    else "put"
                                ),
                                volatility=position_volatility,
                            )
                            status_label.value = (
                                f"✓ Updated position {position_selector.value}"
                            )
                            refresh_position_list()
                            with output:
                                output.clear_output()
                                print(self.portfolio.summary())

                            if on_change_callback:
                                on_change_callback()
                            break
                except Exception as e:  # pylint: disable=broad-except
                    status_label.value = f"✗ Error: {str(e)}"

        # Connect event handlers
        position_selector.observe(on_position_selected, names="value")
        add_button.on_click(on_add_clicked)
        remove_button.on_click(on_remove_clicked)
        update_button.on_click(on_update_clicked)

        # Initial refresh
        refresh_position_list()

        # Assemble interface
        return widgets.VBox(
            [
                widgets.HTML("<h3>Position Management</h3>"),
                position_selector,
                widgets.HBox([quantity_input, strike_input]),
                widgets.HBox([option_type_selector, expiry_input]),
                widgets.HBox([volatility_input, use_default_vol]),
                widgets.HBox([add_button, update_button, remove_button]),
                status_label,
                output,
            ]
        )

    # ==========================================================================
    # Market Parameter Widgets
    # ==========================================================================

    def create_market_params_controls(
        self,
        spot_price: float,
        volatility: float,
        spot_range: float = 0.3,
        vol_range: Tuple[float, float] = (0.05, 0.5),
        continuous_update: bool = False,
    ) -> Dict[str, Any]:
        """
        Create slider controls for market parameters.

        Args:
            spot_price: Current spot price (for centering slider)
            volatility: Current volatility (for centering slider)
            spot_range: Range for spot price slider (±%)
            vol_range: Min/max for volatility slider
            continuous_update: Whether sliders update continuously or on release

        Returns:
            Dictionary containing 'spot' and 'vol' slider widgets
        """
        spot_min = spot_price * (1 - spot_range)
        spot_max = spot_price * (1 + spot_range)

        spot_slider = widgets.FloatSlider(
            value=spot_price,
            min=spot_min,
            max=spot_max,
            step=spot_price * 0.01,  # 1% steps
            description="Spot Price:",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=continuous_update,
            readout_format=".2f",
        )

        vol_slider = widgets.FloatSlider(
            value=volatility,
            min=vol_range[0],
            max=vol_range[1],
            step=0.01,
            description="Volatility:",
            style={"description_width": "120px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=continuous_update,
            readout_format=".2%",
        )

        return {"spot": spot_slider, "vol": vol_slider}

    # ==========================================================================
    # Scenario Analysis Widgets
    # ==========================================================================

    def create_date_selector(
        self,
        max_days: Optional[int] = None,
        description: str = "Valuation Date:",
        num_steps: int = 10,
    ) -> widgets.SelectionSlider:
        """
        Create date selection slider for scenario analysis.

        Args:
            max_days: Maximum days forward (None = use last expiry)
            description: Widget label
            num_steps: Number of date options to display

        Returns:
            SelectionSlider widget with date options
        """
        if max_days is None:
            # Use last option expiry
            if self.portfolio.positions:
                max_maturity = max(
                    pos.option.maturity_date for pos in self.portfolio.positions
                )
                max_days = (max_maturity - self.portfolio.valuation_date).days

        if max_days is None:
            max_days = 90  # Default fallback

        max_days = max(1, max_days)
        step_size = max(1, max_days // num_steps)
        date_range_days = list(range(0, max_days + 1, step_size))

        # Ensure max_days is included
        if max_days not in date_range_days and max_days > 0:
            date_range_days.append(max_days)

        date_options = [
            (
                f"Day {d}: "
                + f"{(self.portfolio.valuation_date + timedelta(days=d)).strftime('%Y-%m-%d')}",
                d,
            )
            for d in date_range_days
        ]

        return widgets.SelectionSlider(
            options=date_options,
            value=0,
            description=description,
            style={"description_width": "150px"},
            layout=widgets.Layout(width="700px"),
            continuous_update=False,
        )

    def create_metric_selector(
        self,
        metrics: Optional[List[Tuple[str, str]]] = None,
        description: str = "Metric:",
        default: str = "pnl",
    ) -> widgets.Dropdown:
        """
        Create metric selection dropdown.

        Args:
            metrics: List of (display_name, value) tuples (None = default set)
            description: Widget label
            default: Default selected metric

        Returns:
            Dropdown widget for metric selection
        """
        if metrics is None:
            metrics = [
                ("Portfolio P&L", "pnl"),
                ("Portfolio Value", "value"),
                ("Net Delta", "net_delta"),
                ("Total Theta", "theta"),
                ("Total Gamma", "gamma"),
                ("Total Vega", "vega"),
                ("Total Rho", "rho"),
            ]

        return widgets.Dropdown(
            options=metrics,
            value=default,
            description=description,
            style={"description_width": "100px"},
            layout=widgets.Layout(width="350px"),
        )

    def create_price_range_slider(
        self,
        description: str = "Price Range (%):",
        default: float = 20.0,
        min_val: float = 5.0,
        max_val: float = 50.0,
        step: float = 5.0,
    ) -> widgets.FloatSlider:
        """
        Create price range slider for scenario analysis.

        Args:
            description: Widget label
            default: Default value
            min_val: Minimum value
            max_val: Maximum value
            step: Step size

        Returns:
            FloatSlider widget
        """
        return widgets.FloatSlider(
            value=default,
            min=min_val,
            max=max_val,
            step=step,
            description=description,
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
        )

    # ==========================================================================
    # Transaction Cost Widgets
    # ==========================================================================

    def create_transaction_cost_controls(
        self, default_slippage_bps: int = 10, default_commission: float = 0.65
    ) -> Dict[str, Any]:
        """
        Create transaction cost parameter controls.

        Args:
            default_slippage_bps: Default slippage in basis points
            default_commission: Default commission per contract

        Returns:
            Dictionary with 'slippage' and 'commission' widgets
        """
        slippage_widget = widgets.IntSlider(
            value=default_slippage_bps,
            min=0,
            max=100,
            step=5,
            description="Slippage (bps):",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
        )

        commission_widget = widgets.FloatText(
            value=default_commission,
            min=0.0,
            max=10.0,
            step=0.05,
            description="Commission/Contract:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="300px"),
        )

        return {"slippage": slippage_widget, "commission": commission_widget}

    def create_target_hedge_slider(
        self, current_ratio: float = 100.0, description: str = "Target Hedge %:"
    ) -> widgets.IntSlider:
        """
        Create target hedge ratio slider.

        Args:
            current_ratio: Current hedge ratio for default value
            description: Widget label

        Returns:
            IntSlider widget
        """
        return widgets.IntSlider(
            value=int(current_ratio),
            min=0,
            max=200,
            step=10,
            description=description,
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
        )

    # ==========================================================================
    # Roll Analysis Widgets
    # ==========================================================================

    def create_roll_controls(
        self, default_days_forward: int = 30
    ) -> Dict[str, Any]:
        """
        Create complete roll analysis control panel.

        Args:
            default_days_forward: Default days forward for new maturity

        Returns:
            Dictionary with all roll-related widgets
        """
        position_selector = widgets.Dropdown(
            options=["Select Position..."]
            + [
                f"{i}: {p.option.option_type.upper()} K={p.option.strike_price} "
                f"Exp={p.option.maturity_date.strftime('%Y-%m-%d')} Qty={p.quantity}"
                for i, p in enumerate(self.portfolio.positions)
            ],
            value="Select Position...",
            description="Position to Roll:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="700px"),
        )

        roll_type = widgets.RadioButtons(
            options=[
                ("Extend Maturity (Same Strike)", "time"),
                ("Adjust Strike (Same Maturity)", "strike"),
                ("Both Strike & Maturity", "both"),
            ],
            value="time",
            description="Roll Type:",
            style={"description_width": "150px"},
        )

        new_strike = widgets.FloatText(
            value=100.0,
            description="New Strike:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="300px"),
        )

        new_maturity = widgets.DatePicker(
            value=datetime.now().date() + timedelta(days=default_days_forward),
            description="New Maturity:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="400px"),
        )

        new_quantity = widgets.IntText(
            value=0,
            description="New Quantity:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="300px"),
        )

        analyze_button = widgets.Button(
            description="Analyze Roll",
            button_style="info",
            icon="calculator",
            layout=widgets.Layout(width="150px"),
        )

        commit_button = widgets.Button(
            description="Commit Roll",
            button_style="success",
            icon="check",
            layout=widgets.Layout(width="150px"),
            disabled=True,
        )

        return {
            "position_selector": position_selector,
            "roll_type": roll_type,
            "new_strike": new_strike,
            "new_maturity": new_maturity,
            "new_quantity": new_quantity,
            "analyze_button": analyze_button,
            "commit_button": commit_button,
        }

    # ==========================================================================
    # Import/Export Widgets
    # ==========================================================================

    def create_export_controls(
        self, default_format: str = "JSON"
    ) -> Dict[str, Any]:
        """
        Create export format selection and execution controls.

        Args:
            default_format: Default export format ('JSON', 'CSV', or 'YAML')

        Returns:
            Dictionary with export-related widgets
        """
        format_selector = widgets.RadioButtons(
            options=["JSON", "CSV", "YAML"],
            value=default_format,
            description="Export Format:",
            style={"description_width": "150px"},
        )

        filename_input = widgets.Text(
            value="portfolio_snapshot",
            description="Filename:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="400px"),
            placeholder="Enter filename (without extension)",
        )

        export_button = widgets.Button(
            description="Export Portfolio",
            button_style="success",
            icon="download",
            layout=widgets.Layout(width="200px"),
        )

        return {
            "format_selector": format_selector,
            "filename_input": filename_input,
            "export_button": export_button,
        }

    def create_import_controls(self) -> Dict[str, Any]:
        """
        Create import file selection and preview controls.

        Returns:
            Dictionary with import-related widgets
        """
        filename_input = widgets.Text(
            value="portfolio_book.json",
            description="Filename:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="400px"),
        )

        file_select = widgets.FileUpload(
            accept=".json,.yaml,.yml",
            button_style="danger",
            multiple=False,
            description="Select File:",
            style={"description_width": "150px"},
        )

        preview_button = widgets.Button(
            description="Preview File",
            button_style="danger",
            icon="eye",
            layout=widgets.Layout(width="150px"),
        )

        import_button = widgets.Button(
            description="Import Portfolio",
            button_style="danger",
            icon="upload",
            layout=widgets.Layout(width="150px"),
        )

        return {
            "filename_input": filename_input,
            "file_select": file_select,
            "preview_button": preview_button,
            "import_button": import_button,
        }

    def display_import(self) -> widgets.VBox:
        """
        Create and display import interface.

        Returns:
            VBox widget containing import controls
        """
        import_controls = self.create_import_controls()
        import_output = widgets.Output()

        # Import button handler
        def on_import_clicked(b):  # pylint: disable=unused-argument
            with import_output:
                import_output.clear_output()
                try:
                    filename = import_controls["filename_input"].value
                    # Auto-detect format handled by import_portfolio

                    filepath = self.export_dir / filename

                    if not filepath.exists():
                        print(f"✗ File not found: {filepath}")
                        return

                    imported_portfolio = import_portfolio(str(filepath))[
                        "portfolio"
                    ]
                    if not isinstance(imported_portfolio, OptionPortfolio):
                        print(
                            "✗ Import failed: Expected OptionPortfolio, "
                            + f"got {type(imported_portfolio)}"
                        )
                        return

                    # Copy all attributes from imported to current
                    self.portfolio.positions = imported_portfolio.positions
                    self.portfolio.spot_price = imported_portfolio.spot_price
                    self.portfolio.volatility = imported_portfolio.volatility
                    self.portfolio.risk_free_rate = (
                        imported_portfolio.risk_free_rate
                    )
                    self.portfolio.dividend_yield = (
                        imported_portfolio.dividend_yield
                    )
                    self.portfolio.valuation_date = (
                        imported_portfolio.valuation_date
                    )
                    self.portfolio.underlying_quantity = (
                        imported_portfolio.underlying_quantity
                    )

                    print(f"✓ Loaded {len(self.portfolio.positions)} positions")
                    import_controls["import_button"].button_style = "success"

                except Exception as e:  # pylint: disable=broad-except
                    print(f"✗ Import failed: {e}")
                    import_controls["import_button"].button_style = "danger"

        # Preview button handler
        def on_preview_clicked(b):  # pylint: disable=unused-argument
            with import_output:
                import_output.clear_output()
                try:
                    filename = import_controls["filename_input"].value
                    filepath = self.export_dir / filename

                    if not filepath.exists():
                        print(f"✗ File not found: {filepath}")
                        return

                    # Load into a temporary portfolio to inspect content
                    print(f"Loading portfolio from {filepath}...")
                    preview_portfolio = import_portfolio(str(filepath))[
                        "portfolio"
                    ]

                    if not isinstance(preview_portfolio, OptionPortfolio):
                        print(
                            f"✗ Invalid portfolio file: {type(preview_portfolio)}"
                        )
                        return

                    # Extract summary details
                    positions_count = len(preview_portfolio.positions)
                    symbol = preview_portfolio.get_symbol()

                    print(f"Previewing Portfolio: {filename}")
                    print("-" * 50)
                    print(f"Symbol:              {symbol}")
                    print(
                        f"Risk-Free Rate:      {preview_portfolio.risk_free_rate:.2%}"
                    )
                    print(
                        f"Spot Price:          {preview_portfolio.spot_price:.2f}"
                    )
                    print(
                        f"Underlying Quantity: {preview_portfolio.underlying_quantity:.0f}"
                    )
                    print(f"Number of Positions: {positions_count}")
                    print("-" * 50)
                    import_controls["preview_button"].button_style = "success"

                except Exception as e:  # pylint: disable=broad-except
                    print(f"✗ Preview failed: {e}")
                    import_controls["preview_button"].button_style = "danger"

        # File upload handler
        def on_file_upload(change):
            if not change["new"]:
                return

            with import_output:
                import_output.clear_output()
                try:
                    uploaded = change["new"]
                    # Handle both ipywidgets 7 and 8 formats
                    if isinstance(uploaded, dict):
                        # ipywidgets 7
                        fname = next(iter(uploaded))
                    else:
                        # ipywidgets 8 (tuple of dicts)
                        item = uploaded[0]
                        fname = item["name"]

                    # Do NOT write file to disk, just update filename input
                    import_controls["filename_input"].value = fname

                    # Construct potential path for display purposes (though
                    # FileUpload doesn't give full path)
                    potential_path = self.export_dir / fname
                    print(f"✓ Selected file: {fname}")
                    print(f"Target path: {potential_path}")
                    import_controls["file_select"].button_style = "success"

                    # Clear widget to allow re-uploading same file
                    # Note: clearing might trigger another event with empty
                    # value, hence the check at start
                    # import_controls["file_select"].value.clear()

                except Exception as e:  # pylint: disable=broad-except
                    print(f"✗ Selection failed: {e}")
                    import_controls["file_select"].button_style = "danger"

        # Connect button handlers
        import_controls["import_button"].on_click(on_import_clicked)
        import_controls["preview_button"].on_click(on_preview_clicked)
        import_controls["file_select"].observe(on_file_upload, names="value")

        action_buttons = widgets.HBox(
            [
                import_controls["file_select"],
                import_controls["preview_button"],
                import_controls["import_button"],
            ]
        )

        # Assemble interface
        import_section = widgets.VBox(
            [
                widgets.HTML("<h3>Import Portfolio</h3>"),
                import_controls["filename_input"],
                action_buttons,
                import_output,
            ]
        )

        return import_section

    def display_export(self) -> widgets.VBox:
        """
        Create and display export interface.

        Returns:
            VBox widget containing export controls
        """
        export_controls = self.create_export_controls()
        export_output = widgets.Output()

        # Export button handler
        def on_export_clicked(b):  # pylint: disable=unused-argument
            with export_output:
                export_output.clear_output()
                try:
                    filename = export_controls["filename_input"].value
                    file_format = export_controls[
                        "format_selector"
                    ].value.lower()

                    # Add extension if not present
                    if not filename.endswith(f".{file_format}"):
                        filename = f"{filename}.{file_format}"

                    filepath = self.export_dir / filename

                    if file_format == "json":
                        export_portfolio_to_json(self.portfolio, str(filepath))
                    elif file_format == "csv":
                        export_portfolio_to_csv(self.portfolio, str(filepath))
                    elif file_format == "yaml":
                        export_portfolio_to_yaml(self.portfolio, str(filepath))
                    else:
                        print(f"✗ Unknown format: {file_format}")
                        return

                    print(f"✓ Exported to {filepath}")

                except Exception as e:  # pylint: disable=broad-except
                    print(f"✗ Export failed: {e}")

        # Connect button handlers
        export_controls["export_button"].on_click(on_export_clicked)

        # Assemble interface
        export_section = widgets.VBox(
            [
                widgets.HTML("<h3>Export Portfolio</h3>"),
                export_controls["format_selector"],
                export_controls["filename_input"],
                export_controls["export_button"],
                export_output,
            ]
        )

        return export_section

    def create_export_dir_widget(
        self,
        show_browser: bool = True,
        on_change_callback: Optional[Callable[[Path], None]] = None,
    ) -> widgets.VBox:
        """
        Create an export-directory selection widget and keep `self.export_dir` in sync.

        Args:
            show_browser: Whether to show the "Open in Finder" button
            on_change_callback: Optional callback invoked with the new Path when changed

        Returns:
            VBox widget created by the shared config helper

        Notes:
            This wraps `deltadewa.config.create_export_dir_widget` so the dashboard
            can reuse the common UI while updating the PortfolioWidgets' `export_dir`.
        """

        def _on_change(export_dir: Path):
            # keep internal export_dir Path in sync
            try:
                self.export_dir = Path(export_dir)
            except Exception:  # pylint: disable=broad-except
                # ignore errors here; the config widget already reports failures
                pass

            if on_change_callback:
                on_change_callback(export_dir)

        # Use a default if export_dir is not set
        try:
            current_dir = str(self.export_dir)
        except ValueError:
            current_dir = str(Path.cwd() / "exports")

        # Use the existing config helper to build the UI; pass current export_dir
        return _create_export_dir_widget(
            default_dir=current_dir,
            on_change_callback=_on_change,
            show_browser=show_browser,
        )

    def display_export_dir_widget(
        self,
        show_browser: bool = True,
        on_change_callback: Optional[Callable[[Path], None]] = None,
    ) -> widgets.VBox:
        """
        Convenience display wrapper for the export-directory widget.

        Returns a small VBox containing a header and the export-dir selector
        so dashboards can simply call this method and `display(...)` the result.
        """

        widget = self.create_export_dir_widget(
            show_browser=show_browser, on_change_callback=on_change_callback
        )

        header = widgets.HTML("<h3>Export Directory</h3>")
        return widgets.VBox(
            [header, widget], layout=widgets.Layout(margin="8px 0")
        )

    # ==========================================================================
    # Heatmap Widgets
    # ==========================================================================

    def create_heatmap_controls(
        self, metrics: Optional[List[Tuple[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Create complete heatmap configuration controls.

        Args:
            metrics: List of (display_name, value) tuples for metric options

        Returns:
            Dictionary with heatmap control widgets
        """
        if metrics is None:
            metrics = [
                ("P&L", "pnl"),
                ("P&L (Options Only)", "pnl_options_only"),
                ("P&L % (Total)", "pnl_pct"),
                ("P&L % (Options Only)", "pnl_options_pct"),
                ("Net Delta", "net_delta"),
                ("Gamma", "gamma"),
                ("Theta (Daily)", "theta"),
                ("Vega", "vega"),
                ("Rho", "rho"),
            ]

        price_range_slider = self.create_price_range_slider()

        display_format = widgets.Dropdown(
            options=[("Dollar ($)", "dollar"), ("Percentage (%)", "percent")],
            value="dollar",
            description="Display Format:",
            style={"description_width": "150px"},
        )

        metric_selector = self.create_metric_selector(
            metrics=metrics, default="pnl"
        )

        date_selector = self.create_date_selector()

        return {
            "price_range": price_range_slider,
            "display_format": display_format,
            "metric_selector": metric_selector,
            "date_selector": date_selector,
        }

    # ==========================================================================
    # Interactive Dashboard
    # ==========================================================================

    def create_interactive_dashboard(
        self, spot_price: float, volatility: float, spot_range: float = 0.3
    ) -> Tuple[widgets.Widget, Dict[str, Any]]:
        """
        Create complete interactive dashboard with market controls.

        Args:
            spot_price: Current spot price
            volatility: Current volatility
            spot_range: Range for spot price slider (±%)

        Returns:
            Tuple of (dashboard_widget, controls_dict)
        """
        market_controls = self.create_market_params_controls(
            spot_price=spot_price,
            volatility=volatility,
            spot_range=spot_range,
            continuous_update=False,
        )

        output = InteractiveOutput()

        dashboard = widgets.VBox(
            [
                widgets.HTML("<h3>Interactive Market Scenario Dashboard</h3>"),
                widgets.HTML(
                    "<p>Adjust market parameters to see real-time portfolio impact</p>"
                ),
                market_controls["spot"],
                market_controls["vol"],
                output.widget,
            ]
        )

        return dashboard, {**market_controls, "output": output}

    # ==========================================================================
    # Utility Methods
    # ==========================================================================

    @staticmethod
    def create_section_header(
        title: str, subtitle: Optional[str] = None
    ) -> widgets.HTML:
        """
        Create formatted section header.

        Args:
            title: Section title
            subtitle: Optional subtitle/description

        Returns:
            HTML widget with formatted header
        """
        html = f"<h3>{title}</h3>"
        if subtitle:
            html += f'<p style="color: #666;">{subtitle}</p>'
        return widgets.HTML(html)

    @staticmethod
    def create_button_group(
        buttons: List[widgets.Button], layout: str = "horizontal"
    ) -> widgets.Widget:
        """
        Create group of buttons with consistent spacing.

        Args:
            buttons: List of button widgets
            layout: 'horizontal' or 'vertical'

        Returns:
            HBox or VBox containing the buttons
        """
        if layout == "horizontal":
            return widgets.HBox(buttons, layout=widgets.Layout(margin="5px"))
        else:
            return widgets.VBox(buttons, layout=widgets.Layout(margin="5px"))

    @staticmethod
    def create_two_column_layout(
        left_widgets: List[widgets.Widget], right_widgets: List[widgets.Widget]
    ) -> widgets.HBox:
        """
        Create two-column layout for widgets.

        Args:
            left_widgets: Widgets for left column
            right_widgets: Widgets for right column

        Returns:
            HBox with two VBox columns
        """
        left_column = widgets.VBox(
            left_widgets, layout=widgets.Layout(width="50%", padding="5px")
        )
        right_column = widgets.VBox(
            right_widgets, layout=widgets.Layout(width="50%", padding="5px")
        )
        return widgets.HBox([left_column, right_column])


class GaugeIndicator:
    """
    A visual gauge indicator bar with configurable color gradient and value marker.

    The gauge displays a horizontal or vertical bar with a color gradient transitioning
    through three key points (min, mid, max) between start and end values. An arrow
    or chevron marker indicates the actual value position.

    Color Gradient Logic:
        - From start to min: Full low_color
        - From min to mid: Gradient from low_color to mid_color
        - From mid to max: Gradient from mid_color to high_color
        - From max to end: Full high_color

    Example:
        With start=0, end=100, min=20, mid=30, max=50, and red-to-green colors:
        - 0-20: Full red
        - 20-30: Red fading to yellow (mid)
        - 30-50: Yellow transitioning to full green
        - 50-100: Full green

    Attributes:
        start: Minimum value of the gauge scale
        end: Maximum value of the gauge scale
        min_val: Value where low_color reaches full saturation
        mid_val: Value at the color midpoint
        max_val: Value where high_color reaches full saturation
        actual: The actual value to mark on the gauge
        low_color: Color for values at/below min_val (default: red)
        mid_color: Color for values at mid_val (default: yellow)
        high_color: Color for values at/above max_val (default: green)
        orientation: 'horizontal' or 'vertical'
        width: Width of the gauge in pixels (for horizontal) or bar width (for vertical)
        height: Height of the gauge in pixels (for vertical) or bar height (for horizontal)
        show_actual_label: Whether to display the actual value label
        show_minmidmax_labels: Whether to display min/mid/max value labels
        show_startend_labels: Whether to display start/end value labels
        label_format: Format string for numeric labels (default: '{:.1f}')
        title: Optional title for the gauge
    """

    def __init__(
        self,
        start: float,
        end: float,
        min_val: float,
        mid_val: float,
        max_val: float,
        actual: float,
        low_color: str = "#d73a49",  # Red (matches COLOUR_NEGATIVE)
        mid_color: str = "#f5a623",  # Yellow/Orange
        high_color: str = "#26a641",  # Green (matches COLOUR_POSITIVE)
        orientation: str = "horizontal",
        width: int = 400,
        height: int = 40,
        show_actual_label: bool = True,
        show_minmidmax_labels: bool = True,
        show_startend_labels: bool = True,
        label_format: str = "{:.1f}",
        title: Optional[str] = None,
    ):
        """
        Initialize the GaugeIndicator.

        Args:
            start: Minimum value of the gauge scale
            end: Maximum value of the gauge scale
            min_val: Value where low_color reaches full saturation
            mid_val: Value at the color midpoint
            max_val: Value where high_color reaches full saturation
            actual: The actual value to mark on the gauge
            low_color: Color for values at/below min_val
            mid_color: Color for values at mid_val
            high_color: Color for values at/above max_val
            orientation: 'horizontal' or 'vertical'
            width: Width in pixels
            height: Height in pixels
            show_actual_label: Display the actual value label
            show_minmidmax_labels: Display min/mid/max labels
            show_startend_labels: Display start/end labels
            label_format: Format string for labels
            title: Optional title text
        """
        # Validate inputs
        if not (start <= min_val <= mid_val <= max_val <= end):
            raise ValueError(
                f"Values must satisfy: start ({start}) <= min ({min_val}) "
                f"<= mid ({mid_val}) <= max ({max_val}) <= end ({end})"
            )

        self.start = start
        self.end = end
        self.min_val = min_val
        self.mid_val = mid_val
        self.max_val = max_val
        self.actual = actual
        self.low_color = low_color
        self.mid_color = mid_color
        self.high_color = high_color
        self.orientation = orientation.lower()
        self.width = width
        self.height = height
        self.show_actual_label = show_actual_label
        self.show_minmidmax_labels = show_minmidmax_labels
        self.show_startend_labels = show_startend_labels
        self.label_format = label_format
        self.title = title

        self._widget = None

    def _value_to_percent(self, value: float) -> float:
        """Convert a value to percentage position on the gauge."""
        if self.end == self.start:
            return 0.0
        return ((value - self.start) / (self.end - self.start)) * 100

    def _build_gradient_css(self) -> str:
        """Build the CSS linear gradient for the color bar."""
        # Calculate percentage positions for key points
        min_pct = self._value_to_percent(self.min_val)
        mid_pct = self._value_to_percent(self.mid_val)
        max_pct = self._value_to_percent(self.max_val)

        # Build gradient stops
        if self.orientation == "horizontal":
            direction = "to right"
        else:
            direction = "to top"  # Vertical: bottom is start, top is end

        gradient = (
            f"linear-gradient({direction}, "
            f"{self.low_color} 0%, "
            f"{self.low_color} {min_pct}%, "
            f"{self.mid_color} {mid_pct}%, "
            f"{self.high_color} {max_pct}%, "
            f"{self.high_color} 100%)"
        )
        return gradient

    def _build_marker_html(self) -> str:
        """Build the HTML for the actual value marker (chevron/arrow)."""
        actual_pct = self._value_to_percent(self.actual)
        # Clamp to 0-100 range for display
        actual_pct = max(0, min(100, actual_pct))

        if self.orientation == "horizontal":
            # Chevron pointing down, positioned above the bar
            marker_style = (
                f"position: absolute; "
                f"left: {actual_pct}%; "
                f"top: -12px; "
                f"transform: translateX(-50%); "
                f"width: 0; height: 0; "
                f"border-left: 8px solid transparent; "
                f"border-right: 8px solid transparent; "
                f"border-top: 10px solid #333333; "
            )
            # Label above the chevron
            label_style = (
                f"position: absolute; "
                f"left: {actual_pct}%; "
                f"top: -32px; "
                f"transform: translateX(-50%); "
                f"font-size: 12px; "
                f"font-weight: bold; "
                f"color: #333333; "
                f"white-space: nowrap; "
                f"background: rgba(255,255,255,0.9); "
                f"padding: 2px 4px; "
                f"border-radius: 3px; "
            )
        else:
            # Vertical: chevron pointing right, positioned to the left of the bar
            marker_style = (
                f"position: absolute; "
                f"bottom: {actual_pct}%; "
                f"left: -12px; "
                f"transform: translateY(50%); "
                f"width: 0; height: 0; "
                f"border-top: 8px solid transparent; "
                f"border-bottom: 8px solid transparent; "
                f"border-left: 10px solid #333333; "
            )
            label_style = (
                f"position: absolute; "
                f"bottom: {actual_pct}%; "
                f"left: -55px; "
                f"transform: translateY(50%); "
                f"font-size: 12px; "
                f"font-weight: bold; "
                f"color: #333333; "
                f"white-space: nowrap; "
                f"background: rgba(255,255,255,0.9); "
                f"padding: 2px 4px; "
                f"border-radius: 3px; "
            )

        marker_html = f'<div style="{marker_style}"></div>'
        if self.show_actual_label:
            label_text = self.label_format.format(self.actual)
            marker_html += f'<div style="{label_style}">{label_text}</div>'

        return marker_html

    def _build_tick_labels_html(self) -> str:
        """Build HTML for tick labels (min/mid/max and start/end)."""
        labels_html = ""

        if self.orientation == "horizontal":
            # Start/End labels at bottom
            if self.show_startend_labels:
                labels_html += (
                    f'<div style="position:absolute; left:0; bottom:-20px; '
                    f'font-size:10px; color:#666;">'
                    f"{self.label_format.format(self.start)}</div>"
                )
                labels_html += (
                    f'<div style="position:absolute; right:0; bottom:-20px; '
                    f'font-size:10px; color:#666;">'
                    f"{self.label_format.format(self.end)}</div>"
                )

            # Min/Mid/Max tick marks and labels
            if self.show_minmidmax_labels:
                for val, label in [
                    (self.min_val, "min"),
                    (self.mid_val, "mid"),
                    (self.max_val, "max"),
                ]:
                    pct = self._value_to_percent(val)
                    # Tick mark
                    labels_html += (
                        f'<div style="position:absolute; left:{pct}%; bottom:-8px; '
                        f"transform:translateX(-50%); width:1px; height:8px; "
                        f'background:#666;"></div>'
                    )
                    # Label
                    labels_html += (
                        f'<div style="position:absolute; left:{pct}%; bottom:-20px; '
                        f'transform:translateX(-50%); font-size:10px; color:#666;">'
                        f"{self.label_format.format(val)}</div>"
                    )
        else:
            # Vertical orientation
            if self.show_startend_labels:
                labels_html += (
                    f'<div style="position:absolute; bottom:0; right:-40px; '
                    f'font-size:10px; color:#666; transform:translateY(50%);">'
                    f"{self.label_format.format(self.start)}</div>"
                )
                labels_html += (
                    f'<div style="position:absolute; top:0; right:-40px; '
                    f'font-size:10px; color:#666; transform:translateY(-50%);">'
                    f"{self.label_format.format(self.end)}</div>"
                )

            if self.show_minmidmax_labels:
                for val, label in [
                    (self.min_val, "min"),
                    (self.mid_val, "mid"),
                    (self.max_val, "max"),
                ]:
                    pct = self._value_to_percent(val)
                    # Tick mark
                    labels_html += (
                        f'<div style="position:absolute; bottom:{pct}%; right:-8px; '
                        f"transform:translateY(50%); width:8px; height:1px; "
                        f'background:#666;"></div>'
                    )
                    # Label
                    labels_html += (
                        f'<div style="position:absolute; bottom:{pct}%; right:-40px; '
                        f'transform:translateY(50%); font-size:10px; color:#666;">'
                        f"{self.label_format.format(val)}</div>"
                    )

        return labels_html

    def _build_html(self) -> str:
        """Build the complete HTML for the gauge widget."""
        gradient = self._build_gradient_css()
        marker = self._build_marker_html()
        labels = self._build_tick_labels_html()

        if self.orientation == "horizontal":
            bar_style = (
                f"position: relative; "
                f"width: {self.width}px; "
                f"height: {self.height}px; "
                f"background: {gradient}; "
                f"border-radius: 5px; "
                f"border: 1px solid #ccc; "
            )
            container_style = (
                f"position: relative; "
                f"width: {self.width}px; "
                f"height: {self.height}px; "
                f"margin: 40px 20px 30px 20px; "  # Space for labels
            )
        else:
            bar_style = (
                f"position: relative; "
                f"width: {self.height}px; "  # Swap for vertical
                f"height: {self.width}px; "
                f"background: {gradient}; "
                f"border-radius: 5px; "
                f"border: 1px solid #ccc; "
            )
            container_style = (
                f"position: relative; "
                f"width: {self.height}px; "
                f"height: {self.width}px; "
                f"margin: 20px 60px 20px 60px; "  # Space for labels
            )

        # Title section
        title_html = ""
        if self.title:
            title_html = (
                f'<div style="font-size:14px; font-weight:bold; '
                f'margin-bottom:10px; color:#333;">{self.title}</div>'
            )

        html = f"""
        <div style="display:inline-block; font-family:sans-serif;">
            {title_html}
            <div style="{container_style}">
                <div style="{bar_style}">
                    {marker}
                    {labels}
                </div>
            </div>
        </div>
        """
        return html

    def create_widget(self) -> "widgets.HTML":
        """
        Create and return the ipywidgets HTML widget.

        Returns:
            ipywidgets.HTML widget containing the gauge visualization
        """
        self._widget = widgets.HTML(value=self._build_html())
        return self._widget

    def update(
        self,
        actual: Optional[float] = None,
        min_val: Optional[float] = None,
        mid_val: Optional[float] = None,
        max_val: Optional[float] = None,
        start: Optional[float] = None,
        end: Optional[float] = None,
    ) -> None:
        """
        Update the gauge values and refresh the display.

        Args:
            actual: New actual value (optional)
            min_val: New min value (optional)
            mid_val: New mid value (optional)
            max_val: New max value (optional)
            start: New start value (optional)
            end: New end value (optional)
        """
        if start is not None:
            self.start = start
        if end is not None:
            self.end = end
        if min_val is not None:
            self.min_val = min_val
        if mid_val is not None:
            self.mid_val = mid_val
        if max_val is not None:
            self.max_val = max_val
        if actual is not None:
            self.actual = actual

        # Validate after update
        if not (
            self.start
            <= self.min_val
            <= self.mid_val
            <= self.max_val
            <= self.end
        ):
            raise ValueError(
                f"Values must satisfy: start ({self.start}) <= min ({self.min_val}) "
                f"<= mid ({self.mid_val}) <= max ({self.max_val}) <= end ({self.end})"
            )

        if self._widget is not None:
            self._widget.value = self._build_html()

    def display(self) -> "widgets.HTML":
        """
        Create the widget and display it.

        Returns:
            The created HTML widget
        """
        widget = self.create_widget()
        return widget
