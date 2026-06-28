"""Portfolio shape guard for the deltadewa hedge dashboard.

Classifies an :class:`~deltadewa.portfolio.core.OptionPortfolio` as conforming
or non-conforming to the expected downside-protection structure (long underlying
protected by long puts).  A conforming portfolio has a positive
``underlying_quantity`` and at least one position where
``option_type == PUT`` and ``quantity > 0``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from deltadewa.constants import OptionType

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


@dataclass(frozen=True)
class PortfolioShape:
    """Classification of a portfolio against the downside-protection structure.

    A conforming portfolio has a positive underlying quantity and at least one
    long put.  Non-conforming portfolios carry a machine-readable ``reason``
    and a user-facing ``notice``.

    Attributes:
        is_conforming: True when the portfolio matches the expected
            downside-protection structure (long underlying + long puts).
        has_underlying: True when ``portfolio.underlying_quantity > 0``.
        has_long_puts: True when at least one position has
            ``option_type == PUT`` and ``quantity > 0``.
        reason: Short machine-readable label for the failure mode; empty
            string when ``is_conforming`` is True.  One of
            ``"no_underlying_no_long_puts"``, ``"no_underlying"``,
            ``"no_long_puts"``, or ``""``.
        notice: User-facing message describing the structural mismatch;
            empty string when ``is_conforming`` is True.

    """

    is_conforming: bool
    has_underlying: bool
    has_long_puts: bool
    reason: str
    notice: str


def classify_portfolio_shape(portfolio: OptionPortfolio) -> PortfolioShape:
    """Classify a portfolio against the downside-protection structure.

    Checks two conditions independently and combines them:

    1. ``has_underlying``: ``portfolio.underlying_quantity > 0``
    2. ``has_long_puts``: any position where ``option_type == PUT``
       and ``quantity > 0``

    Args:
        portfolio: Live portfolio to inspect.

    Returns:
        :class:`PortfolioShape` with conforming status, component flags,
        a machine-readable ``reason``, and a user-facing ``notice``.

    """
    has_underlying: bool = portfolio.underlying_quantity > 0
    has_long_puts: bool = any(
        pos.option.option_type == OptionType.PUT and pos.quantity > 0
        for pos in portfolio.positions
    )
    is_conforming = has_underlying and has_long_puts

    if is_conforming:
        reason, notice = "", ""
    elif not has_underlying and not has_long_puts:
        reason = "no_underlying_no_long_puts"
        notice = (
            "This portfolio isn't a downside-protection structure"
            " (an underlying protected by long puts); the hedge"
            " metrics below assume one and may not be meaningful."
        )
    elif not has_underlying:
        reason = "no_underlying"
        notice = (
            "No underlying position to protect — hedge metrics"
            " assume a long underlying and may not be meaningful."
        )
    else:
        reason = "no_long_puts"
        notice = (
            "No long puts — hedge metrics assume downside protection"
            " via long puts and may not be meaningful."
        )

    return PortfolioShape(
        is_conforming=is_conforming,
        has_underlying=has_underlying,
        has_long_puts=has_long_puts,
        reason=reason,
        notice=notice,
    )
