"""Roll Status display for the options dashboard.

Thin presentation layer over ``analysis.roll_status.evaluate_roll_status`` —
all verdict logic lives there; this module only formats the table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deltadewa.analysis.roll_status import RollVerdict, evaluate_roll_status
from deltadewa.reporting import ConsoleReporter

if TYPE_CHECKING:
    from deltadewa.analysis.roll_status import RollStatusRecord
    from deltadewa.ips_config import IpsConfig
    from deltadewa.portfolio.core import OptionPortfolio

_VERDICT_BADGE = {
    RollVerdict.HOLD: "🟢 HOLD",
    RollVerdict.MONITOR: "🟡 MONITOR",
    RollVerdict.REVIEW: "🟠 REVIEW",
    RollVerdict.ROLL: "🔴 ROLL",
}


def _format_otm(otm_pct: float | None) -> str:
    return f"{otm_pct:+.1f}%" if otm_pct is not None else "n/a"


def _format_cost(cost: float | None) -> str:
    return f"${cost:,.2f}" if cost is not None else "n/a"


def _tranche_label(record: RollStatusRecord) -> str:
    option = record.position.option
    return (
        f"{option.option_type.upper()} ${option.strike_price:.0f} "
        f"x{record.position.quantity}"
    )


class RollStatusDisplay:
    """Build and display per-tranche roll status using IPS thresholds."""

    def __init__(
        self,
        portfolio: OptionPortfolio,
        ips_config: IpsConfig,
        reporter: ConsoleReporter | None = None,
    ) -> None:
        """Initialize with the portfolio/IPS policy to evaluate."""
        self.portfolio = portfolio
        self.ips_config = ips_config
        self._reporter = reporter or ConsoleReporter()

    def display(self, current_spot: float | None = None) -> None:
        """Print the roll status table.

        Columns: tranche, entry %OTM, current %OTM, days to maturity /
        roll window, crash convexity vs target, verdict, est. roll-up cost.

        Args:
            current_spot: Spot price to evaluate against. Defaults to
                ``self.portfolio.spot_price``.

        """
        print()
        self._reporter.header("🔄 ROLL STATUS")
        print()

        if not self.portfolio.positions:
            print("No positions in portfolio yet.")
            return

        records = evaluate_roll_status(
            self.portfolio,
            self.ips_config,
            current_spot,
        )

        for record in records:
            badge = _VERDICT_BADGE[record.verdict]
            tranche = _tranche_label(record)
            entry_otm = _format_otm(record.moneyness.entry_otm_pct)
            current_otm = _format_otm(record.moneyness.current_otm_pct)
            cost = _format_cost(record.estimated_roll_up_cost)

            print(
                f"  {tranche: <16} | {badge: <12} | "
                f"OTM entry/now: {entry_otm:>7} / {current_otm:>7} | "
                f"{record.days_to_maturity:>4}d "
                f"(window {record.roll_window_days}d) | "
                f"convexity {record.crash_convexity_pct:.1f}% "
                f"(target {record.convexity_target_min_pct:.0f}-"
                f"{record.convexity_target_max_pct:.0f}%) | "
                f"roll-up cost: {cost}",
            )

        print()
        self._reporter.divider()
