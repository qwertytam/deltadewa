"""The portfolio-shape notice: quiet unless the book is non-conforming.

Presentation-only wrapper over
``analysis.portfolio_shape.classify_portfolio_shape``, same category as
``app.basis_chip``/``app.bands``: no engine calls, no arithmetic — just
turning an already-computed classification into the notice text both
``/monitor`` and ``/design`` render at a fixed ``shape-notice`` id.

Restores #261: the shape guard ran once per session in both retired
notebooks (``_shape = classify_portfolio_shape(portfolio)``, commit
``73cf8da``) and silently stopped when Stage 4.3 (#263) deleted them without
a replacement. This is that replacement — one function both pages'
``render()`` call for the initial value, and ``/design``'s
``register_callbacks`` re-runs on every ``book-version`` bump, since
``/design`` can change the book's shape (add/remove a position) without a
re-import (RUNBOOK §6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deltadewa.analysis.portfolio_shape import classify_portfolio_shape

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio

_NOTICE_PREFIX = "⚠ Portfolio shape:"


def shape_notice_text(portfolio: OptionPortfolio) -> str | None:
    """Return the shape-notice text, or ``None`` when there is nothing to say.

    ``None`` both when the book conforms and when it is an empty pre-load
    portfolio (no positions and no underlying) — mirroring the retired
    notebooks' own ``_has_book`` gate, so a freshly started program with
    nothing imported yet doesn't open to a warning about a book nobody has
    populated.

    Args:
        portfolio: The live portfolio to classify.

    Returns:
        ``f"{_NOTICE_PREFIX} {notice}"`` for a non-empty, non-conforming
        book; ``None`` otherwise.

    """
    has_book = bool(portfolio.positions) or portfolio.underlying_quantity != 0
    if not has_book:
        return None
    shape = classify_portfolio_shape(portfolio)
    if shape.is_conforming:
        return None
    return f"{_NOTICE_PREFIX} {shape.notice}"
