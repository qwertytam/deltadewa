"""#381/#395: the chrome and /health guards, exercised through the real path.

``panel_guard.safe_render`` (#363) covers every panel *below* the layout.
These call sites sit one layer up: ``_serve_layout`` builds the chrome
that wraps every page, and ``/health`` backs the dead-man's-switch ping.
An unguarded raise in any of them takes down more than itself — the
layout takes ``/monitor``'s six guarded panels with it, and the endpoint
takes the alarm that would have reported the fault (#364's shape).
``/health`` itself has two independent guards, ``_assess_provenance()``
(#381) and ``run_checks()``/``summarize()`` (#395) — each degrades its
own half of the payload without taking the other down.

Every test drives the real request path rather than calling the closures
directly: the layout through Dash's own ``/_dash-layout``, the endpoint
through the Flask test client, so the guard is proven where it actually
has to hold.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Never

import pytest

from deltadewa.analysis.market_environment import assess_market_environment
from deltadewa.app.factory import ProgramDashApp, create_app
from deltadewa.constants import ExerciseStyle
from deltadewa.marketdata import StaticProvider
from deltadewa.state import ProgramState

if TYPE_CHECKING:
    from deltadewa.analysis.market_environment import MarketEnvironment

_MISSING_IPS = Path("does-not-exist-ips.yaml")
_BOOM = "cache file is corrupt"


@pytest.fixture(autouse=True)
def _isolated_cache_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep #309's real write-then-unlink probe inside tmp_path."""
    monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))


