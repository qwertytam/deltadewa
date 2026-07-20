"""Option position representation."""

import uuid
from datetime import datetime as dt
from typing import Any

from deltadewa.constants import ExerciseStyle
from deltadewa.valuation import OptionValuation


class OptionPosition:
    """Represents a position in an option."""

    def __init__(  # pylint: disable=too-many-arguments  # position config
        self,
        option: OptionValuation,
        quantity: int,
        exercise_style: ExerciseStyle,
        contract_size: int = 100,
        custom_volatility: bool = False,
        entry_spot: float | None = None,
        entry_date: dt | None = None,
        entry_premium: float | None = None,
        position_id: str = "",
    ) -> None:
        """Initialize an option position.

        Args:
            option: OptionValuation instance
            quantity: Number of contracts (positive for long, negative for
            short)
            exercise_style: ExerciseStyle.AMERICAN or ExerciseStyle.EUROPEAN
            contract_size: Number of underlying shares per option
            contract (e.g. 100)
            custom_volatility: Whether this position uses custom volatility
            entry_spot: Spot price when this position was entered, or None
            if unknown (e.g. imported from a file predating entry tracking)
            entry_date: Date this position was entered, or None if unknown
            entry_premium: Per-share option price paid at entry, or None if
            unknown.  Total cost-basis = entry_premium * abs(quantity) *
            contract_size.
            position_id: Stable runtime identity for this position.  When
            empty (the default) a fresh UUID is generated automatically.
            Pass an explicit value only when restoring a serialized position
            so that save→load preserves identity.

        """
        self.option = option
        self.quantity = quantity
        self.contract_size = contract_size
        self.custom_volatility = custom_volatility
        self.exercise_style = exercise_style
        self.entry_spot = entry_spot
        self.entry_date = entry_date
        self.entry_premium = entry_premium
        self.position_id = position_id if position_id else str(uuid.uuid4())

    def position_value(self) -> float:
        """Calculate the total value of the position.

        This multiplies the per-share option price by the number of contracts
        and the contract size (shares per contract).
        """
        return self.option.price() * self.quantity * self.contract_size

    def position_delta(self) -> float:
        """Calculate the total delta of the position (in shares)."""
        # option.delta() is per-share; multiply by contract size and number of
        # contracts
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

    def to_dict(self) -> dict[str, Any]:
        """Convert position to dict (optimized with batch Greek computation)."""
        # Use batch computation - gets all Greeks in one efficient call
        greeks = self.option.greeks()
        multiplier = self.quantity * self.contract_size

        return {
            "position_id": self.position_id,
            "option_type": self.option.option_type,
            "strike": self.option.strike_price,
            "maturity": self.option.maturity_date,
            "quantity": self.quantity,
            "exercise_style": self.exercise_style,
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
            "entry_spot": self.entry_spot,
            "entry_date": self.entry_date,
            "entry_premium": self.entry_premium,
        }
