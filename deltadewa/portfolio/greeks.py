"""Greeks calculations mixin for option portfolio."""

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from deltadewa.portfolio.position import OptionPosition


class GreeksMixin:
    """Mixin providing Greek calculations for option portfolio."""

    if TYPE_CHECKING:
        positions: list["OptionPosition"]
        underlying_quantity: float

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

    def all_greeks(self) -> dict:
        """
        Calculate all portfolio Greeks in a single efficient pass.

        More efficient than calling individual methods when you need all Greeks.
        Uses the cached greeks() method on each option for batch computation.

        Returns:
            Dictionary containing:
            - total_delta: Portfolio delta from options only
            - total_gamma: Portfolio gamma
            - total_vega: Portfolio vega
            - total_theta: Portfolio theta (per day)
            - total_rho: Portfolio rho
            - net_delta: Total delta exposure (options + underlying)
        """
        total_delta = 0.0
        total_gamma = 0.0
        total_vega = 0.0
        total_theta = 0.0
        total_rho = 0.0

        for pos in self.positions:
            greeks = pos.option.greeks()  # Uses cache for efficiency
            multiplier = pos.quantity * pos.contract_size

            total_delta += greeks["delta"] * multiplier
            total_gamma += greeks["gamma"] * multiplier
            total_vega += greeks["vega"] * multiplier
            total_theta += greeks["theta"] * multiplier
            total_rho += greeks["rho"] * multiplier

        return {
            "total_delta": total_delta,
            "total_gamma": total_gamma,
            "total_vega": total_vega,
            "total_theta": total_theta,
            "total_rho": total_rho,
            "net_delta": total_delta + self.underlying_quantity,
        }
