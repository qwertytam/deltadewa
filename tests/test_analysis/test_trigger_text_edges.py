"""Trigger text prints the edge the trigger compares (#470).

The roll triggers printed IPS values at zero decimals and carried the window
as an ``int``, while the triggers themselves compare the float. With a
fractional edge the sentence and the decision disagree: a ``rally_review_pct``
of 7.5 read "REVIEW band (8-...)" and graded REVIEW at 7.6%, under a label
that started at 8. The shipped IPS is all whole numbers, so nothing was wrong
on the shipped values, and these tests use values that make the difference show.

Every figure below is invented to exercise the rule; none is a recommended
setting.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from deltadewa import constants as const
from deltadewa.analysis.hedge_triggers import (
    HedgeTriggerThresholds,
    TriggerStatus,
    rally_reason,
)
from deltadewa.analysis.roll_planner import (
    RollAction,
    build_roll_plan,
    leg_action_label,
)
from deltadewa.analysis.roll_status import (
    RollStatusRecord,
    RollVerdict,
    evaluate_roll_status,
    roll_window_opens,
)
from deltadewa.app.pages.design.planning.roll_status import _dte_text
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.ips_config import IpsConfig, load_ips_config
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.position import OptionPosition
from deltadewa.valuation import OptionValuation
from tests.clock_helpers import days_from_today

from .test_roll_by import _book, _convexity, _ips, _put

_REPO = Path(__file__).parent.parent.parent
_SHIPPED_IPS = _REPO / "config" / "ips.example.yaml"
_IN_BAND = 15.0
# A set of band edges no whole-number format can print: every one is a .5.
_HALF_POINT_BANDS = {
    "rally_monitor_pct": 2.5,
    "rally_review_pct": 7.5,
    "rally_action_pct": 12.5,
    "rally_urgent_pct": 17.5,
}


def _with_triggers(**changes: float) -> IpsConfig:
    """The test IPS with some trigger values replaced."""
    ips = _ips()
    return dataclasses.replace(
        ips,
        triggers=dataclasses.replace(ips.triggers, **changes),
    )


def _status(
    monkeypatch: pytest.MonkeyPatch,
    ips: IpsConfig,
    *,
    days: int,
    rally_pct: float | None = None,
) -> RollStatusRecord:
    """One long put's roll status under *ips*, convexity pinned in band."""
    _convexity(monkeypatch, _IN_BAND)
    spot = 6_300.0
    entry_spot = spot if rally_pct is None else spot / (1 + rally_pct / 100)
    (record,) = evaluate_roll_status(
        _book(_put(days=days, spot=spot, entry_spot=entry_spot)),
        ips,
    )
    return record


