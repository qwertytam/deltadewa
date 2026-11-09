"""The /design Liquidity Check panel (Part X #12, 8c / N10).

Server-side tests of the panel's markup and its "record quote" BOOK
mutation; the client-side render is covered by
``test_design.py::TestPlanningZoneRendersClientSide``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from dash import no_update

from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages.design.book import _record_liquidity_logic
from deltadewa.app.pages.design.planning.liquidity import (
    _render_liquidity_panel_logic,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsLiquidity
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState
from tests.clock_helpers import days_from_today
from tests.test_app.test_design import _collect_text

_EXAMPLE_IPS_YAML = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)


def _app(tmp_path: Path) -> ProgramDashApp:
    state = ProgramState.load(
        tmp_path,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state.add_position(
        strike_price=4000.0,
        maturity_date=days_from_today(365),
        quantity=10,
        option_type=OptionType.PUT,
    )
    return create_app(
        state=state,
        market_data=StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0),
        ips_config=state.ips_config,
    )


def _leg_id(app: ProgramDashApp) -> str:
    return app.program_state.portfolio.positions[0].position_id


def _panel_text(app: ProgramDashApp, ips_config: object = None) -> str:
    config = ips_config if ips_config is not None else app.ips_config
    return _collect_text(
        _render_liquidity_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=config,  # type: ignore[arg-type]
        ),
    )


class TestRecordLiquidity:
    """The "record quote" control is a BOOK mutation, keyed by leg id."""

    def test_records_bumps_version_and_persists(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        state = app.program_state

        version, _ = _record_liquidity_logic(
            position_id=_leg_id(app),
            bid=12.0,
            ask=13.0,
            open_interest=2_500.0,
            version=4,
            state=state,
        )

        assert version == 5
        recorded = state.portfolio.positions[0].liquidity
        assert recorded is not None
        assert recorded.open_interest == 2_500
        assert state.dirty is False  # autosaved

        reloaded = ProgramState.load(
            tmp_path,
            ips_path=_EXAMPLE_IPS_YAML,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )
        assert reloaded.portfolio.positions[0].liquidity == recorded

    @pytest.mark.parametrize(
        ("bid", "ask", "open_interest", "message"),
        [
            (None, 13.0, None, "bid and ask"),
            (12.0, None, None, "bid and ask"),
            (14.0, 13.0, None, "crossed"),
            (12.0, 13.0, 10.5, "whole number"),
            (12.0, 13.0, -1.0, "whole number"),
        ],
    )
    def test_refuses_a_bad_quote_without_mutating(
        self,
        tmp_path: Path,
        bid: float | None,
        ask: float | None,
        open_interest: float | None,
        message: str,
    ) -> None:
        app = _app(tmp_path)

        version, status = _record_liquidity_logic(
            position_id=_leg_id(app),
            bid=bid,
            ask=ask,
            open_interest=open_interest,
            version=4,
            state=app.program_state,
        )

        assert version is no_update
        assert message in _collect_text(status)
        assert app.program_state.portfolio.positions[0].liquidity is None

    def test_a_leg_removed_meanwhile_is_reported_not_crashed(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)

        version, status = _record_liquidity_logic(
            position_id="gone",
            bid=1.0,
            ask=1.1,
            open_interest=None,
            version=4,
            state=app.program_state,
        )

        assert version is no_update
        assert "no longer in the book" in _collect_text(status)


class TestLiquidityPanel:
    """What the checklist says — and what it refuses to claim."""

    def test_disclaimer_is_always_rendered(self, tmp_path: Path) -> None:
        text = _panel_text(_app(tmp_path))

        assert "not a liquidity feed" in text
        assert "#156" in text

    def test_never_checked_leg_is_due(self, tmp_path: Path) -> None:
        text = _panel_text(_app(tmp_path))

        assert "never checked" in text
        assert "1 need a fresh quote" in text

    def test_recorded_quote_is_graded_against_ips(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        _record_liquidity_logic(
            position_id=_leg_id(app),
            bid=10.0,
            ask=12.0,  # 18.2% of mid, above the template's 10%
            open_interest=None,
            version=0,
            state=app.program_state,
        )

        text = _panel_text(app)

        assert "18.2% WIDE" in text
        assert "1 wide at last check" in text
        assert "wider than 10% of mid grades WIDE" in text
        assert "open interest is recorded but not graded" in text

    def test_no_policy_renders_ungraded_and_says_why(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        _record_liquidity_logic(
            position_id=_leg_id(app),
            bid=10.0,
            ask=12.0,
            open_interest=None,
            version=0,
            state=app.program_state,
        )
        assert app.ips_config is not None
        no_policy = replace(app.ips_config, liquidity=None)

        text = _panel_text(app, no_policy)

        assert "Ungraded" in text
        assert "WIDE" not in text
        assert "wide at last check" not in text

    def test_oi_minimum_grades_open_interest(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        _record_liquidity_logic(
            position_id=_leg_id(app),
            bid=12.0,
            ask=12.5,
            open_interest=200.0,
            version=0,
            state=app.program_state,
        )
        assert app.ips_config is not None
        with_minimum = replace(
            app.ips_config,
            liquidity=IpsLiquidity(
                spread_warn_pct=10.0,
                observation_max_age_days=30,
                open_interest_min=500,
            ),
        )

        text = _panel_text(app, with_minimum)

        assert "200 LOW" in text
        assert "(you hold 5.0%)" in text
