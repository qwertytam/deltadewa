"""Typing stubs for QuantLib."""

# pylint: disable=unused-argument missing-class-docstring missing-function-docstring
# pylint: disable=invalid-name
from typing import Any

# Minimal, hand-maintained stubs for the QuantLib symbols used in this project.

class Date:
    """QuantLib Date class."""

    def __init__(self, day: int, month: int, year: int) -> None: ...

class DayCounter: ...

Actual365Fixed: DayCounter

class Settings:
    """QuantLib global settings."""

    evaluationDate: Date

    @staticmethod
    def instance() -> "Settings": ...

class Option:
    """Option types."""

    Call: int
    Put: int

class PlainVanillaPayoff:
    """Plain vanilla payoff."""

    def __init__(self, option_type: int, strike: float) -> None: ...

class AmericanExercise:
    """American exercise style."""

    def __init__(self, start: Date, end: Date) -> None: ...

class VanillaOption:
    """Vanilla option instrument."""

    def __init__(self, payoff: PlainVanillaPayoff, exercise: AmericanExercise) -> None: ...
    def setPricingEngine(self, engine: Any) -> None: ...
    def NPV(self) -> float: ...
    def delta(self) -> float: ...
    def gamma(self) -> float: ...
    def vega(self) -> float: ...
    def theta(self) -> float: ...
    def rho(self) -> float: ...

class SimpleQuote:
    """A simple market quote."""

    def __init__(self, value: float) -> None: ...
    def setValue(self, value: float) -> None: ...

class QuoteHandle:
    """Handle for a quote."""

    def __init__(self, quote: SimpleQuote) -> None: ...

class YieldTermStructureHandle: ...

def FlatForward(date: Date, rate: float, daycounter: DayCounter) -> YieldTermStructureHandle: ...

class NullCalendar: ...

class BlackConstantVol:
    """Constant volatility model."""

    def __init__(self, date: Date, calendar: Any, vol: float, daycounter: DayCounter) -> None: ...

class BlackVolTermStructureHandle: ...

class BlackScholesMertonProcess:
    """Black-Scholes-Merton stochastic process."""

    def __init__(
        self,
        spot_handle: QuoteHandle,
        dividend_ts: YieldTermStructureHandle,
        flat_ts: YieldTermStructureHandle,
        flat_vol_ts: BlackVolTermStructureHandle,
    ) -> None: ...

class FdBlackScholesVanillaEngine:
    """Finite Difference engine for pricing vanilla options."""

    def __init__(
        self, process: BlackScholesMertonProcess, time_steps: int, price_steps: int
    ) -> None: ...
