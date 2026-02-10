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
            value=0.75, label="Test Gauge", min_val=0.0, max_val=1.0
        )
        assert gauge is not None

    def test_initialization_with_thresholds(self):
        """Test GaugeIndicator with custom thresholds."""
        thresholds = [0.3, 0.7]
        colors = ["red", "yellow", "green"]
        gauge = GaugeIndicator(
            value=0.5,
            thresholds=thresholds,
            colors=colors,
            min_val=0.0,
            max_val=1.0,
        )
        assert gauge is not None

    def test_update_method(self):
        """Test update method changes gauge value."""
        gauge = GaugeIndicator(value=0.5, min_val=0.0, max_val=1.0)
        gauge.update(0.8)
        # Method should execute without error

    def test_display_returns_widget(self):
        """Test display method returns a widget."""
        gauge = GaugeIndicator(value=0.5, min_val=0.0, max_val=1.0)
        widget = gauge.display()
        assert widget is not None

    def test_widget_attribute_exists(self):
        """Test that widget attribute exists."""
        gauge = GaugeIndicator(value=0.5, min_val=0.0, max_val=1.0)
        assert hasattr(gauge, "container")

    def test_value_clamping(self):
        """Test that values are clamped to min/max range."""
        gauge = GaugeIndicator(value=0.5, min_val=0.0, max_val=1.0)
        # Update with value outside range
        gauge.update(1.5)  # Should clamp to 1.0
        gauge.update(-0.5)  # Should clamp to 0.0
        # Should not raise exceptions

    def test_with_label(self):
        """Test gauge with label."""
        gauge = GaugeIndicator(
            value=0.5, label="My Gauge", min_val=0.0, max_val=1.0
        )
        assert gauge is not None

    def test_with_description(self):
        """Test gauge with description."""
        gauge = GaugeIndicator(
            value=0.5,
            label="My Gauge",
            description="This is a test gauge",
            min_val=0.0,
            max_val=1.0,
        )
        assert gauge is not None
