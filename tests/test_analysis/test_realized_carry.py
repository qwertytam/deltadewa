"""Tests for realized carry, the handbook's identity (#313).

Every figure is crafted from marks and fills with known values, so each
assertion is the identity worked by hand:
``gross = V0 + P - R_routine - V1``, ``net = gross - R_monetization``.
Contracts are 100 shares, so a lot of ``q`` at ``p`` is worth ``100 q p``.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from enum import StrEnum

import pytest

from deltadewa.analysis.realized_carry import (
    hedged_return,
    latest_period,
    realized_carry,
    reconcile_book,
    since_inception,
)
from deltadewa.portfolio.history import (
    CloseReason,
    EditKind,
    FillKind,
    PositionHistory,
)
from tests.history_builders import at, edit, fill, leg, mark, terms

D0 = date(2026, 11, 7)
D1 = date(2026, 11, 14)
D2 = date(2026, 11, 21)

# 1000 shares at 5000: a 5,000,000 portfolio.
PORTFOLIO_VALUE = 5_000_000.0


def _mark_findings(history: PositionHistory) -> list[str]:
    """Reconciliation findings between marks, ignoring the live book."""
    return [
        finding
        for finding in reconcile_book(history, ())
        if not finding.startswith("live book")
    ]


class TestIdentity:
    """The four terms, the sign convention and the gross/net split."""

    def test_quiet_period_is_a_cost(self) -> None:
        """No trades, the book decays 10,000 -> 8,000: carry is +2,000."""
        start = mark(D0, (leg("a", 10, 10.0),))
        end = mark(D1, (leg("a", 10, 8.0),))
        result = realized_carry(PositionHistory(), start=start, end=end)
        assert (result.v0, result.v1) == (10_000.0, 8_000.0)
        assert result.gross == pytest.approx(2_000.0)
        assert result.net == pytest.approx(2_000.0)
        assert result.days == 7
        assert result.portfolio_value == PORTFOLIO_VALUE
        assert result.gross_annual_pct == pytest.approx(
            2_000.0 / PORTFOLIO_VALUE * 365 / 7 * 100,
        )
        assert result.reconcilable

    def test_crash_with_routine_close_is_a_gain(self) -> None:
        """When R - V1 dominates, carry goes negative: the hedge paid."""
        start = mark(D0, (leg("a", 10, 10.0),))
        sold = fill(
            FillKind.CLOSE,
            "a",
            -10,
            60.0,
            day=D1,
            fees=10.0,
            reason=CloseReason.ROUTINE,
        )
        end = mark(D1)
        result = realized_carry(
            PositionHistory(recorded_fills=(sold,)),
            start=start,
            end=end,
        )
        # 10,000 + 0 - 59,990 - 0
        assert result.received_routine == pytest.approx(59_990.0)
        assert result.gross == pytest.approx(-49_990.0)
        assert result.net == result.gross

    def test_monetization_is_kept_out_of_gross(self) -> None:
        """Harvested gains move net only; gross stays the premium."""
        start = mark(D0, (leg("a", 10, 10.0),))
        harvested = fill(
            FillKind.CLOSE,
            "a",
            -10,
            60.0,
            day=D1,
            fees=10.0,
            reason=CloseReason.MONETIZATION,
        )
        result = realized_carry(
            PositionHistory(recorded_fills=(harvested,)),
            start=start,
            end=mark(D1),
        )
        assert result.received_routine == pytest.approx(0.0)
        assert result.received_monetization == pytest.approx(59_990.0)
        assert result.gross == pytest.approx(10_000.0)
        assert result.net == pytest.approx(10_000.0 - 59_990.0)

    def test_roll_is_two_fills(self) -> None:
        """Close the old lot, open the new: the net debit is recoverable."""
        old, new = terms(4200.0), terms(4400.0, date(2027, 12, 17))
        start = mark(D0, (leg("old", 10, 3.0, contract=old),))
        closed = fill(
            FillKind.CLOSE,
            "old",
            -10,
            2.0,
            day=D1,
            fees=5.0,
            reason=CloseReason.ROUTINE,
            contract=old,
            roll_id="r",
        )
        opened = fill(
            FillKind.OPEN,
            "new",
            10,
            8.0,
            day=D1,
            fees=5.0,
            contract=new,
            roll_id="r",
        )
        end = mark(D1, (leg("new", 10, 7.5, contract=new),))
        history = PositionHistory(
            recorded_fills=(closed, opened),
            marks=(start, end),
        )
        result = realized_carry(history, start=start, end=end)
        assert result.paid == pytest.approx(8_005.0)
        assert result.received_routine == pytest.approx(1_995.0)
        # 3,000 + 8,005 - 1,995 - 7,500
        assert result.gross == pytest.approx(1_510.0)
        assert result.paid - result.received_routine == pytest.approx(6_010.0)
        # The two fills explain the end mark's lots exactly.
        assert _mark_findings(history) == []

    def test_partial_close(self) -> None:
        """Selling part of a lot: R is the cash, V1 the remainder."""
        start = mark(D0, (leg("a", 10, 10.0),))
        sold = fill(
            FillKind.CLOSE,
            "a",
            -4,
            12.0,
            day=D1,
            reason=CloseReason.ROUTINE,
        )
        end = mark(D1, (leg("a", 6, 11.0),))
        history = PositionHistory(recorded_fills=(sold,), marks=(start, end))
        result = realized_carry(history, start=start, end=end)
        # 10,000 + 0 - 4,800 - 6,600
        assert result.gross == pytest.approx(-1_400.0)
        assert _mark_findings(history) == []

    def test_short_open_is_a_credit_in_paid(self) -> None:
        """Selling a leg to open is negative P, not a receipt."""
        sold = fill(FillKind.OPEN, "s", -5, 2.0, day=D1)
        result = realized_carry(
            PositionHistory(recorded_fills=(sold,)),
            start=mark(D0),
            end=mark(D1, (leg("s", -5, 2.0),)),
        )
        assert result.paid == pytest.approx(-1_000.0)
        assert result.gross == pytest.approx(0.0)

    def test_fill_on_start_date_belongs_to_the_prior_period(self) -> None:
        """A mark on D includes trades dated D."""
        bought = fill(FillKind.OPEN, "a", 10, 10.0, day=D0)
        result = realized_carry(
            PositionHistory(recorded_fills=(bought,)),
            start=mark(D0, (leg("a", 10, 10.0),)),
            end=mark(D1, (leg("a", 10, 10.0),)),
        )
        assert result.paid == pytest.approx(0.0)
        assert result.gross == pytest.approx(0.0)


class TestPeriods:
    """Periods are spans between marks, and they add up."""

    def test_adjacent_periods_sum_to_the_whole(self) -> None:
        """The shared boundary mark makes quarters sum to the year."""
        m0 = mark(D0, (leg("a", 10, 10.0),), is_opening=True)
        m1 = mark(D1, (leg("a", 10, 9.0), leg("b", 5, 4.0)))
        m2 = mark(D2, (leg("b", 5, 3.0),))
        history = PositionHistory(
            recorded_fills=(
                fill(FillKind.OPEN, "b", 5, 4.2, day=D1, fees=3.0),
                fill(
                    FillKind.CLOSE,
                    "a",
                    -10,
                    8.5,
                    day=D2,
                    fees=3.0,
                    reason=CloseReason.MONETIZATION,
                ),
            ),
            marks=(m0, m1, m2),
        )
        first = realized_carry(history, start=m0, end=m1)
        second = realized_carry(history, start=m1, end=m2)
        whole = since_inception(history)
        assert whole is not None
        assert first.gross + second.gross == pytest.approx(whole.gross)
        assert first.net + second.net == pytest.approx(whole.net)
        assert latest_period(history) == second

    def test_one_mark_is_not_a_measurement(self) -> None:
        """A single mark yields nothing, not zero."""
        history = PositionHistory(marks=(mark(D0, is_opening=True),))
        assert since_inception(history) is None
        assert latest_period(history) is None

    def test_end_must_follow_start(self) -> None:
        """A period cannot run backwards or have zero length."""
        with pytest.raises(ValueError, match="not after start"):
            realized_carry(PositionHistory(), start=mark(D1), end=mark(D1))

    def test_mixed_basis_refused(self) -> None:
        """Two bases at the two ends would be a meaningless figure."""

        class _OtherBasis(StrEnum):
            MID = "MID"

        end = dataclasses.replace(mark(D1), basis=_OtherBasis.MID)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="one basis at both ends"):
            realized_carry(PositionHistory(), start=mark(D0), end=end)

    def test_spot_age_is_reported_not_graded(self) -> None:
        """Spot age is a fact for the reader; staleness policy is the IPS's."""
        result = realized_carry(
            PositionHistory(),
            start=mark(D0),
            end=mark(D1, spot_as_of=at(date(2026, 11, 5))),
        )
        assert result.start_spot_age_days is None
        assert result.end_spot_age_days == 9
        assert result.reconcilable

    def test_no_underlying_means_no_percent(self) -> None:
        """Dollars still compute; a percent of nothing does not."""
        result = realized_carry(
            PositionHistory(),
            start=mark(D0, (leg("a", 1, 1.0),), underlying_quantity=0.0),
            end=mark(D1),
        )
        assert result.gross == pytest.approx(100.0)
        assert result.gross_annual_pct is None
        assert result.net_annual_pct is None


