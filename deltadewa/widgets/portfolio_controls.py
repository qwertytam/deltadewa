"""Portfolio control widgets for managing positions and portfolios.

This module provides comprehensive widget controls for creating, editing,
and managing option portfolios in the deltadewa dashboard.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union, Callable, Tuple, Dict, List, Any
from datetime import datetime, timedelta

import ipywidgets as widgets  # type: ignore[import-untyped]

from deltadewa.persistence import (
    import_portfolio,
    export_portfolio_to_json,
    export_portfolio_to_csv,
    export_portfolio_to_yaml,
)
from deltadewa.config import (
    create_export_dir_widget as _create_export_dir_widget,
)

if TYPE_CHECKING:
    from deltadewa.portfolio import OptionPortfolio


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

        # NOTE: InteractiveOutput is no longer imported in this module
        # Users should handle the output widget separately
        output = widgets.Output()

        dashboard = widgets.VBox(
            [
                widgets.HTML("<h3>Interactive Market Scenario Dashboard</h3>"),
                widgets.HTML(
                    "<p>Adjust market parameters to see real-time portfolio impact</p>"
                ),
                market_controls["spot"],
                market_controls["vol"],
                output,
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
