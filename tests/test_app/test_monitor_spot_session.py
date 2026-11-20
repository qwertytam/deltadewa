"""/monitor's spot cross-check compares only same-session figures (9b, D6).

A fetched book spot is struck at its own session's close. The observed
figure is the index history's close, which after hours is one session behind
it, so comparing across sessions would report a one-day move as a
divergence. A typed spot is compared as it always was.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from deltadewa.analysis.market_environment import DataQuality
from deltadewa.analysis.spot_reading import SpotReading
from deltadewa.app.pages.monitor import _spot_headline
from tests.test_app.test_design import _collect_text

_FRIDAY = datetime(2026, 11, 13, tzinfo=UTC)


def _reading(*, book: float = 5000.0, observed: float = 4900.0) -> SpotReading:
    return SpotReading(
        book_spot=book,
        observed_spot=observed,
        quality=DataQuality.CACHED,
        as_of=_FRIDAY,
        fetched_at=_FRIDAY,
    )


class TestSessions:
    def test_a_fed_spot_from_another_session_is_not_compared(self) -> None:
        headline = _spot_headline(
            _reading(),
            "SPX",
            2.0,
            fed_session=date(2026, 11, 16),
        )

        text = _collect_text(headline)

        assert "Not compared" in text
        assert "2026-11-13 close" in text
        assert "2026-11-16 close" in text
        assert "vs book" not in text
        assert "diverged" not in str(headline)

    def test_a_fed_spot_from_the_same_session_is_compared(self) -> None:
        headline = _spot_headline(
            _reading(),
            "SPX",
            2.0,
            fed_session=date(2026, 11, 13),
        )

        text = _collect_text(headline)

        assert "Not compared" not in text
        assert "vs book" in text
        assert "spot-crosscheck--diverged" in str(headline)

    def test_the_book_line_says_where_a_fed_spot_came_from(self) -> None:
        headline = _spot_headline(
            _reading(),
            "SPX",
            2.0,
            fed_session=date(2026, 11, 13),
        )

        assert "fetched from the 2026-11-13 close" in _collect_text(headline)

    def test_a_typed_spot_is_compared_as_before(self) -> None:
        headline = _spot_headline(_reading(), "SPX", 2.0)

        text = _collect_text(headline)

        assert "Not compared" not in text
        assert "vs book" in text
        assert "hand-entered reference point" in text
