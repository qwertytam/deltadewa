"""The vega row prints a figure that never contradicts its grade (#469).

#434 fixed this for crash convexity: grade on the unrounded value, and go to
two decimals (then a strict sign) rather than print a figure on a band edge
beside the opposite verdict. Vega had no equivalent. With the shipped floor of
1.5%, a reading of 1.46 printed "1.5%" beside a FAIL against a 1.5% floor: a
number on the floor, marked as a breach.

The rule is one implementation now
(:func:`~deltadewa.analysis.convexity_band.display_graded`), used by crash
convexity and vega sufficiency alike, and this pins vega against it.
"""

from __future__ import annotations

import ast
import dataclasses
import math
import re
from pathlib import Path

import pytest

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.analysis.convexity_band import (
    ConvexityGrade,
    ConvexityGrading,
    classify_band,
)
from deltadewa.app.pages.design.planning import sizing as sizing_panel
from deltadewa.ips_config import IpsVega
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.reporting.program_report import (
    VegaSection,
    _vega_compliance_row,
    build_vega_section,
)

from ..test_analysis.test_roll_by import _ips

_REPO = Path(__file__).parent.parent.parent
_EN_DASH = "\N{EN DASH}"
_FLOOR = 1.5
_CEILING = 4.0
_BAND = IpsVega(sufficiency_min_pct=_FLOOR, sufficiency_max_pct=_CEILING)
_BELOW = ConvexityGrade.BELOW
_WITHIN = ConvexityGrade.WITHIN
_ABOVE = ConvexityGrade.ABOVE


def _section(value: float | None, band: IpsVega = _BAND) -> VegaSection:
    return build_vega_section(sufficiency_pct=value, ips_vega=band)


# Each row: a name, a reading, the grade it earns, and the text printed.
_EDGE_GRID = [
    ("min - eps", math.nextafter(_FLOOR, -math.inf), _BELOW, "<1.50%"),
    ("min", _FLOOR, _WITHIN, "1.5%"),
    ("max", _CEILING, _WITHIN, "4.0%"),
    ("max + eps", math.nextafter(_CEILING, math.inf), _ABOVE, ">4.00%"),
    # The reported case: one decimal lands on the floor, the grade is below.
    ("rounds onto the floor from below", 1.46, _BELOW, "1.46%"),
    ("rounds onto the ceiling from above", 4.04, _ABOVE, "4.04%"),
    # One decimal lands on an edge, and the grade really is on that side.
    ("rounds onto the floor from above", 1.54, _WITHIN, "1.5%"),
    ("rounds onto the ceiling from below", 3.96, _WITHIN, "4.0%"),
    ("well below", 0.9, _BELOW, "0.9%"),
    ("a measured zero", 0.0, _BELOW, "0.0%"),
    ("negative", -0.2, _BELOW, "-0.2%"),
    ("mid band", 2.5, _WITHIN, "2.5%"),
    ("well above", 12.0, _ABOVE, "12.0%"),
]
_IDS = [row[0] for row in _EDGE_GRID]


class TestTheEdgesAreGradedAndDisplayed:
    @pytest.mark.parametrize(
        ("name", "value", "grade", "shown"), _EDGE_GRID, ids=_IDS
    )
    def test_the_section_grades_the_raw_value_and_prints_a_matching_figure(
        self,
        name: str,
        value: float,
        grade: ConvexityGrade,
        shown: str,
    ) -> None:
        section = _section(value)

        assert section.grade is grade, name
        assert section.meets_target is (grade is _WITHIN), name
        assert section.display() == shown, name

    @pytest.mark.parametrize(
        ("name", "value", "grade", "shown"), _EDGE_GRID, ids=_IDS
    )
    def test_the_compliance_row_prints_the_same_figure_beside_its_verdict(
        self,
        name: str,
        value: float,
        grade: ConvexityGrade,
        shown: str,
    ) -> None:
        """The digest's §6 row and /monitor's strip both read ``actual``."""
        row = _vega_compliance_row(_section(value))

        assert row.actual == shown, name
        assert row.passes is (grade is _WITHIN), name
        assert (row.action is None) is (grade is _WITHIN), name

    @pytest.mark.parametrize(
        ("name", "value", "grade", "shown"), _EDGE_GRID, ids=_IDS
    )
    def test_the_design_panel_prints_the_same_figure_beside_its_verdict(
        self,
        monkeypatch: pytest.MonkeyPatch,
        name: str,
        value: float,
        grade: ConvexityGrade,
        shown: str,
    ) -> None:
        monkeypatch.setattr(
            PortfolioAnalyzer,
            "calculate_vega_sufficiency_pct",
            lambda _self, *_a, **_k: value,
        )
        ips = dataclasses.replace(_ips(), vega=_BAND)

        panel = sizing_panel._vega_sufficiency_block(OptionPortfolio(), ips)
        text = _all_text(panel)

        assert f"moves {shown} of total portfolio value" in text, name
        verdict = "within band" if grade is _WITHIN else "outside band"
        assert f"({verdict})" in text, name
        # The bar's marker label is the same figure, not a second rounding.
        assert text.count(shown) >= 2, name


