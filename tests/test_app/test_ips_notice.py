"""#385: the IPS parse error reaches the page, not just the server log.

``ProgramState.load`` always had the message — ``IpsConfigError``'s own
text, written to be operator-readable. It logged it and dropped it, so
both pages could only point at ``docker compose logs app``, which on the
droplet is an SSH hop for one sentence.

These tests assert the *message*, not that some error box exists: a test
that only checked for a container would pass against the generic "see the
server log" wording this issue exists to remove.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from dash.development.base_component import Component
from plotly.utils import PlotlyJSONEncoder

from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.app.pages import design, monitor
from deltadewa.constants import ExerciseStyle
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState

_EXAMPLE_IPS = (
    Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
)
# A required field with no default, so load_ips_config raises rather than
# quietly substituting one — the failure mode #385 was reported against.
_DROPPED_FIELD = "roll_at_months_remaining"
_EXPECTED_REASON = (
    f"ips.yaml 'triggers' section missing required field '{_DROPPED_FIELD}'"
)


def _write_invalid_ips(tmp_path: Path) -> Path:
    """Copy the shipped example IPS, minus one required trigger field."""
    path = tmp_path / "ips.yaml"
    kept = [
        line
        for line in _EXAMPLE_IPS.read_text(encoding="utf-8").splitlines()
        if _DROPPED_FIELD not in line
    ]
    path.write_text("\n".join(kept), encoding="utf-8")
    return path


def _invalid_ips_state(tmp_path: Path) -> ProgramState:
    return ProgramState.load(
        tmp_path,
        ips_path=_write_invalid_ips(tmp_path),
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )


def _app(state: ProgramState) -> ProgramDashApp:
    provider = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    return create_app(
        state=state,
        market_data=provider,
        ips_config=state.ips_config,
    )


def _rendered_text(layout: Component) -> str:
    """Serialize a rendered layout so its strings can be asserted on.

    ``to_plotly_json()`` is shallow — it leaves nested components as
    objects — so this uses the same encoder Dash itself serializes a
    layout with, giving the whole tree's text in one string.
    """
    return json.dumps(layout, cls=PlotlyJSONEncoder)


class TestProgramStateCarriesTheReason:
    """The except block keeps the message instead of discarding it."""

    def test_invalid_ips_records_the_specific_reason(
        self,
        tmp_path: Path,
    ) -> None:
        state = _invalid_ips_state(tmp_path)

        assert state.ips_config is None
        assert state.ips_load_error == _EXPECTED_REASON

    def test_load_still_succeeds_without_a_policy(
        self,
        tmp_path: Path,
    ) -> None:
        # An unloadable IPS degrades the program; it must not stop it
        # booting, or the page that would explain why never renders.
        state = _invalid_ips_state(tmp_path)

        assert state.portfolio is not None

    def test_ips_path_records_which_file_was_tried(
        self,
        tmp_path: Path,
    ) -> None:
        state = _invalid_ips_state(tmp_path)

        assert state.ips_path == tmp_path / "ips.yaml"

    def test_a_valid_ips_records_no_error(self, tmp_path: Path) -> None:
        ips_path = tmp_path / "ips.yaml"
        ips_path.write_text(
            _EXAMPLE_IPS.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        state = ProgramState.load(tmp_path, ips_path=ips_path)

        assert state.ips_config is not None
        assert state.ips_load_error is None


@pytest.mark.parametrize(
    "render",
    [monitor.render, design.render],
    ids=["monitor", "design"],
)
class TestBothPagesRenderTheReason:
    """Both no-IPS states name the parse error and the container caveat."""

    def test_renders_the_exact_parse_error(
        self,
        tmp_path: Path,
        render: object,
    ) -> None:
        state = _invalid_ips_state(tmp_path)
        app = _app(state)

        body = _rendered_text(render(app))  # type: ignore[operator]

        assert _EXPECTED_REASON in body

    def test_no_longer_sends_the_reader_to_the_server_log(
        self,
        tmp_path: Path,
        render: object,
    ) -> None:
        state = _invalid_ips_state(tmp_path)
        app = _app(state)

        body = _rendered_text(render(app))  # type: ignore[operator]

        assert "see the server log at startup" not in body

    def test_names_the_container_copy_not_the_host_copy(
        self,
        tmp_path: Path,
        render: object,
    ) -> None:
        # #385's own acceptance criterion, and #386's subject: the two
        # differ exactly when this fires, and conflating them reads as
        # "your edit was wrong" when the edit was fine and the image was
        # stale.
        state = _invalid_ips_state(tmp_path)
        app = _app(state)

        body = _rendered_text(render(app))  # type: ignore[operator]

        assert "running container" in body

    def test_falls_back_when_no_policy_file_was_involved(
        self,
        tmp_path: Path,
        render: object,
    ) -> None:
        # ``app.ips_config`` can be None without a load failure — the
        # policy loaded fine and the caller simply did not pass it. The
        # page must not imply a parse error that never happened.
        ips_path = tmp_path / "ips.yaml"
        ips_path.write_text(
            _EXAMPLE_IPS.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        state = ProgramState.load(tmp_path, ips_path=ips_path)
        provider = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
        app = create_app(state=state, market_data=provider, ips_config=None)

        body = _rendered_text(render(app))  # type: ignore[operator]

        assert "No reason was recorded" in body
