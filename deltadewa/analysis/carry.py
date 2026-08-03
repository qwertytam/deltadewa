"""Carry and theta analysis mixin for portfolio analysis."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pandas as pd

from deltadewa import constants as const
from deltadewa.utils import abs_sum

if TYPE_CHECKING:
    from deltadewa.analysis._protocols import _AnalyzerProtocol


@dataclass(frozen=True)
class CarryBudgetStatus:
    """Carry cost measured against the IPS annual budget.

    Attributes:
        carry_pct_of_notional: ``abs(theta_annual) / book_notional`` as a
            percentage.
        within_budget: True when ``carry_pct_of_notional <=
            budget_annual_pct``.

    """

    carry_pct_of_notional: float
    within_budget: bool


def carry_vs_budget(
    *,
    theta_annual: float,
    book_notional: float,
    budget_annual_pct: float,
) -> CarryBudgetStatus:
    """Carry cost as a % of notional, compared against the IPS budget.

    Args:
        theta_annual: Net annual theta in dollars (sign-agnostic; ``abs`` is
            taken internally since carry cost is reported as a magnitude).
        book_notional: Protected book notional in dollars.
        budget_annual_pct: IPS carry budget, in percent of notional.

    Returns:
        The carry-vs-budget comparison. ``carry_pct_of_notional`` is
        ``0.0`` when ``book_notional <= 0`` (undefined ratio, not an
        error).

    """
    carry_pct = (
        abs(theta_annual) / book_notional * 100 if book_notional > 0 else 0.0
    )
    return CarryBudgetStatus(
        carry_pct_of_notional=carry_pct,
        within_budget=carry_pct <= budget_annual_pct,
    )


class CarryMixin:
    """Mixin for theta and carry analysis.

    Provides methods for analyzing portfolio carry (theta decay)
    characteristics and creating theta summary tables.
    """

    if TYPE_CHECKING:
        _self: "_AnalyzerProtocol"

    def calculate_carry_metrics(
        self: "_AnalyzerProtocol",
    ) -> dict[str, Any]:
        """Analyze portfolio carry (theta decay) characteristics.

        Note: All theta calculations use the industry standard convention of
        365 calendar days (not 252 trading days). This matches:
        - Option pricing model assumptions (Black-Scholes, Bjerksund-Stensland)
        - VIX and exchange conventions
        - Volatility calculations which use calendar time in T

        Returns:
            dict containing:
                - total_theta_daily: Daily theta across all positions
                - total_theta_weekly: Weekly theta (daily * 7 calendar days)
                - total_theta_monthly: Monthly theta (daily * 30 calendar days)
                - total_theta_annual: Annual theta (daily * 365 calendar days)
                - theta_by_bucket: dict of theta totals per maturity bucket
                - theta_by_type: dict of theta totals by option type
                - covered_call_theta: Theta from short calls (income)
                - long_call_theta: Theta from long calls (cost)
                - hedge_put_theta: Theta cost from long puts (protection)
                - short_put_theta: Theta from short puts (income)
                - net_carry: Net daily carry (equals total_theta_daily)
                - carry_efficiency: Theta / position value ratio by bucket

        """
        df = self.portfolio.to_dataframe()
        if df.empty:
            return self._empty_carry_metrics()

        df = self.add_maturity_buckets(df)

        # Total theta metrics
        total_theta_daily = df["position_theta"].sum()

        # Theta by bucket
        theta_by_bucket = (
            df.groupby("maturity_bucket")["position_theta"].sum().to_dict()
        )

        # Theta by type
        theta_by_type = (
            df.groupby("option_type")["position_theta"].sum().to_dict()
        )

        # Covered call analysis (short calls - earning premium)
        short_calls = df[
            (df["option_type"] == const.OptionType.CALL) & (df["quantity"] < 0)
        ]
        covered_call_theta = (
            short_calls["position_theta"].sum() if len(short_calls) > 0 else 0.0
        )
        covered_call_premium = (
            short_calls["position_value"].sum() if len(short_calls) > 0 else 0.0
        )

        # Long call analysis (paying premium)
        long_calls = df[
            (df["option_type"] == const.OptionType.CALL) & (df["quantity"] > 0)
        ]
        long_call_theta = (
            long_calls["position_theta"].sum() if len(long_calls) > 0 else 0.0
        )

        # Hedge put analysis (long puts - paying for downside protection)
        long_puts = df[
            (df["option_type"] == const.OptionType.PUT) & (df["quantity"] > 0)
        ]
        hedge_put_theta = (
            long_puts["position_theta"].sum() if len(long_puts) > 0 else 0.0
        )
        hedge_put_delta = (
            long_puts["position_delta"].sum() if len(long_puts) > 0 else 0.0
        )

        # Short put analysis (short puts - earning premium)
        short_puts = df[
            (df["option_type"] == const.OptionType.PUT) & (df["quantity"] < 0)
        ]
        short_put_theta = (
            short_puts["position_theta"].sum() if len(short_puts) > 0 else 0.0
        )

        # Net carry = total theta (they are identical for options portfolios)
        net_carry = total_theta_daily

        # Carry efficiency by bucket (annualized theta / position value)
        bucket_summary = df.groupby("maturity_bucket").agg(
            {
                "position_theta": "sum",
                "position_value": abs_sum,
            },
        )
        bucket_summary["carry_efficiency_pct"] = (
            (
                bucket_summary["position_theta"]
                / bucket_summary["position_value"]
            )
            * 100
            * const.DAYS_PER_YEAR
        )
        carry_efficiency = bucket_summary["carry_efficiency_pct"].to_dict()

        return {
            "total_theta_daily": total_theta_daily,
            "total_theta_weekly": total_theta_daily * const.DAYS_PER_WEEK,
            "total_theta_monthly": total_theta_daily
            * const.CALENDAR_DAYS_PER_MONTH,
            "total_theta_annual": total_theta_daily * const.DAYS_PER_YEAR,
            "theta_by_bucket": theta_by_bucket,
            "theta_by_type": theta_by_type,
            "covered_call_theta": covered_call_theta,
            "covered_call_premium": covered_call_premium,
            "long_call_theta": long_call_theta,
            "hedge_put_theta": hedge_put_theta,
            "hedge_put_delta": hedge_put_delta,
            "short_put_theta": short_put_theta,
            "net_carry": net_carry,
            "carry_efficiency": carry_efficiency,
            "is_positive_carry": net_carry > 0,
        }

    def _empty_carry_metrics(self) -> dict[str, Any]:
        """Return empty carry metrics structure."""
        return {
            "total_theta_daily": 0.0,
            "total_theta_weekly": 0.0,
            "total_theta_monthly": 0.0,
            "total_theta_annual": 0.0,
            "theta_by_bucket": {},
            "theta_by_type": {},
            "covered_call_theta": 0.0,
            "covered_call_premium": 0.0,
            "long_call_theta": 0.0,
            "hedge_put_theta": 0.0,
            "hedge_put_delta": 0.0,
            "short_put_theta": 0.0,
            "net_carry": 0.0,
            "carry_efficiency": {},
            "is_positive_carry": False,
        }

    def create_theta_summary_table(
        self: "_AnalyzerProtocol",
    ) -> pd.DataFrame:
        """Create consolidated theta/carry summary table.

        Returns a DataFrame showing theta breakdown by source (income/cost) and
        timeframe (daily, weekly, monthly, annual). This provides a clear view
        of where theta is coming from and going to in the portfolio.

        Returns:
            DataFrame with theta breakdown by source (income/cost) and
            timeframe with multi-index (category, source) and columns for
            different time periods

        """
        carry_metrics = self.calculate_carry_metrics()

        data = []

        # Income sources (positive theta - earning premium)
        if carry_metrics["covered_call_theta"] != 0:
            data.append(
                {
                    "category": "Income",
                    "source": "Short Calls",
                    "daily": carry_metrics["covered_call_theta"],
                    "weekly": carry_metrics["covered_call_theta"]
                    * const.DAYS_PER_WEEK,
                    "monthly": carry_metrics["covered_call_theta"]
                    * const.CALENDAR_DAYS_PER_MONTH,
                    "annual": carry_metrics["covered_call_theta"]
                    * const.DAYS_PER_YEAR,
                },
            )

        if carry_metrics["short_put_theta"] != 0:
            data.append(
                {
                    "category": "Income",
                    "source": "Short Puts",
                    "daily": carry_metrics["short_put_theta"],
                    "weekly": carry_metrics["short_put_theta"]
                    * const.DAYS_PER_WEEK,
                    "monthly": carry_metrics["short_put_theta"]
                    * const.CALENDAR_DAYS_PER_MONTH,
                    "annual": carry_metrics["short_put_theta"]
                    * const.DAYS_PER_YEAR,
                },
            )

        # Cost sources (negative theta - paying premium)
        if carry_metrics["hedge_put_theta"] != 0:
            data.append(
                {
                    "category": "Cost",
                    "source": "Long Puts (Hedge)",
                    "daily": carry_metrics["hedge_put_theta"],
                    "weekly": carry_metrics["hedge_put_theta"]
                    * const.DAYS_PER_WEEK,
                    "monthly": carry_metrics["hedge_put_theta"]
                    * const.CALENDAR_DAYS_PER_MONTH,
                    "annual": carry_metrics["hedge_put_theta"]
                    * const.DAYS_PER_YEAR,
                },
            )

        if carry_metrics["long_call_theta"] != 0:
            data.append(
                {
                    "category": "Cost",
                    "source": "Long Calls",
                    "daily": carry_metrics["long_call_theta"],
                    "weekly": carry_metrics["long_call_theta"]
                    * const.DAYS_PER_WEEK,
                    "monthly": carry_metrics["long_call_theta"]
                    * const.CALENDAR_DAYS_PER_MONTH,
                    "annual": carry_metrics["long_call_theta"]
                    * const.DAYS_PER_YEAR,
                },
            )

        # Net total (always show, even if zero)
        data.append(
            {
                "category": "NET",
                "source": "Total Theta/Carry",
                "daily": carry_metrics["total_theta_daily"],
                "weekly": carry_metrics["total_theta_weekly"],
                "monthly": carry_metrics["total_theta_monthly"],
                "annual": carry_metrics["total_theta_annual"],
            },
        )

        df = pd.DataFrame(data)
        return df.set_index(["category", "source"])