def _all_text(component: object) -> str:
    children = getattr(component, "children", component)
    if isinstance(children, str):
        return children
    if isinstance(children, list | tuple):
        return " ".join(_all_text(c) for c in children)
    return "" if children is None else _all_text(children)


class TestNoFigureContradictsItsGrade:
    """The property, not the cases: a dense sweep across both edges."""

    @staticmethod
    def _readings() -> list[float]:
        around_floor = [1.4 + i / 10_000 for i in range(2_001)]
        around_ceiling = [3.9 + i / 10_000 for i in range(2_001)]
        return around_floor + around_ceiling

    def test_a_printed_number_is_graded_the_way_the_reading_was(self) -> None:
        offenders = []
        for value in self._readings():
            section = _section(value)
            shown = section.display()
            if shown[0] in "<>":
                # A strict sign says the figure is past the edge, and which
                # side: it cannot contradict a grade it names.
                assert shown[0] == ("<" if section.grade is _BELOW else ">")
                continue
            printed = float(shown.rstrip("%"))
            if classify_band(printed, _FLOOR, _CEILING) is not section.grade:
                offenders.append((value, shown, section.grade.value))

        assert offenders == []

    def test_vega_and_convexity_print_one_reading_the_same_way(self) -> None:
        """One implementation: the same number on either band reads alike."""
        for value in self._readings():
            section = _section(value)
            grading = ConvexityGrading(
                value_pct=value,
                min_pct=_FLOOR,
                max_pct=_CEILING,
                shock_pct=-25.0,
                grade=classify_band(value, _FLOOR, _CEILING),
            )
            assert section.display() == grading.display()


class TestTheBandEdgesAreNotRoundedAway:
    def test_a_fractional_floor_reads_as_it_is(self) -> None:
        band = IpsVega(sufficiency_min_pct=1.45, sufficiency_max_pct=4.0)

        row = _vega_compliance_row(_section(2.0, band))

        assert row.target == f"1.45%{_EN_DASH}4.0% per +10 vol pts"

    def test_the_shipped_band_reads_as_before(self) -> None:
        row = _vega_compliance_row(_section(2.0))

        assert row.target == f"1.5%{_EN_DASH}4.0% per +10 vol pts"

    def test_an_unmeasured_reading_is_still_an_em_dash(self) -> None:
        section = _section(None)

        assert section.grade is ConvexityGrade.UNMEASURED
        assert section.display() == "—"
        assert _vega_compliance_row(section).actual == "—"


# A vega reading printed at fixed decimals is the #469 defect. The figure is
# printed by ``VegaSection.display`` and nothing else.
_VEGA_NAME = re.compile(r"(?:^|\.)(?:sufficiency_pct|vega_sufficiency_pct)$")
_FIXED_PRECISION = re.compile(r"\.\d+f")


def _hand_rounded_vega(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FormattedValue) or node.format_spec is None:
            continue
        if _VEGA_NAME.search(ast.unparse(node.value)) and (
            _FIXED_PRECISION.search(ast.unparse(node.format_spec))
        ):
            lines.append(node.lineno)
    return lines


class TestNoSurfaceRoundsAVegaReadingByHand:
    def test_the_package_has_none(self) -> None:
        found: list[str] = []
        for path in sorted((_REPO / "deltadewa").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found += [
                f"{path.relative_to(_REPO)}:{line}"
                for line in _hand_rounded_vega(tree)
            ]

        assert found == []

    @pytest.mark.parametrize(
        "source",
        [
            'f"{vega.sufficiency_pct:.1f}%"',
            'f"{section.sufficiency_pct:.2f}%"',
            'f"{vega_sufficiency_pct:.1f}"',
        ],
    )
    def test_the_guard_sees_a_hand_rounded_reading(self, source: str) -> None:
        assert _hand_rounded_vega(ast.parse(source)) == [1]

    def test_the_guard_leaves_the_shared_display_alone(self) -> None:
        assert _hand_rounded_vega(ast.parse('f"{section.display()}"')) == []
