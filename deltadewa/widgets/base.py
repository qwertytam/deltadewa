"""Base widget classes for the deltadewa interactive widgets.

This module provides fundamental widget wrapper classes used throughout
the deltadewa widget system.
"""

from collections.abc import Callable
from typing import Any

import ipywidgets as widgets


class InteractiveOutput:
    """Wrapper for widget output with automatic clearing.

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

    def __init__(self) -> None:
        """Initialize output widget."""
        self.widget = widgets.Output()

    def update(
        self,
        func: Callable[..., Any],
    ) -> Callable[..., Any]:
        """Create wrapper function to handle output clearing.

        Args:
            func: Function to wrap with output clearing logic

        Returns:
            Wrapped function that clears output before executing

        """

        def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            with self.widget:
                self.widget.clear_output(wait=True)
                return func(*args, **kwargs)

        return wrapper

    def clear(self) -> None:
        """Manually clear the output widget."""
        self.widget.clear_output()
