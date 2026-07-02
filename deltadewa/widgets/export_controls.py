"""Export and import control widgets for portfolio management.

This module provides mixin classes for export/import functionality
in the deltadewa dashboard.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import ipywidgets as widgets
from ipyfilechooser import FileChooser

from deltadewa.config import (
    create_export_dir_widget as _create_export_dir_widget,
)
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.reporting.audit import PortfolioLogger

if TYPE_CHECKING:
    from deltadewa.persistence import PortfolioSerializer


class ExportControlsMixin:
    """Mixin providing export/import control widgets.

    This mixin expects the host class to have:
    - self.portfolio: OptionPortfolio instance
    - self.serializer: PortfolioSerializer instance
    - self.portfolio_changelog: PortfolioLogger instance
    """

    portfolio: OptionPortfolio
    serializer: PortfolioSerializer
    portfolio_changelog: PortfolioLogger

    @property
    def export_dir(self) -> Path:
        """Get the current export directory."""
        if self.serializer.export_dir is None:
            raise ValueError("Export directory is not set")
        return self.serializer.export_dir

    @export_dir.setter
    def export_dir(self, value: Path | str) -> None:
        """Set the export directory and update UI."""
        self.serializer.update_export_dir(value)
        self._update_export_ui_state()

    def _update_export_ui_state(self) -> None:
        """Update state of all registered export UI elements."""
        if not hasattr(self, "_export_ui_map"):
            return

        # Check if directory exists and is valid
        try:
            is_ready = self.export_dir.exists()
        except (ValueError, AttributeError):
            is_ready = False

        # Clean up and update widgets
        # Using a copy list to remove dead references if we implemented
        # weakrefs, but here we'll just check for errors
        for widgets_dict in self._export_ui_map:
            btn = widgets_dict.get("button")
            warning = widgets_dict.get("warning")

            if is_ready:
                if btn:
                    btn.button_style = "success"
                    btn.disabled = False
                    btn.tooltip = "Export portfolio to file"
                if warning:
                    warning.value = ""
                    warning.layout.display = "none"
            else:
                if btn:
                    btn.button_style = "danger"
                    # We don't disable it so they can see the error message if
                    # they click
                    btn.tooltip = "Export directory not set"
                if warning:
                    warning.value = (
                        "<div style='color: #d32f2f; background-color:"
                        " #fde8e8; "
                        "padding: 10px; border-radius: 4px;"
                        " border: 1px solid #f8b4b4; "
                        "margin-bottom: 10px;'>"
                        "<strong>⚠️ Action Required:</strong>"
                        " Export directory is not configured. "
                        "Please use the 'Set Directory' button"
                        " in the Setup section above."
                        "</div>"
                    )
                    warning.layout.display = "block"

    # ==========================================================================
    # Import/Export Widgets
    # ==========================================================================

    def create_export_controls(
        self,
        default_format: str = "JSON",
    ) -> dict[str, Any]:
        """Create export format selection and execution controls.

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

        inc_timestamp_checkbox = widgets.Checkbox(
            value=False,
            description="Include Timestamp in Filename",
            style={"description_width": "initial"},
            indent=False,
            layout=widgets.Layout(width="auto"),
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
            button_style="danger",
            icon="download",
            layout=widgets.Layout(width="200px"),
        )

        return {
            "format_selector": format_selector,
            "inc_timestamp_checkbox": inc_timestamp_checkbox,
            "filename_input": filename_input,
            "export_button": export_button,
        }

    def create_import_controls(self) -> dict[str, Any]:
        """Create import file selection and preview controls.

        The file chooser opens a native-style in-notebook browser; once a
        file is selected, its full path is written into ``filename_input``
        for Preview/Import to use directly.

        Returns:
            Dictionary with import-related widgets

        """
        filename_input = widgets.Text(
            value="",
            description="Filename:",
            style={"description_width": "150px"},
            layout=widgets.Layout(width="500px"),
        )

        file_chooser = FileChooser(
            path=str(Path.home()),
            title="Select portfolio file",
            select_desc="Select File",
            filter_pattern=["*.json", "*.yaml", "*.yml"],
        )

        clear_button = widgets.Button(
            description="Clear",
            button_style="warning",
            icon="times",
            layout=widgets.Layout(width="100px"),
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
            "file_chooser": file_chooser,
            "clear_button": clear_button,
            "preview_button": preview_button,
            "import_button": import_button,
        }

    def display_import(  # pylint: disable=too-many-statements  # import UI
        self,
        on_import_success: Callable[..., Any] | None = None,
    ) -> widgets.VBox:
        """Create and display import interface.

        Workflow: click "Select File" on the file chooser to open an
        in-notebook browser, pick a portfolio file — its full path appears
        in the Filename box — then click Preview or Import Portfolio.
        "Clear" resets the chooser and empties the Filename box.

        Args:
            on_import_success: Optional zero-argument callback invoked after a
                successful import.  Use this to re-seed any stateful objects
                (e.g. ``PortfolioChangeTracker.reset``) that hold a snapshot of
                the portfolio, so they don't misclassify the imported positions
                on the next change event.

        Returns:
            VBox widget containing import controls

        """
        import_controls = self.create_import_controls()
        import_output = widgets.Output()

        # Import button handler
        def on_import_clicked(b: widgets.Button) -> None:
            _ = b
            with import_output:
                import_output.clear_output()
                try:
                    filename = import_controls["filename_input"].value
                    if not filename:
                        print(
                            "✗ No file selected. Use 'Select File' first.",
                        )
                        return
                    print(f"Attempting to import portfolio from {filename}...")
                    # Auto-detect format handled by import_portfolio

                    filepath = Path(filename)

                    if not filepath.exists():
                        print(f"✗ File not found: {filepath}")
                        return

                    imported_portfolio = self.serializer.import_portfolio(
                        str(filepath),
                    )["portfolio"]
                    if not isinstance(imported_portfolio, OptionPortfolio):
                        print(
                            "✗ Import failed: Expected OptionPortfolio, "
                            f"got {type(imported_portfolio)}",
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
                    self.portfolio.symbol = imported_portfolio.symbol

                    print(f"✓ Successfully imported portfolio from {filepath}")
                    print(f"Symbol: {self.portfolio.get_symbol()}")
                    print(f"Spot Price: {self.portfolio.spot_price}")

                    print(f"✓ Loaded {len(self.portfolio.positions)} positions")
                    import_controls["import_button"].button_style = "success"

                    # Notify caller that the portfolio has been replaced so
                    # they can update any references if needed
                    if on_import_success is not None:
                        on_import_success()

                except Exception as e:  # pylint: disable=broad-except
                    print(f"✗ Import failed: {e}")
                    import_controls["import_button"].button_style = "danger"

        # Preview button handler
        def on_preview_clicked(b: widgets.Button) -> None:
            _ = b
            with import_output:
                import_output.clear_output()
                try:
                    filename = import_controls["filename_input"].value
                    if not filename:
                        print(
                            "✗ No file selected. Use 'Select File' first.",
                        )
                        return
                    filepath = Path(filename)

                    if not filepath.exists():
                        print(f"✗ File not found: {filepath}")
                        return

                    # Load into a temporary portfolio to inspect content
                    print(f"Loading portfolio from {filepath}...")

                    preview_portfolio = self.serializer.import_portfolio(
                        str(filepath),
                    )["portfolio"]

                    if not isinstance(preview_portfolio, OptionPortfolio):
                        print(
                            f"✗ Invalid portfolio file: "
                            f"{type(preview_portfolio)}",
                        )
                        return

                    # Extract summary details
                    positions_count = len(preview_portfolio.positions)
                    symbol = preview_portfolio.get_symbol()

                    print(f"Previewing Portfolio: {filename}")
                    print("-" * 50)
                    print(f"Symbol:              {symbol}")
                    print(
                        f"Risk-Free Rate:      "
                        f"{preview_portfolio.risk_free_rate:.2%}",
                    )
                    print(
                        f"Spot Price:          "
                        f"{preview_portfolio.spot_price:.2f}",
                    )
                    print(
                        f"Underlying Quantity: "
                        f"{preview_portfolio.underlying_quantity:.0f}",
                    )
                    print(f"Number of Positions: {positions_count}")
                    print("-" * 50)
                    import_controls["preview_button"].button_style = "success"

                except Exception as e:  # pylint: disable=broad-except
                    print(f"✗ Preview failed: {e}")
                    import_controls["preview_button"].button_style = "danger"

        # File chooser callback - fires when the user picks a file in the
        # browser dialog, writing its full path into filename_input.
        def on_file_chosen(chooser: FileChooser) -> None:
            if chooser.selected:
                import_controls["filename_input"].value = chooser.selected

        # Clear button handler - resets the chooser and filename box.
        def on_clear_clicked(b: widgets.Button) -> None:
            _ = b
            import_controls["file_chooser"].reset()
            import_controls["filename_input"].value = ""
            with import_output:
                import_output.clear_output()

        # Connect button handlers
        import_controls["import_button"].on_click(on_import_clicked)
        import_controls["preview_button"].on_click(on_preview_clicked)
        import_controls["clear_button"].on_click(on_clear_clicked)
        import_controls["file_chooser"].register_callback(on_file_chosen)

        action_buttons = widgets.HBox(
            [
                import_controls["clear_button"],
                import_controls["preview_button"],
                import_controls["import_button"],
            ],
        )

        # Assemble interface
        import_section = widgets.VBox(
            [
                widgets.HTML("<h3>Import Portfolio</h3>"),
                import_controls["file_chooser"],
                import_controls["filename_input"],
                action_buttons,
                import_output,
            ],
        )

        return import_section

    def display_export(self) -> widgets.VBox:
        """Create and display export interface.

        Returns:
            VBox widget containing export controls

        """
        export_controls = self.create_export_controls()
        export_output = widgets.Output()

        # Warning label for unconfigured directory
        warning_label = widgets.HTML(
            value="",
            layout=widgets.Layout(display="none"),
        )

        # Register UI elements for state updates
        if not hasattr(self, "_export_ui_map"):
            self._export_ui_map = []

        self._export_ui_map.append(
            {
                "button": export_controls["export_button"],
                "warning": warning_label,
            },
        )

        # Initial status check
        self._update_export_ui_state()

        # Export button handler
        def on_export_clicked(b: widgets.Button) -> None:
            _ = b
            with export_output:
                export_output.clear_output()

                # Double check directory validity
                try:
                    if not self.export_dir.exists():
                        print("✗ Error: Export directory does not exist.")
                        return
                except (ValueError, AttributeError):
                    print(
                        "✗ Error: Export directory is not set. "
                        "Please configure it in the Setup section.",
                    )
                    return

                try:
                    filename = export_controls["filename_input"].value
                    file_format = export_controls[
                        "format_selector"
                    ].value.lower()
                    inc_timestamp = export_controls[
                        "inc_timestamp_checkbox"
                    ].value

                    ts = ""
                    if inc_timestamp:
                        ts = datetime.now(tz=UTC).strftime("_%Y%m%d_%H%M%S")

                    # Add extension if not present
                    if not filename.endswith(f".{file_format}"):
                        filename = f"{filename}{ts}.{file_format}"

                    filepath = self.export_dir / filename

                    if file_format == "json":
                        self.serializer.export_to_json(
                            self.portfolio,
                            self.portfolio_changelog,
                            filename,
                        )
                    elif file_format == "csv":
                        self.serializer.export_to_csv(
                            self.portfolio,
                            self.portfolio_changelog,
                            filename,
                        )
                    elif file_format == "yaml":
                        self.serializer.export_to_yaml(
                            self.portfolio,
                            self.portfolio_changelog,
                            filename,
                        )
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
                warning_label,
                export_controls["format_selector"],
                widgets.HTML(f"<p>Export Directory: {self.export_dir}/</p>"),
                export_controls["inc_timestamp_checkbox"],
                export_controls["filename_input"],
                widgets.HTML("<br>"),
                export_controls["export_button"],
                export_output,
            ],
        )

        return export_section

    def create_export_dir_widget(
        self,
        show_browser: bool = True,
        on_change_callback: Callable[[Path], None] | None = None,
    ) -> widgets.VBox:
        """Create an export-directory selection widget.

        Creates the widget and keep `self export_dir` in sync.

        Args:
            show_browser: Whether to show the "Open in Finder" button
            on_change_callback: Optional callback invoked with the new Path
            when changed

        Returns:
            VBox widget created by the shared config helper

        Notes:
            This wraps `deltadewa.config.create_export_dir_widget` so the
            dashboard can reuse the common UI while updating the
            PortfolioWidgets' `export_dir`.

        """

        def _on_change(export_dir: Path) -> None:
            # keep internal export_dir Path in sync
            try:
                self.export_dir = Path(export_dir)
            except Exception as e:  # pylint: disable=broad-except
                print(f"DEBUG: Failed to update internal export_dir: {e}")
                # Re-raise so the config widget shows the error red
                raise e

            if on_change_callback:
                on_change_callback(export_dir)

        # Use a default if export_dir is not set
        try:
            current_dir = str(self.export_dir)
        except ValueError:
            current_dir = str(Path.cwd() / "exports")

        # Use the existing config helper to build the UI; pass current
        # export_dir
        return _create_export_dir_widget(
            default_dir=current_dir,
            on_change_callback=_on_change,
            show_browser=show_browser,
        )

    def display_export_dir_widget(
        self,
        show_browser: bool = True,
        on_change_callback: Callable[[Path], None] | None = None,
    ) -> widgets.VBox:
        """Display the export-directory selection widget with header.

        Convenience display wrapper for the export-directory widget.

        Returns a small VBox containing a header and the export-dir selector
        so dashboards can simply call this method and `display(...)` the result.
        """
        widget = self.create_export_dir_widget(
            show_browser=show_browser,
            on_change_callback=on_change_callback,
        )

        header = widgets.HTML("<h3>Export Directory</h3>")
        return widgets.VBox(
            [header, widget],
            layout=widgets.Layout(margin="8px 0"),
        )
