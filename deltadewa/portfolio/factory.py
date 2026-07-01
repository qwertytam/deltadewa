"""Factory functions for creating option portfolios."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from deltadewa.constants import ExerciseStyle, OptionType

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


def create_empty_portfolio(**kwargs: Any) -> OptionPortfolio:  # noqa: ANN401  # OptionPortfolio **kwargs; PEP 692 Unpack needed for proper typing
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
    )

    today = datetime.now(tz=UTC)
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


def create_default_portfolio() -> OptionPortfolio:
    """Build default market parameters and positions from inline config."""
    default_config: dict[str, Any] = {
        "market_parameters": {
            "spot_price": 100,
            "risk_free_rate": 0.0500,
            "dividend_yield": 0.0,
            "underlying_quantity": 10 * 1,
            "symbol": "SPX",
            "contract_size": 100,
        },
        "positions": [
            {
                "option_type": OptionType.PUT,
                "strike_price": 80.0,
                "maturity_days": 365,
                "volatility": 0.3,
                "quantity": 5,
                "exercise_style": ExerciseStyle.EUROPEAN,
            },
            {
                "option_type": OptionType.PUT,
                "strike_price": 50.0,
                "maturity_days": 365,
                "volatility": 0.4,
                "quantity": -5,
                "exercise_style": ExerciseStyle.EUROPEAN,
            },
        ],
    }

    portfolio = create_empty_portfolio()
    market_params = dict(default_config["market_parameters"])
    portfolio.underlying_quantity = market_params["underlying_quantity"]
    portfolio.spot_price = market_params["spot_price"]
    portfolio.volatility = market_params.get("volatility", 0)
    portfolio.risk_free_rate = market_params["risk_free_rate"]
    portfolio.dividend_yield = market_params["dividend_yield"]
    portfolio.symbol = market_params.get("symbol", "UNKNOWN")
    portfolio.contract_size = market_params["contract_size"]

    portfolio.positions.clear()

    now = datetime.now(tz=UTC)
    for pos_config in default_config["positions"]:
        if "maturity_date" in pos_config:
            # Absolute date specified
            maturity = datetime.fromisoformat(pos_config["maturity_date"])
        elif "maturity_days" in pos_config:
            # Relative days from today
            maturity = now + timedelta(days=pos_config["maturity_days"])
        else:
            continue

        portfolio.add_position(
            strike_price=pos_config["strike_price"],
            maturity_date=maturity,
            quantity=pos_config["quantity"],
            option_type=pos_config["option_type"],
            volatility=pos_config.get(
                "volatility",
                market_params.get("volatility"),
            ),
            exercise_style=pos_config.get(
                "exercise_style",
                ExerciseStyle.AMERICAN,
            ),
        )
    return portfolio
