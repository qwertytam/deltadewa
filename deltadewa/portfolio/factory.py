"""Factory functions for creating option portfolios."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from deltadewa.clock import program_trading_date
from deltadewa.constants import ExerciseStyle, OptionType

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


def create_empty_portfolio(**kwargs: Any) -> OptionPortfolio:  # ruff: ignore[any-type]  # OptionPortfolio **kwargs; PEP 692 Unpack needed for proper typing
    """Create and return an empty `OptionPortfolio` with sensible defaults.

    Args:
        **kwargs: Any `OptionPortfolio` constructor kwargs (spot_price,
        volatility, etc.)

    Returns:
        OptionPortfolio: empty portfolio instance

    Example:
        p = create_empty_portfolio(spot_price=150.0, volatility=0.25)

    """
    # Import here to avoid circular imports
    # pylint: disable=import-outside-toplevel
    from deltadewa.portfolio.core import OptionPortfolio

    return OptionPortfolio(**kwargs)


def create_demo_portfolio() -> OptionPortfolio:
    """Create and return a small demo `OptionPortfolio`.

    Pre-populated with example positions. Useful for notebook demos and initial
    UI setup.

    Returns:
        OptionPortfolio: portfolio with a couple of example positions

    """
    # Import here to avoid circular imports
    # pylint: disable=import-outside-toplevel
    from deltadewa.portfolio.core import OptionPortfolio

    p = OptionPortfolio(
        underlying_quantity=0,
        spot_price=100.0,
        volatility=0.25,
        symbol="DEMO",
        default_exercise_style=ExerciseStyle.EUROPEAN,
    )

    today = program_trading_date()
    # Short-dated call
    p.add_position(
        strike_price=100.0,
        maturity_date=today + timedelta(days=30),
        quantity=1,
        option_type=OptionType.CALL,
    )

    # Protective put
    p.add_position(
        strike_price=95.0,
        maturity_date=today + timedelta(days=60),
        quantity=1,
        option_type=OptionType.PUT,
    )

    return p
