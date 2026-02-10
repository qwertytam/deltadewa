"""P&L calculations mixin for option portfolio."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolioBase


class PnLMixin:
    """Mixin providing P&L calculations for option portfolio."""

    def calculate_net_debit(self: "OptionPortfolioBase") -> float:
        """
        Calculate the net debit/credit for implementing the portfolio.

        Returns:
            Net debit (positive) or net credit (negative) in dollars
        """
        return self.total_value()

    def calculate_pnl_at_expiry(
        self: "OptionPortfolioBase",
        spot_price_at_expiry: float,
        include_underlying: bool = False,
    ) -> float:
        """
        Calculate P&L at expiration for a given spot price.

        Args:
            spot_price_at_expiry: Spot price at expiration
            include_underlying: Whether to include underlying position P&L

        Returns:
            Total P&L at expiration
        """
        initial_cost = self.total_value()
        pnl = -initial_cost  # Start with negative of initial cost

        # Calculate intrinsic value at expiry for each position
        for pos in self.positions:
            if pos.option.option_type.lower() == "call":
                intrinsic = max(
                    0, spot_price_at_expiry - pos.option.strike_price
                )
            else:  # put
                intrinsic = max(
                    0, pos.option.strike_price - spot_price_at_expiry
                )

            pnl += intrinsic * pos.quantity * pos.contract_size

        # Add underlying P&L if requested
        if include_underlying and self.underlying_quantity != 0:
            underlying_pnl = (
                spot_price_at_expiry - self.spot_price
            ) * self.underlying_quantity
            pnl += underlying_pnl

        return pnl
