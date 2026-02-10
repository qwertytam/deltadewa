"""Tests for deltadewa.portfolio.greeks module."""

from datetime import datetime, timedelta
from deltadewa.portfolio import OptionPortfolio


class TestGreeksMixin:
    """Test cases for GreeksMixin."""

    def test_total_delta(self):
        """Test total_delta calculation."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        delta = portfolio.total_delta()
        assert isinstance(delta, float)
        # ATM call should have positive delta
        assert delta > 0

    def test_total_delta_multiple_positions(self):
        """Test total_delta with multiple positions."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        # Long call
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        # Short put
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="put",
        )
        
        delta = portfolio.total_delta()
        # Should be sum of both deltas
        assert isinstance(delta, float)

    def test_total_gamma(self):
        """Test total_gamma calculation."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        gamma = portfolio.total_gamma()
        assert isinstance(gamma, float)
        assert gamma > 0

    def test_total_vega(self):
        """Test total_vega calculation."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        vega = portfolio.total_vega()
        assert isinstance(vega, float)
        assert vega > 0

    def test_total_theta(self):
        """Test total_theta calculation."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        theta = portfolio.total_theta()
        assert isinstance(theta, float)
        # Long options have negative theta
        assert theta < 0

    def test_total_rho(self):
        """Test total_rho calculation."""
        portfolio = OptionPortfolio(spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        rho = portfolio.total_rho()
        assert isinstance(rho, float)

    def test_net_delta(self):
        """Test net_delta calculation."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0, spot_price=100.0
        )
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-2,  # Short 2 calls
            option_type="call",
        )
        
        net_delta = portfolio.net_delta()
        # Net delta = total_delta + underlying_quantity
        expected = portfolio.total_delta() + 100.0
        assert net_delta == expected

    def test_hedge_ratio(self):
        """Test hedge_ratio calculation."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0, spot_price=100.0
        )
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=-1,
            option_type="call",
        )
        
        hedge_ratio = portfolio.hedge_ratio()
        assert isinstance(hedge_ratio, float)

    def test_hedge_ratio_no_underlying(self):
        """Test hedge_ratio with no underlying position."""
        portfolio = OptionPortfolio(underlying_quantity=0.0, spot_price=100.0)
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        hedge_ratio = portfolio.hedge_ratio()
        assert hedge_ratio == 0.0

    def test_delta_adjustment_needed(self):
        """Test delta_adjustment_needed calculation."""
        portfolio = OptionPortfolio(
            underlying_quantity=100.0, spot_price=100.0
        )
        
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now() + timedelta(days=30),
            quantity=1,
            option_type="call",
        )
        
        adjustment = portfolio.delta_adjustment_needed()
        # Should be negative of net_delta
        assert adjustment == -portfolio.net_delta()

    def test_greeks_empty_portfolio(self):
        """Test Greek calculations with empty portfolio."""
        portfolio = OptionPortfolio()
        
        assert portfolio.total_delta() == 0.0
        assert portfolio.total_gamma() == 0.0
        assert portfolio.total_vega() == 0.0
        assert portfolio.total_theta() == 0.0
        assert portfolio.total_rho() == 0.0
        assert portfolio.net_delta() == 0.0
