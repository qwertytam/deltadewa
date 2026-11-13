"""Every surface's convexity verdict equals the referee's (#434, #442).

``tests/test_analysis/test_convexity_band.py`` pins the referee. This pins the
*callers*: the same boundary grid (min, max, min-eps, max+eps, a mid reading,
a measured zero, ``None``) is run against every surface that says whether
crash convexity is inside the IPS band, and each answer must equal what
:func:`~deltadewa.analysis.convexity_band.grade_convexity` says for that
reading. A surface can only disagree with the referee by recomputing the
comparison, which a grep guard in the referee's test file also forbids.

The grid injects the reading by pinning ``PortfolioAnalyzer``'s crash
convexity, the way ``test_roll_and_compliance_agree.py`` does, so the axis
under test is the verdict, not whether a crafted book prices to a number. The
band-relative family at the bottom covers the surfaces that *compute* a
reading from a sized candidate (sizing, the strike-candidate grid) and so
cannot be injected: it places the band's edge exactly on the reading instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal

import pytest

from deltadewa.analysis import roll_status as roll_status_module
from deltadewa.analysis.convexity_band import (
    ConvexityGrade,
    grade_convexity,
)
from deltadewa.analysis.crash_payoff import compute_crash_convexity
from deltadewa.analysis.crash_repricing import (
    CrashShock,
    crash_convexity_pct,
)
from deltadewa.analysis.decision_matrix import HedgeAdequacy, decision_matrix
from deltadewa.analysis.market_environment import (
    DataQuality,
    HedgeCostVerdict,
    MarketEnvironment,
    RegimeLabel,
    TermShape,
)
from deltadewa.analysis.roll_planner import (
    RollAction,
    build_roll_plan,
    gamma_theta_delay,
)
from deltadewa.analysis.roll_status import RollVerdict, evaluate_roll_status
from deltadewa.analysis.sizing import GROSS_SIZING_NOTE, size_hedge
from deltadewa.analysis.strike_ladder import GridCell, build_candidate_grid
from deltadewa.app.compliance import (
    compliance_sections_at_ips_anchor,
    compliance_strip,
    scorecard,
)
from deltadewa.app.pages.design.planning.sizing import _convexity_verdict
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import (
    IpsBudget,
    IpsConfig,
    IpsConvexity,
    IpsDrawdown,
    IpsMonetization,
    IpsPricing,
    IpsProgram,
    IpsTriggers,
    IpsVega,
)
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.position import OptionPosition
from deltadewa.reporting.program_report import (
    IpsComplianceRow,
    IpsComplianceSection,
    build_ips_compliance,
    build_protection_section,
)
from deltadewa.valuation import OptionValuation
from tests.clock_helpers import days_from_today, program_date

_SPOT = 100.0
_BAND_MIN = 15.0
_BAND_MAX = 25.0
_DEPTH = -25.0

# The boundary grid. ``None`` is the unmeasured reading (#433).
_READINGS: tuple[float | None, ...] = (
    _BAND_MIN,
    _BAND_MAX,
    _BAND_MIN - 1e-9,
    _BAND_MAX + 1e-9,
    20.0,
    0.0,
    None,
)

_Kind = Literal["grade", "meets", "within_only"]


def _ips() -> IpsConfig:
    return IpsConfig(
        program=IpsProgram(name="test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=_DEPTH,
            target_min_pct=_BAND_MIN,
            target_max_pct=_BAND_MAX,
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=20.0),
        triggers=IpsTriggers(
            delta_ratio_deviation_warn_pct=5.0,
            delta_ratio_deviation_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_at_months_remaining=1.0,
            rally_monitor_pct=5.0,
            rally_review_pct=10.0,
            rally_action_pct=15.0,
            rally_urgent_pct=20.0,
            roll_review_buffer=1.5,
        ),
        monetization=IpsMonetization(schedule=()),
        vega=IpsVega(sufficiency_min_pct=1.5, sufficiency_max_pct=4.0),
    )


def _book() -> OptionPortfolio:
    """A hedged book: 100 units of underlying and one long 90 put."""
    portfolio = OptionPortfolio(
        spot_price=_SPOT,
        underlying_quantity=100.0,
        volatility=0.20,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    option = OptionValuation(
        spot_price=_SPOT,
        strike_price=90.0,
        maturity_date=days_from_today(200),
        volatility=0.20,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        option_type=OptionType.PUT,
        exercise_style=ExerciseStyle.EUROPEAN,
    )
    portfolio.positions.append(
        OptionPosition(
            option=option,
            quantity=5,
            exercise_style=ExerciseStyle.EUROPEAN,
            entry_spot=_SPOT,
            entry_date=program_date(),
        ),
    )
    return portfolio


def _pin_reading(
    monkeypatch: pytest.MonkeyPatch,
    value: float | None,
) -> None:
    """Pin the book's crash convexity so the grid controls that axis."""

    def _fake(_self: object, _shock: CrashShock) -> float | None:
        return value

    monkeypatch.setattr(
        roll_status_module.PortfolioAnalyzer,
        "calculate_crash_convexity_pct",
        _fake,
    )


