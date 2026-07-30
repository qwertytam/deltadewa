"""Tests for the deltadewa.app page placeholders."""

from dash import html

from deltadewa.app.pages import design, monitor


class TestPageLayouts:
    """Each page module must expose a constructible Dash layout."""

    def test_monitor_layout_is_a_dash_component(self) -> None:
        assert isinstance(monitor.layout, html.Div)

    def test_design_layout_is_a_dash_component(self) -> None:
        assert isinstance(design.layout, html.Div)

    def test_pages_are_distinct(self) -> None:
        assert monitor.layout is not design.layout
        assert monitor.layout.className != design.layout.className
