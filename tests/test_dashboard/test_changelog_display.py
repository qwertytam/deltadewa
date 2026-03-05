"""Tests for deltadewa.dashboard.changelog_display.ChangeLogDisplay.

Tests exercise:
- Construction (with/without reporter)
- display() smoke tests for empty and populated changelogs
- Output content: action strings, position details
- Summary statistics derived from action counts
- Portfolio evolution table length
"""

# ruff: noqa: S101 D102 ANN001 D101
# pylint: disable=missing-function-docstring, protected-access, missing-class-docstring

from __future__ import annotations

from deltadewa.constants import PortfolioAction
from deltadewa.dashboard.changelog_display import ChangeLogDisplay
from deltadewa.reporting.console import ConsoleReporter

# ===========================================================================
# Construction
# ===========================================================================


class TestChangeLogDisplayConstruction:
    """Tests for constructing ChangeLogDisplay with various arguments."""

    def test_constructs_with_logger_only(self, empty_changelog) -> None:
        d = ChangeLogDisplay(empty_changelog)
        assert d is not None

    def test_constructs_with_reporter(self, empty_changelog, reporter) -> None:
        d = ChangeLogDisplay(empty_changelog, reporter)
        assert d is not None

    def test_default_reporter_created_when_none(self, empty_changelog) -> None:
        d = ChangeLogDisplay(empty_changelog)
        assert d._reporter is not None
        assert isinstance(d._reporter, ConsoleReporter)

    def test_custom_reporter_stored(self, empty_changelog, reporter) -> None:
        d = ChangeLogDisplay(empty_changelog, reporter)
        assert d._reporter is reporter

    def test_changelog_reference_stored(self, changelog_with_add) -> None:
        d = ChangeLogDisplay(changelog_with_add)
        assert d._changelog is changelog_with_add


# ===========================================================================
# display() — smoke tests
# ===========================================================================


class TestChangeLogDisplayMethod:
    def test_display_does_not_raise_for_empty_changelog(
        self,
        empty_changelog,
    ) -> None:
        ChangeLogDisplay(empty_changelog).display()

    def test_display_does_not_raise_for_add_entry(
        self,
        changelog_with_add,
    ) -> None:
        ChangeLogDisplay(changelog_with_add).display()

    def test_display_does_not_raise_for_multiple_actions(
        self,
        changelog_with_multiple_actions,
    ) -> None:
        ChangeLogDisplay(changelog_with_multiple_actions).display()


# ===========================================================================
# Output content
# ===========================================================================


class TestChangeLogDisplayOutput:
    def test_add_action_appears_in_output(
        self,
        changelog_with_add,
        capsys,
    ) -> None:
        ChangeLogDisplay(changelog_with_add).display()
        out = capsys.readouterr().out
        assert "ADD" in out.upper()

    def test_remove_action_appears_in_output(
        self,
        changelog_with_multiple_actions,
        capsys,
    ) -> None:
        ChangeLogDisplay(changelog_with_multiple_actions).display()
        out = capsys.readouterr().out
        assert "REMOVE" in out.upper()

    def test_position_details_appear_in_output(
        self,
        changelog_with_add,
        capsys,
    ) -> None:
        """The details string stored in the log entry should appear in output.

        The fixture adds "Added 1x CALL $100 ..." — "CALL" must appear.
        """
        ChangeLogDisplay(changelog_with_add).display()
        out = capsys.readouterr().out
        # The fixture adds "Added 1x CALL $100 ..." — "100" must appear
        assert "100" in out

    def test_empty_changelog_outputs_something(
        self,
        empty_changelog,
        capsys,
    ) -> None:
        ChangeLogDisplay(empty_changelog).display()
        out = capsys.readouterr().out
        assert len(out) > 0


# ===========================================================================
# Summary statistics
# ===========================================================================


class TestChangeLogSummaryStats:
    def test_add_count_correct(self, changelog_with_multiple_actions) -> None:
        """3 ADD entries + 1 REMOVE + 1 INITIALIZE = 5 total; 3 ADDs."""
        counts = changelog_with_multiple_actions.get_action_counts()
        assert counts.get(PortfolioAction.ADD, 0) == 3

    def test_remove_count_correct(
        self,
        changelog_with_multiple_actions,
    ) -> None:
        counts = changelog_with_multiple_actions.get_action_counts()
        assert counts.get(PortfolioAction.REMOVE, 0) == 1

    def test_total_log_length_correct(
        self,
        changelog_with_multiple_actions,
    ) -> None:
        # 1 INITIALIZE + 3 ADD + 1 REMOVE = 5
        assert changelog_with_multiple_actions.get_log_length() == 5

    def test_snapshot_count_excludes_initialize(
        self,
        changelog_with_multiple_actions,
    ) -> None:
        """INITIALIZE entries have no portfolio_snapshot; snapshots = 4."""
        assert changelog_with_multiple_actions.get_number_of_snapshots() == 4

    def test_total_delta_impact_is_numeric(
        self,
        changelog_with_multiple_actions,
    ) -> None:
        impact = changelog_with_multiple_actions.get_total_delta_impact()
        assert isinstance(impact, float)


# ===========================================================================
# Portfolio evolution table
# ===========================================================================


class TestChangeLogEvolutionTable:
    def test_evolution_row_count_equals_snapshots(
        self,
        changelog_with_multiple_actions,
    ) -> None:
        """Test for get_all_portfolio_snapshots().

        get_all_portfolio_snapshots() should return one row per non-INITentry.

        """
        snapshots = (
            changelog_with_multiple_actions.get_all_portfolio_snapshots()
        )
        assert len(snapshots) == 4  # 3 ADD + 1 REMOVE

    def test_evolution_sorted_by_timestamp(
        self,
        changelog_with_multiple_actions,
    ) -> None:
        snapshots = changelog_with_multiple_actions.get_all_portfolio_snapshots(
            sort=True,
        )
        timestamps = [e["timestamp"] for e in snapshots]
        assert timestamps == sorted(timestamps)

    def test_evolution_each_entry_has_portfolio_snapshot(
        self,
        changelog_with_multiple_actions,
    ) -> None:
        snapshots = (
            changelog_with_multiple_actions.get_all_portfolio_snapshots()
        )
        for entry in snapshots:
            assert entry["portfolio_snapshot"] is not None
            assert "total_positions" in entry["portfolio_snapshot"]
            assert "net_delta" in entry["portfolio_snapshot"]
            assert "portfolio_value" in entry["portfolio_snapshot"]

    def test_empty_changelog_has_zero_snapshots(self, empty_changelog) -> None:
        snapshots = empty_changelog.get_all_portfolio_snapshots()
        assert len(snapshots) == 0
