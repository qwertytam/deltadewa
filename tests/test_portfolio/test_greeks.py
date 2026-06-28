"""Tests for deltadewa.portfolio.greeks module."""

from datetime import UTC, datetime, timedelta

from deltadewa.constants import OptionType
from deltadewa.portfolio.core import OptionPortfolio


class TestGreeksMixin:
    """Test cases for GreeksMixin."""

    def test_total_delta(self) -> None:
        """Test total_delta calculation."""
        portfolio = OptionPortfolio(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        delta = portfolio.total_delta()
        assert isinstance(delta, float)
        # ATM call should have positive delta
        assert delta > 0

    def test_total_delta_multiple_positions(self) -> None:
        """Test total_delta with multiple positions."""
        portfolio = OptionPortfolio(spot_price=100.0)

        # Long call
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        # Short put
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.PUT,
        )

        delta = portfolio.total_delta()
        # Should be sum of both deltas
        assert isinstance(delta, float)

    def test_total_gamma(self) -> None:
        """Test total_gamma calculation."""
        portfolio = OptionPortfolio(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        gamma = portfolio.total_gamma()
        assert isinstance(gamma, float)
        assert gamma > 0

    def test_total_vega(self) -> None:
        """Test total_vega calculation."""
        portfolio = OptionPortfolio(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        vega = portfolio.total_vega()
        assert isinstance(vega, float)
        assert vega > 0

    def test_total_theta(self) -> None:
        """Test total_theta calculation."""
        portfolio = OptionPortfolio(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        theta = portfolio.total_theta()
        assert isinstance(theta, float)
        # Long options have negative theta
        assert theta < 0

    def test_total_rho(self) -> None:
        """Test total_rho calculation."""
        portfolio = OptionPortfolio(spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        rho = portfolio.total_rho()
        assert isinstance(rho, float)

    def test_net_delta(self) -> None:
        """Test net_delta calculation."""
        portfolio = OptionPortfolio(underlying_quantity=100.0, spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-2,  # Short 2 calls
            option_type=OptionType.CALL,
        )

        net_delta = portfolio.net_delta()
        # Net delta = total_delta + underlying_quantity
        expected = portfolio.total_delta() + 100.0
        assert net_delta == expected

    def test_hedge_ratio(self) -> None:
        """Test hedge_ratio calculation."""
        portfolio = OptionPortfolio(underlying_quantity=100.0, spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.CALL,
        )

        hedge_ratio = portfolio.hedge_ratio()
        assert isinstance(hedge_ratio, float)

    def test_hedge_ratio_no_underlying(self) -> None:
        """Test hedge_ratio with no underlying position."""
        portfolio = OptionPortfolio(underlying_quantity=0.0, spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        hedge_ratio = portfolio.hedge_ratio()
        assert hedge_ratio == 0.0

    def test_delta_adjustment_needed(self) -> None:
        """Test delta_adjustment_needed calculation."""
        portfolio = OptionPortfolio(underlying_quantity=100.0, spot_price=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        adjustment = portfolio.delta_adjustment_needed()
        # Should be negative of net_delta
        assert adjustment == -portfolio.net_delta()

    def test_greeks_empty_portfolio(self) -> None:
        """Test Greek calculations with empty portfolio."""
        portfolio = OptionPortfolio()

        assert portfolio.total_delta() == 0.0
        assert portfolio.total_gamma() == 0.0
        assert portfolio.total_vega() == 0.0
        assert portfolio.total_theta() == 0.0
        assert portfolio.total_rho() == 0.0
        assert portfolio.net_delta() == 0.0


class TestAllGreeksBatch:
    """Test batch Greek computation via all_greeks()."""

    def test_all_greeks_single_position(self) -> None:
        """Test all_greeks with single position."""
        portfolio = OptionPortfolio(spot_price=100.0, underlying_quantity=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        greeks = portfolio.all_greeks()

        # Verify all keys present
        assert "total_delta" in greeks
        assert "total_gamma" in greeks
        assert "total_vega" in greeks
        assert "total_theta" in greeks
        assert "total_rho" in greeks
        assert "net_delta" in greeks

        # Verify consistency with individual methods
        assert greeks["total_delta"] == portfolio.total_delta()
        assert greeks["total_gamma"] == portfolio.total_gamma()
        assert greeks["total_vega"] == portfolio.total_vega()
        assert greeks["total_theta"] == portfolio.total_theta()
        assert greeks["total_rho"] == portfolio.total_rho()
        assert greeks["net_delta"] == portfolio.net_delta()

    def test_all_greeks_multiple_positions(self) -> None:
        """Test all_greeks with multiple positions."""
        portfolio = OptionPortfolio(spot_price=100.0, underlying_quantity=50.0)

        # Long call
        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=2,
            option_type=OptionType.CALL,
        )

        # Short put
        portfolio.add_position(
            strike_price=95.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=-1,
            option_type=OptionType.PUT,
        )

        greeks = portfolio.all_greeks()

        # Verify consistency
        assert greeks["total_delta"] == portfolio.total_delta()
        assert greeks["net_delta"] == portfolio.net_delta()

        # Net delta should include underlying
        assert greeks["net_delta"] == greeks["total_delta"] + 50.0

    def test_all_greeks_empty_portfolio(self) -> None:
        """Test all_greeks with empty portfolio."""
        portfolio = OptionPortfolio(underlying_quantity=100.0)

        greeks = portfolio.all_greeks()

        assert greeks["total_delta"] == 0.0
        assert greeks["total_gamma"] == 0.0
        assert greeks["total_vega"] == 0.0
        assert greeks["total_theta"] == 0.0
        assert greeks["total_rho"] == 0.0
        assert greeks["net_delta"] == 100.0  # Only underlying

    def test_summary_stats_uses_all_greeks(self) -> None:
        """Test that summary_stats uses all_greeks for efficiency."""
        portfolio = OptionPortfolio(spot_price=100.0, underlying_quantity=100.0)

        portfolio.add_position(
            strike_price=100.0,
            maturity_date=datetime.now(tz=UTC) + timedelta(days=30),
            quantity=1,
            option_type=OptionType.CALL,
        )

        # Get summary stats (should use all_greeks internally)
        stats = portfolio.summary_stats()

        # Verify all Greek stats are present
        assert "total_delta" in stats
        assert "net_delta" in stats
        assert "total_gamma" in stats
        assert "total_vega" in stats
        assert "total_theta" in stats
        assert "total_rho" in stats
        assert "hedge_ratio" in stats
        assert "delta_adjustment" in stats

        # Verify consistency with all_greeks
        greeks = portfolio.all_greeks()
        assert stats["total_delta"] == greeks["total_delta"]
        assert stats["net_delta"] == greeks["net_delta"]
        assert stats["total_gamma"] == greeks["total_gamma"]