def _env() -> MarketEnvironment:
    return MarketEnvironment(
        vix=18.0,
        regime_band_position_pct=30.0,
        regime_label=RegimeLabel.NORMAL,
        skew_index=130.0,
        skew_percentile=0.35,
        term_structure={},
        term_shape=TermShape.FLAT,
        forward_vol_front_3m=19.0,
        hedge_cost_verdict=HedgeCostVerdict.FAIR,
        data_quality=DataQuality.LIVE,
        as_of=datetime(2026, 7, 24, tzinfo=UTC),
    )


# ── Each surface, driven by a reading, answering with its own verdict ────


def _roll_status(
    _mp: pytest.MonkeyPatch,
    value: float | None,
) -> ConvexityGrade:
    """The roll-status table's convexity trigger and its target flag."""
    (record,) = evaluate_roll_status(_book(), _ips())
    if record.convexity_target_met is None:
        return ConvexityGrade.UNMEASURED
    return {
        RollVerdict.ROLL: ConvexityGrade.BELOW,
        RollVerdict.MONITOR: ConvexityGrade.ABOVE,
        RollVerdict.HOLD: ConvexityGrade.WITHIN,
    }[record.convexity_trigger.verdict]


def _crash_row_meets(
    _mp: pytest.MonkeyPatch,
    value: float | None,
) -> bool | None:
    """The IPS-depth row of the crash-scenario ladder."""
    ips = _ips()
    result = compute_crash_convexity(
        _book(),
        shock=CrashShock.from_ips(ips.convexity),
        ips_convexity=ips.convexity,
    )
    (row,) = (
        r
        for r in result.scenario_rows
        if round(r.shock_pct, 4) == round(_DEPTH, 4)
    )
    return row.meets_target


def _protection_meets(
    _mp: pytest.MonkeyPatch,
    value: float | None,
) -> bool | None:
    ips = _ips()
    return build_protection_section(
        compute_crash_convexity(
            _book(),
            shock=CrashShock.from_ips(ips.convexity),
            ips_convexity=ips.convexity,
        ),
    ).meets_target


def _convexity_row_passes(
    rows: tuple[Any, ...],
) -> bool | None:
    (row,) = (r for r in rows if r.metric.startswith("Crash convexity"))
    return row.passes


def _compliance_row(
    _mp: pytest.MonkeyPatch,
    value: float | None,
) -> bool | None:
    """The compliance table every strip and the digest render."""
    ips = _ips()
    sections = compliance_sections_at_ips_anchor(_book(), ips)
    return _convexity_row_passes(build_ips_compliance(*sections).rows)


def _scorecard_row(
    _mp: pytest.MonkeyPatch,
    value: float | None,
) -> bool | None:
    """The composer's baseline and proposal rows come from ``scorecard``."""
    return _convexity_row_passes(scorecard(_book(), _ips()).compliance.rows)


