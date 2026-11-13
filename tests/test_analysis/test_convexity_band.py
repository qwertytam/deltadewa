"""The convexity referee: one grade, one rounding rule (#434, #431, #433).

Every surface that says whether crash convexity is inside the IPS band asks
:func:`~deltadewa.analysis.convexity_band.grade_convexity`. These tests pin
the referee itself; ``tests/test_app/test_convexity_surfaces_agree.py`` pins
that every caller agrees with it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest

from deltadewa.analysis.convexity_band import (
    ConvexityGrade,
    ConvexityGrading,
    grade_convexity,
)
from deltadewa.ips_config import IpsConvexity

_MIN = 10.0
_MAX = 20.0
_DEPTH = -25.0


def _ips(
    *,
    target_min_pct: float = _MIN,
    target_max_pct: float = _MAX,
    crash_scenario_pct: float = _DEPTH,
) -> IpsConvexity:
    return IpsConvexity(
        crash_scenario_pct=crash_scenario_pct,
        target_min_pct=target_min_pct,
        target_max_pct=target_max_pct,
    )


def _grade(
    value: float | None,
    *,
    at: float = _DEPTH,
    ips: IpsConvexity | None = None,
) -> ConvexityGrading:
    return grade_convexity(value, ips or _ips(), at_shock_pct=at)


class TestBoundaryGrid:
    """Min, max, min-eps, max+eps, None, and a depth that is not the IPS's."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (_MIN, ConvexityGrade.WITHIN),  # inclusive at the floor
            (_MAX, ConvexityGrade.WITHIN),  # inclusive at the ceiling
            (_MIN - 1e-9, ConvexityGrade.BELOW),
            (_MAX + 1e-9, ConvexityGrade.ABOVE),
            (15.0, ConvexityGrade.WITHIN),
            (0.0, ConvexityGrade.BELOW),  # a measured zero is a real reading
            (-3.0, ConvexityGrade.BELOW),
            (None, ConvexityGrade.UNMEASURED),
        ],
    )
    def test_grade_at_the_ips_depth(
        self,
        value: float | None,
        expected: ConvexityGrade,
    ) -> None:
        assert _grade(value).grade is expected

    @pytest.mark.parametrize("value", [_MIN, 15.0, _MAX, 0.0, 99.0, None])
    @pytest.mark.parametrize("depth", [-10.0, -20.0, -24.9999, -30.0, 0.0])
    def test_any_other_depth_is_unmeasured(
        self,
        value: float | None,
        depth: float,
    ) -> None:
        """#431: the band is stated at one depth; nothing else is graded."""
        grading = _grade(value, at=depth)
        assert grading.grade is ConvexityGrade.UNMEASURED
        assert grading.meets is None

    def test_depth_match_tolerates_float_noise_below_four_places(self) -> None:
        assert _grade(15.0, at=-25.000001).grade is ConvexityGrade.WITHIN

    def test_depth_follows_the_ips_not_a_literal(self) -> None:
        ips = _ips(crash_scenario_pct=-30.0)
        assert _grade(15.0, at=-30.0, ips=ips).grade is ConvexityGrade.WITHIN
        assert (
            _grade(15.0, at=-25.0, ips=ips).grade is ConvexityGrade.UNMEASURED
        )

    def test_the_band_is_the_ips_band(self) -> None:
        ips = _ips(target_min_pct=2.0, target_max_pct=3.0)
        assert _grade(2.5, ips=ips).grade is ConvexityGrade.WITHIN
        assert _grade(15.0, ips=ips).grade is ConvexityGrade.ABOVE


class TestMeetsIsDerived:
    @pytest.mark.parametrize(
        ("grade", "meets"),
        [
            (ConvexityGrade.WITHIN, True),
            (ConvexityGrade.BELOW, False),
            (ConvexityGrade.ABOVE, False),
            (ConvexityGrade.UNMEASURED, None),
        ],
    )
    def test_meets_follows_the_grade(
        self,
        grade: ConvexityGrade,
        meets: bool | None,
    ) -> None:
        assert grade.meets is meets

    def test_grading_meets_is_the_grades(self) -> None:
        for value in (5.0, 15.0, 25.0, None):
            grading = _grade(value)
            assert grading.meets is grading.grade.meets

    def test_unmeasured_is_never_a_breach(self) -> None:
        """``None``, not ``False``: unmeasured is not breaching (#433)."""
        assert _grade(None).meets is None


