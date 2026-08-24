"""Tests for the /health endpoint (deltadewa.app.factory.create_app)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from deltadewa.app.factory import create_app
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState

_MISSING_IPS = Path("does-not-exist-ips.yaml")
_EXAMPLE_IPS = (
    Path(__file__).parent.parent.parent / "config" / ("ips.example.yaml")
)
_MATURITY = datetime(2027, 6, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolated_cache_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Point DELTADEWA_CACHE_DIR at a per-test dir, not the real machine's.

    #309's cache_dir_writable check does a real write — without this every
    test in this module would mkdir/write/unlink under the developer's
    actual ``~/.cache/deltadewa/marketdata`` (default_cache_dir()'s
    fallback), a live side effect well outside pytest's tmp_path sandbox.
    """
    monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))


def _state(tmp_path: Path) -> ProgramState:
    """A state with no IPS loaded — ``ips_loaded`` is False here."""
    return ProgramState.load(
        tmp_path,
        ips_path=tmp_path / _MISSING_IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )


def _write_ips_fixture(tmp_path: Path) -> Path:
    """Copy the real example IPS to *tmp_path*, valid and self-contained."""
    fixture_path = tmp_path / "ips.yaml"
    fixture_path.write_text(
        _EXAMPLE_IPS.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return fixture_path


def _fully_wired_state(tmp_path: Path) -> ProgramState:
    """A state with a real, complete IPS loaded — every check should pass.

    ``default_exercise_style`` is deliberately left unset so it's wired
    from ``pricing.exercise_style`` by the real boot path (#295), not
    handed in by the test — the same distinction #295's own regression
    tests insist on.
    """
    ips_path = _write_ips_fixture(tmp_path)
    return ProgramState.load(tmp_path, ips_path=ips_path)


def _provider() -> StaticProvider:
    return StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)


class TestHealth:
    """/health is a cheap, always-registered liveness+provenance probe."""

    def test_returns_200_with_ok_status_when_fully_wired(
        self,
        tmp_path: Path,
    ) -> None:
        app = create_app(
            state=_fully_wired_state(tmp_path),
            market_data=_provider(),
        )
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


