"""CHANGELOG.md and pyproject.toml agree about the current version (#451).

Versioned headings once stopped at 0.7.0 while tags ran to v0.9.1. This
pins the rule in ``docs/RELEASING.md``: the newest versioned heading is
the version in ``pyproject.toml``, ``[Unreleased]`` sits above it, and every
versioned heading has a link reference. It reads two files and needs no
git, so it runs in a bare CI checkout; whether the tag exists is a release
step, not something an offline test can see.
"""

import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent.parent
_CHANGELOG = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
_HEADING = re.compile(
    r"^## \[(?P<name>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?\s*$",
    re.MULTILINE,
)
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def _headings() -> list[tuple[str, str | None]]:
    return [
        (m.group("name"), m.group("date"))
        for m in _HEADING.finditer(_CHANGELOG)
    ]


def _pyproject_version() -> str:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text("utf-8"))
    return str(data["project"]["version"])


def test_unreleased_heading_is_first() -> None:
    headings = _headings()
    assert headings, "CHANGELOG.md has no '## [..]' headings"
    assert headings[0][0] == "Unreleased"


def test_newest_versioned_heading_is_the_pyproject_version() -> None:
    versioned = [h for h in _headings() if _VERSION.match(h[0])]
    assert versioned, "CHANGELOG.md has no versioned heading"
    assert versioned[0][0] == _pyproject_version(), (
        "pyproject.toml and CHANGELOG.md's newest heading disagree: cut "
        "the release as docs/RELEASING.md describes (rename [Unreleased], "
        "bump the version, update the links) in one PR"
    )


def test_versioned_headings_are_dated_and_descending() -> None:
    versioned = [h for h in _headings() if _VERSION.match(h[0])]
    assert all(date for _, date in versioned)
    keys = [tuple(int(p) for p in name.split(".")) for name, _ in versioned]
    assert keys == sorted(keys, reverse=True)


@pytest.mark.parametrize("name", [h[0] for h in _headings()])
def test_every_heading_has_a_link_reference(name: str) -> None:
    assert re.search(
        rf"^\[{re.escape(name)}\]: https://", _CHANGELOG, re.MULTILINE
    ), f"no '[{name}]: https://...' link at the foot of CHANGELOG.md"


def test_unreleased_link_compares_from_the_newest_tag() -> None:
    newest = next(n for n, _ in _headings() if _VERSION.match(n))
    assert re.search(
        rf"^\[Unreleased\]: \S+/compare/v{re.escape(newest)}\.\.\.HEAD$",
        _CHANGELOG,
        re.MULTILINE,
    )