def _decision(
    _mp: pytest.MonkeyPatch,
    value: float | None,
) -> ConvexityGrade:
    """The decision matrix's hedge adequacy."""
    result = decision_matrix(
        _env(),
        convexity_now_pct=value,  # type: ignore[arg-type]
        ips_convexity=_ips().convexity,
    )
    if result.hedge_adequacy is None:
        return ConvexityGrade.UNMEASURED
    return {
        HedgeAdequacy.UNDER: ConvexityGrade.BELOW,
        HedgeAdequacy.ADEQUATE: ConvexityGrade.WITHIN,
        HedgeAdequacy.OVER: ConvexityGrade.ABOVE,
    }[result.hedge_adequacy]


def _delay(
    _mp: pytest.MonkeyPatch,
    value: float | None,
) -> bool:
    """The gamma/theta deferral, with its other two conditions held true."""
    ips = _ips()
    return gamma_theta_delay(
        months_to_maturity=ips.triggers.roll_at_months_remaining + 3.0,
        convexity=grade_convexity(value, ips.convexity, at_shock_pct=_DEPTH),
        drift_pct=-5.0,
        ips_triggers=ips.triggers,
    )


@dataclass(frozen=True)
class _Surface:
    name: str
    drive: Callable[[pytest.MonkeyPatch, float | None], Any]
    kind: _Kind
    pinned: bool = True


_SURFACES = (
    _Surface("roll_status", _roll_status, "grade"),
    _Surface("crash_payoff_row", _crash_row_meets, "meets"),
    _Surface("protection_section", _protection_meets, "meets"),
    _Surface("compliance_row", _compliance_row, "meets"),
    _Surface("scorecard_row", _scorecard_row, "meets"),
    _Surface("decision_matrix", _decision, "grade", pinned=False),
    _Surface("gamma_theta_delay", _delay, "within_only", pinned=False),
)


def _cases() -> list[Any]:
    return [
        pytest.param(surface, reading, id=f"{surface.name}-{reading}")
        for surface in _SURFACES
        for reading in _READINGS
    ]


class TestEverySurfaceAgreesWithTheReferee:
    """One reading in, the referee's grade out of every surface."""

    @pytest.mark.parametrize(("surface", "reading"), _cases())
    def test_surface_equals_the_referee(
        self,
        monkeypatch: pytest.MonkeyPatch,
        surface: _Surface,
        reading: float | None,
    ) -> None:
        if surface.pinned:
            _pin_reading(monkeypatch, reading)
        referee = grade_convexity(
            reading,
            _ips().convexity,
            at_shock_pct=_DEPTH,
        )

        got = surface.drive(monkeypatch, reading)

        if surface.kind == "grade":
            assert got is referee.grade
        elif surface.kind == "meets":
            assert got is referee.meets
        else:
            assert got is (referee.grade is ConvexityGrade.WITHIN)