class TestBreaks:
    """Each reason a period cannot tie to a statement is named."""

    def test_book_edit_breaks_the_period(self) -> None:
        """A change with no fill makes the period unreconcilable."""
        history = PositionHistory(
            edits=(
                edit(
                    EditKind.AMEND,
                    "a",
                    day=D1,
                    quantity_before=10,
                    quantity_after=12,
                ),
            ),
        )
        result = realized_carry(history, start=mark(D0), end=mark(D1))
        assert not result.reconcilable
        assert result.breaks == (
            "book edited without a fill on 2026-11-14 (AMEND): AMEND in a test",
        )

    def test_uncaptured_fees_are_named_and_not_zeroed(self) -> None:
        """The price still counts; the missing fee is a break, not 0."""
        bought = fill(FillKind.OPEN, "a", 10, 10.0, day=D1, fees=None)
        result = realized_carry(
            PositionHistory(recorded_fills=(bought,)),
            start=mark(D0),
            end=mark(D1, (leg("a", 10, 10.0),)),
        )
        assert result.paid == pytest.approx(10_000.0)
        assert result.breaks == (
            "OPEN PUT 4200 2027-06-18 on 2026-11-14: fees not captured",
        )

    def test_uncaptured_price(self) -> None:
        """Both missing parts are named in one break."""
        bought = fill(FillKind.OPEN, "a", 10, None, day=D1, fees=None)
        result = realized_carry(
            PositionHistory(recorded_fills=(bought,)),
            start=mark(D0),
            end=mark(D1),
        )
        assert result.breaks == (
            (
                "OPEN PUT 4200 2027-06-18 on 2026-11-14: price and fees not "
                "captured"
            ),
        )

    def test_expired_unsettled_lot(self) -> None:
        """A lot marked past expiry without a settlement is a break."""
        result = realized_carry(
            PositionHistory(),
            start=mark(D0),
            end=mark(D1, (leg("a", 10, 0.0, expired_unsettled=True),)),
        )
        assert len(result.breaks) == 1
        assert "no settlement recorded" in result.breaks[0]

    def test_fill_recorded_after_the_end_mark(self) -> None:
        """Cash here, lot missing from V1."""
        late = fill(
            FillKind.OPEN,
            "a",
            1,
            1.0,
            day=D1,
            recorded_at=at(date(2026, 11, 16)),
        )
        result = realized_carry(
            PositionHistory(recorded_fills=(late,)),
            start=mark(D0),
            end=mark(D1),
        )
        assert result.breaks == (
            (
                "OPEN PUT 4200 2027-06-18 dated 2026-11-14 was recorded "
                "after the 2026-11-14 mark was taken, so that mark does not "
                "include it"
            ),
        )

    def test_backdated_fill_breaks_the_following_period(self) -> None:
        """Cash in an earlier period, lot appears in this one's V1."""
        backdated = fill(
            FillKind.OPEN,
            "a",
            1,
            1.0,
            day=D0,
            recorded_at=at(date(2026, 11, 10)),
        )
        history = PositionHistory(recorded_fills=(backdated,))
        result = realized_carry(history, start=mark(D0), end=mark(D1))
        assert len(result.breaks) == 1
        assert "2026-11-07 mark" in result.breaks[0]

    def test_fill_recorded_after_both_marks_is_not_this_period(self) -> None:
        """Its cash and its lot are both outside this period."""
        very_late = fill(
            FillKind.OPEN,
            "a",
            1,
            1.0,
            day=D0,
            recorded_at=at(date(2026, 11, 30)),
        )
        result = realized_carry(
            PositionHistory(recorded_fills=(very_late,)),
            start=mark(D0),
            end=mark(D1),
        )
        assert result.reconcilable


