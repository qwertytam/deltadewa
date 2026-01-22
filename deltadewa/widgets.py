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
        vol_range: Tuple[float, float] = (0.05, 0.50),
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
            readout_format=".2%",
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
            ("1 Week (T+7)", 7),
            ("1 Month (T+30)", 30),
            ("2 Months (T+60)", 60),
            ("3 Months (T+90)", 90),
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
            value=20.0,
            min=5.0,
            max=50.0,
            step=5.0,
            description="Spot Shock %:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
            readout_format=".0f",
        )

        self.vol_shock_pct = widgets.FloatSlider(
            value=50.0,
            min=10.0,
            max=100.0,
            step=10.0,
            description="Vol Shock %:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
            continuous_update=False,
            readout_format=".0f",
        )

        self.grid_resolution = widgets.IntSlider(
            value=25,
            min=10,
            max=50,
            step=5,
            description="Grid Resolution:",
            style={"description_width": "150px"},
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
                widgets.HTML("<h4>Time Horizon</h4>"),
                widgets.HBox([self.time_horizon, self.custom_days]),
            ]
        )

        scenario_section = widgets.VBox(
            [
                widgets.HTML("<h4>Scenario Grid Parameters</h4>"),
                self.spot_shock_pct,
                self.vol_shock_pct,
                self.grid_resolution,
            ]
        )

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

    def _format_greek(
        self, name: str, value: float, is_cost: bool = False
    ) -> str:
        """
        Format a Greek metric as colored HTML badge.

        Args:
            name: Greek name
            value: Greek value
            is_cost: Whether this represents a cost (red) vs profit (green)

        Returns:
            HTML string with formatted badge
        """
        if abs(value) < 0.01 and name != "Value":
            value_str = "~0"
        elif abs(value) >= 1000:
            value_str = (
                f"${value/1000:.1f}k"
                if "Value" in name or "Cost" in name
                else f"{value:,.0f}"
            )
        else:
            value_str = (
                f"${value:.2f}"
                if "Value" in name or "Cost" in name
                else f"{value:.2f}"
            )

        # Color coding
        if is_cost or value < 0:
            color = "#d32f2f"  # Red for costs/negative
            text_color = "white"
        elif value > 0:
            color = "#388e3c"  # Green for profits/positive
            text_color = "white"
        else:
            color = "#757575"  # Gray for neutral
            text_color = "white"

        return (
            f'<div style="display:inline-block; background-color:{color}; '
            f"color:{text_color}; padding:8px 12px; margin:5px; "
            f'border-radius:5px; font-weight:bold; min-width:120px;">'
            f'<div style="font-size:11px; opacity:0.9;">{name}</div>'
            f'<div style="font-size:16px;">{value_str}</div>'
            f"</div>"
        )

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
            color = "#388e3c"  # Green
        elif pnl > -1000:
            color = "#f57c00"  # Orange
        else:
            color = "#d32f2f"  # Red

        return (
            f'<div style="display:inline-block; background-color:{color}; '
            f"color:white; padding:6px 10px; margin:3px; "
            f'border-radius:3px; font-size:12px; min-width:100px;">'
            f"<strong>{shock_pct:+.0f}%:</strong> ${pnl:,.0f}"
            f"</div>"
        )

    def _create_widget(self):
        """Create the KPI display widget."""
        self.core_metrics_html = widgets.HTML(value="")
        self.crash_indicators_html = widgets.HTML(value="")
        self.prob_stats_html = widgets.HTML(value="")

        # Expandable accordion for probabilistic stats
        self.accordion = widgets.Accordion(children=[self.prob_stats_html])
        self.accordion.set_title(0, "📊 Probabilistic Statistics (Expand)")
        self.accordion.selected_index = None  # Collapsed by default

        self.widget = widgets.VBox(
            [
                widgets.HTML(
                    '<div style="background-color:#0F4761; color:white; '
                    'padding:10px; border-radius:5px 5px 0 0;">'
                    '<h3 style="margin:0;">Net Hedge Summary</h3>'
                    "</div>"
                ),
                self.core_metrics_html,
                widgets.HTML(
                    "<h4 style='margin:10px 0 5px 0;'>Crash Convexity "
                    + "Indicators: P&L at Expiry</h4>"
                ),
                self.crash_indicators_html,
                self.accordion,
            ],
            layout=widgets.Layout(border="2px solid #0F4761", margin="10px 0"),
        )

        self.update()

    def update(self):
        """Update all metrics with current portfolio data."""
        stats = self.portfolio.summary_stats()

        # Core Greeks
        core_html = (
            self._format_greek("Net Delta", stats["total_delta"])
            + self._format_greek("Net Gamma", stats["total_gamma"])
            + self._format_greek("Net Vega", stats["total_vega"])
            + self._format_greek("Theta (Daily)", stats["total_theta"])
            + self._format_greek("Current Value", stats["total_value"])
        )
        self.core_metrics_html.value = (
            f'<div style="padding:10px;">{core_html}</div>'
        )

        # Crash convexity
        current_spot = self.portfolio.spot_price
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
            self._format_crash_indicator(-10, pnl_10)
            + self._format_crash_indicator(-20, pnl_20)
            + self._format_crash_indicator(-30, pnl_30)
        )
        self.crash_indicators_html.value = (
            f'<div style="padding:10px;">{crash_html}</div>'
        )

        # Probabilistic stats (expandable)
        analysis = self.portfolio.risk_reward_analysis()

        prob_html = "<div style='padding:10px;'>"

        # Check if Monte Carlo results exist
        mc_results = getattr(self.portfolio, "_monte_carlo_results", None)
        if (
            mc_results is not None
            and len(mc_results.get("simulated_pnls", [])) > 0
        ):
            expected_pnl = mc_results.get("expected_pnl", 0)
            prob_profit = mc_results.get("probability_of_profit", 0)
            prob_html += f"<p><strong>Probability of Profit:</strong> {prob_profit:.1f}%</p>"
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

    def __init__(self, portfolio, export_dir: Path = Path("exports")):
        """
        Initialize widget factory.

        Args:
            portfolio: OptionPortfolio instance
            export_dir: Directory for exports (default: 'exports')
        """
        self.portfolio = portfolio
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(exist_ok=True)

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
                ("Total Gamma", "gamma"),
                ("Total Vega", "vega"),
                ("Total Theta", "theta"),
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
        format_selector = widgets.RadioButtons(
            options=["JSON", "YAML"],
            value="JSON",
            description="Import Format:",
            style={"description_width": "150px"},
        )

        filename_input = widgets.Text(
            value="portfolio_book.json",
            description="Filename:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="400px"),
        )

        file_upload = widgets.FileUpload(
            accept=".json,.yaml,.yml",
            multiple=False,
            description="Or Upload:",
            style={"description_width": "150px"},
        )

        preview_button = widgets.Button(
            description="Preview File",
            button_style="",
            icon="eye",
            layout=widgets.Layout(width="150px"),
        )

        import_button = widgets.Button(
            description="Import Portfolio",
            button_style="info",
            icon="upload",
            layout=widgets.Layout(width="150px"),
        )

        replace_checkbox = widgets.Checkbox(
            value=False,
            description="Replace current portfolio",
            style={"description_width": "200px"},
        )

        return {
            "format_selector": format_selector,
            "filename_input": filename_input,
            "file_upload": file_upload,
            "preview_button": preview_button,
            "import_button": import_button,
            "replace_checkbox": replace_checkbox,
        }

    def display_import_export(self) -> widgets.VBox:
        """
        Create and display combined import/export interface.

        Returns:
            VBox widget containing import and export controls
        """
        import_controls = self.create_import_controls()
        export_controls = self.create_export_controls()

        import_output = widgets.Output()
        export_output = widgets.Output()

        # Import button handler
        def on_import_clicked(b):  # pylint: disable=unused-argument
            with import_output:
                import_output.clear_output()
                try:
                    filename = import_controls["filename_input"].value
                    file_format = import_controls[  # noqa:F841 pylint: disable=unused-variable
                        "format_selector"
                    ].value.lower()
                    filepath = self.export_dir / filename

                    if not filepath.exists():
                        print(f"✗ File not found: {filepath}")
                        return

                    replace = import_controls["replace_checkbox"].value
                    if replace:
                        imported_portfolio = import_portfolio(str(filepath))

                        if not isinstance(imported_portfolio, OptionPortfolio):
                            print(
                                "✗ Import failed: Expected OptionPortfolio, "
                                + f"got {type(imported_portfolio)}"
                            )
                            return

                        # Copy all attributes from imported to current
                        self.portfolio.positions = imported_portfolio.positions
                        self.portfolio.spot_price = (
                            imported_portfolio.spot_price
                        )
                        self.portfolio.volatility = (
                            imported_portfolio.volatility
                        )
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
                        print(f"✓ Portfolio replaced from {filepath}")
                    else:
                        print(
                            "✗ Merge mode not yet implemented - use 'Replace' option"
                        )
                        return

                    print(f"✓ Loaded {len(self.portfolio.positions)} positions")

                except Exception as e:  # pylint: disable=broad-except
                    print(f"✗ Import failed: {e}")

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
        import_controls["import_button"].on_click(on_import_clicked)
        export_controls["export_button"].on_click(on_export_clicked)

        # Assemble interface
        import_section = widgets.VBox(
            [
                widgets.HTML("<h3>Import Portfolio</h3>"),
                import_controls["format_selector"],
                import_controls["filename_input"],
                import_controls["replace_checkbox"],
                import_controls["import_button"],
                import_output,
            ]
        )

        export_section = widgets.VBox(
            [
                widgets.HTML("<h3>Export Portfolio</h3>"),
                export_controls["format_selector"],
                export_controls["filename_input"],
                export_controls["export_button"],
                export_output,
            ]
        )

        return widgets.VBox(
            [
                widgets.HTML("<h2>Portfolio Import/Export</h2>"),
                widgets.HTML("<hr>"),
                import_section,
                widgets.HTML("<hr>"),
                export_section,
            ]
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
