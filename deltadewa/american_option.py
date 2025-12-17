"""American option pricing using QuantLib with Bjerksund-Stensland model."""

from datetime import datetime
from typing import Optional

import QuantLib as ql
import numpy as np


class AmericanOption:
    """
    American option pricing using the Bjerksund-Stensland approximation model.
    
    This class provides pricing and Greeks calculation for American options.
    """

    def __init__(
        self,
        spot_price: float,
        strike_price: float,
        maturity_date: datetime,
        volatility: float,
        risk_free_rate: float,
        dividend_yield: float,
        option_type: str = "call",
        valuation_date: Optional[datetime] = None,
    ):
        """
        Initialize American option.

        Args:
            spot_price: Current price of the underlying asset
            strike_price: Strike price of the option
            maturity_date: Expiration date of the option
            volatility: Implied volatility (annualized)
            risk_free_rate: Risk-free interest rate (annualized)
            dividend_yield: Dividend yield (annualized)
            option_type: "call" or "put"
            valuation_date: Date for valuation (defaults to today)
        """
        self.spot_price = spot_price
        self.strike_price = strike_price
        self.maturity_date = maturity_date
        self.volatility = volatility
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield
        self.option_type = option_type.lower()
        self.valuation_date = valuation_date or datetime.now()

        # Set up QuantLib objects
        self._setup_quantlib()

    def _setup_quantlib(self):
        """Set up QuantLib calculation environment."""
        # Convert dates to QuantLib dates
        self.ql_valuation_date = ql.Date(
            self.valuation_date.day,
            self.valuation_date.month,
            self.valuation_date.year,
        )
        self.ql_maturity_date = ql.Date(
            self.maturity_date.day,
            self.maturity_date.month,
            self.maturity_date.year,
        )

        # Set the evaluation date
        ql.Settings.instance().evaluationDate = self.ql_valuation_date

        # Set up the option
        if self.option_type == "call":
            payoff = ql.PlainVanillaPayoff(ql.Option.Call, self.strike_price)
        elif self.option_type == "put":
            payoff = ql.PlainVanillaPayoff(ql.Option.Put, self.strike_price)
        else:
            raise ValueError(f"Invalid option type: {self.option_type}")

        # American exercise
        exercise = ql.AmericanExercise(self.ql_valuation_date, self.ql_maturity_date)

        # Create the option
        self.option = ql.VanillaOption(payoff, exercise)

        # Set up market data with SimpleQuote for spot (allows updates)
        self.spot_quote = ql.SimpleQuote(self.spot_price)
        self.spot_handle = ql.QuoteHandle(self.spot_quote)
        self.flat_ts = ql.YieldTermStructureHandle(
            ql.FlatForward(self.ql_valuation_date, self.risk_free_rate, ql.Actual365Fixed())
        )
        self.dividend_ts = ql.YieldTermStructureHandle(
            ql.FlatForward(self.ql_valuation_date, self.dividend_yield, ql.Actual365Fixed())
        )
        self.flat_vol_ts = ql.BlackVolTermStructureHandle(
            ql.BlackConstantVol(
                self.ql_valuation_date, ql.NullCalendar(), self.volatility, ql.Actual365Fixed()
            )
        )

        # Black-Scholes-Merton process
        self.bsm_process = ql.BlackScholesMertonProcess(
            self.spot_handle, self.dividend_ts, self.flat_ts, self.flat_vol_ts
        )

        # Use Finite Difference engine for American options with Greeks support
        # This uses implicit finite differences which provides accurate Greeks
        self.option.setPricingEngine(
            ql.FdBlackScholesVanillaEngine(self.bsm_process, 200, 200)
        )

    def price(self) -> float:
        """Calculate the option price."""
        return self.option.NPV()

    def delta(self) -> float:
        """Calculate Delta (sensitivity to underlying price)."""
        try:
            return self.option.delta()
        except RuntimeError:
            # If delta not available, compute numerically
            h = 0.01
            original_spot = self.spot_price
            self.update_spot_price(original_spot + h)
            price_up = self.option.NPV()
            self.update_spot_price(original_spot - h)
            price_down = self.option.NPV()
            self.update_spot_price(original_spot)
            return (price_up - price_down) / (2 * h)

    def gamma(self) -> float:
        """Calculate Gamma (second derivative with respect to underlying price)."""
        try:
            return self.option.gamma()
        except RuntimeError:
            # If gamma not available, compute numerically
            h = 0.01
            original_spot = self.spot_price
            self.update_spot_price(original_spot + h)
            delta_up = self.delta()
            self.update_spot_price(original_spot - h)
            delta_down = self.delta()
            self.update_spot_price(original_spot)
            return (delta_up - delta_down) / (2 * h)

    def vega(self) -> float:
        """Calculate Vega (sensitivity to volatility)."""
        try:
            return self.option.vega() / 100.0  # Convert to 1% change
        except RuntimeError:
            # If vega not available, compute numerically
            h = 0.01
            original_vol = self.volatility
            self.update_volatility(original_vol + h)
            price_up = self.option.NPV()
            self.update_volatility(original_vol - h)
            price_down = self.option.NPV()
            self.update_volatility(original_vol)
            return (price_up - price_down) / 2.0  # Already in terms of 1% change

    def theta(self) -> float:
        """Calculate Theta (time decay per day)."""
        try:
            return self.option.theta() / 365.0  # Convert to per day
        except RuntimeError:
            # If theta not available, compute numerically
            # Move evaluation date forward by 1 day
            current_date = ql.Settings.instance().evaluationDate
            ql.Settings.instance().evaluationDate = current_date + 1
            price_tomorrow = self.option.NPV()
            ql.Settings.instance().evaluationDate = current_date
            price_today = self.option.NPV()
            return price_tomorrow - price_today

    def rho(self) -> float:
        """Calculate Rho (sensitivity to interest rate)."""
        try:
            return self.option.rho() / 100.0  # Convert to 1% change
        except RuntimeError:
            # If rho not available, compute numerically
            h = 0.01
            original_rate = self.risk_free_rate
            self.risk_free_rate = original_rate + h
            self._setup_quantlib()
            price_up = self.option.NPV()
            self.risk_free_rate = original_rate - h
            self._setup_quantlib()
            price_down = self.option.NPV()
            self.risk_free_rate = original_rate
            self._setup_quantlib()
            return (price_up - price_down) / 2.0  # Already in terms of 1% change

    def greeks(self) -> dict:
        """Calculate all Greeks."""
        return {
            "price": self.price(),
            "delta": self.delta(),
            "gamma": self.gamma(),
            "vega": self.vega(),
            "theta": self.theta(),
            "rho": self.rho(),
        }

    def intrinsic_value(self) -> float:
        """Calculate intrinsic value of the option."""
        if self.option_type == "call":
            return max(0, self.spot_price - self.strike_price)
        else:
            return max(0, self.strike_price - self.spot_price)

    def time_value(self) -> float:
        """Calculate time value of the option."""
        return self.price() - self.intrinsic_value()

    def update_spot_price(self, new_spot_price: float):
        """Update the spot price and recalculate."""
        self.spot_price = new_spot_price
        self.spot_quote.setValue(new_spot_price)

    def update_volatility(self, new_volatility: float):
        """Update the volatility and recalculate."""
        self.volatility = new_volatility
        self._setup_quantlib()

    def __repr__(self) -> str:
        """String representation of the option."""
        return (
            f"AmericanOption(type={self.option_type}, "
            f"spot={self.spot_price:.2f}, "
            f"strike={self.strike_price:.2f}, "
            f"maturity={self.maturity_date.strftime('%Y-%m-%d')}, "
            f"price={self.price():.4f})"
        )
