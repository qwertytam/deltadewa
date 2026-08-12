"""Tests for deltadewa.app.shape_notice — the shared shape-notice text.

Pure unit tests, no Dash/Playwright needed — same shape as
``tests/test_app/test_bands.py``. The classification itself (what counts as
conforming) is ``analysis.portfolio_shape``'s own concern and is covered by
``tests/test_analysis/test_portfolio_shape.py``; these tests only cover the
formatting/gating this module adds on top.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from deltadewa.app.shape_notice import shape_notice_text
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio

_EXPIRY = datetime.now(tz=UTC) + timedelta(days=90)


def _make_portfolio(*, underlying_quantity: float = 0.0) -> OptionPortfolio:
    """Build a bare portfolio with no positions."""
    return OptionPortfolio(
        spot_price=5000.0,
        underlying_quantity=underlying_quantity,
        volatility=0.20,
        risk_free_rate=0.04,
        dividend_yield=0.015,
        default_exercise_style=ExerciseStyle.EUROPEAN,
        contract_size=100,
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


class TestConformingIsQuiet:
    """A conforming book gets no notice text at all."""

    def test_protective_put_returns_none(self) -> None:
        p = _make_portfolio(underlying_quantity=100.0)
        _add_put(p, 5)

        assert shape_notice_text(p) is None


class TestEmptyPreLoadIsQuiet:
    """An unloaded book doesn't warn about a book nobody has populated."""

    def test_bare_portfolio_returns_none(self) -> None:
        p = _make_portfolio(underlying_quantity=0.0)

        assert shape_notice_text(p) is None


class TestNonConformingWarns:
    """A non-empty, non-conforming book gets the prefixed notice text."""

    def test_no_underlying_names_the_reason(self) -> None:
        p = _make_portfolio(underlying_quantity=0.0)
        _add_put(p, 5)

        text = shape_notice_text(p)

        assert text is not None
        assert text.startswith("⚠ Portfolio shape:")
        assert "No underlying position to protect" in text

    def test_no_long_puts_names_the_reason(self) -> None:
        p = _make_portfolio(underlying_quantity=100.0)

        text = shape_notice_text(p)

        assert text is not None
        assert "No long puts" in text

    def test_underlying_only_no_positions_is_not_empty_pre_load(self) -> None:
        """Underlying alone with no options is a real (non-conforming) book.

        Distinct from the bare-portfolio case: the has-book gate only
        suppresses the notice when *both* legs are absent.
        """
        p = _make_portfolio(underlying_quantity=100.0)

        text = shape_notice_text(p)

        assert text is not None

    def test_neither_leg_but_a_short_call_is_not_empty_pre_load(self) -> None:
        """A short-only book has a position, so the has-book gate lets it
        through even though it satisfies neither structural condition.
        """
        p = _make_portfolio(underlying_quantity=0.0)
        _add_call(p, -5)

        text = shape_notice_text(p)

        assert text is not None
        assert "isn't a downside-protection structure" in text
