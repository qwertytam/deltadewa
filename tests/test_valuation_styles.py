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
        """Verify the analytic European engine is faster than American FD.

        The finite-difference American engine solves a PDE grid, so it does
        strictly more work per price than the closed-form European engine.
        Timings are tiny, so warm each engine up once (to absorb QuantLib's
        one-time setup) and average over many iterations, keeping the
        wall-clock comparison above timer noise. A fixed speed-up multiple is
        unreliable at sub-millisecond scale, so assert only the hardware-
        independent invariant that the analytic engine is quicker.
        """
        params = {
            "spot_price": 100,
            "strike_price": 105,
            "maturity_date": datetime.now(tz=UTC) + timedelta(days=365),
            "volatility": 0.2,
            "risk_free_rate": 0.05,
            "dividend_yield": 0.02,
            "valuation_date": datetime.now(tz=UTC),
        }
        iterations = 200

        def _time_engine(style: ExerciseStyle) -> float:
            # Warm up once so QuantLib's one-time setup is not timed.
            OptionValuation(
                **params,  # type: ignore[arg-type]
                exercise_style=style,
            ).price()
            start = time.perf_counter()
            for _ in range(iterations):
                OptionValuation(
                    **params,  # type: ignore[arg-type]
                    exercise_style=style,
                ).price()
            return time.perf_counter() - start

        amer_time = _time_engine(ExerciseStyle.AMERICAN)
        euro_time = _time_engine(ExerciseStyle.EUROPEAN)

        print(f"American Time ({iterations} runs): {amer_time:.4f}s")
        print(f"European Time ({iterations} runs): {euro_time:.4f}s")

        self.assertLess(euro_time, amer_time)
