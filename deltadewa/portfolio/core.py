"""Core option portfolio management."""

from datetime import datetime
from typing import List, Optional, Dict, Any
import pandas as pd

from deltadewa.american_option import AmericanOption
from deltadewa.portfolio.position import OptionPosition
from deltadewa.portfolio.greeks import GreeksMixin
from deltadewa.portfolio.pnl import PnLMixin
from deltadewa.portfolio.risk import RiskMixin
from deltadewa.portfolio.monte_carlo import MonteCarloMixin
from deltadewa.portfolio.scenario import ScenarioMixin


class OptionPortfolio(
    GreeksMixin, PnLMixin, RiskMixin, MonteCarloMixin, ScenarioMixin
):
    """
    Manages a portfolio of American options with hedge analysis.
    """

    def __init__(
        self,
        underlying_quantity: float = 0.0,
        spot_price: float = 100.0,
        volatility: float = 0.2,
        risk_free_rate: float = 0.05,
        dividend_yield: float = 0.0,
        valuation_date: Optional[datetime] = None,
    ):
        """
        Initialize option portfolio.

        Args:
            underlying_quantity: The underlying notional position to hedge
            spot_price: Current spot price of the underlying
            volatility: Market volatility
            risk_free_rate: Risk-free rate
            dividend_yield: Dividend yield
            valuation_date: Valuation date for all options (defaults to now)
        """
        self.positions: List[OptionPosition] = []
        self.underlying_quantity = underlying_quantity
        self.spot_price = spot_price
        self.volatility = volatility
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield
        self.valuation_date = valuation_date or datetime.now()
        self._monte_carlo_results: Optional[Dict[str, Any]] = None

    def add_position(
        self,
        strike_price: float,
        maturity_date: datetime,
        quantity: int,
        option_type: str = "call",
        symbol: str = "UNKNOWN",
        contract_size: int = 100,
        volatility: Optional[float] = None,
    ):
        """
        Add an option position to the portfolio.

        Args:
            strike_price: Strike price of the option
            maturity_date: Maturity date of the option
            quantity: Number of contracts
            option_type: "call" or "put"
            symbol: Underlying symbol or identifier for display/export
            contract_size: Number of underlying shares per option contract
            volatility: Optional position-specific volatility (uses portfolio default if None)
        """
        # Use position-specific volatility or portfolio default
        option_volatility = (
            volatility if volatility is not None else self.volatility
        )
        custom_volatility = volatility is not None

        option = AmericanOption(
            spot_price=self.spot_price,
            strike_price=strike_price,
            maturity_date=maturity_date,
            volatility=option_volatility,
            risk_free_rate=self.risk_free_rate,
            dividend_yield=self.dividend_yield,
            option_type=option_type,
            valuation_date=self.valuation_date,
        )
        position = OptionPosition(
            option,
            quantity,
            contract_size=contract_size,
            symbol=symbol,
            custom_volatility=custom_volatility,
        )
        self.positions.append(position)

    def set_volatility(self, volatility: float):
        """Set portfolio volatility. Update positions without custom volatility."""
        self.volatility = volatility
        for pos in self.positions:
            if not pos.custom_volatility:
                pos.option.volatility = volatility

    def get_symbol(self) -> str:
        """Get the symbol of the first position, or 'N/A' if none."""
        if self.positions:
            return self.positions[0].symbol
        return "N/A"

    @property
    def monte_carlo_results(self) -> Optional[Dict[str, Any]]:
        """Get Monte Carlo simulation results if available.

        Returns:
            Dictionary containing Monte Carlo analysis results, or None if not yet computed.
            Result keys include: expected_pnl, prob_profit, var_95, cvar_95, etc.
        """
        return self._monte_carlo_results

    @monte_carlo_results.setter
    def monte_carlo_results(self, results: Optional[Dict[str, Any]]):
        """Set Monte Carlo simulation results.

        Args:
            results: Dictionary containing Monte Carlo analysis results
        """
        self._monte_carlo_results = results

    def summary_stats(self) -> dict:
        """
        Get summary statistics of the portfolio.

        Returns:
            Dictionary containing:
            - total_positions: Number of option positions
            - total_value: Value of option positions only
            - total_underlying_value: Value of underlying position
            - total_portfolio_value: Total value (options + underlying)
            - total_delta: Portfolio delta from options only
            - underlying_quantity: Number of underlying shares
            - net_delta: Total delta exposure (options + underlying)
            - hedge_ratio: Percentage of underlying hedged by options
            - delta_adjustment: Shares needed for delta neutrality
            - total_gamma, total_vega, total_theta, total_rho: Greek totals
            - volatility_min, volatility_max: Volatility range
            - custom_volatility_count: Positions with custom volatility
        """
        stats = {
            "total_positions": len(self.positions),
            "total_value": self.total_value(),
            "total_underlying_value": self.total_underlying_value(),
            "total_portfolio_value": self.total_portfolio_value(),
            "total_delta": self.total_delta(),
            "underlying_quantity": self.underlying_quantity,
            "net_delta": self.net_delta(),
            "hedge_ratio": self.hedge_ratio(),
            "delta_adjustment": self.delta_adjustment_needed(),
            "total_gamma": self.total_gamma(),
            "total_vega": self.total_vega(),
            "total_theta": self.total_theta(),
            "total_rho": self.total_rho(),
        }

        # Add volatility statistics
        if self.positions:
            stats["volatility_min"] = min(
                pos.option.volatility for pos in self.positions
            )
            stats["volatility_max"] = max(
                pos.option.volatility for pos in self.positions
            )
            stats["custom_volatility_count"] = sum(
                1 for pos in self.positions if pos.custom_volatility
            )
        else:
            stats["volatility_min"] = self.volatility
            stats["volatility_max"] = self.volatility
            stats["custom_volatility_count"] = 0

        return stats

    def summary(self) -> str:
        """Return a human-readable summary of the portfolio."""
        stats = self.summary_stats()
        return (
            f"Positions: {stats['total_positions']}, "
            f"Value: ${stats['total_value']:,.2f}, "
            f"Net Delta: {stats['net_delta']:,.2f}, "
            f"Gamma: {stats['total_gamma']:.4f}, "
            f"Vega: {stats['total_vega']:.2f}, "
            f"Theta: {stats['total_theta']:.2f}"
        )

    def summary_market(self) -> str:
        """Return a summary of the market conditions."""
        return (
            f"Symbol: {self.positions[0].symbol if self.positions else 'N/A'}, "
            f"Underlying Quantity: {self.underlying_quantity:,.0f} shares, "
            f"Spot Price: ${self.spot_price:,.2f}, "
            f"Volatility: {self.volatility:.2%}, "
            f"Risk-free Rate: {self.risk_free_rate:.2%}, "
            f"Dividend Yield: {self.dividend_yield:.2%}, "
            f"Valuation Date: {self.valuation_date.date()}"
        )

    def get_positions(self) -> List[dict]:
        """Return positions in a format suitable for widgets/UI."""
        positions = []
        for pos in self.positions:
            positions.append(
                {
                    "symbol": pos.symbol,
                    "type": pos.option.option_type.capitalize(),
                    "strike": pos.option.strike_price,
                    "expiry": pos.option.maturity_date.date(),
                    "quantity": pos.quantity,
                    "contract_size": pos.contract_size,
                }
            )
        return positions

    def remove_position(self, index: int):
        """Remove a position by index."""
        if index < 0 or index >= len(self.positions):
            raise IndexError("Position index out of range")
        self.positions.pop(index)

    def update_position(
        self,
        index: int,
        quantity: Optional[int] = None,
        strike: Optional[float] = None,
        expiry: Optional[datetime] = None,
        option_type: Optional[str] = None,
        symbol: Optional[str] = None,
        contract_size: Optional[int] = None,
        volatility: Optional[float] = None,
    ):
        """Update a position's properties by index."""
        if index < 0 or index >= len(self.positions):
            raise IndexError("Position index out of range")

        pos = self.positions[index]
        if quantity is not None:
            pos.quantity = quantity
        if contract_size is not None:
            pos.contract_size = contract_size
        if symbol is not None:
            pos.symbol = symbol

        strike_price = strike if strike is not None else pos.option.strike_price
        maturity_date = (
            expiry if expiry is not None else pos.option.maturity_date
        )
        opt_type = (
            option_type if option_type is not None else pos.option.option_type
        )

        # Handle volatility update
        if volatility is not None:
            option_volatility = volatility
            pos.custom_volatility = True
        else:
            # Keep existing volatility
            option_volatility = pos.option.volatility

        if (
            strike_price != pos.option.strike_price
            or maturity_date != pos.option.maturity_date
            or opt_type != pos.option.option_type
            or volatility is not None
        ):
            pos.option = AmericanOption(
                spot_price=self.spot_price,
                strike_price=strike_price,
                maturity_date=maturity_date,
                volatility=option_volatility,
                risk_free_rate=self.risk_free_rate,
                dividend_yield=self.dividend_yield,
                option_type=opt_type,
                valuation_date=self.valuation_date,
            )

    def to_dataframe(self) -> pd.DataFrame:
        """Convert portfolio to pandas DataFrame."""
        if not self.positions:
            return pd.DataFrame()

        data = [pos.to_dict() for pos in self.positions]
        df = pd.DataFrame(data)

        # Format maturity dates
        df["maturity"] = df["maturity"].apply(
            lambda x: (
                x.strftime("%Y-%m-%d")
                if isinstance(x, datetime)
                else pd.to_datetime(x).strftime("%Y-%m-%d")
            )
        )

        return df

    def update_market_conditions(
        self,
        spot_price: Optional[float] = None,
        volatility: Optional[float] = None,
        risk_free_rate: Optional[float] = None,
        dividend_yield: Optional[float] = None,
        valuation_date: Optional[datetime] = None,
        override_custom_volatility: bool = False,
    ):
        """
        Update market conditions for all positions.

        Args:
            spot_price: New spot price
            volatility: New volatility
            risk_free_rate: New risk-free rate
            dividend_yield: New dividend yield
            valuation_date: New valuation date
            override_custom_volatility: If True, update all positions'
            volatility including custom ones
        """
        if spot_price is not None:
            self.spot_price = spot_price
            for pos in self.positions:
                pos.option.update_spot_price(spot_price)

        if volatility is not None:
            self.volatility = volatility
            for pos in self.positions:
                # Only update if not custom volatility, or if override is requested
                if override_custom_volatility or not pos.custom_volatility:
                    pos.option.update_volatility(volatility)
                    # If overriding, mark as no longer custom
                    if override_custom_volatility:
                        pos.custom_volatility = False

        if valuation_date is not None:
            self.valuation_date = valuation_date
            for pos in self.positions:
                pos.option.update_valuation_date(valuation_date)

        # For rate changes, need to recreate options
        if risk_free_rate is not None or dividend_yield is not None:
            if risk_free_rate is not None:
                self.risk_free_rate = risk_free_rate
            if dividend_yield is not None:
                self.dividend_yield = dividend_yield

            # Recreate all positions with new rates, preserving custom volatility
            new_positions = []
            for pos in self.positions:
                new_option = AmericanOption(
                    spot_price=self.spot_price,
                    strike_price=pos.option.strike_price,
                    maturity_date=pos.option.maturity_date,
                    volatility=pos.option.volatility,  # Preserve existing volatility
                    risk_free_rate=self.risk_free_rate,
                    dividend_yield=self.dividend_yield,
                    option_type=pos.option.option_type,
                    valuation_date=self.valuation_date,
                )
                new_positions.append(
                    OptionPosition(
                        new_option,
                        pos.quantity,
                        contract_size=pos.contract_size,
                        symbol=pos.symbol,
                        custom_volatility=pos.custom_volatility,  # Preserve custom volatility flag
                    )
                )
            self.positions = new_positions

    def clear_positions(self):
        """Clear all positions from the portfolio."""
        self.positions = []

    def __repr__(self) -> str:
        """String representation of the portfolio."""
        return (
            f"OptionPortfolio(positions={len(self.positions)}, "
            f"value={self.total_value():.2f}, "
            f"delta={self.total_delta():.2f})"
        )
