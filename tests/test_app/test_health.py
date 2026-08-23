"""Tests for the /health endpoint (deltadewa.app.factory.create_app)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from deltadewa.app.factory import create_app
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState

_MISSING_IPS = Path("does-not-exist-ips.yaml")
_MATURITY = datetime(2027, 6, 30, tzinfo=UTC)


def _state(tmp_path: Path) -> ProgramState:
    return ProgramState.load(
        tmp_path,
        ips_path=tmp_path / _MISSING_IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )


def _provider() -> StaticProvider:
    return StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)


class TestHealth:
    """/health is a cheap, always-registered liveness+provenance probe."""

    def test_returns_200_with_ok_status(self, tmp_path: Path) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())
        client = app.server.test_client()

        response = client.get("/health")

        assert response.status_code == 200
        assert response.get_json()["status"] == "ok"

    def test_state_loaded_false_for_a_fresh_book(self, tmp_path: Path) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())
        client = app.server.test_client()

        payload = client.get("/health").get_json()

        assert payload["state_loaded"] is False

    def test_state_loaded_true_once_a_save_file_exists(
        self,
        tmp_path: Path,
    ) -> None:
        seed = _state(tmp_path)
        seed.add_position(
            strike_price=5000.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
        )
        reloaded = _state(tmp_path)  # picks up the autosaved file
        app = create_app(state=reloaded, market_data=_provider())

        payload = app.server.test_client().get("/health").get_json()

        assert payload["state_loaded"] is True

    def test_market_data_provenance_reflects_the_provider(
        self,
        tmp_path: Path,
    ) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())

        payload = app.server.test_client().get("/health").get_json()

        assert payload["market_data"]["source"] == "STATIC"
        assert payload["market_data"]["as_of"] is None

    def test_state_section_is_empty_for_a_fresh_book(
        self,
        tmp_path: Path,
    ) -> None:
        """#355: no file yet means nothing was written by anyone."""
        app = create_app(state=_state(tmp_path), market_data=_provider())

        payload = app.server.test_client().get("/health").get_json()

        assert payload["state"]["written_by"] is None
        assert payload["state"]["loaded_at"] is None
        assert payload["state"]["external_write_detected"] is False

    def test_state_section_reflects_who_wrote_the_file(
        self,
        tmp_path: Path,
    ) -> None:
        """#355: written_by names the process the worker itself saved as."""
        seed = _state(tmp_path)
        seed.add_position(
            strike_price=5000.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
        )
        app = create_app(state=seed, market_data=_provider())

        payload = app.server.test_client().get("/health").get_json()

        assert payload["state"]["written_by"] == "app"
        assert payload["state"]["loaded_at"] is not None
        assert payload["state"]["external_write_detected"] is False

    def test_state_section_flags_a_write_from_another_process(
        self,
        tmp_path: Path,
    ) -> None:
        """#355: a file changed by another process is detectable live.

        Two independent ``ProgramState`` instances against the same
        directory — the app's (wrapped in the running ``create_app``) and
        a stand-in CLI importer — never sharing an object, matching the
        real two-process shape.
        """
        app_state = _state(tmp_path)
        app = create_app(state=app_state, market_data=_provider())

        cli_state = ProgramState.load(
            tmp_path,
            ips_path=tmp_path / _MISSING_IPS,
            default_exercise_style=ExerciseStyle.EUROPEAN,
            writer_label="import_portfolio_cli",
        )
        cli_state.add_position(
            strike_price=5000.0,
            maturity_date=_MATURITY,
            quantity=1,
            option_type=OptionType.PUT,
        )

        payload = app.server.test_client().get("/health").get_json()

        assert payload["state"]["external_write_detected"] is True
        # The running worker never reloaded — it still reports nothing.
        assert payload["state"]["written_by"] is None
