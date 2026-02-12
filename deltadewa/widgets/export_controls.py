"""Export and import control widgets for portfolio management.

This module provides mixin classes for export/import functionality
in the deltadewa dashboard.
"""

from pathlib import Path
from typing import (
    Optional,
    Union,
    Callable,
    Dict,
    Any,
)

import ipywidgets as widgets  # type: ignore[import-untyped]

from deltadewa.persistence import PortfolioSerializer
from deltadewa.config import (
    create_export_dir_widget as _create_export_dir_widget,
)
from deltadewa.portfolio.core import OptionPortfolio


class ExportControlsMixin:
    """
    Mixin providing export/import control widgets.

    This mixin expects the host class to have:
    - self.portfolio: OptionPortfolio instance
    - self._export_dir: Path or None attribute
    """

    portfolio: OptionPortfolio
    _export_dir: Optional[Path] = None

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
                    serializer = PortfolioSerializer(str(filepath))

                    if not filepath.exists():
                        print(f"✗ File not found: {filepath}")
                        return

                    imported_portfolio = serializer.import_portfolio(
                        str(filepath)
                    )["portfolio"]
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
                    serializer = PortfolioSerializer(str(filepath))

                    if not filepath.exists():
                        print(f"✗ File not found: {filepath}")
                        return

                    # Load into a temporary portfolio to inspect content
                    print(f"Loading portfolio from {filepath}...")

                    preview_portfolio = serializer.import_portfolio(
                        str(filepath)
                    )["portfolio"]

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
                    serializer = PortfolioSerializer(str(filepath))

                    if file_format == "json":
                        serializer.export_to_json(self.portfolio, filename)
                    elif file_format == "csv":
                        serializer.export_to_csv(self.portfolio, filename)
                    elif file_format == "yaml":
                        serializer.export_to_yaml(self.portfolio, filename)
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
