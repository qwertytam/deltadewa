"""Option portfolio management and hedge analysis."""

from datetime import datetime
from typing import List, Optional
import pandas as pd
import numpy as np

from .american_option import AmericanOption


class OptionPosition:
    """Represents a position in an option."""

    def __init__(self, option: AmericanOption, quantity: int, contract_size: int = 100):
        """
        Initialize an option position.

        Args:
            option: AmericanOption instance
            quantity: Number of contracts (positive for long, negative for short)
        """
        self.option = option
        self.quantity = quantity
        # Number of underlying shares per option contract (e.g. 100)
        self.contract_size = contract_size

    def position_value(self) -> float:
        """Calculate the total value of the position.

        This multiplies the per-share option price by the number of contracts
        and the contract size (shares per contract).
        """
        return self.option.price() * self.quantity * self.contract_size

    def position_delta(self) -> float:
        """Calculate the total delta of the position (in shares)."""
        # option.delta() is per-share; multiply by contract size and number of contracts
        return self.option.delta() * self.quantity * self.contract_size

    def position_gamma(self) -> float:
        """Calculate the total gamma of the position."""
        return self.option.gamma() * self.quantity * self.contract_size

    def position_vega(self) -> float:
        """Calculate the total vega of the position."""
        return self.option.vega() * self.quantity * self.contract_size

    def position_theta(self) -> float:
        """Calculate the total theta of the position (per day)."""
        return self.option.theta() * self.quantity * self.contract_size

    def position_rho(self) -> float:
        """Calculate the total rho of the position."""
        return self.option.rho() * self.quantity * self.contract_size

    def to_dict(self) -> dict:
        """Convert position to dictionary."""
        greeks = self.option.greeks()
        return {
            "type": self.option.option_type,
            "strike": self.option.strike_price,
            "maturity": self.option.maturity_date,
            "quantity": self.quantity,
            "price": greeks["price"],
            "position_value": self.position_value(),
            "delta": greeks["delta"],
            "position_delta": self.position_delta(),
            "gamma": greeks["gamma"],
            "position_gamma": self.position_gamma(),
            "vega": greeks["vega"],
            "position_vega": self.position_vega(),
            "theta": greeks["theta"],
            "position_theta": self.position_theta(),
            "rho": greeks["rho"],
            "position_rho": self.position_rho(),
            "contract_size": self.contract_size,
        }


