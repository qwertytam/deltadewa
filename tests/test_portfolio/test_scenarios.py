"""Tests for deltadewa.portfolio.scenarios module."""

from datetime import datetime, timedelta
import numpy as np
from deltadewa.portfolio import OptionPortfolio


class TestScenariosMixin:
    """Test cases for ScenariosMixin."""

    def test_scenario_analysis_spot_only(self):
        """Test scenario_analysis with spot price range only."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        spot_range = np.linspace(90, 110, 5)
        result = portfolio.scenario_analysis(spot_range)
        
        assert len(result) == 5
        assert "spot_price" in result.columns
        assert "volatility" in result.columns
        assert "portfolio_value" in result.columns
        assert "total_delta" in result.columns

    def test_scenario_analysis_grid(self):
        """Test scenario_analysis with spot and volatility grid."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        spot_range = np.linspace(90, 110, 3)
        vol_range = np.array([0.15, 0.20, 0.25])
        
        result = portfolio.scenario_analysis(spot_range, vol_range)
        
        # Should have 3 spots * 3 vols = 9 scenarios
        assert len(result) == 9
        assert "spot_price" in result.columns
        assert "volatility" in result.columns

    def test_scenario_analysis_proportional_scaling(self):
        """Test scenario_analysis with proportional volatility scaling."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        
        # Add positions with different volatilities
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
            volatility=0.25,
        )
        
        portfolio.add_position(
            strike_price=105.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
            volatility=0.20,
        )
        
        spot_range = np.linspace(95, 105, 3)
        vol_range = np.array([0.20, 0.25])
        
        result = portfolio.scenario_analysis(
            spot_range, vol_range, proportional_vol_scaling=True
        )
        
        assert len(result) == 6  # 3 spots * 2 vols
        assert "volatility" in result.columns

    def test_scenario_analysis_uniform_scaling(self):
        """Test scenario_analysis with uniform volatility scaling."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        spot_range = np.linspace(95, 105, 3)
        vol_range = np.array([0.20, 0.25])
        
        result = portfolio.scenario_analysis(
            spot_range, vol_range, proportional_vol_scaling=False
        )
        
        assert len(result) == 6

    def test_scenario_analysis_restores_state(self):
        """Test that scenario_analysis restores original portfolio state."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        original_spot = portfolio.spot_price
        original_vol = portfolio.volatility
        original_pos_vol = portfolio.positions[0].option.volatility
        
        spot_range = np.linspace(90, 110, 5)
        vol_range = np.array([0.15, 0.25])
        
        portfolio.scenario_analysis(spot_range, vol_range)
        
        # Check that state is restored
        assert portfolio.spot_price == original_spot
        assert portfolio.volatility == original_vol
        assert portfolio.positions[0].option.volatility == original_pos_vol

    def test_scenario_analysis_empty_portfolio(self):
        """Test scenario_analysis with empty portfolio."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        
        spot_range = np.linspace(90, 110, 3)
        
        result = portfolio.scenario_analysis(spot_range)
        
        assert len(result) == 3
        # All values should be 0 for empty portfolio
        assert all(result["portfolio_value"] == 0)
        assert all(result["total_delta"] == 0)

    def test_scenario_analysis_greeks(self):
        """Test that scenario_analysis includes Greek calculations."""
        portfolio = OptionPortfolio(spot_price=100.0, volatility=0.2)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        spot_range = np.linspace(95, 105, 3)
        result = portfolio.scenario_analysis(spot_range)
        
        # Check that Greeks are included
        assert "total_gamma" in result.columns
        assert "total_vega" in result.columns
        assert "net_delta" in result.columns

    def test_scenario_analysis_with_underlying(self):
        """Test scenario_analysis includes underlying position."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0, spot_price=100.0, volatility=0.2
        )
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        spot_range = np.linspace(95, 105, 3)
        result = portfolio.scenario_analysis(spot_range)
        
        # net_delta should include underlying
        assert all(result["net_delta"] != result["total_delta"])