class TestGradingCarriesWhatWasGraded:
    def test_it_keeps_the_raw_value_the_band_and_the_depth(self) -> None:
        grading = _grade(9.96)
        assert grading.value_pct == pytest.approx(9.96)
        assert (grading.min_pct, grading.max_pct) == (_MIN, _MAX)
        assert grading.shock_pct == _DEPTH

    def test_it_is_immutable(self) -> None:
        with pytest.raises(AttributeError):
            _grade(15.0).grade = ConvexityGrade.BELOW  # type: ignore[misc]


class TestDisplayRule:
    """Grade on the raw value; never print a figure that contradicts it."""

    @pytest.mark.parametrize(
        ("value", "shown"),
        [
            (10.2, "10.2%"),  # the live book
            (10.0, "10.0%"),  # exactly the floor: WITHIN
            (9.9, "9.9%"),  # #436's FAIL evidence
            (20.0, "20.0%"),
            (15.0, "15.0%"),
            (0.0, "0.0%"),
            (9.96, "9.96%"),  # rounds to 10.0 but is BELOW -> 2 dp
            (20.04, "20.04%"),  # rounds to 20.0 but is ABOVE -> 2 dp
            (9.999, "<10.00%"),  # still touches the edge at 2 dp
            (20.001, ">20.00%"),
            (None, "—"),
        ],
    )
    def test_display(self, value: float | None, shown: str) -> None:
        assert _grade(value).display() == shown

    def test_a_within_reading_that_rounds_out_of_band_gains_a_place(
        self,
    ) -> None:
        ips = _ips(target_min_pct=10.04)
        grading = _grade(10.04, ips=ips)
        assert grading.grade is ConvexityGrade.WITHIN
        assert grading.display() == "10.04%"

    @pytest.mark.parametrize(
        "value",
        [
            *(9.0, 9.9, 9.94, 9.95, 9.96, 9.999, 10.0, 10.01),
            *(15.0, 19.99, 20.0, 20.001, 20.04, 20.05, 21.0),
        ],
    )
    def test_the_figure_shown_never_implies_another_grade(
        self,
        value: float,
    ) -> None:
        """Whatever is printed, reading it back gives the grade beside it."""
        grading = _grade(value)
        shown = grading.display()
        number = float(re.sub(r"[<>%]", "", shown))
        if shown.startswith("<"):
            assert grading.grade is ConvexityGrade.BELOW
            assert number == _MIN
        elif shown.startswith(">"):
            assert grading.grade is ConvexityGrade.ABOVE
            assert number == _MAX
        else:
            implied = _grade(number)
            assert implied.grade is grading.grade


class TestBandDisplay:
    def test_whole_edges_print_without_decimals(self) -> None:
        assert _grade(15.0).band_display(sep="-") == "10-20%"

    def test_a_fractional_edge_is_not_rounded_away(self) -> None:
        ips = _ips(target_min_pct=10.5)
        assert _grade(15.0, ips=ips).band_display(sep="-") == "10.5-20%"

    def test_default_separator_is_an_en_dash(self) -> None:
        assert _grade(15.0).band_display() == "10\u201320%"


class TestOneComparisonSite:
    """The referee is the only place that compares against the band.

    The grep is the one in the 9a.3 acceptance criteria: nothing in
    ``deltadewa/`` other than ``ips_config.py``'s validation and the referee
    may order a reading against ``target_min*`` / ``target_max*``.
    """

    _PATTERN = re.compile(
        r"(target_min|target_max)[a-z_]*\s*(<=|>=|<|>)"
        r"|(<=|>=|<|>)\s*[a-z_.]*(target_min|target_max)",
    )
    _ALLOWED: ClassVar[frozenset[str]] = frozenset(
        {"ips_config.py", "convexity_band.py"},
    )

    def test_no_caller_keeps_an_inline_band_comparison(self) -> None:
        root = Path(__file__).resolve().parents[2] / "deltadewa"
        offenders = [
            f"{path.relative_to(root.parent)}:{n}: {line.strip()}"
            for path in sorted(root.rglob("*.py"))
            if path.name not in self._ALLOWED
            for n, line in enumerate(path.read_text().splitlines(), 1)
            if self._PATTERN.search(line)
        ]
        assert not offenders, "\n".join(offenders)