class TestComputedSurfacesAgreeWithTheReferee:
    """Sizing, the candidate grid and the panel's side word (band-relative).

    These surfaces *compute* their reading from a sized candidate, so it
    cannot be injected. The band's edge is placed exactly on the computed
    reading instead (the band is policy and does not move the sizing), which
    exercises the inclusive edges for real.
    """

    @staticmethod
    def _with_band(
        band_min: float,
        band_max: float,
    ) -> IpsConfig:
        ips = _ips()
        return replace(
            ips,
            convexity=replace(
                ips.convexity,
                target_min_pct=band_min,
                target_max_pct=band_max,
            ),
        )

    @staticmethod
    def _reading() -> float:
        result = size_hedge(
            _book(),
            _ips(),
            candidate_pct_otm=10.0,
            candidate_maturity_years=1.0,
        )
        return result.achieved_convexity_pct

    @pytest.mark.parametrize(
        ("lo", "hi", "side"),
        [
            pytest.param(0.0, 0.0, "at_min", id="reading-on-the-floor"),
            pytest.param(0.0, 0.0, "at_max", id="reading-on-the-ceiling"),
            pytest.param(1e-6, 1e6, "below", id="reading-under-the-floor"),
            pytest.param(-1e6, -1e-6, "above", id="reading-over-the-ceiling"),
        ],
    )
    def test_sizing_grid_and_panel_equal_the_referee(
        self,
        lo: float,
        hi: float,
        side: str,
    ) -> None:
        reading = self._reading()
        if side == "at_min":
            band = (reading, reading + 10.0)
        elif side == "at_max":
            band = (reading - 10.0, reading)
        else:
            band = (reading + lo, reading + hi)
        ips = self._with_band(*band)
        referee = grade_convexity(reading, ips.convexity, at_shock_pct=_DEPTH)

        sized = size_hedge(
            _book(),
            ips,
            candidate_pct_otm=10.0,
            candidate_maturity_years=1.0,
        )
        cell = build_candidate_grid(
            _book(),
            ips,
            target_deltas=[0.10],
            maturities_years=[1.0],
        ).cells[0]

        assert sized.achieved_convexity_pct == pytest.approx(reading)
        assert sized.meets_convexity_target is referee.meets
        assert sized.achieved_convexity.grade is referee.grade
        assert cell.achieved_convexity.grade is cell_referee(cell, ips)
        assert (
            _convexity_verdict(sized)
            == {
                ConvexityGrade.WITHIN: "within",
                ConvexityGrade.BELOW: "below",
                ConvexityGrade.ABOVE: "above",
            }[referee.grade]
        )


def cell_referee(cell: GridCell, ips: IpsConfig) -> ConvexityGrade:
    """The referee's grade for a grid cell's own computed reading."""
    return grade_convexity(
        cell.achieved_convexity_pct,
        ips.convexity,
        at_shock_pct=_DEPTH,
    ).grade


def _zero_underlying_book() -> OptionPortfolio:
    """A long put with no underlying: no protected notional (#433)."""
    book = _book()
    book.underlying_quantity = 0.0
    return book


class TestAZeroBookIsUnmeasuredEverywhere:
    """#433: an undefined ratio is unmeasured, never a measured 0.0.

    Before the referee a book with no underlying read ``0.0%`` convexity,
    which every grader then graded as a real below-band miss: roll status
    marked every leg ROLL, the decision matrix said UNDER, and the strip
    said FAIL. Nothing is patched here; this is the real zero book through
    each surface's own builder.
    """

    def test_the_root_returns_none_not_zero(self) -> None:
        shock = CrashShock.from_ips(_ips().convexity)

        assert crash_convexity_pct(_zero_underlying_book(), shock=shock) is None

    def test_roll_status_does_not_roll_every_leg_for_a_missing_book(
        self,
    ) -> None:
        (record,) = evaluate_roll_status(_zero_underlying_book(), _ips())

        assert record.crash_convexity_pct is None
        assert record.convexity.grade is ConvexityGrade.UNMEASURED
        assert record.convexity_target_met is None
        assert record.convexity_trigger.verdict is RollVerdict.HOLD
        assert "not measured" in record.convexity_trigger.reason
        # 200 days out with no rally: nothing at all fires.
        assert record.verdict is RollVerdict.HOLD

    def test_the_roll_plan_carries_the_unmeasured_standing(self) -> None:
        (plan,) = build_roll_plan(_zero_underlying_book(), _ips())

        assert plan.convexity_now_pct is None
        assert plan.meets_convexity_target is None
        assert plan.action is RollAction.HOLD

    def test_the_crash_row_and_protection_section_are_unmeasured(self) -> None:
        ips = _ips()
        result = compute_crash_convexity(
            _zero_underlying_book(),
            shock=CrashShock.from_ips(ips.convexity),
            ips_convexity=ips.convexity,
        )
        protection = build_protection_section(result)

        assert protection.convexity is not None
        assert protection.convexity.grade is ConvexityGrade.UNMEASURED
        assert protection.convexity_pct is None
        assert protection.meets_target is None

    def test_the_compliance_row_is_unmeasured_and_the_section_incomplete(
        self,
    ) -> None:
        sections = compliance_sections_at_ips_anchor(
            _zero_underlying_book(),
            _ips(),
        )
        compliance = build_ips_compliance(*sections)
        (row,) = (
            r for r in compliance.rows if r.metric.startswith("Crash convexity")
        )

        assert row.passes is None
        assert row.actual == "—"
        assert row.action is not None
        assert "Unmeasured, not breaching" in row.action
        assert row.metric in compliance.unmeasured_metrics
        assert row.metric not in compliance.failing_metrics
        assert compliance.all_pass is False

    def test_a_candidate_on_a_zero_book_raises_rather_than_reading_zero(
        self,
    ) -> None:
        with pytest.raises(ValueError, match="underlying position"):
            size_hedge(
                _zero_underlying_book(),
                _ips(),
                candidate_pct_otm=10.0,
                candidate_maturity_years=1.0,
            )

    def test_the_strip_says_incomplete_when_nothing_else_is_breached(
        self,
    ) -> None:
        rows = (
            IpsComplianceRow(
                metric="Annual carry cost",
                target="\u2264 2.00%",
                actual="1.00%",
                passes=True,
            ),
            IpsComplianceRow(
                metric="Crash convexity (-25% shock)",
                target="15.0%\u201325.0% of book",
                actual="\u2014",
                passes=None,
            ),
        )
        compliance = IpsComplianceSection(rows=rows, all_pass=False)

        verdict = compliance_strip(compliance, DataQuality.LIVE).children[0]

        assert verdict.children == (
            "IPS compliance: INCOMPLETE \u2014 nothing is out of policy, "
            "but Crash convexity (-25% shock) could not be measured."
        )
        assert "compliance-verdict--incomplete" in verdict.className

    def test_a_real_breach_is_still_a_fail_and_names_the_gap(self) -> None:
        """The zero book's vega is out of band: FAIL, and says what is open."""
        compliance = build_ips_compliance(
            *compliance_sections_at_ips_anchor(
                _zero_underlying_book(),
                _ips(),
            ),
        )

        verdict = compliance_strip(compliance, DataQuality.LIVE).children[0]

        assert verdict.children.startswith("IPS compliance: FAIL")
        assert verdict.children.endswith(
            "Not measured: Crash convexity (-25% shock).",
        )
        assert "compliance-verdict--fail" in verdict.className


