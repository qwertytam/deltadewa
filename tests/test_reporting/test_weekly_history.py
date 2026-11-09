"""The weekly job's mark step and §4, end to end through ``main()`` (#313).

The mark and the digest are isolated both ways: a digest that fails still
leaves the week's mark, and a mark (or a history) that fails still lets
the digest send, saying why §4 has no new figure.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from deltadewa.app.import_portfolio import main as import_portfolio_main
from deltadewa.history_store import HistoryStore
from deltadewa.reporting import weekly_report as weekly_report_module
from deltadewa.reporting.weekly_report import main

if TYPE_CHECKING:
    from collections.abc import Sequence

_IPS = Path(__file__).parent.parent.parent / "config" / "ips.example.yaml"
# Relative maturities, so the book stays live under the clock-shift probe.
_PORTFOLIO = Path("examples/portfolios/spx_tail_20m.yaml")

_EXIT_OK = 0
_EXIT_REFUSED = 1
_EXIT_BUILD_FAILED = 3


def _run(export_dir: Path, *extra: str) -> int:
    """Run the digest for the program's own date: the mark is taken."""
    args: Sequence[str] = [
        "--export-dir",
        str(export_dir),
        "--ips-path",
        str(_IPS),
        *extra,
    ]
    return main(list(args))


def _digest_text(export_dir: Path) -> str:
    (path,) = (export_dir / "reports" / "weekly").glob("digest-*.md")
    return path.read_text(encoding="utf-8")


@pytest.fixture
def export_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tmp export dir holding the §4 example book; no market cache."""
    monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))
    assert (
        import_portfolio_main(
            [
                str(_PORTFOLIO),
                "--export-dir",
                str(tmp_path),
                "--ips-path",
                str(_IPS),
            ],
        )
        == 0
    )
    return tmp_path


def _marks(export_dir: Path) -> int:
    return len(HistoryStore(export_dir / "history").load().marks)


def test_first_run_opens_the_history(export_dir: Path) -> None:
    """The first digest takes the opening mark and says what it means."""
    assert _run(export_dir) == _EXIT_OK
    assert _marks(export_dir) == 1
    text = _digest_text(export_dir)
    assert "No position history before" in text
    assert "not yet measurable (one mark" in text
    assert "PENDING" not in text
    assert "Theta carry drag (annual, model)" in text
    (html_path,) = (export_dir / "reports" / "weekly").glob("digest-*.html")
    html = html_path.read_text(encoding="utf-8")
    assert "No position history before" in html
    assert "PENDING" not in html


def test_backdated_run_takes_no_mark(export_dir: Path) -> None:
    """A re-run for a past date cannot mark today's book as of then."""
    assert _run(export_dir, "--as-of", "2026-08-05") == _EXIT_OK
    assert _marks(export_dir) == 0
    assert "no mark taken: the book is priced on" in _digest_text(export_dir)


def test_failed_build_still_leaves_the_mark(
    export_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#364's raise writes no digest, but the week keeps its boundary."""

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("simulated build failure")

    monkeypatch.setattr(weekly_report_module, "build_and_render", _boom)
    assert _run(export_dir) == _EXIT_BUILD_FAILED
    assert _marks(export_dir) == 1


def test_failed_mark_does_not_stop_the_digest(
    export_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The digest still builds, and §4 says the mark step failed."""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(weekly_report_module, "take_mark", _boom)
    assert _run(export_dir) == _EXIT_OK
    text = _digest_text(export_dir)
    assert "This week: no mark taken — the mark step failed: disk full." in (
        text
    )
    assert "has not started" in text


def test_unreadable_history_degrades_section_four(export_dir: Path) -> None:
    """A corrupt history costs §4 its figures, not the digest."""
    history = export_dir / "history"
    history.mkdir(exist_ok=True)
    (history / "marks.jsonl").write_text("{broken\n")
    assert _run(export_dir) == _EXIT_OK
    text = _digest_text(export_dir)
    assert "The position history could not be read:" in text
    assert "| Realized carry | unavailable |" in text


def test_empty_book_is_refused_but_still_marked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A book that closed everything still needs its V1 = 0 boundary."""
    monkeypatch.setenv("DELTADEWA_CACHE_DIR", str(tmp_path / "cache"))
    assert _run(tmp_path) == _EXIT_REFUSED
    marks = HistoryStore(tmp_path / "history").load().marks
    assert len(marks) == 1
    assert marks[0].hedge_value == pytest.approx(0.0)


def test_non_utf8_history_degrades_section_four_not_the_digest(
    export_dir: Path,
) -> None:
    """An unreadable file once escaped as exit 3 and cost the whole digest."""
    history = export_dir / "history"
    history.mkdir(exist_ok=True)
    (history / "events.jsonl").write_bytes(b"\xff\xfe not utf-8\n")
    assert _run(export_dir) == _EXIT_OK
    text = _digest_text(export_dir)
    assert "The position history could not be read:" in text
    assert "cannot be read" in text


def test_a_raise_building_section_four_does_not_cost_the_digest(
    export_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whatever §4's builder raises, the rest of the digest still sends."""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise ValueError("simulated §4 failure")

    monkeypatch.setattr(
        weekly_report_module,
        "build_realized_carry_section",
        _boom,
    )
    assert _run(export_dir) == _EXIT_OK
    text = _digest_text(export_dir)
    assert "The position history could not be read: simulated §4 failure" in (
        text
    )
