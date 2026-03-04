"""Test different valuation styles (European vs American).

To ensure correct pricing and performance characteristics
"""

import time
import unittest
from datetime import UTC, datetime, timedelta

from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.valuation import OptionValuation


class TestValuationStyles(unittest.TestCase):
    """Test cases to compare European and American option valuations."""

    def test_european_call_parity(self) -> None:
        """European Call should be cheaper than or equal to American Call."""
        # Setup common parameters
        params = {
            "spot_price": 100,
            "strike_price": 100,
            "maturity_date": datetime.now(tz=UTC) + timedelta(days=365),
            "volatility": 0.2,
            "risk_free_rate": 0.05,
            "dividend_yield": 0.0,  # No dividends
            "valuation_date": datetime.now(tz=UTC),
        }

        # For non-dividend paying stock, American Call == European Call
        amer_call = OptionValuation(
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.AMERICAN,
            **params,  # type: ignore[arg-type]
        ).price()
        euro_call = OptionValuation(
            **params,  # type: ignore[arg-type]
            option_type=OptionType.CALL,
            exercise_style=ExerciseStyle.EUROPEAN,
        ).price()

        # Allow small numerical error from Finite Difference method
        self.assertAlmostEqual(amer_call, euro_call, places=2)

    def test_american_put_premium(self) -> None:
        """American Put should be worth MORE than European Put.

        Early Exercise Premium.
        """
        params = {
            "spot_price": 100,
            "strike_price": 100,
            "maturity_date": datetime.now(tz=UTC) + timedelta(days=365),
            "volatility": 0.2,
            # High rates increase value of early exercise for Puts
            "risk_free_rate": 0.25,
            "dividend_yield": 0.0,
            "valuation_date": datetime.now(tz=UTC),
        }

        amer_put = OptionValuation(
            **params,  # type: ignore[arg-type]
            option_type=OptionType.PUT,
            exercise_style=ExerciseStyle.AMERICAN,
        ).price()
        euro_put = OptionValuation(
            **params,  # type: ignore[arg-type]
            option_type=OptionType.PUT,
            exercise_style=ExerciseStyle.EUROPEAN,
        ).price()

        print(f"American Put: {amer_put:.4f}, European Put: {euro_put:.4f}")

        # American put MUST be more valuable due to possibility of early
        # exercise
        self.assertGreater(amer_put, euro_put)

    def test_european_speed_advantage(self) -> None:
        """Verify European engine is significantly faster."""
        params = {
            "spot_price": 100,
            "strike_price": 105,
            "maturity_date": datetime.now(tz=UTC) + timedelta(days=365),
            "volatility": 0.2,
            "risk_free_rate": 0.05,
            "dividend_yield": 0.02,
            "valuation_date": datetime.now(tz=UTC),
        }

        # Measure American (Finite Difference)
        start = time.time()
        for _ in range(10):
            OptionValuation(
                **params,  # type: ignore[arg-type]
                exercise_style=ExerciseStyle.AMERICAN,
            ).price()
        amer_time = time.time() - start

        # Measure European (Analytic)
        start = time.time()
        for _ in range(10):
            OptionValuation(
                **params,  # type: ignore[arg-type]
                exercise_style=ExerciseStyle.EUROPEAN,
            ).price()
        euro_time = time.time() - start

        print(f"American Time (10 runs): {amer_time:.4f}s")
        print(f"European Time (10 runs): {euro_time:.4f}s")

        # European should be at least 10x faster
        self.assertLess(euro_time, amer_time / 10)
