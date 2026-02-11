"""Risk concentration analysis mixin for portfolio analysis."""

from typing import TYPE_CHECKING, Dict, List, Optional, Any
import numbers
import numpy as np

if TYPE_CHECKING:
    from deltadewa.portfolio import OptionPortfolio


class ConcentrationMixin:
    """
    Mixin for risk concentration analysis.

    Provides methods for identifying concentrated risk by strike and maturity,
    analyzing which strikes/maturities contribute most to portfolio Greeks.
    """

    if TYPE_CHECKING:
        portfolio: OptionPortfolio

        # pylint: disable=unused-argument, missing-function-docstring
        def add_maturity_buckets(self, df: Any) -> Any: ...

    def analyze_risk_concentration(
        self,
        metrics: Optional[List[str]] = None,
        top_n: int = 3,
    ) -> Dict:
        """
        Identify concentrated risk by strike and maturity.

        Analyzes which strikes/maturities contribute most to portfolio Greeks.
        Useful for identifying over-concentration that should be diversified.

        Args:
            metrics: List of Greeks to analyze (default: ['delta', 'gamma', 'vega'])
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

        result: Dict[str, Any] = {
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
