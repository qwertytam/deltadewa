"""Tests for the ``python -m deltadewa.app.import_portfolio`` CLI.

The underlying guarded write path (``ProgramState.import_portfolio``) is
already covered by ``tests/test_state.py``; these tests exercise the CLI's
own layer — argument handling, the pre-existing-state refusal, and that a
bad import never touches the state file.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from werkzeug.serving import make_server

from deltadewa.app.factory import create_app
from deltadewa.app.import_portfolio import main
from deltadewa.constants import ExerciseStyle
from deltadewa.marketdata import StaticProvider
from deltadewa.state import STATE_FILENAME, ProgramState

if TYPE_CHECKING:
    from collections.abc import Iterator

_EXAMPLE_PORTFOLIO = Path("examples/portfolios/spx_protective_put.yaml")
_MISSING_IPS = Path("does-not-exist-ips.yaml")


@pytest.fixture
def live_worker(tmp_path: Path) -> Iterator[str]:
    """Boot a real HTTP server against *tmp_path*, ``writer_label="app"``.

    Mirrors ``wsgi.py:_build()`` exactly, on a real socket rather than a
    Flask test client — the importer talks to it over ``requests.get``,
    the same as it would talk to the production gunicorn worker. This is
    what makes the two-process tests below a real regression test for
    #355 rather than a same-object test that could not reproduce it: the
    importer runs ``main()`` (its own, separate ``ProgramState``) while
    this server holds a third, independent one, both pointed at the same
    ``tmp_path``.
    """
    state = ProgramState.load(
        tmp_path,
        ips_path=tmp_path / _MISSING_IPS,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        writer_label="app",
    )
    market_data = StaticProvider(spot_prices={"SPX": 5000.0}, vix=18.0)
    app = create_app(state=state, market_data=market_data)

    server = make_server("127.0.0.1", 0, app.server)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()


def test_import_writes_state_the_app_then_loads(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A clean export dir accepts the import and the app can load it back."""
    exit_code = main(
        [
            str(_EXAMPLE_PORTFOLIO),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
        ],
    )

    assert exit_code == 0
    state_path = tmp_path / STATE_FILENAME
    assert state_path.exists()

    reloaded = ProgramState.load(tmp_path)
    assert reloaded.loaded_from == state_path
    assert len(reloaded.portfolio.positions) == 2
    assert reloaded.portfolio.get_symbol() == "SPX"
    assert reloaded.portfolio.spot_price == pytest.approx(5800.0)

    out = capsys.readouterr().out
    assert str(_EXAMPLE_PORTFOLIO) in out
    assert str(state_path) in out


def test_refuses_to_overwrite_existing_state_without_force(
    tmp_path: Path,
) -> None:
    """A second import without --force is refused and leaves state intact."""
    first = main(
        [
            str(_EXAMPLE_PORTFOLIO),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
        ],
    )
    assert first == 0

    state_path = tmp_path / STATE_FILENAME
    before = state_path.read_bytes()

    refused = main(
        [
            str(_EXAMPLE_PORTFOLIO),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
        ],
    )

    assert refused == 1
    assert state_path.read_bytes() == before

    forced = main(
        [
            str(_EXAMPLE_PORTFOLIO),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
            "--force",
        ],
    )
    assert forced == 0


def test_malformed_yaml_raises_and_writes_nothing(tmp_path: Path) -> None:
    """A malformed portfolio file fails loudly instead of a partial write.

    #325 hardened persistence.py's importers to raise a legible
    ``ValueError`` naming the missing section, rather than the bare
    ``KeyError`` this used to surface.
    """
    bad_yaml = tmp_path / "bad_portfolio.yaml"
    bad_yaml.write_text("positions:\n  - strike_price: 100.0\n")

    with pytest.raises(ValueError, match="market_parameters"):
        main(
            [
                str(bad_yaml),
                "--export-dir",
                str(tmp_path),
                "--ips-path",
                str(tmp_path / _MISSING_IPS),
            ],
        )

    assert not (tmp_path / STATE_FILENAME).exists()


def test_json_state_file_matches_example_positions(tmp_path: Path) -> None:
    """The written JSON reflects the source YAML's positions on disk."""
    main(
        [
            str(_EXAMPLE_PORTFOLIO),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
        ],
    )

    data = json.loads((tmp_path / STATE_FILENAME).read_text())
    assert len(data["positions"]) == 2
    assert data["market_parameters"]["symbol"] == "SPX"


# ---------------------------------------------------------------------------
# #261 — the shape guard, restored
# ---------------------------------------------------------------------------


