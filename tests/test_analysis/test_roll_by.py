"""The roll plan's dated action, and which trigger gets named (#461).

PUT 5,600 sat at 219 days: outside the 180d roll window, inside the 270d
review buffer, so Rule 1's time trigger read REVIEW. The rally trigger read
REVIEW as well, with convexity in band. The plan showed ROLL NOW beside the
rally trigger's "calls for no roll" sentence, because the two REVIEWs
compared equal and the rationale quoted whichever it tested first.

These pin the fix at its three layers: the action (a leg in the buffer is
``ROLL_BY`` the date the window opens, not ``ROLL_NOW``), the attribution (the
rationale names the trigger that produced the action, with one precedence for
ties), and the things that must not move (CHECKED, ROLL_NOW inside the
window, DELAY, and the verdict scale the digest reduces).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, time, timedelta

import pytest

from deltadewa.analysis import roll_status
from deltadewa.analysis.roll_planner import (
    _ACTION_URGENCY,
    RollAction,
    action_label,
    build_roll_plan,
    leg_action,
    leg_reason,
)
from deltadewa.analysis.roll_status import (
    TRIGGER_PRECEDENCE,
    RollVerdict,
    _time_trigger_verdict,
    driving_trigger,
    evaluate_roll_status,
    roll_window_opens,
    trigger_reading,
    verdict_reason,
)
from deltadewa.clock import days_between
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
)
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.position import OptionPosition
from deltadewa.valuation import OptionValuation
from tests.clock_helpers import days_from_today

_WINDOW_DAYS = 180
_BUFFER = 1.5
_ENTRY = 6_300.0
# +11.1% from entry: Rule 2's REVIEW band (10-15%).
_RALLIED = 7_000.0
_BAND = (10.0, 20.0)
_IN_BAND = 15.0
_BELOW_BAND = 5.0


def _ips() -> IpsConfig:
    return IpsConfig(
        program=IpsProgram(name="test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=_BAND[0],
            target_max_pct=_BAND[1],
        ),
        drawdown=IpsDrawdown(max_tolerance_pct=20.0),
        triggers=IpsTriggers(
            delta_ratio_deviation_warn_pct=5.0,
            delta_ratio_deviation_action_pct=10.0,
            theta_cost_acceptable_pct=2.0,
            roll_at_months_remaining=6.0,
            rally_monitor_pct=5.0,
            rally_review_pct=10.0,
            rally_action_pct=15.0,
            rally_urgent_pct=20.0,
            roll_review_buffer=_BUFFER,
        ),
        monetization=IpsMonetization(schedule=()),
    )


def _put(
    *,
    days: int,
    spot: float = _RALLIED,
    entry_spot: float | None = _ENTRY,
    strike: float = 5_600.0,
    quantity: int = 5,
    option_type: OptionType = OptionType.PUT,
) -> OptionPosition:
    option = OptionValuation(
        spot_price=spot,
        strike_price=strike,
        maturity_date=days_from_today(days),
        volatility=0.2,
        risk_free_rate=0.04,
        dividend_yield=0.0,
        option_type=option_type,
        exercise_style=ExerciseStyle.EUROPEAN,
    )
    return OptionPosition(
        option=option,
        quantity=quantity,
        exercise_style=ExerciseStyle.EUROPEAN,
        entry_spot=entry_spot,
        entry_date=datetime.now(tz=UTC) - timedelta(days=30),
    )


def _book(*positions: OptionPosition) -> OptionPortfolio:
    book = OptionPortfolio(spot_price=positions[0].option.spot_price)
    book.positions.extend(positions)
    return book


def _convexity(monkeypatch: pytest.MonkeyPatch, value: float) -> None:
    """Pin the book's crash convexity, as the roll tests beside this do."""
    monkeypatch.setattr(
        roll_status.PortfolioAnalyzer,
        "calculate_crash_convexity_pct",
        lambda _self, _shock: value,
    )


def _plan(
    monkeypatch: pytest.MonkeyPatch,
    *positions: OptionPosition,
    convexity: float = _IN_BAND,
):
    _convexity(monkeypatch, convexity)
    return build_roll_plan(_book(*positions), _ips())


def _put_5600(monkeypatch: pytest.MonkeyPatch):
    """The review's leg: 219d, time REVIEW, rally REVIEW, convexity in band."""
    (record,) = _plan(monkeypatch, _put(days=219))
    return record


