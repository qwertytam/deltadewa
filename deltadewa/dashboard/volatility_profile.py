"""Portfolio Volatility Profile display for the deltadewa options dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deltadewa.analysis.volatility import get_volatility_stats
from deltadewa.reporting import ConsoleReporter

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


class VolatilityProfileDisplay:
    """Build and display the portfolio volatility profile."""

    def __init__(
        self,
        portfolio: OptionPortfolio,
        reporter: ConsoleReporter | None = None,
    ) -> None:
        """Initialize with the portfolio to display."""
        self._portfolio = portfolio
        self._reporter = reporter or ConsoleReporter()

    def display(self, vol_stats: dict[str, Any] | None = None) -> None:
        """Print the portfolio volatility profile.

        If vol_stats is None, it is computed fresh from the portfolio.
        """
        self._reporter.header("PORTFOLIO VOLATILITY PROFILE")

        # Compute vol_stats from portfolio when not provided
        if vol_stats is None:
            vol_stats = self._compute_vol_stats()

        if vol_stats:
            print(
                f"\nVega-Weighted Average Volatility: "
                f"{vol_stats['avg_volatility']:.2%}",
            )
            print(
                f"Portfolio Default Volatility:     "
                f"{vol_stats['portfolio_volatility']:.2%}",
            )
            print("\nVolatility Range:")
            print(f"  Minimum: {vol_stats['min_volatility']:.2%}")
            print(f"  Maximum: {vol_stats['max_volatility']:.2%}")
            print(f"  Std Dev: {vol_stats['std_volatility']:.4f}")
            print(f"  Range:   {vol_stats['volatility_range']:.2%}")

            print(
                f"\nPositions: {vol_stats['num_positions']} total, "
                f"{vol_stats['num_custom_vol']} with custom volatility",
            )

            if vol_stats["num_custom_vol"] > 0:
                print("\n⚠️  Volatility Skew Detected")
                print(
                    "   Stress test analysis uses proportional"
                    " volatility scaling to",
                )
                print(
                    "   maintain the relative volatility structure "
                    "(skew/smile) across positions.",
                )
                print(
                    "   Each position's volatility is scaled "
                    "by the same factor.",
                )
            else:
                print("\n✓ Uniform Volatility")
                print("  All positions use the portfolio default volatility.")

            print("\nPosition Volatilities:")
            for i, pos in enumerate(self._portfolio.positions):
                custom_marker = " (custom)" if pos.custom_volatility else ""
                print(
                    f"  Position {i + 1}: {pos.option.volatility:.2%}"
                    f"{custom_marker} - {pos.option.option_type.upper()} "
                    f"${pos.option.strike_price:.2f}",
                )
        else:
            print("No positions in portfolio")

        self._reporter.divider()

    def _compute_vol_stats(self) -> dict[str, Any]:
        """Compute volatility statistics for the portfolio.

        Delegates to `deltadewa.analysis.volatility.get_volatility_stats`
        to ensure consistent behavior with analysis utilities and tests.
        Returns an empty dict for empty portfolios.
        """
        return get_volatility_stats(self._portfolio)
