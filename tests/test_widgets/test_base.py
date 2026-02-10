"""Tests for deltadewa.widgets.base module."""

import pytest
from deltadewa.widgets.base import InteractiveOutput


class TestInteractiveOutput:
    """Test cases for InteractiveOutput class."""

    def test_initialization(self):
        """Test InteractiveOutput can be instantiated."""
        output = InteractiveOutput()
        assert output is not None
        assert hasattr(output, "widget")
        assert output.widget is not None

    def test_update_decorator(self):
        """Test update decorator wraps function correctly."""
        output = InteractiveOutput()
        call_count = []

        @output.update
        def test_func(value):
            call_count.append(value)
            return f"processed: {value}"

        result = test_func(42)
        assert result == "processed: 42"
        assert call_count == [42]

    def test_clear_method(self):
        """Test clear method can be called."""
        output = InteractiveOutput()
        # Should not raise any exception
        output.clear()

    def test_update_with_args_kwargs(self):
        """Test update decorator handles args and kwargs."""
        output = InteractiveOutput()
        results = []

        @output.update
        def test_func(*args, **kwargs):
            results.append((args, kwargs))
            return len(args) + len(kwargs)

        result = test_func(1, 2, 3, foo="bar", baz="qux")
        assert result == 5
        assert results == [((1, 2, 3), {"foo": "bar", "baz": "qux"})]

    def test_widget_attribute(self):
        """Test that widget attribute is an ipywidgets Output."""
        output = InteractiveOutput()
        # Widget should have expected methods
        assert hasattr(output.widget, "clear_output")
        assert callable(output.widget.clear_output)
