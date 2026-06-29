"""Convenience helpers for widget wiring.

This module contains small helper functions used by the notebook to wire
dashboard-level widgets to portfolio objects. Keep helpers lightweight and
focused on wiring/translation logic only.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from deltadewa.portfolio.core import OptionPortfolioBase
from deltadewa.widgets.assumptions import GlobalAssumptions


def link_portfolio_to_assumptions(
    portfolio: OptionPortfolioBase,
    assumptions: GlobalAssumptions,
) -> Callable[..., Any]:
    """Link a portfolio object's market fields to a GlobalAssumptions widget.

    The helper registers a callback with ``assumptions`` so that when the
    user changes any market parameter the portfolio is updated in-place and
    `update_market_conditions` is called to refresh position valuations.

    Returns a callable which can be used to unregister the callback if
    needed (currently the GlobalAssumptions API only supports registering
    additional callbacks; callers may ignore the return value).
    """

    def _on_assumptions_change(_change: object) -> None:
        # Read widget values and update portfolio
        spot = float(assumptions.spot_price.value)
        vol = float(assumptions.volatility.value)
        rfr = float(assumptions.risk_free_rate.value)
        div = float(assumptions.dividend_yield.value)

        # Valuation date widget stores a date; convert to datetime
        val_date_widget = assumptions.valuation_date.value
        if val_date_widget is None:
            valuation_date = datetime.now(tz=UTC)
        else:
            valuation_date = datetime.combine(
                val_date_widget,
                datetime.min.time(),
                tzinfo=UTC,
            )

        # Update portfolio market fields and refresh positions
        portfolio.update_market_conditions(
            spot_price=spot,
            volatility=vol,
            risk_free_rate=rfr,
            dividend_yield=div,
            valuation_date=valuation_date,
        )

    # Register and perform initial sync
    assumptions.on_change(_on_assumptions_change)

    # Perform an initial synchronization so callers don't have to trigger a
    # change
    _on_assumptions_change({})

    return _on_assumptions_change