class TestABufferZoneReviewIsADatedAction:
    """The review's PUT 5,600: a roll that is due, not overdue."""

    def test_the_leg_reads_the_way_the_review_found_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (status,) = _plan_status(monkeypatch, _put(days=219))

        assert status.verdict is RollVerdict.REVIEW
        assert status.time_trigger.verdict is RollVerdict.REVIEW
        assert status.rally_trigger.verdict is RollVerdict.REVIEW
        assert status.convexity_trigger.verdict is RollVerdict.HOLD

    def test_it_is_roll_by_the_date_the_window_opens(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        record = _put_5600(monkeypatch)

        opens = days_from_today(219).date() - timedelta(days=_WINDOW_DAYS)
        assert record.action is RollAction.ROLL_BY
        assert record.window_opens == opens
        assert record.action_label == f"ROLL BY {opens.isoformat()}"
        assert record.driver == "time"

    def test_the_rationale_names_the_time_trigger_and_its_rule(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        record = _put_5600(monkeypatch)

        assert record.rationale.startswith("Time trigger:")
        assert (
            "approaching the roll window (opens at 180d; review starts at 270d)"
        ) in record.rationale
        assert record.window_opens is not None
        assert record.window_opens.isoformat() in record.rationale

    def test_no_roll_never_appears_beside_the_action(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The contradiction #461 found: a ROLL NOW quoting "no roll"."""
        record = _put_5600(monkeypatch)

        assert "no roll" not in record.rationale.lower()
        assert "calls for no" not in record.rationale.lower()

    def test_the_rally_trigger_is_acknowledged_not_quoted(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        record = _put_5600(monkeypatch)

        assert "The rally trigger is also at REVIEW" in record.rationale
        assert "not a reason to roll sooner" in record.rationale
        assert "Rally trigger:" not in record.rationale

    def test_the_date_is_when_the_time_trigger_turns_roll(self) -> None:
        """``window_opens`` is a date the trigger really changes on."""
        position = _put(days=219)
        (status,) = evaluate_roll_status(_book(position), _ips())
        opens = roll_window_opens(status)
        maturity = position.option.maturity_date

        def day(d):
            return datetime.combine(d, time.min, tzinfo=UTC)

        on_the_day = days_between(day(opens), maturity)
        the_day_before = days_between(day(opens - timedelta(days=1)), maturity)
        assert on_the_day == status.roll_window_days
        assert (
            _time_trigger_verdict(on_the_day, _WINDOW_DAYS, _BUFFER).verdict
            is RollVerdict.ROLL
        )
        assert (
            _time_trigger_verdict(the_day_before, _WINDOW_DAYS, _BUFFER).verdict
            is RollVerdict.REVIEW
        )

    def test_a_fractional_window_opens_on_the_last_whole_day_it_fires(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """6.05 months is a 181.5d window: ROLL at 181 days, REVIEW at 182.

        The record keeps the window as whole days while the trigger compares
        the float. Day counts are integers, so ``days <= 181.5`` is
        ``days <= 181`` and the two agree; this pins the date to that edge.
        """
        ips = _ips()
        ips = dataclasses.replace(
            ips,
            triggers=dataclasses.replace(
                ips.triggers,
                roll_at_months_remaining=6.05,
            ),
        )
        _convexity(monkeypatch, _IN_BAND)
        (at_edge,) = evaluate_roll_status(_book(_put(days=181)), ips)
        (past_edge,) = evaluate_roll_status(_book(_put(days=182)), ips)
        maturity = days_from_today(182)

        assert at_edge.time_trigger.verdict is RollVerdict.ROLL
        assert past_edge.time_trigger.verdict is RollVerdict.REVIEW
        assert "opens at 181.5d" in past_edge.time_trigger.reason
        opens = roll_window_opens(past_edge)
        assert opens == maturity.date() - timedelta(days=181)
        assert (
            days_between(
                datetime.combine(opens, time.min, tzinfo=UTC), maturity
            )
            == 181
        )

    def test_the_verdict_is_still_review(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The action is new; the verdict scale the digest reduces is not."""
        assert _put_5600(monkeypatch).verdict is RollVerdict.REVIEW


def _plan_status(monkeypatch: pytest.MonkeyPatch, *positions: OptionPosition):
    _convexity(monkeypatch, _IN_BAND)
    return evaluate_roll_status(_book(*positions), _ips())


class TestWhatDoesNotMove:
    """The cases #461's fix must leave exactly as they were."""

    def test_a_rally_review_alone_with_convexity_in_band_is_still_checked(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 400d is outside the 270d buffer: only Rule 2 has fired.
        (record,) = _plan(monkeypatch, _put(days=400))

        assert record.action is RollAction.CHECKED
        assert record.window_opens is None
        assert record.driver == "rally"
        assert record.rationale.startswith("Rally trigger:")

    def test_inside_the_window_is_still_roll_now(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (record,) = _plan(monkeypatch, _put(days=150))

        assert record.action is RollAction.ROLL_NOW
        assert record.driver == "time"
        assert record.window_opens is None
        assert "inside the 180d roll window" in record.rationale

    def test_the_first_day_of_the_window_is_roll_now(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (record,) = _plan(monkeypatch, _put(days=_WINDOW_DAYS))
        (day_before,) = _plan(monkeypatch, _put(days=_WINDOW_DAYS + 1))

        assert record.action is RollAction.ROLL_NOW
        assert day_before.action is RollAction.ROLL_BY

    def test_a_deferral_that_applies_is_still_delay_not_roll_by(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Nearer the money, outside the window, convexity in band: defer."""
        declined = _put(
            days=219,
            spot=5_900.0,
            entry_spot=7_000.0,
            strike=5_000.0,
        )
        (record,) = _plan(monkeypatch, declined)

        assert record.action is RollAction.DELAY
        assert record.window_opens is None
        assert record.driver == "time"
        assert "Roll warranted (REVIEW) but deferring" in record.rationale

    def test_convexity_below_the_band_is_roll_now_not_roll_by(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (record,) = _plan(
            monkeypatch,
            _put(days=219),
            convexity=_BELOW_BAND,
        )

        assert record.action is RollAction.ROLL_NOW
        assert record.driver == "convexity"

    def test_a_quiet_leg_holds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        (record,) = _plan(
            monkeypatch,
            _put(days=400, spot=_ENTRY),
        )

        assert record.action is RollAction.HOLD
        assert record.driver is None
        assert record.rationale == "No trigger active; holding."


class TestTheRationaleNamesTheTriggerThatDecided:
    """Attribution is a cause, not a verdict match (#461 (a))."""

    def test_a_rally_action_band_beats_a_dated_time_review(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # +20% from entry is Rule 2's URGENT band, which grades ROLL.
        urgent = _put(days=219, spot=7_560.0)
        (record,) = _plan(monkeypatch, urgent)

        assert record.verdict is RollVerdict.ROLL
        assert record.action is RollAction.ROLL_NOW
        assert record.driver == "rally"
        assert record.rationale.startswith("Rally trigger:")
        assert "The time trigger is also in its review band" in record.rationale
        assert days_from_today(219).date().isoformat() not in (record.rationale)

    def test_a_tie_goes_to_the_earlier_trigger_in_the_shared_precedence(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Time and convexity both ROLL_NOW: time is named, the other noted."""
        (record,) = _plan(
            monkeypatch,
            _put(days=150),
            convexity=_BELOW_BAND,
        )

        assert TRIGGER_PRECEDENCE == ("time", "convexity", "rally")
        assert record.action is RollAction.ROLL_NOW
        assert record.driver == "time"
        assert record.rationale.startswith("Time trigger:")
        assert "Convexity trigger also at ROLL." in record.rationale

    def test_the_status_reason_and_the_plan_driver_agree_on_a_tie(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One precedence: the table and the plan name the same trigger."""
        position = _put(days=150)
        _convexity(monkeypatch, _BELOW_BAND)
        (status,) = evaluate_roll_status(_book(position), _ips())
        (plan,) = build_roll_plan(_book(position), _ips())

        assert driving_trigger(status) == plan.driver == "time"
        assert verdict_reason(status) == status.time_trigger.reason

    def test_the_status_reason_is_the_first_trigger_at_the_verdict(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (status,) = _plan_status(monkeypatch, _put(days=219))

        # Time and rally are both at REVIEW; the table names time.
        assert driving_trigger(status) == "time"
        assert verdict_reason(status) == status.time_trigger.reason


class TestAnUnmeasuredBandCannotClearARallyReview:
    """The REVIEW band's condition has no answer, and the plan says so."""

    def test_the_action_stands_and_the_rationale_says_why(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 400d is outside the buffer: only Rule 2 has fired, and a measured
        # in-band convexity would make this CHECKED.
        (record,) = _plan(monkeypatch, _put(days=400), convexity=None)

        assert record.action is RollAction.ROLL_NOW
        assert record.driver == "rally"
        assert "could not be measured" in record.rationale
        assert "condition cannot clear" in record.rationale
        assert "the roll stands until it can be read" in record.rationale


class TestTheVerdictAndTheActionNameTheSameTrigger:
    """Two code paths, one precedence: checked over a grid, not assumed.

    ``driving_trigger`` names the trigger behind a *verdict* and
    ``leg_action`` the one behind an *action*. Both break ties with
    ``TRIGGER_PRECEDENCE``, so they agree wherever there is an action, with
    one documented exception: a leg whose time and rally triggers are both at
    REVIEW is graded REVIEW on the time trigger, but when convexity is not in
    band the rally's condition fails and the rally decides ROLL NOW. This
    walks time x convexity x rally and fails if any cell disagrees in any
    other way, and checks the reason printed beside the action is always the
    action's own trigger's (``leg_reason``).
    """

    @pytest.mark.parametrize("days", [150, 219, 400], ids=lambda d: f"{d}d")
    @pytest.mark.parametrize(
        "convexity",
        [_BELOW_BAND, _IN_BAND, 25.0],
        ids=["below", "in band", "above"],
    )
    @pytest.mark.parametrize(
        "spot",
        [_ENTRY, _RALLIED, 7_560.0],
        ids=["no rally", "rally REVIEW", "rally URGENT"],
    )
    def test_they_agree(
        self,
        monkeypatch: pytest.MonkeyPatch,
        days: int,
        convexity: float,
        spot: float,
    ) -> None:
        ips = _ips()
        _convexity(monkeypatch, convexity)
        (status,) = evaluate_roll_status(
            _book(_put(days=days, spot=spot)),
            ips,
        )

        decided = leg_action(status, ips_triggers=ips.triggers)

        assert decided is not None
        if decided.action is RollAction.HOLD:
            assert decided.driver is None
            return
        assert decided.driver is not None
        # Whatever the verdict named, the reason beside the action is the
        # trigger that decided the action.
        assert leg_reason(status, ips_triggers=ips.triggers) == (
            trigger_reading(status, decided.driver).reason
        )
        if decided.driver != driving_trigger(status):
            assert status.verdict is RollVerdict.REVIEW
            assert decided.action is RollAction.ROLL_NOW
            assert (decided.driver, driving_trigger(status)) == (
                "rally",
                "time",
            )


class TestTheActionScale:
    """The scale a leg's action is reduced on is written in one place."""

    def test_every_action_has_a_rank_and_the_ranks_are_ordered(self) -> None:
        assert set(_ACTION_URGENCY) == set(RollAction)
        ordered = sorted(RollAction, key=_ACTION_URGENCY.__getitem__)
        assert ordered == [
            RollAction.HOLD,
            RollAction.CHECKED,
            RollAction.DELAY,
            RollAction.ROLL_BY,
            RollAction.ROLL_NOW,
        ]

    def test_a_rally_review_cannot_also_satisfy_the_deferral(self) -> None:
        """CHECKED and DELAY stay exclusive: a rally moves a put away."""
        # drift_pct > 0 for every rally REVIEW; the deferral needs drift < 0.
        position = _put(days=219)
        (status,) = evaluate_roll_status(_book(position), _ips())

        assert status.moneyness.drift_pct is not None
        assert status.moneyness.drift_pct > 0

    def test_the_label_is_one_function(self) -> None:
        opens = days_from_today(10).date()

        assert action_label(RollAction.ROLL_BY, opens) == (
            f"ROLL BY {opens.isoformat()}"
        )
        assert action_label(RollAction.ROLL_NOW) == "ROLL NOW"
        assert action_label(RollAction.CHECKED) == "CHECKED"
        # No date, no invention: a ROLL_BY without one falls back to the name.
        assert action_label(RollAction.ROLL_BY) == "ROLL BY"


class TestLegActionIsTheSourceTheSurfacesShare:
    """/monitor, the status table and the digest ask this, not the plan."""

    def test_it_equals_the_plan_for_every_long_put(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        legs = (_put(days=219), _put(days=150), _put(days=400))
        _convexity(monkeypatch, _IN_BAND)
        ips = _ips()
        book = _book(*legs)
        plan = build_roll_plan(book, ips)

        for status, planned in zip(
            evaluate_roll_status(book, ips),
            plan,
            strict=True,
        ):
            decided = leg_action(status, ips_triggers=ips.triggers)
            assert decided is not None
            assert decided.action is planned.action
            assert decided.rationale == planned.rationale
            assert decided.window_opens == planned.window_opens
            assert decided.label == planned.action_label

    @pytest.mark.parametrize(
        "leg",
        [
            _put(days=219, quantity=-5),
            _put(days=219, option_type=OptionType.CALL),
            _put(days=-10),
        ],
        ids=["short put", "call", "expired"],
    )
    def test_a_leg_the_plan_declines_has_no_action(
        self,
        leg: OptionPosition,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _convexity(monkeypatch, _IN_BAND)
        ips = _ips()
        (status,) = evaluate_roll_status(_book(leg), ips)

        assert leg_action(status, ips_triggers=ips.triggers) is None
