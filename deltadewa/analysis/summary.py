"""Summary and insights mixin for portfolio analysis."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

import numpy as np

from deltadewa.analysis.maturity import DEFAULT_MATURITY_BUCKETS
from deltadewa.portfolio.monte_carlo import drift_measure_label

if TYPE_CHECKING:
    from deltadewa.analysis._protocols import _AnalyzerProtocol
    from deltadewa.portfolio.core import OptionPortfolio

_T = TypeVar("_T")
_Row = tuple[Callable[[_T], bool], Callable[[_T], list[str]]]


def _resolve(context: _T, rows: tuple[_Row[_T], ...]) -> list[str]:
    """Return the lines from the first row whose predicate matches."""
    for predicate, formatter in rows:
        if predicate(context):
            return formatter(context)
    return []


_CAPITAL_ROWS: tuple[_Row[float], ...] = (
    (
        lambda net_debit: net_debit > 0,
        lambda net_debit: [
            f"  Net Debit: ${net_debit:,.2f} (capital required to implement)",
        ],
    ),
    (
        lambda _net_debit: True,
        lambda net_debit: [
            f"  Net Credit: ${-net_debit:,.2f} (capital received)",
        ],
    ),
)

_BREAKEVEN_ROWS: tuple[_Row[list[float]], ...] = (
    (
        bool,
        lambda breakevens: [
            "  Breakeven Points: "
            + ", ".join(f"${be:.2f}" for be in breakevens),
        ],
    ),
    (
        lambda _breakevens: True,
        lambda _breakevens: ["  Breakeven Points: None identified"],
    ),
)


@dataclass(frozen=True)
class _MaxLossContext:
    """Parameters for formatting a max-loss line in either section."""

    info: dict[str, Any]
    unlimited_label: str
    pct_basis: float
    pct_phrase: str
    show_pct: bool


def _format_unlimited_max_loss(ctx: _MaxLossContext) -> list[str]:
    """Format the max-loss line when loss is unlimited."""
    return [f"  Max Loss: UNLIMITED ({ctx.unlimited_label})"]


def _format_bounded_max_loss(ctx: _MaxLossContext) -> list[str]:
    """Format the max-loss line and spot marker when loss is bounded."""
    loss_line = f"  Max Loss: ${-ctx.info['max_loss']:,.2f}"
    if ctx.show_pct:
        loss_pct = (-ctx.info["max_loss"] / abs(ctx.pct_basis)) * 100
        loss_line += f" ({loss_pct:.1f}% {ctx.pct_phrase})"
    return [
        loss_line,
        f"    └─ Occurs at spot price: ${ctx.info['spot_at_max_loss']:.2f}",
    ]


_MAX_LOSS_ROWS: tuple[_Row[_MaxLossContext], ...] = (
    (lambda ctx: bool(ctx.info["is_unlimited"]), _format_unlimited_max_loss),
    (lambda _ctx: True, _format_bounded_max_loss),
)


def _format_max_loss(ctx: _MaxLossContext) -> list[str]:
    """Dispatch max-loss formatting on the unlimited/bounded case."""
    return _resolve(ctx, _MAX_LOSS_ROWS)


@dataclass(frozen=True)
class _MaxProfitContext:
    """Parameters for formatting a max-profit line in either section."""

    info: dict[str, Any]
    unlimited_lines: list[str]
    pct_basis: float
    pct_phrase: str
    show_pct: bool


def _format_unlimited_max_profit(ctx: _MaxProfitContext) -> list[str]:
    """Format the max-profit line(s) when profit is unlimited."""
    return ctx.unlimited_lines


def _format_bounded_max_profit(ctx: _MaxProfitContext) -> list[str]:
    """Format the max-profit line and spot marker when profit is bounded."""
    profit_line = f"  Max Profit: ${ctx.info['max_profit']:,.2f}"
    if ctx.show_pct:
        profit_pct = (ctx.info["max_profit"] / ctx.pct_basis) * 100
        profit_line += f" ({profit_pct:.1f}% {ctx.pct_phrase})"
    return [
        profit_line,
        f"    └─ Occurs at spot price: ${ctx.info['spot_at_max_profit']:.2f}",
    ]


_MAX_PROFIT_ROWS: tuple[_Row[_MaxProfitContext], ...] = (
    (
        lambda ctx: bool(ctx.info["is_unlimited"]),
        _format_unlimited_max_profit,
    ),
    (lambda _ctx: True, _format_bounded_max_profit),
)


def _format_max_profit(ctx: _MaxProfitContext) -> list[str]:
    """Dispatch max-profit formatting on the unlimited/bounded case."""
    return _resolve(ctx, _MAX_PROFIT_ROWS)


_TOTAL_UNLIMITED_PROFIT_ROWS: tuple[_Row[float], ...] = (
    (
        lambda underlying_quantity: underlying_quantity > 0,
        lambda _underlying_quantity: [
            "  Max Profit: UNLIMITED (long underlying position)",
            "    └─ Profit increases with spot price",
        ],
    ),
    (
        lambda _underlying_quantity: True,
        lambda _underlying_quantity: [
            "  Max Profit: UNLIMITED",
            "    └─ Profit increases with spot price",
        ],
    ),
)


def _format_capital_section(net_debit: float) -> list[str]:
    """Format the capital-requirements section."""
    return ["CAPITAL REQUIREMENTS:", *_resolve(net_debit, _CAPITAL_ROWS), ""]


def _format_options_section(
    analysis: dict[str, Any],
    net_debit: float,
) -> list[str]:
    """Format the options-only risk/reward section."""
    loss_ctx = _MaxLossContext(
        info=analysis["max_loss_options"],
        unlimited_label="naked short positions",
        pct_basis=net_debit,
        pct_phrase="of net debit",
        show_pct=net_debit != 0,
    )
    profit_ctx = _MaxProfitContext(
        info=analysis["max_profit_options"],
        unlimited_lines=["  Max Profit: UNLIMITED"],
        pct_basis=net_debit,
        pct_phrase="return on net debit",
        show_pct=net_debit > 0,
    )
    return [
        "OPTIONS ONLY RISK/REWARD:",
        *_format_max_loss(loss_ctx),
        *_format_max_profit(profit_ctx),
        *_resolve(analysis["breakeven_options"], _BREAKEVEN_ROWS),
        "",
    ]


def _format_total_section(
    portfolio: "OptionPortfolio",
    analysis: dict[str, Any],
) -> list[str]:
    """Format the total-portfolio (options + underlying) section."""
    max_loss_total = analysis["max_loss_total"]
    portfolio_value = 0.0
    if not max_loss_total["is_unlimited"]:
        portfolio_value = portfolio.total_portfolio_value()

    loss_ctx = _MaxLossContext(
        info=max_loss_total,
        unlimited_label="short underlying position",
        pct_basis=portfolio_value,
        pct_phrase="of portfolio value",
        show_pct=portfolio_value > 0,
    )
    profit_ctx = _MaxProfitContext(
        info=analysis["max_profit_total"],
        unlimited_lines=_resolve(
            portfolio.underlying_quantity,
            _TOTAL_UNLIMITED_PROFIT_ROWS,
        ),
        pct_basis=portfolio_value,
        pct_phrase="of portfolio value",
        show_pct=portfolio_value > 0,
    )
    return [
        "TOTAL PORTFOLIO RISK/REWARD (Options + Underlying):",
        *_format_max_loss(loss_ctx),
        *_format_max_profit(profit_ctx),
        *_resolve(analysis["breakeven_total"], _BREAKEVEN_ROWS),
        "",
    ]


def _format_probability_section(analysis: dict[str, Any]) -> list[str]:
    """Format the probability-analysis section."""
    prob = analysis["prob_profit"]
    measure = drift_measure_label(analysis.get("drift_measure", "risk_neutral"))
    return [
        "PROBABILITY ANALYSIS:",
        f"  Chance of Profit: {prob * 100:.1f}% ({measure} drift)",
        (
            f"  Expected Value: ${analysis['expected_pnl']:,.2f} "
            f"(probabilistic weighted average)"
        ),
        "",
    ]


def _format_ratio_section(analysis: dict[str, Any]) -> list[str]:
    """Format the risk/reward ratio line, if the ratio is meaningful."""
    max_loss_opts = analysis["max_loss_options"]
    max_profit_opts = analysis["max_profit_options"]
    if (
        not max_loss_opts["is_unlimited"]
        and not max_profit_opts["is_unlimited"]
        and max_loss_opts["max_loss"] < 0 < max_profit_opts["max_profit"]
    ):
        rr_ratio = max_profit_opts["max_profit"] / -max_loss_opts["max_loss"]
        return [
            f"RISK/REWARD RATIO: {rr_ratio:.2f}:1 (max profit to max loss)",
        ]
    return []


class SummaryMixin:
    """Mixin for insights generation and summary formatting.

    Provides methods for generating formatted risk summaries,
    risk/reward summaries, and actionable insights based on portfolio analysis.
    """

    if TYPE_CHECKING:
        _self: "_AnalyzerProtocol"

    def format_risk_summary(
        self: "_AnalyzerProtocol",
        stats: dict[str, Any] | None = None,
    ) -> str:
        """Generate formatted risk summary text.

        Args:
            stats: Portfolio summary stats (uses current if None)

        Returns:
            Formatted string with risk analysis

        """
        if stats is None:
            stats = self.portfolio.summary_stats()
        if stats is None:
            return "No portfolio data available."

        lines = []
        lines.append("=" * 70)
        lines.append("PORTFOLIO RISK SUMMARY")
        lines.append("=" * 70)
        lines.append("")

        # Delta analysis
        lines.append("DIRECTIONAL RISK (DELTA):")
        lines.append(f"  Portfolio Delta: {stats['total_delta']:,.2f}")
        lines.append(
            f"  Notional Position: {stats['underlying_quantity']:,.2f}",
        )
        lines.append(f"  Net Delta: {stats['net_delta']:,.2f}")
        lines.append(f"  Hedge Ratio: {stats['hedge_ratio']:.2f}%")

        if abs(stats["net_delta"]) < abs(stats["underlying_quantity"]) * 0.1:
            lines.append("  ✓ Well hedged (net delta < 10% of notional)")
        elif stats["net_delta"] > 0:
            lines.append("  ⚠ Net long exposure - vulnerable to price decline")
        else:
            lines.append(
                "  ⚠ Net short exposure - vulnerable to price increase",
            )

        lines.append("")

        # Gamma analysis
        lines.append("CONVEXITY RISK (GAMMA):")
        lines.append(f"  Total Gamma: {stats['total_gamma']:.4f}")
        if stats["total_gamma"] > 0:
            lines.append("  → Long gamma: Delta increases as spot rises")
        else:
            lines.append("  → Short gamma: Delta decreases as spot rises")

        lines.append("")

        # Vega analysis
        lines.append("VOLATILITY RISK (VEGA):")
        lines.append(f"  Total Vega: {stats['total_vega']:.2f}")
        if stats["total_vega"] > 0:
            lines.append("  → Long vega: Benefits from volatility increase")
        else:
            lines.append("  → Short vega: Benefits from volatility decrease")

        lines.append("")

        # Theta analysis
        lines.append("TIME DECAY (THETA):")
        lines.append(f"  Total Theta: ${stats['total_theta']:.2f}/day")
        if stats["total_theta"] > 0:
            lines.append("  → Positive theta: Earning from time decay")
        else:
            lines.append("  → Negative theta: Paying for time decay")

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)

    def generate_insights(self: "_AnalyzerProtocol") -> list[str]:
        """Generate actionable insights based on portfolio analysis.

        Returns:
            list of insight strings

        """
        insights = []
        stats = self.portfolio.summary_stats()

        # Only scalar totals are read below, so these edges reach no
        # reader — passed explicitly all the same, because the
        # parameter has no default anywhere (#305).
        carry_metrics = self.calculate_carry_metrics(
            DEFAULT_MATURITY_BUCKETS,
        )

        concentration = self.analyze_risk_concentration()

        # Delta insights
        if abs(stats["net_delta"]) > abs(stats["underlying_quantity"]) * 0.2:
            insights.append(
                f"⚠ High net delta exposure ({stats['net_delta']:.0f}) - "
                "consider rebalancing hedge",
            )

        # Theta insights
        if carry_metrics["is_positive_carry"]:
            insights.append(
                f"✓ Positive carry: Earning $"
                f"{carry_metrics['total_theta_daily']:.2f}/day "
                f"(${carry_metrics['total_theta_monthly']:.0f}/month)",
            )
        else:
            insights.append(
                f"⚠ Negative carry: Paying $"
                f"{-carry_metrics['total_theta_daily']:.2f}/day "
                "for options positions",
            )

        # Concentration insights
        for metric, score in concentration["concentration_scores"].items():
            if "strike" in metric and score > 30:
                insights.append(
                    f"⚠ {metric.split('_')[0].upper()} concentrated in single "
                    f"strike ({score:.1f}%) - consider diversifying",
                )

        # Gamma insights
        if abs(stats["total_gamma"]) > 0.1:
            direction = "long" if stats["total_gamma"] > 0 else "short"
            insights.append(
                f"ℹ High {direction} gamma ({abs(stats['total_gamma']):.4f}) - "  # ruff: ignore[ambiguous-unicode-character-string]
                "delta will change significantly with spot moves",
            )

        # Vega insights
        if abs(stats["total_vega"]) > 100:
            direction = (
                "benefits from" if stats["total_vega"] > 0 else "hurt by"
            )
            insights.append(
                f"ℹ Significant vega exposure ({abs(stats['total_vega']):.0f})"  # ruff: ignore[ambiguous-unicode-character-string]
                f" - portfolio {direction} volatility increases",
            )

        return insights

    def format_risk_reward_summary(
        self: "_AnalyzerProtocol",
        spot_range: np.ndarray[Any, np.dtype[Any]] | None = None,
    ) -> str:
        """Generate formatted risk/reward summary text.

        Args:
            spot_range: Array of spot prices to analyze (optional)

        Returns:
            Formatted string with risk/reward analysis

        """
        analysis = self.risk_reward_analysis(spot_range)
        net_debit = analysis["net_debit"]

        lines = ["=" * 80, "PORTFOLIO RISK/REWARD ANALYSIS", "=" * 80, ""]
        lines.extend(_format_capital_section(net_debit))
        lines.extend(_format_options_section(analysis, net_debit))
        if self.portfolio.underlying_quantity != 0:
            lines.extend(_format_total_section(self.portfolio, analysis))
        lines.extend(_format_probability_section(analysis))
        lines.extend(_format_ratio_section(analysis))
        lines.append("=" * 80)

        return "\n".join(lines)

    def print_risk_reward_summary(
        self: "_AnalyzerProtocol",
        spot_range: np.ndarray[Any, np.dtype[Any]] | None = None,
    ) -> None:
        """Print a formatted risk/reward summary of the portfolio.

        Args:
            spot_range: Array of spot prices to analyze (optional)

        """
        summary = self.format_risk_reward_summary(spot_range)
        print(summary)
