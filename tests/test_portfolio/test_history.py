"""Tests for the position-history records (#313).

Covers each record's validation, the one place cash is derived
(``Fill.cash_flow``), the JSON codec and its refusal of shapes it was not
written for, correction (supersession) rules, and ``mark_book``'s reuse of
the leg-value read every other surface uses.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

import pytest

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.portfolio.history import (
    SCHEMA_VERSION,
    BookEdit,
    CloseReason,
    EditKind,
    FillKind,
    HistorySchemaError,
    MarkBasis,
    PositionHistory,
    mark_book,
    record_from_json,
)
from deltadewa.portfolio.stamps import MarketParameterStamps
from tests.history_builders import at, edit, fill, leg, mark, terms

D1 = date(2026, 11, 7)
D2 = date(2026, 11, 14)


class TestFillValidation:
    """A fill no trade could have produced is refused at construction."""

    def test_close_needs_a_reason(self) -> None:
        """CLOSE without a reason cannot be partitioned into R."""
        with pytest.raises(ValueError, match="needs a reason"):
            fill(FillKind.CLOSE, "a", -1, 10.0, day=D1)

    def test_open_has_no_reason(self) -> None:
        """A reason on an OPEN fill is meaningless and refused."""
        with pytest.raises(ValueError, match="no close reason"):
            fill(
                FillKind.OPEN,
                "a",
                1,
                10.0,
                day=D1,
                reason=CloseReason.ROUTINE,
            )

    def test_settle_is_always_routine(self) -> None:
        """A settlement cannot be recorded as a monetization."""
        with pytest.raises(ValueError, match="always ROUTINE"):
            fill(
                FillKind.SETTLE,
                "a",
                -1,
                0.0,
                day=D1,
                reason=CloseReason.MONETIZATION,
            )

    @pytest.mark.parametrize(
        ("quantity", "price", "fees", "match"),
        [
            (0, 1.0, 0.0, "non-zero"),
            (1, -1.0, 0.0, "price_per_share"),
            (1, 1.0, -0.01, "fees"),
        ],
    )
    def test_impossible_values(
        self,
        quantity: int,
        price: float,
        fees: float,
        match: str,
    ) -> None:
        """Zero quantity, negative price and negative fees are refused."""
        with pytest.raises(ValueError, match=match):
            fill(FillKind.OPEN, "a", quantity, price, day=D1, fees=fees)

    def test_naive_recorded_at_refused(self) -> None:
        """A naive timestamp cannot be ordered against marks."""
        with pytest.raises(ValueError, match="timezone-aware"):
            fill(
                FillKind.OPEN,
                "a",
                1,
                1.0,
                day=D1,
                recorded_at=datetime(2026, 11, 7, 12),
            )

    def test_delete_edit_must_name_its_lot(self) -> None:
        """Only a whole-book REPLACE may omit the lot."""
        with pytest.raises(ValueError, match="must name its lot"):
            edit(EditKind.DELETE, None, day=D1)


class TestCashFlow:
    """``Fill.cash_flow``: ``+`` received, ``-`` paid, fees always cost."""

    def test_buying_pays_premium_plus_fees(self) -> None:
        """OPEN +2 @ 10.00 on 100-share contracts with 5.00 fees pays 2005."""
        assert fill(
            FillKind.OPEN,
            "a",
            2,
            10.0,
            day=D1,
            fees=5.0,
        ).cash_flow() == pytest.approx(-2005.0)

    def test_selling_receives_proceeds_less_fees(self) -> None:
        """CLOSE -2 @ 15.00 with 5.00 fees receives 2995."""
        closed = fill(
            FillKind.CLOSE,
            "a",
            -2,
            15.0,
            day=D1,
            fees=5.0,
            reason=CloseReason.ROUTINE,
        )
        assert closed.cash_flow() == pytest.approx(2995.0)

    def test_short_assignment_pays(self) -> None:
        """Settling a short lot (+1 back to flat) at 20.00 pays 2000."""
        settled = fill(FillKind.SETTLE, "a", 1, 20.0, day=D1)
        assert settled.cash_flow() == pytest.approx(-2000.0)

    def test_worthless_expiry_is_zero_not_none(self) -> None:
        """A recorded zero settlement is a measurement: 0.0."""
        settled = fill(FillKind.SETTLE, "a", -1, 0.0, day=D1)
        assert settled.cash_flow() == pytest.approx(0.0)

    @pytest.mark.parametrize(("price", "fees"), [(None, 0.0), (1.0, None)])
    def test_unknown_is_not_zero(
        self,
        price: float | None,
        fees: float | None,
    ) -> None:
        """An uncaptured price or fee yields no cash figure at all."""
        assert (
            fill(FillKind.OPEN, "a", 1, price, day=D1, fees=fees).cash_flow()
            is None
        )


class TestCodec:
    """Every record round-trips, and unknown shapes are refused."""

    def test_fill_round_trip(self) -> None:
        """A fully populated fill reads back equal."""
        original = fill(
            FillKind.CLOSE,
            "a",
            -3,
            12.5,
            day=D1,
            fees=None,
            reason=CloseReason.MONETIZATION,
            roll_id="r1",
        )
        assert record_from_json(original.to_json()) == original

    def test_edit_round_trip(self) -> None:
        """A book edit reads back equal."""
        original = edit(
            EditKind.AMEND,
            "a",
            day=D1,
            quantity_before=5,
            quantity_after=6,
        )
        assert record_from_json(original.to_json()) == original

    def test_mark_round_trip(self) -> None:
        """A mark with a stamped spot and an expired lot reads back equal."""
        original = mark(
            D1,
            (leg("a", 10, 3.25), leg("b", -2, 0.0, expired_unsettled=True)),
            spot_as_of=at(D1, 9),
            is_opening=True,
        )
        assert record_from_json(original.to_json()) == original

    @pytest.mark.parametrize(
        ("mutate", "match"),
        [
            ({"schema": SCHEMA_VERSION + 1}, "refusing to guess"),
            ({"schema": None}, "refusing to guess"),
            ({"record": "trade"}, "unknown history record type"),
            ({"kind": "EXERCISE"}, "malformed"),
        ],
    )
    def test_refuses_what_it_was_not_written_as(
        self,
        mutate: dict[str, object],
        match: str,
    ) -> None:
        """Version, record type and enum values are checked, not trusted."""
        data = fill(FillKind.OPEN, "a", 1, 1.0, day=D1).to_json() | mutate
        with pytest.raises(HistorySchemaError, match=match):
            record_from_json(data)

    def test_missing_field_is_a_schema_error(self) -> None:
        """A dropped field surfaces as a schema error, not a KeyError."""
        data = fill(FillKind.OPEN, "a", 1, 1.0, day=D1).to_json()
        del data["terms"]
        with pytest.raises(HistorySchemaError, match="malformed"):
            record_from_json(data)

    def test_non_mapping_refused(self) -> None:
        """A JSON array or scalar is not a record."""
        with pytest.raises(HistorySchemaError, match="mapping"):
            record_from_json([1, 2])


class TestSupersession:
    """Corrections replace what was recorded, never what was traded."""

    def test_correction_replaces_the_original(self) -> None:
        """A later fill fixing the fee is the one in force."""
        original = fill(FillKind.OPEN, "a", 1, 10.0, day=D1, fees=None)
        fixed = dataclasses.replace(
            original,
            event_id="fix",
            fees=1.3,
            supersedes=original.event_id,
        )
        history = PositionHistory(recorded_fills=(original, fixed))
        assert history.fills == (fixed,)
        assert history.recorded_fills == (original, fixed)

    def test_a_correction_can_itself_be_corrected(self) -> None:
        """Chains resolve to the last correction."""
        first = fill(FillKind.OPEN, "a", 1, 10.0, day=D1)
        second = dataclasses.replace(
            first,
            event_id="2",
            price_per_share=11.0,
            supersedes=first.event_id,
        )
        third = dataclasses.replace(
            first,
            event_id="3",
            price_per_share=12.0,
            supersedes="2",
        )
        history = PositionHistory(recorded_fills=(first, second, third))
        assert history.fills == (third,)

    def test_unknown_target_refused(self) -> None:
        """A correction of nothing is refused."""
        stray = fill(FillKind.OPEN, "a", 1, 10.0, day=D1, supersedes="nope")
        with pytest.raises(ValueError, match="never recorded"):
            PositionHistory(recorded_fills=(stray,))

    def test_correction_cannot_change_quantity(self) -> None:
        """Changing how much moved is a book change: an AMEND, not a fix."""
        original = fill(FillKind.OPEN, "a", 1, 10.0, day=D1)
        wrong = dataclasses.replace(
            original,
            event_id="x",
            quantity=2,
            supersedes=original.event_id,
        )
        with pytest.raises(ValueError, match="record a book AMEND"):
            PositionHistory(recorded_fills=(original, wrong))

    def test_double_correction_refused(self) -> None:
        """Two corrections of one fill would be ambiguous."""
        original = fill(FillKind.OPEN, "a", 1, 10.0, day=D1)
        one, two = (
            dataclasses.replace(
                original,
                event_id=eid,
                supersedes=original.event_id,
            )
            for eid in ("1", "2")
        )
        with pytest.raises(ValueError, match="more than once"):
            PositionHistory(recorded_fills=(original, one, two))


class TestPositionHistory:
    """Marks are ordered, unique per date, and only the first opens."""

    def test_marks_sorted_and_start_reported(self) -> None:
        """Out-of-order marks are sorted; the first date is the start."""
        history = PositionHistory(marks=(mark(D2), mark(D1, is_opening=True)))
        assert [m.mark_date for m in history.marks] == [D1, D2]
        assert history.history_start == D1
        assert history.opening_mark is history.marks[0]

    def test_empty_history_has_no_start(self) -> None:
        """Nothing recorded means no start date, not a default one."""
        assert PositionHistory().history_start is None

    def test_two_marks_one_date_refused(self) -> None:
        """A boundary is computed once; two for one date is a corruption."""
        with pytest.raises(ValueError, match="share a mark_date"):
            PositionHistory(marks=(mark(D1), mark(D1)))

    def test_opening_mark_must_be_first(self) -> None:
        """Only the earliest mark can start the history."""
        with pytest.raises(ValueError, match="only the earliest"):
            PositionHistory(marks=(mark(D1), mark(D2, is_opening=True)))

    def test_period_membership_is_half_open(self) -> None:
        """A fill on the start date belongs to the prior period."""
        on_start = fill(FillKind.OPEN, "a", 1, 1.0, day=D1)
        on_end = fill(FillKind.OPEN, "b", 1, 1.0, day=D2)
        history = PositionHistory(recorded_fills=(on_start, on_end))
        assert history.fills_between(D1, D2) == (on_end,)

    def test_edit_kinds_cover_the_three_unfilled_changes(self) -> None:
        """AMEND, DELETE and REPLACE are the whole vocabulary."""
        assert {k.value for k in EditKind} == {"AMEND", "DELETE", "REPLACE"}
        assert isinstance(edit(EditKind.REPLACE, None, day=D1), BookEdit)


class TestMarkBook:
    """``mark_book`` prices through the shared leg-value read."""

    @pytest.fixture
    def book(self) -> OptionPortfolio:
        """A pinned two-lot SPX book, one lot already expired."""
        valuation = datetime(2026, 11, 6, tzinfo=UTC)
        portfolio = OptionPortfolio(
            underlying_quantity=2000.0,
            spot_price=5000.0,
            volatility=0.2,
            risk_free_rate=0.04,
            dividend_yield=0.015,
            valuation_date=valuation,
            symbol="SPX",
            default_exercise_style=ExerciseStyle.EUROPEAN,
            contract_size=100,
            stamps=MarketParameterStamps(
                spot_as_of=datetime(2026, 11, 5, 21, tzinfo=UTC),
            ),
        )
        portfolio.add_position(
            strike_price=4200.0,
            maturity_date=datetime(2027, 6, 18, tzinfo=UTC),
            quantity=10,
            option_type=OptionType.PUT,
        )
        portfolio.add_position(
            strike_price=4500.0,
            maturity_date=datetime(2026, 10, 16, tzinfo=UTC),
            quantity=5,
            option_type=OptionType.PUT,
            reject_expired=False,
        )
        return portfolio

    def test_mark_reads_the_book(self, book: OptionPortfolio) -> None:
        """Date, inputs and each lot's value come from the book itself."""
        result = mark_book(
            book,
            marked_at=at(date(2026, 11, 7), 3),
            written_by="weekly_report",
        )
        assert result.mark_date == date(2026, 11, 6)
        assert result.basis is MarkBasis.MODEL
        assert result.spot == pytest.approx(5000.0)
        assert result.spot_as_of == datetime(2026, 11, 5, 21, tzinfo=UTC)
        assert result.portfolio_value == pytest.approx(10_000_000.0)
        assert not result.is_opening
        for lot, position in zip(result.legs, book.positions, strict=True):
            assert lot.position_id == position.position_id
            assert lot.value == pytest.approx(position.position_value())
            assert lot.terms == dataclasses.replace(
                terms(),
                strike=position.option.strike_price,
                expiry=position.option.maturity_date.date(),
            )
        assert result.hedge_value == pytest.approx(book.total_value())

    def test_expired_lot_is_flagged_unsettled(
        self,
        book: OptionPortfolio,
    ) -> None:
        """A lot past expiry still in the book has no settlement yet."""
        result = mark_book(book, marked_at=at(D1), written_by="t")
        assert [lot.expired_unsettled for lot in result.legs] == [False, True]
        assert result.expired_unsettled_legs == (result.legs[1],)