class TestHedgedReturn:
    """Before- and after-hedge return over one period."""

    def test_after_hedge_subtracts_net_carry(self) -> None:
        """Spot -20%, net carry is a 100,000 gain on 5,000,000: +2pp."""
        start = mark(D0, (leg("a", 10, 10.0),))
        end = mark(D1, spot=4000.0)
        harvested = fill(
            FillKind.CLOSE,
            "a",
            -10,
            110.0,
            day=D1,
            reason=CloseReason.MONETIZATION,
        )
        carry = realized_carry(
            PositionHistory(recorded_fills=(harvested,)),
            start=start,
            end=end,
        )
        assert carry.net == pytest.approx(-100_000.0)
        result = hedged_return(carry, start=start, end=end)
        assert result.before_hedge_pct == pytest.approx(-20.0)
        assert result.after_hedge_pct == pytest.approx(-18.0)
        assert result.unavailable_reason is None

    def test_changed_holding_is_unavailable(self) -> None:
        """Underlying flows are not recorded, so no return is invented."""
        start = mark(D0)
        end = mark(D1, underlying_quantity=1200.0)
        carry = realized_carry(PositionHistory(), start=start, end=end)
        result = hedged_return(carry, start=start, end=end)
        assert result.before_hedge_pct is None
        assert result.after_hedge_pct is None
        assert result.unavailable_reason is not None
        assert "holding changed" in result.unavailable_reason

    def test_no_holding_is_unavailable(self) -> None:
        """A zero-value portfolio has no return."""
        start = mark(D0, underlying_quantity=0.0)
        end = mark(D1, underlying_quantity=0.0)
        carry = realized_carry(PositionHistory(), start=start, end=end)
        result = hedged_return(carry, start=start, end=end)
        assert result.unavailable_reason == "no underlying holding is recorded"

    def test_marks_must_match_the_carry(self) -> None:
        """A return over other marks than the carry's is refused."""
        carry = realized_carry(PositionHistory(), start=mark(D0), end=mark(D1))
        with pytest.raises(ValueError, match="marks carry was computed on"):
            hedged_return(carry, start=mark(D0), end=mark(D2))


