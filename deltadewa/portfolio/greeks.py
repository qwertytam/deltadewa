"""Greeks calculations mixin for option portfolio."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolioBase


class GreeksMixin:
    """Mixin providing Greek calculations for option portfolio."""

    def total_delta(self: "OptionPortfolioBase") -> float:
        """
        Calculate total portfolio delta from option positions only.

        This is the sum of all option position deltas, excluding the underlying position.
        Also referred to as "Portfolio Delta" or "Total Delta".

        Returns:
            Total delta from options only (positive = net long options,
            negative = net short options)
        """
        return sum(pos.position_delta() for pos in self.positions)

    def total_gamma(self: "OptionPortfolioBase") -> float:
        """Calculate total portfolio gamma."""
        return sum(pos.position_gamma() for pos in self.positions)

    def total_vega(self: "OptionPortfolioBase") -> float:
        """Calculate total portfolio vega."""
        return sum(pos.position_vega() for pos in self.positions)

    def total_theta(self: "OptionPortfolioBase") -> float:
        """Calculate total portfolio theta."""
        return sum(pos.position_theta() for pos in self.positions)

    def total_rho(self: "OptionPortfolioBase") -> float:
        """Calculate total portfolio rho."""
        return sum(pos.position_rho() for pos in self.positions)

    def net_delta(self: "OptionPortfolioBase") -> float:
        """
        Calculate net delta including both options and underlying position.

        This is the total directional exposure combining:
        - Portfolio delta (from all option positions)
        - Underlying position quantity

        Also referred to as "Net Position Delta" or "Total Exposure".

        Returns:
            Net delta exposure (positive = net long, negative = net short)

        Example:
            - Portfolio delta (options): -100
            - Underlying position: +100 shares
            - Net delta: 0 (perfectly hedged)
        """
        return self.total_delta() + self.underlying_quantity

    def hedge_ratio(self: "OptionPortfolioBase") -> float:
        """
        Calculate the hedge ratio (how much of the notional is hedged).

        Returns:
            Hedge ratio as a percentage
        """
        if self.underlying_quantity == 0:
            return 0.0
        return -(self.total_delta() / self.underlying_quantity) * 100

    def delta_adjustment_needed(self: "OptionPortfolioBase") -> float:
        """
        Calculate the delta adjustment needed to achieve delta neutrality.

        Returns:
            Number of shares to buy/sell to achieve delta neutrality
        """
        return -self.net_delta()
