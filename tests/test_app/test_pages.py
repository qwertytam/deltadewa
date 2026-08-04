"""Tests for the deltadewa.app page placeholders."""

from pathlib import Path

from dash import html

from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages import design, monitor
from deltadewa.constants import ExerciseStyle
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState

_MISSING_IPS = Path("does-not-exist-ips.yaml")


def _app(tmp_path: Path) -> ProgramDashApp:
    state = ProgramState.load(
        tmp_path,
        ips_path=tmp_path / _MISSING_IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    provider = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    return create_app(state=state, market_data=provider)


class TestPageLayouts:
    """Each page module must expose a constructible Dash layout."""

    def test_monitor_render_is_a_dash_component(self, tmp_path: Path) -> None:
        app = _app(tmp_path)

        assert isinstance(monitor.render(app), html.Div)

    def test_design_render_is_a_dash_component(self, tmp_path: Path) -> None:
        app = _app(tmp_path)

        assert isinstance(design.render(app), html.Div)

    def test_pages_are_distinct(self, tmp_path: Path) -> None:
        app = _app(tmp_path)

        monitor_layout = monitor.render(app)
        design_layout = design.render(app)

        assert monitor_layout is not design_layout
        assert monitor_layout.className != design_layout.className
