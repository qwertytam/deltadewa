"""Global assumptions and market parameters widget.

This module provides a centralized widget for managing market parameters
and scenario assumptions across the deltadewa dashboard.
"""

# TODO: Linter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import ipywidgets as widgets  # type: ignore[import-untyped]

from deltadewa import constants as const
from deltadewa.colours import DEFAULT_PALETTE


class GlobalAssumptions:
    """Centralized market parameters and scenario assumptions.

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
        valuation_date: datetime | None = None,
        spot_range_pct: float = 30.0,
        vol_range: tuple[float, float] = (0.05, 1.00),
        portfolio_time_horizon: int | None = None,
    ) -> None:
        """Initialize global assumptions panel.

        Args:
            spot_price: Initial spot price
            volatility: Initial volatility
            risk_free_rate: Risk-free rate
            dividend_yield: Dividend yield
            valuation_date: Valuation date (defaults to today)
            spot_range_pct: Range for spot slider (+/- %)
            vol_range: Min/max for volatility slider
            portfolio_time_horizon: Optional default time horizon in days for
            portfolio (overrides time horizon selector)

        """
        if valuation_date is None:
            valuation_date = datetime.now(tz=UTC)

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

        insert_index = None
        if portfolio_time_horizon is not None:
            last_maturity_title = (
                "Portfolio Furthest Maturity (T" + f"+{portfolio_time_horizon})"
            )

            # Insert the portfolio furthest maturity into the ordered options
            # list. Keep the 'Custom' option (value -1) at the end.
            existing_values = [val for (_lbl, val) in time_horizon_options]
            if portfolio_time_horizon not in existing_values:
                new_option = (last_maturity_title, portfolio_time_horizon)
                for idx, (_lbl, val) in enumerate(time_horizon_options):
                    # If we hit the Custom option, insert before it
                    if val == -1:
                        insert_index = idx
                        break
                    # Insert before the first option with a larger numeric value
                    if val > portfolio_time_horizon:
                        insert_index = idx
                        break
                if insert_index is None:
                    # No larger value and no Custom found; append at end
                    time_horizon_options.append(new_option)
                else:
                    time_horizon_options.insert(insert_index, new_option)

        # Default selection: use portfolio_time_horizon (days) when provided,
        # otherwise default to 6 months (in days). Note: Dropdown `value`
        # must be the option's value (days), not the index.
        if portfolio_time_horizon is None:
            time_horizon_default = const.CALENDAR_DAYS_PER_MONTH * 6
        else:
            time_horizon_default = portfolio_time_horizon

        self.time_horizon = widgets.Dropdown(
            options=time_horizon_options,
            value=time_horizon_default,
            description="Time Horizon:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="350px"),
        )

        self.custom_days = widgets.IntText(
            value=time_horizon_default,
            description="Custom Days:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="250px"),
            disabled=True,
        )

        # Link time horizon selector to custom days field
        def on_horizon_change(change) -> None:  # noqa: ANN001
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
        )

        # Callbacks registry
        self._callbacks: list[Callable] = []

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

    def _notify_callbacks(self, change) -> None:  # noqa: ANN001
        """Notify all registered callbacks when any parameter changes."""
        for callback in self._callbacks:
            callback(change)

    def on_change(self, callback: Callable) -> None:
        """Register a callback to be called when any parameter changes.

        Args:
            callback: Function to call with change dict

        """
        self._callbacks.append(callback)

    def get_days_forward(self) -> int:
        """Get the selected number of days forward.

        Returns:
            Days forward based on time horizon selector

        """
        if self.time_horizon.value == -1:
            return self.custom_days.value
        return self.time_horizon.value

    @property
    def time_horizon_days(self):  # noqa: ANN201
        """Property to get the selected number of days forward.

        This is a convenience property that wraps get_days_forward()
        to match the expected interface in the notebook.

        Returns:
            Widget-like object with a 'value' attribute containing the days forward

        """
        return SimpleNamespace(value=self.get_days_forward())

    def get_valuation_date_forward(self) -> datetime:
        """Get the future valuation date based on time horizon.

        Returns:
            Future datetime based on selected horizon

        """
        val_date = datetime.combine(
            self.valuation_date.value,
            datetime.min.time(),
        )
        return val_date + timedelta(days=self.get_days_forward())

    def to_dict(self) -> dict[str, Any]:
        """Export current assumptions as dictionary.

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
        """Create and return the display widget.

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
            ],
        )

        time_section = widgets.VBox(
            [
                widgets.HTML(
                    "<h4>Time Horizon: Days Forward From Valuation Date</h4>",
                ),
                widgets.HBox([self.time_horizon, self.custom_days]),
            ],
        )

        scenario_selectors = widgets.VBox(
            [
                self.spot_shock_pct,
                self.vol_shock_pct,
                self.grid_resolution,
                self.monte_carlo_num_sims,
                self.monte_carlo_inc_ul,
            ],
        )
        scenario_section = widgets.Accordion(children=[scenario_selectors])
        scenario_section.set_title(0, "Scenario Grid Parameters (Expand)")
        scenario_section.selected_index = None  # Collapsed by default

        return widgets.VBox(
            [
                widgets.HTML(
                    f"""
                    <div style="background-color:{DEFAULT_PALETTE.med_dark_background}; """
                    """color:white; padding:10px; border-radius:5px; margin-bottom:10px;">
                    <h3 style="margin:0;">Global Assumptions Panel</h3>
                    <p style="margin:5px 0 0 0; font-size:14px;">
                    Single source of truth for all market parameters</p>
                    </div>
                    """,
                ),
                market_section,
                time_section,
                scenario_section,
            ],
            layout=widgets.Layout(
                border=f"2px solid {DEFAULT_PALETTE.med_dark_background}",
                padding="15px",
                margin="10px 0",
            ),
        )
