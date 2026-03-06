"""Position Aging & Expiration Calendar display for the options dashboard."""

from __future__ import annotations

import datetime
from datetime import datetime as dt
from typing import TYPE_CHECKING

import pandas as pd

from deltadewa.reporting import ConsoleReporter

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio

_URGENCY_ORDER = [
    "🔴 URGENT (<7d)",
    "🟠 SOON (<14d)",
    "🟡 APPROACHING (<21d)",
    "🟢 NORMAL (<45d)",
    "⚪ LONG-TERM (45d+)",
]


def _get_urgency_category(days: int) -> str:
    if days < 7:
        return _URGENCY_ORDER[0]
    elif days < 14:
        return _URGENCY_ORDER[1]
    elif days < 21:
        return _URGENCY_ORDER[2]
    elif days < 45:
        return _URGENCY_ORDER[3]

    return _URGENCY_ORDER[4]


class PositionAgingDisplay:
    """Build and display the position aging insights and expiration calendar."""

    def __init__(
        self,
        portfolio: OptionPortfolio,
        reporter: ConsoleReporter | None = None,
    ) -> None:
        """Initialize with the portfolio to analyze and an optional reporter."""
        self.portfolio = portfolio
        self._reporter = reporter or ConsoleReporter()

    def display(self, today: dt | None = None) -> None:
        """Print the expiration calendar and aging insights.

        Args:
            today: Override the current date for testing (defaults to today).

        """
        # Position Aging & Expiration Calendar

        if today is None:
            today = dt.now(tz=datetime.UTC)

        print()
        self._reporter.header("📅 POSITION AGING & EXPIRATION CALENDAR")
        print()

        # Group positions by expiration urgency
        df_positions = self.portfolio.to_dataframe()

        if not df_positions.empty:
            # Add days to expiry
            df_positions["maturity"] = pd.to_datetime(
                df_positions["maturity"],
                utc=True,
            )

            # vectorized days to expiry as integer days
            df_positions["days_to_expiry"] = (
                df_positions["maturity"] - today
            ).dt.days

            df_positions["urgency"] = df_positions.sort_values(
                "days_to_expiry",
            )["days_to_expiry"].apply(_get_urgency_category)

            # Group and display
            _urgency_groups = df_positions.sort_values(
                ["urgency", "days_to_expiry"],
            ).reset_index(drop=True)

            # Display by urgency category
            for category in [
                "🔴 URGENT (<7d)",
                "🟠 SOON (<14d)",
                "🟡 APPROACHING (<21d)",
                "🟢 NORMAL (<45d)",
                "⚪ LONG-TERM (45d+)",
            ]:
                positions_in_category = df_positions[
                    df_positions["urgency"] == category
                ]

                if len(positions_in_category) > 0:
                    print(
                        f"\n{category}:  "
                        f"{len(positions_in_category)} position(s)",
                    )
                    self._reporter.divider()

                    for _, pos in positions_in_category.iterrows():
                        days_left = pos["days_to_expiry"]
                        expiry_date = pos["maturity"]

                        # Format display
                        opt_type = pos["option_type"].upper()
                        strike = pos["strike"]
                        qty = pos["quantity"]
                        delta = pos["position_delta"]
                        theta = pos["position_theta"]

                        print(
                            f"  {opt_type: <4} "
                            f"${strike:>6.0f} x{qty:>4.0f}  |  "
                            f"Expires: {expiry_date} ({days_left}d)  |  "
                            f"Δ={delta: >7.1f}  θ=${theta:>6.2f}/day",
                        )

                        # Add action recommendation for urgent items
                        if days_left < 7:
                            print(
                                "       → ACTION:  Roll this position in "
                                "Section 6 or close",
                            )
                        elif days_left < 14:
                            print(
                                "       → PLAN:  Start evaluating roll"
                                " opportunities",
                            )

            print()
            self._reporter.divider()
            print("💡 AGING INSIGHTS:")

            # Calculate aggregate theta by expiration bucket
            urgent_theta = df_positions[df_positions["days_to_expiry"] < 7][
                "position_theta"
            ].sum()
            soon_theta = df_positions[
                (df_positions["days_to_expiry"] >= 7)
                & (df_positions["days_to_expiry"] < 21)
            ]["position_theta"].sum()

            print(
                f"  • Urgent positions (<7d): Burning $"
                f"{abs(urgent_theta):.2f}/day",
            )
            print(
                f"  • Near-term positions (7-21d): Burning $"
                f"{abs(soon_theta):.2f}/day",
            )
            print("  • Recommendation: Focus rolls on urgent positions first")
            self._reporter.divider()

        else:
            print("No positions in portfolio yet.")
