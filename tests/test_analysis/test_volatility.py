"""Tests for deltadewa.analysis.volatility module."""

from datetime import UTC, datetime, timedelta

import pytest

from deltadewa.analysis.volatility import (
    apply_proportional_volatility_shift,
    calculate_portfolio_avg_volatility,
    get_volatility_stats,
    restore_volatilities,
)
from deltadewa.constants import ExerciseStyle, OptionType
from deltadewa.portfolio.core import OptionPortfolio


class TestCalculatePortfolioAvgVolatility:
    """Test cases for calculate_portfolio_avg_volatility function."""

    def test_empty_portfolio_returns_portfolio_volatility(self) -> None:
        """Test that empty portfolio returns portfolio-level volatility."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
        )

        avg_vol = calculate_portfolio_avg_volatility(portfolio)
        assert avg_vol == pytest.approx(0.25, rel=1e-4)

    def test_single_position(self) -> None:
        """Test vega-weighted average with single position."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        avg_vol = calculate_portfolio_avg_volatility(portfolio)
        # With single position, average should equal position volatility
        assert avg_vol == pytest.approx(0.30, abs=0.001)

    def test_multi_position_weighted_average(self) -> None:
        """Test vega-weighted average with multiple positions."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.EUROPEAN,
        )

        # Add positions with different volatilities and vegas
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=2,
            option_type=OptionType.PUT,
            volatility=0.20,
        )

        avg_vol = calculate_portfolio_avg_volatility(portfolio)

        # Vega-weighted average should be between min and max
        assert 0.20 <= avg_vol <= 0.30

    def test_negative_position_uses_absolute_vega(self) -> None:
        """Test that negative positions use absolute vega for weighting."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # Add long and short positions with same strike/maturity
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
            volatility=0.20,
        )

        avg_vol = calculate_portfolio_avg_volatility(portfolio)

        # Both should contribute equally (abs vega), so average should be 0.25
        assert avg_vol == pytest.approx(0.25, abs=0.01)

    def test_zero_vega_positions_fallback(self) -> None:
        """Test fallback when all positions have zero vega."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        # Add deep ITM position (very low vega)
        portfolio.add_position(
            strike_price=50.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=1),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        avg_vol = calculate_portfolio_avg_volatility(portfolio)

        # Should return a reasonable value (either position vol or portfolio
        # vol)
        assert 0.20 <= avg_vol <= 0.35


class TestApplyProportionalVolatilityShift:
    """Test cases for apply_proportional_volatility_shift function."""

    def test_proportional_scaling(self) -> None:
        """Test proportional scaling maintains volatility structure."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
            volatility=0.20,
        )

        # Get original ratio
        original_ratio = (
            portfolio.positions[0].option.volatility
            / portfolio.positions[1].option.volatility
        )

        # Shift to 30% average
        original_vols = apply_proportional_volatility_shift(
            portfolio,
            0.30,
            preserve_structure=True,
        )

        # Check ratio is preserved
        new_ratio = (
            portfolio.positions[0].option.volatility
            / portfolio.positions[1].option.volatility
        )
        assert original_ratio == pytest.approx(new_ratio, abs=0.01)

        # Check original vols were stored
        assert len(original_vols) == 2
        assert 0 in original_vols
        assert 1 in original_vols

    def test_uniform_shift(self) -> None:
        """Test uniform shift sets all positions to target."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
            volatility=0.20,
        )

        # Apply uniform shift
        original_vols = apply_proportional_volatility_shift(
            portfolio,
            0.35,
            preserve_structure=False,
        )

        # All positions should now be at target
        for position in portfolio.positions:
            assert position.option.volatility == pytest.approx(0.35, abs=0.001)

        # Original vols should be stored
        assert original_vols[0] == pytest.approx(0.30, rel=1e-4)
        assert original_vols[1] == pytest.approx(0.20, rel=1e-4)

    def test_zero_avg_vol_edge_case(self) -> None:
        """Test handling when current average volatility is near zero."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.01,  # Very small but non-zero to avoid QuantLib issues
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.01,  # Very small but non-zero
        )

        # Should scale proportionally or uniformly
        original_vols = apply_proportional_volatility_shift(
            portfolio,
            0.30,
            preserve_structure=True,
        )

        # Position should now be at or near target (scaled from 0.01 to 0.30)
        assert (
            portfolio.positions[0].option.volatility > 0.20
        )  # Should be scaled up
        assert original_vols[0] == pytest.approx(0.01, rel=1e-4)

    def test_returns_original_volatilities_dict(self) -> None:
        """Test that function returns dict of original volatilities."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        original_vols = apply_proportional_volatility_shift(
            portfolio,
            0.35,
            preserve_structure=True,
        )

        # Check return value structure
        assert isinstance(original_vols, dict)
        assert 0 in original_vols
        assert original_vols[0] == pytest.approx(0.30, rel=1e-4)


class TestRestoreVolatilities:
    """Test cases for restore_volatilities function."""

    def test_basic_restore(self) -> None:
        """Test basic restoration of volatilities."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
            volatility=0.20,
        )

        # Store original
        original_vol_0 = portfolio.positions[0].option.volatility
        original_vol_1 = portfolio.positions[1].option.volatility

        # Apply shift
        original_vols = apply_proportional_volatility_shift(
            portfolio,
            0.35,
            preserve_structure=False,
        )

        # Verify changed
        assert portfolio.positions[0].option.volatility != original_vol_0
        assert portfolio.positions[1].option.volatility != original_vol_1

        # Restore
        restore_volatilities(portfolio, original_vols)

        # Verify restored
        assert (
            abs(portfolio.positions[0].option.volatility - original_vol_0)
            < 0.001
        )
        assert (
            abs(portfolio.positions[1].option.volatility - original_vol_1)
            < 0.001
        )

    def test_partial_restore_missing_indices(self) -> None:
        """Test restore handles missing position indices gracefully."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        # Create a dict with out-of-bounds index
        original_vols = {0: 0.30, 5: 0.20}

        # Should not crash, should restore position 0 and skip 5
        restore_volatilities(portfolio, original_vols)

        assert portfolio.positions[0].option.volatility == pytest.approx(
            0.30, abs=0.001
        )

    def test_empty_restore_dict(self) -> None:
        """Test restore with empty dict does nothing."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        original_vol = portfolio.positions[0].option.volatility

        # Restore with empty dict
        restore_volatilities(portfolio, {})

        # Volatility should be unchanged
        assert portfolio.positions[0].option.volatility == original_vol


