"""Realized carry flags an option whose IV changed source (9b, D11).

When the feed fails, or comes back, an option is re-priced with no trade, and
the identity ``V0 + P - R - V1`` books that re-pricing as carry. Each mark
records where every option's IV came from; a period whose two marks disagree
on whether it was the feed's number or a typed one names the option and says
part of the figure is a re-pricing. The figure is still printed.
"""

from __future__ import annotations

from datetime import date

import pytest

from deltadewa.analysis.realized_carry import realized_carry, since_inception
from deltadewa.portfolio.history import LegMark, PositionHistory
from tests.history_builders import leg, mark

D0 = date(2026, 11, 7)
D1 = date(2026, 11, 14)
D2 = date(2026, 11, 21)


def _breaks(start_origin: str, end_origin: str) -> tuple[str, ...]:
    start = mark(D0, (leg("a", 10, 10.0, origin=start_origin),))
    end = mark(D1, (leg("a", 10, 8.0, origin=end_origin),))
    return realized_carry(PositionHistory(), start=start, end=end).breaks


class TestOriginFlag:
    """Compared by basis class: the feed's number, or a typed one."""

    def test_feed_to_typed_is_flagged(self) -> None:
        reasons = _breaks("FETCHED", "FALLBACK")

        assert len(reasons) == 1
        assert "IV changed source" in reasons[0]
        assert "re-pricing, not carry" in reasons[0]
        assert "FETCHED" in reasons[0]
        assert "FALLBACK" in reasons[0]

    def test_typed_to_feed_is_flagged(self) -> None:
        """The first week after adoption: every earlier mark was typed."""
        assert len(_breaks("ENTERED", "FETCHED")) == 1

    def test_fetched_to_last_good_is_not_flagged(self) -> None:
        """The same chain on another night is market movement, not a basis."""
        assert _breaks("FETCHED", "LAST_GOOD") == ()

    def test_override_to_fallback_is_not_flagged(self) -> None:
        """Both are your typed value."""
        assert _breaks("OVERRIDE", "FALLBACK") == ()
        assert _breaks("ENTERED", "OVERRIDE") == ()

    def test_unchanged_origin_is_clean(self) -> None:
        assert _breaks("FETCHED", "FETCHED") == ()
        assert _breaks("ENTERED", "ENTERED") == ()

    def test_the_figure_is_still_computed(self) -> None:
        start = mark(D0, (leg("a", 10, 10.0, origin="ENTERED"),))
        end = mark(D1, (leg("a", 10, 8.0, origin="FETCHED"),))

        result = realized_carry(PositionHistory(), start=start, end=end)

        assert result.gross == pytest.approx(2_000.0)
        assert not result.reconcilable

    def test_a_lot_opened_in_the_period_is_a_trade_not_a_flag(self) -> None:
        start = mark(D0, (leg("a", 10, 10.0, origin="ENTERED"),))
        end = mark(
            D1,
            (
                leg("a", 10, 8.0, origin="ENTERED"),
                leg("b", 5, 6.0, origin="FETCHED"),
            ),
        )

        result = realized_carry(PositionHistory(), start=start, end=end)

        assert not any("IV changed source" in b for b in result.breaks)

    def test_each_changed_option_is_named_once(self) -> None:
        start = mark(
            D0,
            (
                leg("a", 10, 10.0, origin="ENTERED"),
                leg("b", 10, 9.0, origin="ENTERED"),
            ),
        )
        end = mark(
            D1,
            (
                leg("a", 10, 8.0, origin="FETCHED"),
                leg("b", 10, 7.0, origin="ENTERED"),
            ),
        )

        result = realized_carry(PositionHistory(), start=start, end=end)

        flagged = [b for b in result.breaks if "IV changed source" in b]
        assert len(flagged) == 1

    def test_since_inception_flags_the_switch_week_and_keeps_it(self) -> None:
        marks = (
            mark(D0, (leg("a", 10, 10.0, origin="ENTERED"),), is_opening=True),
            mark(D1, (leg("a", 10, 8.0, origin="ENTERED"),)),
            mark(D2, (leg("a", 10, 6.0, origin="FETCHED"),)),
        )
        history = PositionHistory(marks=marks)

        inception = since_inception(history)

        assert inception is not None
        assert sum("IV changed source" in b for b in inception.breaks) == 1


class TestTheRecordRoundTrips:
    """The origin is stored on the mark; older marks read as typed."""

    def test_a_leg_mark_carries_its_origin(self) -> None:
        original = leg("a", 10, 10.0, origin="LAST_GOOD")

        restored = LegMark.from_json(original.to_json())

        assert restored == original
        assert restored.volatility_origin == "LAST_GOOD"

    def test_a_mark_written_before_the_feed_reads_as_entered(self) -> None:
        data = leg("a", 10, 10.0).to_json()
        del data["volatility_origin"]

        assert LegMark.from_json(data).volatility_origin == "ENTERED"
