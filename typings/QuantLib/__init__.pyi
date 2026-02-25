"""Typing stubs for QuantLib.

Minimal, hand-maintained typing stubs for the QuantLib symbols used in this
project.
"""

# ruff: noqa: N802, UP037
# pylint: disable=unused-argument missing-class-docstring missing-function-docstring
# pylint: disable=invalid-name
from typing import Any

# Settings

class Settings:
    """QuantLib global settings."""

    evaluationDate: Date  # noqa: N815

    @staticmethod
    def instance() -> "Settings": ...

# Date and Calendar

class Date:
    """QuantLib Date class."""

    def __init__(self, day: int, month: int, year: int) -> None: ...

    # QuantLib supports arithmetic between Date and Period:
    #   Date + Period -> Date
    #   Date - Period -> Date
    #   Date - Date   -> Period
    def __add__(self, other: "Period") -> "Date": ...
    def __sub__(self, other: "Period" | "Date") -> "Date" | "Period": ...

class Days: ...
class DayCounter: ...

class Actual365Fixed(DayCounter):
    """Actual/365 fixed day count convention."""

    def __init__(self) -> None: ...

class NullCalendar: ...

class Calendar:
    """QuantLib calendar."""

    @staticmethod
    def from_name(name: str) -> "Calendar": ...

class UnitedStates(Calendar):
    """United States calendar."""

    NYSE: int

    def __init__(self, market: int | None = ...) -> None: ...

class Period:
    """QuantLib Period class."""

    def __init__(self, length: int, unit: Any) -> None: ...

# Options

class Option:
    """Option types."""

    Call: int
    Put: int

class PlainVanillaPayoff:
    """Plain vanilla payoff."""

    def __init__(self, option_type: int, strike: float) -> None: ...

class EuropeanExercise:
    """European exercise style."""

    def __init__(self, end: Date) -> None: ...

class AmericanExercise:
    """American exercise style."""

    def __init__(self, start: Date, end: Date) -> None: ...

class VanillaOption:
    """Vanilla option instrument."""

    def __init__(
        self,
        payoff: PlainVanillaPayoff,
        exercise: EuropeanExercise | AmericanExercise,
    ) -> None: ...
    def setPricingEngine(self, engine: Any) -> None: ...
    def NPV(self) -> float: ...
    def delta(self) -> float: ...
    def gamma(self) -> float: ...
    def vega(self) -> float: ...
    def theta(self) -> float: ...
    def rho(self) -> float: ...

# Quotes

class SimpleQuote:
    """A simple market quote."""

    def __init__(self, value: float) -> None: ...
    def setValue(self, value: float) -> None: ...

class QuoteHandle:
    """Handle for a quote."""

    def __init__(self, quote: SimpleQuote) -> None: ...

# Term structures

class BlackVolTermStructureHandle: ...
class YieldTermStructureHandle: ...

def FlatForward(
    date: Date,
    rate: float,
    daycounter: DayCounter,
) -> YieldTermStructureHandle: ...

# Models, Processes and Engines

class BlackConstantVol:
    """Constant volatility model."""

    def __init__(
        self,
        date: Date,
        calendar: Any,
        vol: float,
        daycounter: DayCounter,
    ) -> None: ...

class BlackScholesMertonProcess:
    """Black-Scholes-Merton stochastic process."""

    def __init__(
        self,
        spot_handle: QuoteHandle,
        dividend_ts: YieldTermStructureHandle,
        flat_ts: YieldTermStructureHandle,
        flat_vol_ts: BlackVolTermStructureHandle,
    ) -> None: ...

class AnalyticEuropeanEngine:
    """Finite Difference engine for pricing European options."""

    def __init__(
        self,
        process: BlackScholesMertonProcess,
    ) -> None: ...

class FdBlackScholesVanillaEngine:
    """Finite Difference engine for pricing vanilla options."""

    def __init__(
        self,
        process: BlackScholesMertonProcess,
        time_steps: int,
        price_steps: int,
    ) -> None: ...