class TestGetVolatilityStats:
    """Test cases for get_volatility_stats function."""

    def test_empty_portfolio_returns_empty_dict(self) -> None:
        """Test that empty portfolio returns empty dict."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
        )

        stats = get_volatility_stats(portfolio)
        assert not stats

    def test_populated_portfolio_has_expected_keys(self) -> None:
        """Test that stats dict has all expected keys."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        stats = get_volatility_stats(portfolio)

        # Check all expected keys exist
        expected_keys = {
            "avg_volatility",
            "min_volatility",
            "max_volatility",
            "std_volatility",
            "num_positions",
            "num_custom_vol",
            "portfolio_volatility",
            "volatility_range",
        }
        assert set(stats.keys()) == expected_keys

    def test_single_position_stats(self) -> None:
        """Test stats with single position."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        stats = get_volatility_stats(portfolio)

        assert stats["num_positions"] == 1
        assert stats["num_custom_vol"] == 1
        assert stats["min_volatility"] == pytest.approx(0.30, abs=0.001)
        assert stats["max_volatility"] == pytest.approx(0.30, abs=0.001)
        assert abs(stats["volatility_range"]) < 0.001
        assert stats["std_volatility"] == pytest.approx(0.0, rel=1e-4)
        assert stats["portfolio_volatility"] == pytest.approx(0.25, abs=0.001)

    def test_multiple_positions_stats(self) -> None:
        """Test stats with multiple positions."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.PUT,
            volatility=0.20,
        )

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        stats = get_volatility_stats(portfolio)

        assert stats["num_positions"] == 3
        assert stats["num_custom_vol"] == 2  # Two positions with custom vol
        assert stats["min_volatility"] == pytest.approx(0.20, abs=0.001)
        assert stats["max_volatility"] == pytest.approx(0.30, abs=0.001)
        assert stats["volatility_range"] == pytest.approx(0.10, abs=0.001)
        assert stats["std_volatility"] > 0  # Should have some variation
        assert stats["portfolio_volatility"] == pytest.approx(0.25, abs=0.001)

    def test_avg_volatility_is_vega_weighted(self) -> None:
        """Test that avg_volatility uses vega weighting."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
            default_exercise_style=ExerciseStyle.AMERICAN,
        )

        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
            volatility=0.30,
        )

        stats = get_volatility_stats(portfolio)

        # avg_volatility should call calculate_portfolio_avg_volatility
        manual_avg = calculate_portfolio_avg_volatility(portfolio)
        assert stats["avg_volatility"] == pytest.approx(manual_avg, abs=0.001)
