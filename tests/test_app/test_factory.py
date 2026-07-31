"""Tests for deltadewa.app.factory — app construction and state wiring."""

from pathlib import Path

import pytest

from deltadewa.app.factory import (
    FetchCapableProviderError,
    ProgramDashApp,
    create_app,
)
from deltadewa.constants import ExerciseStyle
from deltadewa.marketdata import CboeFredProvider, StaticProvider
from deltadewa.state import ProgramState

_MISSING_IPS = Path("does-not-exist-ips.yaml")


def _state(tmp_path: Path) -> ProgramState:
    return ProgramState.load(
        tmp_path,
        ips_path=tmp_path / _MISSING_IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )


def _provider() -> StaticProvider:
    return StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)


class TestCreateApp:
    """create_app() builds a real Dash app over one shared ProgramState."""

    def test_returns_a_program_dash_app(self, tmp_path: Path) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())

        assert isinstance(app, ProgramDashApp)

    def test_wires_the_same_state_instance(self, tmp_path: Path) -> None:
        state = _state(tmp_path)

        app = create_app(state=state, market_data=_provider())

        assert app.program_state is state

    def test_two_apps_carry_distinct_state(self, tmp_path: Path) -> None:
        first_state = _state(tmp_path / "a")
        second_state = _state(tmp_path / "b")

        first_app = create_app(state=first_state, market_data=_provider())
        second_app = create_app(state=second_state, market_data=_provider())

        assert first_app.program_state is not second_app.program_state

    def test_rejects_a_fetch_capable_provider(self, tmp_path: Path) -> None:
        provider = CboeFredProvider(cache_dir=tmp_path)

        with pytest.raises(FetchCapableProviderError):
            create_app(state=_state(tmp_path), market_data=provider)


class TestRoutes:
    """Both pages must come up over HTTP without a server-side exception."""

    def test_monitor_route_returns_ok(self, tmp_path: Path) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())
        client = app.server.test_client()

        response = client.get("/monitor")

        assert response.status_code == 200

    def test_design_route_returns_ok(self, tmp_path: Path) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())
        client = app.server.test_client()

        response = client.get("/design")

        assert response.status_code == 200
