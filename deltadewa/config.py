"""Configuration utilities for DeltaDewa dashboard.

Provides interactive configuration widgets and default settings management.
"""

# TODO: Linter
import platform
import subprocess
from collections.abc import Callable
from pathlib import Path

import ipywidgets as widgets  # type: ignore[import-untyped]


def create_export_dir_widget(
    default_dir: str = "exports",
    on_change_callback: Callable | None = None,
    show_browser: bool = True,
) -> widgets.VBox:
    """Create interactive export directory configuration widget.

    Args:
        default_dir: Default export directory name
        on_change_callback:  Optional callback when directory changes
        show_browser:  Whether to show "Open in Finder" button

    Returns:
        VBox widget with complete directory configuration interface

    Example:
        from deltadewa.config import create_export_dir_widget

        def on_dir_change(export_dir):
            print(f"Directory changed to: {export_dir}")

        widget = create_export_dir_widget(
            default_dir='my_exports',
            on_change_callback=on_dir_change
        )
        display(widget)

    """
    if not Path(default_dir).exists():
        initial_value = str(Path.cwd())
    else:
        initial_value = default_dir

    custom_path_input = widgets.Text(
        value=initial_value,
        placeholder="Enter path or browse...",
        description="Path:",
        style={"description_width": "120px"},
        layout=widgets.Layout(width="500px"),
        disabled=False,
    )

    browse_button = widgets.Button(
        description="Browse...",
        button_style="info",
        icon="search",
        layout=widgets.Layout(width="100px"),
        tooltip="Select folder using system dialog",
    )

    create_button = widgets.Button(
        description="Set Directory",
        button_style="danger",
        icon="check",
        layout=widgets.Layout(width="150px"),
        tooltip="Confirm and create directory",
    )

    open_button = widgets.Button(
        description="Open in Finder",
        button_style="info",
        icon="external-link",
        layout=widgets.Layout(width="180px"),
        disabled=True,
    )

    status_output = widgets.Output()

    # Store current directory in widget metadata (public attribute to avoid
    # protected access)
    widget_container = widgets.VBox()
    # store as a public attribute; use setattr to avoid static analyzer
    # complaints on unknown attributes
    widget_container.export_dir = Path(default_dir)

    def on_browse_click(b) -> None:  # pylint: disable=unused-argument
        """Handle browse button click using OS-native dialogs."""
        _ = b
        try:
            path = None
            if platform.system() == "Darwin":
                # macOS AppleScript
                cmd = [
                    "osascript",
                    "-e",
                    (
                        'POSIX path of (choose folder with prompt "Select '
                        'Export Directory")'
                    ),
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                path = result.stdout.strip()
            elif platform.system() == "Windows":
                # PowerShell
                ps_script = (
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
                    "$f.ShowDialog() | Out-Null; "
                    "$f.SelectedPath"
                )
                result = subprocess.run(
                    ["powershell", "-Command", ps_script],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                path = result.stdout.strip()

            if path:
                custom_path_input.value = path

        except subprocess.CalledProcessError:
            pass  # User cancelled
        except Exception as e:  # pylint: disable=broad-exception-caught
            with status_output:
                print(f"⚠️  Browse failed: {e}")

    def on_create_click(b) -> None:  # pylint: disable=unused-argument
        _ = b
        with status_output:
            status_output.clear_output(wait=True)

            # Determine path
            dir_path = custom_path_input.value
            export_dir = Path(dir_path).expanduser().resolve()

            try:
                export_dir.mkdir(parents=True, exist_ok=True)

                # Test write permission
                test_file = export_dir / ".test_write"
                test_file.touch()
                test_file.unlink()

                widget_container.export_dir = export_dir

                if export_dir.exists():
                    create_button.button_style = "success"
                    print(f"✅ Export directory set to:  {export_dir}")
                else:
                    raise ValueError(
                        f"Unable to set export directory to {export_dir}",
                    )

                # Count existing files
                json_count = len(list(export_dir.glob("*.json")))
                yaml_count = len(list(export_dir.glob("*.yaml")))
                csv_count = len(list(export_dir.glob("*.csv")))
                total = json_count + yaml_count + csv_count

                if total > 0:
                    print(
                        f"   Found:  {json_count} JSON, {yaml_count} YAML, "
                        f"{csv_count} CSV",
                    )
                else:
                    print("   Directory is empty")

                open_button.disabled = False

                # Trigger callback
                if on_change_callback:
                    on_change_callback(export_dir)

            except Exception as e:  # pylint: disable=broad-exception-caught
                create_button.button_style = "danger"
                print(f"❌ Error:  {e!s}")

    def on_open_click(b):  # pylint: disable=unused-argument
        _ = b
        try:
            if hasattr(widget_container, "export_dir"):
                export_dir = widget_container.export_dir
            else:
                export_dir = Path.cwd()

            if platform.system() == "Darwin":
                subprocess.run(["open", str(export_dir)], check=False)
            elif platform.system() == "Windows":
                subprocess.run(["explorer", str(export_dir)], check=False)
            else:
                subprocess.run(["xdg-open", str(export_dir)], check=False)
        except Exception as e:  # pylint: disable=broad-exception-caught
            with status_output:
                print(f"⚠️  Could not open:  {e}")

    create_button.on_click(on_create_click)
    open_button.on_click(on_open_click)
    browse_button.on_click(on_browse_click)

    # Assemble widget
    action_buttons = (
        [create_button, open_button] if show_browser else [create_button]
    )

    input_row = widgets.HBox(
        [custom_path_input, browse_button],
        layout=widgets.Layout(align_items="center"),
    )

    widget_container.children = [
        widgets.HTML("<h4>📁 Export Directory Configuration</h4>"),
        widgets.HTML(
            (
                "<p style='color: #666;'>"
                "Choose where to save portfolio exports</p>"
            ),
        ),
        input_row,
        widgets.HBox(action_buttons),
        status_output,
    ]

    # Auto-initialize default
    default_path = Path(default_dir).expanduser().resolve()
    default_path.mkdir(parents=True, exist_ok=True)
    widget_container.export_dir = default_path

    return widget_container


def get_export_dir_from_widget(widget: widgets.VBox) -> Path:
    """Extract export directory Path from configuration widget.

    Args:
        widget: Widget created by create_export_dir_widget()

    Returns:
        Path object for export directory

    """
    return widget.export_dir
