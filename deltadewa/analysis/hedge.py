"""Hedge recommendations mixin for portfolio analysis."""

from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from deltadewa.portfolio import OptionPortfolio


class HedgeMixin:
    """
    Mixin for hedge recommendations.

    Provides methods for generating specific hedge recommendations
    to achieve target hedge ratios.
    """

    if TYPE_CHECKING:
        portfolio: "OptionPortfolio"

    def calculate_hedge_actions(
        self,
        target_hedge_ratio: float,
        include_option_alternatives: bool = True,
        max_alternatives: int = 10,
    ) -> Dict:
        """
        Generate specific hedge recommendations to achieve target hedge ratio.

        Args:
            target_hedge_ratio: Target hedge ratio (0-100, where 100 = fully hedged)
            include_option_alternatives: Whether to suggest option-based hedges
            max_alternatives: Maximum number of option alternatives to return

        Returns:
            Dictionary containing:
            - current_state: Current portfolio metrics
            - target_state: Target metrics
            - delta_change_needed: Delta adjustment required
            - underlying_trade: Shares to buy/sell
            - underlying_cost: Estimated cost of share trade
            - option_alternatives: List of option trades to achieve same delta (if enabled)
        """
        stats = self.portfolio.summary_stats()

        current_delta = stats["total_delta"]
        notional = stats["underlying_quantity"]
        current_ratio = stats["hedge_ratio"]
        spot_price = self.portfolio.spot_price

        # Calculate target delta
        target_delta = -notional * (target_hedge_ratio / 100.0)
        delta_change_needed = target_delta - current_delta

        # Underlying trade recommendation
        underlying_trade = {
            "action": "BUY" if delta_change_needed > 0 else "SELL",
            "shares": abs(delta_change_needed),
            "cost": abs(delta_change_needed * spot_price),
        }

        result = {
            "current_state": {
                "portfolio_delta": current_delta,
                "notional_position": notional,
                "hedge_ratio": current_ratio,
            },
            "target_state": {
                "target_hedge_ratio": target_hedge_ratio,
                "target_portfolio_delta": target_delta,
                "delta_change_needed": delta_change_needed,
            },
            "underlying_trade": underlying_trade,
            "underlying_cost": underlying_trade["cost"],
        }

        # Add option alternatives if requested
        if include_option_alternatives and abs(delta_change_needed) >= 1:
            result["option_alternatives"] = self._calculate_option_alternatives(
                delta_change_needed, max_alternatives
            )
        else:
            result["option_alternatives"] = []

        return result

    def _calculate_option_alternatives(
        self,
        delta_change_needed: float,
        max_alternatives: int,
    ) -> List[Dict]:
        """
        Calculate option-based hedge alternatives.

        Args:
            delta_change_needed: Delta adjustment required
            max_alternatives: Maximum alternatives to return

        Returns:
            List of option trade recommendations
        """
        alternatives = []

        for pos in self.portfolio.positions:
            per_contract_delta = (
                pos.position_delta() / pos.quantity if pos.quantity != 0 else 0
            )

            if abs(per_contract_delta) > 0.01:  # Only meaningful deltas
                contracts_needed = delta_change_needed / per_contract_delta
                price = pos.option.price()

                alternatives.append(
                    {
                        "action": "BUY" if contracts_needed > 0 else "SELL",
                        "type": pos.option.option_type.upper(),
                        "strike": float(pos.option.strike_price),
                        "maturity": pos.option.maturity_date.strftime(
                            "%Y-%m-%d"
                        ),
                        "delta_per_contract": float(per_contract_delta),
                        "contracts_needed": abs(contracts_needed),
                        "price": float(price),
                        "cost": abs(contracts_needed)
                        * price
                        * 100,  # Per contract
                    }
                )

        # Sort by number of contracts (prefer fewer contracts)
        alternatives.sort(key=lambda x: x["contracts_needed"])

        return alternatives[:max_alternatives]
