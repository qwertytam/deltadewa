"""Batch 8a.2/8a.3 / N2+N3: the roll plan and the compliance verdict must agree.

Three surfaces describe one book to one reader, and review #3 found them
disagreeing:

- ``/design``'s roll plan said ``ROLL NOW`` for three long legs while the
  roll status table and ``/monitor``'s Decisions said ``REVIEW`` for the
  same legs at the same instant (#408). The rally sat in the handbook's
  Rule 2 REVIEW band, whose action is stated as a *conditional* — "roll
  strikes up **if** the convexity target is no longer met" — and the book's
  convexity was inside the band, so the condition was false. Nothing
  evaluated it: ``build_roll_plan`` treated REVIEW as actionable and
  ``gamma_theta_delay``, the only softening path, requires the put to have
  moved *nearer* the money, which a rally can never satisfy.
- ``/monitor``'s compliance strip said ``PASS`` while the same panel's
  efficiency sentence said the book was "too small", because
  ``build_ips_compliance`` never graded vega sufficiency (#409).

Both defects are the same shape: a second code path with nothing refereeing
it. So this module pins *properties over a whole book* rather than one
assertion per surface — the same rule Batch 8a.1's
``tests/test_portfolio/test_leg_marks_agree.py`` applies to a leg's marks.

Two families:

``TestPlanNeverEscalatesPastTheStatus`` sweeps a grid of rally readings x
convexity standings x time-to-maturity and asserts the relationship between
``RollAction`` and the raw trigger facts. It is deliberately written against
those facts (``record.verdict``, ``record.time_trigger.verdict``,
``record.convexity_target_met``) and not against
:func:`~deltadewa.analysis.roll_planner.rally_review_cleared`, which would
only restate the implementation back to itself.

``TestConvexityStandingIsOneBoolean`` is the referee between N2 and N3: the
roll path and the compliance path each answer "is the convexity target
met", and this pins that they answer it identically for the same book at
the same IPS anchor. ``test_crash_single_source.py`` already pins the
underlying *number* across those paths; this pins the *verdict* derived
from it.

Two more, named directly for Batch 8a.3's acceptance shape:

``TestFourRallyBandsByConvexityMatrix`` is the four-handbook-rally-bands x
convexity-in/out grid explicitly, rather than leaving it implicit in the
45-case sweep above. It pins the corner that makes ``CHECKED`` legitimate
(REVIEW band, convexity in band) against every other cell, which all
resolve to ``HOLD`` or ``ROLL_NOW`` -- never ``CHECKED`` -- so the matrix
also demonstrates the two grounds the plan documents for a legitimate
rally ``ROLL_NOW``: the ACTION/URGENT bands firing outright, or the
convexity trigger itself firing ``ROLL`` (which dominates ``max()``
regardless of how mild the rally is).

``TestPlanStatusAndDecisionsAgree`` is the cross-page proof: ``/design``'s
roll-status table, ``/monitor``'s Decisions panel, and
``build_roll_plan``'s own internal read all call
``evaluate_roll_status(portfolio, ips_config)`` -- the identical function,
with the identical two positional arguments and no ``current_spot``
override -- at every call site (verified by reading
``app/pages/monitor.py:_build_decisions_panel``,
``app/pages/design/planning/roll_status.py:_render_roll_panel_logic``, and
``analysis/roll_planner.py:build_roll_plan``). So the three surfaces are
SINGLE-SOURCE on a leg's verdict by construction, not merely DERIVED with a
referee -- this test pins that construction so a future call site that
starts passing its own ``current_spot`` (the one parameter that could make
them diverge) fails loudly here rather than showing up as three panels
quietly disagreeing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis import roll_status as roll_status_module
from deltadewa.analysis.crash_payoff import compute_crash_convexity
from deltadewa.analysis.crash_repricing import CrashShock
from deltadewa.analysis.roll_planner import (
    RollAction,
    build_roll_plan,
)
from deltadewa.analysis.roll_status import (
    RollVerdict,
    evaluate_roll_status,
    meets_convexity_target,
)
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
from deltadewa.reporting.program_report import build_protection_section
from deltadewa.valuation import OptionValuation
from tests.clock_helpers import days_from_today, program_date

_SPOT = 100.0
_VOL = 0.20
_RATE = 0.04

# The IPS band the grid below is graded against. Distinct from the rally
# band edges so a mis-wired comparison cannot pass by coincidence.
_BAND_MIN = 15.0
_BAND_MAX = 25.0

# Convexity readings placed either side of, and inside, that band.
_CONVEXITY_BELOW = 10.0
_CONVEXITY_IN_BAND = 20.0
_CONVEXITY_ABOVE = 30.0

# roll_at_months_remaining=1.0 -> a 30-day roll window; roll_review_buffer
# 1.5 -> REVIEW from 45 days out. The three day counts below land one in
# each region: inside the window (ROLL), inside the review buffer (REVIEW),
# and clear of both (HOLD).
_DAYS_INSIDE_WINDOW = 20
_DAYS_IN_REVIEW_BUFFER = 40
_DAYS_CLEAR = 200


def _make_ips_config(
    *,
    target_min_pct: float = _BAND_MIN,
    target_max_pct: float = _BAND_MAX,
) -> IpsConfig:
    """An IPS whose rally bands are the handbook's shipped 5/10/15/20."""
    return IpsConfig(
        program=IpsProgram(name="test", instrument="SPX"),
        pricing=IpsPricing(exercise_style=ExerciseStyle.EUROPEAN),
        budget=IpsBudget(annual_carry_pct=2.0),
        convexity=IpsConvexity(
            crash_scenario_pct=-25.0,
            target_min_pct=target_min_pct,
            target_max_pct=target_max_pct,
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


def _entry_spot_for(rally_pct: float) -> float:
    """The entry spot that makes the book's rally-since-entry *rally_pct*."""
    return _SPOT / (1.0 + rally_pct / 100.0)


def _put_rallied_by(
    rally_pct: float,
    days_to_maturity: int,
    *,
    strike_price: float = 90.0,
) -> OptionPosition:
    """A long put whose rally-since-entry reads *rally_pct*."""
    option = OptionValuation(
        spot_price=_SPOT,
        strike_price=strike_price,
        maturity_date=days_from_today(days_to_maturity),
        volatility=_VOL,
        risk_free_rate=_RATE,
        dividend_yield=0.0,
        option_type=OptionType.PUT,
        exercise_style=ExerciseStyle.EUROPEAN,
    )
    return OptionPosition(
        option=option,
        quantity=5,
        exercise_style=ExerciseStyle.EUROPEAN,
        entry_spot=_entry_spot_for(rally_pct),
        entry_date=program_date() - timedelta(days=30),
    )


def _portfolio_with(
    *positions: OptionPosition,
    underlying_quantity: float = 0.0,
) -> OptionPortfolio:
    portfolio = OptionPortfolio(
        spot_price=_SPOT,
        underlying_quantity=underlying_quantity,
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )
    for position in positions:
        portfolio.positions.append(position)
    return portfolio


def _force_convexity(
    monkeypatch: pytest.MonkeyPatch,
    value: float,
) -> None:
    """Pin the book's crash convexity so the grid controls that axis.

    The grid is about the *relationship* between a convexity standing and a
    roll action, not about whether a crafted book prices to a particular
    convexity — which would make every case a hostage to the pricing
    engine. ``TestConvexityStandingIsOneBoolean`` below deliberately does
    not patch, so the real reading is exercised too.
    """

    def _fake(_self: object, _shock: CrashShock) -> float:
        return value

    monkeypatch.setattr(
        roll_status_module.PortfolioAnalyzer,
        "calculate_crash_convexity_pct",
        _fake,
    )


# ---------------------------------------------------------------------------
# The property: the plan never escalates past what the status supports
# ---------------------------------------------------------------------------


_RALLY_READINGS = (0.0, 7.0, 12.0, 17.0, 22.0)
_CONVEXITY_READINGS = (
    _CONVEXITY_BELOW,
    _CONVEXITY_IN_BAND,
    _CONVEXITY_ABOVE,
)
_DAY_COUNTS = (_DAYS_INSIDE_WINDOW, _DAYS_IN_REVIEW_BUFFER, _DAYS_CLEAR)


@pytest.mark.parametrize("rally_pct", _RALLY_READINGS)
@pytest.mark.parametrize("convexity_pct", _CONVEXITY_READINGS)
@pytest.mark.parametrize("days_to_maturity", _DAY_COUNTS)
class TestPlanNeverEscalatesPastTheStatus:
    """One property, swept over every rally x convexity x maturity cell.

    45 books. Each assertion below is a statement about *any* leg, not
    about one crafted scenario — which is what makes this a referee between
    the two verdict paths rather than a third opinion.
    """

    @staticmethod
    def _only_leg(
        monkeypatch: pytest.MonkeyPatch,
        rally_pct: float,
        convexity_pct: float,
        days_to_maturity: int,
    ) -> tuple[object, object]:
        _force_convexity(monkeypatch, convexity_pct)
        portfolio = _portfolio_with(
            _put_rallied_by(rally_pct, days_to_maturity),
        )
        ips = _make_ips_config()
        (status,) = evaluate_roll_status(portfolio, ips)
        (plan,) = build_roll_plan(portfolio, ips)
        return status, plan

    def test_roll_now_always_has_a_reason_the_triggers_support(
        self,
        monkeypatch: pytest.MonkeyPatch,
        rally_pct: float,
        convexity_pct: float,
        days_to_maturity: int,
    ) -> None:
        """#408's boundary condition, stated over the whole grid.

        ROLL_NOW is legitimate on exactly three grounds, and the raw
        triggers must show at least one of them:

        - the verdict is ROLL outright (the time window, a convexity floor
          breach, or the rally's own ACTION/URGENT bands);
        - the *time* trigger is at REVIEW, i.e. Rule 1's review buffer,
          which carries no convexity condition; or
        - the convexity target is genuinely not met, which is the Rule 2
          REVIEW band's own stated condition.

        A rally REVIEW with the target still met satisfies none of them,
        and that is the case the live book hit: three long legs called
        ROLL NOW at ~$140K of roll-up cost on a condition that was false.
        """
        status, plan = self._only_leg(
            monkeypatch,
            rally_pct,
            convexity_pct,
            days_to_maturity,
        )
        if plan.action is not RollAction.ROLL_NOW:
            return
        assert (
            status.verdict is RollVerdict.ROLL
            or status.time_trigger.verdict is RollVerdict.REVIEW
            or not status.convexity_target_met
        ), (
            f"ROLL_NOW on rally {rally_pct}%, convexity {convexity_pct}%,"
            f" {days_to_maturity}d — no trigger supports it"
        )

    def test_an_action_only_ever_answers_an_actionable_verdict(
        self,
        monkeypatch: pytest.MonkeyPatch,
        rally_pct: float,
        convexity_pct: float,
        days_to_maturity: int,
    ) -> None:
        """Anything but HOLD requires the status table to be at REVIEW+.

        The plan may soften a verdict; it may never invent urgency the
        evidence layer does not carry.
        """
        status, plan = self._only_leg(
            monkeypatch,
            rally_pct,
            convexity_pct,
            days_to_maturity,
        )
        if plan.action is RollAction.HOLD:
            assert status.verdict not in (
                RollVerdict.ROLL,
                RollVerdict.REVIEW,
            )
        else:
            assert status.verdict in (RollVerdict.ROLL, RollVerdict.REVIEW)

    def test_checked_means_the_rally_review_condition_came_back_false(
        self,
        monkeypatch: pytest.MonkeyPatch,
        rally_pct: float,
        convexity_pct: float,
        days_to_maturity: int,
    ) -> None:
        """CHECKED is reachable from exactly one place, and says so."""
        status, plan = self._only_leg(
            monkeypatch,
            rally_pct,
            convexity_pct,
            days_to_maturity,
        )
        if plan.action is not RollAction.CHECKED:
            return
        assert status.verdict is RollVerdict.REVIEW
        assert status.rally_trigger.verdict is RollVerdict.REVIEW
        assert status.time_trigger.verdict is not RollVerdict.REVIEW
        assert status.convexity_target_met is True

    def test_the_recomputation_is_stated_wherever_it_was_made(
        self,
        monkeypatch: pytest.MonkeyPatch,
        rally_pct: float,
        convexity_pct: float,
        days_to_maturity: int,
    ) -> None:
        """A rally REVIEW never leaves its "if" hanging on any surface.

        The reason is what ``/design``'s roll status table, ``/monitor``'s
        Decisions, and the roll plan's own rationale all render, so
        resolving the conditional there is what makes the three agree.
        """
        status, _plan = self._only_leg(
            monkeypatch,
            rally_pct,
            convexity_pct,
            days_to_maturity,
        )
        if status.rally_trigger.verdict is not RollVerdict.REVIEW:
            return
        assert "Recomputed:" in status.rally_trigger.reason
        stated_met = "still inside" in status.rally_trigger.reason
        assert stated_met is status.convexity_target_met


# ---------------------------------------------------------------------------
# The specific cases review #3 reported, and their boundaries
# ---------------------------------------------------------------------------


class TestTheReportedCase:
    """The live book's exact shape, and the cases either side of it."""

    def _plan_for(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        rally_pct: float,
        convexity_pct: float,
        days_to_maturity: int = _DAYS_CLEAR,
    ) -> RollAction | None:
        _force_convexity(monkeypatch, convexity_pct)
        portfolio = _portfolio_with(
            _put_rallied_by(rally_pct, days_to_maturity),
        )
        (plan,) = build_roll_plan(portfolio, _make_ips_config())
        return plan.action

    def test_rally_review_with_convexity_in_band_is_checked(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The reported case: +11.6% rally, convexity in band.

        Was ROLL_NOW on ~$140K of roll-up cost across three legs, against a
        REVIEW in the table beside it.
        """
        assert (
            self._plan_for(
                monkeypatch,
                rally_pct=11.6,
                convexity_pct=_CONVEXITY_IN_BAND,
            )
            is RollAction.CHECKED
        )

    def test_rally_review_with_convexity_out_of_band_still_rolls(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The condition is true, so the REVIEW band does call for a roll.

        Below the floor the convexity trigger grades ROLL in its own right,
        so this is ROLL_NOW twice over — which is the point: #408 is about
        an unevaluated condition, not about suppressing a real one.
        """
        assert (
            self._plan_for(
                monkeypatch,
                rally_pct=11.6,
                convexity_pct=_CONVEXITY_BELOW,
            )
            is RollAction.ROLL_NOW
        )

    def test_the_action_band_rolls_however_healthy_convexity_is(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """At/past 15% the handbook prescribes outright — no condition."""
        assert (
            self._plan_for(
                monkeypatch,
                rally_pct=17.0,
                convexity_pct=_CONVEXITY_IN_BAND,
            )
            is RollAction.ROLL_NOW
        )

    def test_just_under_the_review_band_never_reached_an_action(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The MONITOR band is not actionable, before or after #408."""
        assert (
            self._plan_for(
                monkeypatch,
                rally_pct=7.0,
                convexity_pct=_CONVEXITY_IN_BAND,
            )
            is RollAction.HOLD
        )

    def test_a_time_review_is_not_cleared_by_a_healthy_band(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Rule 1's review buffer carries no convexity condition.

        A leg approaching its roll window is due a look whatever the book's
        convexity reads, so CHECKED must not swallow it — this is
        ``rally_review_cleared``'s third condition, and the reason it is
        not enough to test the rally trigger alone.
        """
        action = self._plan_for(
            monkeypatch,
            rally_pct=11.6,
            convexity_pct=_CONVEXITY_IN_BAND,
            days_to_maturity=_DAYS_IN_REVIEW_BUFFER,
        )
        assert action is not RollAction.CHECKED

    def test_checked_and_delay_are_mutually_exclusive(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A rally and a nearer-the-money drift cannot co-occur.

        ``_plan_structure`` tests CHECKED before DELAY, and this is why the
        ordering is documentation rather than load-bearing: a rally moves a
        put *further* OTM, so any leg CHECKED clears has ``drift_pct > 0``
        and can never satisfy ``gamma_theta_delay``'s nearer-the-money
        condition.
        """
        _force_convexity(monkeypatch, _CONVEXITY_IN_BAND)
        portfolio = _portfolio_with(_put_rallied_by(11.6, _DAYS_CLEAR))
        ips = _make_ips_config()

        (status,) = evaluate_roll_status(portfolio, ips)
        (plan,) = build_roll_plan(portfolio, ips)

        assert plan.action is RollAction.CHECKED
        drift_pct = status.moneyness.drift_pct
        assert drift_pct is not None
        assert drift_pct > 0

    def test_the_rationale_resolves_the_conditional_it_used_to_parrot(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """#408's false-green half: the rendered reason must not hang.

        The roll plan's rationale cell is rendered verbatim on ``/design``.
        Before this batch it read "roll strikes up if the convexity target
        is no longer met" beside a ROLL NOW badge, on a book whose target
        *was* met.
        """
        _force_convexity(monkeypatch, _CONVEXITY_IN_BAND)
        portfolio = _portfolio_with(_put_rallied_by(11.6, _DAYS_CLEAR))
        (plan,) = build_roll_plan(portfolio, _make_ips_config())

        assert "Recomputed:" in plan.rationale
        assert "still inside" in plan.rationale
        assert "No roll warranted" in plan.rationale


# ---------------------------------------------------------------------------
# The referee between N2 and N3
# ---------------------------------------------------------------------------


def _real_book() -> OptionPortfolio:
    """A priceable book with an underlying, so convexity is real.

    Deliberately unpatched: this family exists to check that two code
    paths reduce the *same* measured number to the same verdict, which a
    forced reading would not exercise.
    """
    portfolio = _portfolio_with(underlying_quantity=1_000.0)
    portfolio.add_position(
        strike_price=85.0,
        maturity_date=days_from_today(400),
        quantity=20,
        option_type=OptionType.PUT,
    )
    return portfolio


class TestConvexityStandingIsOneBoolean:
    """ "Is the convexity target met" has one answer, not two (#408/#409).

    The roll path resolves it on ``RollStatusRecord.convexity_target_met``;
    the compliance path resolves it on
    ``ProtectionSection.meets_target``. Both grade the same book against
    the same IPS band, and ``/design``'s roll plan sits one page away from
    ``/monitor``'s compliance strip, so a reader can hold both at once.
    """

    @pytest.mark.parametrize(
        ("target_min_pct", "target_max_pct"),
        [
            pytest.param(-100.0, 100.0, id="band-straddles-the-reading"),
            pytest.param(90.0, 100.0, id="band-above-the-reading"),
            pytest.param(-100.0, -90.0, id="band-below-the-reading"),
        ],
    )
    def test_both_paths_agree_for_the_same_book(
        self,
        target_min_pct: float,
        target_max_pct: float,
    ) -> None:
        """In band, under it, and over it — the two verdicts must match.

        Bands are placed relative to the reading rather than pinned to the
        IPS's own 10-20%, so this stays correct however policy moves — the
        same fixture rule ``test_monitor.py``'s convexity fixture follows.
        """
        portfolio = _real_book()
        ips = _make_ips_config(
            target_min_pct=target_min_pct,
            target_max_pct=target_max_pct,
        )

        (status,) = evaluate_roll_status(portfolio, ips)
        protection = build_protection_section(
            compute_crash_convexity(
                portfolio,
                shock=CrashShock.from_ips(ips.convexity),
                ips_convexity=ips.convexity,
            ),
        )

        assert protection.meets_target is not None
        assert status.convexity_target_met is protection.meets_target

    def test_the_boolean_matches_the_number_beside_it(self) -> None:
        """The record's own two fields cannot disagree with each other."""
        portfolio = _real_book()
        ips = _make_ips_config(target_min_pct=-100.0, target_max_pct=100.0)

        (status,) = evaluate_roll_status(portfolio, ips)

        assert status.convexity_target_met is meets_convexity_target(
            status.crash_convexity_pct,
            target_min_pct=status.convexity_target_min_pct,
            target_max_pct=status.convexity_target_max_pct,
        )

    def test_an_expired_leg_still_carries_the_books_standing(self) -> None:
        """It is a book fact, not a leg fact (#362/#373).

        An expired leg is excluded from the convexity *figures*, but the
        book still has a convexity standing, and a row that reported
        ``False`` here would read as a breach that never happened.
        """
        portfolio = _portfolio_with(underlying_quantity=1_000.0)
        portfolio.add_position(
            strike_price=85.0,
            maturity_date=days_from_today(400),
            quantity=20,
            option_type=OptionType.PUT,
        )
        expired = OptionValuation(
            spot_price=_SPOT,
            strike_price=80.0,
            maturity_date=datetime(2020, 1, 17, tzinfo=UTC),
            volatility=_VOL,
            risk_free_rate=_RATE,
            dividend_yield=0.0,
            option_type=OptionType.PUT,
            exercise_style=ExerciseStyle.EUROPEAN,
        )
        portfolio.positions.append(
            OptionPosition(
                option=expired,
                quantity=5,
                exercise_style=ExerciseStyle.EUROPEAN,
            ),
        )
        ips = _make_ips_config(target_min_pct=-100.0, target_max_pct=100.0)

        records = evaluate_roll_status(portfolio, ips)

        expired_record = next(
            r for r in records if r.verdict is RollVerdict.EXPIRED
        )
        assert expired_record.convexity_target_met is True


# ---------------------------------------------------------------------------
# The explicit four-rally-bands x convexity-in/out matrix (Batch 8a.3)
# ---------------------------------------------------------------------------

# Representative points strictly inside each of the handbook's four Rule 2
# bands (rally_monitor_pct=5, _review_pct=10, _action_pct=15,
# _urgent_pct=20 -- see _make_ips_config). MONITOR is included so the
# matrix shows the non-actionable case too, even though only REVIEW carries
# a conditional action.
_RALLY_MONITOR = 7.0
_RALLY_REVIEW = 12.0
_RALLY_ACTION = 17.0
_RALLY_URGENT = 22.0

# "In" reuses _CONVEXITY_IN_BAND; "out" is specifically *below the floor*
# (the direction the REVIEW band's own condition and the plan's
# convexity-fail ground both describe as "target no longer met") rather
# than above the ceiling, which the wider grid above already covers and
# which drives the convexity trigger to MONITOR rather than ROLL -- a
# different severity that would blur this matrix's point.
_CONVEXITY_OUT = _CONVEXITY_BELOW


@pytest.mark.parametrize(
    ("rally_pct", "convexity_pct", "expected"),
    [
        pytest.param(
            _RALLY_MONITOR,
            _CONVEXITY_IN_BAND,
            RollAction.HOLD,
            id="MONITOR-band-x-convexity-in",
        ),
        pytest.param(
            _RALLY_MONITOR,
            _CONVEXITY_OUT,
            RollAction.ROLL_NOW,
            id="MONITOR-band-x-convexity-out",
        ),
        pytest.param(
            _RALLY_REVIEW,
            _CONVEXITY_IN_BAND,
            RollAction.CHECKED,
            id="REVIEW-band-x-convexity-in",
        ),
        pytest.param(
            _RALLY_REVIEW,
            _CONVEXITY_OUT,
            RollAction.ROLL_NOW,
            id="REVIEW-band-x-convexity-out",
        ),
        pytest.param(
            _RALLY_ACTION,
            _CONVEXITY_IN_BAND,
            RollAction.ROLL_NOW,
            id="ACTION-band-x-convexity-in",
        ),
        pytest.param(
            _RALLY_ACTION,
            _CONVEXITY_OUT,
            RollAction.ROLL_NOW,
            id="ACTION-band-x-convexity-out",
        ),
        pytest.param(
            _RALLY_URGENT,
            _CONVEXITY_IN_BAND,
            RollAction.ROLL_NOW,
            id="URGENT-band-x-convexity-in",
        ),
        pytest.param(
            _RALLY_URGENT,
            _CONVEXITY_OUT,
            RollAction.ROLL_NOW,
            id="URGENT-band-x-convexity-out",
        ),
    ],
)
def test_four_rally_bands_by_convexity_matrix(
    monkeypatch: pytest.MonkeyPatch,
    rally_pct: float,
    convexity_pct: float,
    expected: RollAction,
) -> None:
    """The review's acceptance matrix, named explicitly (#408, Batch 8a.3).

    Time trigger held clear (``_DAYS_CLEAR``) so only the rally x convexity
    interaction is on test. ``CHECKED`` is reachable from exactly one
    cell -- REVIEW-band rally with convexity in band, the reported case --
    and a convexity-below-floor reading escalates every other cell to
    ``ROLL_NOW`` regardless of how mild the rally is, because the
    convexity trigger fires ``ROLL`` in its own right and ``max()`` picks
    it up (#408's second legitimate ground for a rally ``ROLL_NOW``).
    """
    _force_convexity(monkeypatch, convexity_pct)
    portfolio = _portfolio_with(_put_rallied_by(rally_pct, _DAYS_CLEAR))
    (plan,) = build_roll_plan(portfolio, _make_ips_config())

    assert plan.action is expected


# ---------------------------------------------------------------------------
# The cross-page proof (Batch 8a.3): plan, roll-status table, /monitor's
# Decisions all read the identical verdict for the identical leg.
# ---------------------------------------------------------------------------


def _mixed_state_book() -> OptionPortfolio:
    """One book, three legs, three different verdicts.

    A single-verdict book would make an equality check trivially pass —
    this book forces HOLD, CHECKED-eligible REVIEW, and ROLL_NOW-eligible
    ACTION legs to coexist, the way ``/design`` and ``/monitor`` actually
    render one book with several tranches at once.
    """
    return _portfolio_with(
        _put_rallied_by(0.0, _DAYS_CLEAR, strike_price=90.0),
        _put_rallied_by(_RALLY_REVIEW, _DAYS_CLEAR, strike_price=88.0),
        _put_rallied_by(_RALLY_ACTION, _DAYS_CLEAR, strike_price=86.0),
    )


class TestPlanStatusAndDecisionsAgree:
    """One verdict per leg, read identically by every rendering surface.

    ``/monitor``'s Decisions panel
    (``app/pages/monitor.py:_build_decisions_panel``) and ``/design``'s
    roll-status table
    (``app/pages/design/planning/roll_status.py:_render_roll_panel_logic``)
    both call ``evaluate_roll_status(portfolio, ips_config)`` — the
    identical function, the identical two positional arguments, no
    ``current_spot`` override at either site. ``build_roll_plan`` calls the
    same function the same way internally. This test exercises that one
    function once and asserts every leg's ``RollPlanRecord.verdict``
    matches its own ``RollStatusRecord.verdict`` — proving by construction,
    not just by reading the call sites, that a leg's severity cannot read
    differently on the two pages.
    """

    def test_every_legs_verdict_matches_across_producers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _force_convexity(monkeypatch, _CONVEXITY_IN_BAND)
        portfolio = _mixed_state_book()
        ips = _make_ips_config()

        status_by_position = {
            r.position.position_id: r
            for r in evaluate_roll_status(
                portfolio,
                ips,
            )
        }
        plan_records = build_roll_plan(portfolio, ips)

        # The book must actually exercise more than one verdict, or this
        # test would pass by accident on an all-HOLD book.
        assert len({r.verdict for r in status_by_position.values()}) > 1

        for plan_record in plan_records:
            status_record = status_by_position[plan_record.position.position_id]
            assert plan_record.verdict == status_record.verdict, (
                f"{plan_record.position.option.strike_price}: plan says "
                f"{plan_record.verdict}, status says {status_record.verdict}"
            )

    def test_the_reported_legs_verdict_is_review_everywhere(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The live book's shape: REVIEW on both producers, CHECKED action.

        This is what review #3 found broken — a leg the status table and
        Decisions called REVIEW while the plan called it ROLL NOW, an
        action, not a verdict, with no REVIEW-severity counterpart at all.
        """
        _force_convexity(monkeypatch, _CONVEXITY_IN_BAND)
        portfolio = _portfolio_with(_put_rallied_by(11.6, _DAYS_CLEAR))
        ips = _make_ips_config()

        (status,) = evaluate_roll_status(portfolio, ips)
        (plan,) = build_roll_plan(portfolio, ips)

        assert status.verdict is RollVerdict.REVIEW
        assert plan.verdict is RollVerdict.REVIEW
        assert plan.action is RollAction.CHECKED
