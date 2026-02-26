"""Portfolio Change Log display for the deltadewa options dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

import deltadewa.constants as const
from deltadewa.reporting import ConsoleReporter

if TYPE_CHECKING:
    from deltadewa.reporting.audit import PortfolioLogger


class ChangeLogDisplay:
    """Build and display change log, summary stats, and portfolio evolution."""

    def __init__(
        self,
        changelog: PortfolioLogger,
        reporter: ConsoleReporter | None = None,
    ) -> None:
        """Initialize with the session's change log and optional reporter."""
        self._changelog = changelog
        self._reporter = reporter or ConsoleReporter()

    def display(self) -> None:
        """Print session change log, summary stats, and portfolio evolution."""
        self._reporter.header("📜 SESSION CHANGE LOG")
        print()

        if not self._changelog or self._changelog.get_number_of_snapshots() == 0:
            self._reporter.warning("No changes recorded in this session.")
            print("\n💡 Changes are tracked when you:")
            print("  • Add/update/remove positions in Section 2")
            print("  • Execute rolls in Section 6")
            print("  • Adjust delta in Section 7")
        else:
            print(
                f"📊 Total changes this session: "
                f"{self._changelog.get_number_of_snapshots()}",
            )
            print()

            # Display changes in chronological order
            print(f"{'Time':<20} {'Action':<15} {'Description':<45} {'Δ Impact':<15}")
            self._reporter.divider()

            for entry in self._changelog.get_all_portfolio_snapshots():
                time_str = entry["timestamp"].strftime("%H:%M:%S")
                action = entry["action"]

                # Truncate long descriptions
                details = entry["details"]
                if len(details) > 42:
                    details = details[:42] + "..."

                # Format delta impact
                if entry["impact_delta"] is not None:
                    delta_str = f"{entry['impact_delta']:+.1f} delta"
                else:
                    delta_str = "—"

                # Color code by action type
                if action in ["ADD", "ROLL"]:
                    symbol = "➕"  # noqa: RUF001
                elif action == "REMOVE":
                    symbol = "➖"  # noqa: RUF001
                elif action == "UPDATE":
                    symbol = "✏️"
                elif action == "REBALANCE":
                    symbol = "⚖️"
                else:
                    symbol = "•"

                print(
                    f"{time_str:<20} {symbol} {action:<13} "
                    f"{details:<45} {delta_str:<15}",
                )

            print()
            self._reporter.divider()

            # Summary statistics
            print("\n📊 SESSION SUMMARY:")

            action_counts = self._changelog.get_action_counts(
                exclude=[const.PortfolioAction.INITIALIZE],
            )
            for action, count in sorted(
                action_counts.items(),
                key=lambda x: x[0].name,
                reverse=False,
            ):
                print(f"  • {action}: {count} change(s)")

            total_delta_impact = self._changelog.get_total_delta_impact()
            print(f"\n  Net Delta Impact: {total_delta_impact:+.1f}")

            # Portfolio evolution
            if self._changelog.get_number_of_snapshots() > 0:
                first_snapshot = self._changelog.get_all_portfolio_snapshots()[0][
                    "portfolio_snapshot"
                ]
                last_snapshot = self._changelog.get_all_portfolio_snapshots()[-1][
                    "portfolio_snapshot"
                ]

                print("\n📈 PORTFOLIO EVOLUTION:")
                print(
                    f"  Position Count: {first_snapshot['total_positions']} → "
                    f"{last_snapshot['total_positions']}",
                )
                print(
                    f"  Net Delta: {first_snapshot['net_delta']:.1f} → "
                    f"{last_snapshot['net_delta']:.1f}",
                )
                print(
                    f"  Portfolio Value: ${first_snapshot['portfolio_value']: ,.2f}"
                    f" → ${last_snapshot['portfolio_value']:,.2f}",
                )

        print()
        print("💾 Changelog will be included in JSON exports below")
        self._reporter.divider()
        print()
