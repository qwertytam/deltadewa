"""Tests for deltadewa.portfolio.scenario module."""

import pytest
import numpy as np
import pandas as pd
from unittest.mock import Mock, patch
from deltadewa.portfolio.core import OptionPortfolio


class TestScenarioMixin:
    """Test cases for scenario analysis mixin."""

    @pytest.fixture
    def portfolio(self):
        """Create a portfolio for testing."""
        return OptionPortfolio(
            underlying_quantity=100.0,
            spot_price=100.0,
            volatility=0.25,
        )

    def test_scenario_analysis_spot_only(self, portfolio):
        """Test scenario_analysis with spot range only."""
        spot_range = np.array([90, 95, 100, 105, 110])
        
        result = portfolio.scenario_analysis(spot_range)
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 5
        assert "spot_price" in result.columns
        assert "volatility" in result.columns
        assert "portfolio_value" in result.columns
        assert "total_delta" in result.columns

    def test_scenario_analysis_spot_and_vol(self, portfolio):
        """Test scenario_analysis with both spot and volatility ranges."""
        spot_range = np.array([90, 100, 110])
        vol_range = np.array([0.20, 0.25, 0.30])
        
        result = portfolio.scenario_analysis(
            spot_range, vol_range, proportional_vol_scaling=False
        )
        
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 9  # 3 spots x 3 vols
        assert "volatility" in result.columns

    def test_scenario_analysis_restores_conditions(self, portfolio):
        """Test scenario_analysis restores original market conditions."""
        original_spot = portfolio.spot_price
        original_vol = portfolio.volatility
        
        spot_range = np.array([80, 90, 100, 110, 120])
        
        portfolio.scenario_analysis(spot_range)
        
        # Should restore original conditions
        assert portfolio.spot_price == original_spot
        assert portfolio.volatility == original_vol

    @patch('deltadewa.portfolio.scenario.restore_volatilities')
    @patch('deltadewa.portfolio.scenario.apply_proportional_volatility_shift')
    @patch('deltadewa.portfolio.scenario.calculate_portfolio_avg_volatility')
    def test_scenario_analysis_proportional_scaling(
        self, mock_avg, mock_shift, mock_restore, portfolio
    ):
        """Test scenario_analysis with proportional volatility scaling."""
        mock_avg.return_value = 0.25
        
        spot_range = np.array([95, 100, 105])
        vol_range = np.array([0.20, 0.30])
        
        result = portfolio.scenario_analysis(
            spot_range, vol_range, proportional_vol_scaling=True
        )
        
        # Should call proportional volatility methods
        assert mock_shift.called
        assert mock_restore.called

    def test_scenario_analysis_includes_greeks(self, portfolio):
        """Test scenario_analysis includes Greek calculations."""
        spot_range = np.array([95, 100, 105])
        
        result = portfolio.scenario_analysis(spot_range)
        
        required_columns = [
            "spot_price",
            "volatility",
            "portfolio_value",
            "total_delta",
            "net_delta",
            "total_gamma",
            "total_vega",
        ]
        
        for col in required_columns:
            assert col in result.columns

    def test_scenario_analysis_with_positions(self, portfolio):
        """Test scenario_analysis with mock positions."""
        # Add mock position
        pos = Mock()
        pos.option.volatility = 0.25
        pos.custom_volatility = False
        portfolio.positions = [pos]
        
        spot_range = np.array([95, 100, 105])
        
        result = portfolio.scenario_analysis(spot_range)
        
        assert len(result) == 3
        assert isinstance(result, pd.DataFrame)
