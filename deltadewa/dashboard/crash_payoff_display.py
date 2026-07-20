"""Crash Payoff & Scenario Table display for the options dashboard.

Thin presentation layer over ``analysis.crash_payoff.compute_crash_convexity``
— all P&L/ratio logic lives there; this module only formats the table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from IPython.display import display

from deltadewa.analysis.crash_payoff import compute_crash_convexity
from deltadewa.colours import DEFAULT_PALETTE
from deltadewa.formatters.dataframes import apply_table_preset

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from deltadewa.analysis.crash_payoff import (
        CrashConvexityResult,
        CrashScenarioRow,
    )
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


def _print_headline(result: CrashConvexityResult) -> None:
    """Print the payoff-ratio headline for *result*."""
    if result.ips_convexity is None or result.payoff_ratio is None:
        print(
            "No IPS convexity target configured — showing the raw "
            "scenario ladder only.",
        )
        return

    ips = result.ips_convexity
    ips_row = next(
        (
            r
            for r in result.scenario_rows
            if r.shock_pct == ips.crash_scenario_pct
        ),
        None,
    )
    if ips_row is None:
        return
    verdict = "PASS" if ips_row.meets_target else "FAIL"
    basis_note = f" [premium basis: {result.premium_basis}]"
    print(
        f"Headline payoff ratio at "
        f"{ips.crash_scenario_pct:+.0f}% shock: "
        f"{result.payoff_ratio:.2f}x — {verdict} "
        f"(target {ips.target_min_pct:.0f}-"
        f"{ips.target_max_pct:.0f}% convexity, "
        f"actual {ips_row.convexity_pct:.1f}%)"
        f"{basis_note}",
    )


def render_crash_table(result: CrashConvexityResult) -> None:
    """Render the crash payoff scenario table from a pre-computed result.

    Prints the headline payoff-ratio line and displays a styled scenario
    table.  Does not recompute from the portfolio — consumes *result* only.

    Args:
        result: Pre-computed crash convexity result.

    """
    _print_headline(result)

    target_shock = (
        f"{result.ips_convexity.crash_scenario_pct:+.0f}%"
        if result.ips_convexity is not None
        else None
    )
    # Intrinsic floor is a labelled conservative lower bound, surfaced only
    # when the IPS opts in (crash_floor_reported); never the headline.
    floor_on = (
        result.ips_convexity is not None
        and result.ips_convexity.crash_floor_reported
    )
    rows = result.scenario_rows

    def _row_record(row: CrashScenarioRow) -> dict[str, object]:
        record: dict[str, object] = {
            "Shock": f"{row.shock_pct:+.0f}%",
            "Hedge P&L": row.hedge_pnl,
            "Payoff Ratio": row.payoff_ratio,
            "Convexity": row.convexity_pct,
            "Meets Target": "✓ Pass" if row.meets_target else "✗ Fail",
        }
        if floor_on:
            record["Intrinsic Floor"] = row.intrinsic_floor
        return record

    df = pd.DataFrame([_row_record(row) for row in rows])

    styled = df.style.format(
        {
            "Hedge P&L": "${:,.0f}",
            "Payoff Ratio": "{:.2f}x",
            "Convexity": "{:+.1f}%",
        },
    )
    if floor_on:
        styled = styled.format({"Intrinsic Floor": "${:,.0f}"})
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
        self._result: CrashConvexityResult | None = None

    @property
    def result(self) -> CrashConvexityResult | None:
        """Last computed result, or ``None`` before ``display()`` is called."""
        return self._result

    def display(self) -> None:
        """Print the headline payoff ratio and the styled scenario table."""
        if not self._portfolio.positions:
            print("No positions in portfolio yet.")
            return

        result = compute_crash_convexity(
            self._portfolio,
            crash_vol_shock=self._ips_convexity.crash_vol_shock,
            ips_convexity=self._ips_convexity,
            scenario_shocks=self._shocks,
        )
        self._result = result
        render_crash_table(result)
