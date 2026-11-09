"""The /design Skew Exposure panel (Part X #9, 8c / N9).

One number, one chip, no band: the handbook gives none, so the panel
must say so and must not grade the reading in words either.
"""

from __future__ import annotations

from pathlib import Path

from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages.design.planning.skew_beta import (
    _render_skew_beta_panel_logic,
    layout,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState
from tests.clock_helpers import days_from_today
from tests.test_app.test_design import _collect_text

_EXAMPLE_IPS_YAML = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)


def _app(tmp_path: Path, *, with_leg: bool = True) -> ProgramDashApp:
    state = ProgramState.load(
        tmp_path,
        ips_path=_EXAMPLE_IPS_YAML,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    state.set_underlying_quantity(1_000.0)
    if with_leg:
        state.add_position(
            strike_price=state.portfolio.spot_price * 0.75,
            maturity_date=days_from_today(365),
            quantity=10,
            option_type=OptionType.PUT,
        )
    return create_app(
        state=state,
        market_data=StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0),
        ips_config=state.ips_config,
    )


def _text(app: ProgramDashApp) -> str:
    assert app.ips_config is not None
    return _collect_text(
        _render_skew_beta_panel_logic(
            portfolio=app.program_state.portfolio,
            ips_config=app.ips_config,
        ),
    )


def test_one_number_per_vol_point(tmp_path: Path) -> None:
    text = _text(_app(tmp_path))

    assert "per +1 vol point of downside skew" in text
    assert "of the protected book" in text


def test_says_there_is_no_band_and_grades_nothing(tmp_path: Path) -> None:
    text = _text(_app(tmp_path))

    assert "No handbook band" in text
    assert "not graded" in text
    # No grading words for the reading itself (the handbook's own
    # qualitative words appear only inside the quoted explanation).
    reading = text.split(".")[0]
    for word in ("high", "low", "strong", "weak", "adequate"):
        assert word not in reading.lower()


def test_distinguishes_exposure_from_level(tmp_path: Path) -> None:
    assert "Skew exposure is not skew level" in _text(_app(tmp_path))


def test_empty_book_says_nothing_to_measure(tmp_path: Path) -> None:
    text = _text(_app(tmp_path, with_leg=False))

    assert "nothing to measure" in text
    assert "per +1 vol point" not in text


def test_chip_names_the_ips_wing(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert app.ips_config is not None
    wing = app.ips_config.convexity.skew_reference_delta * 100

    panel = layout(
        portfolio=app.program_state.portfolio,
        ips_config=app.ips_config,
    )

    text = _collect_text(panel)
    assert f"IPS {wing:g}Δ wing" in text
    # The number uses the book's hand-entered spot, not a live one.
    assert "book spot" in text
    assert "today's spot" not in text
