"""Core portfolio management and mixin composition."""

import datetime
from datetime import datetime as dt
from typing import TYPE_CHECKING, Any

import pandas as pd

from deltadewa.constants import ExerciseStyle, FDGridResolution, OptionType
from deltadewa.portfolio.greeks import GreeksMixin
from deltadewa.portfolio.monte_carlo import MonteCarloMixin
from deltadewa.portfolio.pnl import PnLMixin
from deltadewa.portfolio.position import OptionPosition
from deltadewa.portfolio.risk import RiskMixin
from deltadewa.valuation import OptionValuation

if TYPE_CHECKING:
    from deltadewa.portfolio._protocols import _PortfolioProtocol


class OptionPortfolioBase:
    """Base class for option portfolio management.

    Handles core portfolio functionality including position management,
    market conditions, and basic value calculations.
    """

    if TYPE_CHECKING:
        _self: "_PortfolioProtocol"

    def __init__(
        self,
        underlying_quantity: float = 0.0,
        spot_price: float = 100.0,
        volatility: float = 0.2,
        risk_free_rate: float = 0.05,
        dividend_yield: float = 0.0,
        valuation_date: dt | None = None,
        symbol: str = "UNKNOWN",
        default_exercise_style: ExerciseStyle = ExerciseStyle.AMERICAN,
    ) -> None:
        """Initialize option portfolio.

        Args:
            underlying_quantity: The underlying notional position to hedge
            spot_price: Current spot price of the underlying
            volatility: Market volatility
            risk_free_rate: Risk-free rate
            dividend_yield: Dividend yield
            valuation_date: Valuation date for all options (defaults to now)
            symbol: Underlying symbol or identifier for display/export
            default_exercise_style: Exercise style used by add_position()
            when its own exercise_style argument is omitted

        """
        self.positions: list[OptionPosition] = []
        self.underlying_quantity = underlying_quantity
        self.spot_price = spot_price
        self.volatility = volatility
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield
        self.valuation_date = valuation_date or dt.now(tz=datetime.UTC)
        self.symbol = symbol
        self.default_exercise_style = default_exercise_style
        self._monte_carlo_results: dict[str, Any] | None = None

        # Monte Carlo staleness tracking
        self.monte_carlo_stale: bool = False
        self.monte_carlo_timestamp: dt | None = None
        self.monte_carlo_last_modified: dt | None = None

    def add_position(
        self,
        strike_price: float,
        maturity_date: dt,
        quantity: int,
        option_type: OptionType = OptionType.CALL,
        contract_size: int = 100,
        volatility: float | None = None,
        exercise_style: ExerciseStyle | None = None,
        entry_spot: float | None = None,
        entry_date: dt | None = None,
    ) -> None:
        """Add an option position to the portfolio.

        Args:
            strike_price: Strike price of the option
            maturity_date: Maturity date of the option
            quantity: Number of contracts
            option_type: OptionType.CALL or OptionType.PUT
            contract_size: Number of underlying shares per option contract
            volatility: Optional position-specific volatility (uses portfolio
            default if None)
            exercise_style: ExerciseStyle.AMERICAN or ExerciseStyle.EUROPEAN
            (uses self.default_exercise_style if None)
            entry_spot: Spot price at entry (uses self.spot_price if None)
            entry_date: Date of entry (uses self.valuation_date if None)

        """
        # Use position-specific volatility or portfolio default
        if volatility is not None:
            option_volatility = volatility
        else:
            option_volatility = self.volatility

        custom_volatility = volatility is not None

        if exercise_style is None:
            exercise_style = self.default_exercise_style

        if entry_spot is None:
            entry_spot = self.spot_price
        if entry_date is None:
            entry_date = self.valuation_date

        option = OptionValuation(
            spot_price=self.spot_price,
            strike_price=strike_price,
            maturity_date=maturity_date,
            volatility=option_volatility,
            risk_free_rate=self.risk_free_rate,
            dividend_yield=self.dividend_yield,
            option_type=option_type,
            valuation_date=self.valuation_date,
            exercise_style=exercise_style,
            grid_resolution=FDGridResolution.STANDARD,
        )
        position = OptionPosition(
            option,
            quantity,
            contract_size=contract_size,
            custom_volatility=custom_volatility,
            exercise_style=exercise_style,
            entry_spot=entry_spot,
            entry_date=entry_date,
        )
        self.positions.append(position)

    def set_volatility(self, volatility: float) -> None:
        """Set portfolio volatility.

        Update positions without custom volatility.
        """
        self.volatility = volatility
        for pos in self.positions:
            if not pos.custom_volatility:
                pos.option.volatility = volatility

    def get_symbol(self) -> str:
        """Get the symbol of the portfolio."""
        return self.symbol

    @property
    def monte_carlo_results(self) -> dict[str, Any] | None:
        """Get Monte Carlo simulation results if available.

        Returns:
            Dictionary containing Monte Carlo analysis results, or None if not
            yet computed.

        """
        return self._monte_carlo_results

    @monte_carlo_results.setter
    def monte_carlo_results(self, results: dict[str, Any] | None) -> None:
        """Set Monte Carlo simulation results.

        Args:
            results: dictionary containing Monte Carlo analysis results

        """
        self._monte_carlo_results = results

    def total_value(self) -> float:
        """Calculate total portfolio value."""
        return sum(pos.position_value() for pos in self.positions)

    def total_underlying_value(self) -> float:
        """Calculate the value of the underlying notional position."""
        return self.underlying_quantity * self.spot_price

    def total_portfolio_value(self) -> float:
        """Total portfolio value including options and underlying notional."""
        return self.total_value() + self.total_underlying_value()

    def summary_stats(
        self: "_PortfolioProtocol",
    ) -> dict:
        """Get summary statistics of the portfolio.

        Returns:
            Dictionary containing:
            - total_positions: Number of option positions
            - total_value: Value of option positions only
            - total_underlying_value: Value of underlying position
            - total_portfolio_value: Total value (options + underlying)
            - total_delta: Portfolio delta from options only (if available)
            - underlying_quantity: Number of underlying shares
            - net_delta: Total delta exposure (if available)
            - hedge_ratio: Percentage of underlying hedged by options (if
            available)
            - delta_adjustment: Shares needed for delta neutrality (if
            available)
            - total_gamma, total_vega, total_theta, total_rho: Greek totals (if
            available)
            - volatility_min, volatility_max: Volatility range
            - custom_volatility_count: Positions with custom volatility

        """
        stats = {
            "total_positions": len(self.positions),
            "total_value": self.total_value(),
            "total_underlying_value": self.total_underlying_value(),
            "total_portfolio_value": self.total_portfolio_value(),
            "underlying_quantity": self.underlying_quantity,
        }

        # Use batch Greek calculation if available (optimized path)
        if hasattr(self, "all_greeks"):
            greeks = self.all_greeks()
            stats["total_delta"] = greeks["total_delta"]
            stats["net_delta"] = greeks["net_delta"]
            stats["total_gamma"] = greeks["total_gamma"]
            stats["total_vega"] = greeks["total_vega"]
            stats["total_theta"] = greeks["total_theta"]
            stats["total_rho"] = greeks["total_rho"]

            # Derived metrics
            if self.underlying_quantity != 0:
                stats["hedge_ratio"] = (
                    -(greeks["total_delta"] / self.underlying_quantity) * 100
                )
            else:
                stats["hedge_ratio"] = 0.0
            stats["delta_adjustment"] = -greeks["net_delta"]
        else:
            # Fallback to individual methods (existing code)
            if hasattr(self, "total_delta"):

                stats["total_delta"] = self.total_delta()
            if hasattr(self, "net_delta"):

                stats["net_delta"] = self.net_delta()
            if hasattr(self, "hedge_ratio"):

                stats["hedge_ratio"] = self.hedge_ratio()
            if hasattr(self, "delta_adjustment_needed"):

                stats["delta_adjustment"] = self.delta_adjustment_needed()
            if hasattr(self, "total_gamma"):

                stats["total_gamma"] = self.total_gamma()
            if hasattr(self, "total_vega"):

                stats["total_vega"] = self.total_vega()
            if hasattr(self, "total_theta"):

                stats["total_theta"] = self.total_theta()
            if hasattr(self, "total_rho"):

                stats["total_rho"] = self.total_rho()

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

    def summary(self: "_PortfolioProtocol") -> str:
        """Return a human-readable summary of the portfolio."""
        stats = self.summary_stats()
        parts = [f"Positions: {stats['total_positions']}"]
        parts.append(f"Value: ${stats['total_value']:,.2f}")

        if "net_delta" in stats:
            parts.append(f"Net Delta: {stats['net_delta']:,.2f}")
        if "total_gamma" in stats:
            parts.append(f"Gamma: {stats['total_gamma']:.4f}")
        if "total_vega" in stats:
            parts.append(f"Vega: {stats['total_vega']:.2f}")
        if "total_theta" in stats:
            parts.append(f"Theta: {stats['total_theta']:.2f}")

        return ", ".join(parts)

    def summary_market(self) -> str:
        """Return a summary of the market conditions."""
        return (
            f"Symbol: {self.symbol}, "
            f"Underlying Quantity: {self.underlying_quantity:,.0f} shares, "
            f"Spot Price: ${self.spot_price:,.2f}, "
            f"Volatility: {self.volatility:.2%}, "
            f"Risk-free Rate: {self.risk_free_rate:.2%}, "
            f"Dividend Yield: {self.dividend_yield:.2%}, "
            f"Valuation Date: {self.valuation_date.date()}"
        )

    def get_positions(self) -> list[dict]:
        """Return positions in a format suitable for widgets/UI."""
        return [
            {
                "option_type": pos.option.option_type,
                "strike": pos.option.strike_price,
                "expiry": pos.option.maturity_date.date(),
                "quantity": pos.quantity,
                "contract_size": pos.contract_size,
            }
            for pos in self.positions
        ]

    def remove_position(self, index: int) -> None:
        """Remove a position by index."""
        if index < 0 or index >= len(self.positions):
            raise IndexError("Position index out of range")
        self.positions.pop(index)

    def update_position(
        self,
        index: int,
        quantity: int | None = None,
        strike: float | None = None,
        expiry: dt | None = None,
        option_type: OptionType | None = None,
        contract_size: int | None = None,
        volatility: float | None = None,
        exercise_style: ExerciseStyle | None = None,
    ) -> None:
        """Update a position's properties by index."""
        if index < 0 or index >= len(self.positions):
            raise IndexError("Position index out of range")

        pos = self.positions[index]
        if quantity is not None:
            pos.quantity = quantity
        if contract_size is not None:
            pos.contract_size = contract_size

        strike_price = strike if strike is not None else pos.option.strike_price
        if expiry is not None:
            maturity_date = expiry
        else:
            maturity_date = pos.option.maturity_date
        if option_type is not None:
            opt_type = option_type
        else:
            opt_type = pos.option.option_type
        exercise_style = (
            exercise_style if exercise_style is not None else pos.exercise_style
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
            or exercise_style != pos.option.exercise_style
            or volatility is not None
        ):
            pos.option = OptionValuation(
                spot_price=self.spot_price,
                strike_price=strike_price,
                maturity_date=maturity_date,
                volatility=option_volatility,
                risk_free_rate=self.risk_free_rate,
                dividend_yield=self.dividend_yield,
                option_type=opt_type,
                valuation_date=self.valuation_date,
                exercise_style=exercise_style,
                grid_resolution=FDGridResolution.STANDARD,
            )
            # Keep OptionPosition.exercise_style in sync with the new
            # OptionValuation
            pos.exercise_style = pos.option.exercise_style

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
                if isinstance(x, dt)
                else pd.to_datetime(x).strftime("%Y-%m-%d")
            ),
        )

        return df

    def update_market_conditions(
        self,
        spot_price: float | None = None,
        volatility: float | None = None,
        risk_free_rate: float | None = None,
        dividend_yield: float | None = None,
        valuation_date: dt | None = None,
        override_custom_volatility: bool = False,
    ) -> None:
        """Update market conditions for all positions.

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
                # Only update if not custom volatility, or if override is
                # requested
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

            # Recreate all positions with new rates, preserving custom
            # volatility
            new_positions = []
            for pos in self.positions:
                new_option = OptionValuation(
                    spot_price=self.spot_price,
                    strike_price=pos.option.strike_price,
                    maturity_date=pos.option.maturity_date,
                    # Preserve existing volatility
                    volatility=pos.option.volatility,
                    risk_free_rate=self.risk_free_rate,
                    dividend_yield=self.dividend_yield,
                    option_type=pos.option.option_type,
                    valuation_date=self.valuation_date,
                    exercise_style=pos.exercise_style,
                    grid_resolution=pos.option.grid_resolution,
                )
                new_positions.append(
                    OptionPosition(
                        new_option,
                        pos.quantity,
                        contract_size=pos.contract_size,
                        # Preserve custom volatility flag
                        custom_volatility=pos.custom_volatility,
                        exercise_style=pos.exercise_style,
                    ),
                )
            self.positions = new_positions

    def clear_positions(self) -> None:
        """Clear all positions from the portfolio."""
        self.positions = []

    def __repr__(
        self: "_PortfolioProtocol",
    ) -> str:
        """Return string representation of the portfolio."""
        if hasattr(self, "net_delta"):
            s = (
                f"<OptionPortfolio: {len(self.positions)} "
                f"positions, Net Delta: {self.net_delta():.2f}>"
            )
            return s
        return f"<OptionPortfolio: {len(self.positions)} positions>"

    def get_furtherest_maturity(self) -> dt | None:
        """Get the furthest maturity date among all positions."""
        if not self.positions:
            return None
        return max(pos.option.maturity_date for pos in self.positions)

    def get_days_to_furthest_maturity(self) -> int | None:
        """Get days until the furthest maturity date."""
        furthest_maturity = self.get_furtherest_maturity()
        if furthest_maturity is None:
            return None
        delta = furthest_maturity - self.valuation_date
        return max(delta.days, 0)  # Ensure non-negative


# Final composed class with all mixins
class OptionPortfolio(
    GreeksMixin,
    PnLMixin,
    RiskMixin,
    MonteCarloMixin,
    OptionPortfolioBase,
):
    """Manages a portfolio of American options with hedge analysis.

    This class combines all portfolio functionality through mixins:
    - Core portfolio management (OptionPortfolioBase)
    - Greek calculations (GreeksMixin)
    - P&L calculations (PnLMixin)
    - Risk analysis (RiskMixin)
    - Monte Carlo simulation (MonteCarloMixin)

    For scenario analysis, use PortfolioAnalyzer from deltadewa.analysis.
    """

    pass  # noqa: PIE790  pylint: disable=unnecessary-pass
