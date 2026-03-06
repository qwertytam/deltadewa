"""Module providing audit logging utilities for portfolio operations.

This module defines:

- ``PortfolioLogger``       — append-only changelog for portfolio events.
- ``PortfolioChangeTracker`` — stateful diff engine that detects add/remove/
                               update transitions and delegates to a logger.

Public API
----------
PortfolioLogger(name)
    .log_portfolio_change(portfolio, action_type, details, ...)
    .get_all_entries() / .get_last_entry() / ...

PortfolioChangeTracker(portfolio, logger, reporter)
    .reset(portfolio)        — seed / re-seed the baseline snapshot
    .track()                 — diff current state vs last snapshot, log change
    .as_callback()           — return a zero-arg callable for widget wiring
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from datetime import datetime as dt
from typing import TYPE_CHECKING

from deltadewa.constants import PortfolioAction

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio
    from deltadewa.reporting.console import ConsoleReporter


class PortfolioLogger:
    """Centralized logger for portfolio audit events."""

    def __init__(
        self,
        name: str = "portfolio.audit",
    ) -> None:
        """Initialize the PortfolioLogger.

        Args:
            name (str): Logger name (default: "portfolio.audit").

        """
        self.name = name
        self.changelog: list[dict] = []
        self.__initial_changelog_entry()

    def __initial_changelog_entry(self) -> None:
        """Add an initial entry to the changelog for portfolio creation."""
        self.changelog.append(
            {
                "timestamp": dt.now(tz=datetime.UTC),
                "action": PortfolioAction.INITIALIZE,
                "details": "Portfolio initialized",
                "impact_delta": None,
                "impact_cost": None,
                "position_id": None,
                "portfolio_snapshot": None,
            },
        )

    def log_portfolio_change(
        self,
        portfolio: OptionPortfolio,
        action_type: PortfolioAction,
        details: str,
        impact_delta: float | None = None,
        impact_cost: float | None = None,
        position_id: str | None = None,
    ) -> None:
        """Log a portfolio change for audit trail.

        Args:
            portfolio: The portfolio instance after the change.
            action_type: Type of change (e.g., ADD, REMOVE, UPDATE).
            details: Description of the change
            impact_delta: Change in portfolio delta (optional)
            impact_cost: Cost of transaction (optional)
            position_id: Position identifier (optional)

        """
        entry = {
            "timestamp": dt.now(tz=datetime.UTC),
            "action": action_type,
            "details": details,
            "impact_delta": impact_delta,
            "impact_cost": impact_cost,
            "position_id": position_id,
            "portfolio_snapshot": {
                "total_positions": len(portfolio.positions),
                "net_delta": portfolio.net_delta(),
                "portfolio_value": portfolio.total_value(),
            },
        }
        self.changelog.append(entry)

    def get_all_entries(self) -> list[dict]:
        """Get the full changelog."""
        return self.changelog

    def get_all_portfolio_snapshots(
        self,
        sort: bool = True,
        key: str = "timestamp",
    ) -> list[dict]:
        """Get a list of all portfolio snapshots from the changelog.

        In pratice this should be all entries exlucding the initial one, but we
        filter for non-None snapshots just in case.

        Args:
            sort: Whether to sort the snapshots by a specific key (default:
            True)
            key: The key to sort by if sort is True (default: "timestamp")

        Returns:
            A list of changelog entries that include portfolio snapshots,
            optionally sorted.

        """
        snapshots = [
            entry
            for entry in self.changelog
            if entry["portfolio_snapshot"] is not None
        ]
        if sort:
            snapshots.sort(key=lambda x: x[key])
        return snapshots

    def get_last_entry(self) -> dict:
        """Get the most recent log entry."""
        return self.changelog[-1]

    def get_log_length(self) -> int:
        """Get the number of log entries."""
        return len(self.changelog)

    def get_number_of_snapshots(self) -> int:
        """Get the number of portfolio snapshots in the changelog."""
        return sum(
            1
            for entry in self.changelog
            if entry["portfolio_snapshot"] is not None
        )

    def get_number_of_snapshots_by_action(
        self,
        action_type: PortfolioAction,
    ) -> int:
        """Get the number of portfolio snapshots for a specific action type."""
        return sum(
            1
            for entry in self.changelog
            if entry["action"] == action_type
            and entry["portfolio_snapshot"] is not None
        )

    def get_action_counts(
        self,
        exclude: list[PortfolioAction] | None = None,
    ) -> dict[PortfolioAction, int]:
        """Get a count of log entries by action type."""
        counts: dict[PortfolioAction, int] = {}
        for entry in self.changelog:
            action = entry["action"]
            if exclude and action in exclude:
                continue
            counts[action] = counts.get(action, 0) + 1
        return counts

    def get_total_delta_impact(self) -> float:
        """Calculate the total delta impact across all log entries."""
        return sum(
            entry["impact_delta"]
            for entry in self.changelog
            if entry["impact_delta"] is not None
        )


# ---------------------------------------------------------------------------
# PortfolioChangeTracker
# ---------------------------------------------------------------------------


class PortfolioChangeTracker:
    """Stateful diff engine that detects and logs portfolio changes.

    Replaces the ``track_position_change`` function-with-attribute-state
    anti-pattern from the notebook.  Holds a snapshot of the portfolio at the
    last observed state and computes ADD / REMOVE / UPDATE transitions each
    time :meth:`track` is called.

    Parameters
    ----------
    portfolio:
        The live ``OptionPortfolio`` to watch.
    logger:
        ``PortfolioLogger`` instance to receive change entries.
    reporter:
        Optional ``ConsoleReporter`` for inline success messages.
        When ``None`` no console output is produced.

    Example
    -------
    >>> tracker = PortfolioChangeTracker(portfolio, portfolio_changelog,
    reporter)
    >>> position_editor = portfolio_widgets.create_position_editor(
    ...     on_change_callback=tracker.as_callback()
    ... )

    """

    def __init__(
        self,
        portfolio: OptionPortfolio,
        logger: PortfolioLogger,
        reporter: ConsoleReporter | None = None,
    ) -> None:
        """Initialize the PortfolioChangeTracker."""
        self._portfolio = portfolio
        self._logger = logger
        self._reporter = reporter
        self._last_state: dict | None = None
        # Seed baseline from the current portfolio state
        self.reset(portfolio)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self, portfolio: OptionPortfolio | None = None) -> None:
        """Seed (or re-seed) the baseline snapshot.

        Call this after programmatically loading a new portfolio so that the
        next :meth:`track` call does not misclassify all positions as "added".

        Args:
            portfolio: Portfolio to snapshot.  Defaults to the instance's own
                       portfolio when ``None``.

        """
        pf = portfolio if portfolio is not None else self._portfolio
        self._last_state = self._snapshot(pf)

    def track(self) -> None:
        """Diff current portfolio state against the last snapshot and log.

        Infers the action type from the change in position count:

        - count increased  → ``ADD``
        - count decreased  → ``REMOVE``
        - count unchanged  → ``UPDATE``

        Also marks Monte Carlo results stale when they exist.
        """
        pf = self._portfolio
        current = self._snapshot(pf)

        if self._last_state is None:
            # Defensive: should not happen after __init__, but guard anyway
            self._last_state = current
            return

        last = self._last_state

        # --- infer action and build detail string ---
        if current["positions"] > last["positions"]:
            action = PortfolioAction.ADD
            details = self._describe_last_added(pf)
        elif current["positions"] < last["positions"]:
            action = PortfolioAction.REMOVE
            details = f"Removed position (total now: {current['positions']})"
        else:
            action = PortfolioAction.UPDATE
            details = "Updated position"

        delta_change = current["delta"] - last["delta"]
        value_change = current["value"] - last["value"]

        self._logger.log_portfolio_change(
            portfolio=pf,
            action_type=action,
            details=details,
            impact_delta=delta_change,
            impact_cost=value_change,
            position_id=None,
        )

        # Mark Monte Carlo results stale if they exist
        if getattr(pf, "monte_carlo_results", None):
            pf.monte_carlo_stale = True
            pf.monte_carlo_last_modified = dt.now(tz=datetime.UTC)

        # Advance the baseline
        self._last_state = current

        if self._reporter is not None:
            ts = self._logger.get_last_entry()["timestamp"].strftime("%H:%M:%S")
            self._reporter.success(f"Change logged: {action} at {ts}")

    def as_callback(self) -> Callable[[], None]:
        """Return a zero-argument callable that calls :meth:`track`.

        Suitable for passing directly to
        ``PortfolioWidgets.create_position_editor(on_change_callback=...)``.

        Returns
        -------
        Callable[[], None]

        """

        def _callback() -> None:
            self.track()

        return _callback

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _snapshot(portfolio: OptionPortfolio) -> dict:
        """Capture a lightweight state snapshot of *portfolio*."""
        return {
            "positions": len(portfolio.positions),
            "delta": portfolio.total_delta(),
            "value": portfolio.total_value(),
        }

    @staticmethod
    def _describe_last_added(portfolio: OptionPortfolio) -> str:
        """Build a human-readable description of last added position."""
        # This is a bit hacky since it relies on the assumption that the
        # last position in the list is the one just added, but it works for our
        # current use case and keeps the logger decoupled from the portfolio
        # internals.
        # https://github.com/qwertytam/deltadewa/issues/71

        if not portfolio.positions:
            return "Added position"
        pos = portfolio.positions[-1]
        return (
            f"Added {pos.quantity}x "
            f"{pos.option.option_type.upper()} "
            f"${pos.option.strike_price:.0f} "
            f"exp {pos.option.maturity_date.strftime('%Y-%m-%d')}"
            f" {pos.option.exercise_style.capitalize()}"
        )
