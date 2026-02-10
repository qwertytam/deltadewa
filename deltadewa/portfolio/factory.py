"""Factory functions for creating option portfolios."""

from datetime import datetime, timedelta


def create_empty_portfolio(**kwargs):
    """
    Create and return an empty `OptionPortfolio` with sensible defaults.

    Args:
        **kwargs: Any `OptionPortfolio` constructor kwargs (spot_price, volatility, etc.)

    Returns:
        OptionPortfolio: empty portfolio instance

    Example:
        p = create_empty_portfolio(spot_price=150.0, volatility=0.25)
    """
    from deltadewa.portfolio.core import OptionPortfolio
    return OptionPortfolio(**kwargs)


def create_demo_portfolio():
    """
    Create and return a small demo `OptionPortfolio` pre-populated with
    example positions. Useful for notebook demos and initial UI setup.

    Returns:
        OptionPortfolio: portfolio with a couple of example positions
    """
    from deltadewa.portfolio.core import OptionPortfolio
    
    p = OptionPortfolio(
        underlying_quantity=0, spot_price=100.0, volatility=0.25
    )

    today = datetime.now()
    # Short-dated call
    p.add_position(
        strike_price=100.0,
        maturity_date=today + timedelta(days=30),
        quantity=1,
        option_type="call",
        symbol="DEMO",
    )

    # Protective put
    p.add_position(
        strike_price=95.0,
        maturity_date=today + timedelta(days=60),
        quantity=1,
        option_type="put",
        symbol="DEMO",
    )

    return p
