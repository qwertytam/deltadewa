"""Tests for deltadewa.analysis.portfolio_shape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis.portfolio_shape import (
    PortfolioShape,
    classify_portfolio_shape,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio

_EXPIRY = datetime.now(tz=UTC) + timedelta(days=90)


def _make_portfolio(
    *,
    spot: float = 5000.0,
    underlying_quantity: float = 100.0,
    vol: float = 0.20,
    rate: float = 0.04,
    div: float = 0.015,
    exercise_style: ExerciseStyle = ExerciseStyle.EUROPEAN,
    contract_size: int = 100,
) -> OptionPortfolio:
    """Build a bare portfolio with no positions."""
    return OptionPortfolio(
        spot_price=spot,
        underlying_quantity=underlying_quantity,
        volatility=vol,
        risk_free_rate=rate,
        dividend_yield=div,
        default_exercise_style=exercise_style,
        contract_size=contract_size,
    )


def _add_put(portfolio: OptionPortfolio, quantity: int) -> None:
    portfolio.add_position(
        strike_price=4500.0,
        maturity_date=_EXPIRY,
        quantity=quantity,
        option_type=OptionType.PUT,
    )


def _add_call(portfolio: OptionPortfolio, quantity: int) -> None:
    portfolio.add_position(
        strike_price=5500.0,
        maturity_date=_EXPIRY,
        quantity=quantity,
        option_type=OptionType.CALL,
    )


# ---------------------------------------------------------------------------
# Conforming
# ---------------------------------------------------------------------------


class TestConforming:
    """Portfolios that match the downside-protection structure."""

    def test_long_underlying_long_put(self) -> None:
        """Protective put — the canonical conforming case."""
        p = _make_portfolio(underlying_quantity=100.0)
        _add_put(p, 5)
        result = classify_portfolio_shape(p)
        assert result.is_conforming is True
        assert result.has_underlying is True
        assert result.has_long_puts is True
        assert result.reason == ""
        assert result.notice == ""

    def test_collar_long_put_short_call(self) -> None:
        """Collar (long put + short call) — still conforming."""
        p = _make_portfolio(underlying_quantity=100.0)
        _add_put(p, 5)
        _add_call(p, -5)
        result = classify_portfolio_shape(p)
        assert result.is_conforming is True

    def test_multiple_long_puts(self) -> None:
        """More than one long put — conforming."""
        p = _make_portfolio(underlying_quantity=100.0)
        _add_put(p, 5)
        _add_put(p, 3)
        result = classify_portfolio_shape(p)
        assert result.is_conforming is True


# ---------------------------------------------------------------------------
# No underlying
# ---------------------------------------------------------------------------


class TestNoUnderlying:
    """Portfolios that have long puts but no underlying."""

    def test_zero_underlying_with_long_put(self) -> None:
        """underlying_quantity == 0 is not a long underlying."""
        p = _make_portfolio(underlying_quantity=0.0)
        _add_put(p, 5)
        result = classify_portfolio_shape(p)
        assert result.is_conforming is False
        assert result.has_underlying is False
        assert result.has_long_puts is True
        assert result.reason == "no_underlying"
        assert "No underlying position to protect" in result.notice

    def test_negative_underlying_with_long_put(self) -> None:
        """Short underlying is not a long underlying."""
        p = _make_portfolio(underlying_quantity=-50.0)
        _add_put(p, 5)
        result = classify_portfolio_shape(p)
        assert result.has_underlying is False
        assert result.reason == "no_underlying"


# ---------------------------------------------------------------------------
# No long puts
# ---------------------------------------------------------------------------


class TestNoLongPuts:
    """Portfolios that have a long underlying but no long puts."""

    def test_underlying_no_positions(self) -> None:
        """Empty book — no puts at all."""
        p = _make_portfolio(underlying_quantity=100.0)
        result = classify_portfolio_shape(p)
        assert result.is_conforming is False
        assert result.has_underlying is True
        assert result.has_long_puts is False
        assert result.reason == "no_long_puts"
        assert "No long puts" in result.notice

    def test_underlying_short_puts_only(self) -> None:
        """Short puts do not satisfy the long-puts requirement."""
        p = _make_portfolio(underlying_quantity=100.0)
        _add_put(p, -5)
        result = classify_portfolio_shape(p)
        assert result.has_long_puts is False
        assert result.reason == "no_long_puts"

    def test_underlying_long_calls_only(self) -> None:
        """Long calls are not puts."""
        p = _make_portfolio(underlying_quantity=100.0)
        _add_call(p, 5)
        result = classify_portfolio_shape(p)
        assert result.has_long_puts is False
        assert result.reason == "no_long_puts"


# ---------------------------------------------------------------------------
# Neither underlying nor long puts
# ---------------------------------------------------------------------------


class TestNeitherMissing:
    """Portfolios that have neither a long underlying nor long puts."""

    def test_empty_portfolio(self) -> None:
        """Bare portfolio — no underlying, no positions."""
        p = _make_portfolio(underlying_quantity=0.0)
        result = classify_portfolio_shape(p)
        assert result.is_conforming is False
        assert result.has_underlying is False
        assert result.has_long_puts is False
        assert result.reason == "no_underlying_no_long_puts"
        assert "isn't a downside-protection structure" in result.notice

    def test_short_calls_only(self) -> None:
        """No underlying, only short calls — neither condition met."""
        p = _make_portfolio(underlying_quantity=0.0)
        _add_call(p, -5)
        result = classify_portfolio_shape(p)
        assert result.reason == "no_underlying_no_long_puts"


# ---------------------------------------------------------------------------
# Return type and immutability
# ---------------------------------------------------------------------------


class TestReturnType:
    """Structural guarantees about PortfolioShape."""

    def test_returns_portfolio_shape(self) -> None:
        """classify_portfolio_shape always returns a PortfolioShape."""
        p = _make_portfolio(underlying_quantity=0.0)
        assert isinstance(classify_portfolio_shape(p), PortfolioShape)

    def test_frozen(self) -> None:
        """PortfolioShape is immutable."""
        p = _make_portfolio(underlying_quantity=0.0)
        result = classify_portfolio_shape(p)
        with pytest.raises((AttributeError, TypeError)):
            result.is_conforming = True  # type: ignore[misc]