class OptionPortfolio:
    """
    Manages a portfolio of American options with hedge analysis.
    """

    def __init__(
        self,
        notional_position: float = 0.0,
        spot_price: float = 100.0,
        volatility: float = 0.2,
        risk_free_rate: float = 0.05,
        dividend_yield: float = 0.0,
    ):
        """
        Initialize option portfolio.

        Args:
            notional_position: The underlying notional position to hedge
            spot_price: Current spot price of the underlying
            volatility: Market volatility
            risk_free_rate: Risk-free rate
            dividend_yield: Dividend yield
        """
        self.positions: List[OptionPosition] = []
        self.notional_position = notional_position
        self.spot_price = spot_price
        self.volatility = volatility
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield

    def add_position(
        self,
        strike_price: float,
        maturity_date: datetime,
        quantity: int,
        option_type: str = "call",
    ):
        """
        Add an option position to the portfolio.

        Args:
            strike_price: Strike price of the option
            maturity_date: Maturity date of the option
            quantity: Number of contracts
            option_type: "call" or "put"
        """
        option = AmericanOption(
            spot_price=self.spot_price,
            strike_price=strike_price,
            maturity_date=maturity_date,
            volatility=self.volatility,
            risk_free_rate=self.risk_free_rate,
            dividend_yield=self.dividend_yield,
            option_type=option_type,
        )
        position = OptionPosition(option, quantity)
        self.positions.append(position)

    def total_value(self) -> float:
        """Calculate total portfolio value."""
        return sum(pos.position_value() for pos in self.positions)

    def total_underlying_value(self) -> float:
        """Calculate the value of the underlying notional position."""
        return self.notional_position * self.spot_price

    def total_portfolio_value(self) -> float:
        """Total portfolio value including options and underlying notional."""
        return self.total_value() + self.total_underlying_value()

    def total_delta(self) -> float:
        """Calculate total portfolio delta."""
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
        Calculate net delta including the notional position.

        Returns:
            Net delta exposure (positive = net long, negative = net short)
        """
        return self.total_delta() + self.notional_position

    def hedge_ratio(self) -> float:
        """
        Calculate the hedge ratio (how much of the notional is hedged).

        Returns:
            Hedge ratio as a percentage
        """
        if self.notional_position == 0:
            return 0.0
        return -(self.total_delta() / self.notional_position) * 100

    def delta_adjustment_needed(self) -> float:
        """
        Calculate the delta adjustment needed to achieve delta neutrality.

        Returns:
            Number of shares to buy/sell to achieve delta neutrality
        """
        return -self.net_delta()

    def summary_stats(self) -> dict:
        """Get summary statistics of the portfolio."""
        return {
            "total_positions": len(self.positions),
            "total_value": self.total_value(),
            "total_underlying_value": self.total_underlying_value(),
            "total_portfolio_value": self.total_portfolio_value(),
            "total_delta": self.total_delta(),
            "notional_position": self.notional_position,
            "net_delta": self.net_delta(),
            "hedge_ratio": self.hedge_ratio(),
            "delta_adjustment": self.delta_adjustment_needed(),
            "total_gamma": self.total_gamma(),
            "total_vega": self.total_vega(),
            "total_theta": self.total_theta(),
            "total_rho": self.total_rho(),
        }

    def to_dataframe(self) -> pd.DataFrame:
        """Convert portfolio to pandas DataFrame."""
        if not self.positions:
            return pd.DataFrame()

        data = [pos.to_dict() for pos in self.positions]
        df = pd.DataFrame(data)

        # Format maturity dates
        df["maturity"] = pd.to_datetime(df["maturity"]).dt.strftime("%Y-%m-%d")

        return df

    def update_market_conditions(
        self,
        spot_price: Optional[float] = None,
        volatility: Optional[float] = None,
        risk_free_rate: Optional[float] = None,
        dividend_yield: Optional[float] = None,
    ):
        """
        Update market conditions for all positions.

        Args:
            spot_price: New spot price
            volatility: New volatility
            risk_free_rate: New risk-free rate
            dividend_yield: New dividend yield
        """
        if spot_price is not None:
            self.spot_price = spot_price
            for pos in self.positions:
                pos.option.update_spot_price(spot_price)

        if volatility is not None:
            self.volatility = volatility
            for pos in self.positions:
                pos.option.update_volatility(volatility)

        # For rate changes, need to recreate options
        if risk_free_rate is not None or dividend_yield is not None:
            if risk_free_rate is not None:
                self.risk_free_rate = risk_free_rate
            if dividend_yield is not None:
                self.dividend_yield = dividend_yield

            # Recreate all positions with new rates
            new_positions = []
            for pos in self.positions:
                new_option = AmericanOption(
                    spot_price=self.spot_price,
                    strike_price=pos.option.strike_price,
                    maturity_date=pos.option.maturity_date,
                    volatility=self.volatility,
                    risk_free_rate=self.risk_free_rate,
                    dividend_yield=self.dividend_yield,
                    option_type=pos.option.option_type,
                )
                new_positions.append(OptionPosition(new_option, pos.quantity))
            self.positions = new_positions

    def scenario_analysis(
        self, spot_range: np.ndarray, vol_range: Optional[np.ndarray] = None
    ) -> pd.DataFrame:
        """
        Perform scenario analysis across different spot prices and volatilities.

        Args:
            spot_range: Array of spot prices to analyze
            vol_range: Array of volatilities to analyze (optional)

        Returns:
            DataFrame with scenario results
        """
        results = []

        if vol_range is None:
            # Single volatility analysis
            for spot in spot_range:
                # Temporarily update spot
                original_spot = self.spot_price
                self.update_market_conditions(spot_price=spot)

                results.append(
                    {
                        "spot_price": spot,
                        "volatility": self.volatility,
                        "portfolio_value": self.total_value(),
                        "total_delta": self.total_delta(),
                        "net_delta": self.net_delta(),
                        "total_gamma": self.total_gamma(),
                        "total_vega": self.total_vega(),
                    }
                )

                # Restore original spot
                self.update_market_conditions(spot_price=original_spot)
        else:
            # Full grid analysis
            for spot in spot_range:
                for vol in vol_range:
                    original_spot = self.spot_price
                    original_vol = self.volatility

                    self.update_market_conditions(spot_price=spot, volatility=vol)

                    results.append(
                        {
                            "spot_price": spot,
                            "volatility": vol,
                            "portfolio_value": self.total_value(),
                            "total_delta": self.total_delta(),
                            "net_delta": self.net_delta(),
                            "total_gamma": self.total_gamma(),
                            "total_vega": self.total_vega(),
                        }
                    )

                    self.update_market_conditions(spot_price=original_spot, volatility=original_vol)

        return pd.DataFrame(results)

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
