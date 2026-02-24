"""Batch pricer for efficient portfolio valuation across scenario grids."""

from datetime import datetime
from typing import List, Dict, Tuple
import numpy as np

from deltadewa.valuation import OptionValuation
from deltadewa.portfolio.position import OptionPosition
from deltadewa.constants import OptionType


class BatchPricer:
    """
    Efficient batch pricer for portfolio valuation across scenario grids.

    Optimizes portfolio valuation by caching OptionValuation instances per
    (position, date) and reusing them across spot price sweeps using the
    efficient update_spot_price() method.

    This reduces QuantLib environment constructions from P×S×T to P×T,
    where P=positions, S=spot scenarios, T=time points.

    Performance Impact:
        Measured speedup: 5-10% improvement across different scenario sizes
        - Example: 10 positions × 50 spots × 20 dates = 10,000 → 200 setups
        - Main benefit: Avoids expensive QL environment rebuilds
        - Note: QL price computation still dominates (finite difference calculation)
    """

    def __init__(
        self,
        positions: List[OptionPosition],
        risk_free_rate: float,
        dividend_yield: float,
        underlying_quantity: float,
    ):
        """
        Initialize batch pricer.

        Args:
            positions: List of option positions to price
            risk_free_rate: Risk-free interest rate (annualized)
            dividend_yield: Dividend yield (annualized)
            underlying_quantity: Quantity of underlying shares in portfolio
        """
        self.positions = positions
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield
        self.underlying_quantity = underlying_quantity

        # Cache: (position_index, valuation_date) -> OptionValuation
        self._cache: Dict[Tuple[int, datetime], OptionValuation] = {}

    def portfolio_values_at(
        self,
        spots: np.ndarray,
        valuation_date: datetime,
    ) -> np.ndarray:
        """
        Calculate portfolio values at multiple spot prices for a given date.

        For each position, checks if a cached OptionValuation exists for the
        given valuation_date. If cached and date matches, reuses it; otherwise
        builds a new one and caches it.

        For expired positions (days_to_maturity <= 0), uses vectorized NumPy
        intrinsic value calculation. For live positions, calls
        opt.update_spot_price(spot) then opt.price() for each spot (cheap
        SimpleQuote.setValue(), no engine rebuild).

        Args:
            spots: Array of spot prices to evaluate
            valuation_date: Valuation date for pricing

        Returns:
            Array of total portfolio values (options + underlying) at each spot
        """
        # Initialize result array
        portfolio_values = np.zeros(len(spots))

        # Add underlying position value (vectorized)
        portfolio_values += self.underlying_quantity * spots

        # Price each option position
        for pos_idx, position in enumerate(self.positions):
            days_to_maturity = (
                position.option.maturity_date - valuation_date
            ).days

            if days_to_maturity <= 0:
                # Option expired - use vectorized intrinsic value calculation
                if position.option.option_type == OptionType.CALL:
                    intrinsic = np.maximum(
                        0, spots - position.option.strike_price
                    )
                else:
                    intrinsic = np.maximum(
                        0, position.option.strike_price - spots
                    )
                portfolio_values += (
                    intrinsic * position.quantity * position.contract_size
                )
            else:
                # Option still alive - use cached OptionValuation
                cache_key = (pos_idx, valuation_date)

                if cache_key not in self._cache:
                    # Create new OptionValuation and cache it
                    # Use first spot as initial value (will be updated in loop)
                    opt = OptionValuation(
                        spot_price=float(spots[0]),
                        strike_price=position.option.strike_price,
                        maturity_date=position.option.maturity_date,
                        volatility=position.option.volatility,
                        risk_free_rate=self.risk_free_rate,
                        dividend_yield=self.dividend_yield,
                        option_type=position.option.option_type,
                        valuation_date=valuation_date,
                        exercise_style=position.exercise_style,
                    )
                    self._cache[cache_key] = opt
                else:
                    opt = self._cache[cache_key]

                # Sweep across spots using efficient update_spot_price()
                for i, spot in enumerate(spots):
                    opt.update_spot_price(spot)
                    portfolio_values[i] += (
                        opt.price() * position.quantity * position.contract_size
                    )

        return portfolio_values

    def clear_cache(self):
        """Clear the internal cache of OptionValuation instances."""
        self._cache.clear()
