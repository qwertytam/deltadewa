"""P&L calculations mixin for option portfolio."""

from typing import TYPE_CHECKING

import numpy as np

from deltadewa.constants import OptionType

if TYPE_CHECKING:
    from deltadewa.portfolio._protocols import _PortfolioProtocol


class PnLMixin:
    """Mixin providing P&L calculations for option portfolio."""

    if TYPE_CHECKING:
        _self: "_PortfolioProtocol"

    def calculate_net_debit(self: "_PortfolioProtocol") -> float:
        """Calculate the net debit/credit for implementing the portfolio.

        Returns:
            Net debit (positive) or net credit (negative) in dollars

        """
        return self.total_value()

    def calculate_pnl_at_expiry(
        self: "_PortfolioProtocol",
        spot_price_at_expiry: float,
        include_underlying: bool = False,
    ) -> float:
        """Calculate P&L at expiration for a given spot price.

        Args:
            spot_price_at_expiry: Spot price at expiration
            include_underlying: Whether to include underlying position P&L

        Returns:
            Total P&L at expiration

        """
        initial_cost = self.total_value()
        initial_cost = 0.0 if initial_cost is None else float(initial_cost)
        pnl = -initial_cost  # Start with negative of initial cost

        # Calculate intrinsic value at expiry for each position
        for pos in self.positions:
            if pos.option.option_type == OptionType.CALL:
                intrinsic = max(
                    0,
                    spot_price_at_expiry - pos.option.strike_price,
                )
            else:  # put
                intrinsic = max(
                    0,
                    pos.option.strike_price - spot_price_at_expiry,
                )

            pnl += intrinsic * pos.quantity * pos.contract_size

        # Add underlying P&L if requested
        if include_underlying and self.underlying_quantity != 0:
            underlying_pnl = (
                spot_price_at_expiry - self.spot_price
            ) * self.underlying_quantity
            pnl += underlying_pnl

        return pnl

    def vectorized_pnl_at_expiry(
        self: "_PortfolioProtocol",
        spot_scenarios: np.ndarray,
        include_underlying: bool = True,
    ) -> np.ndarray:
        """Calculate P&L at expiry using vectorized NumPy operations.

        This method provides a vectorized alternative to calculate_pnl_at_expiry
        for computing P&L across many spot scenarios simultaneously. It's much
        faster for large arrays because it uses NumPy broadcasting and avoids
        Python loops.

        Args:
            spot_scenarios: Array of spot prices to evaluate (shape: (n,))
            include_underlying: Whether to include underlying position P&L

        Returns:
            np.ndarray of P&L values for each spot scenario (shape: (n,))

        """
        if len(self.positions) == 0:
            # Empty portfolio case
            if include_underlying and self.underlying_quantity != 0:
                return self.underlying_quantity * (
                    spot_scenarios - self.spot_price
                )
            return np.zeros_like(spot_scenarios)

        # Pre-extract position data into arrays
        strikes = np.array([pos.option.strike_price for pos in self.positions])
        quantities = np.array([pos.quantity for pos in self.positions])
        contract_sizes = np.array([pos.contract_size for pos in self.positions])
        is_call = np.array(
            [
                pos.option.option_type == OptionType.CALL
                for pos in self.positions
            ],
        )

        # Vectorized intrinsic value calculation using broadcasting
        # Shape: spot_scenarios[:, None] is (n_spots, 1)  # noqa: ERA001
        # Shape: strikes[None, :] is (1, n_positions)  # noqa: ERA001
        # Result: (n_spots, n_positions)  # noqa: ERA001
        spots_2d = spot_scenarios[:, np.newaxis]
        strikes_2d = strikes[np.newaxis, :]

        call_intrinsic = np.maximum(spots_2d - strikes_2d, 0)
        put_intrinsic = np.maximum(strikes_2d - spots_2d, 0)
        intrinsic = np.where(is_call, call_intrinsic, put_intrinsic)

        # Apply quantity and contract size
        position_values = (
            intrinsic
            * quantities[np.newaxis, :]
            * contract_sizes[np.newaxis, :]
        )
        total_option_value = position_values.sum(axis=1)

        # Calculate P&L relative to initial cost
        initial_cost = self.total_value()
        pnl = total_option_value - initial_cost

        # Add underlying P&L if requested
        if include_underlying and self.underlying_quantity != 0:
            underlying_pnl = self.underlying_quantity * (
                spot_scenarios - self.spot_price
            )
            pnl += underlying_pnl

        return pnl
