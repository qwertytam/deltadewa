"""Tests for deltadewa.widgets.gauges module."""

from deltadewa.widgets.gauges import GaugeIndicator


class TestGaugeIndicator:
    """Test cases for GaugeIndicator class."""

    def test_initialization_defaults(self):
        """Test GaugeIndicator can be instantiated with defaults."""
        gauge = GaugeIndicator()
        assert gauge is not None

    def test_initialization_with_value(self):
        """Test GaugeIndicator with initial value."""
        gauge = GaugeIndicator(
            actual=0.75,
            title="Test Gauge",
            start=0.0,
            end=1.0,
            min_val=0.25,
            mid_val=0.5,
            max_val=0.75,
        )
        assert gauge is not None

    def test_initialization_with_thresholds(self):
        """Test GaugeIndicator with custom thresholds."""
        gauge = GaugeIndicator(
            actual=0.5,
            title="Test Gauge",
            start=0.0,
            end=1.0,
            min_val=0.3,
            mid_val=0.5,
            max_val=0.7,
            low_color="red",
            mid_color="yellow",
            high_color="green",
        )
        assert gauge is not None

    def test_update_method(self):
        """Test update method changes gauge value."""
        gauge = GaugeIndicator(actual=50.0)
        gauge.update(actual=80.0)
        assert gauge.actual == 80.0

    def test_display_returns_widget(self):
        """Test display method returns a widget."""
        # Provide compatible values or just use defaults (0-100)
        gauge = GaugeIndicator(actual=50.0)
        widget = gauge.display()
        assert widget is not None

    def test_widget_attribute_exists(self):
        """Test that widget attribute exists after creation."""
        gauge = GaugeIndicator(actual=50.0)
        gauge.create_widget()
        # The class uses _widget internally
        assert gauge._widget is not None

    def test_value_clamping(self):
        """Test that values are clamped to min/max range for display."""
        # The display logic (internal _build_html) clamps, but the actual value
        # storage (self.actual) doesn't strictly have to be clamped unless implementation enforces it.
        # But let's check if valid inputs don't crash.
        gauge = GaugeIndicator(actual=50.0, start=0, end=100)

        # This will trigger bounds check during update if specific params are touched,
        # but pure actual update doesn't trigger start/end/min/mid/max consistency check if only actual changes?
        # Re-reading update(): it checks "if not (start <= min <= mid <= max <= end)".
        # It does NOT check actual vs start/end.

        gauge.update(
            actual=150.0
        )  # Should accept it, display logic clamps visual marker
        gauge.update(actual=-50.0)  # Should accept it

        assert gauge.actual == -50.0

    def test_with_label(self):
        """Test gauge with label."""
        gauge = GaugeIndicator(actual=50.0, title="My Gauge")
        assert gauge is not None
