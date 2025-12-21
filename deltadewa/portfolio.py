"""Option portfolio management and hedge analysis."""

from datetime import datetime
from typing import List, Optional
import pandas as pd
import numpy as np

from .american_option import AmericanOption


class OptionPosition:
    """Represents a position in an option."""

    def __init__(
        self,
        option: AmericanOption,
        quantity: int,
        contract_size: int = 100,
        symbol: str = "UNKNOWN",
    ):
        """
        Initialize an option position.

        Args:
            option: AmericanOption instance
            quantity: Number of contracts (positive for long, negative for short)
            contract_size: Number of underlying shares per option contract (e.g. 100)
            symbol: Underlying symbol or identifier for display/export
        """
        self.option = option
        self.quantity = quantity
        self.contract_size = contract_size
        self.symbol = symbol

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
            "symbol": self.symbol,
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

    def add_position(
        self,
        strike_price: float,
        maturity_date: datetime,
        quantity: int,
        option_type: str = "call",
        symbol: str = "UNKNOWN",
        contract_size: int = 100,
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
        """
        option = AmericanOption(
            spot_price=self.spot_price,
            strike_price=strike_price,
            maturity_date=maturity_date,
            volatility=self.volatility,
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
        )
        self.positions.append(position)

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

    def summary_stats(self) -> dict:
        """Get summary statistics of the portfolio."""
        return {
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
        maturity_date = expiry if expiry is not None else pos.option.maturity_date
        opt_type = option_type if option_type is not None else pos.option.option_type

        if (
            strike_price != pos.option.strike_price
            or maturity_date != pos.option.maturity_date
            or opt_type != pos.option.option_type
        ):
            pos.option = AmericanOption(
                spot_price=self.spot_price,
                strike_price=strike_price,
                maturity_date=maturity_date,
                volatility=self.volatility,
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
        df["maturity"] = pd.to_datetime(df["maturity"]).dt.strftime("%Y-%m-%d")

        return df

    def update_market_conditions(
        self,
        spot_price: Optional[float] = None,
        volatility: Optional[float] = None,
        risk_free_rate: Optional[float] = None,
        dividend_yield: Optional[float] = None,
        valuation_date: Optional[datetime] = None,
    ):
        """
        Update market conditions for all positions.

        Args:
            spot_price: New spot price
            volatility: New volatility
            risk_free_rate: New risk-free rate
            dividend_yield: New dividend yield
            valuation_date: New valuation date
        """
        if spot_price is not None:
            self.spot_price = spot_price
            for pos in self.positions:
                pos.option.update_spot_price(spot_price)

        if volatility is not None:
            self.volatility = volatility
            for pos in self.positions:
                pos.option.update_volatility(volatility)

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
                    valuation_date=self.valuation_date,
                )
                new_positions.append(OptionPosition(new_option, pos.quantity, pos.contract_size))
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
        original_spot = self.spot_price
        original_vol = self.volatility

        if vol_range is None:
            # Single volatility analysis
            for spot in spot_range:
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
        else:
            # Full grid analysis
            for spot in spot_range:
                for vol in vol_range:
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

    def calculate_net_debit(self) -> float:
        """
        Calculate the net debit/credit for implementing the portfolio.
        
        Returns:
            Net debit (positive) or net credit (negative) in dollars
        """
        return self.total_value()

    def calculate_pnl_at_expiry(
        self, spot_price_at_expiry: float, include_underlying: bool = False
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
                intrinsic = max(0, spot_price_at_expiry - pos.option.strike_price)
            else:  # put
                intrinsic = max(0, pos.option.strike_price - spot_price_at_expiry)
            
            pnl += intrinsic * pos.quantity * pos.contract_size
        
        # Add underlying P&L if requested
        if include_underlying and self.underlying_quantity != 0:
            underlying_pnl = (spot_price_at_expiry - self.spot_price) * self.underlying_quantity
            pnl += underlying_pnl
        
        return pnl

    def calculate_max_loss_options(
        self, spot_range: Optional[np.ndarray] = None
    ) -> dict:
        """
        Calculate maximum loss from options positions only.
        
        Args:
            spot_range: Array of spot prices to analyze (optional)
            
        Returns:
            Dict with 'max_loss', 'spot_at_max_loss', and 'is_unlimited'
        """
        if spot_range is None:
            # Create reasonable range around current spot
            spot_min = max(0.01, self.spot_price * 0.5)
            spot_max = self.spot_price * 2.0
            spot_range = np.linspace(spot_min, spot_max, 200)
        
        max_loss = 0.0
        spot_at_max_loss = self.spot_price
        
        for spot in spot_range:
            pnl = self.calculate_pnl_at_expiry(spot, include_underlying=False)
            if pnl < max_loss:
                max_loss = pnl
                spot_at_max_loss = spot
        
        # Check for unlimited loss (naked short positions)
        has_naked_shorts = any(
            pos.quantity < 0 for pos in self.positions
        )
        
        return {
            "max_loss": max_loss,
            "spot_at_max_loss": spot_at_max_loss,
            "is_unlimited": False,  # For now, conservatively assume bounded
        }

    def calculate_max_profit_options(
        self, spot_range: Optional[np.ndarray] = None
    ) -> dict:
        """
        Calculate maximum profit from options positions only.
        
        Args:
            spot_range: Array of spot prices to analyze (optional)
            
        Returns:
            Dict with 'max_profit', 'spot_at_max_profit', and 'is_unlimited'
        """
        if spot_range is None:
            # Create reasonable range around current spot
            spot_min = max(0.01, self.spot_price * 0.5)
            spot_max = self.spot_price * 2.0
            spot_range = np.linspace(spot_min, spot_max, 200)
        
        max_profit = float('-inf')
        spot_at_max_profit = self.spot_price
        
        for spot in spot_range:
            pnl = self.calculate_pnl_at_expiry(spot, include_underlying=False)
            if pnl > max_profit:
                max_profit = pnl
                spot_at_max_profit = spot
        
        return {
            "max_profit": max_profit,
            "spot_at_max_profit": spot_at_max_profit,
            "is_unlimited": False,  # For now, conservatively assume bounded
        }

    def calculate_max_loss_total(
        self, spot_range: Optional[np.ndarray] = None
    ) -> dict:
        """
        Calculate maximum loss including underlying position.
        
        Args:
            spot_range: Array of spot prices to analyze (optional)
            
        Returns:
            Dict with 'max_loss', 'spot_at_max_loss', and 'is_unlimited'
        """
        if spot_range is None:
            # Create reasonable range around current spot
            spot_min = max(0.01, self.spot_price * 0.5)
            spot_max = self.spot_price * 2.0
            spot_range = np.linspace(spot_min, spot_max, 200)
        
        max_loss = 0.0
        spot_at_max_loss = self.spot_price
        
        for spot in spot_range:
            pnl = self.calculate_pnl_at_expiry(spot, include_underlying=True)
            if pnl < max_loss:
                max_loss = pnl
                spot_at_max_loss = spot
        
        # Check if loss is potentially unlimited
        is_unlimited = False
        if self.underlying_quantity > 0:
            # Long underlying has unlimited upside, but loss capped at zero
            pass
        elif self.underlying_quantity < 0:
            # Short underlying has unlimited loss potential
            is_unlimited = True
        
        return {
            "max_loss": max_loss,
            "spot_at_max_loss": spot_at_max_loss,
            "is_unlimited": is_unlimited,
        }

    def calculate_max_profit_total(
        self, spot_range: Optional[np.ndarray] = None
    ) -> dict:
        """
        Calculate maximum profit including underlying position.
        
        Args:
            spot_range: Array of spot prices to analyze (optional)
            
        Returns:
            Dict with 'max_profit', 'spot_at_max_profit', and 'is_unlimited'
        """
        if spot_range is None:
            # Create reasonable range around current spot
            spot_min = max(0.01, self.spot_price * 0.5)
            spot_max = self.spot_price * 2.0
            spot_range = np.linspace(spot_min, spot_max, 200)
        
        max_profit = float('-inf')
        spot_at_max_profit = self.spot_price
        
        for spot in spot_range:
            pnl = self.calculate_pnl_at_expiry(spot, include_underlying=True)
            if pnl > max_profit:
                max_profit = pnl
                spot_at_max_profit = spot
        
        # Check if profit is potentially unlimited
        is_unlimited = False
        if self.underlying_quantity > 0:
            # Long underlying has unlimited upside
            is_unlimited = True
        
        return {
            "max_profit": max_profit,
            "spot_at_max_profit": spot_at_max_profit,
            "is_unlimited": is_unlimited,
        }

    def calculate_breakeven_points(
        self, spot_range: Optional[np.ndarray] = None, include_underlying: bool = False
    ) -> List[float]:
        """
        Calculate breakeven spot prices at expiration.
        
        Args:
            spot_range: Array of spot prices to analyze (optional)
            include_underlying: Whether to include underlying position
            
        Returns:
            List of breakeven spot prices
        """
        if spot_range is None:
            # Create reasonable range around current spot
            spot_min = max(0.01, self.spot_price * 0.5)
            spot_max = self.spot_price * 2.0
            spot_range = np.linspace(spot_min, spot_max, 500)
        
        breakeven_points = []
        prev_pnl = None
        
        for spot in spot_range:
            pnl = self.calculate_pnl_at_expiry(spot, include_underlying=include_underlying)
            
            # Check for sign change (crossing zero)
            if prev_pnl is not None:
                if (prev_pnl < 0 and pnl >= 0) or (prev_pnl > 0 and pnl <= 0):
                    # Interpolate to find more precise breakeven
                    breakeven_points.append(spot)
            
            prev_pnl = pnl
        
        return breakeven_points

    def calculate_probability_of_profit(
        self,
        method: str = 'monte_carlo',
        num_simulations: int = 10000,
        include_underlying: bool = False,
        days_to_expiry: Optional[int] = None,
    ) -> dict:
        """
        Calculate probability that portfolio will be profitable at expiration.
        
        Args:
            method: Calculation method ('monte_carlo' or 'normal')
            num_simulations: Number of Monte Carlo simulations
            include_underlying: Whether to include underlying position
            days_to_expiry: Days to expiration (uses nearest maturity if None)
            
        Returns:
            Dict with 'probability', 'expected_value', and 'breakeven_points'
        """
        # Determine time to expiration
        if days_to_expiry is None:
            if not self.positions:
                days_to_expiry = 30
            else:
                # Use the nearest maturity
                min_maturity = min(pos.option.maturity_date for pos in self.positions)
                days_to_expiry = max(1, (min_maturity - self.valuation_date).days)
        
        time_to_expiry = days_to_expiry / 365.0
        
        if method == 'monte_carlo':
            # Monte Carlo simulation
            profitable_count = 0
            total_pnl = 0.0
            
            for _ in range(num_simulations):
                # Simulate final spot price using geometric Brownian motion
                z = np.random.standard_normal()
                drift = (self.risk_free_rate - self.dividend_yield - 0.5 * self.volatility**2) * time_to_expiry
                diffusion = self.volatility * np.sqrt(time_to_expiry) * z
                final_spot = self.spot_price * np.exp(drift + diffusion)
                
                # Calculate P&L at this simulated spot
                pnl = self.calculate_pnl_at_expiry(final_spot, include_underlying=include_underlying)
                total_pnl += pnl
                
                if pnl > 0:
                    profitable_count += 1
            
            probability = profitable_count / num_simulations
            expected_value = total_pnl / num_simulations
        
        else:  # 'normal' approximation
            # For simplicity, use Monte Carlo with normal distribution
            # This is a simplified implementation
            probability = 0.5  # Placeholder
            expected_value = 0.0
        
        # Calculate breakeven points
        breakeven_points = self.calculate_breakeven_points(include_underlying=include_underlying)
        
        return {
            'probability': probability,
            'expected_value': expected_value,
            'breakeven_points': breakeven_points,
        }

    def risk_reward_analysis(
        self,
        spot_range: Optional[np.ndarray] = None,
        num_simulations: int = 10000,
    ) -> dict:
        """
        Generate comprehensive risk/reward analysis of the portfolio.
        
        Args:
            spot_range: Array of spot prices to analyze (optional)
            num_simulations: Number of Monte Carlo simulations for probability
            
        Returns:
            Dict containing all risk/reward metrics
        """
        net_debit = self.calculate_net_debit()
        
        # Options only analysis
        max_loss_opts = self.calculate_max_loss_options(spot_range)
        max_profit_opts = self.calculate_max_profit_options(spot_range)
        breakeven_opts = self.calculate_breakeven_points(spot_range, include_underlying=False)
        
        # Total portfolio analysis
        max_loss_total = self.calculate_max_loss_total(spot_range)
        max_profit_total = self.calculate_max_profit_total(spot_range)
        breakeven_total = self.calculate_breakeven_points(spot_range, include_underlying=True)
        
        # Probability analysis
        prob_analysis = self.calculate_probability_of_profit(
            method='monte_carlo',
            num_simulations=num_simulations,
            include_underlying=True,
        )
        
        return {
            'net_debit': net_debit,
            'max_loss_options': max_loss_opts,
            'max_profit_options': max_profit_opts,
            'breakeven_options': breakeven_opts,
            'max_loss_total': max_loss_total,
            'max_profit_total': max_profit_total,
            'breakeven_total': breakeven_total,
            'probability_of_profit': prob_analysis['probability'],
            'expected_value': prob_analysis['expected_value'],
        }

    def print_risk_reward_summary(self, spot_range: Optional[np.ndarray] = None):
        """
        Print a formatted risk/reward summary of the portfolio.
        
        Args:
            spot_range: Array of spot prices to analyze (optional)
        """
        analysis = self.risk_reward_analysis(spot_range)
        
        print("=" * 80)
        print("PORTFOLIO RISK/REWARD ANALYSIS")
        print("=" * 80)
        print()
        
        # Capital Requirements
        print("CAPITAL REQUIREMENTS:")
        net_debit = analysis['net_debit']
        if net_debit > 0:
            print(f"  Net Debit: ${net_debit:,.2f} (capital required to implement)")
        else:
            print(f"  Net Credit: ${-net_debit:,.2f} (capital received)")
        print()
        
        # Options Only Risk/Reward
        print("OPTIONS ONLY RISK/REWARD:")
        max_loss_opts = analysis['max_loss_options']
        max_profit_opts = analysis['max_profit_options']
        
        if max_loss_opts['is_unlimited']:
            print("  Max Loss: UNLIMITED (naked short positions)")
        else:
            print(f"  Max Loss: ${-max_loss_opts['max_loss']:,.2f}", end="")
            if net_debit != 0:
                loss_pct = (-max_loss_opts['max_loss'] / abs(net_debit)) * 100
                print(f" ({loss_pct:.1f}% of net debit)")
            else:
                print()
            print(f"    └─ Occurs at spot price: ${max_loss_opts['spot_at_max_loss']:.2f}")
        
        if max_profit_opts['is_unlimited']:
            print("  Max Profit: UNLIMITED")
        else:
            print(f"  Max Profit: ${max_profit_opts['max_profit']:,.2f}", end="")
            if net_debit > 0:
                roi = (max_profit_opts['max_profit'] / net_debit) * 100
                print(f" ({roi:.1f}% return on net debit)")
            else:
                print()
            print(f"    └─ Occurs at spot price: ${max_profit_opts['spot_at_max_profit']:.2f}")
        
        if analysis['breakeven_options']:
            breakevens_str = ", ".join([f"${be:.2f}" for be in analysis['breakeven_options']])
            print(f"  Breakeven Points: {breakevens_str}")
        else:
            print("  Breakeven Points: None identified")
        print()
        
        # Total Portfolio Risk/Reward
        if self.underlying_quantity != 0:
            print("TOTAL PORTFOLIO RISK/REWARD (Options + Underlying):")
            max_loss_total = analysis['max_loss_total']
            max_profit_total = analysis['max_profit_total']
            
            if max_loss_total['is_unlimited']:
                print("  Max Loss: UNLIMITED (short underlying position)")
            else:
                portfolio_value = self.total_portfolio_value()
                print(f"  Max Loss: ${-max_loss_total['max_loss']:,.2f}", end="")
                if portfolio_value > 0:
                    loss_pct = (-max_loss_total['max_loss'] / portfolio_value) * 100
                    print(f" ({loss_pct:.1f}% of portfolio value)")
                else:
                    print()
                print(f"    └─ Occurs at spot price: ${max_loss_total['spot_at_max_loss']:.2f}")
            
            if max_profit_total['is_unlimited']:
                if self.underlying_quantity > 0:
                    print("  Max Profit: UNLIMITED (long underlying position)")
                else:
                    print("  Max Profit: UNLIMITED")
                print("    └─ Profit increases with spot price")
            else:
                print(f"  Max Profit: ${max_profit_total['max_profit']:,.2f}", end="")
                if portfolio_value > 0:
                    profit_pct = (max_profit_total['max_profit'] / portfolio_value) * 100
                    print(f" ({profit_pct:.1f}% of portfolio value)")
                else:
                    print()
                print(f"    └─ Occurs at spot price: ${max_profit_total['spot_at_max_profit']:.2f}")
            
            if analysis['breakeven_total']:
                breakevens_str = ", ".join([f"${be:.2f}" for be in analysis['breakeven_total']])
                print(f"  Breakeven Points: {breakevens_str}")
            else:
                print("  Breakeven Points: None identified")
            print()
        
        # Probability Analysis
        print("PROBABILITY ANALYSIS:")
        prob = analysis['probability_of_profit']
        print(f"  Chance of Profit: {prob*100:.1f}%")
        print(f"  Expected Value: ${analysis['expected_value']:,.2f} (probabilistic weighted average)")
        print()
        
        # Risk/Reward Ratio
        if not max_loss_opts['is_unlimited'] and not max_profit_opts['is_unlimited']:
            if max_profit_opts['max_profit'] > 0 and max_loss_opts['max_loss'] < 0:
                rr_ratio = -max_loss_opts['max_loss'] / max_profit_opts['max_profit']
                print(f"RISK/REWARD RATIO: {rr_ratio:.2f}:1 (max loss to max profit)")
        print("=" * 80)

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
