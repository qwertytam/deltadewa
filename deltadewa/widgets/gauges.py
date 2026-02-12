"""
Gauge indicator widgets for visual metrics display.

This module provides visual gauge indicators with configurable color gradients
and value markers for displaying portfolio health metrics.
"""

from typing import Optional
import ipywidgets as widgets  # type: ignore[import-untyped]
from deltadewa.colours import DEFAULT_PALETTE


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
        start: float = 0.0,
        end: float = 100.0,
        min_val: float = 25.0,
        mid_val: float = 50.0,
        max_val: float = 75.0,
        actual: float = 50.0,
        low_color: str = DEFAULT_PALETTE.negative,  # Red
        mid_color: str = DEFAULT_PALETTE.yellow,  # Yellow/Orange
        high_color: str = DEFAULT_PALETTE.positive,  # Green
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
        if not start <= min_val <= mid_val <= max_val <= end:
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
                f"border-top: 10px solid {DEFAULT_PALETTE.dark_grey}; "
                f"z-index: 3; "
            )
            # Label above the chevron
            label_style = (
                f"position: absolute; "
                f"left: {actual_pct}%; "
                f"top: -40px; "
                f"transform: translateX(-50%); "
                f"font-size: 12px; "
                f"font-weight: bold; "
                f"color: {DEFAULT_PALETTE.dark_grey}; "
                f"white-space: nowrap; "
                f"background: rgba(255,255,255,0.0); "
                f"padding: 2px 4px; "
                f"border-radius: 3px; "
                f"z-index: 2; "
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
                f"border-left: 10px solid {DEFAULT_PALETTE.dark_grey}; "
                f"z-index: 3; "
            )
            label_style = (
                f"position: absolute; "
                f"bottom: {actual_pct}%; "
                f"left: -50px; "
                f"transform: translateY(50%); "
                f"font-size: 12px; "
                f"font-weight: bold; "
                f"color: {DEFAULT_PALETTE.dark_grey}; "
                f"white-space: nowrap; "
                f"background: rgba(255,255,255,0.0); "
                f"padding: 2px 4px; "
                f"border-radius: 3px; "
                f"z-index: 2; "
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
                    f'<div style="position:absolute; left:0; bottom:-30px; '
                    f'font-size:10px; color:#666;">'
                    f"{self.label_format.format(self.start)}</div>"
                )
                labels_html += (
                    f'<div style="position:absolute; right:0; bottom:-30px; '
                    f'font-size:10px; color:#666;">'
                    f"{self.label_format.format(self.end)}</div>"
                )

            # Min/Mid/Max tick marks and labels
            if self.show_minmidmax_labels:
                for val, label in [  # pylint: disable=unused-variable
                    (self.min_val, "min"),
                    (self.mid_val, "mid"),
                    (self.max_val, "max"),
                ]:
                    pct = self._value_to_percent(val)
                    # Tick mark
                    labels_html += (
                        f'<div style="position:absolute; left:{pct}%; bottom:-10px; '
                        f"transform:translateX(-50%); width:1px; height:8px; "
                        f'background:#666;"></div>'
                    )
                    # Label
                    labels_html += (
                        f'<div style="position:absolute; left:{pct}%; bottom:-30px; '
                        f'transform:translateX(-50%); font-size:10px; color:#666;">'
                        f"{self.label_format.format(val)}</div>"
                    )
        else:
            # Vertical orientation
            if self.show_startend_labels:
                labels_html += (
                    f'<div style="position:absolute; bottom:0; right:-35px; '
                    f'font-size:10px; color:#666; transform:translateY(50%);">'
                    f"{self.label_format.format(self.start)}</div>"
                )
                labels_html += (
                    f'<div style="position:absolute; top:0; right:-35px; '
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
                        f'<div style="position:absolute; bottom:{pct}%; right:-35px; '
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
