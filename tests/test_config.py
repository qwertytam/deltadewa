"""Tests for deltadewa.config module - configuration widget functions."""

from pathlib import Path

import ipywidgets as widgets  # type: ignore[import-untyped]

from deltadewa.config import (
    create_export_dir_widget,
    get_export_dir_from_widget,
)


class TestCreateExportDirWidget:
    """Tests for create_export_dir_widget."""

    def test_returns_vbox_widget(self, tmp_path) -> None:
        """Test that the function returns an ipywidgets.VBox."""
        widget = create_export_dir_widget(
            default_dir=str(tmp_path / "exports"),
            show_browser=False,
        )

        assert isinstance(widget, widgets.VBox)

    def test_default_dir_creates_directory(self, tmp_path) -> None:
        """Test that the default directory is created on widget initialization.

        The widget should create the directory specified by default_dir if it
        does not already exist.
        """
        export_dir = tmp_path / "test_exports"
        assert not export_dir.exists()

        _ = create_export_dir_widget(
            default_dir=str(export_dir),
            show_browser=False,
        )

        assert export_dir.exists()

    def test_export_dir_attribute_set(self, tmp_path) -> None:
        """Test that the widget has an 'export_dir' attribute set to a Path."""
        export_dir = tmp_path / "exports"

        widget = create_export_dir_widget(
            default_dir=str(export_dir),
            show_browser=False,
        )

        assert hasattr(widget, "export_dir")
        assert isinstance(widget.export_dir, Path)

    def test_widget_has_children(self, tmp_path) -> None:
        """Test that the VBox contains expected child widgets."""
        widget = create_export_dir_widget(
            default_dir=str(tmp_path / "exports"),
            show_browser=False,
        )

        # Widget should have children
        assert hasattr(widget, "children")
        assert len(widget.children) > 0

        # Check for expected widget types in children
        has_html = False
        has_hbox = False
        has_output = False

        for child in widget.children:
            if isinstance(child, widgets.HTML):
                has_html = True
            elif isinstance(child, widgets.HBox):
                has_hbox = True
            elif isinstance(child, widgets.Output):
                has_output = True

        assert has_html, "Widget should contain HTML widgets"
        assert has_hbox, "Widget should contain HBox widgets"
        assert has_output, "Widget should contain Output widget"

    def test_show_browser_false_hides_open_button(self, tmp_path) -> None:
        """Test that show_browser=False omits the 'Open in Finder' button."""
        widget = create_export_dir_widget(
            default_dir=str(tmp_path / "exports"),
            show_browser=False,
        )

        # Check that no button with "Open in Finder" text exists
        # by searching through all children recursively
        def find_buttons(w) -> list[widgets.Button]:
            buttons = []
            if isinstance(w, widgets.Button):
                buttons.append(w)
            if hasattr(w, "children"):
                for child in w.children:  # type: ignore[attr-defined]
                    buttons.extend(find_buttons(child))
            return buttons

        all_buttons = find_buttons(widget)
        open_buttons = [
            b
            for b in all_buttons
            if "Open" in b.description or "Finder" in b.description
        ]

        assert (
            len(open_buttons) == 0
        ), "No 'Open in Finder' button should exist when show_browser=False"

    def test_custom_default_dir(self, tmp_path) -> None:
        """Test widget creation with a custom default directory."""
        custom_dir = tmp_path / "my_custom_dir"

        widget = create_export_dir_widget(
            default_dir=str(custom_dir),
            show_browser=False,
        )

        # Directory should be created
        assert custom_dir.exists()

        # Widget's export_dir should match
        widget_dir = widget.export_dir
        assert widget_dir == custom_dir


class TestGetExportDirFromWidget:
    """Tests for get_export_dir_from_widget."""

    def test_extracts_path(self, tmp_path) -> None:
        """Test that get_export_dir_from_widget returns the correct Path."""
        export_dir = tmp_path / "exports"

        widget = create_export_dir_widget(
            default_dir=str(export_dir),
            show_browser=False,
        )

        extracted_path = get_export_dir_from_widget(widget)

        assert extracted_path == export_dir

    def test_returns_path_type(self, tmp_path) -> None:
        """Test that the returned value is a Path instance."""
        widget = create_export_dir_widget(
            default_dir=str(tmp_path / "exports"),
            show_browser=False,
        )

        extracted_path = get_export_dir_from_widget(widget)

        assert isinstance(extracted_path, Path)
