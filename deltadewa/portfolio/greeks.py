"""Greek calculations mixin for option portfolios."""


class GreeksMixin:
    """Mixin providing Greek calculations for OptionPortfolio."""

    def total_value(self) -> float:
        """Calculate total portfolio value."""
        return sum(pos.position_value() for pos in self.positions)

    def total_underlying_value(self) -> float:
        """Calculate the value of the underlying notional position."""
        return self.underlying_quantity * self.spot_price

    def total_portfolio_value(self) -> float:
        """Total portfolio value including options and underlying notional."""
        return self.total_value() + self.total_underlying_value()

    def total_delta(self) -> float:
        """
        Calculate total portfolio delta from option positions only.

        This is the sum of all option position deltas, excluding the underlying position.
        Also referred to as "Portfolio Delta" or "Total Delta".

        Returns:
            Total delta from options only (positive = net long options,
            negative = net short options)
        """
        return sum(pos.position_delta() for pos in self.positions)

    def total_gamma(self) -> float:
        """Calculate total portfolio gamma."""
        return sum(pos.position_gamma() for pos in self.positions)

    def total_vega(self) -> float:
        """Calculate total portfolio vega."""
        return sum(pos.position_vega() for pos in self.positions)

    def total_theta(self) -> float:
        """Calculate total portfolio theta."""
        return sum(pos.position_theta() for pos in self.positions)

    def total_rho(self) -> float:
        """Calculate total portfolio rho."""
        return sum(pos.position_rho() for pos in self.positions)

    def net_delta(self) -> float:
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

    def hedge_ratio(self) -> float:
        """
        Calculate the hedge ratio (how much of the notional is hedged).

        Returns:
            Hedge ratio as a percentage
        """
        if self.underlying_quantity == 0:
            return 0.0
        return -(self.total_delta() / self.underlying_quantity) * 100

    def delta_adjustment_needed(self) -> float:
        """
        Calculate the delta adjustment needed to achieve delta neutrality.

        Returns:
            Number of shares to buy/sell to achieve delta neutrality
        """
        return -self.net_delta()
