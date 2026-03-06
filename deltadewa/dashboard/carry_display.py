"""Carry / Theta-decay display module for the deltadewa options dashboard.

Encapsulates the ~100-line Theta Decay & Carry Analysis section of
``options_dashboard.ipynb`` (MODE 2 cells) into a single callable class.

The class is deliberately thin: it delegates all computation to
``PortfolioAnalyzer`` (``CarryMixin``) and all table styling to
``create_diverging_style``.  Its only job is orchestrating the output
sequence and producing the formatted tables so the notebook cell is
reduced to a single ``display()`` call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
from IPython.display import display

from deltadewa.analysis.base import PortfolioAnalyzer
from deltadewa.formatters.dataframes import create_diverging_style
from deltadewa.reporting import ConsoleReporter

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


class CarryDisplay:
    """Orchestrates the Theta Decay & Carry Analysis section of the dashboard.

    Parameters
    ----------
    portfolio:
        Live ``OptionPortfolio`` instance.
    reporter:
        ``ConsoleReporter`` for headers and status messages.  A default
        instance (width=100) is created when ``None`` is supplied.

    Example
    -------
    >>> carry = CarryDisplay(portfolio, reporter)
    >>> carry.display()

    """

    def __init__(
        self,
        portfolio: OptionPortfolio,
        reporter: ConsoleReporter | None = None,
    ) -> None:
        """Initialize with portfolio and optional reporter."""
        self._portfolio = portfolio
        self._reporter = reporter or ConsoleReporter(width=100)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def display(self) -> None:
        """Run and display the full carry / theta-decay analysis.

        Outputs (in order):

        1. Section header + educational note
        2. **Theta/Carry breakdown by source** — styled multi-index table
           (Income / Cost / NET rows x daily / weekly / monthly / annual)
        3. Carry status message (positive or negative carry)
        4. **Theta by maturity bucket** — styled table with contract count
           and % share of total theta
        5. **Theta by position (detailed)** — per-position styled table
        6. Net-carry validation line
        """
        if not self._portfolio.positions:
            print("No positions in portfolio yet.")
            return

        analyzer = PortfolioAnalyzer(self._portfolio)
        carry_metrics = analyzer.calculate_carry_metrics()
        df_carry = analyzer.add_maturity_buckets(self._portfolio.to_dataframe())

        self._reporter.header("Theta Decay & Carry Analysis")
        print(
            "\n💡 For options portfolios: Theta = Carry (same economic effect)",
        )

        self._display_summary_table(analyzer)
        self._display_carry_status(carry_metrics)
        self._display_bucket_table(carry_metrics, df_carry)
        self._display_position_table(df_carry)
        self._display_validation(carry_metrics)

    def display_summary_table(self) -> None:
        """Display only the theta/carry breakdown by source table."""
        if not self._portfolio.positions:
            print("No positions in portfolio yet.")
            return
        analyzer = PortfolioAnalyzer(self._portfolio)
        self._display_summary_table(analyzer)

    def display_bucket_table(self) -> None:
        """Display only the theta-by-maturity-bucket table."""
        if not self._portfolio.positions:
            print("No positions in portfolio yet.")
            return
        analyzer = PortfolioAnalyzer(self._portfolio)
        carry_metrics = analyzer.calculate_carry_metrics()
        df_carry = analyzer.add_maturity_buckets(self._portfolio.to_dataframe())
        self._display_bucket_table(carry_metrics, df_carry)

    def display_position_table(self) -> None:
        """Display only the per-position theta detail table."""
        if not self._portfolio.positions:
            print("No positions in portfolio yet.")
            return
        analyzer = PortfolioAnalyzer(self._portfolio)
        df_carry = analyzer.add_maturity_buckets(self._portfolio.to_dataframe())
        self._display_position_table(df_carry)

    # ------------------------------------------------------------------
    # Private rendering helpers
    # ------------------------------------------------------------------

    def _display_summary_table(self, analyzer: PortfolioAnalyzer) -> None:
        """Render the consolidated theta/carry breakdown by source."""
        print()
        self._reporter.subheader("Theta/Carry Breakdown by Source")

        theta_summary_df = analyzer.create_theta_summary_table()
        styled = create_diverging_style(
            theta_summary_df.reset_index(),
            value_columns=["daily", "weekly", "monthly", "annual"],
            currency_columns=["daily", "weekly", "monthly", "annual"],
            title_case=True,
        )
        display(styled)

    def _display_carry_status(self, carry_metrics: dict) -> None:
        """Print positive / negative carry status message."""
        print()
        if carry_metrics["is_positive_carry"]:
            self._reporter.success(
                f"Positive carry: "
                f"Earning ${carry_metrics['total_theta_daily']:.2f}/day",
            )
            print(
                f"  Annual income: "
                f"${carry_metrics['total_theta_annual']:,.2f}/year",
            )
        else:
            self._reporter.warning(
                f"Negative carry: Paying "
                f"${abs(carry_metrics['total_theta_daily']):,.2f}/day",
            )
            print(
                f"  Annual cost: "
                f"${abs(carry_metrics['total_theta_annual']):,.2f}/year",
            )

    def _display_bucket_table(
        self,
        carry_metrics: dict,
        df_carry: pd.DataFrame,
    ) -> None:
        """Render the theta-by-maturity-bucket styled table."""
        print()
        self._reporter.subheader("Theta by Maturity Bucket")

        bucket_data = []
        for bucket, theta in carry_metrics["theta_by_bucket"].items():
            bucket_positions = df_carry[df_carry["maturity_bucket"] == bucket]
            bucket_data.append(
                {
                    "maturity_bucket": bucket,
                    "daily_theta": theta,
                    "num_contracts": bucket_positions["quantity"].abs().sum(),
                    "pct_of_total": (
                        (
                            abs(theta)
                            / abs(carry_metrics["total_theta_daily"])
                            * 100
                        )
                        if carry_metrics["total_theta_daily"] != 0
                        else 0
                    ),
                },
            )

        df_bucket = pd.DataFrame(bucket_data)
        styled = create_diverging_style(
            df_bucket,
            value_columns=["daily_theta"],
            currency_columns=["daily_theta"],
            title_case=True,
        )
        styled = styled.format(
            {
                "Pct Of Total": "{:.1f}%",
                "Num Contracts": "{:.0f}",
                "Daily Theta": "${:,.2f}",
            },
        )
        display(styled)

    def _display_position_table(self, df_carry: pd.DataFrame) -> None:
        """Render the per-position theta detail styled table."""
        print()
        self._reporter.subheader("Theta by Position (Detailed)")

        position_theta_cols = [
            "option_type",
            "strike",
            "maturity_bucket",
            "quantity",
            "position_theta",
            "position_value",
        ]
        # Only keep columns that actually exist (defensive against schema
        # changes)
        cols_present = [c for c in position_theta_cols if c in df_carry.columns]
        df_position_theta = df_carry[cols_present].copy()

        styled = create_diverging_style(
            df_position_theta,
            value_columns=["position_theta", "position_value"],
            currency_columns=["strike", "position_theta", "position_value"],
            title_case=True,
        )
        styled = styled.format(
            {
                "Quantity": "{:.0f}",
                "Strike": "${:,.2f}",
                "Position Theta": "${:,.2f}",
                "Position Value": "${:,.2f}",
            },
        )
        display(styled)

    def _display_validation(self, carry_metrics: dict) -> None:
        """Print the net-carry == total-theta validation line."""
        print()
        net = carry_metrics["net_carry"]
        total = carry_metrics["total_theta_daily"]
        match = abs(net - total) < 0.01
        check = "✓" if match else "✗ BUG"
        print(
            f"✅ Validation: "
            f"Net Carry (${net:.2f}) = Total Theta (${total:.2f}) {check}",
        )
        self._reporter.divider()