class TestReconcileBook:
    """The history must explain every lot each mark and the book hold."""

    def test_consistent_history_has_no_findings(self) -> None:
        """Opening mark plus fills reproduces every later mark."""
        m0 = mark(D0, (leg("a", 10, 1.0),), is_opening=True)
        bought = fill(FillKind.OPEN, "b", 5, 1.0, day=D1)
        m1 = mark(D1, (leg("a", 10, 1.0), leg("b", 5, 1.0)))
        history = PositionHistory(recorded_fills=(bought,), marks=(m0, m1))
        assert reconcile_book(history, ()) == (
            "live book: lot a — the history implies 10 contracts, 0 are held",
            "live book: lot b — the history implies 5 contracts, 0 are held",
        )

    def test_unrecorded_change_between_marks(self) -> None:
        """A lot that grew with no fill or edit is a finding."""
        m0 = mark(D0, (leg("a", 10, 1.0),))
        m1 = mark(D1, (leg("a", 12, 1.0),))
        history = PositionHistory(marks=(m0, m1))
        findings = reconcile_book(history, ())
        assert findings[0] == (
            "2026-11-14 mark: lot a — the history implies 10 contracts, "
            "12 are held"
        )

    def test_edits_are_applied(self) -> None:
        """AMEND sets the quantity, DELETE clears the lot."""
        m0 = mark(D0, (leg("a", 10, 1.0), leg("b", 3, 1.0)))
        history = PositionHistory(
            edits=(
                edit(
                    EditKind.AMEND,
                    "a",
                    day=D1,
                    quantity_before=10,
                    quantity_after=12,
                ),
                edit(EditKind.DELETE, "b", day=D1, quantity_before=3),
            ),
            marks=(m0, mark(D1, (leg("a", 12, 1.0),))),
        )
        assert reconcile_book(history, ()) == (
            "live book: lot a — the history implies 12 contracts, 0 are held",
        )

    def test_replace_makes_the_segment_uncheckable(self) -> None:
        """After an import the lots are new; say so instead of guessing."""
        history = PositionHistory(
            edits=(edit(EditKind.REPLACE, None, day=D1),),
            marks=(mark(D0, (leg("a", 10, 1.0),)),),
        )
        findings = reconcile_book(history, ())
        assert findings == (
            (
                "live book: the book was replaced by an import on "
                "2026-11-14, so its lots cannot be checked against the "
                "history until the next mark"
            ),
        )

    def test_no_mark_no_findings(self) -> None:
        """Before the history starts there is nothing to check against."""
        assert reconcile_book(PositionHistory(), ()) == ()
