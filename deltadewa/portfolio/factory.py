"""Factory functions for creating option portfolios."""

from datetime import UTC, datetime, timedelta

from deltadewa.constants import ExerciseStyle, OptionType


def create_empty_portfolio(**kwargs):  # noqa: ANN003 ANN201
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


def create_demo_portfolio():  # noqa: ANN201
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


def create_default_portfolio():  # noqa: ANN201
    """Build default market parameters and positions from inline config."""
    default_config = {
        "market_parameters": {
            "spot_price": 84.61,
            "risk_free_rate": 0.0400,
            "dividend_yield": 0.0,
            "underlying_quantity": 300 * 0,
            "symbol": "NFLX",
            "contract_size": 100,
        },
        "positions": [
            {
                "option_type": OptionType.CALL,
                "strike_price": 95.0,
                "maturity_days": 322,
                "volatility": 0.387,
                "quantity": 5,
                "exercise_style": ExerciseStyle.AMERICAN,
            },
            {
                "option_type": OptionType.PUT,
                "strike_price": 70.0,
                "maturity_days": 322,
                "volatility": 0.424,
                "quantity": -5,
                "exercise_style": ExerciseStyle.AMERICAN,
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