def _all_text(component: Any) -> str:
    """Concatenate every string under a Dash component tree."""
    children = getattr(component, "children", component)
    if isinstance(children, str):
        return children
    if isinstance(children, list | tuple):
        return " ".join(_all_text(c) for c in children)
    return "" if children is None else _all_text(children)


class TestGrossSizingIsDisclosedBesideEveryCoversTheOffset:
    """#436 (decided GROSS): the caveat sits where the claim is made."""

    def test_the_sizing_panel_carries_the_note(self) -> None:
        from deltadewa.app.pages.design.planning import sizing as sizing_panel

        result = size_hedge(
            _book(),
            _ips(),
            candidate_pct_otm=10.0,
            candidate_maturity_years=1.0,
        )
        panel = sizing_panel._sizing_panel_view(result, _ips())

        assert GROSS_SIZING_NOTE in _all_text(panel)

    def test_the_candidate_table_note_carries_it(self) -> None:
        from deltadewa.app.pages.design.planning import ladder as ladder_panel

        assert GROSS_SIZING_NOTE in ladder_panel._ALONE_NOTE

    def test_a_zero_offset_candidate_is_not_called_below_target(self) -> None:
        """No contracts needed is not an under-hedge (false-green audit)."""
        from deltadewa.app.pages.design.planning import sizing as sizing_panel

        generous = replace(
            _ips(),
            drawdown=replace(_ips().drawdown, max_tolerance_pct=90.0),
        )
        result = size_hedge(
            _book(),
            generous,
            candidate_pct_otm=10.0,
            candidate_maturity_years=1.0,
        )
        text = _all_text(sizing_panel._sizing_panel_view(result, generous))

        assert result.contracts_needed == 0
        assert "No contracts are needed" in text
        assert "below target" not in text
        assert GROSS_SIZING_NOTE not in text
