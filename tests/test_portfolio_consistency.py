"""Unit tests for portfolio consistency and integrity."""

from datetime import UTC, datetime, timedelta

from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio

# ruff: noqa: S101


class TestPortfolioConsistency:
    """Tests for portfolio logic and data integrity."""

    def test_portfolio_initialization_sets_symbol(self) -> None:
        """Verify portfolio has a symbol on init."""
        portfolio = OptionPortfolio(symbol="SPX", spot_price=4000)
        assert portfolio.symbol == "SPX"

    def test_add_position_inherits_symbol(self) -> None:
        """Verify adding a position automatically inherits portfolio symbol."""
        portfolio = OptionPortfolio(symbol="TSLA", spot_price=200)

        # We don't pass symbol here, it should be auto-assigned
        portfolio.add_position(
            strike_price=210,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            option_type=OptionType.CALL,
            quantity=1,
        )

        assert portfolio.symbol == "TSLA"
