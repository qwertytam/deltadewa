"""American option pricing using QuantLib with Bjerksund-Stensland model."""

import datetime
from datetime import datetime as dt

import QuantLib as QtLib  # type: ignore[import-untyped]

from deltadewa import constants as const
from deltadewa.constants import ExerciseStyle, FDGridResolution, OptionType
from deltadewa.greeks_cache import GreeksCache


class OptionValuation:
    """Option pricing engine.

    Supports both American (Finite Difference) and European (Analytic
    Black-Scholes) exercise styles. This class provides pricing and Greeks
    calculation for options.

    Performance Note:
        Spot price and volatility updates use QuantLib's SimpleQuote mechanism
        for efficient repricing without rebuilding the entire calculation
        environment. Only date or rate changes trigger a full rebuild.
    """

    # Numerical differentiation parameters
    _SPOT_BUMP = 0.01  # Bump size for delta/gamma calculation
    _VOL_BUMP = 0.01  # Bump size for vega calculation

    def __init__(
        self,
        spot_price: float,
        strike_price: float,
        maturity_date: dt,
        volatility: float,
        risk_free_rate: float,
        dividend_yield: float,
        option_type: OptionType = OptionType.CALL,
        valuation_date: dt | None = None,
        exercise_style: ExerciseStyle = ExerciseStyle.AMERICAN,
        grid_resolution: FDGridResolution = FDGridResolution.STANDARD,
    ) -> None:
        """Initialize option.

        Args:
            spot_price: Current price of the underlying asset
            strike_price: Strike price of the option
            maturity_date: Expiration date of the option
            volatility: Implied volatility (annualized)
            risk_free_rate: Risk-free interest rate (annualized)
            dividend_yield: Dividend yield (annualized)
            option_type: OptionType.CALL or OptionType.PUT
            valuation_date: Date for valuation (defaults to today)
            exercise_style: ExerciseStyle.AMERICAN or ExerciseStyle.EUROPEAN
            grid_resolution: FDGridResolution for finite difference engine
            (ignored for European options)

        """
        self.spot_price = float(spot_price)
        self.strike_price = float(strike_price)
        self.maturity_date = maturity_date
        self.volatility = float(volatility)
        self.risk_free_rate = float(risk_free_rate)
        self.dividend_yield = float(dividend_yield)
        self.option_type = option_type
        self.valuation_date = valuation_date or dt.now(tz=datetime.UTC)
        self.exercise_style = exercise_style
        self._time_steps = grid_resolution.value
        self._price_steps = grid_resolution.value

        # Initialize Greeks cache
        self._greeks_cache = GreeksCache()

        # Set up QuantLib objects
        self._setup_quantlib()

        # Register Greek computation functions
        self._register_greeks()

    def _is_expired_or_at_expiry(self) -> bool:
        """Check if option is at or past expiry."""
        return self.valuation_date.date() >= self.maturity_date.date()

    def _setup_quantlib(self) -> None:
        """Set up QuantLib calculation environment."""
        # 1. Calendar & Dates (Same as before)
        calendar = QtLib.UnitedStates(QtLib.UnitedStates.NYSE)
        day_count = QtLib.Actual365Fixed()

        # Convert dates to QuantLib dates
        self.ql_valuation_date = QtLib.Date(
            self.valuation_date.day,
            self.valuation_date.month,
            self.valuation_date.year,
        )
        self.ql_maturity_date = QtLib.Date(
            self.maturity_date.day,
            self.maturity_date.month,
            self.maturity_date.year,
        )

        QtLib.Settings.instance().evaluationDate = self.ql_valuation_date

        # 2. Market Data Handles (Same as before - strictly minimal handles)
        self.spot_quote = QtLib.SimpleQuote(self.spot_price)
        self.spot_handle = QtLib.QuoteHandle(self.spot_quote)
        self.flat_ts = QtLib.YieldTermStructureHandle(
            QtLib.FlatForward(  # type: ignore[assignment]
                self.ql_valuation_date,
                self.risk_free_rate,
                day_count,
            ),
        )
        self.dividend_ts = QtLib.YieldTermStructureHandle(
            QtLib.FlatForward(  # type: ignore[assignment]
                self.ql_valuation_date,
                self.dividend_yield,
                day_count,
            ),
        )

        self.vol_quote = QtLib.SimpleQuote(self.volatility)
        self.vol_handle = QtLib.QuoteHandle(self.vol_quote)
        self.flat_vol_ts = QtLib.BlackVolTermStructureHandle(
            QtLib.BlackConstantVol(  # type: ignore[assignment]
                self.ql_valuation_date,
                calendar,
                self.vol_handle,  # type: ignore[assignment]
                day_count,
            ),
        )

        # 3. Process
        bsm_process = QtLib.BlackScholesMertonProcess(
            self.spot_handle,
            self.dividend_ts,
            self.flat_ts,
            self.flat_vol_ts,
        )

        # 4. Payoff
        ql_option_type = (
            QtLib.Option.Call
            if self.option_type == OptionType.CALL
            else QtLib.Option.Put
        )
        payoff = QtLib.PlainVanillaPayoff(ql_option_type, self.strike_price)

        # 5. Exercise & Engine Selection
        # Use the ExerciseStyle enum to decide which engine to use.
        if self.exercise_style == ExerciseStyle.EUROPEAN:
            # Fast Analytic Formula for European options
            exercise = QtLib.EuropeanExercise(self.ql_maturity_date)
            self.option = QtLib.VanillaOption(payoff, exercise)
            self.option.setPricingEngine(
                QtLib.AnalyticEuropeanEngine(bsm_process),
            )
        else:
            # Finite Difference Grid for American-style (or other) options
            exercise = QtLib.AmericanExercise(
                self.ql_valuation_date,
                self.ql_maturity_date,
            )
            self.option = QtLib.VanillaOption(payoff, exercise)
            self.option.setPricingEngine(
                QtLib.FdBlackScholesVanillaEngine(
                    bsm_process,
                    self._time_steps,
                    self._price_steps,
                ),
            )

        # If cache exists, just invalidate it since Greeks are already
        # registered in __init__
        if hasattr(self, "_greeks_cache"):
            self._invalidate_greeks_cache()

    def _register_greeks(self) -> None:
        """Register Greek computation functions with the cache."""
        self._greeks_cache.register("price", self._compute_price)
        self._greeks_cache.register("delta", self._compute_delta)
        self._greeks_cache.register("gamma", self._compute_gamma)
        self._greeks_cache.register("vega", self._compute_vega)
        self._greeks_cache.register("theta", self._compute_theta)
        self._greeks_cache.register("rho", self._compute_rho)

    def _invalidate_greeks_cache(self) -> None:
        """Invalidate all cached Greeks."""
        self._greeks_cache.invalidate_all()

    def _compute_price(self) -> float:
        """Compute option price."""
        if self._is_expired_or_at_expiry():
            return self.intrinsic_value()
        return self.option.NPV()

    def _compute_delta(self) -> float:
        """Compute option delta."""
        # At or past expiry, delta is 1.0 if in-the-money, 0.0 otherwise
        if self._is_expired_or_at_expiry():
            if self.option_type == OptionType.CALL:
                return 1.0 if self.spot_price > self.strike_price else 0.0
            else:
                return -1.0 if self.spot_price < self.strike_price else 0.0
        try:
            return self.option.delta()
        except RuntimeError:
            # If delta not available, compute numerically
            h = self._SPOT_BUMP
            original_spot = self.spot_price
            up_spot = max(original_spot + h, 1e-8)
            down_spot = max(original_spot - h, 1e-8)
            # Directly set quote value without invalidating cache
            self.spot_quote.setValue(up_spot)
            price_up = self.option.NPV()
            self.spot_quote.setValue(down_spot)
            price_down = self.option.NPV()
            self.spot_quote.setValue(original_spot)
            return (price_up - price_down) / (up_spot - down_spot)

    def _compute_gamma(self) -> float:
        """Compute option gamma."""
        # At or past expiry, gamma is zero (no curvature)
        if self._is_expired_or_at_expiry():
            return 0.0
        try:
            return self.option.gamma()
        except RuntimeError:
            # If gamma not available, compute numerically
            h = self._SPOT_BUMP
            original_spot = self.spot_price
            up_spot = max(original_spot + h, 1e-8)
            down_spot = max(original_spot - h, 1e-8)
            # Directly set quote value without invalidating cache
            self.spot_quote.setValue(up_spot)
            delta_up = self._compute_delta()
            self.spot_quote.setValue(down_spot)
            delta_down = self._compute_delta()
            self.spot_quote.setValue(original_spot)
            return (delta_up - delta_down) / (up_spot - down_spot)

    def _compute_vega(self) -> float:
        """Compute option vega."""
        # At or past expiry, vega is zero (no time value)
        if self._is_expired_or_at_expiry():
            return 0.0
        try:
            return self.option.vega() / 100.0  # Convert to 1% change
        except RuntimeError:
            # If vega not available, compute numerically
            h = self._VOL_BUMP
            original_vol = self.volatility
            # Directly set quote value without invalidating cache
            self.vol_quote.setValue(original_vol + h)
            price_up = self.option.NPV()
            self.vol_quote.setValue(original_vol - h)
            price_down = self.option.NPV()
            self.vol_quote.setValue(original_vol)
            return (
                price_up - price_down
            ) / 2.0  # Already in terms of 1% change

    def _compute_theta(self) -> float:
        """Compute option theta (time decay per day).

        Returns theta in dollars per calendar day. Note that the industry
        standard convention uses 365 calendar days for theta calculations,
        not 252 trading days. This matches:
        - Black-Scholes and Bjerksund-Stensland model assumptions
        - VIX and exchange conventions
        - Volatility calculations which use calendar time

        The QuantLib theta() method returns annualized theta, so we divide
        by 365 to get the daily rate.

        Returns:
            float: Theta value ($ per calendar day)

        """
        # At or past expiry, theta is zero (no time decay)
        if self._is_expired_or_at_expiry():
            return 0.0
        try:
            # QuantLib returns annualized theta, convert to per calendar day
            # Using 365 days (not 252) per industry standard
            return self.option.theta() / const.DAYS_PER_YEAR
        except RuntimeError:
            # If theta not available, compute numerically
            # Move evaluation date forward by 1 day
            current_date = QtLib.Settings.instance().evaluationDate
            QtLib.Settings.instance().evaluationDate = (
                current_date + QtLib.Period(1, QtLib.Days)  # type: ignore[operator]
            )
            price_tomorrow = self.option.NPV()
            QtLib.Settings.instance().evaluationDate = current_date
            price_today = self.option.NPV()
            return price_tomorrow - price_today

    def _compute_rho(self) -> float:
        """Compute option rho."""
        # At or past expiry, rho is zero (no time value)
        if self._is_expired_or_at_expiry():
            return 0.0
        try:
            return self.option.rho() / 100.0  # Convert to 1% change
        except RuntimeError:
            # If rho not available, compute numerically
            h = self._VOL_BUMP  # Use same bump size
            original_rate = self.risk_free_rate
            self.risk_free_rate = original_rate + h
            self._setup_quantlib()
            price_up = self.option.NPV()
            self.risk_free_rate = original_rate - h
            self._setup_quantlib()
            price_down = self.option.NPV()
            self.risk_free_rate = original_rate
            self._setup_quantlib()
            return (
                price_up - price_down
            ) / 2.0  # Already in terms of 1% change

    def price(self) -> float:
        """Calculate the option price (cached)."""
        return self._greeks_cache.get("price")

    def delta(self) -> float:
        """Calculate Delta (sensitivity to underlying price) (cached)."""
        return self._greeks_cache.get("delta")

    def gamma(self) -> float:
        """Calculate Gamma (cached)."""
        return self._greeks_cache.get("gamma")

    def vega(self) -> float:
        """Calculate Vega (sensitivity to volatility) (cached)."""
        return self._greeks_cache.get("vega")

    def theta(self) -> float:
        """Calculate Theta (time decay per day) (cached).

        Returns theta in dollars per calendar day. Note that the industry
        standard convention uses 365 calendar days for theta calculations,
        not 252 trading days. This matches:
        - Black-Scholes and Bjerksund-Stensland model assumptions
        - VIX and exchange conventions
        - Volatility calculations which use calendar time

        The QuantLib theta() method returns annualized theta, so we divide
        by 365 to get the daily rate.

        Returns:
            float: Theta value ($ per calendar day)

        """
        return self._greeks_cache.get("theta")

    def rho(self) -> float:
        """Calculate Rho (sensitivity to interest rate) (cached)."""
        return self._greeks_cache.get("rho")

    def greeks(self) -> dict:
        """Calculate all Greeks (batch computation for efficiency)."""
        return self._greeks_cache.compute_all()

    def intrinsic_value(self) -> float:
        """Calculate intrinsic value of the option."""
        if self.option_type == OptionType.CALL:
            return max(0, self.spot_price - self.strike_price)
        else:
            return max(0, self.strike_price - self.spot_price)

    def time_value(self) -> float:
        """Calculate time value of the option."""
        return self.price() - self.intrinsic_value()

    def update_spot_price(self, new_spot_price: float) -> None:
        """Update the spot price and recalculate."""
        # Ensure spot remains strictly positive for QuantLib engines
        # Cast to float to handle numpy types which QuantLib rejects
        new_spot_price = float(new_spot_price)
        safe_spot = max(new_spot_price, 1e-8)
        self.spot_price = safe_spot
        self.spot_quote.setValue(safe_spot)
        self._invalidate_greeks_cache()

    def update_volatility(self, new_volatility: float) -> None:
        """Update the volatility and recalculate.

        Uses SimpleQuote for efficient update without rebuilding QuantLib
        objects. This is significantly faster than the previous implementation
        which called _setup_quantlib() on every volatility change.

        Args:
            new_volatility: New volatility value (annualized, e.g., 0.25 for
            25%)

        """
        # Cast to float to handle numpy types which QuantLib rejects
        new_volatility = float(new_volatility)
        self.volatility = new_volatility
        if hasattr(self, "vol_quote") and self.vol_quote is not None:
            self.vol_quote.setValue(new_volatility)
        else:
            # Fallback: full rebuild if quote doesn't exist (shouldn't happen)
            self._setup_quantlib()
        self._invalidate_greeks_cache()

    def update_valuation_date(self, new_valuation_date: dt) -> None:
        """Update the valuation date and recalculate."""
        # If the requested valuation date is after maturity, clamp to maturity
        if new_valuation_date is None:
            return

        if new_valuation_date > self.maturity_date:
            # Avoid creating an AmericanExercise with earliest > latest
            # by clamping the valuation date to the maturity date.
            self.valuation_date = self.maturity_date
        else:
            self.valuation_date = new_valuation_date

        self._setup_quantlib()
        self._invalidate_greeks_cache()

    def __repr__(self) -> str:
        """Return string representation of the option."""
        return (
            f"OptionValuation(type={self.option_type}, "
            f"spot={self.spot_price:.2f}, "
            f"strike={self.strike_price:.2f}, "
            f"maturity={self.maturity_date.strftime('%Y-%m-%d')}, "
            f"price={self.price():.4f})"
        )
