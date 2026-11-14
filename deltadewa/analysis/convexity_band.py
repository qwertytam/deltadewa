"""The convexity referee: is crash convexity inside the IPS band? (#434).

Before this module the answer was written out in thirteen places across
``analysis/``, ``reporting/`` and ``app/`` (the agreement audit of 2026-11-13
counted nine that set a verdict and four that re-graded for prose), and they
disagreed in four ways: what an *unmeasured* reading is, whether a figure at
some other crash depth may be graded at all, which side of the band a miss
fell on, and how the reading is rounded for display. Nothing refereed them.

:func:`grade_convexity` is now the only place that orders a convexity reading
against ``target_min_pct`` / ``target_max_pct``. Every surface calls it and
reads the grade; a ``bool`` ``meets`` is *derived* from the grade
(:attr:`ConvexityGrade.meets`), never recomputed. A test greps the package for
any inline comparison that survives (``test_convexity_band.py``).

Lives in ``analysis/`` because the graders are in ``analysis/``,
``reporting/`` and ``app/``, and ``reporting/`` must not import ``app/``.

The rules, so they are not re-litigated:

**Bounds are inclusive at both ends.** Exactly ``target_min_pct`` or exactly
``target_max_pct`` is :attr:`~ConvexityGrade.WITHIN`. This is what every
caller already did.

**The band belongs to one depth.** The handbook states it at a single crash
depth (+10%..+20% at -25% SPX) and says a figure at any other depth "cannot be
read against this range". A reading taken at another depth is therefore
:attr:`~ConvexityGrade.UNMEASURED` *against this band*, not a breach and not a
pass (#431). The caller passes the depth the reading was taken at
(``at_shock_pct``, normally ``CrashShock.crash_scenario_pct``) and the referee
refuses it; no caller has to remember to.

**Unmeasured is not breaching.** ``None`` in gives
:attr:`~ConvexityGrade.UNMEASURED` out, and :attr:`~ConvexityGrade.meets` is
``None``, never ``False`` (#433). This is ``build_vega_section``'s rule. A
*measured* ``0.0`` is a real reading and grades ``BELOW`` when the floor is
positive; the "no protected book" case is ``None`` at its source
(``crash_convexity_pct``), not ``0.0``.

**Grade on the unrounded value, and never print a figure that contradicts its
grade** (the rule, in the spirit of #393's freshness rule: the label has to
match the number it describes). The grade is always taken on the raw reading.
The display is one decimal place unless that would put the printed figure on
the other side of a band edge from its grade (9.96% shown as "10.0%" beside a
FAIL). Then it gains a second place ("9.96%"); and if two places still touch
the edge (9.999% -> "10.00%") it prints the edge with a strict sign instead
("<10.00%", ">20.00%"). :meth:`ConvexityGrading.display` is the only place
that rounds a graded convexity for a reader.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

    from deltadewa.ips_config import IpsConvexity

# The depth match is the one ``build_protection_section`` has always used:
# four decimal places, so 1e-6 float noise from a percent round trip is not a
# different depth, while -24.9999 is.
_DEPTH_PLACES: Final[int] = 4
_EDGE_MAX_PLACES: Final[int] = 4

_UNMEASURED_TEXT: Final[str] = "—"
"""What a surface prints for a reading it could not take (an em dash)."""

NOT_MEASURED: Final[str] = "not measured"
"""The short status phrase every surface uses for an UNMEASURED reading."""

COULD_NOT_BE_MEASURED: Final[str] = "could not be measured"
"""The same fact as a clause in a sentence ("X could not be measured")."""

UNMEASURED_NOT_BREACHING: Final[str] = "Unmeasured, not breaching."
"""The closing sentence of any explanation of an UNMEASURED row (#433).

``build_vega_section``'s own rule, said the same way wherever a reader could
otherwise take a missing reading for a breach.
"""


def same_crash_depth(depth_pct: float, other_pct: float) -> bool:
    """Say whether two signed crash depths are the same depth.

    The one depth-match rule in the program: equal to four decimal places, so
    float noise from a percent round trip is not a different depth. The
    referee, the protection section's row selection and the ladder composer's
    "IPS depth" row all use it, so none can pick a different row than the one
    the band was graded on.
    """
    return round(depth_pct, _DEPTH_PLACES) == round(other_pct, _DEPTH_PLACES)


def with_ips_depth(
    depths: Iterable[float],
    ips_depth_pct: float,
) -> set[float]:
    """Return *depths* with exactly one entry at the IPS crash depth.

    Any depth the :func:`same_crash_depth` rule calls the IPS depth is
    replaced by the IPS one (rounded to six places, the key the scenario
    tables use), so a table can never carry two rows that both read as "the
    IPS depth" and both get graded: the standard -25.0 and an IPS depth of
    -25.00004 would otherwise be two rows, one of which the referee would
    grade and the other would be flagged IPS beside it.
    """
    kept = {d for d in depths if not same_crash_depth(d, ips_depth_pct)}
    kept.add(round(ips_depth_pct, 6))
    return kept


def format_depth(depth_pct: float, *, signed: bool = False) -> str:
    """Format a crash depth for a label: ``-25``, ``-22.5``, ``+10``.

    Six significant figures, so a depth is never rounded to a whole number
    (``:.0f`` printed -22.5 as "-22"), and the same text in every surface's
    label so a depth cannot read differently beside the grade it belongs to.
    """
    return f"{depth_pct:+g}" if signed else f"{depth_pct:g}"


def format_band_edge(value: float, *, min_places: int = 0) -> str:
    """Format a band edge without rounding it away.

    Shows at least *min_places* decimals and as many more (up to four) as it
    takes to represent *value* exactly: a 10.0 floor is "10" (or "10.0" with
    ``min_places=1``), a 10.5 floor is "10.5", and a 10.04 floor is "10.04",
    where ``:.1f`` would have printed it as the 10.0 it is not. A band edge
    printed wrong is the same defect as a reading printed wrong.

    Args:
        value: The edge, in percent.
        min_places: The fewest decimals to show.

    Returns:
        The number as text, with no percent sign.

    """
    for places in range(min_places, _EDGE_MAX_PLACES + 1):
        text = f"{value:.{places}f}"
        if math.isclose(float(text), value, rel_tol=0.0, abs_tol=1e-12):
            return text
    return f"{value:.{_EDGE_MAX_PLACES}f}"


class ConvexityGrade(StrEnum):
    """Where a crash-convexity reading sits against the IPS band."""

    BELOW = "BELOW"
    """Under the floor: the book is under-hedged."""

    WITHIN = "WITHIN"
    """Inside the band, inclusive of both edges."""

    ABOVE = "ABOVE"
    """Over the ceiling: the book is over-hedged."""

    UNMEASURED = "UNMEASURED"
    """No reading, or a reading at a depth the band is not stated at.

    Neither a pass nor a breach (#433, #431).
    """

    @property
    def meets(self) -> bool | None:
        """Whether the reading is in band: ``None`` when unmeasured."""
        if self is ConvexityGrade.UNMEASURED:
            return None
        return self is ConvexityGrade.WITHIN


def _classify(
    value_pct: float,
    min_pct: float,
    max_pct: float,
) -> ConvexityGrade:
    """Classify a reading against the band, inclusive at both ends.

    The one *convexity* band comparison in the program. (Vega sufficiency has
    its own band and its own section, ``build_vega_section``, #409.)
    """
    if value_pct < min_pct:
        return ConvexityGrade.BELOW
    if value_pct > max_pct:
        return ConvexityGrade.ABOVE
    return ConvexityGrade.WITHIN


@dataclass(frozen=True)
class ConvexityGrading:
    """A graded convexity reading, carrying what it was graded against.

    Attributes:
        value_pct: The raw, unrounded reading, or ``None`` when no reading
            could be taken.
        min_pct: IPS band floor.
        max_pct: IPS band ceiling.
        shock_pct: The crash depth the reading was taken at.
        grade: The referee's grade. Everything else derives from it.

    """

    value_pct: float | None
    min_pct: float
    max_pct: float
    shock_pct: float
    grade: ConvexityGrade

    @property
    def meets(self) -> bool | None:
        """Derived from :attr:`grade`; ``None`` when unmeasured."""
        return self.grade.meets

    def display(self) -> str:
        """Return the reading as a reader should see it, matching its grade.

        See the module docstring for the rule: one decimal place unless that
        would contradict the grade, then two, then a strict-signed edge.

        Returns:
            For example ``"10.2%"``, ``"9.96%"``, ``"<10.00%"``, or an em
            dash when unmeasured.

        """
        value = self.value_pct
        if value is None or self.grade is ConvexityGrade.UNMEASURED:
            return _UNMEASURED_TEXT
        for places in (1, 2):
            text = f"{value:.{places}f}"
            if _classify(float(text), self.min_pct, self.max_pct) is self.grade:
                return f"{text}%"
        if self.grade is ConvexityGrade.BELOW:
            return f"<{format_band_edge(self.min_pct, min_places=2)}%"
        if self.grade is ConvexityGrade.ABOVE:
            return f">{format_band_edge(self.max_pct, min_places=2)}%"
        # WITHIN yet outside the band at two places: only a band edge with
        # more than two decimals can do that. Show the reading in full.
        return f"{value:.4f}%"

    def band_display(self, *, sep: str = "\u2013") -> str:
        """Return the band as text, without rounding an edge away.

        ``{:g}`` prints ``10.0`` as ``10`` and keeps ``10.5``: a ``:.0f``
        would have shown a 10.5% floor as "10".

        Args:
            sep: Between the edges. An en dash by default.

        Returns:
            For example ``"10-20%"`` with a hyphen separator.

        """
        return (
            f"{format_band_edge(self.min_pct)}{sep}"
            f"{format_band_edge(self.max_pct)}%"
        )


def grade_convexity(
    value_pct: float | None,
    ips_convexity: IpsConvexity,
    *,
    at_shock_pct: float,
) -> ConvexityGrading:
    """Grade a crash-convexity reading against the IPS band.

    Inclusive at both ends. Grades on the raw value (the display rule is in
    the module docstring). Returns ``UNMEASURED`` for a ``None`` reading and
    for a reading taken at any depth other than the IPS's.

    Args:
        value_pct: Crash convexity as a percent of the protected book, or
            ``None`` when it could not be taken (no protected book).
        ips_convexity: The IPS convexity policy; supplies the band and the
            one depth it is stated at.
        at_shock_pct: The signed crash depth *value_pct* was measured at,
            e.g. ``-25.0``. Required, so no caller can forget the depth.

    Returns:
        The grading, carrying the raw value, the band and the depth.

    """
    same_depth = same_crash_depth(
        at_shock_pct,
        ips_convexity.crash_scenario_pct,
    )
    if value_pct is None or not same_depth:
        grade = ConvexityGrade.UNMEASURED
    else:
        grade = _classify(
            value_pct,
            ips_convexity.target_min_pct,
            ips_convexity.target_max_pct,
        )
    return ConvexityGrading(
        value_pct=value_pct,
        min_pct=ips_convexity.target_min_pct,
        max_pct=ips_convexity.target_max_pct,
        shock_pct=at_shock_pct,
        grade=grade,
    )