def _app(tmp_path: Path) -> ProgramDashApp:
    state = ProgramState.load(
        tmp_path,
        ips_path=tmp_path / _MISSING_IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    provider = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    return create_app(state=state, market_data=provider)


def _break_assessment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``assess_market_environment`` raise on the factory's own path.

    Deliberately an ``OSError``, not a ``MarketDataError``: the latter is
    the one class ``assess_market_environment`` catches itself
    (``market_environment.py``), so using it would test that function's
    fallback rather than this module's boundary. A corrupt cache file is
    the realistic way its documented "never raises" contract breaks.
    """

    def _raise(*_args: object, **_kwargs: object) -> Never:
        raise OSError(_BOOM)

    monkeypatch.setattr(
        "deltadewa.app.factory.assess_market_environment",
        _raise,
    )


class TestServeLayoutGuard:
    """A failed assessment degrades the chrome, not the whole layout."""

    def test_layout_still_serves_and_says_provenance_is_unavailable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app = _app(tmp_path)
        _break_assessment(monkeypatch)
        client = app.server.test_client()

        response = client.get("/_dash-layout")

        assert response.status_code == 200
        assert "PROVENANCE UNAVAILABLE" in response.get_data(as_text=True)

    def test_page_content_and_routing_survive_the_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The point of the guard: only the chrome degrades. If
        # page-content or the Location were inside the boundary, every
        # safe_render-wrapped panel below would go down with it.
        app = _app(tmp_path)
        _break_assessment(monkeypatch)
        client = app.server.test_client()

        body = client.get("/_dash-layout").get_data(as_text=True)

        assert "page-content" in body
        assert '"id":"url"' in body

    def test_healthy_assessment_renders_no_failure_banner(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        client = app.server.test_client()

        body = client.get("/_dash-layout").get_data(as_text=True)

        assert "PROVENANCE UNAVAILABLE" not in body


class TestHealthGuard:
    """The endpoint answers even when its own inputs cannot be assessed."""

    def test_responds_200_degraded_with_a_named_reason(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app = _app(tmp_path)
        _break_assessment(monkeypatch)
        client = app.server.test_client()

        response = client.get("/health")

        # 200, not 500: the process *is* alive, and a heartbeat watcher
        # that pages for a restart here would be acting on a fault a
        # restart cannot fix.
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["status"] == "degraded"
        assert payload["provenance_error"] == f"OSError: {_BOOM}"

    def test_provenance_blocks_are_null_not_a_fabricated_quality(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # UNAVAILABLE is a real DataQuality meaning "the provider failed
        # and every field is None" — a successful assessment with an
        # empty answer. Reusing it here would make a genuine feed outage
        # indistinguishable from a code fault.
        app = _app(tmp_path)
        _break_assessment(monkeypatch)
        client = app.server.test_client()

        payload = client.get("/health").get_json()

        assert payload["market_data"] is None
        assert payload["pricing_inputs"] is None

    def test_boot_wiring_still_reports_when_provenance_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The diagnosis must survive the fault that needs diagnosing.
        app = _app(tmp_path)
        _break_assessment(monkeypatch)
        client = app.server.test_client()

        payload = client.get("/health").get_json()

        assert payload["boot_wiring"]["ips_loaded"]["ok"] is False
        assert payload["state_loaded"] is False

    def test_provenance_error_is_null_on_the_healthy_path(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        client = app.server.test_client()

        payload = client.get("/health").get_json()

        assert payload["provenance_error"] is None
        assert payload["market_data"] is not None


class TestBootWiringGuard:
    """#395: the same guard, one call lower — run_checks()/summarize()."""

    def test_responds_200_degraded_with_a_named_reason(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app = _app(tmp_path)

        def _raise(*_args: object, **_kwargs: object) -> Never:
            raise OSError(_BOOM)

        monkeypatch.setattr("deltadewa.app.factory.run_checks", _raise)
        client = app.server.test_client()

        response = client.get("/health")

        # 200, not 500 — same contract as the provenance guard above.
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["status"] == "degraded"
        assert payload["boot_wiring_error"] == f"OSError: {_BOOM}"

    def test_boot_wiring_is_null_not_a_fabricated_table(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app = _app(tmp_path)

        def _raise(*_args: object, **_kwargs: object) -> Never:
            raise OSError(_BOOM)

        monkeypatch.setattr("deltadewa.app.factory.summarize", _raise)
        client = app.server.test_client()

        payload = client.get("/health").get_json()

        assert payload["boot_wiring"] is None

    def test_provenance_still_reports_when_boot_wiring_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The diagnosis must survive the fault that needs diagnosing —
        # the mirror image of TestHealthGuard's
        # test_boot_wiring_still_reports_when_provenance_fails.
        app = _app(tmp_path)

        def _raise(*_args: object, **_kwargs: object) -> Never:
            raise OSError(_BOOM)

        monkeypatch.setattr("deltadewa.app.factory.run_checks", _raise)
        client = app.server.test_client()

        payload = client.get("/health").get_json()

        assert payload["market_data"] is not None
        assert payload["provenance_error"] is None

    def test_boot_wiring_error_is_null_on_the_healthy_path(
        self,
        tmp_path: Path,
    ) -> None:
        app = _app(tmp_path)
        client = app.server.test_client()

        payload = client.get("/health").get_json()

        assert payload["boot_wiring_error"] is None
        assert payload["boot_wiring"] is not None


class TestNoSharedPrecomputedValue:
    """#376's refusal, re-asserted one layer up (#381)."""

    def test_each_surface_assesses_independently(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A shared precomputed ledger would mean one raise took down the
        # layout *and* the endpoint that would have reported it. Proven
        # by counting: /health must do its own assessment after the
        # layout has already done one, never reuse that result. The
        # absolute count is Dash's business (it may serve a layout more
        # than once per request); the increase is the contract.
        app = _app(tmp_path)
        calls: list[object] = []
        real = assess_market_environment

        def _counted(*args: object, **kwargs: object) -> MarketEnvironment:
            calls.append(args)
            return real(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(
            "deltadewa.app.factory.assess_market_environment",
            _counted,
        )
        client = app.server.test_client()

        client.get("/_dash-layout")
        after_layout = len(calls)
        client.get("/health")

        assert after_layout >= 1
        assert len(calls) > after_layout
