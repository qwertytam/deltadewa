"""Risk analysis mixin for option portfolio."""

from typing import TYPE_CHECKING, Optional, List
import numpy as np

if TYPE_CHECKING:
    from deltadewa.portfolio.core import OptionPortfolioBase


class RiskMixin:
    """Mixin providing risk analysis for option portfolio."""

    def _get_spot_range(
        self: "OptionPortfolioBase",
        spot_range: Optional[np.ndarray] = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
        num_points: int = 250,
        use_comprehensive_range: bool = False,
    ) -> np.ndarray:
        """
        Get or create a spot price range for analysis.

        Args:
            spot_range: Existing spot range to use (returned as-is if provided)
            spot_min_pct: Minimum spot price as percentage of current spot (default: 0%)
            spot_max_pct: Maximum spot price as percentage of current spot (default: 200%)
            num_points: Number of points in the range (default: 250)
            use_comprehensive_range: If True, creates a comprehensive range that includes
                extreme scenarios (spot near $0, very high spot prices) with critical
                points to ensure accurate max loss/profit detection (default: False)

        Returns:
            NumPy array of spot prices for analysis
        """
        if spot_range is not None:
            return spot_range

        if use_comprehensive_range:
            # Create comprehensive range that includes extreme scenarios
            current_spot = self.spot_price

            # Near-zero value scaled appropriately for the asset price
            # Use 0.01% of current spot, but ensure minimum of 0.01
            near_zero = max(0.01, current_spot * 0.0001)

            # Critical points to always check for accurate max/min detection
            critical_points = [
                # Near zero (important for puts - can't use exact 0 due to
                # log calculations)
                near_zero,
                current_spot * 0.1,  # 90% down
                current_spot * 0.25,  # 75% down
                current_spot * 0.5,  # 50% down
                current_spot * 0.75,  # 25% down
                current_spot,  # Current spot
                current_spot * 1.25,  # 25% up
                current_spot * 1.5,  # 50% up
                current_spot * 2.0,  # 100% up
                current_spot * 3.0,  # 200% up
                current_spot * 5.0,  # 400% up
                current_spot * 10.0,  # 900% up
            ]

            # Dense range for main area - from near-zero to highest critical point
            spot_min = near_zero
            spot_max = current_spot * 10.0  # Maximum is 10x current spot
            main_range = np.linspace(spot_min, spot_max, 300)

            # Combine and sort
            spot_range = np.unique(
                np.concatenate([critical_points, main_range])
            )
            return np.sort(spot_range)
        else:
            # Standard range
            spot_min = max(0.01, self.spot_price * spot_min_pct / 100)
            spot_max = self.spot_price * spot_max_pct / 100
            return np.linspace(spot_min, spot_max, num_points)

    def _check_unlimited_trend(
        self: "OptionPortfolioBase",
        spot_range: np.ndarray,
        include_underlying: bool,
        check_increasing: bool,
    ) -> bool:
        """
        Check if P&L trend continues at the extreme end of spot range.

        This helps detect unlimited profit/loss scenarios by examining if
        the trend continues beyond the sampled range.

        Args:
            spot_range: Array of spot prices
            include_underlying: Whether to include underlying in P&L calculation
            check_increasing: If True, check for increasing trend (profit).
                            If False, check for decreasing trend (loss).

        Returns:
            True if unlimited trend is detected, False otherwise
        """
        if len(spot_range) < 10:
            return False

        # Check if P&L trend continues at the high end of range
        high_end_pnls = [
            self.calculate_pnl_at_expiry(
                spot, include_underlying=include_underlying
            )
            for spot in spot_range[-5:]
        ]

        if check_increasing:
            # Check if profits are consistently increasing
            return all(
                high_end_pnls[i] < high_end_pnls[i + 1]
                for i in range(len(high_end_pnls) - 1)
            )
        else:
            # Check if losses are consistently increasing (P&L decreasing)
            return all(
                high_end_pnls[i] > high_end_pnls[i + 1]
                for i in range(len(high_end_pnls) - 1)
            )

    def calculate_max_loss_options(
        self: "OptionPortfolioBase",
        spot_range: Optional[np.ndarray] = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> dict:
        """
        Calculate maximum loss from options positions only.

        CRITICAL: Checks extreme scenarios including spot = $0 and high spot values
        to ensure accurate max loss detection for all portfolio types.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            spot_min_pct: Minimum spot price as percentage of current spot
            (default: 0% i.e., spot = 0.0)
            spot_max_pct: Maximum spot price as percentage of current spot
            (default: 200% i.e., spot = 2x current spot)

        Returns:
            Dict with 'max_loss', 'spot_at_max_loss', and 'is_unlimited'
        """
        # Use comprehensive range to check extreme scenarios
        spot_range = self._get_spot_range(
            spot_range,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
            use_comprehensive_range=(
                spot_range is None
            ),  # Only for auto-generated ranges
        )

        max_loss = 0.0
        spot_at_max_loss = self.spot_price

        for spot in spot_range:
            pnl = self.calculate_pnl_at_expiry(spot, include_underlying=False)
            if pnl < max_loss:
                max_loss = pnl
                spot_at_max_loss = spot

        # Check for unlimited loss (naked short calls have unlimited loss potential)
        has_naked_short_calls = any(
            pos.quantity < 0 and pos.option.option_type.lower() == "call"
            for pos in self.positions
        )

        # Enhanced unlimited loss detection using helper method
        is_unlimited = has_naked_short_calls or self._check_unlimited_trend(
            spot_range, include_underlying=False, check_increasing=False
        )

        return {
            "max_loss": max_loss,
            "spot_at_max_loss": spot_at_max_loss,
            "is_unlimited": is_unlimited,
        }

    def calculate_max_profit_options(
        self: "OptionPortfolioBase",
        spot_range: Optional[np.ndarray] = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> dict:
        """
        Calculate maximum profit from options positions only.

        CRITICAL: Checks extreme scenarios including spot = $0 and high spot values
        to ensure accurate max profit detection for all portfolio types.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            spot_min_pct: Minimum spot price as percentage of current spot
            (default: 0% i.e., spot = 0.0)
            spot_max_pct: Maximum spot price as percentage of current spot
            (default: 200% i.e., spot = 2x current spot)

        Returns:
            Dict with 'max_profit', 'spot_at_max_profit', and 'is_unlimited'
        """
        # Use comprehensive range to check extreme scenarios
        spot_range = self._get_spot_range(
            spot_range,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
            use_comprehensive_range=(
                spot_range is None
            ),  # Only for auto-generated ranges
        )

        max_profit = float("-inf")
        spot_at_max_profit = self.spot_price

        for spot in spot_range:
            pnl = self.calculate_pnl_at_expiry(spot, include_underlying=False)
            if pnl > max_profit:
                max_profit = pnl
                spot_at_max_profit = spot

        # Check for unlimited profit (long calls have unlimited profit potential)
        has_long_calls = any(
            pos.quantity > 0 and pos.option.option_type.lower() == "call"
            for pos in self.positions
        )

        # Enhanced unlimited profit detection using helper method
        is_unlimited = has_long_calls or self._check_unlimited_trend(
            spot_range, include_underlying=False, check_increasing=True
        )

        return {
            "max_profit": max_profit,
            "spot_at_max_profit": spot_at_max_profit,
            "is_unlimited": is_unlimited,
        }

    def calculate_max_loss_total(
        self: "OptionPortfolioBase",
        spot_range: Optional[np.ndarray] = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> dict:
        """
        Calculate maximum loss including underlying position.

        CRITICAL: Checks extreme scenarios including spot = $0 and high spot values
        to ensure accurate max loss detection for all portfolio types.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            spot_min_pct: Minimum spot price as percentage of current spot
            (default: 0% i.e., spot = 0.0)
            spot_max_pct: Maximum spot price as percentage of current spot
            (default: 200% i.e., spot = 2x current spot)

        Returns:
            Dict with 'max_loss', 'spot_at_max_loss', and 'is_unlimited'
        """
        # Use comprehensive range to check extreme scenarios
        spot_range = self._get_spot_range(
            spot_range,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
            use_comprehensive_range=(
                spot_range is None
            ),  # Only for auto-generated ranges
        )

        max_loss = 0.0
        spot_at_max_loss = self.spot_price

        for spot in spot_range:
            pnl = self.calculate_pnl_at_expiry(spot, include_underlying=True)
            if pnl < max_loss:
                max_loss = pnl
                spot_at_max_loss = spot

        # Check if loss is potentially unlimited
        is_unlimited = False
        if self.underlying_quantity > 0:
            # Long underlying has unlimited upside, but loss capped at zero
            pass
        elif self.underlying_quantity < 0:
            # Short underlying has unlimited loss potential
            is_unlimited = True

        # Also check for naked short calls in options
        has_naked_short_calls = any(
            pos.quantity < 0 and pos.option.option_type.lower() == "call"
            for pos in self.positions
        )
        is_unlimited = is_unlimited or has_naked_short_calls

        # Enhanced unlimited loss detection using helper method
        if not is_unlimited:
            is_unlimited = self._check_unlimited_trend(
                spot_range, include_underlying=True, check_increasing=False
            )

        return {
            "max_loss": max_loss,
            "spot_at_max_loss": spot_at_max_loss,
            "is_unlimited": is_unlimited,
        }

    def calculate_max_profit_total(
        self: "OptionPortfolioBase",
        spot_range: Optional[np.ndarray] = None,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> dict:
        """
        Calculate maximum profit including underlying position.

        CRITICAL: Checks extreme scenarios including spot = $0 and high spot values
        to ensure accurate max profit detection for all portfolio types.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            spot_min_pct: Minimum spot price as percentage of current spot
            (default: 0% i.e., spot = 0.0)
            spot_max_pct: Maximum spot price as percentage of current spot
            (default: 200% i.e., spot = 2x current spot)

        Returns:
            Dict with 'max_profit', 'spot_at_max_profit', and 'is_unlimited'
        """
        # Use comprehensive range to check extreme scenarios
        spot_range = self._get_spot_range(
            spot_range,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
            use_comprehensive_range=(
                spot_range is None
            ),  # Only for auto-generated ranges
        )

        max_profit = float("-inf")
        spot_at_max_profit = self.spot_price

        for spot in spot_range:
            pnl = self.calculate_pnl_at_expiry(spot, include_underlying=True)
            if pnl > max_profit:
                max_profit = pnl
                spot_at_max_profit = spot

        # Check if profit is potentially unlimited
        is_unlimited = False
        if self.underlying_quantity > 0:
            # Long underlying has unlimited upside
            is_unlimited = True

        # Also check for long calls in options
        has_long_calls = any(
            pos.quantity > 0 and pos.option.option_type.lower() == "call"
            for pos in self.positions
        )
        is_unlimited = is_unlimited or has_long_calls

        # Enhanced unlimited profit detection using helper method
        if not is_unlimited:
            is_unlimited = self._check_unlimited_trend(
                spot_range, include_underlying=True, check_increasing=True
            )

        return {
            "max_profit": max_profit,
            "spot_at_max_profit": spot_at_max_profit,
            "is_unlimited": is_unlimited,
        }

    def calculate_breakeven_points(
        self: "OptionPortfolioBase",
        spot_range: Optional[np.ndarray] = None,
        include_underlying: bool = False,
        spot_min_pct: float = 0.0,
        spot_max_pct: float = 200.0,
    ) -> List[float]:
        """
        Calculate breakeven spot prices at expiration.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            include_underlying: Whether to include underlying position
            spot_min_pct: Minimum spot price as percentage of current spot
            (default: 0% i.e., spot = 0.0)
            spot_max_pct: Maximum spot price as percentage of current spot
            (default: 200% i.e., spot = 2x current spot)

        Returns:
            List of breakeven spot prices
        """
        spot_range = self._get_spot_range(
            spot_range,
            num_points=500,
            spot_min_pct=spot_min_pct,
            spot_max_pct=spot_max_pct,
        )

        breakeven_points = []
        prev_pnl = None

        for spot in spot_range:
            pnl = self.calculate_pnl_at_expiry(
                spot, include_underlying=include_underlying
            )

            # Check for sign change (crossing zero)
            if prev_pnl is not None:
                if (prev_pnl < 0 and pnl >= 0) or (prev_pnl > 0 and pnl <= 0):
                    # Interpolate to find more precise breakeven
                    breakeven_points.append(spot)

            prev_pnl = pnl

        return breakeven_points

    def risk_reward_analysis(
        self: "OptionPortfolioBase",
        spot_range: Optional[np.ndarray] = None,
        num_simulations: int = 10000,
    ) -> dict:
        """
        Generate comprehensive risk/reward analysis of the portfolio.

        Args:
            spot_range: Array of spot prices to analyze (optional)
            num_simulations: Number of Monte Carlo simulations for probability

        Returns:
            Dict containing all risk/reward metrics
        """
        net_debit = self.calculate_net_debit()

        # Options only analysis
        max_loss_opts = self.calculate_max_loss_options(spot_range)
        max_profit_opts = self.calculate_max_profit_options(spot_range)
        breakeven_opts = self.calculate_breakeven_points(
            spot_range, include_underlying=False
        )

        # Total portfolio analysis
        max_loss_total = self.calculate_max_loss_total(spot_range)
        max_profit_total = self.calculate_max_profit_total(spot_range)
        breakeven_total = self.calculate_breakeven_points(
            spot_range, include_underlying=True
        )

        # Probability analysis
        prob_analysis = self.calculate_probability_of_profit(
            method="monte_carlo",
            num_simulations=num_simulations,
            include_underlying=True,
        )

        return {
            "net_debit": net_debit,
            "max_loss_options": max_loss_opts,
            "max_profit_options": max_profit_opts,
            "breakeven_options": breakeven_opts,
            "max_loss_total": max_loss_total,
            "max_profit_total": max_profit_total,
            "breakeven_total": breakeven_total,
            "probability_of_profit": prob_analysis["probability"],
            "expected_value": prob_analysis["expected_value"],
        }

    def print_risk_reward_summary(
        self: "OptionPortfolioBase", spot_range: Optional[np.ndarray] = None
    ):
        """
        Print a formatted risk/reward summary of the portfolio.

        Args:
            spot_range: Array of spot prices to analyze (optional)
        """
        analysis = self.risk_reward_analysis(spot_range)
        portfolio_value = 0.0

        print("=" * 80)
        print("PORTFOLIO RISK/REWARD ANALYSIS")
        print("=" * 80)
        print()

        # Capital Requirements
        print("CAPITAL REQUIREMENTS:")
        net_debit = analysis["net_debit"]
        if net_debit > 0:
            print(
                f"  Net Debit: ${net_debit:,.2f} (capital required to implement)"
            )
        else:
            print(f"  Net Credit: ${-net_debit:,.2f} (capital received)")
        print()

        # Options Only Risk/Reward
        print("OPTIONS ONLY RISK/REWARD:")
        max_loss_opts = analysis["max_loss_options"]
        max_profit_opts = analysis["max_profit_options"]

        if max_loss_opts["is_unlimited"]:
            print("  Max Loss: UNLIMITED (naked short positions)")
        else:
            print(f"  Max Loss: ${-max_loss_opts['max_loss']:,.2f}", end="")
            if net_debit != 0:
                loss_pct = (-max_loss_opts["max_loss"] / abs(net_debit)) * 100
                print(f" ({loss_pct:.1f}% of net debit)")
            else:
                print()
            print(
                f"    └─ Occurs at spot price: ${max_loss_opts['spot_at_max_loss']:.2f}"
            )

        if max_profit_opts["is_unlimited"]:
            print("  Max Profit: UNLIMITED")
        else:
            print(
                f"  Max Profit: ${max_profit_opts['max_profit']:,.2f}", end=""
            )
            if net_debit > 0:
                roi = (max_profit_opts["max_profit"] / net_debit) * 100
                print(f" ({roi:.1f}% return on net debit)")
            else:
                print()
            print(
                f"    └─ Occurs at spot price: ${max_profit_opts['spot_at_max_profit']:.2f}"
            )

        if analysis["breakeven_options"]:
            breakevens_str = ", ".join(
                [f"${be:.2f}" for be in analysis["breakeven_options"]]
            )
            print(f"  Breakeven Points: {breakevens_str}")
        else:
            print("  Breakeven Points: None identified")
        print()

        # Total Portfolio Risk/Reward
        if self.underlying_quantity != 0:
            print("TOTAL PORTFOLIO RISK/REWARD (Options + Underlying):")
            max_loss_total = analysis["max_loss_total"]
            max_profit_total = analysis["max_profit_total"]

            if max_loss_total["is_unlimited"]:
                print("  Max Loss: UNLIMITED (short underlying position)")
            else:
                portfolio_value = self.total_portfolio_value()
                print(
                    f"  Max Loss: ${-max_loss_total['max_loss']:,.2f}", end=""
                )
                if portfolio_value > 0:
                    loss_pct = (
                        -max_loss_total["max_loss"] / portfolio_value
                    ) * 100
                    print(f" ({loss_pct:.1f}% of portfolio value)")
                else:
                    print()
                print(
                    f"    └─ Occurs at spot price: ${max_loss_total['spot_at_max_loss']:.2f}"
                )

            if max_profit_total["is_unlimited"]:
                if self.underlying_quantity > 0:
                    print("  Max Profit: UNLIMITED (long underlying position)")
                else:
                    print("  Max Profit: UNLIMITED")
                print("    └─ Profit increases with spot price")
            else:
                print(
                    f"  Max Profit: ${max_profit_total['max_profit']:,.2f}",
                    end="",
                )
                if portfolio_value > 0:
                    profit_pct = (
                        max_profit_total["max_profit"] / portfolio_value
                    ) * 100
                    print(f" ({profit_pct:.1f}% of portfolio value)")
                else:
                    print()
                print(
                    f"    └─ Occurs at spot price: ${max_profit_total['spot_at_max_profit']:.2f}"
                )

            if analysis["breakeven_total"]:
                breakevens_str = ", ".join(
                    [f"${be:.2f}" for be in analysis["breakeven_total"]]
                )
                print(f"  Breakeven Points: {breakevens_str}")
            else:
                print("  Breakeven Points: None identified")
            print()

        # Probability Analysis
        print("PROBABILITY ANALYSIS:")
        prob = analysis["probability_of_profit"]
        print(f"  Chance of Profit: {prob*100:.1f}%")
        print(
            f"  Expected Value: ${analysis['expected_value']:,.2f} (probabilistic weighted average)"
        )
        print()

        # Risk/Reward Ratio
        if (
            not max_loss_opts["is_unlimited"]
            and not max_profit_opts["is_unlimited"]
        ):
            if (
                max_profit_opts["max_profit"] > 0
                and max_loss_opts["max_loss"] < 0
            ):
                # Standard risk/reward ratio: profit potential to loss potential
                rr_ratio = (
                    max_profit_opts["max_profit"] / -max_loss_opts["max_loss"]
                )
                print(
                    f"RISK/REWARD RATIO: {rr_ratio:.2f}:1 (max profit to max loss)"
                )
        print("=" * 80)
