"""Crash Payoff & Scenario Table display for the options dashboard.

Thin presentation layer over ``analysis.crash_payoff.crash_scenario_table``
— all P&L/ratio logic lives there; this module only formats the table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from IPython.display import display

from deltadewa.analysis.crash_payoff import crash_scenario_table
from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.formatters.dataframes import apply_table_preset

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from deltadewa.analysis.crash_payoff import CrashScenarioRow
    from deltadewa.ips_config import IpsConvexity
    from deltadewa.portfolio.core import OptionPortfolio

_DEFAULT_SHOCKS: tuple[float, ...] = (-10.0, -20.0, -30.0, -40.0)


def _pass_fail_color(val: str) -> str:
    if val == "✓ Pass":
        return f"background-color: {DEFAULT_PALETTE.positive_faded}"
    if val == "✗ Fail":
        return f"background-color: {DEFAULT_PALETTE.negative_faded}"
    return ""


def _highlight_row_factory(
    target_shock: str,
) -> Callable[[pd.Series], list[str]]:
    """Build a Styler row-highlighter for the IPS crash_scenario_pct row.

    Highlights every column of the matching row except "Meets Target",
    which keeps its own pass/fail color from ``_pass_fail_color``.
    """

    def _highlight(row: pd.Series) -> list[str]:
        if row["Shock"] != target_shock:
            return [""] * len(row)
        return [
            (
                ""
                if col == "Meets Target"
                else f"background-color: {DEFAULT_PALETTE.yellow_faded}"
            )
            for col in row.index
        ]

    return _highlight


class CrashPayoffDisplay:
    """Build and display the crash-scenario payoff ladder."""

    def __init__(
        self,
        portfolio: OptionPortfolio,
        ips_convexity: IpsConvexity | None = None,
        shocks: Sequence[float] = _DEFAULT_SHOCKS,
    ) -> None:
        """Initialize with the portfolio and IPS convexity target."""
        self._portfolio = portfolio
        self._ips_convexity = ips_convexity
        self._shocks = shocks

    def display(self) -> None:
        """Print the headline payoff ratio and the styled scenario table."""
        if not self._portfolio.positions:
            print("No positions in portfolio yet.")
            return

        rows = crash_scenario_table(
            self._portfolio,
            shocks=self._shocks,
            ips_convexity=self._ips_convexity,
        )
        self._print_headline(rows)

        target_shock = (
            f"{self._ips_convexity.crash_scenario_pct:+.0f}%"
            if self._ips_convexity is not None
            else None
        )
        df = pd.DataFrame(
            [
                {
                    "Shock": f"{row.shock_pct:+.0f}%",
                    "Hedge P&L": row.hedge_pnl,
                    "Payoff Ratio": row.payoff_ratio,
                    "Convexity": row.convexity_pct,
                    "Meets Target": "✓ Pass" if row.meets_target else "✗ Fail",
                }
                for row in rows
            ],
        )

        styled = df.style.format(
            {
                "Hedge P&L": "${:,.0f}",
                "Payoff Ratio": "{:.2f}x",
                "Convexity": "{:+.1f}%",
            },
        )
        styled = styled.apply(
            lambda col: col.map(_pass_fail_color),
            subset=["Meets Target"],
        )
        if target_shock is not None:
            styled = styled.apply(
                _highlight_row_factory(target_shock),
                axis=1,
            )
        styled = apply_table_preset(styled, preset="fancy")
        styled = styled.hide(axis="index")

        display(styled)

    def _print_headline(self, rows: list[CrashScenarioRow]) -> None:
        if self._ips_convexity is None:
            print(
                "No IPS convexity target configured — showing the raw "
                "scenario ladder only.",
            )
            return

        target_pct = self._ips_convexity.crash_scenario_pct
        headline = next(row for row in rows if row.shock_pct == target_pct)
        verdict = "PASS" if headline.meets_target else "FAIL"
        print(
            f"Headline payoff ratio at {target_pct:+.0f}% shock: "
            f"{headline.payoff_ratio:.2f}x — {verdict} "
            f"(target {self._ips_convexity.target_min_pct:.0f}-"
            f"{self._ips_convexity.target_max_pct:.0f}% convexity, "
            f"actual {headline.convexity_pct:.1f}%)",
        )
