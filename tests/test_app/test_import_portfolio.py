"""Tests for the ``python -m deltadewa.app.import_portfolio`` CLI.

The underlying guarded write path (``ProgramState.import_portfolio``) is
already covered by ``tests/test_state.py``; these tests exercise the CLI's
own layer — argument handling, the pre-existing-state refusal, and that a
bad import never touches the state file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deltadewa.app.import_portfolio import main
from deltadewa.state import STATE_FILENAME, ProgramState

_EXAMPLE_PORTFOLIO = Path("examples/portfolios/spx_protective_put.yaml")
_MISSING_IPS = Path("does-not-exist-ips.yaml")


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
    """A malformed portfolio file fails loudly instead of a partial write."""
    bad_yaml = tmp_path / "bad_portfolio.yaml"
    bad_yaml.write_text("positions:\n  - strike_price: 100.0\n")

    with pytest.raises(KeyError):
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
