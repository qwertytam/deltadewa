"""Tests for deltadewa.reporting.audit — PortfolioChangeTracker."""

from datetime import UTC, datetime, timedelta

from deltadewa.constants import ExerciseStyle, OptionType, PortfolioAction
from deltadewa.portfolio.core import OptionPortfolio
from deltadewa.reporting.audit import PortfolioChangeTracker, PortfolioLogger

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_portfolio() -> OptionPortfolio:
    return OptionPortfolio(
        spot_price=100.0,
        volatility=0.2,
        risk_free_rate=0.05,
        dividend_yield=0.0,
        default_exercise_style=ExerciseStyle.AMERICAN,
    )


def _maturity(days: int = 30) -> datetime:
    return datetime.now(tz=UTC) + timedelta(days=days)


# ---------------------------------------------------------------------------
# _snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    """Unit tests for PortfolioChangeTracker._snapshot."""

    def test_snapshot_has_position_ids_and_id_to_desc(self) -> None:
        """_snapshot includes position_ids (set) and id_to_desc (dict)."""
        pf = _make_portfolio()
        pos = pf.add_position(
            strike_price=100.0,
            maturity_date=_maturity(),
            quantity=1,
            option_type=OptionType.CALL,
        )
        snap = PortfolioChangeTracker._snapshot(pf)

        assert "position_ids" in snap
        assert "id_to_desc" in snap
        assert pos.position_id in snap["position_ids"]
        assert pos.position_id in snap["id_to_desc"]

    def test_snapshot_empty_portfolio(self) -> None:
        """_snapshot on an empty portfolio has empty sets/dicts."""
        pf = _make_portfolio()
        snap = PortfolioChangeTracker._snapshot(pf)

        assert snap["position_ids"] == set()
        assert snap["id_to_desc"] == {}
        assert snap["positions"] == 0


# ---------------------------------------------------------------------------
# track() — ADD
# ---------------------------------------------------------------------------


class TestTrackAdd:
    """track() correctly logs ADD events with real position_ids."""

    def test_single_add_logs_correct_position_id(self) -> None:
        """Adding one position → one ADD entry with the position's id."""
        pf = _make_portfolio()
        logger = PortfolioLogger()
        tracker = PortfolioChangeTracker(pf, logger)

        pos = pf.add_position(
            strike_price=100.0,
            maturity_date=_maturity(),
            quantity=2,
            option_type=OptionType.PUT,
        )
        tracker.track()

        entry = logger.get_last_entry()
        assert entry["action"] == PortfolioAction.ADD
        assert entry["position_id"] == pos.position_id
        assert entry["position_id"] is not None

    def test_single_add_details_describe_position(self) -> None:
        """ADD entry details mention the strike and quantity."""
        pf = _make_portfolio()
        logger = PortfolioLogger()
        tracker = PortfolioChangeTracker(pf, logger)

        pf.add_position(
            strike_price=105.0,
            maturity_date=_maturity(),
            quantity=3,
            option_type=OptionType.CALL,
        )
        tracker.track()

        details = logger.get_last_entry()["details"]
        assert "105" in details
        assert "3x" in details

    def test_bulk_add_logs_one_entry_per_position(self) -> None:
        """Adding two positions before a single track() → two ADD entries."""
        pf = _make_portfolio()
        logger = PortfolioLogger()
        tracker = PortfolioChangeTracker(pf, logger)

        pos_a = pf.add_position(
            strike_price=100.0,
            maturity_date=_maturity(30),
            quantity=1,
            option_type=OptionType.CALL,
        )
        pos_b = pf.add_position(
            strike_price=110.0,
            maturity_date=_maturity(60),
            quantity=2,
            option_type=OptionType.PUT,
        )
        tracker.track()  # called once after both adds

        add_entries = [
            e
            for e in logger.get_all_entries()
            if e["action"] == PortfolioAction.ADD
        ]
        assert len(add_entries) == 2

        logged_ids = {e["position_id"] for e in add_entries}
        assert pos_a.position_id in logged_ids
        assert pos_b.position_id in logged_ids

    def test_bulk_add_position_ids_are_not_none(self) -> None:
        """Every ADD entry from a bulk track() has a non-None position_id."""
        pf = _make_portfolio()
        logger = PortfolioLogger()
        tracker = PortfolioChangeTracker(pf, logger)

        pf.add_position(100.0, _maturity(30), 1, OptionType.CALL)
        pf.add_position(105.0, _maturity(60), 1, OptionType.PUT)
        tracker.track()

        for entry in logger.get_all_entries():
            if entry["action"] == PortfolioAction.ADD:
                assert entry["position_id"] is not None