class TestBootWiring:
    """#309: /health must catch a wiring failure, not just state presence.

    Each check gets its own regression: the healthy path (fully wired,
    ``status: ok``) plus the specific failure that check exists to catch.
    """

    def test_fully_wired_boot_reports_ok_for_every_check(
        self,
        tmp_path: Path,
    ) -> None:
        app = create_app(
            state=_fully_wired_state(tmp_path),
            market_data=_provider(),
        )

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "ok"
        boot_wiring = payload["boot_wiring"]
        assert set(boot_wiring) == {
            "ips_loaded",
            "ips_sections_configured",
            "exercise_style_wired",
            "state_persisted",
            "state_file_undisturbed",
            "cache_dir_writable",
        }
        assert all(check["ok"] for check in boot_wiring.values())
        # config/ips.example.yaml carries all three optional sections.
        assert boot_wiring["ips_sections_configured"]["value"] == []

    def test_missing_ips_degrades_status_and_flags_ips_loaded(
        self,
        tmp_path: Path,
    ) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "degraded"
        assert payload["boot_wiring"]["ips_loaded"]["ok"] is False

    def test_unwired_exercise_style_degrades_status(
        self,
        tmp_path: Path,
    ) -> None:
        """#295's own bug, reproduced: no IPS and no explicit override."""
        state = ProgramState.load(
            tmp_path,
            ips_path=tmp_path / _MISSING_IPS,
            default_exercise_style=None,
        )
        app = create_app(state=state, market_data=_provider())

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "degraded"
        assert payload["boot_wiring"]["exercise_style_wired"]["ok"] is False

    def test_wired_exercise_style_reports_ok_with_the_resolved_value(
        self,
        tmp_path: Path,
    ) -> None:
        app = create_app(
            state=_fully_wired_state(tmp_path),
            market_data=_provider(),
        )

        payload = app.server.test_client().get("/health").get_json()

        check = payload["boot_wiring"]["exercise_style_wired"]
        assert check["ok"] is True
        assert "EUROPEAN" in check["detail"]

    def test_defaulted_ips_sections_are_reported_but_never_degrade(
        self,
        tmp_path: Path,
    ) -> None:
        """Report-only per B3a.2's direction: defaults are not a failure."""
        # A minimal ips.yaml with every required section but none of the
        # three optional ones — market_environment/sizing/vega all fall
        # back to their DEFAULT_* constants.
        example = _EXAMPLE_IPS.read_text(encoding="utf-8")
        lines = example.splitlines()
        optional_headers = {"sizing:", "vega:", "market_environment:"}
        trimmed: list[str] = []
        skipping = False
        for line in lines:
            if line.rstrip() in optional_headers:
                skipping = True
                continue
            if skipping and line.startswith((" ", "\t")):
                continue
            skipping = False
            trimmed.append(line)
        ips_path = tmp_path / "ips.yaml"
        ips_path.write_text("\n".join(trimmed), encoding="utf-8")

        state = ProgramState.load(tmp_path, ips_path=ips_path)
        app = create_app(state=state, market_data=_provider())

        payload = app.server.test_client().get("/health").get_json()

        check = payload["boot_wiring"]["ips_sections_configured"]
        assert check["ok"] is True
        assert set(check["value"]) == {
            "sizing",
            "vega",
            "market_environment",
        }
        # The only failing thing here would be an unrelated check; this
        # one must not be why status is anything but ok.
        assert payload["status"] == "ok"

    def test_dirty_state_degrades_status_and_flags_state_persisted(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        state = _state(tmp_path)

        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated crash mid-write")

        with monkeypatch.context() as patch:
            patch.setattr("deltadewa.persistence.json.dump", _raise)
            with pytest.raises(RuntimeError, match="simulated crash"):
                state.add_position(
                    strike_price=5000.0,
                    maturity_date=_MATURITY,
                    quantity=1,
                    option_type=OptionType.PUT,
                )
        assert state.dirty is True

        app = create_app(state=state, market_data=_provider())
        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "degraded"
        assert payload["boot_wiring"]["state_persisted"]["ok"] is False

    def test_external_write_degrades_status_and_state_file_undisturbed(
        self,
        tmp_path: Path,
    ) -> None:
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

        assert payload["status"] == "degraded"
        check = payload["boot_wiring"]["state_file_undisturbed"]
        assert check["ok"] is False
        # The worker never re-reads the file, so it can only report its
        # OWN last known write (here: none — it booted before any file
        # existed), not who the external write actually came from.
        assert "restart is required" in check["detail"]

    def test_cache_dir_writable_reports_the_resolved_path(
        self,
        tmp_path: Path,
    ) -> None:
        app = create_app(state=_state(tmp_path), market_data=_provider())

        payload = app.server.test_client().get("/health").get_json()

        check = payload["boot_wiring"]["cache_dir_writable"]
        assert check["ok"] is True
        assert check["value"] == str(tmp_path / "cache")

    def test_unwritable_cache_dir_degrades_status(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A file where the cache dir should be: mkdir(parents=True) fails."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setenv(
            "DELTADEWA_CACHE_DIR",
            str(blocker / "marketdata-cache"),
        )
        app = create_app(state=_state(tmp_path), market_data=_provider())

        payload = app.server.test_client().get("/health").get_json()

        assert payload["status"] == "degraded"
        assert payload["boot_wiring"]["cache_dir_writable"]["ok"] is False

    def test_status_ok_still_returns_http_200_even_when_degraded(
        self,
        tmp_path: Path,
    ) -> None:
        """/health stays a liveness probe: HTTP 200 regardless of status."""
        app = create_app(state=_state(tmp_path), market_data=_provider())
        client = app.server.test_client()

        response = client.get("/health")

        assert response.status_code == 200
        assert response.get_json()["status"] == "degraded"
