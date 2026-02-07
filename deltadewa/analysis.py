# pylint: disable=too-many-lines
"""
Portfolio Analysis Module for Options Portfolios

This module provides advanced analytical utilities for options portfolio management,
including carry analysis, risk concentration, maturity classification, scenario
generation, and hedge recommendation logic.

Usage:
    from deltadewa.analysis import PortfolioAnalyzer

    analyzer = PortfolioAnalyzer(portfolio)
    carry_metrics = analyzer.calculate_carry_metrics()
    concentration = analyzer.analyze_risk_concentration()

Author: DeltaDewa Team
Date: 2026-01-12
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import hashlib
import numbers
import pandas as pd
import numpy as np
from deltadewa.american_option import AmericanOption


class PortfolioAnalyzer:
    """
    Advanced portfolio analysis utilities.

    Provides methods for:
    - Maturity bucket classification
    - Theta/carry analysis
    - Risk concentration identification
    - Hedge recommendations
    - Scenario grid generation
    """

    def __init__(self, portfolio):
        """
        Initialize analyzer with portfolio.

        Args:
            portfolio: OptionPortfolio instance to analyze
        """
        self.portfolio = portfolio

    # ========================================================================
    # Maturity Classification
    # ========================================================================

    @staticmethod
    def classify_maturity_bucket(days_to_expiry: int) -> str:
        """
        Classify option by time to expiration bucket.

        Buckets:
        - 0-7 days: Weekly options (high theta, significant gamma)
        - 8-30 days: Monthly options (moderate theta)
        - 31-60 days: 2-month options (lower theta)
        - 61-90 days: 3-month options (very low theta)
        - 90+ days: Long-term options (minimal theta)

        Args:
            days_to_expiry: Days until option expiration

        Returns:
            Bucket label string
        """
        if days_to_expiry <= 7:
            return "0-7 days (Weekly)"
        elif days_to_expiry <= 30:
            return "8-30 days (Monthly)"
        elif days_to_expiry <= 60:
            return "31-60 days (2M)"
        elif days_to_expiry <= 90:
            return "61-90 days (3M)"
        else:
            return "90+ days (Long-term)"

    def add_maturity_buckets(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add maturity bucket column to positions DataFrame.

        Args:
            df: DataFrame with 'maturity' column

        Returns:
            DataFrame with added 'maturity_bucket' and 'days_to_expiry' columns
        """
        df = df.copy()

        # Calculate days to expiry
        df["days_to_expiry"] = df["maturity"].apply(
            lambda x: (pd.to_datetime(x) - pd.Timestamp.now()).days
        )

        # Classify into buckets
        df["maturity_bucket"] = df["days_to_expiry"].apply(
            self.classify_maturity_bucket
        )

        return df

    # ========================================================================
    # Carry / Theta Analysis
    # ========================================================================

    def calculate_carry_metrics(self) -> Dict:
        """
        Analyze portfolio carry (theta decay) characteristics.

        Note: All theta calculations use the industry standard convention of
        365 calendar days (not 252 trading days). This matches:
        - Option pricing model assumptions (Black-Scholes, Bjerksund-Stensland)
        - VIX and exchange conventions
        - Volatility calculations which use calendar time in T

        Returns:
            Dict containing:
                - total_theta_daily: Daily theta across all positions
                - total_theta_weekly: Weekly theta (daily * 7 calendar days)
                - total_theta_monthly: Monthly theta (daily * 30 calendar days)
                - total_theta_annual: Annual theta (daily * 365 calendar days)
                - theta_by_bucket: Dict of theta totals per maturity bucket
                - theta_by_type: Dict of theta totals by option type
                - covered_call_theta: Theta from short calls (income)
                - long_call_theta: Theta from long calls (cost)
                - hedge_put_theta: Theta cost from long puts (protection)
                - short_put_theta: Theta from short puts (income)
                - net_carry: Net daily carry (equals total_theta_daily)
                - carry_efficiency: Theta / position value ratio by bucket
        """
        df = self.portfolio.to_dataframe()
        if df.empty:
            return self._empty_carry_metrics()

        df = self.add_maturity_buckets(df)

        # Total theta metrics
        total_theta_daily = df["position_theta"].sum()

        # Theta by bucket
        theta_by_bucket = (
            df.groupby("maturity_bucket")["position_theta"].sum().to_dict()
        )

        # Theta by type
        theta_by_type = df.groupby("type")["position_theta"].sum().to_dict()

        # Covered call analysis (short calls - earning premium)
        short_calls = df[(df["type"] == "call") & (df["quantity"] < 0)]
        covered_call_theta = (
            short_calls["position_theta"].sum() if len(short_calls) > 0 else 0.0
        )
        covered_call_premium = (
            short_calls["position_value"].sum() if len(short_calls) > 0 else 0.0
        )

        # Long call analysis (paying premium)
        long_calls = df[(df["type"] == "call") & (df["quantity"] > 0)]
        long_call_theta = (
            long_calls["position_theta"].sum() if len(long_calls) > 0 else 0.0
        )

        # Hedge put analysis (long puts - paying for downside protection)
        long_puts = df[(df["type"] == "put") & (df["quantity"] > 0)]
        hedge_put_theta = (
            long_puts["position_theta"].sum() if len(long_puts) > 0 else 0.0
        )
        hedge_put_delta = (
            long_puts["position_delta"].sum() if len(long_puts) > 0 else 0.0
        )

        # Short put analysis (short puts - earning premium)
        short_puts = df[(df["type"] == "put") & (df["quantity"] < 0)]
        short_put_theta = (
            short_puts["position_theta"].sum() if len(short_puts) > 0 else 0.0
        )

        # Net carry = total theta (they are identical for options portfolios)
        net_carry = total_theta_daily

        # Carry efficiency by bucket (annualized theta / position value)
        bucket_summary = df.groupby("maturity_bucket").agg(
            {"position_theta": "sum", "position_value": lambda x: x.abs().sum()}
        )
        bucket_summary["carry_efficiency_pct"] = (
            (
                bucket_summary["position_theta"]
                / bucket_summary["position_value"]
            )
            * 100
            * 365
        )
        carry_efficiency = bucket_summary["carry_efficiency_pct"].to_dict()

        return {
            "total_theta_daily": total_theta_daily,
            "total_theta_weekly": total_theta_daily * 7,
            "total_theta_monthly": total_theta_daily * 30,
            "total_theta_annual": total_theta_daily * 365,
            "theta_by_bucket": theta_by_bucket,
            "theta_by_type": theta_by_type,
            "covered_call_theta": covered_call_theta,
            "covered_call_premium": covered_call_premium,
            "long_call_theta": long_call_theta,
            "hedge_put_theta": hedge_put_theta,
            "hedge_put_delta": hedge_put_delta,
            "short_put_theta": short_put_theta,
            "net_carry": net_carry,
            "carry_efficiency": carry_efficiency,
            "is_positive_carry": net_carry > 0,
        }

    def _empty_carry_metrics(self) -> Dict:
        """Return empty carry metrics structure."""
        return {
            "total_theta_daily": 0.0,
            "total_theta_weekly": 0.0,
            "total_theta_monthly": 0.0,
            "total_theta_annual": 0.0,
            "theta_by_bucket": {},
            "theta_by_type": {},
            "covered_call_theta": 0.0,
            "covered_call_premium": 0.0,
            "long_call_theta": 0.0,
            "hedge_put_theta": 0.0,
            "hedge_put_delta": 0.0,
            "short_put_theta": 0.0,
            "net_carry": 0.0,
            "carry_efficiency": {},
            "is_positive_carry": False,
        }

    def create_theta_summary_table(self) -> pd.DataFrame:
        """
        Create consolidated theta/carry summary table.

        Returns a DataFrame showing theta breakdown by source (income/cost) and timeframe
        (daily, weekly, monthly, annual). This provides a clear view of where theta is
        coming from and going to in the portfolio.

        Returns:
            DataFrame with theta breakdown by source (income/cost) and timeframe,
            with multi-index (category, source) and columns for different time periods
        """
        carry_metrics = self.calculate_carry_metrics()

        data = []

        # Income sources (positive theta - earning premium)
        if carry_metrics["covered_call_theta"] != 0:
            data.append(
                {
                    "category": "Income",
                    "source": "Short Calls",
                    "daily": carry_metrics["covered_call_theta"],
                    "weekly": carry_metrics["covered_call_theta"] * 7,
                    "monthly": carry_metrics["covered_call_theta"] * 30,
                    "annual": carry_metrics["covered_call_theta"] * 365,
                }
            )

        if carry_metrics["short_put_theta"] != 0:
            data.append(
                {
                    "category": "Income",
                    "source": "Short Puts",
                    "daily": carry_metrics["short_put_theta"],
                    "weekly": carry_metrics["short_put_theta"] * 7,
                    "monthly": carry_metrics["short_put_theta"] * 30,
                    "annual": carry_metrics["short_put_theta"] * 365,
                }
            )

        # Cost sources (negative theta - paying premium)
        if carry_metrics["hedge_put_theta"] != 0:
            data.append(
                {
                    "category": "Cost",
                    "source": "Long Puts (Hedge)",
                    "daily": carry_metrics["hedge_put_theta"],
                    "weekly": carry_metrics["hedge_put_theta"] * 7,
                    "monthly": carry_metrics["hedge_put_theta"] * 30,
                    "annual": carry_metrics["hedge_put_theta"] * 365,
                }
            )

        if carry_metrics["long_call_theta"] != 0:
            data.append(
                {
                    "category": "Cost",
                    "source": "Long Calls",
                    "daily": carry_metrics["long_call_theta"],
                    "weekly": carry_metrics["long_call_theta"] * 7,
                    "monthly": carry_metrics["long_call_theta"] * 30,
                    "annual": carry_metrics["long_call_theta"] * 365,
                }
            )

        # Net total (always show, even if zero)
        data.append(
            {
                "category": "NET",
                "source": "Total Theta/Carry",
                "daily": carry_metrics["total_theta_daily"],
                "weekly": carry_metrics["total_theta_weekly"],
                "monthly": carry_metrics["total_theta_monthly"],
                "annual": carry_metrics["total_theta_annual"],
            }
        )

        df = pd.DataFrame(data)
        return df.set_index(["category", "source"])

    # ========================================================================
    # Risk Concentration
    # ========================================================================

    def analyze_risk_concentration(
        self, metrics: Optional[List[str]] = None, top_n: int = 3
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

    # ========================================================================
    # Hedge Recommendations
    # ========================================================================

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
        self, delta_change_needed: float, max_alternatives: int
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

    # ========================================================================
    # Scenario Grid Generation
    # ========================================================================

    def _calculate_portfolio_value_at(
        self, spot: float, valuation_date: datetime
    ) -> float:
        """
        Calculate total portfolio value at given spot and date.

        Args:
            spot: Spot price to use for valuation
            valuation_date: Date to use for valuation

        Returns:
            Total portfolio value (options + underlying)
        """
        total_value = 0.0

        for position in self.portfolio.positions:
            days_to_maturity = (
                position.option.maturity_date - valuation_date
            ).days

            if days_to_maturity <= 0:
                # Option expired - use intrinsic value
                if position.option.option_type == "call":
                    intrinsic = max(0, spot - position.option.strike_price)
                else:
                    intrinsic = max(0, position.option.strike_price - spot)
                total_value += (
                    intrinsic * position.quantity * position.contract_size
                )
            else:
                # Option still alive - price it
                opt = AmericanOption(
                    spot_price=spot,
                    strike_price=position.option.strike_price,
                    maturity_date=position.option.maturity_date,
                    volatility=position.option.volatility,  # Use position volatility
                    risk_free_rate=self.portfolio.risk_free_rate,
                    dividend_yield=self.portfolio.dividend_yield,
                    option_type=position.option.option_type,
                    valuation_date=valuation_date,
                )
                total_value += (
                    opt.price() * position.quantity * position.contract_size
                )

        # Add underlying position value
        total_value += self.portfolio.underlying_quantity * spot

        return total_value

    def _calculate_pnl_at_expiry_vectorized(
        self,
        spot_scenarios: np.ndarray,
        include_underlying: bool = True,
    ) -> np.ndarray:
        """
        Calculate P&L at expiry using vectorized NumPy operations.

        This method should only be used for at-expiry calculations where all
        positions have expired (days_to_maturity <= 0). At expiry, options have
        only intrinsic value and no time value, so volatility doesn't affect
        the results.

        This is much faster than iterating for large grids because:
        - Intrinsic value is element-wise max operation
        - All positions computed simultaneously across all spots
        - NumPy broadcasting handles grid expansion

        Args:
            spot_scenarios: Array of spot prices to evaluate
            include_underlying: Whether to include underlying position P&L

        Returns:
            np.ndarray of P&L values for each spot scenario
        """
        # Pre-extract position data into arrays
        strikes = np.array(
            [pos.option.strike_price for pos in self.portfolio.positions]
        )
        quantities = np.array(
            [pos.quantity for pos in self.portfolio.positions]
        )
        contract_sizes = np.array(
            [pos.contract_size for pos in self.portfolio.positions]
        )
        is_call = np.array(
            [
                pos.option.option_type.lower() == "call"
                for pos in self.portfolio.positions
            ]
        )

        # Vectorized intrinsic value calculation
        # Shape: (n_positions, 1) and (1, n_spots) -> broadcasts to (n_positions, n_spots)
        strikes_2d = strikes[:, np.newaxis]  # (n_positions, 1)
        spots_2d = spot_scenarios[np.newaxis, :]  # (1, n_spots)

        call_intrinsic = np.maximum(spots_2d - strikes_2d, 0)
        put_intrinsic = np.maximum(strikes_2d - spots_2d, 0)
        intrinsic = np.where(
            is_call[:, np.newaxis], call_intrinsic, put_intrinsic
        )

        # Apply quantity and contract size, sum across positions
        position_values = (
            intrinsic
            * quantities[:, np.newaxis]
            * contract_sizes[:, np.newaxis]
        )
        portfolio_values = position_values.sum(axis=0)

        # Add underlying if requested
        if include_underlying and self.portfolio.underlying_quantity != 0:
            underlying_pnl = self.portfolio.underlying_quantity * (
                spot_scenarios - self.portfolio.spot_price
            )
            portfolio_values += underlying_pnl

        # Calculate P&L relative to initial premium paid/received
        initial_value = self.portfolio.total_value()
        pnl = portfolio_values - initial_value

        return pnl

    def scenario_grid(
        self,
        spot_scenarios: np.ndarray,
        time_points: List[datetime],
        metric: str = "pnl",
        baseline_spot: Optional[float] = None,
        baseline_valuation_date: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Calculate portfolio metrics across 2D grid of spot prices and time.

        Useful for heatmap generation showing how portfolio evolves across
        different price levels and time horizons.

        Args:
            spot_scenarios: Array of spot prices to test
            time_points: List of valuation dates to test
            metric: Metric to calculate ('pnl', 'value', 'delta', 'net_delta',
            'gamma', 'vega', 'theta')
            baseline_spot: Spot price for P&L baseline (default: current portfolio spot)
            baseline_valuation_date: Valuation date for P&L baseline (default:
            current portfolio date)

        Returns:
            DataFrame with columns: spot_price, valuation_date, metric_value
        """

        results = []
        original_spot = self.portfolio.spot_price
        original_date = self.portfolio.valuation_date

        # For P&L calculation, use the baseline values if provided
        if baseline_spot is None:
            baseline_spot = original_spot
        if baseline_spot is None:
            raise ValueError(
                "Portfolio spot price is not set for baseline calculation."
            )

        if baseline_valuation_date is None:
            baseline_valuation_date = original_date
        if baseline_valuation_date is None:
            raise ValueError(
                "Portfolio valuation date is not set for baseline calculation."
            )

        # Calculate baseline value at baseline date/spot for P&L calculations
        baseline_value = self._calculate_portfolio_value_at(
            baseline_spot, baseline_valuation_date
        )

        for time_point in time_points:
            for spot in spot_scenarios:
                # Calculate metric at this scenario
                if metric == "pnl":
                    # Calculate P&L relative to baseline
                    scenario_value = self._calculate_portfolio_value_at(
                        spot, time_point
                    )
                    metric_value = scenario_value - baseline_value

                elif metric == "value":
                    # Calculate absolute portfolio value
                    metric_value = self._calculate_portfolio_value_at(
                        spot, time_point
                    )

                else:
                    # For Greeks, update portfolio and calculate
                    self.portfolio.update_market_conditions(
                        spot_price=spot, valuation_date=time_point
                    )

                    if metric == "delta":
                        metric_value = self.portfolio.total_delta()
                    elif metric == "net_delta":
                        metric_value = self.portfolio.net_delta()
                    elif metric == "gamma":
                        metric_value = self.portfolio.total_gamma()
                    elif metric == "vega":
                        metric_value = self.portfolio.total_vega()
                    elif metric == "theta":
                        metric_value = self.portfolio.total_theta()
                    else:
                        metric_value = 0.0

                results.append(
                    {
                        "spot_price": spot,
                        "valuation_date": time_point,
                        "days_forward": (time_point - original_date).days,
                        "metric": metric,
                        "value": metric_value,
                    }
                )

        # Restore original state
        self.portfolio.update_market_conditions(
            spot_price=original_spot, valuation_date=original_date
        )

        return pd.DataFrame(results)

    def scenario_grid_spot_vol(
        self,
        spot_scenarios: np.ndarray,
        vol_scenarios: np.ndarray,
        metric: str = "pnl",
        baseline_value: Optional[float] = None,
        proportional_vol_scaling: bool = True,
    ) -> pd.DataFrame:
        """
        Calculate portfolio metrics across 2D grid of spot prices and volatilities.

        For P&L at expiry (intrinsic value), uses vectorized calculation for
        maximum performance. For other metrics requiring repricing, uses
        iterative approach with proportional vol scaling.

        Args:
            spot_scenarios: Array of spot prices to test
            vol_scenarios: Array of volatilities to test
            metric: Metric to calculate ('pnl', 'value', 'delta', 'gamma', 'vega', 'theta')
            baseline_value: Portfolio value for P&L baseline (default: current value)
            proportional_vol_scaling: If True, scale position vols proportionally

        Returns:
            DataFrame with columns: spot_price, volatility, value
        """
        from deltadewa.utils import (
            apply_proportional_volatility_shift,
            restore_volatilities,
        )

        results = []
        original_spot = self.portfolio.spot_price
        original_vol = self.portfolio.volatility
        original_date = self.portfolio.valuation_date

        # Calculate baseline value if not provided
        if baseline_value is None:
            baseline_value = self.portfolio.total_value()

        # Store original position volatilities for restoration
        original_position_vols = {
            i: pos.option.volatility
            for i, pos in enumerate(self.portfolio.positions)
        }

        # For P&L metric, check if we can use vectorized calculation
        # (only applicable at expiry where volatility doesn't matter)
        if metric == "pnl":
            # Check if all positions are at expiry (days_to_maturity == 0)
            # We check for exactly 0 to avoid issues with historical valuations
            all_at_expiry = all(
                (pos.option.maturity_date - original_date).days == 0
                for pos in self.portfolio.positions
            )

            if all_at_expiry:
                # Use vectorized calculation for maximum speed
                # Create meshgrid of spot and vol scenarios
                spot_grid, vol_grid = np.meshgrid(spot_scenarios, vol_scenarios)

                # Calculate PnL using vectorized method (vol doesn't affect intrinsic value)
                pnl_values = self._calculate_pnl_at_expiry_vectorized(
                    spot_scenarios, include_underlying=True
                )

                # Expand to full grid
                for i, vol in enumerate(vol_scenarios):
                    for j, spot in enumerate(spot_scenarios):
                        results.append(
                            {
                                "spot_price": spot,
                                "volatility": vol,
                                "value": pnl_values[j],
                            }
                        )

                return pd.DataFrame(results)

        # For other metrics or non-expiry PnL, iterate with vol scaling
        for vol in vol_scenarios:
            # Apply proportional volatility shift
            if proportional_vol_scaling:
                apply_proportional_volatility_shift(
                    self.portfolio, vol, preserve_structure=True
                )
            else:
                # Set all positions to same volatility
                for pos in self.portfolio.positions:
                    pos.option.volatility = vol

            for spot in spot_scenarios:
                # Update market conditions
                self.portfolio.update_market_conditions(
                    spot_price=spot, valuation_date=original_date
                )

                # Calculate metric
                if metric == "pnl":
                    current_value = self.portfolio.total_value()
                    underlying_pnl = (
                        spot - original_spot
                    ) * self.portfolio.underlying_quantity
                    metric_value = (
                        current_value - baseline_value
                    ) + underlying_pnl
                elif metric == "value":
                    metric_value = self.portfolio.total_value()
                elif metric == "delta":
                    metric_value = self.portfolio.total_delta()
                elif metric == "gamma":
                    metric_value = self.portfolio.total_gamma()
                elif metric == "vega":
                    metric_value = self.portfolio.total_vega()
                elif metric == "theta":
                    metric_value = self.portfolio.total_theta()
                else:
                    raise ValueError(
                        f"Unsupported metric: {metric}. "
                        f"Supported: pnl, value, delta, gamma, vega, theta"
                    )

                results.append(
                    {
                        "spot_price": spot,
                        "volatility": vol,
                        "value": metric_value,
                    }
                )

            # Restore volatilities after each volatility level
            restore_volatilities(self.portfolio, original_position_vols)

        # Restore original portfolio state
        self.portfolio.update_market_conditions(
            spot_price=original_spot,
            volatility=original_vol,
            valuation_date=original_date,
        )

        return pd.DataFrame(results)

    # ========================================================================
    # Risk Summary Formatting
    # ========================================================================

    def format_risk_summary(self, stats: Optional[Dict] = None) -> str:
        """
        Generate formatted risk summary text.

        Args:
            stats: Portfolio summary stats (uses current if None)

        Returns:
            Formatted string with risk analysis
        """
        if stats is None:
            stats = self.portfolio.summary_stats()
        if stats is None:
            return "No portfolio data available."

        lines = []
        lines.append("=" * 70)
        lines.append("PORTFOLIO RISK SUMMARY")
        lines.append("=" * 70)
        lines.append("")

        # Delta analysis
        lines.append("DIRECTIONAL RISK (DELTA):")
        lines.append(f"  Portfolio Delta: {stats['total_delta']:,.2f}")
        lines.append(
            f"  Notional Position: {stats['underlying_quantity']:,.2f}"
        )
        lines.append(f"  Net Delta: {stats['net_delta']:,.2f}")
        lines.append(f"  Hedge Ratio: {stats['hedge_ratio']:.2f}%")

        if abs(stats["net_delta"]) < abs(stats["underlying_quantity"]) * 0.1:
            lines.append("  ✓ Well hedged (net delta < 10% of notional)")
        elif stats["net_delta"] > 0:
            lines.append("  ⚠ Net long exposure - vulnerable to price decline")
        else:
            lines.append(
                "  ⚠ Net short exposure - vulnerable to price increase"
            )

        lines.append("")

        # Gamma analysis
        lines.append("CONVEXITY RISK (GAMMA):")
        lines.append(f"  Total Gamma: {stats['total_gamma']:.4f}")
        if stats["total_gamma"] > 0:
            lines.append("  → Long gamma: Delta increases as spot rises")
        else:
            lines.append("  → Short gamma: Delta decreases as spot rises")

        lines.append("")

        # Vega analysis
        lines.append("VOLATILITY RISK (VEGA):")
        lines.append(f"  Total Vega: {stats['total_vega']:.2f}")
        if stats["total_vega"] > 0:
            lines.append("  → Long vega: Benefits from volatility increase")
        else:
            lines.append("  → Short vega: Benefits from volatility decrease")

        lines.append("")

        # Theta analysis
        lines.append("TIME DECAY (THETA):")
        lines.append(f"  Total Theta: ${stats['total_theta']:.2f}/day")
        if stats["total_theta"] > 0:
            lines.append("  → Positive theta: Earning from time decay")
        else:
            lines.append("  → Negative theta: Paying for time decay")

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)

    # ========================================================================
    # Actionable Insights
    # ========================================================================

    def generate_insights(self) -> List[str]:
        """
        Generate actionable insights based on portfolio analysis.

        Returns:
            List of insight strings
        """
        insights = []
        stats = self.portfolio.summary_stats()
        carry_metrics = self.calculate_carry_metrics()
        concentration = self.analyze_risk_concentration()

        # Delta insights
        if abs(stats["net_delta"]) > abs(stats["underlying_quantity"]) * 0.2:
            insights.append(
                f"⚠ High net delta exposure ({stats['net_delta']:.0f}) - "
                "consider rebalancing hedge"
            )

        # Theta insights
        if carry_metrics["is_positive_carry"]:
            insights.append(
                f"✓ Positive carry: Earning ${carry_metrics['total_theta_daily']:.2f}/day "
                f"(${carry_metrics['total_theta_monthly']:.0f}/month)"
            )
        else:
            insights.append(
                f"⚠ Negative carry: Paying ${-carry_metrics['total_theta_daily']:.2f}/day "
                "for options positions"
            )

        # Concentration insights
        for metric, score in concentration["concentration_scores"].items():
            if "strike" in metric and score > 30:
                insights.append(
                    f"⚠ {metric.split('_')[0].upper()} concentrated in single strike "
                    f"({score:.1f}%) - consider diversifying"
                )

        # Gamma insights
        if abs(stats["total_gamma"]) > 0.1:
            direction = "long" if stats["total_gamma"] > 0 else "short"
            insights.append(
                f"ℹ High {direction} gamma ({abs(stats['total_gamma']):.4f}) - "
                "delta will change significantly with spot moves"
            )

        # Vega insights
        if abs(stats["total_vega"]) > 100:
            direction = (
                "benefits from" if stats["total_vega"] > 0 else "hurt by"
            )
            insights.append(
                f"ℹ Significant vega exposure ({abs(stats['total_vega']):.0f}) - "
                f"portfolio {direction} volatility increases"
            )

        return insights


# ============================================================================
# Module-Level Convenience Functions
# ============================================================================


def classify_maturity_bucket(days_to_expiry: int) -> str:
    """
    Convenience function for maturity classification.

    Args:
        days_to_expiry: Days until expiration

    Returns:
        Bucket label string
    """
    return PortfolioAnalyzer.classify_maturity_bucket(days_to_expiry)


def quick_carry_analysis(portfolio) -> Dict:
    """
    Quick carry analysis for a portfolio.

    Args:
        portfolio: OptionPortfolio instance

    Returns:
        Dictionary with carry metrics
    """
    analyzer = PortfolioAnalyzer(portfolio)
    return analyzer.calculate_carry_metrics()


def quick_risk_concentration(
    portfolio, metrics: Optional[List[str]] = None
) -> Dict:
    """
    Quick risk concentration analysis.

    Args:
        portfolio: OptionPortfolio instance
        metrics: Greeks to analyze (default: ['delta', 'gamma', 'vega'])

    Returns:
        Dictionary with concentration analysis
    """
    analyzer = PortfolioAnalyzer(portfolio)
    return analyzer.analyze_risk_concentration(metrics=metrics)


# ============================================================================
# Scenario Grid Caching Utilities
# ============================================================================


def create_scenario_cache_key(
    spot_scenarios: np.ndarray,
    time_points: List[datetime],
    metric: str,
    portfolio_state_hash: str,
) -> Tuple:
    """
    Create a hashable cache key for scenario grid results.

    Args:
        spot_scenarios: Array of spot prices
        time_points: List of valuation dates
        metric: Metric being calculated
        portfolio_state_hash: Hash representing portfolio state

    Returns:
        Tuple suitable for use as dictionary key
    """
    # Convert numpy array to tuple for hashing
    spot_tuple = tuple(spot_scenarios.tolist())
    time_tuple = tuple(tp.isoformat() for tp in time_points)

    return (spot_tuple, time_tuple, metric, portfolio_state_hash)


def create_spot_vol_cache_key(
    spot_scenarios: np.ndarray,
    vol_scenarios: np.ndarray,
    metric: str,
    portfolio_state_hash: str,
) -> Tuple:
    """
    Create hashable cache key for spot × vol scenario grid results.

    Args:
        spot_scenarios: Array of spot prices
        vol_scenarios: Array of volatilities
        metric: Metric being calculated
        portfolio_state_hash: Hash representing portfolio state

    Returns:
        Tuple suitable for use as dictionary key

    Note:
        Rounds to 6 decimal places for stability. This provides precision
        to 0.000001 for typical spot prices and 0.0001% for volatilities,
        which is more than sufficient for caching purposes.
    """
    # Convert numpy arrays to tuples for hashing (rounded for stability)
    spot_tuple = tuple(np.round(spot_scenarios, 6).tolist())
    vol_tuple = tuple(np.round(vol_scenarios, 6).tolist())

    return ("spot_vol", spot_tuple, vol_tuple, metric, portfolio_state_hash)


def get_portfolio_state_hash(portfolio) -> str:
    """
    Generate a hash representing the current portfolio state.

    This is used for cache invalidation - if the portfolio changes,
    the hash changes and cached scenario grids are invalidated.

    Args:
        portfolio: OptionPortfolio instance

    Returns:
        String hash of portfolio state
    """

    # Collect all relevant state
    state_elements = [
        str(portfolio.spot_price),
        str(portfolio.volatility),
        str(portfolio.risk_free_rate),
        str(portfolio.dividend_yield),
        str(portfolio.valuation_date.isoformat()),
        str(len(portfolio.positions)),
    ]

    # Add position details
    for pos in portfolio.positions:
        state_elements.extend(
            [
                pos.symbol,
                str(pos.quantity),
                str(pos.option.strike_price),
                str(pos.option.maturity_date.isoformat()),
                pos.option.option_type,
                str(pos.option.volatility),
            ]
        )

    # Create hash
    state_str = "|".join(state_elements)
    return hashlib.md5(state_str.encode()).hexdigest()


class ScenarioGridCache:
    """
    Cache for scenario grid calculations with automatic invalidation.

    This class provides caching for expensive scenario grid calculations.
    The cache is automatically invalidated when portfolio state changes.

    Usage:
        cache = ScenarioGridCache()

        # First call calculates and caches
        result1 = cache.get_or_calculate(
            portfolio, analyzer, spot_scenarios, time_points, metric
        )

        # Second call returns cached result (if portfolio unchanged)
        result2 = cache.get_or_calculate(
            portfolio, analyzer, spot_scenarios, time_points, metric
        )
    """

    def __init__(self, max_size: int = 128):
        """
        Initialize cache.

        Args:
            max_size: Maximum number of cached results (LRU eviction)
        """
        self._cache: Dict[Tuple, pd.DataFrame] = {}
        self._max_size = max_size
        self._access_order: List[Tuple] = []

    def get_or_calculate(
        self,
        portfolio,
        analyzer: PortfolioAnalyzer,
        spot_scenarios: np.ndarray,
        time_points: List[datetime],
        metric: str,
        baseline_spot: Optional[float] = None,
        baseline_valuation_date: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        Get cached result or calculate if not available.

        Args:
            portfolio: OptionPortfolio instance
            analyzer: PortfolioAnalyzer instance
            spot_scenarios: Array of spot prices
            time_points: List of valuation dates
            metric: Metric to calculate
            baseline_spot: Baseline spot for P&L calculation
            baseline_valuation_date: Baseline date for P&L calculation

        Returns:
            DataFrame with scenario grid results
        """
        # Generate cache key
        portfolio_hash = get_portfolio_state_hash(portfolio)
        cache_key = create_scenario_cache_key(
            spot_scenarios, time_points, metric, portfolio_hash
        )

        # Check cache
        if cache_key in self._cache:
            # Update access order
            if cache_key in self._access_order:
                self._access_order.remove(cache_key)
            self._access_order.append(cache_key)
            return self._cache[cache_key].copy()

        # Calculate result
        result = analyzer.scenario_grid(
            spot_scenarios=spot_scenarios,
            time_points=time_points,
            metric=metric,
            baseline_spot=baseline_spot,
            baseline_valuation_date=baseline_valuation_date,
        )

        # Store in cache
        self._cache[cache_key] = result.copy()
        self._access_order.append(cache_key)

        # Enforce max size (LRU eviction)
        while len(self._cache) > self._max_size:
            oldest_key = self._access_order.pop(0)
            if oldest_key in self._cache:
                del self._cache[oldest_key]

        return result

    def get_or_calculate_spot_vol(
        self,
        portfolio,
        analyzer: PortfolioAnalyzer,
        spot_scenarios: np.ndarray,
        vol_scenarios: np.ndarray,
        metric: str = "pnl",
        baseline_value: Optional[float] = None,
        proportional_vol_scaling: bool = True,
    ) -> pd.DataFrame:
        """
        Get cached spot × vol result or calculate if not available.

        Uses vectorized calculation for P&L at expiry for maximum performance.

        Args:
            portfolio: OptionPortfolio instance
            analyzer: PortfolioAnalyzer instance
            spot_scenarios: Array of spot prices
            vol_scenarios: Array of volatilities
            metric: Metric to calculate
            baseline_value: Portfolio value for P&L baseline
            proportional_vol_scaling: If True, scale position vols proportionally

        Returns:
            DataFrame with scenario grid results (columns: spot_price, volatility, value)
        """
        # Generate cache key
        portfolio_hash = get_portfolio_state_hash(portfolio)
        cache_key = create_spot_vol_cache_key(
            spot_scenarios, vol_scenarios, metric, portfolio_hash
        )

        # Check cache
        if cache_key in self._cache:
            # Update access order (LRU)
            if cache_key in self._access_order:
                self._access_order.remove(cache_key)
            self._access_order.append(cache_key)
            return self._cache[cache_key].copy()

        # Calculate result
        result = analyzer.scenario_grid_spot_vol(
            spot_scenarios=spot_scenarios,
            vol_scenarios=vol_scenarios,
            metric=metric,
            baseline_value=baseline_value,
            proportional_vol_scaling=proportional_vol_scaling,
        )

        # Store in cache with LRU eviction
        self._cache[cache_key] = result.copy()
        self._access_order.append(cache_key)

        while len(self._cache) > self._max_size:
            oldest_key = self._access_order.pop(0)
            if oldest_key in self._cache:
                del self._cache[oldest_key]

        return result

    def clear(self):
        """Clear all cached results."""
        self._cache.clear()
        self._access_order.clear()

    def size(self) -> int:
        """Return number of cached results."""
        return len(self._cache)