class TestAFractionalWindowIsPrintedAsComparedAndDated:
    """4.55 months is a 136.5-day window; every surface says 136.5."""

    _MONTHS = 4.55

    def _ips(self) -> IpsConfig:
        return _with_triggers(roll_at_months_remaining=self._MONTHS)

    def test_the_record_carries_the_float_the_trigger_compares(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        record = _status(monkeypatch, self._ips(), days=137)

        compared = self._MONTHS * const.CALENDAR_DAYS_PER_MONTH
        assert isinstance(record.roll_window_days, float)
        assert record.roll_window_days == compared
        assert compared == pytest.approx(136.5)

    def test_the_time_sentence_the_table_cell_and_the_date_agree(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        review = _status(monkeypatch, self._ips(), days=137)

        assert review.time_trigger.verdict is RollVerdict.REVIEW
        assert "opens at 136.5d" in review.time_trigger.reason
        assert _dte_text(review) == "137d / 136.5d"

    def test_the_date_is_the_first_day_the_trigger_reads_roll(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ROLL at 136 days, REVIEW at 137: the date is 136 days out.

        A day count is whole, so a 136.5-day window fires at 136 and not at
        137. The date is the floor of the window, which is the trigger's own
        edge. Neither a 137-day date (a day early) nor a rounded 136.5 would
        be.
        """
        ips = self._ips()
        at_edge = _status(monkeypatch, ips, days=136)
        past_edge = _status(monkeypatch, ips, days=137)
        maturity = days_from_today(137).date()

        assert at_edge.time_trigger.verdict is RollVerdict.ROLL
        assert past_edge.time_trigger.verdict is RollVerdict.REVIEW
        assert (maturity - roll_window_opens(past_edge)).days == 136

    def test_a_whole_window_still_prints_without_a_decimal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``:g`` keeps 180, not 180.0: the shipped values read as before."""
        record = _status(monkeypatch, _ips(), days=219)

        assert _dte_text(record) == "219d / 180d"
        assert "opens at 180d" in record.time_trigger.reason


class TestTheRallyBandsPrintTheirEdges:
    """A 7.5% band reads 7.5 on the sentence, not 8."""

    @pytest.mark.parametrize(
        ("rally_pct", "verdict", "phrase"),
        [
            (17.6, RollVerdict.ROLL, "URGENT band (>17.5%)"),
            (12.6, RollVerdict.ROLL, "ACTION band (12.5-17.5%)"),
            (7.6, RollVerdict.REVIEW, "REVIEW band (7.5-12.5%)"),
            (2.6, RollVerdict.MONITOR, "MONITOR band (2.5-7.5%)"),
            (2.4, RollVerdict.HOLD, "below the 2.5% monitor band"),
        ],
        ids=["urgent", "action", "review", "monitor", "below"],
    )
    def test_each_band_prints_the_edge_it_compared(
        self,
        monkeypatch: pytest.MonkeyPatch,
        rally_pct: float,
        verdict: RollVerdict,
        phrase: str,
    ) -> None:
        record = _status(
            monkeypatch,
            _with_triggers(**_HALF_POINT_BANDS),
            days=400,
            rally_pct=rally_pct,
        )

        assert record.rally_trigger.verdict is verdict
        assert phrase in record.rally_trigger.reason

    def test_a_reading_on_the_review_edge_is_review_under_a_label_that_says_so(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The #470 case: 7.6% is REVIEW, and the label starts at 7.5, not 8."""
        record = _status(
            monkeypatch,
            _with_triggers(**_HALF_POINT_BANDS),
            days=400,
            rally_pct=7.6,
        )

        assert record.rally_trigger.verdict is RollVerdict.REVIEW
        assert "REVIEW band (8-" not in record.rally_trigger.reason

    def test_whole_edges_still_print_without_a_decimal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        record = _status(monkeypatch, _ips(), days=400, rally_pct=12.0)

        assert "REVIEW band (10-15%)" in record.rally_trigger.reason


class TestTheBookLevelRallySentenceDoesToo:
    """``hedge_triggers.rally_reason`` bands on the outer two edges."""

    _T = HedgeTriggerThresholds(rally_monitor_pct=2.5, rally_action_pct=7.5)

    def test_the_action_band(self) -> None:
        reason = rally_reason((7.6, "PUT 5,600"), self._T)

        assert reason.status is TriggerStatus.ACTION
        assert "at or past the 7.5% action band" in reason.reason

    def test_the_monitor_band_names_both_edges(self) -> None:
        reason = rally_reason((5.0, "PUT 5,600"), self._T)

        assert reason.status is TriggerStatus.MONITOR
        assert "past the 2.5% monitor band" in reason.reason
        assert "below the 7.5% action band" in reason.reason

    def test_below_the_monitor_band(self) -> None:
        reason = rally_reason((1.0, "PUT 5,600"), self._T)

        assert reason.status is TriggerStatus.OK
        assert "below the 2.5% monitor band" in reason.reason


class TestTheDelayWindowIsPrintedAsComparedAndDated:
    """A 4.5-month window reads "4.5 mo", not "5 mo"."""

    def test_the_rationale_names_the_window_it_deferred_against(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ips = _with_triggers(roll_at_months_remaining=4.5)
        _convexity(monkeypatch, _IN_BAND)
        # In the 135-202.5d buffer, nearer the money since entry, in band.
        deferred = _put(
            days=190,
            spot=5_900.0,
            entry_spot=7_000.0,
            strike=5_000.0,
        )
        (record,) = build_roll_plan(_book(deferred), ips)

        assert record.action is RollAction.DELAY
        assert "outside the 4.5 mo roll window" in record.rationale
        assert "outside the 5 mo roll window" not in record.rationale

    def test_a_whole_window_reads_as_before(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _convexity(monkeypatch, _IN_BAND)
        deferred = _put(
            days=219,
            spot=5_900.0,
            entry_spot=7_000.0,
            strike=5_000.0,
        )
        (record,) = build_roll_plan(_book(deferred), _ips())

        assert record.action is RollAction.DELAY
        assert "outside the 6 mo roll window" in record.rationale


class TestThePutFromIssue461KeepsItsDate:
    """#461's PUT 5,600 is ROLL BY 2026-12-22 under the shipped IPS, as it was.

    The window is 6.0 months, so 180 days, and the date does not move when
    the window is carried as a float. Pinned as a calendar fact: a leg
    maturing 2027-06-20 opens its window 180 days earlier.
    """

    def test_the_date_under_the_shipped_ips(self) -> None:
        zone = ZoneInfo("America/New_York")
        as_of = datetime(2026, 11, 13, tzinfo=zone)
        maturity = datetime(2027, 6, 20, tzinfo=zone)
        ips = load_ips_config(_SHIPPED_IPS)
        option = OptionValuation(
            spot_price=6_300.0,
            strike_price=5_600.0,
            maturity_date=maturity,
            volatility=0.2,
            risk_free_rate=0.04,
            dividend_yield=0.0,
            option_type=OptionType.PUT,
            exercise_style=ExerciseStyle.EUROPEAN,
            valuation_date=as_of,
        )
        position = OptionPosition(
            option=option,
            quantity=5,
            exercise_style=ExerciseStyle.EUROPEAN,
            entry_spot=6_300.0,
            entry_date=datetime(2026, 10, 14, tzinfo=UTC),
        )
        book = OptionPortfolio(spot_price=6_300.0, valuation_date=as_of)
        book.positions.append(position)

        (record,) = evaluate_roll_status(book, ips)

        assert record.days_to_maturity == 219
        assert record.roll_window_days == pytest.approx(180.0)
        assert roll_window_opens(record) == date(2026, 12, 22)
        assert (
            leg_action_label(record, ips_triggers=ips.triggers)
            == "ROLL BY 2026-12-22"
        )


# Names whose value is a policy edge a trigger compares. A fixed-precision
# format on one of these is the #470 defect; ``:g`` is the rule.
_EDGE_NAME = re.compile(
    r"(?:^|\.)(?:rally_\w+_pct|roll_at_months_remaining"
    r"|roll_review_buffer|roll_window_days)$",
)
_FIXED_PRECISION = re.compile(r"\.\d+f")


def _fixed_precision_edges(tree: ast.AST) -> list[int]:
    """Line numbers where an f-string prints a policy edge at fixed decimals."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FormattedValue) or node.format_spec is None:
            continue
        spec = ast.unparse(node.format_spec)
        if _EDGE_NAME.search(ast.unparse(node.value)) and (
            _FIXED_PRECISION.search(spec)
        ):
            lines.append(node.lineno)
    return lines


class TestNoSentenceRoundsAnEdgeAgain:
    """A guard, so the next trigger sentence cannot reintroduce ``:.0f``."""

    def test_the_package_has_none(self) -> None:
        found: list[str] = []
        for path in sorted((_REPO / "deltadewa").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            found += [
                f"{path.relative_to(_REPO)}:{line}"
                for line in _fixed_precision_edges(tree)
            ]

        assert found == []

    @pytest.mark.parametrize(
        "source",
        [
            'f"{triggers.rally_review_pct:.0f}%"',
            'f"{t.rally_action_pct:.1f}%"',
            'f"{ips_triggers.roll_at_months_remaining:.0f} mo"',
            'f"{record.roll_window_days:.0f}d"',
        ],
    )
    def test_the_guard_sees_a_fixed_precision_edge(self, source: str) -> None:
        assert _fixed_precision_edges(ast.parse(source)) == [1]

    @pytest.mark.parametrize(
        "source",
        [
            'f"{triggers.rally_review_pct:g}%"',
            'f"{rally_pct:+.1f}% rally since entry"',
            'f"{record.days_to_maturity:.0f}d"',
            'f"{ips_triggers.roll_at_months_remaining}"',
        ],
    )
    def test_the_guard_leaves_readings_and_the_g_rule_alone(
        self,
        source: str,
    ) -> None:
        assert _fixed_precision_edges(ast.parse(source)) == []
