"""Core portfolio management and mixin composition."""

from dataclasses import replace as dataclass_replace
from datetime import datetime as dt
from typing import TYPE_CHECKING, Any

import pandas as pd

from deltadewa.clock import program_now, program_trading_date
from deltadewa.constants import ExerciseStyle, FDGridResolution, OptionType
from deltadewa.portfolio.greeks import GreeksMixin
from deltadewa.portfolio.monte_carlo import MonteCarloMixin
from deltadewa.portfolio.pnl import PnLMixin
from deltadewa.portfolio.position import OptionPosition
from deltadewa.portfolio.risk import RiskMixin
from deltadewa.portfolio.stamps import MarketParameterStamps
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

    def __init__(  # pylint: disable=too-many-arguments  # market data set
        self,
        underlying_quantity: float = 0.0,
        spot_price: float = 100.0,
        volatility: float = 0.2,
        risk_free_rate: float = 0.05,
        dividend_yield: float = 0.0,
        valuation_date: dt | None = None,
        symbol: str = "UNKNOWN",
        default_exercise_style: ExerciseStyle | None = None,
        contract_size: int = 100,
        stamps: MarketParameterStamps | None = None,
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
            default_exercise_style: Default exercise style for positions added
                via add_position() when their own exercise_style argument is
                omitted. When None, add_position() raises ValueError if a
                style cannot be resolved from the per-call argument.  Callers
                should set this from ``ips_config.pricing.exercise_style``
                before adding positions (e.g. in setup_dashboard).
            contract_size: Number of underlying units per contract; used as
                the default for positions added via add_position()
            stamps: When each hand-entered book-level pricing input
                (spot, risk-free rate, dividend yield) was last confirmed
                — see ``deltadewa.portfolio.stamps.MarketParameterStamps``
                (#367). Defaults to an all-``None`` stamp set, matching an
                as-yet-unconfirmed book; callers restoring a serialized
                portfolio should pass the stored stamps rather than
                letting a fresh set be assumed.

        """
        self.positions: list[OptionPosition] = []
        self.underlying_quantity = underlying_quantity
        self.spot_price = spot_price
        self.volatility = volatility
        self.risk_free_rate = risk_free_rate
        self.dividend_yield = dividend_yield
        # The program's trading date, not the server's instant: midnight in
        # the program timezone, so the book prices the same all day and the
        # day rolls with the market rather than with UTC (#182).
        self.valuation_date = valuation_date or program_trading_date()
        self.symbol = symbol
        self.default_exercise_style = default_exercise_style
        self.contract_size = contract_size
        self.stamps = stamps if stamps is not None else MarketParameterStamps()
        self._monte_carlo_results: dict[str, Any] | None = None

        # Monte Carlo staleness tracking
        self.monte_carlo_stale: bool = False
        self.monte_carlo_timestamp: dt | None = None
        self.monte_carlo_last_modified: dt | None = None

    def add_position(  # pylint: disable=too-many-arguments
        self,
        strike_price: float,
        maturity_date: dt,
        quantity: int,
        option_type: OptionType = OptionType.CALL,
        contract_size: int | None = None,
        volatility: float | None = None,
        exercise_style: ExerciseStyle | None = None,
        entry_spot: float | None = None,
        entry_date: dt | None = None,
        entry_premium: float | None = None,
        volatility_as_of: dt | None = None,
        *,
        reject_expired: bool = True,
    ) -> OptionPosition:
        """Add an option position to the portfolio.

        Args:
            strike_price: Strike price of the option
            maturity_date: Maturity date of the option
            quantity: Number of contracts
            option_type: OptionType.CALL or OptionType.PUT
            contract_size: Number of underlying units per contract.  When
                ``None`` (the default) the position inherits
                ``self.contract_size``.  Pass an explicit value only when a
                specific position needs a different multiplier.
            volatility: Optional position-specific volatility (uses portfolio
                default if None)
            exercise_style: ExerciseStyle.AMERICAN or ExerciseStyle.EUROPEAN
                (uses self.default_exercise_style if None)
            entry_spot: Spot price at entry (uses self.spot_price if None)
            entry_date: Date of entry (uses self.valuation_date if None)
            entry_premium: Per-share option price paid at entry, or None if
                unknown. Used as the cost basis for monetization/gain
                calculations; a position with no recorded entry_premium
                reports its gain basis as "unknown" rather than "paid".
            volatility_as_of: When this leg's effective volatility (custom
                or inherited) was last confirmed. Defaults to
                ``program_now()`` — a live caller adding a position is
                confirming its inputs at that instant. A restore path
                (``persistence.py``'s importers) should overwrite this on
                the returned position directly with the serialized value,
                the same way it already does for ``entry_spot``/
                ``entry_date``, rather than accepting this default.
            reject_expired: When ``True`` (the default), raise
                ``ValueError`` rather than add a position whose
                ``maturity_date`` is already at or before
                ``self.valuation_date`` (#365) — refuse at typing time
                so a fat-fingered maturity year can't quietly enter the
                book as a leg with zero remaining runway. A restore path
                (``persistence.py``'s importers) passes ``False``: a real
                historical or autosaved book can legitimately hold a leg
                that expired after being added, and refusing the whole
                file over one leg is the wrong failure mode there — see
                :func:`~deltadewa.analysis.crash_repricing.is_expired`.

        Returns:
            The newly created and appended OptionPosition.

        Raises:
            ValueError: *exercise_style* cannot be resolved, or
                *reject_expired* is ``True`` and *maturity_date* is
                already expired as of ``self.valuation_date``.

        """
        effective_cs = (
            contract_size if contract_size is not None else self.contract_size
        )

        # Use position-specific volatility or portfolio default
        if volatility is not None:
            option_volatility = volatility
        else:
            option_volatility = self.volatility

        custom_volatility = volatility is not None

        if exercise_style is None:
            if self.default_exercise_style is None:
                raise ValueError(
                    "exercise_style cannot be resolved: neither the "
                    "add_position() argument nor the portfolio's "
                    "default_exercise_style is set. Pass exercise_style= "
                    "explicitly, or set portfolio.default_exercise_style "
                    "from ips_config.pricing.exercise_style before calling "
                    "add_position()."
                )
            exercise_style = self.default_exercise_style

        if entry_spot is None:
            entry_spot = self.spot_price
        if entry_date is None:
            entry_date = self.valuation_date
        if volatility_as_of is None:
            volatility_as_of = program_now()

        option = OptionValuation(
            spot_price=self.spot_price,
            strike_price=strike_price,
            maturity_date=maturity_date,
            volatility=option_volatility,
            risk_free_rate=self.risk_free_rate,
            dividend_yield=self.dividend_yield,
            exercise_style=exercise_style,
            option_type=option_type,
            valuation_date=self.valuation_date,
            grid_resolution=FDGridResolution.STANDARD,
        )
        position = OptionPosition(
            option,
            quantity,
            exercise_style=exercise_style,
            contract_size=effective_cs,
            custom_volatility=custom_volatility,
            entry_spot=entry_spot,
            entry_date=entry_date,
            entry_premium=entry_premium,
            volatility_as_of=volatility_as_of,
        )
        # Local import: analysis/crash_repricing.py sits above this module
        # in the package (deltadewa.analysis.__init__ imports
        # deltadewa.analysis.cache, which imports OptionPortfolio) — a
        # module-level import here would be circular. See #365.
        # pylint: disable-next=import-outside-toplevel
        from deltadewa.analysis.crash_repricing import is_expired

        if reject_expired and is_expired(
            position,
            valuation_date=self.valuation_date,
        ):
            raise ValueError(
                f"maturity {maturity_date.date()} is at or before the "
                f"book's valuation date {self.valuation_date.date()} — "
                "refusing to add an already-expired position",
            )
        self.positions.append(position)
        return position

    def set_volatility(
        self,
        volatility: float,
        *,
        stamp_as_of: dt | None = None,
    ) -> None:
        """Set portfolio volatility.

        Update positions without custom volatility.

        Args:
            volatility: The new book-level volatility.
            stamp_as_of: When this change is deemed confirmed, for
                ``volatility_as_of`` on every affected position. Defaults
                to ``program_now()``. Only applied when *volatility*
                actually differs from the current value — a no-op call
                (e.g. re-saving an unchanged book) must not refresh a
                stamp, or every stale input would be laundered fresh the
                next time the file happens to round-trip (#367).

        """
        if volatility == self.volatility:
            return
        effective_stamp = (
            stamp_as_of if stamp_as_of is not None else program_now()
        )
        self.volatility = volatility
        for pos in self.positions:
            if not pos.custom_volatility:
                # Route through update_volatility() so the QuantLib quote and
                # the greek cache are updated, not just the Python attribute.
                pos.option.update_volatility(volatility)
                pos.volatility_as_of = effective_stamp

    def set_underlying_quantity(self, underlying_quantity: float) -> None:
        """Set the underlying notional position being hedged."""
        self.underlying_quantity = underlying_quantity

    def get_symbol(self) -> str:
        """Get the symbol of the portfolio."""
        return self.symbol

    @property
    def monte_carlo_results(self) -> dict[str, Any] | None:
        """Monte Carlo simulation results if available.

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
    ) -> dict[str, Any]:
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

    def get_positions(self) -> list[dict[str, Any]]:
        """Return positions as plain dicts, suitable for a UI layer.

        Note:
            No caller since #279 retired the Jupyter position editor. Kept
            as a tested, general-purpose accessor.

        """
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

    def update_position(  # pylint: disable=too-many-arguments
        self,
        index: int,
        quantity: int | None = None,
        strike: float | None = None,
        expiry: dt | None = None,
        option_type: OptionType | None = None,
        contract_size: int | None = None,
        volatility: float | None = None,
        exercise_style: ExerciseStyle | None = None,
        *,
        stamp_as_of: dt | None = None,
    ) -> None:
        """Update a position's properties by index.

        Args:
            index: Index of the position to update.
            quantity: New quantity, if changing.
            strike: New strike price, if changing.
            expiry: New maturity date, if changing.
            option_type: New option type, if changing.
            contract_size: New contract size, if changing.
            volatility: New per-leg volatility, if changing. Passing a
                value marks the position custom and stamps
                ``volatility_as_of`` (#367) — a human just confirmed this
                leg's volatility.
            exercise_style: New exercise style, if changing.
            stamp_as_of: When the volatility change (if any) is deemed
                confirmed. Defaults to ``program_now()``. Ignored when
                *volatility* is ``None``.

        """
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
            if volatility != pos.option.volatility:
                pos.volatility_as_of = (
                    stamp_as_of if stamp_as_of is not None else program_now()
                )
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

    def update_market_conditions(  # pylint: disable=too-many-arguments,too-many-branches
        self,
        spot_price: float | None = None,
        volatility: float | None = None,
        risk_free_rate: float | None = None,
        dividend_yield: float | None = None,
        valuation_date: dt | None = None,
        override_custom_volatility: bool = False,
        *,
        stamp_as_of: dt | None = None,
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
            stamp_as_of: When these changes are deemed confirmed, for
            ``self.stamps`` (spot/rate/dividend) and any affected
            position's ``volatility_as_of`` (#367). Defaults to
            ``program_now()``. Each stamp is only touched when its own
            value actually changes — a call that repeats the current
            spot, rate, or dividend yield must not refresh that stamp, or
            a save→reload cycle would launder a stale input into looking
            freshly confirmed.

        """
        effective_stamp = (
            stamp_as_of if stamp_as_of is not None else program_now()
        )

        if spot_price is not None:
            if spot_price != self.spot_price:
                self.stamps = dataclass_replace(
                    self.stamps,
                    spot_as_of=effective_stamp,
                )
            self.spot_price = spot_price
            for pos in self.positions:
                pos.option.update_spot_price(spot_price)

        if volatility is not None:
            self.volatility = volatility
            for pos in self.positions:
                # Only update if not custom volatility, or if override is
                # requested
                if override_custom_volatility or not pos.custom_volatility:
                    if volatility != pos.option.volatility:
                        pos.volatility_as_of = effective_stamp
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
                if risk_free_rate != self.risk_free_rate:
                    self.stamps = dataclass_replace(
                        self.stamps,
                        risk_free_rate_as_of=effective_stamp,
                    )
                self.risk_free_rate = risk_free_rate
            if dividend_yield is not None:
                if dividend_yield != self.dividend_yield:
                    self.stamps = dataclass_replace(
                        self.stamps,
                        dividend_yield_as_of=effective_stamp,
                    )
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
                        # Preserve cost basis and identity across the rebuild
                        entry_spot=pos.entry_spot,
                        entry_date=pos.entry_date,
                        entry_premium=pos.entry_premium,
                        position_id=pos.position_id,
                        # Preserve the volatility stamp — the rate/dividend
                        # rebuild does not touch volatility itself, so
                        # losing this here would be a silent reset to
                        # UNKNOWN for every leg on the next rate change.
                        volatility_as_of=pos.volatility_as_of,
                    ),
                )
            self.positions = new_positions

    def clear_positions(self) -> None:
        """Clear all positions from the portfolio."""
        self.positions = []

    def confirm_current_inputs(self, *, as_of: dt | None = None) -> None:
        """Stamp every hand-entered pricing input as confirmed *now*.

        Unlike ``update_market_conditions``/``set_volatility``/
        ``update_position``, this stamps unconditionally — an operator
        reviewing the book and finding every number still correct has
        nothing to *change*, but has still performed the confirmation
        #367's provenance ledger exists to record. The change-gated
        stamping those other mutators do is for the opposite case: a
        value that actually moved.

        This is deliberately the only unconditional stamp in the
        portfolio layer — ``ProgramState.mark_inputs_reviewed`` gates
        calling it behind ``confirm=True`` (#367), since it erases
        whatever staleness signal existed before.

        Args:
            as_of: When this confirmation is deemed to have happened.
                Defaults to ``program_now()``.

        """
        effective_stamp = as_of if as_of is not None else program_now()
        self.stamps = MarketParameterStamps(
            spot_as_of=effective_stamp,
            risk_free_rate_as_of=effective_stamp,
            dividend_yield_as_of=effective_stamp,
        )
        for pos in self.positions:
            pos.volatility_as_of = effective_stamp

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


# Final composed class with all mixins
class OptionPortfolio(
    GreeksMixin,
    PnLMixin,
    RiskMixin,
    MonteCarloMixin,
    OptionPortfolioBase,
):
    """Manages a portfolio of options with hedge analysis.

    Each position sets its own exercise style (or inherits
    ``default_exercise_style``) — American and European positions can
    coexist in the same portfolio. SPX positions must use
    ``ExerciseStyle.EUROPEAN``.

    This class combines all portfolio functionality through mixins:
    - Core portfolio management (OptionPortfolioBase)
    - Greek calculations (GreeksMixin)
    - P&L calculations (PnLMixin)
    - Risk analysis (RiskMixin)
    - Monte Carlo simulation (MonteCarloMixin)

    For scenario analysis, use PortfolioAnalyzer from deltadewa.analysis.
    """