def _write_non_conforming_yaml(tmp_path: Path) -> Path:
    """A book with a long call and no underlying — neither leg satisfied."""
    path = tmp_path / "non_conforming.yaml"
    path.write_text(
        "market_parameters:\n"
        "  spot_price: 100.0\n"
        "  volatility: 0.20\n"
        "  risk_free_rate: 0.03\n"
        "  dividend_yield: 0.0\n"
        "  underlying_quantity: 0.0\n"
        '  symbol: "TEST"\n'
        "  contract_size: 100\n"
        "positions:\n"
        '  - option_type: "call"\n'
        "    strike_price: 110.0\n"
        '    maturity_date: "2027-01-01"\n'
        "    quantity: 5\n"
        '    exercise_style: "EUROPEAN"\n',
    )
    return path


def _write_conforming_yaml(tmp_path: Path) -> Path:
    """A long-underlying + long-put book that is quiet at any clock shift.

    Deliberately NOT ``_EXAMPLE_PORTFOLIO``: that canonical file's
    ``maturity_date`` is an intentionally pinned absolute date (it is the
    golden fixture other tests compute exact re-priced values against —
    see ``tests/test_analysis/test_crash_repricing.py`` and
    ``docs/implementation-plan.md``'s "Canonical" entries), so it goes
    genuinely, correctly expired under a large clock-shift and would
    trip the #365 ``_warn_if_expired_legs`` advisory here — a real
    warning, not a bug. ``maturity_days`` (relative, like
    ``examples/portfolios/spx_tail_20m.yaml``) keeps this fixture's own
    "quiet on a conforming book" assertion true at every shift instead.
    """
    path = tmp_path / "conforming.yaml"
    path.write_text(
        "market_parameters:\n"
        "  spot_price: 5800.0\n"
        "  volatility: 0.17\n"
        "  risk_free_rate: 0.04\n"
        "  dividend_yield: 0.013\n"
        "  underlying_quantity: 1000.0\n"
        '  symbol: "SPX"\n'
        "  contract_size: 100\n"
        "positions:\n"
        '  - option_type: "put"\n'
        "    strike_price: 5200.0\n"
        "    maturity_days: 305\n"
        "    quantity: 5\n"
        "    volatility: 0.19\n"
        '    exercise_style: "EUROPEAN"\n',
    )
    return path


def test_conforming_import_prints_no_warning(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A conforming long-underlying + long-put book imports quiet."""
    conforming = _write_conforming_yaml(tmp_path)

    exit_code = main(
        [
            str(conforming),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
        ],
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "WARNING" not in captured.out
    assert "WARNING" not in captured.err


def test_non_conforming_import_warns_but_still_succeeds(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A non-conforming book still imports (exit 0) but warns loudly."""
    bad_shape = _write_non_conforming_yaml(tmp_path)

    exit_code = main(
        [
            str(bad_shape),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
        ],
    )

    assert exit_code == 0
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "no_underlying_no_long_puts" in err
    assert "isn't a downside-protection structure" in err
    # Unmissable under docker exec: the warning is wrapped in a rule.
    assert "!" * 10 in err


# ---------------------------------------------------------------------------
# #355 — the live-worker divergence notice
# ---------------------------------------------------------------------------


def test_no_reachable_worker_warns_and_still_exits_0(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No app listening at --app-url: best-effort, never fails the import."""
    exit_code = main(
        [
            str(_EXAMPLE_PORTFOLIO),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
            "--app-url",
            "http://127.0.0.1:1/health",  # nothing listens on port 1
        ],
    )

    assert exit_code == 0
    err = capsys.readouterr().err
    assert "Could not reach a running app worker" in err
    assert "docker compose restart app" in err


def test_no_live_check_skips_the_probe_entirely(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--no-live-check means no network attempt and no divergence notice."""
    exit_code = main(
        [
            str(_EXAMPLE_PORTFOLIO),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
            "--app-url",
            "http://127.0.0.1:1/health",
            "--no-live-check",
        ],
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "app worker" not in captured.out
    assert "app worker" not in captured.err


def test_written_by_stamped_import_portfolio_cli(tmp_path: Path) -> None:
    """The state file records which process wrote it (#355)."""
    main(
        [
            str(_EXAMPLE_PORTFOLIO),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
            "--no-live-check",
        ],
    )

    data = json.loads((tmp_path / STATE_FILENAME).read_text())
    assert data["metadata"]["written_by"] == "import_portfolio_cli"


def test_running_worker_reports_it_has_not_picked_up_the_import(
    live_worker: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The real two-process shape: a live worker is up, unrelated to the
    CLI's own ``ProgramState``, sharing only the export directory on disk.

    Importing must not silently claim to have reached it — the worker's
    own ``/health`` (queried live, over a real socket) must still show its
    original boot-time ``written_by``, not the importer's.
    """
    exit_code = main(
        [
            str(_EXAMPLE_PORTFOLIO),
            "--export-dir",
            str(tmp_path),
            "--ips-path",
            str(tmp_path / _MISSING_IPS),
            "--app-url",
            f"{live_worker}/health",
        ],
    )

    assert exit_code == 0
    err = capsys.readouterr().err
    assert "has NOT picked this up yet" in err
    assert "written_by=None" in err  # the worker booted with no file yet
    assert "docker compose restart app" in err
