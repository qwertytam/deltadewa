"""
reporting.audit

Module providing audit logging utilities for portfolio operations.

This module defines the PortfolioLogger class, which centralizes audit
and operational logging for portfolio-related activities. PortfolioLogger
encapsulates logging state and logic so the rest of the codebase can
emit structured, consistent audit events without dealing with handler
configuration, formatting, or persistence concerns.

Responsibilities
- Provide a single, configurable entry point for audit events related to
    portfolios (create, update, delete, trade, valuation, etc.).
- Emit structured log records (timestamp, event_type, portfolio_id,
    actor, delta, metadata) suitable for downstream processing or storage.
- Integrate with the standard Python logging framework while allowing
    optional persistent sinks (file, database, HTTP endpoint).
- Offer simple runtime configuration (log level, handlers) and helpers
    for common audit patterns.
- Be safe to use in multi-threaded or async contexts.

Public API (expected)
- class PortfolioLogger(name: str = "portfolio.audit", level: int = logging.INFO, ...)
    - log_event(event_type: str, portfolio_id: str, payload: dict | None =
    None, level: int | None = None, **metadata)
    - set_level(level: int)
    - add_handler(handler)
    - remove_handler(handler)
    - flush()
    - close()
    - get_recent(limit: int = 100) -> list[dict]   # optional in-memory recent events cache

Usage example
>>> from reporting.audit import PortfolioLogger
>>> logger = PortfolioLogger(name="deltadewa.portfolio", level=logging.INFO)
>>> logger.log_event(
...     event_type="portfolio.update",
...     portfolio_id="pf-123",
...     payload={"changed_fields": ["positions", "cash"]},
...     actor="service:rebalance",
...     reason="scheduled rebalance"
... )
"""

from datetime import datetime, timezone

from deltadewa.constants import PortfolioAction
from deltadewa.portfolio.core import OptionPortfolio


class PortfolioLogger:
    """Centralized logger for portfolio audit events."""

    def __init__(
        self,
        name: str = "portfolio.audit",
    ):
        """
        Initialize the PortfolioLogger.

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
                "timestamp": datetime.now(tz=timezone.utc),
                "action": PortfolioAction.INITIALIZE,
                "details": "Portfolio initialized",
                "impact_delta": None,
                "impact_cost": None,
                "position_id": None,
                "portfolio_snapshot": None,
            }
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
        """
        Log a portfolio change for audit trail.

        Args:
            action_type: Type of change (e.g., ADD, REMOVE, UPDATE).
            details: Description of the change
            impact_delta: Change in portfolio delta (optional)
            impact_cost: Cost of transaction (optional)
            position_id: Position identifier (optional)
        """
        entry = {
            "timestamp": datetime.now(tz=timezone.utc),
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
        self, sort: bool = True, key: str = "timestamp"
    ) -> list[dict]:
        """Get a list of all portfolio snapshots from the changelog.

        In pratice this should be all entries exlucding the initial one, but we
        filter for non-None snapshots just in case.

        Args:
            sort: Whether to sort the snapshots by a specific key (default: True)
            key: The key to sort by if sort is True (default: "timestamp")

        Returns:
            A list of changelog entries that include portfolio snapshots, optionally sorted.
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
        self, action_type: PortfolioAction
    ) -> int:
        """Get the number of portfolio snapshots for a specific action type."""
        return sum(
            1
            for entry in self.changelog
            if entry["action"] == action_type
            and entry["portfolio_snapshot"] is not None
        )

    def get_action_counts(
        self, exclude: list[PortfolioAction] | None = None
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