# ---------------------------------------------------------------------------
# track() — REMOVE
# ---------------------------------------------------------------------------


class TestTrackRemove:
    """track() correctly logs REMOVE events with real position_ids."""

    def test_remove_logs_correct_position_id(self) -> None:
        """Removing a position → REMOVE entry carries the original id."""
        pf = _make_portfolio()
        logger = PortfolioLogger()
        tracker = PortfolioChangeTracker(pf, logger)

        pos = pf.add_position(
            strike_price=100.0,
            maturity_date=_maturity(),
            quantity=1,
            option_type=OptionType.CALL,
        )
        tracker.track()  # baseline: one position present

        original_id = pos.position_id
        pf.remove_position(0)
        tracker.track()  # should log REMOVE

        remove_entries = [
            e
            for e in logger.get_all_entries()
            if e["action"] == PortfolioAction.REMOVE
        ]
        assert len(remove_entries) == 1
        assert remove_entries[0]["position_id"] == original_id

    def test_remove_entry_position_id_not_none(self) -> None:
        """REMOVE entry has a non-None position_id."""
        pf = _make_portfolio()
        logger = PortfolioLogger()
        tracker = PortfolioChangeTracker(pf, logger)

        pf.add_position(100.0, _maturity(), 1, OptionType.PUT)
        tracker.track()
        pf.remove_position(0)
        tracker.track()

        remove_entry = next(
            e
            for e in logger.get_all_entries()
            if e["action"] == PortfolioAction.REMOVE
        )
        assert remove_entry["position_id"] is not None

    def test_remove_details_describe_original_position(self) -> None:
        """REMOVE entry details survive after the position is gone."""
        pf = _make_portfolio()
        logger = PortfolioLogger()
        tracker = PortfolioChangeTracker(pf, logger)

        pf.add_position(
            strike_price=95.0,
            maturity_date=_maturity(),
            quantity=4,
            option_type=OptionType.PUT,
        )
        tracker.track()
        pf.remove_position(0)
        tracker.track()

        remove_entry = next(
            e
            for e in logger.get_all_entries()
            if e["action"] == PortfolioAction.REMOVE
        )
        assert "95" in remove_entry["details"]
        assert "4x" in remove_entry["details"]


# ---------------------------------------------------------------------------
# track() — UPDATE
# ---------------------------------------------------------------------------


class TestTrackUpdate:
    """track() correctly logs UPDATE events."""

    def test_update_logs_update_action(self) -> None:
        """Updating a position (count unchanged) → UPDATE entry."""
        pf = _make_portfolio()
        logger = PortfolioLogger()
        tracker = PortfolioChangeTracker(pf, logger)

        pf.add_position(100.0, _maturity(), 1, OptionType.CALL)
        tracker.track()

        pf.update_position(0, quantity=5)
        tracker.track()

        update_entries = [
            e
            for e in logger.get_all_entries()
            if e["action"] == PortfolioAction.UPDATE
        ]
        assert len(update_entries) == 1

    def test_no_spurious_add_remove_on_update(self) -> None:
        """Updating a position must not produce extra ADD or any REMOVE."""
        pf = _make_portfolio()
        logger = PortfolioLogger()
        tracker = PortfolioChangeTracker(pf, logger)

        pf.add_position(100.0, _maturity(), 1, OptionType.CALL)
        tracker.track()  # one ADD

        pf.update_position(0, quantity=5)
        tracker.track()  # must log UPDATE, not a second ADD or any REMOVE

        counts = logger.get_action_counts()
        assert counts.get(PortfolioAction.ADD, 0) == 1
        assert counts.get(PortfolioAction.REMOVE, 0) == 0
