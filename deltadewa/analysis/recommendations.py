"""Hedge and concentration recommendations mixin for portfolio analysis."""

import numbers
from typing import TYPE_CHECKING, Any, Dict, List

import numpy as np

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolio


class RecommendationsMixin:
    """
    Mixin for hedge recommendations and risk concentration analysis.

    Provides methods for:
    - Generating specific hedge recommendations to achieve target hedge ratios
    - Identifying concentrated risk by strike and maturity
    - Analyzing which strikes/maturities contribute most to portfolio Greeks
    """

    if TYPE_CHECKING:
        portfolio: "OptionPortfolio"

        # pylint: disable=unused-argument, missing-function-docstring
        def add_maturity_buckets(self, df: Any) -> Any: ...

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
            - option_alternatives: list of option trades to achieve same delta (if enabled)
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

    def analyze_risk_concentration(
        self,
        metrics: list[str] | None = None,
        top_n: int = 3,
    ) -> Dict:
        """
        Identify concentrated risk by strike and maturity.

        Analyzes which strikes/maturities contribute most to portfolio Greeks.
        Useful for identifying over-concentration that should be diversified.

        Args:
            metrics: list of Greeks to analyze (default: ['delta', 'gamma', 'vega'])
            top_n: Number of top contributors to identify

        Returns:
            Dictionary with concentration analysis:
            - by_strike: Top strikes for each Greek
            - by_maturity: Top maturities for each Greek
            - concentration_scores: Percentage contribution of top strikes/maturities
        """
        if metrics is None:
            metrics = ["delta", "gamma", "vega"]

        df = self.portfolio.to_dataframe()
        if df.empty:
            return self._empty_concentration()

        # pylint: disable=assignment-from-no-return
        df = self.add_maturity_buckets(df)

        result: dict[str, Any] = {
            "by_strike": {},
            "by_maturity": {},
            "concentration_scores": {},
        }

        for metric in metrics:
            column = f"position_{metric}"
            if column not in df.columns:
                continue

            # Concentration by strike
            by_strike = df.groupby("strike")[column].sum().abs()
            total_abs = by_strike.sum()

            if total_abs > 0:
                top_strikes = by_strike.nlargest(top_n)

                def _safe_to_number(val):
                    # If val is a native numeric type or numpy numeric,
                    # return float; otherwise preserve original
                    if isinstance(
                        val, (int, float, np.integer, np.floating, numbers.Real)
                    ):
                        return float(val)
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        return val

                result["by_strike"][metric] = [
                    {
                        "strike": _safe_to_number(strike),
                        "value": float(value),
                        "percentage": float((value / total_abs) * 100),
                    }
                    for strike, value in top_strikes.items()
                ]

                # Concentration score (% held by top strike)
                top_pct = (
                    (top_strikes.iloc[0] / total_abs) * 100
                    if len(top_strikes) > 0
                    else 0
                )
                result["concentration_scores"][f"{metric}_strike"] = float(
                    top_pct
                )

            # Concentration by maturity
            by_maturity = df.groupby("maturity_bucket")[column].sum().abs()
            total_abs_mat = by_maturity.sum()

            if total_abs_mat > 0:
                top_maturities = by_maturity.nlargest(top_n)
                result["by_maturity"][metric] = [
                    {
                        "bucket": bucket,
                        "value": float(value),
                        "percentage": float((value / total_abs_mat) * 100),
                    }
                    for bucket, value in top_maturities.items()
                ]

                # Concentration score (% held by top bucket)
                top_pct = (
                    (top_maturities.iloc[0] / total_abs_mat) * 100
                    if len(top_maturities) > 0
                    else 0
                )
                result["concentration_scores"][f"{metric}_maturity"] = float(
                    top_pct
                )

        return result

    def _empty_concentration(self) -> Dict:
        """Return empty concentration structure."""
        return {"by_strike": {}, "by_maturity": {}, "concentration_scores": {}}
