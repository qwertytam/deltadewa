"""Option position representation."""

from deltadewa.american_option import AmericanOption


class OptionPosition:
    """Represents a position in an option."""

    def __init__(
        self,
        option: AmericanOption,
        quantity: int,
        contract_size: int = 100,
        custom_volatility: bool = False,
    ):
        """
        Initialize an option position.

        Args:
            option: AmericanOption instance
            quantity: Number of contracts (positive for long, negative for short)
            contract_size: Number of underlying shares per option contract (e.g. 100)
            custom_volatility: Whether this position uses custom volatility
        """
        self.option = option
        self.quantity = quantity
        self.contract_size = contract_size
        self.custom_volatility = custom_volatility

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
        """Convert position to dictionary (optimized with batch Greek computation)."""
        # Use batch computation - gets all Greeks in one efficient call
        greeks = self.option.greeks()
        multiplier = self.quantity * self.contract_size

        return {
            "type": self.option.option_type,
            "strike": self.option.strike_price,
            "maturity": self.option.maturity_date,
            "quantity": self.quantity,
            "price": greeks["price"],
            "position_value": greeks["price"] * multiplier,
            "delta": greeks["delta"],
            "position_delta": greeks["delta"] * multiplier,
            "gamma": greeks["gamma"],
            "position_gamma": greeks["gamma"] * multiplier,
            "vega": greeks["vega"],
            "position_vega": greeks["vega"] * multiplier,
            "theta": greeks["theta"],
            "position_theta": greeks["theta"] * multiplier,
            "rho": greeks["rho"],
            "position_rho": greeks["rho"] * multiplier,
            "contract_size": self.contract_size,
            "volatility": self.option.volatility,
            "custom_volatility": self.custom_volatility,
        }
